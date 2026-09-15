"""Bluetooth-LE-Anbindung an beliebig viele ThermoPro-TP357S-Sensoren.

Laeuft in einem eigenen Thread mit eigener asyncio-Event-Loop (bleak ist
async, der Flask-Server laeuft in seinem eigenen Thread). Pro gekoppeltem
Sensor (MAC-Adresse) laeuft eine eigene Verbindungs-Task nebenlaeufig in
derselben Event-Loop; zusaetzlich kann jederzeit ein BLE-Scan gestartet
werden, um neue Geraete in der Naehe zu finden.
"""
import asyncio
import functools
import logging
import threading
from concurrent.futures import Future
from typing import Dict, Optional

from bleak import BleakClient, BleakScanner

from . import protocol
from .config import AppConfig
from .state import AppState
from .storage import Storage

logger = logging.getLogger(__name__)

HISTORY_TIMEOUT_SECONDS = 30


class BleManager:
    def __init__(self, config: AppConfig, state: AppState, storage: Storage):
        self.config = config
        self.state = state
        self.storage = storage

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

        self._clients: Dict[str, BleakClient] = {}
        self._device_tasks: Dict[str, "asyncio.Task"] = {}
        self._history_state: Dict[str, dict] = {}

    # -- Lifecycle -------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, name="ble-loop", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _run_coro(self, coro) -> Future:
        if not self._loop:
            raise RuntimeError("BLE-Event-Loop laeuft noch nicht.")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # -- Geraete koppeln/entfernen -----------------------------------------------

    def add_device(self, mac: str, name: str) -> None:
        mac = mac.upper()
        self.state.ensure_device(mac, name)
        self._run_coro(self._spawn_device_task(mac))

    async def _spawn_device_task(self, mac: str) -> None:
        existing = self._device_tasks.get(mac)
        if existing and not existing.done():
            return
        self._device_tasks[mac] = asyncio.create_task(self._device_loop(mac))

    def remove_device(self, mac: str) -> None:
        mac = mac.upper()
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
                pass

    # -- Verbindung + Live-Werte ------------------------------------------------

    async def _device_loop(self, mac: str) -> None:
        while True:
            try:
                await self._connect_and_listen(mac)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - Verbindungsfehler duerfen die Loop nicht beenden
                logger.exception("BLE-Verbindungsfehler bei %s", mac)
                self.state.set_error(mac, str(exc))
            self.state.set_status(mac, "disconnected")
            await asyncio.sleep(self.config.reconnect_delay_seconds)

    async def _connect_and_listen(self, mac: str) -> None:
        self.state.set_status(mac, "connecting")
        async with BleakClient(mac) as client:
            self._clients[mac] = client
            self.state.set_status(mac, "connected")
            self.state.set_error(mac, None)
            logger.info("Mit %s verbunden", mac)

            await client.start_notify(protocol.NOTIFY_CHAR_UUID, functools.partial(self._on_notify, mac))

            while client.is_connected:
                await asyncio.sleep(1)

        self._clients.pop(mac, None)

    def _on_notify(self, mac: str, _handle: int, data: bytearray) -> None:
        packet = bytes(data)
        hstate = self._history_state.get(mac)
        if hstate and hstate["in_progress"]:
            self._handle_history_or_end(mac, packet, hstate)
            return

        reading = protocol.decode_live(packet)
        if reading is not None:
            self.state.set_live_reading(mac, reading)
            self.storage.insert_live_reading(mac, reading)

    def _handle_history_or_end(self, mac: str, packet: bytes, hstate: dict) -> None:
        if hstate["packet_index"] == 0 or protocol.is_history_header(packet):
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

    def _finish_history(self, mac: str, hstate: dict, trailing_live: Optional[protocol.Reading] = None) -> None:
        records = hstate["buffer"]
        hstate["in_progress"] = False

        count = self.storage.insert_history_readings(
            mac, records, interval_seconds=self.config.history_record_interval_seconds
        )
        self.state.set_history_result(mac, count)
        self.state.set_status(mac, "connected")
        logger.info("Verlaufsabruf fuer %s abgeschlossen: %d Datensaetze", mac, count)

        hstate["done_event"].set()

        if trailing_live is not None:
            self.state.set_live_reading(mac, trailing_live)
            self.storage.insert_live_reading(mac, trailing_live)

    # -- Scannen nach Geraeten in der Naehe --------------------------------------

    def scan(self, duration: Optional[int] = None) -> Future:
        duration = duration or self.config.scan_duration_seconds
        return self._run_coro(self._scan_async(duration))

    async def _scan_async(self, duration: int) -> None:
        self.state.set_scanning(True)
        try:
            found = await BleakScanner.discover(timeout=duration, return_adv=True)
            results = []
            for device, adv in found.values():
                name = device.name or (adv.local_name if adv else None) or "Unbekanntes Geraet"
                rssi = adv.rssi if adv else None
                results.append({"mac": device.address, "name": name, "rssi": rssi})
            results.sort(key=lambda d: (d["rssi"] is None, -(d["rssi"] or -999)))
            self.state.set_scan_results(results)
        except Exception as exc:  # noqa: BLE001
            logger.exception("BLE-Scan fehlgeschlagen")
            self.state.set_scan_results([])
            raise
        finally:
            self.state.set_scanning(False)

    # -- Verlaufsabruf (von aussen aufgerufen, z.B. aus dem Flask-Thread) -----

    def request_history(self, mac: str, count: int = 500) -> Future:
        mac = mac.upper()
        future = self._run_coro(self._request_history_async(mac, count))

        def _on_done(fut: Future) -> None:
            exc = fut.exception()
            if exc is not None:
                logger.error("Verlaufsabruf fuer %s fehlgeschlagen: %s", mac, exc)
                self.state.set_error(mac, str(exc))
                self.state.set_status(mac, "connected" if mac in self._clients else "disconnected")

        future.add_done_callback(_on_done)
        return future

    async def _request_history_async(self, mac: str, count: int) -> int:
        client = self._clients.get(mac)
        if not client or not client.is_connected:
            raise RuntimeError(f"Nicht mit {mac} verbunden.")

        hstate = {"in_progress": True, "packet_index": 0, "buffer": [], "done_event": asyncio.Event()}
        self._history_state[mac] = hstate
        self.state.set_status(mac, "fetching_history")

        try:
            await client.write_gatt_char(protocol.WRITE_CHAR_UUID, protocol.build_time_sync_command())
            await asyncio.sleep(protocol.COMMAND_DELAY_SECONDS)

            await client.write_gatt_char(protocol.WRITE_CHAR_UUID, protocol.get_session_init_command())
            await asyncio.sleep(protocol.COMMAND_DELAY_SECONDS)

            await client.write_gatt_char(protocol.WRITE_CHAR_UUID, protocol.get_offset_command())
            await asyncio.sleep(protocol.COMMAND_DELAY_SECONDS)

            await client.write_gatt_char(protocol.WRITE_CHAR_UUID, protocol.build_data_request_command(count))

            try:
                await asyncio.wait_for(hstate["done_event"].wait(), timeout=HISTORY_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout beim Warten auf Verlaufsdaten von %s, breche mit %d Datensaetzen ab",
                    mac, len(hstate["buffer"]),
                )
                self._finish_history(mac, hstate)
        finally:
            hstate["in_progress"] = False

        return len(hstate["buffer"])
