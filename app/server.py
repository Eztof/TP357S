"""Lokaler Webserver (Flask): liefert das Dashboard und die JSON-API.

Entwickler-Fokus: jede unbehandelte Exception in einer Route wird mit
vollem Traceback geloggt UND als JSON zurueckgegeben (kein stilles
Verschlucken von Fehlern, keine generische 500-Seite ohne Inhalt)."""
import logging
import traceback
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from .ble_client import BleManager
from .config import AppConfig
from .devices import DeviceStore
from .logging_setup import tail_log_file
from .state import AppState
from .storage import Storage

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: AppConfig, state: AppState, storage: Storage, ble: BleManager, devices: DeviceStore) -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.errorhandler(Exception)
    def handle_exception(exc: Exception):
        logger.exception("Unbehandelte Exception in Route %s", request.path)
        return jsonify({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "path": request.path,
        }), 500

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/app.js")
    def app_js():
        return send_from_directory(STATIC_DIR, "app.js")

    @app.get("/style.css")
    def style_css():
        return send_from_directory(STATIC_DIR, "style.css")

    # -- Status / Debug --------------------------------------------------------

    @app.get("/api/status")
    def api_status():
        return jsonify(state.snapshot())

    @app.get("/api/config")
    def api_config():
        return jsonify(config.as_json_dict())

    @app.get("/api/debug")
    def api_debug():
        return jsonify(ble.debug_snapshot())

    @app.get("/api/logs")
    def api_logs():
        lines = request.args.get("lines", default=300, type=int)
        text = tail_log_file(config.log_path, max_lines=lines)
        return Response(text, mimetype="text/plain")

    # -- Scan --------------------------------------------------------------------

    @app.post("/api/scan")
    def api_scan():
        duration = request.args.get("duration", type=int)
        ble.scan(duration=duration)
        return jsonify({"ok": True})

    # -- Gekoppelte Geraete --------------------------------------------------------

    @app.get("/api/devices")
    def api_list_devices():
        return jsonify(state.snapshot()["devices"])

    @app.post("/api/devices")
    def api_add_device():
        payload = request.get_json(force=True, silent=True) or {}
        mac = (payload.get("mac") or "").strip()
        name = (payload.get("name") or "").strip() or mac
        if not mac:
            return jsonify({"ok": False, "error": "MAC-Adresse fehlt"}), 400
        record = devices.add(mac, name)
        ble.add_device(record.mac, record.name, is_probe=False)
        return jsonify({"ok": True, "device": {"mac": record.mac, "name": record.name}})

    @app.patch("/api/devices/<mac>")
    def api_rename_device(mac):
        payload = request.get_json(force=True, silent=True) or {}
        name = (payload.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Name fehlt"}), 400
        record = devices.rename(mac, name)
        if not record:
            return jsonify({"ok": False, "error": "Geraet nicht gefunden"}), 404
        state.rename_device(record.mac, record.name)
        return jsonify({"ok": True})

    @app.delete("/api/devices/<mac>")
    def api_remove_device(mac):
        devices.remove(mac)
        ble.remove_device(mac)
        return jsonify({"ok": True})

    @app.get("/api/devices/<mac>/live")
    def api_device_live(mac):
        limit = request.args.get("limit", default=50, type=int)
        return jsonify(storage.recent_live(mac.upper(), limit=limit))

    @app.get("/api/devices/<mac>/history")
    def api_device_history(mac):
        limit = request.args.get("limit", default=500, type=int)
        return jsonify(storage.recent_history(mac.upper(), limit=limit))

    @app.get("/api/devices/<mac>/log")
    def api_device_log(mac):
        limit = request.args.get("limit", default=500, type=int)
        return jsonify(state.get_raw_log(mac.upper(), limit=limit))

    @app.post("/api/devices/<mac>/fetch-history")
    def api_fetch_history(mac):
        count = request.args.get("count", default=500, type=int)
        ble.request_history(mac, count=count)
        return jsonify({"ok": True})

    # -- Live-Test / Probe (temporaere, nicht gespeicherte Verbindung) -----------

    @app.post("/api/probe")
    def api_start_probe():
        payload = request.get_json(force=True, silent=True) or {}
        mac = (payload.get("mac") or "").strip()
        name = (payload.get("name") or "").strip() or mac
        if not mac:
            return jsonify({"ok": False, "error": "MAC-Adresse fehlt"}), 400
        ble.add_device(mac.upper(), name, is_probe=True)
        return jsonify({"ok": True})

    @app.post("/api/probe/<mac>/stop")
    def api_stop_probe(mac):
        ble.remove_device(mac)
        return jsonify({"ok": True})

    @app.post("/api/probe/<mac>/promote")
    def api_promote_probe(mac):
        payload = request.get_json(force=True, silent=True) or {}
        name = (payload.get("name") or "").strip() or mac
        record = devices.add(mac, name)
        state.rename_device(record.mac, record.name)
        state.set_probe_flag(record.mac, False)
        return jsonify({"ok": True})

    # -- Export ------------------------------------------------------------------

    @app.get("/api/export.csv")
    def api_export_csv():
        mac = request.args.get("mac")
        rows = storage.export_csv_rows(mac.upper() if mac else None)

        def generate():
            yield "geraet_mac,quelle,zeitstempel,temperatur_c,luftfeuchte_pct,batterie_pct,abgerufen_am\n"
            for row in rows:
                yield ",".join("" if v is None else str(v) for v in row) + "\n"

        return Response(generate(), mimetype="text/csv")

    return app
