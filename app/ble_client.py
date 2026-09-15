"""Bluetooth-LE-Anbindung an beliebig viele ThermoPro-TP357S-Sensoren.

WICHTIG (Architektur seit der Prozess-Isolation): Die eigentliche
bleak/BLE-Kommunikation laeuft NICHT mehr in diesem Prozess, sondern in
einem separaten Kindprozess (siehe app/ble_worker.py), gestartet und
ueberwacht von der Klasse BleManager hier. Grund: bleaks WinRT-Backend
stuerzt auf Windows/Python 3.14 reproduzierbar mit einer nativen Access
Violation ab (kein Python-Traceback moeglich). In einem eigenen
Kindprozess nimmt so ein Absturz nur den BLE-Teil mit - Webserver,
Dashboard und alle bereits gespeicherten Daten bleiben unberuehrt. Der
BleManager erkennt einen toten Worker-Prozess (Supervisor-Thread,
proc.is_alive()) und startet automatisch einen neuen, der sich wieder mit
allen bekannten Geraeten verbindet.

BleManager <-> Worker-Prozess reden ausschliesslich ueber zwei
multiprocessing.Queue (Kommandos raus, Ereignisse rein). BleManager selbst
haelt keinerlei bleak-Objekte mehr, nur noch Buchfuehrung (welche MACs
sind laut letztem Status "connected", welche Verlaufsabrufe laufen gerade)
und uebernimmt weiterhin die Persistenz (AppState, Storage) sowie den
Auto-Sync-Scheduler (periodischer Verlaufs-Abruf mit Luecken-Erkennung).

Zwei Arten von Geraeten:
- "gekoppelt" (persist=True): dauerhaft in data/devices.json gespeichert,
  wird bei jedem Start automatisch wieder verbunden.
- "Probe"/Live-Test (persist=False): nur zum Reinschauen, wird NICHT in
  devices.json gespeichert.

Alles, was ueber die Bluetooth-Verbindung laeuft (jedes empfangene Rohpaket,
jedes gesendete Kommando, jeder Verbindungsstatuswechsel, jeder Fehler)
kommt als Ereignis vom Worker-Prozess rein und wird ins Logfile geschrieben
sowie in den Rohdaten-Puffer des jeweiligen Geraets (state.append_raw_log) -
sichtbar im Dashboard und ueber /api/devices/<mac>/log.
"""
import logging
import multiprocessing
import threading
import time
import uuid
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from . import protocol
from .ble_worker import worker_entrypoint
from .config import AppConfig
from .devices import DeviceStore
from .logging_setup import start_log_queue_listener
from .state import AppState
from .storage import Storage

logger = logging.getLogger(__name__)

AUTO_SYNC_TICK_SECONDS = 30
AUTO_SYNC_GAP_MARGIN_RECORDS = 10  # Sicherheitsmarge oben drauf, falls das Intervall nicht exakt stimmt
SYNC_CHECK_TEMP_TOLERANCE_C = 1.0
SYNC_CHECK_HUMIDITY_TOLERANCE_PCT = 6

WORKER_POLL_SECONDS = 2  # wie oft der Supervisor-Thread proc.is_alive() prueft
WORKER_RESTART_BACKOFF_SECONDS = 5  # Pause vor dem Neustart, falls der Worker sofort wieder abstuerzt
HISTORY_FUTURE_TIMEOUT_SECONDS = 1800 + 60  # Rueckfallnetz; der Worker selbst begrenzt frueher (siehe ble_worker.py)

# spawn statt fork: auf Windows sowieso die einzige Option, auf Linux fuer
# konsistentes/vorhersagbares Verhalten (kein Vererben von Threads/asyncio-
# Zustand aus dem Elternprozess in den Kindprozess) ebenfalls bewusst erzwungen.
MP_CTX = multiprocessing.get_context("spawn")


