"""Aplicación web Flask de BetAnalyzer."""

from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from .data_source import DataSourceError
from .service import BetService

app = Flask(__name__)
service = BetService()


def data_error(exc: Exception):
    return jsonify({"error": str(exc), "code": "data_source_unavailable"}), 503


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(service.status())


@app.route("/api/upcoming")
def api_upcoming():
    try:
        matches = service.upcoming(refresh=request.args.get("refresh") == "1")
    except DataSourceError as exc:
        return data_error(exc)
    return jsonify({"online": True, "matches": matches})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json(force=True) or {}
    home = (data.get("home") or "").strip()
    away = (data.get("away") or "").strip()
    if not home or not away:
        return jsonify({"error": "Faltan equipos (home/away)."}), 400
    try:
        result = service.analyze_match(home, away, save=bool(data.get("save")), manual_payload=data.get("manual"))
    except DataSourceError as exc:
        return data_error(exc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    result.pop("_probs", None)
    return jsonify(result)


@app.route("/api/parlay", methods=["POST"])
def api_parlay():
    data = request.get_json(force=True) or {}
    raw_matches = data.get("matches") or []
    matches = [{"home": (m.get("home") or "").strip(), "away": (m.get("away") or "").strip(), "manual": m.get("manual") or {}} for m in raw_matches if m.get("home") and m.get("away")]
    if not matches:
        return jsonify({"error": "Envía al menos un partido."}), 400
    try:
        result = service.suggest_parlay(matches, max_legs=max(1, min(int(data.get("max_legs", 3)), 5)))
    except DataSourceError as exc:
        return data_error(exc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.route("/api/cashout", methods=["POST"])
def api_cashout():
    d = request.get_json(force=True) or {}
    try:
        result = service.cash_out(home=d["home"].strip(), away=d["away"].strip(), market=d.get("market", "home"), minute=int(d.get("minute", 0)), home_score=int(d.get("home_score", 0)), away_score=int(d.get("away_score", 0)), stake=float(d.get("stake", 10)), original_odds=float(d.get("original_odds", 2.0)), offered_cashout=float(d["offered_cashout"]) if d.get("offered_cashout") not in (None, "") else None, manual_payload=d.get("manual"))
    except DataSourceError as exc:
        return data_error(exc)
    except (KeyError, ValueError, AttributeError) as exc:
        return jsonify({"error": f"Datos inválidos: {exc}"}), 400
    return jsonify(result)


@app.route("/api/predictions")
def api_predictions():
    return jsonify({"predictions": service.tracker.list_predictions()})


@app.route("/api/resolve", methods=["POST"])
def api_resolve():
    d = request.get_json(force=True) or {}
    try:
        result = service.resolve(int(d["prediction_id"]), int(d["home_goals"]), int(d["away_goals"]))
    except DataSourceError as exc:
        return data_error(exc)
    except (KeyError, ValueError) as exc:
        return jsonify({"error": f"Datos inválidos: {exc}"}), 400
    return jsonify(result)


def main():
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    main()
