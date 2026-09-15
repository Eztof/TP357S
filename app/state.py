"""Thread-sicherer, geteilter Programmstatus (BLE-Thread <-> Web-Server)."""
import threading
from datetime import datetime, timezone
from typing import Optional

from .protocol import Reading


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self.status = "starting"
        self.last_error: Optional[str] = None
        self.last_live: Optional[dict] = None
        self.last_live_ts: Optional[str] = None
        self.last_history_count: Optional[int] = None
        self.last_history_ts: Optional[str] = None

    def set_status(self, status: str) -> None:
        with self._lock:
            self.status = status

    def set_error(self, message: Optional[str]) -> None:
        with self._lock:
            self.last_error = message
            if message:
                self.status = "error"

    def set_live_reading(self, reading: Reading) -> None:
        with self._lock:
            self.last_live = {
                "temperature_c": reading.temperature_c,
                "humidity_pct": reading.humidity_pct,
                "battery_pct": reading.battery_pct,
            }
            self.last_live_ts = datetime.now(timezone.utc).isoformat()

    def set_history_result(self, count: int) -> None:
        with self._lock:
            self.last_history_count = count
            self.last_history_ts = datetime.now(timezone.utc).isoformat()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "last_error": self.last_error,
                "last_live": self.last_live,
                "last_live_ts": self.last_live_ts,
                "last_history_count": self.last_history_count,
                "last_history_ts": self.last_history_ts,
            }
