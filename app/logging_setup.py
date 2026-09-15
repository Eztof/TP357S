"""Zentrale, moeglichst luecken-freie Logging-Konfiguration.

Ziel: Wenn der Prozess abstuerzt oder sich merkwuerdig verhaelt, soll IMMER
etwas in data/app.log stehen - inklusive unbehandelter Exceptions im
Hauptthread, in Hintergrund-Threads und in der asyncio-Event-Loop des
BLE-Threads. Nichts soll still verschwinden.
"""
import asyncio
import logging
import logging.handlers
import re
import sys
import threading
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s"

# Das Dashboard pollt diese Endpunkte alle paar Sekunden selbst (Status,
# Debug-Panel, Log-Fenster). Deren 200er-Zugriffs-Log wuerde das Logfile
# ausschliesslich mit sich selbst fluten (jedes Log-Poll erzeugt eine
# Logzeile, die beim naechsten Poll wieder mitgeloggt wird). Echte Fehler
# (Status != 200) und alle anderen Routen (Scan starten, Geraet
# hinzufuegen, Verlauf abrufen, ...) bleiben normal sichtbar.
_NOISY_POLL_PATTERN = re.compile(
    r'"GET (?:/api/status|/api/config|/api/debug|/api/logs(?:\?[^"\s]*)?'
    r'|/api/devices/[^"\s/]+/(?:live|history|log)(?:\?[^"\s]*)?) HTTP/[^"]+"\s+200'
)


class _NoisyPollFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _NOISY_POLL_PATTERN.search(record.getMessage()) is None


def setup_logging(log_path: Path, level: str = "DEBUG", max_bytes: int = 5_000_000, backup_count: int = 5) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        str(log_path), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # Nur die reinen Status-Polling-GETs rausfiltern - alles andere (inkl.
    # Fehler-Statuscodes) bleibt wie gewohnt sichtbar.
    logging.getLogger("werkzeug").addFilter(_NoisyPollFilter())

    _install_crash_hooks()

    logging.getLogger(__name__).info(
        "Logging initialisiert: Datei=%s Level=%s MaxBytes=%s Backups=%s",
        log_path, level, max_bytes, backup_count,
    )


def _install_crash_hooks() -> None:
    """Sorgt dafuer, dass unbehandelte Exceptions IMMER geloggt werden,
    egal in welchem Thread oder in welcher asyncio-Loop sie auftreten."""
    logger = logging.getLogger("crash")

    def log_unhandled(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("UNBEHANDELTE EXCEPTION (Hauptthread)", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = log_unhandled

    def log_thread_exc(args: threading.ExceptHookArgs):
        logger.critical(
            "UNBEHANDELTE EXCEPTION in Thread '%s'",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = log_thread_exc


def install_asyncio_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    logger = logging.getLogger("asyncio-loop")

    def handler(loop_, context):
        message = context.get("message")
        exc = context.get("exception")
        if exc is not None:
            logger.error("Asyncio-Loop-Fehler: %s", message, exc_info=exc)
        else:
            logger.error("Asyncio-Loop-Fehler: %s | context=%s", message, context)

    loop.set_exception_handler(handler)


def start_log_queue_listener(log_queue) -> logging.handlers.QueueListener:
    """Empfaengt Log-Records vom BLE-Worker-Kindprozess (siehe ble_worker.py)
    ueber eine multiprocessing.Queue und schreibt sie mit den Handlern des
    Hauptprozesses (Datei + Konsole) weg - so landet auch alles aus dem
    isolierten Worker-Prozess in derselben data/app.log, ohne dass zwei
    Prozesse denselben RotatingFileHandler gleichzeitig beschreiben (das
    waere nicht prozesssicher)."""
    root = logging.getLogger()
    listener = logging.handlers.QueueListener(log_queue, *root.handlers, respect_handler_level=True)
    listener.start()
    return listener


def setup_worker_logging(log_queue, level: str = "DEBUG") -> None:
    """Im BLE-Worker-Kindprozess aufzurufen (statt setup_logging): schickt
    alle Log-Records ueber log_queue an den Hauptprozess, statt selbst eine
    Logdatei zu schreiben."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.DEBUG))
    root.handlers.clear()
    root.addHandler(logging.handlers.QueueHandler(log_queue))
    _install_crash_hooks()


def tail_log_file(log_path: Path, max_lines: int = 300) -> str:
    if not log_path.exists():
        return "(noch keine Logdatei vorhanden)"
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:])
    except Exception as exc:  # noqa: BLE001
        return f"(Logdatei konnte nicht gelesen werden: {exc})"
