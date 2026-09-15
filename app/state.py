"""Thread-sicherer, geteilter Programmstatus fuer mehrere Sensoren
(BLE-Thread <-> Web-Server)."""
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .protocol import Reading


class DeviceState:
    def __init__(self, mac: str, name: str):
        self.mac = mac
        self.name = name
        self.status = "connecting"
        self.last_error: Optional[str] = None
        self.last_live: Optional[dict] = None
        self.last_live_ts: Optional[str] = None
        self.last_history_count: Optional[int] = None
        self.last_history_ts: Optional[str] = None

    def snapshot(self) -> dict:
        return {
            "mac": self.mac,
            "name": self.name,
            "status": self.status,
            "last_error": self.last_error,
            "last_live": self.last_live,
            "last_live_ts": self.last_live_ts,
            "last_history_count": self.last_history_count,
            "last_history_ts": self.last_history_ts,
        }


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self._devices: Dict[str, DeviceState] = {}
        self.scanning = False
        self.scan_results: List[dict] = []

    def ensure_device(self, mac: str, name: str) -> None:
        with self._lock:
            if mac not in self._devices:
                self._devices[mac] = DeviceState(mac, name)
            else:
                self._devices[mac].name = name

    def remove_device(self, mac: str) -> None:
        with self._lock:
            self._devices.pop(mac, None)

    def rename_device(self, mac: str, name: str) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].name = name

    def set_status(self, mac: str, status: str) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].status = status

    def set_error(self, mac: str, message: Optional[str]) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_error = message
                if message:
                    self._devices[mac].status = "error"

    def set_live_reading(self, mac: str, reading: Reading) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_live = {
                    "temperature_c": reading.temperature_c,
                    "humidity_pct": reading.humidity_pct,
                    "battery_pct": reading.battery_pct,
                }
                self._devices[mac].last_live_ts = datetime.now(timezone.utc).isoformat()

    def set_history_result(self, mac: str, count: int) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_history_count = count
                self._devices[mac].last_history_ts = datetime.now(timezone.utc).isoformat()

    def set_scanning(self, scanning: bool) -> None:
        with self._lock:
            self.scanning = scanning

    def set_scan_results(self, results: List[dict]) -> None:
        with self._lock:
            self.scan_results = results

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "scanning": self.scanning,
                "scan_results": list(self.scan_results),
                "devices": [d.snapshot() for d in self._devices.values()],
            }
