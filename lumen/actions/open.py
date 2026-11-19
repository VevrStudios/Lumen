"""Etwas aufmachen: ein Programm, eine Datei, ein Ordner, eine Adresse.

`os.startfile` ist der ganze Mechanismus -- es nimmt Pfade, Ordner, URLs und Shell-URIs
und überlässt Windows die Entscheidung, womit. Was es **nicht** nimmt, ist ein blosser
Programmname, und genau den sagt sie ("mach Spotify auf"). Dafür die zwei Nachschlage-
wege, die Windows selbst benutzt: die Registry (App Paths) und das Startmenü.

Argumente gibt es hier bewusst nicht. Ein Programm starten heisst starten -- wer einem
Programm eine Kommandozeile mitgeben kann, hat eine Shell, und die hat sie nicht.
"""

import os
import winreg
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from lumen import lang, log

_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

# Wo Windows die Verknüpfungen hinlegt -- das Startmenü des Nutzers und das für alle.
_MENUS = (
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
)


def _from_registry(name: str) -> str | None:
    """Der Weg, den auch das Ausführen-Fenster nimmt. Nur eingetragene Programme."""
    key = name if name.lower().endswith(".exe") else f"{name}.exe"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with (winreg.OpenKey(root, _APP_PATHS) as paths,
                  winreg.OpenKey(paths, key) as handle):
                path = winreg.QueryValueEx(handle, "")[0].strip('"')
                if path and Path(path).exists():
                    return path
        except OSError:
            continue
    return None


def _from_menu(name: str) -> str | None:
    """Die Verknüpfung aus dem Startmenü. Deckt alles ab, was ein Installer anlegt --
    Spiele und Launcher stehen fast nie in der Registry, aber fast immer hier.

    `os.startfile` öffnet eine `.lnk` direkt; sie muss also nicht aufgelöst werden.
    """
    wanted = name.lower().removesuffix(".exe")
    best: str | None = None
    for menu in _MENUS:
        if not menu.exists():
            continue
        for link in menu.rglob("*.lnk"):
            stem = link.stem.lower()
            if stem == wanted:
                return str(link)
            # Ein Treffer im Namen zählt, aber nur als Rückfall: "Steam" findet so auch
            # "Steam Launcher", ohne dass ein exakter Treffer verdrängt wird.
            if best is None and wanted in stem:
                best = str(link)
    return best


_UNINSTALL = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)


def _from_uninstall(name: str) -> str | None:
    """Der dritte Weg: was Windows über installierte Programme weiß.

    Für Spiele der wichtigste. Gemessen am Original: ein Spiel hatte weder eine
    Verknüpfung noch einen Installationsort -- aber Steam trägt jedes Spiel als
    `Steam App <id>` ein, und `steam://rungameid/<id>` startet es über Steam.

    Ein `DisplayIcon`, das auf einen Installer zeigt, wird übersprungen: manche Programme
    tragen dort ihren Installer ein, und den zu starten wäre eine Neuinstallation
    statt eines Starts.
    """
    wanted = name.lower().removesuffix(".exe")
    for root, path in _UNINSTALL:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    entry = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, entry) as sub:
                        display = winreg.QueryValueEx(sub, "DisplayName")[0]
                        if wanted not in display.lower():
                            continue
                        if entry.lower().startswith("steam app "):
                            return f"steam://rungameid/{entry.rsplit(' ', 1)[-1]}"
                        icon = winreg.QueryValueEx(sub, "DisplayIcon")[0].split(",")[0].strip('"')
                except OSError:
                    continue
                if icon.lower().endswith(".exe") and "install" not in Path(icon).name.lower():
                    if Path(icon).exists():
                        return icon
    return None


def _resolve(ziel: str) -> tuple[str | None, str]:
    """(was startfile bekommt, wie es gefunden wurde). None heisst: nicht gefunden."""
    if ziel.lower().startswith(("http://", "https://")):
        return ziel, "adresse"
    if Path(ziel).exists():
        return ziel, "pfad"
    if found := _from_registry(ziel):
        return found, "registry"
    if found := _from_menu(ziel):
        return found, "startmenue"
    if found := _from_uninstall(ziel):
        return found, "installiert"
    return None, "nichts"


@tool(
    "open",
    "tool.open",
    {"ziel": str},
)
async def open_ziel(args: dict[str, Any]) -> dict[str, Any]:
    ziel = args["ziel"]
    what, how = _resolve(ziel)
    if not what:
        log.info("act", f"open {ziel}: nicht gefunden")
        return {"content": [{"type": "text", "text": lang.t("reply.open_missing", target=ziel)}]}
    try:
        os.startfile(what)  # noqa: S606 -- genau dafür ist es da, und es nimmt keine Argumente
    except OSError as why:
        log.warn("act", f"open {what}: {why}")
        return {"content": [{"type": "text", "text": lang.t("reply.open_failed", target=ziel, why=why)}]}
    log.info("act", f"open {ziel} -> {what} ({how})")
    return {"content": [{"type": "text", "text": lang.t("reply.opened", what=what)}]}


TOOL = open_ziel


def _self_check() -> None:
    """Was ohne Bildschirm prüfbar ist: die Einordnung des Ziels. Dass ein bestimmtes
    Programm auf diesem Rechner installiert ist, wird **nicht** geprüft -- ein Assert,
    der vom Zustand der Maschine abhängt, verhindert irgendwann den Start (B9)."""
    assert _resolve("https://example.com") == ("https://example.com", "adresse")
    assert _resolve(str(Path(__file__)))[1] == "pfad", "eine existierende Datei ist ein Pfad"
    assert _resolve("gibtesnichtxyz123") == (None, "nichts"), "unbekanntes Ziel ist keins"
