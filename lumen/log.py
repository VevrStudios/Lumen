"""Logging. Nothing else in this project calls print or logging directly, so output
stays greppable and can be redirected or silenced in one place.

Every call names where it came from: log.info("clock", "tick 3").
"""

import contextlib
import logging
import sys
from logging.handlers import RotatingFileHandler

from lumen.config import system

_log = logging.getLogger("lumen")


def start() -> None:
    system.LOGS.mkdir(parents=True, exist_ok=True)
    _log.setLevel(logging.DEBUG)
    shape = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    to_file = RotatingFileHandler(
        system.LOGS / "lumen.log",
        maxBytes=system.LOG_MAX_BYTES,
        backupCount=system.LOG_KEEP,
        encoding="utf-8",
    )
    to_file.setFormatter(shape)

    handlers = [to_file]

    # B4: started by the Task Scheduler she runs under pythonw.exe, which has no
    # console at all -- sys.stdout is None, and `None.reconfigure` killed the process
    # inside the logger, so nothing was written about why. The daemon case is the one
    # this project is for, and it was the one case start() could not survive.
    if sys.stdout is not None:
        # Windows opens stdout as cp1252, which turns every umlaut in what she says
        # into a replacement character. The file is already utf-8; this makes them agree.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        to_screen = logging.StreamHandler(sys.stdout)
        to_screen.setFormatter(shape)
        handlers.append(to_screen)

    # Replace rather than add: calling start() twice must not double every line.
    _log.handlers = handlers


def debug(where: str, what: str) -> None:
    _log.debug("[%s] %s", where, what)


def info(where: str, what: str) -> None:
    _log.info("[%s] %s", where, what)


def warn(where: str, what: str) -> None:
    _log.warning("[%s] %s", where, what)


def error(where: str, what: str) -> None:
    _log.error("[%s] %s", where, what)


def exception(where: str, what: str) -> None:
    """Like error, plus the traceback. Only meaningful inside an except block."""
    _log.exception("[%s] %s", where, what)


@contextlib.contextmanager
def hushed():
    """Nichts schreiben, solange das hier läuft.

    Für die Self-Checks beim Boot. `mode` meldet absichtlich laut, wenn Testmodus oder
    Stumm an sind -- prüft man das bei jedem Start durch, stehen fünf solche Zeilen im
    Log, ohne dass irgendwas an ist. Dann ist die Lautstärke wertlos, und genau die war
    der Sinn der Sache. Asserts werfen, sie loggen nicht: hier geht nichts verloren.
    """
    was = _log.disabled
    _log.disabled = True
    try:
        yield
    finally:
        _log.disabled = was


def _self_check() -> None:
    """One runnable check: start() has to survive a process with no console, because
    that is how she actually runs."""
    real = sys.stdout
    try:
        sys.stdout = None
        start()
        info("log", "headless start ok")
    finally:
        sys.stdout = real
        start()
