"""ThermoPro TP357S BLE-GATT-Protokoll: Dekodierung/Kodierung der Datenpakete.

Alle vier Verlaufs-Kommandos sind vollstaendig implementiert und gegen ein
unabhaengiges, gegen echte Sensor-Antworten verifiziertes Referenzprojekt
abgeglichen (Ursprung: pytp357s):

a) Uhrzeit-Sync:    A5 YY MM DD HH MM SS DOW CS                  (9 Bytes, eigenes Format)
b) Session-Init:    CC CC 02 01 00 00 01 04 66 66                (fest, 10 Bytes)
c) Offset:          CC CC 04 00 00 00 00 04 66 66                (fest, 10 Bytes)
d) Datenanfrage:    CC CC 01 09 00 00 00 YY MM DD HH MM SS NL NH CS 66 66

Bei a) ist CS = Checksumme ueber A5+Datumsfelder. Bei d) ist CS = Checksumme
ueber die Bytes ab "01 09" bis einschliesslich NH (NICHT ueber die
CC-CC-Praefix und NICHT ueber die abschliessenden 66-66-Bytes). Kommando d)
hat - anders als a) - KEIN Wochentags-Byte im Datumsteil.
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

# a) Uhrzeit-Sync: Opcode 0xA5, danach YY MM DD HH MM SS DOW + Checksumme.
TIME_SYNC_OPCODE: bytes = bytes([0xA5])

# b) Session-Init: komplettes, festes Kommando ohne variable Felder.
SESSION_INIT_COMMAND: bytes = bytes([0xCC, 0xCC, 0x02, 0x01, 0x00, 0x00, 0x01, 0x04, 0x66, 0x66])

# c) Offset-Kommando: komplettes, festes Kommando ohne variable Felder.
OFFSET_COMMAND: bytes = bytes([0xCC, 0xCC, 0x04, 0x00, 0x00, 0x00, 0x00, 0x04, 0x66, 0x66])

# d) Datenanfrage: Opcode "01 09" innerhalb des CC-CC/66-66-Rahmens (siehe
# build_data_request_command).
DATA_REQUEST_OPCODE: bytes = bytes([0x01, 0x09])

HISTORY_REQUEST_FRAME_PREFIX: bytes = HISTORY_HEADER_MARKER  # CC CC - gleiche Bytes wie der Antwort-Header
HISTORY_REQUEST_FRAME_SUFFIX: bytes = HISTORY_END_MARKER  # 66 66 - gleiche Bytes wie das Antwort-Ende


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
    """A5 YY MM DD HH MM SS DOW CS."""
    dt = dt or datetime.now()
    payload = TIME_SYNC_OPCODE + _bcd_datetime_fields(dt)
    return payload + bytes([checksum(payload)])


def build_time_shaped_candidate(prefix: bytes, dt: Optional[datetime] = None) -> bytes:
    """Baut ein Kandidaten-Kommando im selben Feldschema wie
    build_time_sync_command() (Praefix + aktuelle Datumsfelder YY MM DD HH
    MM SS DOW + Checksumme), aber mit frei waehlbarem Praefix. Nicht mehr
    fuer die Standard-Historie noetig (TIME_SYNC_OPCODE ist bekannt),
    bleibt aber nuetzlich zum Experimentieren mit anderen, noch unbekannten
    Kommandos ueber die Rohbefehl-Konsole im Dashboard."""
    dt = dt or datetime.now()
    payload = prefix + _bcd_datetime_fields(dt)
    return payload + bytes([checksum(payload)])


def build_data_request_command(count: int, dt: Optional[datetime] = None) -> bytes:
    """CC CC 01 09 00 00 00 YY MM DD HH MM SS NL NH CS 66 66.

    CS wird ueber die Bytes ab "01 09" bis einschliesslich NH berechnet -
    NICHT ueber die fuehrenden CC-CC-Bytes und NICHT ueber die
    abschliessenden 66-66-Bytes. Anders als beim Uhrzeit-Sync-Kommando
    enthaelt der Datumsteil hier KEIN Wochentags-Byte (nur YY MM DD HH MM SS,
    6 statt 7 Bytes)."""
    dt = dt or datetime.now()
    count = max(0, min(count, 0xFFFF))
    date_fields = _bcd_datetime_fields(dt)[:-1]  # YY MM DD HH MM SS (ohne DOW)
    inner = DATA_REQUEST_OPCODE + bytes([0x00, 0x00, 0x00]) + date_fields + bytes([count & 0xFF, (count >> 8) & 0xFF])
    cs = checksum(inner)
    return HISTORY_REQUEST_FRAME_PREFIX + inner + bytes([cs]) + HISTORY_REQUEST_FRAME_SUFFIX


def get_session_init_command() -> bytes:
    return SESSION_INIT_COMMAND


def get_offset_command() -> bytes:
    return OFFSET_COMMAND
