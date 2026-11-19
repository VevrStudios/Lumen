"""The only way to disk. Everything that must survive a restart goes through here, so
one place knows about atomic writes, encoding and the trash.

This is her operating state, not her memory -- the notes in the vault are a different
thing with different rules.
"""

import json
import msvcrt
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from lumen import log
from lumen.config import system

TRASH = "_trash"

# The open handle behind the single-instance lock. Kept, never closed: the OS releases
# the lock when the process ends, however it ends -- which a lock *file* would not do.
_lock = None


def start() -> None:
    system.DATA.mkdir(parents=True, exist_ok=True)


def _try_lock():
    path = system.DATA / "lumen.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def claim() -> bool:
    """Is this the only instance? False means another one already runs, and this one must go.

    B5: three once ran at once -- from a shortcut, a scheduled task and the shortcut
    again. Three clocks, three sessions,
    three writers on the same files, and `append` rewrites the whole file, so two of
    them silently erased each other's lines. The check in start.vbs was supposed to
    prevent it and could not see the scheduled instance at all: WMI hides the command
    line of processes in another session. A guard that cannot see is a decoration.

    The lock is taken by the operating system on an open handle, so a crash or a kill
    releases it -- no stale lock file to clean up after a power cut.
    """
    global _lock
    if _lock is None:
        _lock = _try_lock()
    return _lock is not None


def _path(name: str) -> Path:
    return system.DATA / f"{name}.json"


