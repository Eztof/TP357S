"""Periodischer Upload neuer Live-/Verlaufs-Messwerte nach Firestore.

Laeuft in einem eigenen Hintergrund-Thread (nicht im BLE-asyncio-Loop, da
firebase-admin synchron/blockierend arbeitet, nicht async). Server-seitiger
Zugriff per Service-Account (Firebase Admin SDK) umgeht Firestore Security
Rules grundsaetzlich - die gelten nur fuer Client-SDKs (Browser/App), nicht
fuer Admin-Zugriff vom eigenen Server. Es wird daher nichts an den
Firestore-Regeln des Projekts veraendert oder vorausgesetzt.

Datenmodell: EINE flache Collection (Standard-Name "readings", konfigurierbar
ueber firebase_collection in config.json) fuer alle Sensoren zusammen, ein
Dokument pro Messwert:
    {mac, name, ts, temperature_c, humidity_pct, source: "live"|"history", synced_at}

Fortschritt wird lokal in SQLite verfolgt (Storage.get_sync_cursor/
set_sync_cursor, Tabelle firebase_sync_state: letzte hochgeladene id je
Tabelle und Sensor) - kein Firestore-Read noetig, um zu wissen, was schon
hochgeladen wurde (spart Kosten/Latenz, funktioniert auch offline weiter
Daten zu sammeln, bis der naechste Upload-Tick laeuft)."""
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from .config import AppConfig
from .devices import DeviceStore
from .storage import Storage

logger = logging.getLogger(__name__)

FIRESTORE_BATCH_LIMIT = 500  # harte Firestore-Grenze pro Batch-Write


class FirebaseSync:
    def __init__(self, config: AppConfig, storage: Storage, devices: DeviceStore):
        self.config = config
        self.storage = storage
        self.devices = devices
        self._thread: Optional[threading.Thread] = None
        self._client = None
        self.last_upload_at: Optional[str] = None
        self.last_result: Optional[dict] = None

    def start(self) -> None:
        if not self.config.firebase_enabled:
            logger.info("Firebase-Upload deaktiviert (firebase_enabled=false in config.json)")
            return
        self._thread = threading.Thread(target=self._run_loop, name="firebase-sync", daemon=True)
        self._thread.start()

    def _init_client(self) -> None:
        import firebase_admin
        from firebase_admin import credentials, firestore

        path = self.config.firebase_service_account_path
        if not path.exists():
            raise FileNotFoundError(f"Firebase-Service-Account-Datei nicht gefunden: {path}")
        cred = credentials.Certificate(str(path))
        app = firebase_admin.initialize_app(cred)
        self._client = firestore.client(app)
        logger.info("Firebase Admin SDK initialisiert (Projekt: %s, Collection: %s)",
                    cred.project_id, self.config.firebase_collection)

    def _run_loop(self) -> None:
        try:
            self._init_client()
        except Exception:
            logger.exception("Firebase-Upload konnte nicht initialisiert werden, Upload bleibt deaktiviert")
            self.last_result = {"ok": False, "error": "Initialisierung fehlgeschlagen (siehe Log)"}
            return

        logger.info(
            "Firebase-Upload-Scheduler gestartet: erster Lauf in %ds, danach alle %ds",
            self.config.firebase_upload_initial_delay_seconds, self.config.firebase_upload_interval_seconds,
        )
        time.sleep(self.config.firebase_upload_initial_delay_seconds)
        while True:
            try:
                self._upload_tick()
            except Exception:
                logger.exception("Fehler beim Firebase-Upload")
                self.last_result = {"ok": False, "error": "siehe Log"}
            time.sleep(self.config.firebase_upload_interval_seconds)

    def _upload_tick(self) -> None:
        collection = self._client.collection(self.config.firebase_collection)
        total_uploaded = 0
        per_device: dict = {}

        for record in self.devices.list():
            mac = record.mac
            last_live_id, last_history_id = self.storage.get_sync_cursor(mac)

            live_rows = self.storage.unsynced_live_rows(mac, last_live_id, limit=2000)
            history_rows = self.storage.unsynced_history_rows(mac, last_history_id, limit=2000)
            if not live_rows and not history_rows:
                continue

            synced_at = datetime.now(timezone.utc).isoformat()
            docs = []
            for r in live_rows:
                docs.append({
                    "mac": mac, "name": record.name, "ts": r["ts"],
                    "temperature_c": r["temperature_c"], "humidity_pct": r["humidity_pct"],
                    "source": "live", "synced_at": synced_at,
                })
            for r in history_rows:
                docs.append({
                    "mac": mac, "name": record.name, "ts": r["ts"],
                    "temperature_c": r["temperature_c"], "humidity_pct": r["humidity_pct"],
                    "source": "history", "synced_at": synced_at,
                })

            uploaded = self._write_batched(collection, docs)
            total_uploaded += uploaded

            new_live_id = live_rows[-1]["id"] if live_rows else last_live_id
            new_history_id = history_rows[-1]["id"] if history_rows else last_history_id
            self.storage.set_sync_cursor(mac, new_live_id, new_history_id)

            per_device[mac] = {"uploaded": uploaded, "live": len(live_rows), "history": len(history_rows)}
            logger.info(
                "Firebase-Upload fuer %s: %d live + %d history = %d Dokumente",
                mac, len(live_rows), len(history_rows), uploaded,
            )

        self.last_upload_at = datetime.now(timezone.utc).isoformat()
        self.last_result = {"ok": True, "total_uploaded": total_uploaded, "per_device": per_device}
        if total_uploaded:
            logger.info("Firebase-Upload abgeschlossen: %d Dokumente insgesamt", total_uploaded)
        else:
            logger.debug("Firebase-Upload: nichts Neues hochzuladen")

    def _write_batched(self, collection, docs: list) -> int:
        uploaded = 0
        for i in range(0, len(docs), FIRESTORE_BATCH_LIMIT):
            chunk = docs[i:i + FIRESTORE_BATCH_LIMIT]
            batch = self._client.batch()
            for doc in chunk:
                batch.set(collection.document(), doc)
            batch.commit()
            uploaded += len(chunk)
        return uploaded

    def snapshot(self) -> dict:
        return {
            "enabled": self.config.firebase_enabled,
            "collection": self.config.firebase_collection,
            "upload_interval_seconds": self.config.firebase_upload_interval_seconds,
            "initial_delay_seconds": self.config.firebase_upload_initial_delay_seconds,
            "last_upload_at": self.last_upload_at,
            "last_result": self.last_result,
        }

    def trigger_now(self) -> None:
        """Fuer den manuellen 'Jetzt hochladen'-Button im Dashboard - laeuft
        in einem eigenen Thread, blockiert also den Flask-Request nicht."""
        threading.Thread(target=self._safe_manual_upload, name="firebase-sync-manual", daemon=True).start()

    def _safe_manual_upload(self) -> None:
        if self._client is None:
            try:
                self._init_client()
            except Exception:
                logger.exception("Firebase-Upload (manuell) konnte nicht initialisiert werden")
                self.last_result = {"ok": False, "error": "Initialisierung fehlgeschlagen (siehe Log)"}
                return
        try:
            self._upload_tick()
        except Exception:
            logger.exception("Fehler beim manuellen Firebase-Upload")
            self.last_result = {"ok": False, "error": "siehe Log"}
