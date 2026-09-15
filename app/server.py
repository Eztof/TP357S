"""Lokaler Webserver (Flask): liefert das Dashboard und die JSON-API.

Entwickler-Fokus: jede unbehandelte Exception in einer Route wird mit
vollem Traceback geloggt UND als JSON zurueckgegeben (kein stilles
Verschlucken von Fehlern, keine generische 500-Seite ohne Inhalt)."""
import logging
import traceback
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from . import protocol
from .ble_client import BleManager
from .config import AppConfig
from .devices import DeviceStore
from .firebase_sync import FirebaseSync
from .logging_setup import tail_log_file
from .state import AppState
from .storage import Storage, aggregate_points

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    config: AppConfig, state: AppState, storage: Storage, ble: BleManager, devices: DeviceStore,
    firebase: FirebaseSync,
) -> Flask:
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

    @app.post("/api/devices/<mac>/auto-sync")
    def api_set_auto_sync(mac):
        payload = request.get_json(force=True, silent=True) or {}
        enabled = bool(payload.get("enabled", False))
        interval_minutes = payload.get("interval_minutes", 10)
        try:
            interval_seconds = max(60, int(float(interval_minutes) * 60))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Ungueltiges Intervall"}), 400
        record = devices.set_auto_sync(mac, enabled, interval_seconds)
        if not record:
            return jsonify({"ok": False, "error": "Geraet nicht gefunden (nur gekoppelte Geraete, keine Live-Tests)"}), 404
        state.set_auto_sync_config(record.mac, enabled, interval_seconds)
        return jsonify({"ok": True, "enabled": enabled, "interval_seconds": interval_seconds})

    @app.get("/api/firebase/status")
    def api_firebase_status():
        return jsonify(firebase.snapshot())

    @app.post("/api/firebase/upload-now")
    def api_firebase_upload_now():
        if not config.firebase_enabled:
            return jsonify({"ok": False, "error": "firebase_enabled ist false in config.json"}), 400
        firebase.trigger_now()
        return jsonify({"ok": True})

    @app.get("/api/devices/<mac>/live")
    def api_device_live(mac):
        limit = request.args.get("limit", default=50, type=int)
        return jsonify(storage.recent_live(mac.upper(), limit=limit))

    @app.get("/api/devices/<mac>/history")
    def api_device_history(mac):
        limit = request.args.get("limit", default=500, type=int)
        return jsonify(storage.recent_history(mac.upper(), limit=limit))

    @app.get("/api/devices/<mac>/series")
    def api_device_series(mac):
        """Live- + Verlaufsdaten zusammengefuehrt und optional in Zeit-Buckets
        gemittelt - Datenquelle fuer den Graphen im Dashboard."""
        resolution = request.args.get("resolution", default="raw")
        limit = request.args.get("limit", default=5000, type=int)
        bucket_seconds = {"raw": 0, "5min": 300, "15min": 900, "hour": 3600, "day": 86400}.get(resolution, 0)
        points = storage.combined_series(mac.upper(), limit=limit)
        points = aggregate_points(points, bucket_seconds)
        return jsonify({"ok": True, "resolution": resolution, "resolution_seconds": bucket_seconds, "points": points})

    @app.get("/api/devices/<mac>/log")
    def api_device_log(mac):
        limit = request.args.get("limit", default=500, type=int)
        return jsonify(state.get_raw_log(mac.upper(), limit=limit))

    @app.post("/api/devices/<mac>/fetch-history")
    def api_fetch_history(mac):
        count = request.args.get("count", default=500, type=int)
        ble.request_history(mac, count=count)
        return jsonify({"ok": True})

    @app.post("/api/devices/<mac>/write")
    def api_write_raw(mac):
        payload = request.get_json(force=True, silent=True) or {}
        hex_str = (payload.get("hex") or "").strip().replace(" ", "")
        try:
            data = bytes.fromhex(hex_str)
        except ValueError:
            return jsonify({"ok": False, "error": "Ungueltige Hex-Zeichenkette"}), 400
        if not data:
            return jsonify({"ok": False, "error": "Keine Bytes angegeben"}), 400
        ble.write_raw(mac, data)
        return jsonify({"ok": True})

    @app.get("/api/checksum")
    def api_checksum():
        hex_str = (request.args.get("hex") or "").strip().replace(" ", "")
        try:
            data = bytes.fromhex(hex_str)
        except ValueError:
            return jsonify({"ok": False, "error": "Ungueltige Hex-Zeichenkette"}), 400
        cs = protocol.checksum(data)
        return jsonify({
            "ok": True,
            "checksum_hex": f"{cs:02x}",
            "checksum_dec": cs,
            "with_checksum_hex": data.hex() + f"{cs:02x}",
        })

    @app.get("/api/protocol/examples")
    def api_protocol_examples():
        """Liefert das Datenanfrage-Kommando fertig kodiert fuer den
        aktuellen Zeitpunkt - zum Reinkopieren in die Rohbefehl-Konsole,
        z.B. um es isoliert (ohne die drei vorgeschalteten Kommandos) am
        Geraet zu testen."""
        count = request.args.get("count", default=500, type=int)
        data_request = protocol.build_data_request_command(count)
        return jsonify({
            "ok": True,
            "data_request_hex": data_request.hex(),
            "data_request_count": count,
            "note": (
                "Aufbau: CC CC 01 09 00 00 00 YY MM DD HH MM SS NL NH CS 66 66 "
                "(YY MM DD HH MM SS = aktuelles Datum/Zeit ohne Wochentag, "
                "NL NH = Anzahl als 16-bit little-endian, "
                "CS = Checksumme ueber 01 09 00 00 00 <Datum> NL NH)."
            ),
        })

    @app.get("/api/protocol/time-shaped-candidate")
    def api_time_shaped_candidate():
        """Baut ein Kandidaten-Kommando (Praefix + aktuelle Datumsfelder +
        Checksumme) fuer einen frei gewaehlten Praefix - zum Durchprobieren
        moeglicher Uhrzeit-Sync-Opcodes, ohne Datum/Checksumme von Hand
        ausrechnen zu muessen."""
        prefix_hex = (request.args.get("prefix") or "").strip().replace(" ", "")
        try:
            prefix = bytes.fromhex(prefix_hex)
        except ValueError:
            return jsonify({"ok": False, "error": "Ungueltige Hex-Zeichenkette"}), 400
        candidate = protocol.build_time_shaped_candidate(prefix)
        return jsonify({"ok": True, "hex": candidate.hex()})

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
