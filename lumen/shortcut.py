"""Autostart and desktop shortcut: a .lnk to start.vbs, made by Windows itself.

A .lnk needs COM, which the stdlib does not reach; PowerShell's WScript.Shell does, and it
ships with every Windows. The paths go in as environment variables, never pasted into the
command: a folder name with a quote in it cannot turn into code that way.
"""

import ctypes
import os
import subprocess
from pathlib import Path

from lumen import lang, log, mode, store
from lumen.config import system

STATE = "shortcuts"
_STARTUP, _DESKTOP = 0x07, 0x10  # CSIDL: the user's Autostart folder, the user's desktop
_PS = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK); "
       "$s.TargetPath = $env:TARGET; $s.Arguments = $env:ARGS; "
       "$s.WorkingDirectory = $env:WORKDIR; $s.Description = $env:DESC; "
       "$s.IconLocation = $env:ICON; $s.Save()")
# A Windows built-in icon, so nothing has to ship with the repo.
_ICON = "imageres.dll,76"


def _folder(csidl: int) -> Path:
    """Where Windows keeps it -- the desktop can live in OneDrive, so never guessed."""
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buf)
    return Path(buf.value)


def _make(link: Path) -> bool:
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    env = {**os.environ, "LINK": str(link), "TARGET": str(windows / "wscript.exe"),
           "ICON": str(windows / _ICON),
           "ARGS": f'"{system.ROOT / "start.vbs"}"', "WORKDIR": str(system.ROOT),
           "DESC": lang.t("shortcut.desc", name=mode.assistant())}
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                              env=env, capture_output=True, timeout=30,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as why:
        log.error("shortcut", f"{link.name}: {why!r}")
        return False
    if done.returncode or not link.exists():
        log.error("shortcut", f"{link.name}: {done.stderr.decode(errors='replace')[:300]}")
        return False
    log.info("shortcut", f"angelegt: {link}")
    return True


def autostart() -> bool:
    """Does the autostart link exist? Read from disk -- someone may have deleted it by hand."""
    at = (store.read(STATE, {}) or {}).get("autostart")
    return bool(at) and Path(at).exists()


def set_autostart(on: bool) -> bool:
    """On: a link in the Autostart folder. Off: that link goes to the trash, not away for
    good -- nothing in this program deletes a file."""
    if on == autostart():
        return True
    if not on:
        store.trash(Path(store.read(STATE, {})["autostart"]))
        store.write(STATE, {**(store.read(STATE, {}) or {}), "autostart": None})
        return True
    link = _folder(_STARTUP) / f"{mode.assistant()}.lnk"
    if not _make(link):
        return False
    store.write(STATE, {**(store.read(STATE, {}) or {}), "autostart": str(link)})
    return True


def desktop() -> bool:
    """A link on the desktop, named after her."""
    return _make(_folder(_DESKTOP) / f"{mode.assistant()}.lnk")


def _self_check() -> None:
    """Only what needs no writing: Windows names both folders, and the launcher is there."""
    for csidl in (_STARTUP, _DESKTOP):
        assert _folder(csidl).is_dir(), f"Windows names no folder for CSIDL {csidl}"
    assert (system.ROOT / "start.vbs").exists(), "the shortcuts would point at nothing"
