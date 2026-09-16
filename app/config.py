"""Laedt die lokale Konfiguration (config.json) der Anwendung."""
import json
import logging
from dataclasses import asdict, dataclass
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
    ui_state_path: Path
    hue_config_path: Path
    log_path: Path
    log_level: str
    log_max_bytes: int
    log_backup_count: int
    device_log_buffer_size: int
    firebase_enabled: bool
    firebase_service_account_path: Path
    firebase_collection: str
    firebase_upload_interval_seconds: int
    firebase_upload_initial_delay_seconds: int

    def as_json_dict(self) -> dict:
        raw = asdict(self)
        for key, value in raw.items():
            if isinstance(value, Path):
                raw[key] = str(value)
        return raw


def load_config() -> AppConfig:
    path = CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    if path == EXAMPLE_CONFIG_PATH:
        logger.warning(
            "config.json nicht gefunden, verwende config.example.json als Vorlage. "
            "Bitte config.json anlegen (Kopie von config.example.json)."
        )
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    config = AppConfig(
        history_record_interval_seconds=int(raw.get("history_record_interval_seconds", 60)),
        reconnect_delay_seconds=int(raw.get("reconnect_delay_seconds", 10)),
        scan_duration_seconds=int(raw.get("scan_duration_seconds", 8)),
        web_host=raw.get("web_host", "127.0.0.1"),
        web_port=int(raw.get("web_port", 5000)),
        db_path=BASE_DIR / raw.get("db_path", "data/tp357s.db"),
        devices_path=BASE_DIR / raw.get("devices_path", "data/devices.json"),
        ui_state_path=BASE_DIR / raw.get("ui_state_path", "data/ui_state.json"),
        hue_config_path=BASE_DIR / raw.get("hue_config_path", "data/hue_config.json"),
        log_path=BASE_DIR / raw.get("log_path", "data/app.log"),
        log_level=raw.get("log_level", "DEBUG"),
        log_max_bytes=int(raw.get("log_max_bytes", 5_000_000)),
        log_backup_count=int(raw.get("log_backup_count", 5)),
        device_log_buffer_size=int(raw.get("device_log_buffer_size", 500)),
        firebase_enabled=bool(raw.get("firebase_enabled", False)),
        firebase_service_account_path=BASE_DIR / raw.get("firebase_service_account_path", "firebase-service-account.json"),
        firebase_collection=raw.get("firebase_collection", "readings"),
        firebase_upload_interval_seconds=int(raw.get("firebase_upload_interval_seconds", 600)),
        firebase_upload_initial_delay_seconds=int(raw.get("firebase_upload_initial_delay_seconds", 300)),
    )
    logger.debug("Konfiguration geladen aus %s: %s", path, config.as_json_dict())
    return config
