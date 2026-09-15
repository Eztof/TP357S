"""Bluetooth-LE-Anbindung an beliebig viele ThermoPro-TP357S-Sensoren.

Laeuft in einem eigenen Thread mit eigener asyncio-Event-Loop (bleak ist
async, der Flask-Server laeuft in seinem eigenen Thread). Pro Geraet (MAC-
Adresse) laeuft eine eigene Verbindungs-Task nebenlaeufig in derselben
Event-Loop; zusaetzlich kann jederzeit ein BLE-Scan gestartet werden.

Zwei Arten von Geraeten:
- "paediert" (persist=True): dauerhaft in data/devices.json gespeichert,
  wird bei jedem Start automatisch wieder verbunden.
- "Probe"/Live-Test (persist=False): nur zum Reinschauen, wird NICHT in
  devices.json gespeichert; ueber /api/probe/<mac>/promote kann eine
  laufende Probe jederzeit in eine dauerhafte Kopplung umgewandelt werden.

Alles, was ueber die Bluetooth-Verbindung laeuft (jedes empfangene Rohpaket,
jedes gesendete Kommando, jeder Verbindungsstatuswechsel, jeder Fehler mit
vollem Traceback) wird sowohl ins Logfile geschrieben als auch in den
Rohdaten-Puffer des jeweiligen Geraets (state.append_raw_log) - sichtbar im
Dashboard und ueber /api/devices/<mac>/log.
"""
import asyncio
import functools
import importlib.metadata
import logging
import platform
import sys
import threading
import time
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import Dict, Optional

from bleak import BleakClient, BleakScanner

from . import protocol
from .config import AppConfig
from .devices import DeviceStore
from .logging_setup import install_asyncio_exception_handler
from .state import AppState
from .storage import Storage

logger = logging.getLogger(__name__)

HISTORY_IDLE_TIMEOUT_SECONDS = 20  # Abbruch, wenn so lange kein neues Paket mehr kam
HISTORY_MIN_OVERALL_TIMEOUT_SECONDS = 120
HISTORY_MAX_OVERALL_TIMEOUT_SECONDS = 1800  # Sicherheitsnetz, falls die Verbindung komplett haengt

AUTO_SYNC_TICK_SECONDS = 30
AUTO_SYNC_GAP_MARGIN_RECORDS = 10  # Sicherheitsmarge oben drauf, falls das Intervall nicht exakt stimmt
SYNC_CHECK_TEMP_TOLERANCE_C = 1.0
SYNC_CHECK_HUMIDITY_TOLERANCE_PCT = 6


def _bleak_version() -> str:
    try:
        return importlib.metadata.version("bleak")
    except Exception:  # noqa: BLE001
        return "unbekannt"


BLEAK_VERSION = _bleak_version()


