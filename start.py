"""Startanwendung: startet die Bluetooth-Anbindung und den lokalen Webserver
und oeffnet anschliessend automatisch das Dashboard im Standardbrowser."""
import logging
import threading
import time
import webbrowser

from app.ble_client import BleManager
from app.config import load_config
from app.devices import DeviceStore
from app.server import create_app
from app.state import AppState
from app.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("start")


def main() -> None:
    config = load_config()

    state = AppState()
    storage = Storage(config.db_path)
    devices = DeviceStore(config.devices_path)

    ble = BleManager(config, state, storage)
    ble.start()

    for record in devices.list():
        ble.add_device(record.mac, record.name)

    app = create_app(state, storage, ble, devices)
    url = f"http://{config.web_host}:{config.web_port}/"

    def open_browser() -> None:
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            logger.warning("Konnte Browser nicht automatisch oeffnen. Bitte manuell aufrufen: %s", url)

    threading.Thread(target=open_browser, daemon=True).start()

    logger.info("TP357S-Anwendung laeuft. Dashboard: %s", url)
    app.run(host=config.web_host, port=config.web_port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
