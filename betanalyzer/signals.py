"""Señales explicables que ajustan el modelo de goles.

Las señales automáticas salen de resultados reales de TheSportsDB. Lesiones y
motivación no se inventan: se introducen manualmente y su efecto queda limitado.
"""

from __future__ import annotations

from dataclasses import dataclass


def _norm(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class ManualAdjustments:
    home_absences: int = 0
    away_absences: int = 0
    home_motivation: int = 0
    away_motivation: int = 0

    @classmethod
    def from_payload(cls, payload: dict | None) -> "ManualAdjustments":
        payload = payload or {}
        try:
            values = {
                "home_absences": int(payload.get("home_absences", 0)),
                "away_absences": int(payload.get("away_absences", 0)),
                "home_motivation": int(payload.get("home_motivation", 0)),
                "away_motivation": int(payload.get("away_motivation", 0)),
            }
        except (TypeError, ValueError) as exc:
            raise ValueError("Bajas y motivación deben ser números enteros.") from exc
        if not 0 <= values["home_absences"] <= 5 or not 0 <= values["away_absences"] <= 5:
            raise ValueError("Las bajas clave deben estar entre 0 y 5 por equipo.")
        if not -2 <= values["home_motivation"] <= 2 or not -2 <= values["away_motivation"] <= 2:
            raise ValueError("La motivación debe estar entre -2 y 2.")
        return cls(**values)

    def modifiers(self) -> dict[str, float]:
        """Transforma entradas manuales en ajustes pequeños y simétricos."""
        home_absence = 0.96**self.home_absences
        away_absence = 0.96**self.away_absences
        home_motivation_attack = 1.0 + 0.025 * self.home_motivation
        away_motivation_attack = 1.0 + 0.025 * self.away_motivation
        home_motivation_defense = 1.0 - 0.015 * self.home_motivation
        away_motivation_defense = 1.0 - 0.015 * self.away_motivation
        return {
            "home_attack": home_absence * home_motivation_attack,
            "home_defense": home_absence * home_motivation_defense,
            "away_attack": away_absence * away_motivation_attack,
            "away_defense": away_absence * away_motivation_defense,
        }

    def labels(self, home: str, away: str) -> list[str]:
        motivation = {0: "normal", 1: "alta", 2: "debe ganar", -1: "baja", -2: "muy baja"}
        return [
            f"Bajas: {home} {self.home_absences}, {away} {self.away_absences}",
            f"Motivación: {home} {motivation[self.home_motivation]}, {away} {motivation[self.away_motivation]}",
        ]


@dataclass
class TeamForm:
    team: str
    matches: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    avg_goals_for: float
    avg_goals_against: float
    btts_rate: float
    over25_rate: float
    home_win_rate: float
    away_loss_rate: float
    style: str

    def to_dict(self) -> dict:
        return {
            "team": self.team,
            "matches": self.matches,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "goals_for": self.goals_for,
            "goals_against": self.goals_against,
            "avg_goals_for": self.avg_goals_for,
            "avg_goals_against": self.avg_goals_against,
            "btts_rate": self.btts_rate,
            "over25_rate": self.over25_rate,
            "style": self.style,
        }


def summarize_form(history: list[dict], team: str, league_average: float) -> TeamForm:
    team_key = _norm(team)
    matches = wins = draws = losses = goals_for = goals_against = 0
    btts = over25 = home_games = home_wins = away_games = away_losses = 0
    for event in history:
        is_home = _norm(event["home"]) == team_key
        is_away = _norm(event["away"]) == team_key
        if not (is_home or is_away):
            continue
        gf = event["home_goals"] if is_home else event["away_goals"]
        ga = event["away_goals"] if is_home else event["home_goals"]
        matches += 1
        goals_for += gf
        goals_against += ga
        if gf > ga:
            wins += 1
        elif gf == ga:
            draws += 1
        else:
            losses += 1
        btts += int(gf > 0 and ga > 0)
        over25 += int(gf + ga > 2)
        if is_home:
            home_games += 1
            home_wins += int(gf > ga)
        else:
            away_games += 1
            away_losses += int(gf < ga)

    if not matches:
        raise ValueError(f"No hay forma reciente para {team}.")
    avg_for = goals_for / matches
    avg_against = goals_against / matches
    total_avg = avg_for + avg_against
    if avg_for >= league_average * 1.2 or total_avg >= 3.0:
        style = "ofensivo"
    elif avg_for <= league_average * 0.85 and total_avg <= 2.35:
        style = "defensivo"
    else:
        style = "equilibrado"
    return TeamForm(
        team=team,
        matches=matches,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for=goals_for,
        goals_against=goals_against,
        avg_goals_for=round(avg_for, 2),
        avg_goals_against=round(avg_against, 2),
        btts_rate=round(btts / matches, 3),
        over25_rate=round(over25 / matches, 3),
        home_win_rate=home_wins / home_games if home_games else 0.5,
        away_loss_rate=away_losses / away_games if away_games else 0.5,
        style=style,
    )


def h2h_summary(h2h: list[dict], home: str, away: str) -> dict:
    home_key, away_key = _norm(home), _norm(away)
    home_wins = draws = away_wins = 0
    for event in h2h:
        event_home, event_away = _norm(event["home"]), _norm(event["away"])
        gh, ga = event["home_goals"], event["away_goals"]
        if event_home == home_key and event_away == away_key:
            result_home, result_away = gh, ga
        elif event_home == away_key and event_away == home_key:
            result_home, result_away = ga, gh
        else:
            continue
        if result_home > result_away:
            home_wins += 1
        elif result_home == result_away:
            draws += 1
        else:
            away_wins += 1
    total = home_wins + draws + away_wins
    return {
        "matches": total,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "label": f"{home_wins}-{draws}-{away_wins}" if total else "sin datos",
    }


def build_signals(
    home: str,
    away: str,
    home_history: list[dict],
    away_history: list[dict],
    h2h: list[dict],
    avg_home_goals: float,
    avg_away_goals: float,
    manual: ManualAdjustments,
) -> dict:
    league_average = max(0.2, (avg_home_goals + avg_away_goals) / 2)
    home_form = summarize_form(home_history, home, league_average)
    away_form = summarize_form(away_history, away, league_average)
    h2h_data = h2h_summary(h2h, home, away)

    def form_attack(form: TeamForm) -> float:
        return _clamp(1.0 + ((form.avg_goals_for / league_average) - 1.0) * 0.25, 0.9, 1.1)

    def form_defense(form: TeamForm) -> float:
        return _clamp(1.0 + ((form.avg_goals_against / league_average) - 1.0) * 0.25, 0.9, 1.1)

    if h2h_data["matches"]:
        h2h_edge = (h2h_data["home_wins"] - h2h_data["away_wins"]) / h2h_data["matches"]
        h2h_home = _clamp(1.0 + h2h_edge * 0.06, 0.94, 1.06)
        h2h_away = _clamp(1.0 - h2h_edge * 0.06, 0.94, 1.06)
    else:
        h2h_home = h2h_away = 1.0

    local_edge = ((home_form.home_win_rate + away_form.away_loss_rate) / 2) - 0.5
    local_factor = _clamp(1.0 + local_edge * 0.08, 0.96, 1.04)

    manual_modifiers = manual.modifiers()
    modifiers = {
        "home_attack": _clamp(form_attack(home_form) * h2h_home * local_factor * manual_modifiers["home_attack"], 0.78, 1.22),
        "home_defense": _clamp(form_defense(home_form) / local_factor * manual_modifiers["home_defense"], 0.78, 1.22),
        "away_attack": _clamp(form_attack(away_form) * h2h_away * manual_modifiers["away_attack"], 0.78, 1.22),
        "away_defense": _clamp(form_defense(away_form) * manual_modifiers["away_defense"], 0.78, 1.22),
    }
    return {
        "home_form": home_form,
        "away_form": away_form,
        "h2h": h2h_data,
        "local_factor": round(local_factor, 3),
        "modifiers": modifiers,
        "manual": manual,
        "breakdown": [
            f"Forma: {home} {home_form.wins}-{home_form.draws}-{home_form.losses}; {away} {away_form.wins}-{away_form.draws}-{away_form.losses}.",
            f"Estilo: {home} {home_form.style}; {away} {away_form.style}. H2H: {h2h_data['label']}.",
            "Contexto: " + " · ".join(manual.labels(home, away)),
        ],
    }
