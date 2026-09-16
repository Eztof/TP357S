"""Speichert das hochgeladene Grundriss-Bild und die Positionen (x/y als
Bruchteil 0..1 der Bildgroesse, aufloesungsunabhaengig) der darauf per
Drag&Drop platzierten Hue-Ressourcen (Lampen, Sensoren). Reiner
Anzeige-/Bedien-Zustand, keine Zugangsdaten - trotzdem lokal in data/, weil
er (anders als hue_config.json) erst zur Laufzeit ueber das Dashboard
entsteht."""
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MiB - grosszuegig fuer ein Foto/Scan


class HueLayout:
    def __init__(self, layout_dir: Path):
        self.layout_dir = layout_dir
        self.meta_path = layout_dir / "layout.json"
        self._lock = threading.Lock()
        self._positions: Dict[str, Dict[str, float]] = {}
        self._image_filename: Optional[str] = None
        self._load()

    def _load(self) -> None:
        if not self.meta_path.exists():
            return
        try:
            with open(self.meta_path, "r", encoding="utf-8-sig") as f:
                raw: Dict[str, Any] = json.load(f)
            positions = raw.get("positions")
            if isinstance(positions, dict):
                self._positions = {
                    str(k): {"x": float(v["x"]), "y": float(v["y"])}
                    for k, v in positions.items()
                    if isinstance(v, dict) and "x" in v and "y" in v
                }
            image_filename = raw.get("image_filename")
            if isinstance(image_filename, str) and image_filename:
                self._image_filename = image_filename
        except Exception:  # noqa: BLE001
            logger.exception("Hue-Layout (%s) konnte nicht geladen werden", self.meta_path)

    def _save(self) -> None:
        try:
            self.layout_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.meta_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"image_filename": self._image_filename, "positions": self._positions}, f, indent=2)
            tmp.replace(self.meta_path)
        except Exception:  # noqa: BLE001
            logger.exception("Hue-Layout (%s) konnte nicht gespeichert werden", self.meta_path)

    # -- Grundriss-Bild ------------------------------------------------------

    def set_image(self, filename: str, data: bytes) -> None:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError(f"Nicht unterstuetzter Bildtyp: {ext or '(keine Endung)'}")
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(f"Bild zu gross ({len(data)} Bytes, Limit {MAX_IMAGE_BYTES})")
        self.layout_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            # Altes Bild mit ggf. anderer Endung entfernen, bevor das neue
            # geschrieben wird - sonst blieben bei einem Endungswechsel
            # (z.B. png -> jpg) beide Dateien liegen.
            if self._image_filename:
                old_path = self.layout_dir / self._image_filename
                if old_path.exists():
                    old_path.unlink()
            new_filename = f"floorplan{ext}"
            (self.layout_dir / new_filename).write_bytes(data)
            self._image_filename = new_filename
            self._save()
        logger.info("Hue-Grundriss-Bild gespeichert: %s (%d Bytes)", new_filename, len(data))

    def get_image_path(self) -> Optional[Path]:
        with self._lock:
            if not self._image_filename:
                return None
            path = self.layout_dir / self._image_filename
        return path if path.exists() else None

    def remove_image(self) -> None:
        with self._lock:
            if self._image_filename:
                path = self.layout_dir / self._image_filename
                if path.exists():
                    path.unlink()
                self._image_filename = None
            self._positions = {}
            self._save()
        logger.info("Hue-Grundriss-Bild entfernt (inkl. aller Positionen)")

    # -- Positionen ------------------------------------------------------------

    def get_positions(self) -> Dict[str, Dict[str, float]]:
        with self._lock:
            return {k: dict(v) for k, v in self._positions.items()}

    def set_position(self, resource_id: str, x: float, y: float) -> None:
        x = max(0.0, min(1.0, float(x)))
        y = max(0.0, min(1.0, float(y)))
        with self._lock:
            self._positions[resource_id] = {"x": x, "y": y}
            self._save()

    def remove_position(self, resource_id: str) -> None:
        with self._lock:
            if resource_id in self._positions:
                del self._positions[resource_id]
                self._save()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "has_image": self._image_filename is not None,
                "image_filename": self._image_filename,
                "positions": {k: dict(v) for k, v in self._positions.items()},
            }
