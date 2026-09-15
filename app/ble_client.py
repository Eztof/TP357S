"""Bluetooth-LE-Anbindung an den ThermoPro TP357S (laeuft in eigenem Thread
mit eigener asyncio-Event-Loop, da bleak async ist und der Flask-Server in
seinem eigenen Thread laeuft)."""
import asyncio
import logging
import threading
from concurrent.futures import Future
from typing import List, Optional

from bleak import BleakClient

from . import protocol
from .config import AppConfig
from .state import AppState
from .storage import Storage

logger = logging.getLogger(__name__)

HISTORY_TIMEOUT_SECONDS = 30


class BleController:
    def __init__(self, config: AppConfig, state: AppState, storage: Storage):
        self.config = config
        self.state = state
        self.storage = storage

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._client: Optional[BleakClient] = None
        self._stop_event: Optional[asyncio.Event] = None

        self._history_in_progress = False
        self._history_packet_index = 0
        self._history_buffer: List[protocol.Reading] = []
        self._history_done_event: Optional[asyncio.Event] = None

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, name="ble-loop", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._loop.close()

    async def _main(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
            except Exception as exc:  # noqa: BLE001 - Verbindungsfehler sollen den Loop nicht beenden
                logger.exception("BLE-Verbindungsfehler")
                self.state.set_error(str(exc))
            if self._stop_event.is_set():
                break
            self.state.set_status("disconnected")
            await asyncio.sleep(self.config.reconnect_delay_seconds)

    async def _connect_and_listen(self) -> None:
        mac = self.config.mac_address
        if not mac:
            self.state.set_status("unconfigured")
            self.state.set_error("Keine MAC-Adresse in config.json hinterlegt.")
            await asyncio.sleep(5)
            return

        self.state.set_status("connecting")
        async with BleakClient(mac) as client:
            self._client = client
            self.state.set_status("connected")
            self.state.set_error(None)
            logger.info("Mit %s verbunden", mac)

            await client.start_notify(protocol.NOTIFY_CHAR_UUID, self._on_notify)

            while client.is_connected and not self._stop_event.is_set():
                await asyncio.sleep(1)

        self._client = None

    # -- Notifications ---------------------------------------------------------

    def _on_notify(self, _handle: int, data: bytearray) -> None:
        packet = bytes(data)
        if self._history_in_progress:
            self._handle_history_or_end(packet)
            return

        reading = protocol.decode_live(packet)
        if reading is not None:
            self.state.set_live_reading(reading)
            self.storage.insert_live_reading(reading)

    def _handle_history_or_end(self, packet: bytes) -> None:
        # Kein explizites Ende (66 66) noetig: eine normale Live-Notification
        # waehrend eines laufenden Verlaufs-Abrufs signalisiert ebenfalls das Ende.
        if self._history_packet_index == 0 or protocol.is_history_header(packet):
            is_first = self._history_packet_index == 0
            records, is_end = protocol.process_history_packet(packet, is_first_packet=is_first)
            self._history_packet_index += 1
            self._history_buffer.extend(records)
            if is_end:
                self._finish_history()
            return

        live = protocol.decode_live(packet)
        if live is not None:
            self._finish_history(trailing_live=live)
            return

        records, is_end = protocol.process_history_packet(packet, is_first_packet=False)
        self._history_packet_index += 1
        self._history_buffer.extend(records)
        if is_end:
            self._finish_history()

    def _finish_history(self, trailing_live: Optional[protocol.Reading] = None) -> None:
        records = self._history_buffer
        self._history_buffer = []
        self._history_in_progress = False
        self._history_packet_index = 0

        count = self.storage.insert_history_readings(
            records, interval_seconds=self.config.history_record_interval_seconds
        )
        self.state.set_history_result(count)
        self.state.set_status("connected")
        logger.info("Verlaufsabruf abgeschlossen: %d Datensaetze", count)

        if self._history_done_event is not None:
            self._history_done_event.set()

        if trailing_live is not None:
            self.state.set_live_reading(trailing_live)
            self.storage.insert_live_reading(trailing_live)

    # -- Verlaufsabruf (von aussen aufgerufen, z.B. aus dem Flask-Thread) -----

    def request_history(self, count: int = 500) -> Future:
        if not self._loop:
            raise RuntimeError("BLE-Verbindung laeuft noch nicht.")
        future = asyncio.run_coroutine_threadsafe(self._request_history_async(count), self._loop)

        def _on_done(fut: Future) -> None:
            exc = fut.exception()
            if exc is not None:
                logger.error("Verlaufsabruf fehlgeschlagen: %s", exc)
                self.state.set_error(str(exc))
                self.state.set_status("connected" if self._client else "disconnected")

        future.add_done_callback(_on_done)
        return future

    async def _request_history_async(self, count: int) -> int:
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Nicht mit dem Sensor verbunden.")

        self._history_buffer = []
        self._history_packet_index = 0
        self._history_in_progress = True
        self._history_done_event = asyncio.Event()
        self.state.set_status("fetching_history")

        try:
            await self._client.write_gatt_char(protocol.WRITE_CHAR_UUID, protocol.build_time_sync_command())
            await asyncio.sleep(protocol.COMMAND_DELAY_SECONDS)

            await self._client.write_gatt_char(protocol.WRITE_CHAR_UUID, protocol.get_session_init_command())
            await asyncio.sleep(protocol.COMMAND_DELAY_SECONDS)

            await self._client.write_gatt_char(protocol.WRITE_CHAR_UUID, protocol.get_offset_command())
            await asyncio.sleep(protocol.COMMAND_DELAY_SECONDS)

            await self._client.write_gatt_char(
                protocol.WRITE_CHAR_UUID, protocol.build_data_request_command(count)
            )

            try:
                await asyncio.wait_for(self._history_done_event.wait(), timeout=HISTORY_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("Timeout beim Warten auf Verlaufsdaten, breche mit %d Datensaetzen ab",
                                len(self._history_buffer))
                self._finish_history()
        finally:
            self._history_in_progress = False

        return len(self._history_buffer)
