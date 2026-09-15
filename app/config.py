"""Laedt die lokale Konfiguration (config.json) der Anwendung."""
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
EXAMPLE_CONFIG_PATH = BASE_DIR / "config.example.json"


@dataclass
class AppConfig:
    history_record_interval_seconds: int
    reconnect_delay_seconds: int
    scan_duration_seconds: int
    web_host: str
    web_port: int
    db_path: Path
    devices_path: Path


def load_config() -> AppConfig:
    path = CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    if path == EXAMPLE_CONFIG_PATH:
        logger.warning(
            "config.json nicht gefunden, verwende config.example.json als Vorlage. "
            "Bitte config.json anlegen (Kopie von config.example.json)."
        )
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return AppConfig(
        history_record_interval_seconds=int(raw.get("history_record_interval_seconds", 60)),
        reconnect_delay_seconds=int(raw.get("reconnect_delay_seconds", 10)),
        scan_duration_seconds=int(raw.get("scan_duration_seconds", 8)),
        web_host=raw.get("web_host", "127.0.0.1"),
        web_port=int(raw.get("web_port", 5000)),
        db_path=BASE_DIR / raw.get("db_path", "data/tp357s.db"),
        devices_path=BASE_DIR / raw.get("devices_path", "data/devices.json"),
    )