class BleManager:
    def __init__(self, config: AppConfig, state: AppState, storage: Storage, devices: DeviceStore):
        self.config = config
        self.state = state
        self.storage = storage
        self.devices = devices
        self.started_at = time.time()

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

        self._clients: Dict[str, BleakClient] = {}
        self._device_tasks: Dict[str, "asyncio.Task"] = {}
        self._history_state: Dict[str, dict] = {}

        logger.info(
            "BleManager erstellt. Python=%s Plattform=%s bleak=%s",
            sys.version.replace("\n", " "), platform.platform(), BLEAK_VERSION,
        )

    # -- Lifecycle -------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, name="ble-loop", daemon=True)
        self._thread.start()
        ready = self._ready.wait(timeout=5)
        logger.info("BLE-Event-Loop-Thread gestartet (bereit=%s)", ready)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        install_asyncio_exception_handler(self._loop)
        self._ready.set()
        logger.debug("asyncio-Event-Loop laeuft jetzt (run_forever)")
        try:
            self._loop.run_forever()
        except Exception:
            logger.exception("BLE-Event-Loop ist mit einer Exception abgestuerzt")
            raise
        finally:
            logger.warning("BLE-Event-Loop wurde beendet (run_forever() ist zurueckgekehrt)")

    def _run_coro(self, coro) -> Future:
        if not self._loop:
            raise RuntimeError("BLE-Event-Loop laeuft noch nicht.")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def start_auto_sync(self) -> None:
        """Startet den Auto-Sync-Scheduler (periodischer Verlaufs-Abruf mit
        Luecken-Erkennung fuer alle Geraete, bei denen das im Dashboard
        eingeschaltet ist). Einmalig nach start() aufzurufen."""
        self._run_coro(self._auto_sync_loop())

    async def _auto_sync_loop(self) -> None:
        logger.info("Auto-Sync-Scheduler gestartet (Tick=%ds)", AUTO_SYNC_TICK_SECONDS)
        while True:
            try:
                await self._auto_sync_tick()
            except Exception:  # noqa: BLE001
                logger.exception("Fehler im Auto-Sync-Scheduler-Tick")
            await asyncio.sleep(AUTO_SYNC_TICK_SECONDS)

    async def _auto_sync_tick(self) -> None:
        now = datetime.now(timezone.utc)
        for entry in self.state.list_auto_sync_devices():
            mac = entry["mac"]
            if mac not in self._clients:
                continue  # nicht verbunden - beim naechsten Tick erneut versuchen

            hstate = self._history_state.get(mac)
            if hstate and hstate.get("in_progress"):
                continue  # laeuft schon (z.B. manueller Abruf gerade aktiv)

            last_attempt = entry["last_auto_sync_at"]
            interval = entry["auto_sync_interval_seconds"]
            if last_attempt:
                elapsed = (now - datetime.fromisoformat(last_attempt)).total_seconds()
                if elapsed < interval:
                    continue

            await self._run_auto_sync_for_device(mac, entry["last_synced_ts"], interval, now)

    async def _run_auto_sync_for_device(
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

        try:
            result = await self._request_history_async(mac, count)
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

    def debug_snapshot(self) -> dict:
        return {
            "loop_running": bool(self._loop and self._loop.is_running()),
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "connected_clients": sorted(self._clients.keys()),
            "active_device_tasks": {mac: not task.done() for mac, task in self._device_tasks.items()},
            "history_in_progress": [mac for mac, h in self._history_state.items() if h.get("in_progress")],
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "bleak_version": BLEAK_VERSION,
        }

    # -- Geraete koppeln/entfernen -----------------------------------------------

    def add_device(self, mac: str, name: str, is_probe: bool = False) -> None:
        mac = mac.upper()
        logger.info("Fuege Geraet hinzu: mac=%s name=%r is_probe=%s", mac, name, is_probe)
        self.state.ensure_device(mac, name, is_probe=is_probe)
        self._run_coro(self._spawn_device_task(mac))

    async def _spawn_device_task(self, mac: str) -> None:
        existing = self._device_tasks.get(mac)
        if existing and not existing.done():
            logger.debug("Verbindungs-Task fuer %s laeuft bereits, ueberspringe", mac)
            return
        self._device_tasks[mac] = asyncio.create_task(self._device_loop(mac), name=f"ble-device-{mac}")

    def remove_device(self, mac: str) -> None:
        mac = mac.upper()
        logger.info("Entferne Geraet: mac=%s", mac)
        self.state.remove_device(mac)
        self._run_coro(self._cancel_device_task(mac))

    async def _cancel_device_task(self, mac: str) -> None:
        task = self._device_tasks.pop(mac, None)
        if task:
            task.cancel()
        client = self._clients.pop(mac, None)
        if client:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                logger.exception("Fehler beim Trennen von %s", mac)

    # -- Verbindung + Live-Werte ------------------------------------------------

    async def _device_loop(self, mac: str) -> None:
        while True:
            try:
                await self._connect_and_listen(mac)
            except asyncio.CancelledError:
                logger.info("Verbindungs-Task fuer %s abgebrochen (Geraet entfernt/gestoppt)", mac)
                raise
            except Exception as exc:  # noqa: BLE001 - Verbindungsfehler duerfen die Loop nicht beenden
                logger.exception("BLE-Verbindungsfehler bei %s", mac)
                self.state.set_error(mac, f"{type(exc).__name__}: {exc}")
                self.state.append_raw_log(mac, {"kind": "error", "note": f"{type(exc).__name__}: {exc}"})
            self.state.set_status(mac, "disconnected")
            logger.debug("Warte %ss vor erneutem Verbindungsversuch zu %s", self.config.reconnect_delay_seconds, mac)
            await asyncio.sleep(self.config.reconnect_delay_seconds)

    @staticmethod
    def _build_client(mac: str) -> BleakClient:
        """Baut den BleakClient fuer eine Verbindung.

        winrt=dict(use_cached_services=False) deaktiviert auf Windows den
        WinRT-GATT-Geraete-Cache (verifiziert gegen bleak's
        WinRTClientArgs/BleakClientWinRT: winrt["use_cached_services"]
        steuert BluetoothCacheMode.Uncached vs. Cached bei der Service-
        Discovery). Ein bekannter, dokumentierter Workaround gegen native
        Abstuerze (Access Violation) durch einen korrupten Geraete-Cache
        im Windows-Bluetooth-Stack. Auf Nicht-Windows-Backends wird das
        Argument von bleak klaglos ignoriert (generisches **kwargs im
        gemeinsamen BleakClient.__init__), daher ohne Plattform-
        Unterscheidung immer gesetzt."""
        return BleakClient(mac, timeout=20.0, winrt=dict(use_cached_services=False))

    async def _connect_and_listen(self, mac: str) -> None:
        logger.info("Verbinde zu %s ...", mac)
        self.state.set_status(mac, "connecting")
        self.state.append_raw_log(mac, {"kind": "info", "note": "Verbindungsversuch gestartet"})

        # Bewusst KEIN eigener Scan zur Adressaufloesung vor dem Connect
        # (frueher hier vorhanden, per BleakScanner.find_device_by_address):
        # das wiederholte Erstellen/Zerstoeren von WinRT-Scan-Objekten bei
        # jedem (Re-)Verbindungsversuch korrelierte real mit dem nativen
        # Absturz auf Windows/Python 3.14. BleakClient(mac) direkt mit der
        # Adresse verbinden ist die von bleak selbst unterstuetzte Methode;
        # ein gelegentlicher BleakDeviceNotFoundError wird unten wie jeder
        # andere Verbindungsfehler abgefangen und nach reconnect_delay_seconds
        # erneut versucht.
        client = self._build_client(mac)

        logger.debug("Rufe client.connect() fuer %s auf ...", mac)
        self.state.append_raw_log(mac, {"kind": "info", "note": "rufe client.connect() auf"})
        await client.connect()
        logger.info("client.connect() fuer %s zurueckgekehrt (verbunden=%s)", mac, client.is_connected)
        self.state.append_raw_log(mac, {"kind": "info", "note": "client.connect() zurueckgekehrt"})

        try:
            self._clients[mac] = client
            self.state.set_status(mac, "connected")
            self.state.set_error(mac, None)
            logger.info("Mit %s verbunden", mac)

            logger.debug("Aktiviere Notify fuer %s auf %s ...", mac, protocol.NOTIFY_CHAR_UUID)
            self.state.append_raw_log(mac, {"kind": "info", "note": "aktiviere Notify"})
            await client.start_notify(protocol.NOTIFY_CHAR_UUID, functools.partial(self._on_notify, mac))
            logger.debug("Notify aktiviert fuer %s", mac)
            self.state.append_raw_log(mac, {"kind": "info", "note": "Notify aktiviert"})

            while client.is_connected:
                await asyncio.sleep(1)

            logger.warning("Verbindung zu %s wurde vom Geraet/Stack beendet", mac)
        finally:
            self._clients.pop(mac, None)
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                logger.exception("Fehler beim Trennen von %s nach Verbindungsende", mac)

    def _on_notify(self, mac: str, _handle: int, data: bytearray) -> None:
        packet = bytes(data)
        hex_str = packet.hex()

        hstate = self._history_state.get(mac)
        if hstate and hstate["in_progress"]:
            logger.debug("RX (Historie) %s: %s (%d Bytes)", mac, hex_str, len(packet))
            self.state.append_raw_log(mac, {"kind": "notify-history", "hex": hex_str, "len": len(packet)})
            self._handle_history_or_end(mac, packet, hstate)
            return

        reading = protocol.decode_live(packet)
        if reading is not None:
            logger.debug(
                "RX (Live) %s: %s -> temp=%.1f hum=%d batt=%s",
                mac, hex_str, reading.temperature_c, reading.humidity_pct, reading.battery_pct,
            )
            self.state.append_raw_log(mac, {
                "kind": "notify-live", "hex": hex_str, "len": len(packet),
                "decoded": {
                    "temperature_c": reading.temperature_c,
                    "humidity_pct": reading.humidity_pct,
                    "battery_pct": reading.battery_pct,
                },
            })
            self.state.set_live_reading(mac, reading)
            self.storage.insert_live_reading(mac, reading)
        else:
            logger.debug("RX (nicht dekodierbar) %s: %s (%d Bytes)", mac, hex_str, len(packet))
            self.state.append_raw_log(mac, {"kind": "notify-undecoded", "hex": hex_str, "len": len(packet)})

    def _handle_history_or_end(self, mac: str, packet: bytes, hstate: dict) -> None:
        if hstate["packet_index"] == 0 or protocol.is_history_header(packet):
            is_first = hstate["packet_index"] == 0
            records, is_end = protocol.process_history_packet(packet, is_first_packet=is_first)
            hstate["packet_index"] += 1
            hstate["buffer"].extend(records)
            logger.debug(
                "Historie-Paket #%d von %s: %d Datensaetze, Ende=%s",
                hstate["packet_index"], mac, len(records), is_end,
            )
            if is_end:
                self._finish_history(mac, hstate)
            return

        live = protocol.decode_live(packet)
        if live is not None:
            logger.debug("Historie von %s implizit beendet (Live-Paket empfangen)", mac)
            self._finish_history(mac, hstate, trailing_live=live)
            return

        records, is_end = protocol.process_history_packet(packet, is_first_packet=False)
        hstate["packet_index"] += 1
        hstate["buffer"].extend(records)
        logger.debug(
            "Historie-Paket #%d von %s: %d Datensaetze, Ende=%s",
            hstate["packet_index"], mac, len(records), is_end,
        )
        if is_end:
            self._finish_history(mac, hstate)

    def _finish_history(
        self, mac: str, hstate: dict, trailing_live: Optional[protocol.Reading] = None, clean: bool = True
    ) -> None:
        """clean=True: sauberes Ende (explizite 66 66-Terminierung oder ein
        Live-Paket als implizites Ende). clean=False: wir haben selbst
        abgebrochen (Idle- oder Gesamt-Timeout) - das Geraet hat vermutlich
        noch mehr Daten, die Uebertragung war unterbrochen/unvollstaendig."""
        records = hstate["buffer"]
        hstate["in_progress"] = False
        hstate["clean"] = clean

        count = self.storage.insert_history_readings(
            mac, records, interval_seconds=self.config.history_record_interval_seconds
        )
        self.state.set_history_result(mac, count, clean=clean)
        self.state.set_status(mac, "connected")
        self.state.append_raw_log(mac, {
            "kind": "info",
            "note": f"Verlaufsabruf abgeschlossen: {count} Datensaetze ({'sauber' if clean else 'ABGEBROCHEN, vermutlich unvollstaendig'})",
        })
        logger.info("Verlaufsabruf fuer %s abgeschlossen: %d Datensaetze (clean=%s)", mac, count, clean)

        hstate["done_event"].set()

        if trailing_live is not None:
            self.state.set_live_reading(mac, trailing_live)
            self.storage.insert_live_reading(mac, trailing_live)

    # -- Scannen nach Geraeten in der Naehe --------------------------------------

    def scan(self, duration: Optional[int] = None) -> Future:
        duration = duration or self.config.scan_duration_seconds
        logger.info("Starte BLE-Scan (Dauer=%ss)", duration)
        return self._run_coro(self._scan_async(duration))

    async def _scan_async(self, duration: int) -> None:
        self.state.set_scanning(True)
        try:
            found = await BleakScanner.discover(timeout=duration, return_adv=True, scanning_mode="active")
            results = []
            for device, adv in found.values():
                entry = self._describe_scan_result(device, adv)
                results.append(entry)
                logger.debug("Scan-Treffer: %s", entry)
            results.sort(key=lambda d: (d["rssi"] is None, -(d["rssi"] or -999)))
            self.state.set_scan_results(results)
            self.state.set_scan_error(None)
            logger.info("Scan abgeschlossen: %d Geraete gefunden", len(results))
        except Exception as exc:  # noqa: BLE001
            logger.exception("BLE-Scan fehlgeschlagen")
            self.state.set_scan_results([])
            self.state.set_scan_error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self.state.set_scanning(False)

    @staticmethod
    def _describe_scan_result(device, adv) -> dict:
        """Baut ein moeglichst vollstaendiges, JSON-sicheres Dict aus den
        von bleak gelieferten Rohdaten (Debug-Zweck: lieber zu viel als zu
        wenig Information)."""

        def safe(fn, default=None):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                return default

        manufacturer_data = safe(lambda: {
            f"0x{k:04x}": v.hex() for k, v in (adv.manufacturer_data or {}).items()
        }, {}) if adv else {}

        service_data = safe(lambda: {
            k: v.hex() for k, v in (adv.service_data or {}).items()
        }, {}) if adv else {}

        service_uuids = safe(lambda: list(adv.service_uuids or []), []) if adv else []

        return {
            "mac": device.address,
            "name": device.name,
            "local_name": safe(lambda: adv.local_name if adv else None),
            "rssi": safe(lambda: adv.rssi if adv else getattr(device, "rssi", None)),
            "tx_power": safe(lambda: adv.tx_power if adv else None),
            "manufacturer_data": manufacturer_data,
            "service_data": service_data,
            "service_uuids": service_uuids,
            "device_details": safe(lambda: str(device.details)),
            "adv_platform_data": safe(lambda: str(getattr(adv, "platform_data", None))),
        }

    # -- Verlaufsabruf (von aussen aufgerufen, z.B. aus dem Flask-Thread) -----

    def request_history(self, mac: str, count: int = 500) -> Future:
        mac = mac.upper()
        logger.info("Fordere Verlauf an: mac=%s count=%d", mac, count)
        future = self._run_coro(self._request_history_async(mac, count))

        def _on_done(fut: Future) -> None:
            exc = fut.exception()
            if exc is not None:
                logger.error("Verlaufsabruf fuer %s fehlgeschlagen: %s", mac, exc)
                self.state.set_error(mac, str(exc))
                self.state.set_status(mac, "connected" if mac in self._clients else "disconnected")

        future.add_done_callback(_on_done)
        return future

    async def _request_history_async(self, mac: str, count: int) -> dict:
        """Fordert Verlauf an und wartet IDLE-basiert auf die Antwort: solange
        neue Pakete reinkommen, wird weitergewartet; erst wenn
        HISTORY_IDLE_TIMEOUT_SECONDS lang gar nichts mehr kam (oder das
        grosszuegige Gesamt-Zeitfenster ueberschritten ist), wird abgebrochen.
        Ein fester Gesamt-Timeout (frueher: 30s, spaeter grob nach Anzahl
        hochskaliert) erwies sich in der Praxis als zu ungenau: die
        Uebertragungsrate ueber eine reale, ggf. schwache BLE-Verbindung ist
        nicht konstant, ein zu kurzes festes Fenster schnitt grosse Abrufe
        vorzeitig ab. Gibt {"count": int, "clean": bool} zurueck - clean=False
        bedeutet: wir haben selbst abgebrochen, das Geraet hat vermutlich noch
        mehr Daten (fuer den Auto-Sync-Mechanismus relevant, siehe dort)."""
        client = self._clients.get(mac)
        if not client or not client.is_connected:
            raise RuntimeError(f"Nicht mit {mac} verbunden.")

        hstate = {"in_progress": True, "packet_index": 0, "buffer": [], "done_event": asyncio.Event(), "clean": False}
        self._history_state[mac] = hstate
        self.state.set_status(mac, "fetching_history")

        overall_cap = max(HISTORY_MIN_OVERALL_TIMEOUT_SECONDS, min(HISTORY_MAX_OVERALL_TIMEOUT_SECONDS, count * 0.05))

        async def send(label: str, payload: bytes) -> None:
            logger.debug("TX (%s) %s: %s", label, mac, payload.hex())
            self.state.append_raw_log(mac, {"kind": f"write-{label}", "hex": payload.hex(), "len": len(payload)})
            await client.write_gatt_char(protocol.WRITE_CHAR_UUID, payload)
            await asyncio.sleep(protocol.COMMAND_DELAY_SECONDS)

        try:
            await send("time-sync", protocol.build_time_sync_command())
            await send("session-init", protocol.get_session_init_command())
            await send("offset", protocol.get_offset_command())
            await send("data-request", protocol.build_data_request_command(count))

            logger.debug(
                "Warte auf Verlaufsdaten von %s (angefragt: %d, Idle-Timeout=%ds, Gesamt-Obergrenze=%.0fs)",
                mac, count, HISTORY_IDLE_TIMEOUT_SECONDS, overall_cap,
            )
            start = time.monotonic()
            last_packet_index = -1
            while True:
                remaining_overall = overall_cap - (time.monotonic() - start)
                if remaining_overall <= 0:
                    logger.warning(
                        "Gesamt-Obergrenze (%.0fs) fuer Verlaufsabruf von %s erreicht, breche mit %d Datensaetzen ab",
                        overall_cap, mac, len(hstate["buffer"]),
                    )
                    self._finish_history(mac, hstate, clean=False)
                    break
                try:
                    await asyncio.wait_for(hstate["done_event"].wait(), timeout=min(HISTORY_IDLE_TIMEOUT_SECONDS, remaining_overall))
                    break
                except asyncio.TimeoutError:
                    if hstate["packet_index"] == last_packet_index:
                        logger.warning(
                            "Keine neuen Verlaufs-Pakete seit %ds von %s, beende Abruf mit %d Datensaetzen",
                            HISTORY_IDLE_TIMEOUT_SECONDS, mac, len(hstate["buffer"]),
                        )
                        self._finish_history(mac, hstate, clean=False)
                        break
                    last_packet_index = hstate["packet_index"]
        finally:
            hstate["in_progress"] = False

        return {"count": len(hstate["buffer"]), "clean": hstate.get("clean", False)}

    # -- Rohbefehl senden (Reverse-Engineering-Werkzeug) -------------------------

    def write_raw(self, mac: str, data: bytes) -> Future:
        """Schreibt beliebige Rohbytes direkt auf die Write-Characteristic.
        Fuer die drei nicht dokumentierten Verlaufs-Kommandos (Zeit-Sync,
        Session-Init, Offset - siehe protocol.py) lassen sich hiermit
        Kandidaten-Bytes am echten Geraet ausprobieren; die Antwort
        erscheint wie jedes andere empfangene Paket live im Rohdaten-Feed
        des Geraets (/api/devices/<mac>/log)."""
        mac = mac.upper()
        logger.info("Sende Rohbefehl an %s: %s", mac, data.hex())
        future = self._run_coro(self._write_raw_async(mac, data))

        def _on_done(fut: Future) -> None:
            exc = fut.exception()
            if exc is not None:
                logger.error("Rohbefehl an %s fehlgeschlagen: %s", mac, exc)
                self.state.set_error(mac, str(exc))

        future.add_done_callback(_on_done)
        return future

    async def _write_raw_async(self, mac: str, data: bytes) -> None:
        client = self._clients.get(mac)
        if not client or not client.is_connected:
            raise RuntimeError(f"Nicht mit {mac} verbunden.")
        self.state.append_raw_log(mac, {"kind": "write-manual", "hex": data.hex(), "len": len(data)})
        await client.write_gatt_char(protocol.WRITE_CHAR_UUID, data)
