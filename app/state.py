"""Thread-sicherer, geteilter Programmstatus fuer mehrere Sensoren
(BLE-Thread <-> Web-Server). Haelt bewusst viele Rohdaten vor (Debug-Zweck)."""
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from .protocol import Reading


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeviceState:
    def __init__(self, mac: str, name: str, is_probe: bool, log_buffer_size: int):
        self.mac = mac
        self.name = name
        self.is_probe = is_probe
        self.status = "connecting"
        self.last_error: Optional[str] = None
        self.last_status_change: str = _now_iso()
        self.last_live: Optional[dict] = None
        self.last_live_ts: Optional[str] = None
        self.last_history_count: Optional[int] = None
        self.last_history_ts: Optional[str] = None
        self.last_history_clean: Optional[bool] = None
        self.raw_log: Deque[dict] = deque(maxlen=log_buffer_size)
        self.packet_count = 0

        # Auto-Sync (periodischer Verlaufs-Abruf mit Luecken-Erkennung)
        self.auto_sync_enabled: bool = False
        self.auto_sync_interval_seconds: int = 600
        self.last_synced_ts: Optional[str] = None
        self.last_auto_sync_at: Optional[str] = None
        self.last_auto_sync_result: Optional[dict] = None
        self.last_sync_check: Optional[dict] = None

    def snapshot(self) -> dict:
        return {
            "mac": self.mac,
            "name": self.name,
            "is_probe": self.is_probe,
            "status": self.status,
            "last_status_change": self.last_status_change,
            "last_error": self.last_error,
            "last_live": self.last_live,
            "last_live_ts": self.last_live_ts,
            "last_history_count": self.last_history_count,
            "last_history_ts": self.last_history_ts,
            "last_history_clean": self.last_history_clean,
            "packet_count": self.packet_count,
            "auto_sync_enabled": self.auto_sync_enabled,
            "auto_sync_interval_seconds": self.auto_sync_interval_seconds,
            "last_synced_ts": self.last_synced_ts,
            "last_auto_sync_at": self.last_auto_sync_at,
            "last_auto_sync_result": self.last_auto_sync_result,
            "last_sync_check": self.last_sync_check,
        }


class AppState:
    def __init__(self, device_log_buffer_size: int = 500):
        self._lock = threading.Lock()
        self._devices: Dict[str, DeviceState] = {}
        self._log_buffer_size = device_log_buffer_size
        self.scanning = False
        self.scan_started_at: Optional[str] = None
        self.scan_finished_at: Optional[str] = None
        self.scan_error: Optional[str] = None
        self.scan_results: List[dict] = []

    def ensure_device(self, mac: str, name: str, is_probe: bool = False) -> None:
        with self._lock:
            if mac not in self._devices:
                self._devices[mac] = DeviceState(mac, name, is_probe, self._log_buffer_size)
            else:
                self._devices[mac].name = name
                self._devices[mac].is_probe = is_probe

    def set_probe_flag(self, mac: str, is_probe: bool) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].is_probe = is_probe

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
                self._devices[mac].last_status_change = _now_iso()

    def set_error(self, mac: str, message: Optional[str]) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_error = message
                if message:
                    self._devices[mac].status = "error"
                    self._devices[mac].last_status_change = _now_iso()

    def set_live_reading(self, mac: str, reading: Reading) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_live = {
                    "temperature_c": reading.temperature_c,
                    "humidity_pct": reading.humidity_pct,
                    "battery_pct": reading.battery_pct,
                }
                self._devices[mac].last_live_ts = _now_iso()

    def get_last_live(self, mac: str) -> Optional[dict]:
        with self._lock:
            device = self._devices.get(mac)
            if not device or not device.last_live:
                return None
            return dict(device.last_live, ts=device.last_live_ts)

    def set_history_result(self, mac: str, count: int, clean: bool = True) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_history_count = count
                self._devices[mac].last_history_ts = _now_iso()
                self._devices[mac].last_history_clean = clean

    def append_raw_log(self, mac: str, entry: dict) -> None:
        entry = dict(entry)
        entry.setdefault("ts", _now_iso())
        with self._lock:
            if mac in self._devices:
                self._devices[mac].raw_log.append(entry)
                self._devices[mac].packet_count += 1

    def get_raw_log(self, mac: str, limit: int = 500) -> List[dict]:
        with self._lock:
            device = self._devices.get(mac)
            if not device:
                return []
            items = list(device.raw_log)
        return items[-limit:]

    def set_scanning(self, scanning: bool) -> None:
        with self._lock:
            self.scanning = scanning
            if scanning:
                self.scan_started_at = _now_iso()
                self.scan_error = None
            else:
                self.scan_finished_at = _now_iso()

    def set_scan_error(self, message: Optional[str]) -> None:
        with self._lock:
            self.scan_error = message

    def set_scan_results(self, results: List[dict]) -> None:
        with self._lock:
            self.scan_results = results

    # -- Auto-Sync -----------------------------------------------------------

    def set_auto_sync_config(self, mac: str, enabled: bool, interval_seconds: int) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].auto_sync_enabled = enabled
                self._devices[mac].auto_sync_interval_seconds = interval_seconds

    def set_last_synced(self, mac: str, ts: Optional[str]) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_synced_ts = ts

    def get_last_synced(self, mac: str) -> Optional[str]:
        with self._lock:
            device = self._devices.get(mac)
            return device.last_synced_ts if device else None

    def set_auto_sync_result(self, mac: str, result: dict) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_auto_sync_at = _now_iso()
                self._devices[mac].last_auto_sync_result = result

    def set_sync_check(self, mac: str, result: dict) -> None:
        with self._lock:
            if mac in self._devices:
                self._devices[mac].last_sync_check = result

    def list_auto_sync_devices(self) -> List[dict]:
        """Momentaufnahme aller Geraete mit auto_sync_enabled - fuer den
        Scheduler im BLE-Thread, ohne dass er direkt auf _devices zugreift."""
        with self._lock:
            return [
                {
                    "mac": d.mac,
                    "auto_sync_interval_seconds": d.auto_sync_interval_seconds,
                    "last_synced_ts": d.last_synced_ts,
                    "last_auto_sync_at": d.last_auto_sync_at,
                }
                for d in self._devices.values()
                if d.auto_sync_enabled and not d.is_probe
            ]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "scanning": self.scanning,
                "scan_started_at": self.scan_started_at,
                "scan_finished_at": self.scan_finished_at,
                "scan_error": self.scan_error,
                "scan_results": list(self.scan_results),
                "devices": [d.snapshot() for d in self._devices.values()],
            }
