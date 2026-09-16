"""Persistiert rein kosmetischen Dashboard-Zustand (welche Panels sind
eingeklappt, welcher Reiter ist aktiv) in data/ui_state.json, damit das
beim naechsten Start des Servers/Oeffnen der Oberflaeche wiederhergestellt
wird - bewusst serverseitig statt nur im Browser (localStorage), da die
Anforderung "fuer den naechsten Start des Servers gespeichert" war, nicht
nur "im selben Browser"."""
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_TAB = "sensors"


class UiState:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._collapsed: Dict[str, bool] = {}
        self._active_tab: str = DEFAULT_TAB
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8-sig") as f:
                raw: Dict[str, Any] = json.load(f)
            collapsed = raw.get("collapsed")
            if isinstance(collapsed, dict):
                self._collapsed = {str(k): bool(v) for k, v in collapsed.items()}
            active_tab = raw.get("active_tab")
            if isinstance(active_tab, str) and active_tab:
                self._active_tab = active_tab
        except Exception:  # noqa: BLE001
            logger.exception("UI-Zustand (%s) konnte nicht geladen werden, verwende Defaults", self.path)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"collapsed": self._collapsed, "active_tab": self._active_tab}, f, indent=2)
            tmp.replace(self.path)
        except Exception:  # noqa: BLE001
            logger.exception("UI-Zustand (%s) konnte nicht gespeichert werden", self.path)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"collapsed": dict(self._collapsed), "active_tab": self._active_tab}

    def update(self, *, collapsed: Dict[str, bool] = None, active_tab: str = None) -> None:
        with self._lock:
            if collapsed:
                for panel_id, value in collapsed.items():
                    self._collapsed[str(panel_id)] = bool(value)
            if active_tab:
                self._active_tab = str(active_tab)
            self._save()
