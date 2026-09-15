"""ThermoPro TP357S BLE-GATT-Protokoll: Dekodierung/Kodierung der Datenpakete.

UUIDs, Aufbau der Live-Werte und Aufbau/Beendigung der Verlaufsantwort sind
vollstaendig nach der Spezifikation implementiert. Fuer den Verlaufs-Abruf
(request_history) fehlen in der urspruenglichen Spezifikation die konkreten
Hex-Bytes fuer drei der vier zu sendenden Kommandos (Uhrzeit-Sync, Session-Init,
Offset-Kommando) - dort waren nur die *Feldbedeutungen*, nicht die festen
Opcode-/Praefix-Bytes angegeben. Diese drei Konstanten sind unten als
Platzhalter (None) markiert und muessen einmalig eingetragen werden, bevor der
Verlaufs-Abruf funktioniert. Der Live-Wert und die Datenanfrage (Kommando d,
Praefix "01 09" laut Spezifikation) funktionieren bereits vollstaendig.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

# --- GATT UUIDs -------------------------------------------------------------

NOTIFY_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b10"
WRITE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

# --- Live-Wert ---------------------------------------------------------------

LIVE_PACKET_LEN = 7
LIVE_MARKER = 0xC2

TEMP_MIN_C = -40.0
TEMP_MAX_C = 85.0
HUMIDITY_MIN = 0
HUMIDITY_MAX = 100

# --- Verlauf -------------------------------------------------------------

HISTORY_HEADER_LEN = 7
HISTORY_HEADER_MARKER = bytes([0xCC, 0xCC])
HISTORY_RECORD_LEN = 3
HISTORY_END_MARKER = bytes([0x66, 0x66])

COMMAND_DELAY_SECONDS = 0.25

# --- Verlaufs-Kommandos ----------------------------------------------------
# WICHTIG: In der Vorlage fehlten die konkreten Byte-Werte fuer diese drei
# Kommandos (nur die Feldbedeutungen waren beschrieben). Bitte hier eintragen,
# sobald bekannt (z.B. aus einem BLE-Sniff der offiziellen ThermoPro-App).
#
# TIME_SYNC_OPCODE: fester Praefix vor YY MM DD HH MM SS DOW (Kommando a)
TIME_SYNC_OPCODE: Optional[bytes] = None  # z.B. bytes([0x01, 0x01])

# SESSION_INIT_COMMAND: komplettes, festes Kommando ohne variable Felder (b)
SESSION_INIT_COMMAND: Optional[bytes] = None

# OFFSET_COMMAND: komplettes, festes Kommando ohne variable Felder (c)
OFFSET_COMMAND: Optional[bytes] = None

# DATA_REQUEST_OPCODE: laut Spezifikation belegt ("Bytes ab 01 09 ... bis NH")
DATA_REQUEST_OPCODE: bytes = bytes([0x01, 0x09])


@dataclass
class Reading:
    temperature_c: float
    humidity_pct: int
    battery_pct: Optional[int] = None

    def is_valid(self) -> bool:
        if not (TEMP_MIN_C <= self.temperature_c <= TEMP_MAX_C):
            return False
        if not (HUMIDITY_MIN <= self.humidity_pct <= HUMIDITY_MAX):
            return False
        return True


def _decode_temp_humidity(byte_lo: int, byte_hi: int, humidity_byte: int) -> Tuple[float, int]:
    temp_raw = (byte_hi << 8) | byte_lo
    if temp_raw > 32767:
        temp_raw -= 65536
    temperature_c = temp_raw / 10.0
    return temperature_c, humidity_byte


def decode_live(data: bytes) -> Optional[Reading]:
    """Dekodiert eine 7-Byte-Live-Notification (Marker 0xC2)."""
    if len(data) != LIVE_PACKET_LEN or data[0] != LIVE_MARKER:
        return None
    temperature_c, humidity_pct = _decode_temp_humidity(data[3], data[4], data[5])
    reading = Reading(temperature_c=temperature_c, humidity_pct=humidity_pct, battery_pct=data[6])
    return reading if reading.is_valid() else None


def decode_history_record(chunk: bytes) -> Optional[Reading]:
    """Dekodiert einen 3-Byte-Verlaufs-Datensatz (ohne Batteriewert)."""
    if len(chunk) != HISTORY_RECORD_LEN:
        return None
    temperature_c, humidity_pct = _decode_temp_humidity(chunk[0], chunk[1], chunk[2])
    reading = Reading(temperature_c=temperature_c, humidity_pct=humidity_pct, battery_pct=None)
    return reading if reading.is_valid() else None


def is_history_header(packet: bytes) -> bool:
    return len(packet) >= HISTORY_HEADER_LEN and packet[:2] == HISTORY_HEADER_MARKER and packet[2] == 0x01


def _parse_records(payload: bytes) -> List[Reading]:
    """Zerlegt ein Paket in 3-Byte-Bloecke; Restbytes am Paketende werden
    verworfen (kein Zusammenhaengen ueber Paketgrenzen hinweg)."""
    records: List[Reading] = []
    usable_len = (len(payload) // HISTORY_RECORD_LEN) * HISTORY_RECORD_LEN
    for i in range(0, usable_len, HISTORY_RECORD_LEN):
        reading = decode_history_record(payload[i : i + HISTORY_RECORD_LEN])
        if reading is not None:
            records.append(reading)
    return records


def process_history_packet(packet: bytes, *, is_first_packet: bool) -> Tuple[List[Reading], bool]:
    """Verarbeitet ein einzelnes Verlaufs-Notification-Paket.

    Gibt (Datensaetze_in_diesem_Paket, ist_explizites_Ende) zurueck. Das
    explizite Ende (Byte-Paar 0x66 0x66 am Paketende) ist von dem impliziten
    Ende (naechstes Paket ist ein normales Live-Paket) zu unterscheiden; das
    implizite Ende wird vom Aufrufer anhand von decode_live() erkannt.
    """
    payload = packet[HISTORY_HEADER_LEN:] if is_first_packet and is_history_header(packet) else packet
    is_end = payload[-2:] == HISTORY_END_MARKER
    if is_end:
        payload = payload[:-2]
    return _parse_records(payload), is_end


def checksum(payload: bytes) -> int:
    """Summe aller Bytes (jeweils 0-255), davon nur das unterste Byte."""
    return sum(b & 0xFF for b in payload) & 0xFF


def _bcd_datetime_fields(dt: datetime) -> bytes:
    # DOW: 1=Sonntag ... 7=Samstag; Python weekday(): Montag=0 ... Sonntag=6
    python_dow = dt.weekday()
    dow = 1 if python_dow == 6 else python_dow + 2
    return bytes([dt.year - 2000, dt.month, dt.day, dt.hour, dt.minute, dt.second, dow])


def build_time_sync_command(dt: Optional[datetime] = None) -> bytes:
    if TIME_SYNC_OPCODE is None:
        raise NotImplementedError(
            "TIME_SYNC_OPCODE ist nicht konfiguriert (app/protocol.py). "
            "Das genaue Byte-Praefix fuer den Uhrzeit-Sync-Befehl fehlt in der Spezifikation."
        )
    dt = dt or datetime.now()
    payload = TIME_SYNC_OPCODE + _bcd_datetime_fields(dt)
    return payload + bytes([checksum(payload)])


def build_data_request_command(count: int, dt: Optional[datetime] = None) -> bytes:
    dt = dt or datetime.now()
    count = max(0, min(count, 0xFFFF))
    payload = DATA_REQUEST_OPCODE + _bcd_datetime_fields(dt) + bytes([count & 0xFF, (count >> 8) & 0xFF])
    return payload + bytes([checksum(payload)])


def get_session_init_command() -> bytes:
    if SESSION_INIT_COMMAND is None:
        raise NotImplementedError(
            "SESSION_INIT_COMMAND ist nicht konfiguriert (app/protocol.py). "
            "Das feste Byte-Kommando fuer die Session-Init fehlt in der Spezifikation."
        )
    return SESSION_INIT_COMMAND


def get_offset_command() -> bytes:
    if OFFSET_COMMAND is None:
        raise NotImplementedError(
            "OFFSET_COMMAND ist nicht konfiguriert (app/protocol.py). "
            "Das feste Byte-Kommando fuer den Offset-Befehl fehlt in der Spezifikation."
        )
    return OFFSET_COMMAND
