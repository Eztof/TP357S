"""Laeuft als eigener Kindprozess (multiprocessing) und macht NICHTS als
bleak/BLE-Kommunikation. Grund: auf Windows/Python 3.14 stuerzt bleaks
WinRT-Backend reproduzierbar mit einer nativen Access Violation ab (kein
Python-Traceback, sys.excepthook/threading.excepthook/asyncio-Exception-
Handler greifen alle nicht - der Prozess stirbt einfach). Wenn das im
selben Prozess wie der Flask-Webserver passiert, ist das ganze Dashboard
tot. In einem eigenen Kindprozess dagegen stirbt nur dieser Kindprozess;
der Elternprozess (siehe ble_client.py: BleSupervisor) bemerkt das ueber
process.is_alive()/exitcode und startet automatisch einen neuen Worker,
waehrend Webserver, gespeicherte Daten und Dashboard die ganze Zeit
erreichbar bleiben.

Kommunikation ausschliesslich ueber zwei multiprocessing.Queue:
- cmd_queue:   Elternprozess -> Worker  (Befehle: add_device, remove_device,
               scan, request_history, write_raw, shutdown)
- event_queue: Worker -> Elternprozess  (Status-/Log-/Mess-Ereignisse)

Der Worker haelt selbst KEINEN Programmzustand, der ueberlebenswichtig
ist (kein SQLite, kein AppState) - all das lebt ausschliesslich im
Elternprozess, damit ein Worker-Absturz nichts an gespeicherten Daten
verliert. Der Worker meldet nur rohe Ereignisse; der Elternprozess
entscheidet, was er damit macht (state.py, storage.py).

Dieses Modul ist bewusst eine fast 1:1-Uebertragung der fruehereren
BleManager-Logik (vor der Prozess-Isolation) - siehe git-Historie von
ble_client.py fuer den direkten Vergleich."""
import asyncio
import functools
import importlib.metadata
import logging
import platform
import sys
import threading
import time
from typing import Dict, Optional

from bleak import BleakClient, BleakScanner

from . import protocol
from .logging_setup import install_asyncio_exception_handler, setup_worker_logging

logger = logging.getLogger(__name__)

HISTORY_IDLE_TIMEOUT_SECONDS = 20
HISTORY_MIN_OVERALL_TIMEOUT_SECONDS = 120
HISTORY_MAX_OVERALL_TIMEOUT_SECONDS = 1800


def _bleak_version() -> str:
    try:
        return importlib.metadata.version("bleak")
    except Exception:  # noqa: BLE001
        return "unbekannt"


def _reading_to_dict(reading: protocol.Reading) -> dict:
    return {
        "temperature_c": reading.temperature_c,
        "humidity_pct": reading.humidity_pct,
        "battery_pct": reading.battery_pct,
    }


