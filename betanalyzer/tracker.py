"""Seguimiento y aprendizaje con SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager

DEFAULT_DB = os.environ.get("BETANALYZER_DB", os.path.join(os.path.dirname(__file__), "..", "betanalyzer.db"))


class Tracker:
    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                match_name TEXT NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL,
                p_home REAL, p_draw REAL, p_away REAL, predicted_outcome TEXT,
                actual_home_goals INTEGER, actual_away_goals INTEGER, actual_outcome TEXT,
                resolved INTEGER DEFAULT 0)""")
            c.execute("""CREATE TABLE IF NOT EXISTS results_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, home TEXT NOT NULL, away TEXT NOT NULL,
                home_goals INTEGER NOT NULL, away_goals INTEGER NOT NULL)""")
            columns = {row["name"] for row in c.execute("PRAGMA table_info(predictions)")}
            if "context_json" not in columns:
                c.execute("ALTER TABLE predictions ADD COLUMN context_json TEXT")

    def save_prediction(self, probs, context: dict | None = None) -> int:
        predicted = max([("home", probs.p_home), ("draw", probs.p_draw), ("away", probs.p_away)], key=lambda x: x[1])[0]
        with self._conn() as c:
            cur = c.execute("""INSERT INTO predictions
                (match_name, home, away, p_home, p_draw, p_away, predicted_outcome, context_json)
                VALUES (?,?,?,?,?,?,?,?)""", (f"{probs.home} vs {probs.away}", probs.home, probs.away, probs.p_home, probs.p_draw, probs.p_away, predicted, json.dumps(context or {}, ensure_ascii=False)))
            return cur.lastrowid

    def resolve_prediction(self, pred_id: int, home_goals: int, away_goals: int) -> None:
        outcome = "home" if home_goals > away_goals else "draw" if home_goals == away_goals else "away"
        with self._conn() as c:
            row = c.execute("SELECT home, away FROM predictions WHERE id=?", (pred_id,)).fetchone()
            if row is None:
                raise ValueError(f"No existe la predicción {pred_id}")
            c.execute("UPDATE predictions SET actual_home_goals=?, actual_away_goals=?, actual_outcome=?, resolved=1 WHERE id=?", (home_goals, away_goals, outcome, pred_id))
            c.execute("INSERT INTO results_history (home, away, home_goals, away_goals) VALUES (?,?,?,?)", (row["home"], row["away"], home_goals, away_goals))

    def list_predictions(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM predictions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def metrics(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM predictions WHERE resolved=1").fetchall()
        if not rows:
            return {"resolved": 0, "hit_rate": None, "brier": None}
        hits = 0
        brier_total = 0.0
        for r in rows:
            if r["predicted_outcome"] == r["actual_outcome"]:
                hits += 1
            for outcome, probability in {"home": r["p_home"], "draw": r["p_draw"], "away": r["p_away"]}.items():
                brier_total += (probability - (1.0 if outcome == r["actual_outcome"] else 0.0)) ** 2
        n = len(rows)
        return {"resolved": n, "hit_rate": round(hits / n, 4), "brier": round(brier_total / n, 4)}

    def learned_history(self) -> list[tuple]:
        with self._conn() as c:
            rows = c.execute("SELECT home, away, home_goals, away_goals FROM results_history").fetchall()
            return [(r["home"], r["away"], r["home_goals"], r["away_goals"]) for r in rows]
