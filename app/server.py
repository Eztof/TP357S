"""Lokaler Webserver (Flask): liefert das Dashboard und die JSON-API."""
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from .ble_client import BleController
from .state import AppState
from .storage import Storage

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(state: AppState, storage: Storage, ble: BleController) -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/app.js")
    def app_js():
        return send_from_directory(STATIC_DIR, "app.js")

    @app.get("/style.css")
    def style_css():
        return send_from_directory(STATIC_DIR, "style.css")

    @app.get("/api/status")
    def api_status():
        return jsonify(state.snapshot())

    @app.get("/api/live")
    def api_live():
        limit = request.args.get("limit", default=50, type=int)
        return jsonify(storage.recent_live(limit=limit))

    @app.get("/api/history")
    def api_history():
        limit = request.args.get("limit", default=500, type=int)
        return jsonify(storage.recent_history(limit=limit))

    @app.post("/api/fetch-history")
    def api_fetch_history():
        count = request.args.get("count", default=500, type=int)
        try:
            ble.request_history(count=count)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True})

    @app.get("/api/export.csv")
    def api_export_csv():
        rows = storage.export_csv_rows()

        def generate():
            yield "quelle,zeitstempel,temperatur_c,luftfeuchte_pct,batterie_pct,abgerufen_am\n"
            for row in rows:
                yield ",".join("" if v is None else str(v) for v in row) + "\n"

        return Response(generate(), mimetype="text/csv")

    return app
