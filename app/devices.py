"""Persistente Liste gekoppelter Sensoren (data/devices.json)."""
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class DeviceRecord:
    mac: str
    name: str
    auto_sync_enabled: bool = False
    auto_sync_interval_seconds: int = 600
    last_synced_ts: Optional[str] = None


class DeviceStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._devices: Dict[str, DeviceRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        for item in raw:
            mac = item["mac"].upper()
            self._devices[mac] = DeviceRecord(
                mac=mac,
                name=item.get("name") or mac,
                auto_sync_enabled=bool(item.get("auto_sync_enabled", False)),
                auto_sync_interval_seconds=int(item.get("auto_sync_interval_seconds", 600)),
                last_synced_ts=item.get("last_synced_ts"),
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump([asdict(d) for d in self._devices.values()], f, indent=2, ensure_ascii=False)

    def list(self) -> List[DeviceRecord]:
        with self._lock:
            return list(self._devices.values())

    def add(self, mac: str, name: Optional[str] = None) -> DeviceRecord:
        mac = mac.upper()
        with self._lock:
            existing = self._devices.get(mac)
            if existing:
                if name and name != existing.name:
                    existing.name = name
                    self._save()
                return existing
            record = DeviceRecord(mac=mac, name=name or mac)
            self._devices[mac] = record
            self._save()
            return record

    def remove(self, mac: str) -> bool:
        mac = mac.upper()
        with self._lock:
            if mac in self._devices:
                del self._devices[mac]
                self._save()
                return True
            return False

    def rename(self, mac: str, name: str) -> Optional[DeviceRecord]:
        mac = mac.upper()
        with self._lock:
            record = self._devices.get(mac)
            if not record:
                return None
            record.name = name
            self._save()
            return record

    def set_auto_sync(self, mac: str, enabled: bool, interval_seconds: int) -> Optional[DeviceRecord]:
        mac = mac.upper()
        with self._lock:
            record = self._devices.get(mac)
            if not record:
                return None
            record.auto_sync_enabled = enabled
            record.auto_sync_interval_seconds = max(60, interval_seconds)
            self._save()
            return record

    def set_last_synced(self, mac: str, ts: Optional[str]) -> None:
        mac = mac.upper()
        with self._lock:
            record = self._devices.get(mac)
            if record:
                record.last_synced_ts = ts
                self._save()
