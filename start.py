"""Startanwendung: startet die Bluetooth-Anbindung und den lokalen Webserver
und oeffnet anschliessend automatisch das Dashboard im Standardbrowser.

Entwickler-Hinweis: Alles Relevante (Konfiguration, jeder BLE-Vorgang, jede
Exception in jedem Thread) wird nach data/app.log geloggt - auch nachdem
das Konsolenfenster geschlossen wurde. Bei einem Absturz zuerst dort
nachsehen bzw. im Dashboard unter "Server" (/api/logs)."""
import logging
import threading
import time
import webbrowser

from app.ble_client import BleManager
from app.config import load_config
from app.devices import DeviceStore
from app.firebase_sync import FirebaseSync
from app.hue_client import HueManager
from app.hue_layout import HueLayout
from app.logging_setup import setup_logging
from app.server import create_app
from app.state import AppState
from app.storage import Storage
from app.ui_state import UiState

logger = logging.getLogger("start")


def main() -> None:
    config = load_config()
    setup_logging(
        config.log_path,
        level=config.log_level,
        max_bytes=config.log_max_bytes,
        backup_count=config.log_backup_count,
    )
    logger.info("=== TP357S-Anwendung startet ===")
    logger.info("Effektive Konfiguration: %s", config.as_json_dict())

    state = AppState(device_log_buffer_size=config.device_log_buffer_size)
    storage = Storage(config.db_path)
    devices = DeviceStore(config.devices_path)
    ui_state = UiState(config.ui_state_path)
    hue = HueManager(config.hue_config_path)
    hue_layout = HueLayout(config.hue_layout_dir)
    logger.info("Gekoppelte Geraete geladen: %s", [d.mac for d in devices.list()])

    ble = BleManager(config, state, storage, devices)
    ble.start()

    for record in devices.list():
        ble.add_device(record.mac, record.name, is_probe=False)
        state.set_auto_sync_config(record.mac, record.auto_sync_enabled, record.auto_sync_interval_seconds)
        state.set_last_synced(record.mac, record.last_synced_ts)

    ble.start_auto_sync()

    firebase = FirebaseSync(config, storage, devices)
    firebase.start()

    app = create_app(config, state, storage, ble, devices, firebase, ui_state, hue, hue_layout)
    url = f"http://{config.web_host}:{config.web_port}/"

    def open_browser() -> None:
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            logger.warning("Konnte Browser nicht automatisch oeffnen. Bitte manuell aufrufen: %s", url)

    threading.Thread(target=open_browser, daemon=True, name="open-browser").start()

    logger.info("TP357S-Anwendung laeuft. Dashboard: %s", url)
    try:
        app.run(host=config.web_host, port=config.web_port, threaded=True, use_reloader=False)
    except Exception:
        logger.critical("Flask-Server ist abgestuerzt", exc_info=True)
        raise
    finally:
        logger.warning("app.run() ist zurueckgekehrt, Prozess beendet sich jetzt.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.critical("TP357S-Anwendung wurde durch eine unbehandelte Exception beendet", exc_info=True)
        raise
