"""Fuente estrictamente online basada en TheSportsDB.

Este módulo no hace scraping y no contiene datos ficticios. Si la API no está
disponible, la aplicación devuelve un error explicando el problema en lugar de
inventar partidos o resultados.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


class DataSourceError(RuntimeError):
    """Indica que no se pudo obtener o validar un dato online."""


API_KEY = os.environ.get("THESPORTSDB_KEY", "3")
BASE_URL = "https://www.thesportsdb.com/api/v1/json"
TIMEOUT = float(os.environ.get("THESPORTSDB_TIMEOUT", "15"))

DEFAULT_LEAGUE_IDS = [
    "4328",  # English Premier League, fútbol masculino
    "4335",  # Spanish La Liga, fútbol masculino
    "4849",  # FA Women's Super League, fútbol femenino
]


def configured_league_ids() -> list[str]:
    raw = os.environ.get("THESPORTSDB_LEAGUE_IDS", "")
    return [item.strip() for item in raw.split(",") if item.strip()] or list(DEFAULT_LEAGUE_IDS)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _same_team(left: str, right: str) -> bool:
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


class DataSource:
    """Cliente online con caché de proceso para reducir llamadas repetidas."""

    def __init__(self, league_ids: Optional[list[str]] = None):
        self.league_ids = league_ids or configured_league_ids()
        self.last_error: str | None = None
        self.last_successful_leagues = 0
        self._upcoming_cache: list[dict] | None = None
        self._team_cache: dict[str, dict] = {}
        self._history_cache: dict[str, list[dict]] = {}

    @property
    def online(self) -> bool:
        """True solo si la última operación de datos obtuvo información real."""
        return self.last_error is None and (
            self.last_successful_leagues > 0 or self._upcoming_cache is not None
        )

    def _get(self, path: str) -> dict:
        url = f"{BASE_URL}/{API_KEY}/{path}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "BetAnalyzer/0.2 (+https://github.com/)"}
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                data = json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = f"No se pudo consultar TheSportsDB: {exc}"
            raise DataSourceError(self.last_error) from exc
        except (ValueError, TypeError) as exc:
            self.last_error = "TheSportsDB devolvió una respuesta JSON inválida."
            raise DataSourceError(self.last_error) from exc

        if not isinstance(data, dict):
            self.last_error = "TheSportsDB devolvió un formato inesperado."
            raise DataSourceError(self.last_error)
        self.last_error = None
        return data

    def upcoming_matches(self, refresh: bool = False) -> list[dict]:
        """Obtiene próximos partidos reales de las ligas configuradas.

        Se tolera que una liga concreta falle, pero nunca se sustituyen sus datos
        por ejemplos. Si ninguna liga responde o no hay partidos, se informa del error.
        """
        if self._upcoming_cache is not None and not refresh:
            return list(self._upcoming_cache)

        matches: list[dict] = []
        errors: list[str] = []
        successful = 0
        for league_id in self.league_ids:
            try:
                data = self._get(f"eventsnextleague.php?id={urllib.parse.quote(league_id)}")
                successful += 1
            except DataSourceError as exc:
                errors.append(str(exc))
                continue
            for event in data.get("events") or []:
                normalized = self._normalize_event(event)
                if normalized["home"] and normalized["away"]:
                    matches.append(normalized)

        self.last_successful_leagues = successful
        if not matches:
            self.last_error = (
                "TheSportsDB no devolvió próximos partidos. "
                + (errors[0] if errors else "Revisa las ligas configuradas.")
            )
            raise DataSourceError(self.last_error)

        self._upcoming_cache = matches
        if errors:
            self.last_error = f"Algunas ligas no respondieron ({len(errors)}); datos parciales reales."
        else:
            self.last_error = None
        return list(matches)

    def find_team(self, team_name: str) -> dict:
        """Busca un equipo online y conserva su identificador para futuras llamadas."""
        key = " ".join(team_name.casefold().split())
        if not key:
            raise DataSourceError("El nombre del equipo no puede estar vacío.")
        if key in self._team_cache:
            return dict(self._team_cache[key])

        data = self._get(f"searchteams.php?t={urllib.parse.quote(team_name)}")
        teams = data.get("teams") or []
        if not teams:
            raise DataSourceError(f"No se encontró el equipo online: {team_name}.")

        chosen = next(
            (team for team in teams if _same_team(_clean(team.get("strTeam")), team_name)),
            teams[0],
        )
        team_id = _clean(chosen.get("idTeam"))
        canonical = _clean(chosen.get("strTeam"))
        if not team_id or not canonical:
            raise DataSourceError(f"TheSportsDB no identificó correctamente: {team_name}.")
        result = {
            "id": team_id,
            "name": canonical,
            "sport": _clean(chosen.get("strSport")),
            "league": _clean(chosen.get("strLeague")),
        }
        self._team_cache[key] = result
        self._team_cache[canonical.casefold()] = result
        return dict(result)

    def team_history(self, team_name: str, limit: int = 20) -> list[dict]:
        """Obtiene resultados recientes reales de un equipo."""
        team = self.find_team(team_name)
        if team["id"] in self._history_cache:
            return list(self._history_cache[team["id"]][:limit])

        data = self._get(f"eventslast.php?id={urllib.parse.quote(team['id'])}")
        events: list[dict] = []
        for event in data.get("results") or []:
            normalized = self._normalize_history(event)
            if normalized is not None:
                events.append(normalized)
        if not events:
            raise DataSourceError(f"No hay resultados históricos online para {team_name}.")
        self._history_cache[team["id"]] = events
        return list(events[:limit])

    def head_to_head(self, home: str, away: str, limit: int = 10) -> list[dict]:
        """Filtra enfrentamientos directos desde el histórico real del local."""
        away_team = self.find_team(away)
        home_history = self.team_history(home, limit=50)
        h2h = [
            event
            for event in home_history
            if event.get("home_id") == away_team["id"]
            or event.get("away_id") == away_team["id"]
            or _same_team(event["home"], away_team["name"])
            or _same_team(event["away"], away_team["name"])
        ]
        return h2h[:limit]

    def all_history(self, extra_teams: Optional[list[str]] = None) -> list[tuple]:
        """Recopila históricos reales de los equipos de próximos partidos."""
        upcoming = self.upcoming_matches()
        names = {m["home"] for m in upcoming} | {m["away"] for m in upcoming}
        names.update(extra_teams or [])
        history: list[tuple] = []
        seen: set[tuple] = set()
        for name in names:
            for event in self.team_history(name):
                row = (event["home"], event["away"], event["home_goals"], event["away_goals"])
                if row not in seen:
                    seen.add(row)
                    history.append(row)
        if not history:
            raise DataSourceError("No hay suficientes resultados reales para entrenar el modelo.")
        return history

    @staticmethod
    def _normalize_event(event: dict) -> dict:
        return {
            "id": _clean(event.get("idEvent")),
            "name": _clean(event.get("strEvent")),
            "home": _clean(event.get("strHomeTeam")),
            "away": _clean(event.get("strAwayTeam")),
            "home_id": _clean(event.get("idHomeTeam")),
            "away_id": _clean(event.get("idAwayTeam")),
            "league": _clean(event.get("strLeague")),
            "sport": _clean(event.get("strSport")),
            "date": _clean(event.get("dateEvent")),
            "time": _clean(event.get("strTime")),
        }

    @staticmethod
    def _normalize_history(event: dict) -> dict | None:
        try:
            home_goals = int(event.get("intHomeScore"))
            away_goals = int(event.get("intAwayScore"))
        except (TypeError, ValueError):
            return None
        home = _clean(event.get("strHomeTeam"))
        away = _clean(event.get("strAwayTeam"))
        if not home or not away:
            return None
        return {
            "id": _clean(event.get("idEvent")),
            "home": home,
            "away": away,
            "home_id": _clean(event.get("idHomeTeam")),
            "away_id": _clean(event.get("idAwayTeam")),
            "home_goals": home_goals,
            "away_goals": away_goals,
            "date": _clean(event.get("dateEvent")),
            "league": _clean(event.get("strLeague")),
            "sport": _clean(event.get("strSport")),
        }
