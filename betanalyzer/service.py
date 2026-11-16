"""Capa de servicio que combina datos online, señales y modelo."""

from __future__ import annotations

from .betting import Parlay, build_value_parlay, cash_out_advice, live_win_probability, selections_from_probabilities
from .data_source import DataSource, DataSourceError
from .model import PoissonModel
from .signals import ManualAdjustments, build_signals
from .tracker import Tracker


class BetService:
    def __init__(self):
        self.data = DataSource()
        self.model = PoissonModel()
        self.tracker = Tracker()
        self._trained = False

    def train(self, extra_teams: list[str] | None = None) -> dict:
        base_history = self.data.all_history(extra_teams=extra_teams)
        learned = self.tracker.learned_history()
        self.model.train(base_history + learned)
        self._trained = True
        return {"trained_matches": self.model.trained_matches, "learned_from_results": len(learned), "online": True}

    def _ensure_trained(self, home: str, away: str) -> None:
        if not self._trained:
            self.train(extra_teams=[home, away])

    def upcoming(self, refresh: bool = False) -> list[dict]:
        return self.data.upcoming_matches(refresh=refresh)

    def _signals(self, home: str, away: str, manual_payload: dict | None) -> dict:
        manual = ManualAdjustments.from_payload(manual_payload)
        return build_signals(
            home, away,
            self.data.team_history(home, limit=20),
            self.data.team_history(away, limit=20),
            self.data.head_to_head(home, away, limit=10),
            self.model.avg_home_goals,
            self.model.avg_away_goals,
            manual,
        )

    @staticmethod
    def _public_signals(signals: dict) -> dict:
        return {
            "home_form": signals["home_form"].to_dict(),
            "away_form": signals["away_form"].to_dict(),
            "h2h": signals["h2h"],
            "local_factor": signals["local_factor"],
            "manual": {
                "home_absences": signals["manual"].home_absences,
                "away_absences": signals["manual"].away_absences,
                "home_motivation": signals["manual"].home_motivation,
                "away_motivation": signals["manual"].away_motivation,
            },
            "breakdown": signals["breakdown"],
        }

    def analyze_match(self, home: str, away: str, save: bool = False, manual_payload: dict | None = None) -> dict:
        self._ensure_trained(home, away)
        signals = self._signals(home, away, manual_payload)
        probs = self.model.predict(home, away, modifiers=signals["modifiers"])
        selections = selections_from_probabilities(f"{home} vs {away}", probs)
        pred_id = self.tracker.save_prediction(probs, context=self._public_signals(signals)) if save else None
        return {
            "home": probs.home, "away": probs.away,
            "p_home": probs.p_home, "p_draw": probs.p_draw, "p_away": probs.p_away,
            "expected_home_goals": probs.expected_home_goals,
            "expected_away_goals": probs.expected_away_goals,
            "p_over_2_5": probs.p_over_2_5, "p_btts": probs.p_btts,
            "fair_odds": probs.fair_odds(),
            "selections": [{"market": s.market, "label": s.label, "probability": s.probability, "fair_odds": s.fair_odds} for s in selections],
            "prediction_id": pred_id, "signals": self._public_signals(signals), "_probs": probs,
        }

    def suggest_parlay(self, matches: list[dict | tuple], max_legs: int = 3) -> dict:
        all_selections = []
        for match in matches:
            if isinstance(match, dict):
                home, away, manual = match["home"].strip(), match["away"].strip(), match.get("manual") or {}
            else:
                home, away, manual = match[0], match[1], {}
            self._ensure_trained(home, away)
            signals = self._signals(home, away, manual)
            all_selections += selections_from_probabilities(f"{home} vs {away}", self.model.predict(home, away, modifiers=signals["modifiers"]))
        parlay: Parlay = build_value_parlay(all_selections, max_legs=max_legs)
        return {
            "legs": [{"match": s.match, "label": s.label, "probability": s.probability, "fair_odds": s.fair_odds} for s in parlay.selections],
            "combined_probability": parlay.combined_probability,
            "combined_fair_odds": round(1.0 / parlay.combined_probability, 2) if parlay.combined_probability > 0 else 999.0,
            "warning": f"Una combinada solo gana si aciertas TODAS las patas. Probabilidad conjunta estimada: {parlay.combined_probability*100:.1f}%.",
        }

    def cash_out(self, home: str, away: str, market: str, minute: int, home_score: int, away_score: int, stake: float, original_odds: float, offered_cashout: float | None = None, manual_payload: dict | None = None) -> dict:
        self._ensure_trained(home, away)
        signals = self._signals(home, away, manual_payload)
        probs = self.model.predict(home, away, modifiers=signals["modifiers"])
        win_prob = live_win_probability(market, minute, home_score, away_score, probs.expected_home_goals, probs.expected_away_goals)
        advice = cash_out_advice(stake, original_odds, win_prob, offered_cashout)
        return {"win_probability_now": advice.win_probability, "fair_cashout": advice.fair_cashout, "recommendation": advice.recommendation, "keep": advice.keep, "score": f"{home_score}-{away_score}", "minute": minute, "breakdown": signals["breakdown"][:2]}

    def resolve(self, pred_id: int, home_goals: int, away_goals: int) -> dict:
        self.tracker.resolve_prediction(pred_id, home_goals, away_goals)
        self._trained = False
        retrain = self.train()
        return {"resolved": pred_id, **retrain, "metrics": self.tracker.metrics()}

    def status(self) -> dict:
        return {"online": self.data.online, "data_error": self.data.last_error, "trained": self._trained, "trained_matches": self.model.trained_matches, "metrics": self.tracker.metrics()}
