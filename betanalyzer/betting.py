"""Lógica de apuestas: valor, combinadas y cash-out.

Todas las funciones son de *análisis*. No colocan apuestas ni mueven dinero.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import MatchProbabilities, poisson_pmf


@dataclass
class Selection:
    """Una selección dentro de una apuesta (p.ej. 'gana el local')."""

    match: str
    market: str
    label: str
    probability: float
    market_odds: float

    @property
    def fair_odds(self) -> float:
        return round(1.0 / self.probability, 2) if self.probability > 0 else 999.0

    @property
    def edge(self) -> float:
        return round(self.probability * self.market_odds - 1.0, 4)

    @property
    def has_value(self) -> bool:
        return self.edge > 0


def selections_from_probabilities(
    match_name: str, probs: MatchProbabilities, market_odds: dict[str, float] | None = None
) -> list[Selection]:
    fair = probs.fair_odds()
    odds = {**fair, **(market_odds or {})}
    specs = [
        ("home", f"Gana {probs.home}", probs.p_home),
        ("draw", "Empate", probs.p_draw),
        ("away", f"Gana {probs.away}", probs.p_away),
        ("over_2_5", "Más de 2.5 goles", probs.p_over_2_5),
        ("btts", "Ambos marcan", probs.p_btts),
    ]
    return [Selection(match_name, mk, label, prob, odds.get(mk, fair[mk])) for mk, label, prob in specs]


@dataclass
class Parlay:
    selections: list[Selection]

    @property
    def combined_probability(self) -> float:
        p = 1.0
        for s in self.selections:
            p *= s.probability
        return round(p, 6)

    @property
    def combined_odds(self) -> float:
        o = 1.0
        for s in self.selections:
            o *= s.market_odds
        return round(o, 2)

    @property
    def edge(self) -> float:
        return round(self.combined_probability * self.combined_odds - 1.0, 4)

    def potential_return(self, stake: float) -> float:
        return round(stake * self.combined_odds, 2)


def build_value_parlay(
    all_selections: list[Selection], max_legs: int = 3, min_prob: float = 0.45
) -> Parlay:
    candidates = [s for s in all_selections if s.probability >= min_prob]
    candidates.sort(key=lambda s: (s.has_value, s.edge, s.probability), reverse=True)
    picked: list[Selection] = []
    used_matches: set[str] = set()
    for s in candidates:
        if s.match in used_matches:
            continue
        picked.append(s)
        used_matches.add(s.match)
        if len(picked) >= max_legs:
            break
    return Parlay(picked)


@dataclass
class CashOutAdvice:
    win_probability: float
    fair_cashout: float
    recommendation: str
    keep: bool


def live_win_probability(
    market: str,
    minute: int,
    home_score: int,
    away_score: int,
    pre_lambda_home: float,
    pre_lambda_away: float,
    match_minutes: int = 90,
) -> float:
    minute = max(0, min(minute, match_minutes))
    frac_left = (match_minutes - minute) / match_minutes
    lam_home_rest = pre_lambda_home * frac_left
    lam_away_rest = pre_lambda_away * frac_left
    prob = 0.0
    for gh in range(9):
        for ga in range(9):
            p = poisson_pmf(gh, lam_home_rest) * poisson_pmf(ga, lam_away_rest)
            if _selection_wins(market, home_score + gh, away_score + ga):
                prob += p
    return round(prob, 4)


def _selection_wins(market: str, fh: int, fa: int) -> bool:
    if market == "home":
        return fh > fa
    if market == "away":
        return fa > fh
    if market == "draw":
        return fh == fa
    if market == "over_2_5":
        return fh + fa > 2
    if market == "btts":
        return fh >= 1 and fa >= 1
    return False


def cash_out_advice(
    stake: float,
    original_odds: float,
    win_prob_now: float,
    offered_cashout: float | None = None,
) -> CashOutAdvice:
    potential_return = stake * original_odds
    fair_cashout = round(win_prob_now * potential_return, 2)
    if offered_cashout is None:
        rec = (
            f"Probabilidad de ganar ahora: {win_prob_now*100:.1f}%. "
            f"Valor justo del cash-out ≈ {fair_cashout}. "
            "Si tu casa ofrece menos, conviene mantener; si ofrece más, retirarte."
        )
        return CashOutAdvice(win_prob_now, fair_cashout, rec, win_prob_now >= 0.5)
    if offered_cashout >= fair_cashout:
        rec = f"La casa ofrece {offered_cashout}, por encima del valor justo ({fair_cashout}). RETIRARTE es la opción con mejor valor esperado."
        return CashOutAdvice(win_prob_now, fair_cashout, rec, False)
    rec = f"La casa ofrece {offered_cashout}, por debajo del valor justo ({fair_cashout}). MANTENER tiene mejor valor esperado de media (pero con más riesgo)."
    return CashOutAdvice(win_prob_now, fair_cashout, rec, True)
