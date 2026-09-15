"""Zentrale, moeglichst luecken-freie Logging-Konfiguration.

Ziel: Wenn der Prozess abstuerzt oder sich merkwuerdig verhaelt, soll IMMER
etwas in data/app.log stehen - inklusive unbehandelter Exceptions im
Hauptthread, in Hintergrund-Threads und in der asyncio-Event-Loop des
BLE-Threads. Nichts soll still verschwinden.
"""
import asyncio
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s"


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


def tail_log_file(log_path: Path, max_lines: int = 300) -> str:
    if not log_path.exists():
        return "(noch keine Logdatei vorhanden)"
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:])
    except Exception as exc:  # noqa: BLE001
        return f"(Logdatei konnte nicht gelesen werden: {exc})"
