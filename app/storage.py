"""SQLite-Speicherung der Live- und Verlaufs-Messwerte, je Sensor (MAC)."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .protocol import Reading

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mac TEXT NOT NULL,
    ts TEXT NOT NULL,
    temperature_c REAL NOT NULL,
    humidity_pct INTEGER NOT NULL,
    battery_pct INTEGER
);
CREATE INDEX IF NOT EXISTS idx_live_mac_ts ON live_readings(mac, ts);

CREATE TABLE IF NOT EXISTS history_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mac TEXT NOT NULL,
    ts_estimated TEXT NOT NULL,
    temperature_c REAL NOT NULL,
    humidity_pct INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE(mac, ts_estimated, temperature_c, humidity_pct)
);
CREATE INDEX IF NOT EXISTS idx_history_mac_ts ON history_readings(mac, ts_estimated);
"""


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def insert_live_reading(self, mac: str, reading: Reading, ts: Optional[datetime] = None) -> None:
        ts = ts or datetime.now(timezone.utc)
        with self._lock:
            self._conn.execute(
                "INSERT INTO live_readings (mac, ts, temperature_c, humidity_pct, battery_pct) "
                "VALUES (?, ?, ?, ?, ?)",
                (mac, ts.isoformat(), reading.temperature_c, reading.humidity_pct, reading.battery_pct),
            )
            self._conn.commit()

    def insert_history_readings(self, mac: str, readings: List[Reading], interval_seconds: int) -> int:
        """Speichert Verlaufs-Datensaetze eines Sensors. readings[0] ist laut
        Spezifikation der neueste Wert; Zeitstempel werden rueckwaerts vom
        Abrufzeitpunkt geschaetzt, im angenommenen Aufnahmeintervall des Geraets."""
        if not readings:
            return 0
        now = datetime.now(timezone.utc)
        fetched_at = now.isoformat()
        rows = []
        for index, reading in enumerate(readings):
            ts_estimated = now - timedelta(seconds=index * interval_seconds)
            rows.append((mac, ts_estimated.isoformat(), reading.temperature_c, reading.humidity_pct, fetched_at))
        with self._lock:
            self._conn.executemany(
                "INSERT OR IGNORE INTO history_readings "
                "(mac, ts_estimated, temperature_c, humidity_pct, fetched_at) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    def recent_live(self, mac: str, limit: int = 50) -> List[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, temperature_c, humidity_pct, battery_pct FROM live_readings "
                "WHERE mac = ? ORDER BY id DESC LIMIT ?",
                (mac, limit),
            )
            rows = cur.fetchall()
        return [{"ts": r[0], "temperature_c": r[1], "humidity_pct": r[2], "battery_pct": r[3]} for r in rows]

    def recent_history(self, mac: str, limit: int = 500) -> List[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts_estimated, temperature_c, humidity_pct, fetched_at FROM history_readings "
                "WHERE mac = ? ORDER BY ts_estimated DESC LIMIT ?",
                (mac, limit),
            )
            rows = cur.fetchall()
        return [{"ts": r[0], "temperature_c": r[1], "humidity_pct": r[2], "fetched_at": r[3]} for r in rows]

    def combined_series(self, mac: str, limit: int = 5000) -> List[dict]:
        """Live- und Verlaufswerte eines Sensors zusammengeführt, chronologisch
        aufsteigend sortiert - Basis für den Graphen im Dashboard."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, temperature_c, humidity_pct FROM ("
                "  SELECT ts, temperature_c, humidity_pct FROM live_readings WHERE mac = ?"
                "  UNION ALL"
                "  SELECT ts_estimated, temperature_c, humidity_pct FROM history_readings WHERE mac = ?"
                ") ORDER BY ts DESC LIMIT ?",
                (mac, mac, limit),
            )
            rows = cur.fetchall()
        rows.reverse()
        return [{"ts": r[0], "temperature_c": r[1], "humidity_pct": r[2]} for r in rows]

    def export_csv_rows(self, mac: Optional[str] = None):
        with self._lock:
            if mac:
                cur = self._conn.execute(
                    "SELECT mac, 'live', ts, temperature_c, humidity_pct, battery_pct, NULL FROM live_readings "
                    "WHERE mac = ? "
                    "UNION ALL "
                    "SELECT mac, 'history', ts_estimated, temperature_c, humidity_pct, NULL, fetched_at "
                    "FROM history_readings WHERE mac = ? "
                    "ORDER BY 3",
                    (mac, mac),
                )
            else:
                cur = self._conn.execute(
                    "SELECT mac, 'live', ts, temperature_c, humidity_pct, battery_pct, NULL FROM live_readings "
                    "UNION ALL "
                    "SELECT mac, 'history', ts_estimated, temperature_c, humidity_pct, NULL, fetched_at "
                    "FROM history_readings "
                    "ORDER BY 1, 3"
                )
            return cur.fetchall()


def aggregate_points(points: List[dict], bucket_seconds: int) -> List[dict]:
    """Mittelt eine chronologisch sortierte Punktliste ({ts, temperature_c,
    humidity_pct}) in feste Zeit-Buckets (z.B. 300 = 5-Minuten-Mittel).
    bucket_seconds <= 0 bedeutet Rohdaten (keine Aggregation)."""
    if bucket_seconds <= 0 or not points:
        return points

    buckets: dict = {}
    order: List[int] = []
    for p in points:
        dt = datetime.fromisoformat(p["ts"])
        epoch = dt.timestamp()
        bucket_start = int(epoch // bucket_seconds) * bucket_seconds
        bucket = buckets.get(bucket_start)
        if bucket is None:
            bucket = {"temp_sum": 0.0, "hum_sum": 0.0, "count": 0}
            buckets[bucket_start] = bucket
            order.append(bucket_start)
        bucket["temp_sum"] += p["temperature_c"]
        bucket["hum_sum"] += p["humidity_pct"]
        bucket["count"] += 1

    result = []
    for bucket_start in order:
        b = buckets[bucket_start]
        ts = datetime.fromtimestamp(bucket_start, tz=timezone.utc).isoformat()
        result.append({
            "ts": ts,
            "temperature_c": round(b["temp_sum"] / b["count"], 2),
            "humidity_pct": round(b["hum_sum"] / b["count"], 1),
            "count": b["count"],
        })
    return result