def read(name: str, default: Any = None) -> Any:
    """Read one state file, falling back to default if it is missing or unreadable.

    A daemon has to boot with a corrupted state file rather than refuse to. The bad
    file is kept in the trash instead of overwritten, because it is usually the only
    evidence of what went wrong.
    """
    path = _path(name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as why:
        log.error("store", f"{path.name} unreadable, using default: {why}")
        trash(path)
        return default


def write(name: str, data: Any) -> None:
    """Write one state file atomically.

    The daemon can be killed at any moment. A half-written state file would make the
    restart lose more than the kill did, which is the opposite of the point.
    """
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(".writing")
    scratch.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(scratch, path)  # atomic within a volume, on Windows too


def write_text(name: str, text: str, suffix: str = ".md") -> Path:
    """Write a derived text file atomically and return where it went.

    Not everything on disk is state to keep -- the assembled system prompt is rebuilt
    from persona and vault every session. It still comes through here, so "one place
    writes to disk" stays literally true instead of gaining its first exception.
    """
    path = system.DATA / f"{name}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(".writing")
    scratch.write_text(text, encoding="utf-8")
    os.replace(scratch, path)
    return path


def write_at(path: Path, text: str) -> Path:
    """Write a text file at a path outside `data/`, atomically.

    Two callers: the memory backup (remember.py) and the window's Azure key (.env). It
    still goes through here so "one module writes to disk" stays literally true.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(path.suffix + ".writing")
    scratch.write_text(text, encoding="utf-8")
    os.replace(scratch, path)
    return path


def _env_lines(lines: list[str], values: dict[str, str]) -> list[str]:
    """.env with `values` set: other lines kept as they are, an empty value removes its key."""
    for value in values.values():
        if "\n" in value or "\r" in value:
            raise ValueError("a line break in a secret would write a second key")
    kept = [line for line in lines if line.split("=", 1)[0].strip() not in values]
    return kept + [f"{key}={value}" for key, value in values.items() if value]


def save_secrets(values: dict[str, str]) -> None:
    """Keys from the window (Azure) into .env. The model never reaches this file:
    '.env' is in guard.NEVER for every tool."""
    lines = system.ENV.read_text(encoding="utf-8").splitlines() if system.ENV.exists() else []
    write_at(system.ENV, "\n".join(_env_lines(lines, values)) + "\n")
    system.secrets_changed()
    log.info("store", f".env: {', '.join(k for k, v in values.items() if v) or 'nichts'} gesetzt, "
                      f"{', '.join(k for k, v in values.items() if not v) or 'nichts'} entfernt")


def write_bytes(name: str, data: bytes) -> Path:
    """A file he sent her -- an image, a PDF -- kept under `data/` and returned by path.

    Kept, not scratch: the path goes into the thread, and after a restart she should
    still be able to open what he showed her.
    """
    path = system.DATA / name
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(path.suffix + ".writing")
    scratch.write_bytes(data)
    os.replace(scratch, path)
    return path


def append(name: str, record: dict[str, Any], keep: int | None = 2000) -> None:
    """Add one line to a running record, oldest lines dropped past `keep`.

    The cap is not tidiness. v1's log reached 28.5 MB, at which point nobody read it --
    and a record nobody reads is the same as no record, except it also costs disk.
    `keep=None` is for the one record that must not lose anything: the thread.
    """
    path = system.DATA / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines.append(json.dumps(record, ensure_ascii=False))
    scratch = path.with_suffix(".writing")
    scratch.write_text("\n".join(lines if keep is None else lines[-keep:]) + "\n", encoding="utf-8")
    os.replace(scratch, path)


def tail(name: str, n: int) -> list[dict[str, Any]]:
    """The last n records of a running record, oldest first.

    A single unreadable line is skipped rather than fatal. These files are appended to
    by a process that can be killed mid-write, and one torn line must not cost the
    whole record -- nor stop a boot that only wanted to read the last few entries.
    """
    path = system.DATA / f"{name}.jsonl"
    if not path.exists():
        return []
    out, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    if bad:
        log.warn("store", f"{path.name}: {bad} unlesbare zeilen uebersprungen")
    return out


def trash(path: Path) -> Path | None:
    """Move instead of delete. Nothing in this program removes a file for good.

    Returns where it went, or None if there was nothing there.
    """
    if not path.exists():
        return None
    box = system.DATA / TRASH / datetime.now().strftime("%Y%m%dT%H%M%S")
    box.mkdir(parents=True, exist_ok=True)
    gone = box / path.name
    os.replace(path, gone)
    log.info("store", f"{path.name} -> {gone.relative_to(system.DATA)}")
    return gone


def _self_check() -> None:
    """One runnable check: a write that cannot be read back is a silent data loss."""
    probe = "_selfcheck"
    payload = {"n": 1, "text": "ä ö ü — non-ascii must survive the round trip"}

    write(probe, payload)
    assert read(probe) == payload, "write/read round trip changed the data"
    assert not _path(probe).with_suffix(".writing").exists(), "scratch file left behind"

    assert read("_nothing_here", "fallback") == "fallback", "missing file must give the default"

    gone = trash(_path(probe))
    assert gone is not None and gone.exists(), "trash must move the file, not drop it"
    assert not _path(probe).exists(), "trashed file is still in place"
    assert trash(_path(probe)) is None, "trashing nothing must be a no-op, not an error"

    os.remove(gone)
    gone.parent.rmdir()

    # B5: haelt diese Instanz die Sperre, darf keine zweite sie bekommen. Ohne gehaltene
    # Sperre (Skripte ausserhalb von __main__) gibt es hier nichts zu pruefen.
    if _lock is not None:
        assert _try_lock() is None, "a second instance could take the lock (B5)"

    # .env: a saved key replaces its old line, the rest stays, empty removes.
    assert _env_lines(["A=1", "# note", "AZURE_SPEECH_KEY=old"], {"AZURE_SPEECH_KEY": "new"}) == \
        ["A=1", "# note", "AZURE_SPEECH_KEY=new"]
    assert _env_lines(["AZURE_SPEECH_KEY=old"], {"AZURE_SPEECH_KEY": ""}) == []
    try:
        _env_lines([], {"AZURE_SPEECH_KEY": "x\nEVIL=1"})
    except ValueError:
        pass
    else:
        raise AssertionError("a line break must not smuggle a second key into .env")

    # tail: leeres Ergebnis statt Absturz, wenn es die Datei nie gab.
    assert tail("_nothing_here", 5) == [], "a missing record must read as empty"

    # keep=None hält alles, sonst gehen dem Faden seine ältesten Worte verloren.
    probe = system.DATA / "_selfcheck_keep.jsonl"
    try:
        for i in range(3):
            append("_selfcheck_keep", {"i": i}, keep=None)
        append("_selfcheck_keep", {"i": 3}, keep=None)
        assert len(tail("_selfcheck_keep", 10)) == 4, "keep=None dropped lines"
        append("_selfcheck_keep", {"i": 4}, keep=2)
        assert [e["i"] for e in tail("_selfcheck_keep", 10)] == [3, 4], "keep=2 must cap"
    finally:
        probe.unlink(missing_ok=True)