class BleWorker:
    def __init__(self, cmd_queue, event_queue, config: dict):
        self.cmd_queue = cmd_queue
        self.event_queue = event_queue
        self.config = config

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._clients: Dict[str, BleakClient] = {}
        self._device_tasks: Dict[str, "asyncio.Task"] = {}
        self._history_state: Dict[str, dict] = {}

    # -- Event-Versand an den Elternprozess --------------------------------------

    def _emit(self, event: dict) -> None:
        try:
            self.event_queue.put(event)
        except Exception:  # noqa: BLE001
            logger.exception("Konnte Ereignis nicht an Elternprozess senden: %r", event)

    def _log(self, mac: str, kind: str, **fields) -> None:
        entry = {"kind": kind, **fields}
        self._emit({"type": "raw_log", "mac": mac, "entry": entry})

    def _status(self, mac: str, status: str) -> None:
        self._emit({"type": "status", "mac": mac, "status": status})

    def _error(self, mac: str, message: str) -> None:
        self._emit({"type": "error", "mac": mac, "message": message})

    # -- Hauptschleife ------------------------------------------------------------

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        install_asyncio_exception_handler(self.loop)

        threading.Thread(target=self._cmd_reader_loop, name="ble-worker-cmd-reader", daemon=True).start()

        self._emit({
            "type": "hello",
            "pid": __import__("os").getpid(),
            "python_version": sys.version.replace("\n", " "),
            "platform": platform.platform(),
            "bleak_version": _bleak_version(),
        })
        logger.info("BLE-Worker-Prozess gestartet (Python=%s bleak=%s)", sys.version.split()[0], _bleak_version())
        try:
            self.loop.run_forever()
        finally:
            logger.warning("BLE-Worker-Event-Loop wurde beendet")

    def _cmd_reader_loop(self) -> None:
        """Laeuft in einem eigenen Thread (Queue.get() ist blockierend, passt
        nicht direkt in die asyncio-Loop); reicht jeden Befehl per
        call_soon_threadsafe an die Event-Loop weiter."""
        while True:
            try:
                cmd = self.cmd_queue.get()
            except (EOFError, OSError):
                return
            if cmd is None:
                continue
            if cmd.get("type") == "shutdown":
                logger.info("Shutdown-Kommando empfangen, beende Worker-Event-Loop")
                self.loop.call_soon_threadsafe(self.loop.stop)
                return
            self.loop.call_soon_threadsafe(self._dispatch, cmd)

    def _dispatch(self, cmd: dict) -> None:
        asyncio.ensure_future(self._handle_cmd(cmd), loop=self.loop)

    async def _handle_cmd(self, cmd: dict) -> None:
        t = cmd.get("type")
        try:
            if t == "add_device":
                await self._spawn_device_task(cmd["mac"], cmd["name"])
            elif t == "remove_device":
                await self._cancel_device_task(cmd["mac"])
            elif t == "scan":
                await self._scan_async(cmd.get("duration") or self.config.get("scan_duration_seconds", 15))
            elif t == "request_history":
                await self._request_history_async(cmd["mac"], cmd["count"], cmd["req_id"])
            elif t == "write_raw":
                await self._write_raw_async(cmd["mac"], bytes.fromhex(cmd["hex"]))
            else:
                logger.warning("Unbekanntes Kommando vom Elternprozess: %r", cmd)
        except Exception:  # noqa: BLE001
            logger.exception("Fehler bei der Verarbeitung von Kommando %r", cmd)

    # -- Geraete verbinden/trennen ------------------------------------------------

    async def _spawn_device_task(self, mac: str, name: str) -> None:
        existing = self._device_tasks.get(mac)
        if existing and not existing.done():
            return
        self._device_tasks[mac] = asyncio.create_task(self._device_loop(mac), name=f"ble-device-{mac}")

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

    async def _device_loop(self, mac: str) -> None:
        reconnect_delay = self.config.get("reconnect_delay_seconds", 10)
        while True:
            try:
                await self._connect_and_listen(mac)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("BLE-Verbindungsfehler bei %s", mac)
                self._error(mac, f"{type(exc).__name__}: {exc}")
                self._log(mac, "error", note=f"{type(exc).__name__}: {exc}")
            self._status(mac, "disconnected")
            await asyncio.sleep(reconnect_delay)

    @staticmethod
    def _build_client(mac: str) -> BleakClient:
        """winrt=dict(use_cached_services=False): siehe fruehere ausfuehrliche
        Begruendung in der Git-Historie von ble_client.py. Bleibt gesetzt,
        ist ein echter, dokumentierter bleak/WinRT-Workaround, hat den
        nativen Absturz aber nicht vollstaendig behoben - daher jetzt
        zusaetzlich die Prozessisolation um dieses Modul herum."""
        return BleakClient(mac, timeout=20.0, winrt=dict(use_cached_services=False))

    async def _connect_and_listen(self, mac: str) -> None:
        self._status(mac, "connecting")
        self._log(mac, "info", note="Verbindungsversuch gestartet")

        client = self._build_client(mac)

        self._log(mac, "info", note="rufe client.connect() auf")
        await client.connect()
        self._log(mac, "info", note="client.connect() zurueckgekehrt")

        try:
            self._clients[mac] = client
            self._status(mac, "connected")
            self._error(mac, None)

            self._log(mac, "info", note="aktiviere Notify")
            await client.start_notify(protocol.NOTIFY_CHAR_UUID, functools.partial(self._on_notify, mac))
            self._log(mac, "info", note="Notify aktiviert")

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
            self._log(mac, "notify-history", hex=hex_str, len=len(packet))
            self._handle_history_or_end(mac, packet, hstate)
            return

        reading = protocol.decode_live(packet)
        if reading is not None:
            self._log(mac, "notify-live", hex=hex_str, len=len(packet), decoded=_reading_to_dict(reading))
            self._emit({"type": "live_reading", "mac": mac, "reading": _reading_to_dict(reading)})
        else:
            self._log(mac, "notify-undecoded", hex=hex_str, len=len(packet))

    def _handle_history_or_end(self, mac: str, packet: bytes, hstate: dict) -> None:
        if protocol.is_history_header(packet):
            is_first = hstate["packet_index"] == 0
            records, is_end = protocol.process_history_packet(packet, is_first_packet=is_first)
            hstate["packet_index"] += 1
            hstate["buffer"].extend(records)
            if is_end:
                self._finish_history(mac, hstate)
            return

        live = protocol.decode_live(packet)
        if live is not None:
            self._finish_history(mac, hstate, trailing_live=live)
            return

        records, is_end = protocol.process_history_packet(packet, is_first_packet=False)
        hstate["packet_index"] += 1
        hstate["buffer"].extend(records)
        if is_end:
            self._finish_history(mac, hstate)

    def _finish_history(
        self, mac: str, hstate: dict, trailing_live: Optional[protocol.Reading] = None, clean: bool = True
    ) -> None:
        hstate["in_progress"] = False
        hstate["clean"] = clean
        hstate["done_event"].set()
        self._emit({
            "type": "history_result",
            "req_id": hstate["req_id"],
            "mac": mac,
            "records": [_reading_to_dict(r) for r in hstate["buffer"]],
            "clean": clean,
            "trailing_live": _reading_to_dict(trailing_live) if trailing_live is not None else None,
        })

    # -- Scan -----------------------------------------------------------------

    async def _scan_async(self, duration: int) -> None:
        self._emit({"type": "scanning", "value": True})
        try:
            found = await BleakScanner.discover(timeout=duration, return_adv=True, scanning_mode="active")
            results = []
            for device, adv in found.values():
                results.append(self._describe_scan_result(device, adv))
            results.sort(key=lambda d: (d["rssi"] is None, -(d["rssi"] or -999)))
            self._emit({"type": "scan_result", "results": results})
        except Exception as exc:  # noqa: BLE001
            logger.exception("BLE-Scan fehlgeschlagen")
            self._emit({"type": "scan_error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            self._emit({"type": "scanning", "value": False})

    @staticmethod
    def _describe_scan_result(device, adv) -> dict:
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

    # -- Verlaufsabruf ----------------------------------------------------------

    async def _request_history_async(self, mac: str, count: int, req_id: str) -> None:
        client = self._clients.get(mac)
        if not client or not client.is_connected:
            self._emit({"type": "history_error", "req_id": req_id, "mac": mac, "message": f"Nicht mit {mac} verbunden."})
            return

        hstate = {
            "in_progress": True, "packet_index": 0, "buffer": [], "done_event": asyncio.Event(),
            "clean": False, "req_id": req_id,
        }
        self._history_state[mac] = hstate
        self._status(mac, "fetching_history")

        overall_cap = max(HISTORY_MIN_OVERALL_TIMEOUT_SECONDS, min(HISTORY_MAX_OVERALL_TIMEOUT_SECONDS, count * 0.05))

        async def send(label: str, payload: bytes) -> None:
            self._log(mac, f"write-{label}", hex=payload.hex(), len=len(payload))
            await client.write_gatt_char(protocol.WRITE_CHAR_UUID, payload)
            await asyncio.sleep(protocol.COMMAND_DELAY_SECONDS)

        try:
            await send("time-sync", protocol.build_time_sync_command())
            await send("session-init", protocol.get_session_init_command())
            await send("offset", protocol.get_offset_command())
            await send("data-request", protocol.build_data_request_command(count))

            start = time.monotonic()
            last_packet_index = -1
            while True:
                remaining_overall = overall_cap - (time.monotonic() - start)
                if remaining_overall <= 0:
                    self._finish_history(mac, hstate, clean=False)
                    break
                try:
                    await asyncio.wait_for(hstate["done_event"].wait(), timeout=min(HISTORY_IDLE_TIMEOUT_SECONDS, remaining_overall))
                    break
                except asyncio.TimeoutError:
                    if hstate["packet_index"] == last_packet_index:
                        self._finish_history(mac, hstate, clean=False)
                        break
                    last_packet_index = hstate["packet_index"]
        except Exception as exc:  # noqa: BLE001
            logger.exception("Verlaufsabruf fuer %s fehlgeschlagen", mac)
            hstate["in_progress"] = False
            self._emit({"type": "history_error", "req_id": req_id, "mac": mac, "message": f"{type(exc).__name__}: {exc}"})
            self._status(mac, "connected" if mac in self._clients else "disconnected")
            return
        finally:
            hstate["in_progress"] = False

        self._status(mac, "connected" if mac in self._clients else "disconnected")

    # -- Rohbefehl senden ---------------------------------------------------------

    async def _write_raw_async(self, mac: str, data: bytes) -> None:
        client = self._clients.get(mac)
        if not client or not client.is_connected:
            self._error(mac, f"Nicht mit {mac} verbunden (Rohbefehl konnte nicht gesendet werden).")
            return
        self._log(mac, "write-manual", hex=data.hex(), len=len(data))
        try:
            await client.write_gatt_char(protocol.WRITE_CHAR_UUID, data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Rohbefehl an %s fehlgeschlagen", mac)
            self._error(mac, f"{type(exc).__name__}: {exc}")


def worker_entrypoint(cmd_queue, event_queue, log_queue, config: dict) -> None:
    """Prozess-Einstiegspunkt (multiprocessing.Process(target=...)). Muss
    auf Modulebene stehen, damit Windows' spawn-Startmethode die Funktion
    im Kindprozess importieren/pickeln kann (keine gebundene Methode,
    keine Lambda)."""
    setup_worker_logging(log_queue, config.get("log_level", "DEBUG"))
    worker = BleWorker(cmd_queue, event_queue, config)
    worker.run()