class BleManager:
    def __init__(self, config: AppConfig, state: AppState, storage: Storage, devices: DeviceStore):
        self.config = config
        self.state = state
        self.storage = storage
        self.devices = devices
        self.started_at = time.time()

        self._lock = threading.Lock()
        self._known_devices: Dict[str, dict] = {}  # mac -> {"name", "is_probe"}
        self._connected_macs: Set[str] = set()
        self._history_in_progress: Set[str] = set()
        self._pending_history: Dict[str, Future] = {}

        self._proc_lock = threading.Lock()
        self._proc: Optional["multiprocessing.process.BaseProcess"] = None
        self._restart_count = 0
        self._last_hello: Optional[dict] = None
        self._shutdown_requested = False

        self._cmd_queue = None
        self._event_queue = None
        self._log_queue = None
        self._log_listener = None

    # -- Lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._supervisor_loop, name="ble-supervisor", daemon=True).start()
        self._spawn_worker()
        logger.info("BLE-Supervisor gestartet (Worker-Prozess laeuft isoliert, wird automatisch neugestartet falls er abstuerzt)")

    def _spawn_worker(self) -> None:
        """Erstellt bei JEDEM (Neu-)Start frische Queues (Kommando/Ereignis/Log)
        und einen frischen Event-Reader-Thread, statt die alten wiederzuverwenden.

        Grund (per Test reproduziert, kein theoretisches Risiko): stirbt ein
        Kindprozess waehrend er in Queue.get() blockiert (dort haelt er
        intern einen prozessuebergreifenden POSIX-Semaphore/Lock, solange
        er auf Daten wartet), bleibt dieser Lock nach einem harten Abbruch
        (os._exit()/Access Violation - kein normales Queue.close()) fuer
        immer im "belegt"-Zustand haengen. Ein neuer Prozess, der dieselbe
        Queue weiterverwendet, wuerde dann selbst beim ersten get() ewig
        blockieren - das Symptom war genau das: der Worker-Prozess wurde
        nach einem simulierten Absturz zwar sauber neugestartet, hat aber
        nie wieder auf Kommandos vom Elternprozess reagiert. Frische Queues
        pro (Neu-)Start umgehen das Problem vollstaendig."""
        cmd_queue = MP_CTX.Queue()
        event_queue = MP_CTX.Queue()
        log_queue = MP_CTX.Queue()
        config_dict = {
            "reconnect_delay_seconds": self.config.reconnect_delay_seconds,
            "scan_duration_seconds": self.config.scan_duration_seconds,
            "log_level": self.config.log_level,
        }

        with self._proc_lock:
            self._cmd_queue = cmd_queue
            self._event_queue = event_queue
            old_listener = self._log_listener
            self._log_queue = log_queue
            self._log_listener = start_log_queue_listener(log_queue)

            threading.Thread(
                target=self._event_reader_loop, args=(event_queue,), name="ble-event-reader", daemon=True
            ).start()

            proc = MP_CTX.Process(
                target=worker_entrypoint,
                args=(cmd_queue, event_queue, log_queue, config_dict),
                name="ble-worker",
                daemon=True,
            )
            proc.start()
            self._proc = proc
            logger.info("BLE-Worker-Prozess gestartet (pid=%s, restart_count=%d)", proc.pid, self._restart_count)

        if old_listener is not None:
            old_listener.stop()

        with self._lock:
            known = dict(self._known_devices)
        for mac, info in known.items():
            self._send_cmd({"type": "add_device", "mac": mac, "name": info["name"]})

    def _supervisor_loop(self) -> None:
        while True:
            time.sleep(WORKER_POLL_SECONDS)
            if self._shutdown_requested:
                return
            with self._proc_lock:
                proc = self._proc
            if proc is None or proc.is_alive():
                continue
            exitcode = proc.exitcode
            logger.critical(
                "BLE-Worker-Prozess (pid=%s) ist beendet/abgestuerzt (exitcode=%s) - "
                "das Dashboard bleibt erreichbar, starte automatisch einen neuen Worker-Prozess ...",
                proc.pid, exitcode,
            )
            self._on_worker_died(exitcode)
            self._restart_count += 1
            time.sleep(WORKER_RESTART_BACKOFF_SECONDS)
            self._spawn_worker()

    def _on_worker_died(self, exitcode: Optional[int]) -> None:
        with self._lock:
            self._connected_macs.clear()
            self._history_in_progress.clear()
            known_macs = list(self._known_devices.keys())
            pending = dict(self._pending_history)
            self._pending_history.clear()

        for mac in known_macs:
            # set_error() setzt den Status ohnehin auf "error" (siehe state.py),
            # ein zusaetzliches set_status(...) davor waere nur eine Zwischenstufe,
            # die sofort wieder ueberschrieben wird - die aussagekraeftige
            # Fehlermeldung landet in last_error und im Rohdaten-Log unten.
            self.state.set_error(mac, f"BLE-Worker-Prozess abgestuerzt (exitcode={exitcode})")
            self.state.append_raw_log(mac, {
                "kind": "error",
                "note": (
                    f"BLE-Worker-Prozess abgestuerzt (exitcode={exitcode}, vermutlich nativer WinRT/"
                    f"bleak-Fehler). Automatischer Neustart des isolierten Worker-Prozesses laeuft, "
                    f"die Verbindung wird danach automatisch wiederhergestellt. Dashboard/gespeicherte "
                    f"Daten sind davon nicht betroffen."
                ),
            })
        for req_id, fut in pending.items():
            if not fut.done():
                fut.set_exception(RuntimeError(f"BLE-Worker-Prozess abgestuerzt (exitcode={exitcode})"))

    def _send_cmd(self, cmd: dict) -> None:
        if self._cmd_queue is None:
            raise RuntimeError("BLE-Manager ist noch nicht gestartet (start() nicht aufgerufen).")
        self._cmd_queue.put(cmd)

    # -- Ereignisse vom Worker-Prozess --------------------------------------------

    def _event_reader_loop(self, event_queue) -> None:
        """Liest genau EINE feste Queue-Instanz (siehe _spawn_worker fuer die
        Begruendung, warum bei jedem Worker-Neustart eine frische Queue samt
        frischem Reader-Thread erstellt wird, statt self._event_queue zu
        lesen - das koennte inzwischen schon durch einen Neustart ersetzt
        worden sein)."""
        while True:
            try:
                event = event_queue.get()
            except (EOFError, OSError):
                return
            try:
                self._handle_event(event)
            except Exception:  # noqa: BLE001
                logger.exception("Fehler bei der Verarbeitung eines Worker-Ereignisses: %r", event)

    def _handle_event(self, event: dict) -> None:
        t = event.get("type")
        if t == "hello":
            self._last_hello = event
            logger.info(
                "BLE-Worker-Prozess meldet sich: pid=%s bleak=%s python=%s",
                event.get("pid"), event.get("bleak_version"), event.get("python_version"),
            )
        elif t == "status":
            mac, status = event["mac"], event["status"]
            self.state.set_status(mac, status)
            with self._lock:
                if status == "connected":
                    self._connected_macs.add(mac)
                else:
                    self._connected_macs.discard(mac)
        elif t == "error":
            self.state.set_error(event["mac"], event.get("message"))
        elif t == "raw_log":
            self.state.append_raw_log(event["mac"], event["entry"])
        elif t == "live_reading":
            mac = event["mac"]
            reading = protocol.Reading(**event["reading"])
            self.state.set_live_reading(mac, reading)
            self.storage.insert_live_reading(mac, reading)
        elif t == "history_result":
            self._on_history_result(event)
        elif t == "history_error":
            self._on_history_error(event)
        elif t == "scanning":
            self.state.set_scanning(event["value"])
        elif t == "scan_result":
            self.state.set_scan_results(event["results"])
            self.state.set_scan_error(None)
            logger.info("Scan abgeschlossen: %d Geraete gefunden", len(event["results"]))
        elif t == "scan_error":
            self.state.set_scan_results([])
            self.state.set_scan_error(event.get("message"))
        else:
            logger.warning("Unbekanntes Ereignis vom Worker-Prozess: %r", event)

    def _on_history_result(self, event: dict) -> None:
        mac = event["mac"]
        req_id = event["req_id"]
        records = [protocol.Reading(**r) for r in event["records"]]
        clean = event["clean"]

        count = self.storage.insert_history_readings(
            mac, records, interval_seconds=self.config.history_record_interval_seconds
        )
        self.state.set_history_result(mac, count, clean=clean)
        with self._lock:
            still_connected = mac in self._connected_macs
        self.state.set_status(mac, "connected" if still_connected else "disconnected")
        self.state.append_raw_log(mac, {
            "kind": "info",
            "note": f"Verlaufsabruf abgeschlossen: {count} Datensaetze ({'sauber' if clean else 'ABGEBROCHEN, vermutlich unvollstaendig'})",
        })
        logger.info("Verlaufsabruf fuer %s abgeschlossen: %d Datensaetze (clean=%s)", mac, count, clean)

        trailing = event.get("trailing_live")
        if trailing:
            reading = protocol.Reading(**trailing)
            self.state.set_live_reading(mac, reading)
            self.storage.insert_live_reading(mac, reading)

        with self._lock:
            self._history_in_progress.discard(mac)
            fut = self._pending_history.pop(req_id, None)
        if fut is not None and not fut.done():
            fut.set_result({"count": count, "clean": clean})

    def _on_history_error(self, event: dict) -> None:
        mac = event["mac"]
        req_id = event["req_id"]
        message = event.get("message") or "Verlaufsabruf fehlgeschlagen"
        logger.error("Verlaufsabruf fuer %s fehlgeschlagen: %s", mac, message)
        self.state.set_error(mac, message)
        with self._lock:
            self._history_in_progress.discard(mac)
            still_connected = mac in self._connected_macs
            fut = self._pending_history.pop(req_id, None)
        self.state.set_status(mac, "connected" if still_connected else "disconnected")
        if fut is not None and not fut.done():
            fut.set_exception(RuntimeError(message))

    def debug_snapshot(self) -> dict:
        with self._proc_lock:
            proc = self._proc
        with self._lock:
            connected = sorted(self._connected_macs)
            in_progress = sorted(self._history_in_progress)
            known = sorted(self._known_devices.keys())
        return {
            "worker_pid": proc.pid if proc else None,
            "worker_alive": bool(proc and proc.is_alive()),
            "worker_exitcode": proc.exitcode if proc else None,
            "worker_restart_count": self._restart_count,
            "worker_hello": self._last_hello,
            "connected_clients": connected,
            "known_devices": known,
            "history_in_progress": in_progress,
            "uptime_seconds": round(time.time() - self.started_at, 1),
        }

    # -- Geraete koppeln/entfernen -------------------------------------------------

    def add_device(self, mac: str, name: str, is_probe: bool = False) -> None:
        mac = mac.upper()
        logger.info("Fuege Geraet hinzu: mac=%s name=%r is_probe=%s", mac, name, is_probe)
        self.state.ensure_device(mac, name, is_probe=is_probe)
        with self._lock:
            self._known_devices[mac] = {"name": name, "is_probe": is_probe}
        self._send_cmd({"type": "add_device", "mac": mac, "name": name})

    def remove_device(self, mac: str) -> None:
        mac = mac.upper()
        logger.info("Entferne Geraet: mac=%s", mac)
        self.state.remove_device(mac)
        with self._lock:
            self._known_devices.pop(mac, None)
            self._connected_macs.discard(mac)
        self._send_cmd({"type": "remove_device", "mac": mac})

    # -- Scannen --------------------------------------------------------------------

    def scan(self, duration: Optional[int] = None) -> None:
        duration = duration or self.config.scan_duration_seconds
        logger.info("Starte BLE-Scan (Dauer=%ss)", duration)
        self._send_cmd({"type": "scan", "duration": duration})

    # -- Verlaufsabruf ----------------------------------------------------------------

    def request_history(self, mac: str, count: int = 500) -> Future:
        mac = mac.upper()
        logger.info("Fordere Verlauf an: mac=%s count=%d", mac, count)
        req_id = uuid.uuid4().hex
        fut: Future = Future()
        with self._lock:
            self._history_in_progress.add(mac)
            self._pending_history[req_id] = fut
        self._send_cmd({"type": "request_history", "mac": mac, "count": count, "req_id": req_id})
        return fut

    # -- Rohbefehl senden ---------------------------------------------------------------

    def write_raw(self, mac: str, data: bytes) -> None:
        mac = mac.upper()
        logger.info("Sende Rohbefehl an %s: %s", mac, data.hex())
        self._send_cmd({"type": "write_raw", "mac": mac, "hex": data.hex()})

    # -- Auto-Sync (periodischer Verlaufs-Abruf mit Luecken-Erkennung) -------------------

    def start_auto_sync(self) -> None:
        threading.Thread(target=self._auto_sync_loop, name="ble-auto-sync", daemon=True).start()

    def _auto_sync_loop(self) -> None:
        logger.info("Auto-Sync-Scheduler gestartet (Tick=%ds)", AUTO_SYNC_TICK_SECONDS)
        while True:
            try:
                self._auto_sync_tick()
            except Exception:  # noqa: BLE001
                logger.exception("Fehler im Auto-Sync-Scheduler-Tick")
            time.sleep(AUTO_SYNC_TICK_SECONDS)

    def _auto_sync_tick(self) -> None:
        now = datetime.now(timezone.utc)
        for entry in self.state.list_auto_sync_devices():
            mac = entry["mac"]
            with self._lock:
                connected = mac in self._connected_macs
                busy = mac in self._history_in_progress
            if not connected or busy:
                continue  # nicht verbunden oder laeuft schon (z.B. manueller Abruf) - naechster Tick

            last_attempt = entry["last_auto_sync_at"]
            interval = entry["auto_sync_interval_seconds"]
            if last_attempt:
                elapsed = (now - datetime.fromisoformat(last_attempt)).total_seconds()
                if elapsed < interval:
                    continue

            self._run_auto_sync_for_device(mac, entry["last_synced_ts"], interval, now)

    def _run_auto_sync_for_device(
        self, mac: str, last_synced_ts: Optional[str], interval_seconds: int, now: datetime
    ) -> None:
        record_interval = max(1, self.config.history_record_interval_seconds)
        if last_synced_ts:
            gap_seconds = (now - datetime.fromisoformat(last_synced_ts)).total_seconds()
        else:
            gap_seconds = interval_seconds
        gap_seconds = max(gap_seconds, record_interval)
        count = int(gap_seconds // record_interval) + AUTO_SYNC_GAP_MARGIN_RECORDS
        count = max(10, min(0xFFFF, count))

        logger.info(
            "Auto-Sync: fordere Verlauf fuer %s an (Luecke=%.0fs seit %s, angefragt=%d Datensaetze)",
            mac, gap_seconds, last_synced_ts or "nie", count,
        )
        self.state.append_raw_log(mac, {"kind": "info", "note": f"Auto-Sync: fordere {count} Datensaetze an (Luecke {gap_seconds:.0f}s)"})

        fut = self.request_history(mac, count)
        try:
            result = fut.result(timeout=HISTORY_FUTURE_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Auto-Sync fuer %s fehlgeschlagen", mac)
            self.state.set_auto_sync_result(mac, {"ok": False, "error": str(exc), "requested": count})
            return

        self.state.set_auto_sync_result(mac, {"ok": True, "requested": count, **result})

        if result["clean"]:
            new_synced_ts = now.isoformat()
            self.state.set_last_synced(mac, new_synced_ts)
            self.devices.set_last_synced(mac, new_synced_ts)
            logger.info("Auto-Sync fuer %s abgeschlossen: %d Datensaetze, last_synced_ts=%s", mac, result["count"], new_synced_ts)
            self._check_sync(mac)
        else:
            logger.warning(
                "Auto-Sync fuer %s unvollstaendig (clean=%s, %d Datensaetze) - "
                "last_synced_ts bleibt unveraendert, naechster Versuch deckt eine groessere Luecke ab",
                mac, result["clean"], result["count"],
            )

    def _check_sync(self, mac: str) -> None:
        """Vergleicht den neuesten (per Zeitstempel-Schaetzung) Verlaufs-
        Datensatz mit dem aktuellen Live-Wert. Liegen Temperatur/Feuchte nah
        beieinander, deutet das darauf hin, dass die Zeitstempel-Rekonstruktion
        (angenommenes Aufnahmeintervall, history_record_interval_seconds)
        einigermassen zur Realitaet passt - eine Plausibilitaetspruefung, keine
        automatische Korrektur."""
        live = self.state.get_last_live(mac)
        history = self.storage.recent_history(mac, limit=1)
        if not live or not history:
            return
        newest = history[0]
        temp_diff = abs(live["temperature_c"] - newest["temperature_c"])
        hum_diff = abs(live["humidity_pct"] - newest["humidity_pct"])
        ok = temp_diff <= SYNC_CHECK_TEMP_TOLERANCE_C and hum_diff <= SYNC_CHECK_HUMIDITY_TOLERANCE_PCT
        result = {
            "ok": ok,
            "temp_diff": round(temp_diff, 2),
            "humidity_diff": round(hum_diff, 2),
            "live": live,
            "newest_history": newest,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        self.state.set_sync_check(mac, result)
        self.state.append_raw_log(mac, {
            "kind": "info",
            "note": f"Sync-Check: {'OK' if ok else 'ABWEICHUNG'} (dT={temp_diff:.2f}C dH={hum_diff:.2f}%)",
        })
        logger.info("Sync-Check fuer %s: %s (dT=%.2f dH=%.2f)", mac, "OK" if ok else "ABWEICHUNG", temp_diff, hum_diff)
