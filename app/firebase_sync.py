"""Periodischer Upload neuer Live-/Verlaufs-Messwerte nach Firestore.

Laeuft in einem eigenen Hintergrund-Thread (nicht im BLE-asyncio-Loop, da
firebase-admin synchron/blockierend arbeitet, nicht async). Server-seitiger
Zugriff per Service-Account (Firebase Admin SDK) umgeht Firestore Security
Rules grundsaetzlich - die gelten nur fuer Client-SDKs (Browser/App), nicht
fuer Admin-Zugriff vom eigenen Server. Es wird daher nichts an den
Firestore-Regeln des Projekts veraendert oder vorausgesetzt.

Datenmodell: EINE flache Collection (Standard-Name "readings", konfigurierbar
ueber firebase_collection in config.json) fuer alle Sensoren zusammen -
ABER: nicht ein Dokument pro Messwert, sondern ein Dokument pro Sensor PRO
UPLOAD-DURCHLAUF, das ein Array aller in diesem Durchlauf neuen Messwerte
enthaelt:
    {mac, name, synced_at, count, readings: [{ts, temperature_c,
     humidity_pct, source: "live"|"history"}, ...]}

Grund: Firestore berechnet pro SCHREIBOPERATION, nicht pro Byte - ein
Dokument pro Einzelmesswert (die urspruengliche Variante) erzeugt bei
haeufigen kleinen Sync-Durchlaeufen unnoetig viele abgerechnete Writes.
Buendeln aller neuen Messwerte eines Durchlaufs in ein Dokument reduziert
das auf 1 Write pro Sensor pro Durchlauf (Standard: alle 10 Minuten) -
unabhaengig davon, ob darin 1 oder 500 Messwerte stecken. Nur bei sehr
grossen Batches (z.B. der allererste volle Verlaufsabruf) wird auf mehrere
Dokumente aufgeteilt, um das 1-MiB-Dokumentlimit von Firestore sicher
einzuhalten (siehe FIRESTORE_MAX_READINGS_PER_DOC).

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

# Konservativ weit unter Firestores 1-MiB-Dokumentlimit gehalten (grobe
# Schaetzung: ~100-150 Bytes je Messwert-Eintrag inkl. Feldnamen/Overhead;
# 5000 Eintraege bleiben damit auch mit Sicherheitsmarge weit darunter).
# Betrifft in der Praxis nur den allerersten, sehr grossen Verlaufsabruf
# eines neuen Sensors - normale Sync-Durchlaeufe haben nur wenige Eintraege
# und landen ohnehin in einem einzigen Dokument.
FIRESTORE_MAX_READINGS_PER_DOC = 5000


class FirebaseSync:
    def __init__(self, config: AppConfig, storage: Storage, devices: DeviceStore):
        self.config = config
        self.storage = storage
        self.devices = devices
        self._thread: Optional[threading.Thread] = None
        self._client = None
        self._project_id: Optional[str] = None
        self.last_upload_at: Optional[str] = None
        self.last_result: Optional[dict] = None
        self.last_verified_count: Optional[int] = None
        self.last_verify_error: Optional[str] = None

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
        self._project_id = cred.project_id
        logger.info(
            "Firebase Admin SDK initialisiert (Projekt: %s, Datenbank: (default), Collection: %s). "
            "Zum Pruefen in der Firebase-Konsole: Projekt '%s' -> Firestore Database (NICHT Realtime "
            "Database) -> Datenbank '(default)' -> Collection '%s'.",
            cred.project_id, self.config.firebase_collection, cred.project_id, self.config.firebase_collection,
        )

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
        total_readings = 0
        total_writes = 0
        per_device: dict = {}

        for record in self.devices.list():
            mac = record.mac
            last_live_id, last_history_id = self.storage.get_sync_cursor(mac)

            live_rows = self.storage.unsynced_live_rows(mac, last_live_id, limit=2000)
            history_rows = self.storage.unsynced_history_rows(mac, last_history_id, limit=2000)
            if not live_rows and not history_rows:
                continue

            synced_at = datetime.now(timezone.utc).isoformat()
            readings = []
            for r in live_rows:
                readings.append({
                    "ts": r["ts"], "temperature_c": r["temperature_c"],
                    "humidity_pct": r["humidity_pct"], "source": "live",
                })
            for r in history_rows:
                readings.append({
                    "ts": r["ts"], "temperature_c": r["temperature_c"],
                    "humidity_pct": r["humidity_pct"], "source": "history",
                })

            writes = self._write_bundled(collection, mac, record.name, synced_at, readings)
            total_readings += len(readings)
            total_writes += writes

            new_live_id = live_rows[-1]["id"] if live_rows else last_live_id
            new_history_id = history_rows[-1]["id"] if history_rows else last_history_id
            self.storage.set_sync_cursor(mac, new_live_id, new_history_id)

            per_device[mac] = {
                "readings": len(readings), "writes": writes, "live": len(live_rows), "history": len(history_rows),
            }
            logger.info(
                "Firebase-Upload fuer %s: %d live + %d history = %d Messwerte in %d Dokument(en)",
                mac, len(live_rows), len(history_rows), len(readings), writes,
            )

        self.last_upload_at = datetime.now(timezone.utc).isoformat()
        self.last_result = {"ok": True, "total_readings": total_readings, "total_writes": total_writes, "per_device": per_device}
        if total_readings:
            logger.info(
                "Firebase-Upload abgeschlossen: %d Messwerte in %d Dokument(en) geschrieben (kostenrelevant ist "
                "die Dokumentanzahl, nicht die Messwertanzahl)",
                total_readings, total_writes,
            )
        else:
            logger.debug("Firebase-Upload: nichts Neues hochzuladen")

        self._verify_remote_count(collection)

    def _verify_remote_count(self, collection) -> None:
        """Liest die Dokumentanzahl der Collection direkt aus Firestore
        zurueck (Aggregation-Query, zaehlt serverseitig, kein Download aller
        Dokumente noetig) - reiner Ehrlichkeits-Check: batch.commit() wirft
        zwar eine Exception, wenn etwas schiefgeht, aber ein Blick auf die
        tatsaechlich in Firestore vorhandene Anzahl macht fuer den Nutzer
        sofort im Dashboard sichtbar, ob die Daten WIRKLICH angekommen sind
        (z.B. falls im Firebase-Konsole aus Versehen das falsche Projekt
        oder die Realtime Database statt Firestore angeschaut wird)."""
        try:
            agg = collection.count().get()
            self.last_verified_count = int(agg[0][0].value)
            self.last_verify_error = None
            logger.info(
                "Firestore-Verifikation: Collection '%s' im Projekt '%s' enthaelt aktuell %d Dokument(e) insgesamt.",
                self.config.firebase_collection, self._project_id, self.last_verified_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Firestore-Verifikation (Dokumentanzahl auslesen) fehlgeschlagen")
            self.last_verified_count = None
            self.last_verify_error = f"{type(exc).__name__}: {exc}"

    def _write_bundled(self, collection, mac: str, name: str, synced_at: str, readings: list) -> int:
        """Schreibt alle uebergebenen Messwerte eines Sensors als moeglichst
        WENIGE Dokumente (Standardfall: genau eines, unabhaengig von der
        Anzahl Messwerte darin) statt einem Dokument je Messwert - das ist
        die abgerechnete Groesse bei Firestore, nicht die Messwertanzahl.
        Gibt die Anzahl geschriebener Dokumente zurueck."""
        if not readings:
            return 0
        chunks = [
            readings[i : i + FIRESTORE_MAX_READINGS_PER_DOC]
            for i in range(0, len(readings), FIRESTORE_MAX_READINGS_PER_DOC)
        ]
        for chunk in chunks:
            collection.document().set({
                "mac": mac, "name": name, "synced_at": synced_at,
                "count": len(chunk), "readings": chunk,
            })
        return len(chunks)

    def snapshot(self) -> dict:
        return {
            "enabled": self.config.firebase_enabled,
            "project_id": self._project_id,
            "database": "(default)",
            "collection": self.config.firebase_collection,
            "upload_interval_seconds": self.config.firebase_upload_interval_seconds,
            "initial_delay_seconds": self.config.firebase_upload_initial_delay_seconds,
            "last_upload_at": self.last_upload_at,
            "last_result": self.last_result,
            "last_verified_count_in_firestore": self.last_verified_count,
            "last_verify_error": self.last_verify_error,
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
