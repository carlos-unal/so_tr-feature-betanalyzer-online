"""Tests de la lógica central sin usar datos ficticios de producción."""

import json
import os
import tempfile

import pytest

from betanalyzer.betting import Parlay, Selection, build_value_parlay, cash_out_advice, live_win_probability
from betanalyzer.data_source import DataSource, DataSourceError
from betanalyzer.model import PoissonModel, poisson_pmf
from betanalyzer.signals import ManualAdjustments, build_signals
from betanalyzer.tracker import Tracker

HISTORY = [("Alpha", "Beta", 3, 1), ("Alpha", "Gamma", 2, 0), ("Beta", "Alpha", 1, 1), ("Beta", "Gamma", 2, 2), ("Gamma", "Alpha", 0, 2), ("Gamma", "Beta", 1, 0)]


def event(home, away, home_goals, away_goals):
    return {"home": home, "away": away, "home_id": "", "away_id": "", "home_goals": home_goals, "away_goals": away_goals}


FORM_ALPHA = [event("Alpha", "Beta", 3, 1), event("Gamma", "Alpha", 0, 2), event("Alpha", "Gamma", 2, 0)]
FORM_BETA = [event("Beta", "Alpha", 1, 1), event("Gamma", "Beta", 1, 0), event("Beta", "Gamma", 2, 2)]


def test_poisson_pmf_sums_to_one():
    assert abs(sum(poisson_pmf(k, 1.5) for k in range(40)) - 1.0) < 1e-6


def test_model_probabilities_sum_to_one_and_accept_modifiers():
    model = PoissonModel(); model.train(HISTORY)
    base = model.predict("Alpha", "Beta"); adjusted = model.predict("Alpha", "Beta", {"home_attack": 0.8})
    assert abs(base.p_home + base.p_draw + base.p_away - 1.0) < 1e-3
    assert adjusted.expected_home_goals < base.expected_home_goals


def test_model_rejects_empty_training():
    with pytest.raises(ValueError):
        PoissonModel().train([])


def test_signals_include_form_style_h2h_and_manual_limits():
    manual = ManualAdjustments.from_payload({"home_absences": 2, "away_absences": 1, "home_motivation": 2})
    signals = build_signals("Alpha", "Beta", FORM_ALPHA, FORM_BETA, [event("Alpha", "Beta", 3, 1), event("Beta", "Alpha", 1, 1)], 1.5, 1.1, manual)
    assert signals["home_form"].style in {"ofensivo", "equilibrado", "defensivo"}
    assert signals["h2h"] == {"matches": 2, "home_wins": 1, "draws": 1, "away_wins": 0, "label": "1-1-0"}
    assert len(signals["breakdown"]) == 3
    assert all(0.78 <= v <= 1.22 for v in signals["modifiers"].values())


def test_manual_adjustments_are_validated():
    with pytest.raises(ValueError): ManualAdjustments.from_payload({"home_absences": 6})
    with pytest.raises(ValueError): ManualAdjustments.from_payload({"home_motivation": 3})


def test_selection_and_parlay_math():
    s1 = Selection("A vs B", "home", "Gana A", 0.6, 1.7); s2 = Selection("C vs D", "home", "Gana C", 0.5, 2.0)
    assert s1.has_value is True
    parlay = Parlay([s1, s2])
    assert parlay.combined_probability == pytest.approx(0.3)
    assert parlay.combined_odds == pytest.approx(3.4)
    assert len(build_value_parlay([s1, s2], max_legs=2).selections) == 2


def test_live_probability_and_cashout():
    assert live_win_probability("over_2_5", 80, 2, 1, 1.5, 1.2) == pytest.approx(1.0)
    early = live_win_probability("home", 20, 1, 0, 1.5, 1.2); late = live_win_probability("home", 85, 1, 0, 1.5, 1.2)
    assert late > early
    assert cash_out_advice(10, 2, 0.5, 20).keep is False
    assert cash_out_advice(10, 2, 0.9, 5).keep is True


def test_tracker_persists_context_and_learns():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    try:
        tracker = Tracker(db_path=path); model = PoissonModel(); model.train(HISTORY); probs = model.predict("Alpha", "Beta")
        pred_id = tracker.save_prediction(probs, {"breakdown": ["forma real"]})
        assert json.loads(tracker.list_predictions()[0]["context_json"])["breakdown"] == ["forma real"]
        tracker.resolve_prediction(pred_id, 2, 0)
        assert tracker.metrics()["resolved"] == 1
        assert len(tracker.learned_history()) == 1
    finally: os.remove(path)


def test_data_source_never_falls_back(monkeypatch):
    source = DataSource(league_ids=["test"])
    monkeypatch.setattr(source, "_get", lambda _path: (_ for _ in ()).throw(DataSourceError("API caída")))
    with pytest.raises(DataSourceError, match="API caída"): source.upcoming_matches()


def test_data_source_normalizes_and_filters_h2h(monkeypatch):
    source = DataSource()
    responses = {"searchteams.php?t=Alpha": {"teams": [{"idTeam": "1", "strTeam": "Alpha"}]}, "searchteams.php?t=Beta": {"teams": [{"idTeam": "2", "strTeam": "Beta"}]}, "eventslast.php?id=1": {"results": [{"idEvent": "e1", "idHomeTeam": "1", "idAwayTeam": "2", "strHomeTeam": "Alpha", "strAwayTeam": "Beta", "intHomeScore": "2", "intAwayScore": "1"}, {"idEvent": "e2", "idHomeTeam": "1", "idAwayTeam": "3", "strHomeTeam": "Alpha", "strAwayTeam": "Gamma", "intHomeScore": "1", "intAwayScore": "0"}]}}
    monkeypatch.setattr(source, "_get", lambda path: responses[path])
    h2h = source.head_to_head("Alpha", "Beta")
    assert len(h2h) == 1
    assert h2h[0]["home_goals"] == 2
