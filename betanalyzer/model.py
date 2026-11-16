"""Modelo transparente de probabilidades para partidos de fútbol.

Usa Poisson para los goles y acepta multiplicadores pequeños procedentes de
forma, H2H, localía, bajas y motivación. Los multiplicadores están limitados en
la capa de señales para evitar que una opinión manual convierta una estimación
en una falsa certeza.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

MAX_GOALS = 10


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


@dataclass
class MatchProbabilities:
    home: str
    away: str
    p_home: float
    p_draw: float
    p_away: float
    expected_home_goals: float
    expected_away_goals: float
    p_over_2_5: float
    p_btts: float

    def fair_odds(self) -> dict[str, float]:
        def inv(p: float) -> float:
            return round(1.0 / p, 2) if p > 0 else 999.0

        return {
            "home": inv(self.p_home),
            "draw": inv(self.p_draw),
            "away": inv(self.p_away),
            "over_2_5": inv(self.p_over_2_5),
            "btts": inv(self.p_btts),
        }


@dataclass
class PoissonModel:
    attack: dict[str, float] = field(default_factory=dict)
    defense: dict[str, float] = field(default_factory=dict)
    avg_home_goals: float = 1.4
    avg_away_goals: float = 1.1
    trained_matches: int = 0

    def train(self, history: list[tuple]) -> None:
        if not history:
            raise ValueError("El modelo necesita al menos un resultado real para entrenar.")

        home_goals = [int(h[2]) for h in history]
        away_goals = [int(h[3]) for h in history]
        n = len(history)
        self.avg_home_goals = max(0.2, sum(home_goals) / n)
        self.avg_away_goals = max(0.2, sum(away_goals) / n)

        scored = defaultdict(float)
        conceded = defaultdict(float)
        games = defaultdict(int)
        for home, away, goals_home, goals_away in history:
            scored[home] += goals_home
            conceded[home] += goals_away
            scored[away] += goals_away
            conceded[away] += goals_home
            games[home] += 1
            games[away] += 1

        league_avg = max(0.2, (sum(home_goals) + sum(away_goals)) / (2 * n))
        self.attack.clear()
        self.defense.clear()
        for team, played in games.items():
            self.attack[team] = (scored[team] / played) / league_avg
            self.defense[team] = (conceded[team] / played) / league_avg
        self.trained_matches = n

    def _strength(self, team: str, kind: str) -> float:
        values = self.attack if kind == "attack" else self.defense
        return values.get(team, 1.0)

    def predict(
        self,
        home: str,
        away: str,
        modifiers: dict[str, float] | None = None,
    ) -> MatchProbabilities:
        """Calcula probabilidades y aplica ajustes acotados de contexto.

        modifiers usa cuatro claves opcionales:
        home_attack, home_defense, away_attack, away_defense.
        """
        modifiers = modifiers or {}
        home_attack = modifiers.get("home_attack", 1.0)
        home_defense = modifiers.get("home_defense", 1.0)
        away_attack = modifiers.get("away_attack", 1.0)
        away_defense = modifiers.get("away_defense", 1.0)

        lam_home = (
            self.avg_home_goals
            * self._strength(home, "attack")
            * self._strength(away, "defense")
            * home_attack
            * away_defense
        )
        lam_away = (
            self.avg_away_goals
            * self._strength(away, "attack")
            * self._strength(home, "defense")
            * away_attack
            * home_defense
        )
        lam_home = min(max(lam_home, 0.1), 6.0)
        lam_away = min(max(lam_away, 0.1), 6.0)

        p_home = p_draw = p_away = p_over = p_btts = 0.0
        home_pmf = [poisson_pmf(i, lam_home) for i in range(MAX_GOALS + 1)]
        away_pmf = [poisson_pmf(j, lam_away) for j in range(MAX_GOALS + 1)]
        for goals_home in range(MAX_GOALS + 1):
            for goals_away in range(MAX_GOALS + 1):
                probability = home_pmf[goals_home] * away_pmf[goals_away]
                if goals_home > goals_away:
                    p_home += probability
                elif goals_home == goals_away:
                    p_draw += probability
                else:
                    p_away += probability
                if goals_home + goals_away > 2:
                    p_over += probability
                if goals_home >= 1 and goals_away >= 1:
                    p_btts += probability

        total = p_home + p_draw + p_away
        if total:
            p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total
        return MatchProbabilities(
            home=home,
            away=away,
            p_home=round(p_home, 4),
            p_draw=round(p_draw, 4),
            p_away=round(p_away, 4),
            expected_home_goals=round(lam_home, 2),
            expected_away_goals=round(lam_away, 2),
            p_over_2_5=round(p_over, 4),
            p_btts=round(p_btts, 4),
        )
