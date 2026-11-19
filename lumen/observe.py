"""What is happening on this machine, read straight from Windows.

No model, no guessing: window, title, idle time, and which programs hold the
microphone. Everything here is a fact with a source, which is what lets the persona
rule hold -- observation is observation, not meaning.

ctypes and winreg only. v1 did the same job without psutil, pywin32 or pyautogui, and
that was one of the decisions worth keeping.
"""

import ctypes
import ctypes.wintypes as w
import datetime
import sys
import winreg
from typing import Any

from lumen import lang, log, mode, store
from lumen.config import observe as cfg
from lumen.config import system

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_MIC = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
    r"\ConsentStore\microphone"
)




class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]


def start() -> None:
    """Nothing to set up. Every reading here is taken fresh at the moment it is asked
    for, so there is no state to get out of date."""


def _exe_of(hwnd: int) -> str:
    pid = w.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = _kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(len(buf))
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def foreground() -> tuple[str, str]:
    """(exe, window title) of whatever is in front. Empty strings if nothing is."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    length = _user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, title, length + 1)
    return _exe_of(hwnd), title.value


_ENUM = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


def running() -> list[str]:
    """Programs with a visible window right now, by executable name.

    Not the process list: a service or a background task has no window and is not
    something he has "open". What this answers is "was the editor open while someone watched
    YouTube", and that question is about windows.

    Context, never a trigger. Every opened Notepad would otherwise wake her -- the
    whitelist stays at five.
    """
    seen: list[str] = []

    def visit(hwnd, _):
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.GetWindow(hwnd, 4):  # GW_OWNER -- owned windows are dialogs, not apps
            return True
        if _user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        if _user32.GetWindowLongW(hwnd, -20) & 0x00000080:  # WS_EX_TOOLWINDOW
            return True
        exe = _exe_of(hwnd)
        if exe.lower() in cfg.NOT_A_PROGRAM:
            return True
        if exe and exe not in seen:
            seen.append(exe)
        return True

    _user32.EnumWindows(_ENUM(visit), 0)
    return sorted(seen)


def idle_s() -> float:
    """Seconds since the last keystroke or mouse move, anywhere on the machine."""
    info = _LastInput(ctypes.sizeof(_LastInput), 0)
    _user32.GetLastInputInfo(ctypes.byref(info))
    return (_kernel32.GetTickCount() - info.dwTime) / 1000.0


def _self_names() -> set[str]:
    """Every name the consent store might file her own process under.

    Two, because Windows files a packaged program under its package family name and an
    ordinary one under its executable. Store Python appears as
    `pythonsoftwarefoundation.python.3.13_qbz5n2kfra8p0`, never as `python.exe` -- so
    comparing executables alone silently fails to recognise her, which is B3: measured
    with v1 holding the microphone next to a Discord call, she listed her own process
    as a stranger.

    The package name is only trusted under WindowsApps, where the parent directory *is*
    the package identity. Elsewhere the parent is just a folder and would be a guess.

    Her ear is covered by this: since 28.09.2026 she reads the microphone in her own
    process. Before, `whisper-stream.exe` held it as a child and needed its own entry (B16).
    """
    path = sys.executable.replace("/", "\\").lower()
    names = {path.rsplit("\\", 1)[-1]}
    parts = path.split("\\")
    if "windowsapps" in parts and len(parts) >= 2:
        names.add(parts[-2])
    return names


def mic_apps() -> list[str]:
    """Executables holding the microphone right now.

    Windows keeps one record per program under the consent store, with the start and
    stop of the last use. `LastUsedTimeStop == 0` means it has not stopped: it is open
    now. Matching is on the executable name, because the key is the full install path
    and a program leaves a fresh key behind after every update.
    """
    me = _self_names()
    live: list[str] = []
    for branch in (_MIC + r"\NonPackaged", _MIC):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, branch)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(key)[0]):
            try:
                name = winreg.EnumKey(key, i)
                sub = winreg.OpenKey(key, name)
                if winreg.QueryValueEx(sub, "LastUsedTimeStop")[0] != 0:
                    continue
            except OSError:
                continue
            exe = name.replace("#", "\\").rsplit("\\", 1)[-1].lower()
            if exe not in me and exe not in live:
                live.append(exe)
    return live


def on_call() -> str | None:
    """Which program says he is talking to someone, or None.

    A name rather than a boolean, so the guard has its rule and she gets a fact she can
    reason about. "Discord hat das Mikrofon" is information; "mic in use" is not.
    """
    for exe in mic_apps():
        if exe in cfg.CALL_APPS:
            return exe
    return None


def look() -> dict[str, Any]:
    """One reading of the machine. Facts only -- no judgement about what they mean."""
    exe, title = foreground()
    # "Nicht zugucken" (28.09.2026): ein Chatfenster traegt Namen im Titel. Hier und nicht
    # spaeter geschwaerzt, damit der Titel nicht einmal in den gespeicherten Stand kommt.
    # Welches Programm vorne ist, bleibt -- sonst zaehlte die Zeit auf nichts.
    # Watching switched off in the settings: the title never even reaches the saved state.
    if mode.blind() or not mode.feature("watch"):
        title = ""
    open_apps = running()
    return {
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        "app": exe,
        "title": title,
        "idle_s": round(idle_s(), 1),
        "mic": mic_apps(),
        "call": on_call(),
        "open": open_apps,
    }


def _check_reading() -> None:
    """Every reading here is a Windows call that can silently return nothing, and a
    snapshot of empty strings still looks like a snapshot."""
    now = look()
    assert set(now) == {"at", "app", "title", "idle_s", "mic", "call", "open"}, f"shape changed: {now}"
    assert now["idle_s"] >= 0, "idle time cannot be negative"
    assert isinstance(now["mic"], list), "mic has to be a list of names, not a flag"
    # No "something has a window": started at login, nothing may have one yet (B9 -- a
    # check tests the code, not the machine it runs on).
    # No "what is in front is among what is open": started from a desktop icon, the
    # desktop is in front -- explorer.exe with no title, which `running` rightly skips.
    # Measured 11.09.2026, the first boots after B8 revived this check: two in a row died.

    # B3. The old form of this check compared her executable name and passed for the
    # wrong reason: it was never going to match the packaged name in the first place.
    # So assert the identity itself, not that a broken comparison found nothing.
    me = _self_names()
    assert any(n.endswith(".exe") for n in me), f"no executable name among {me}"
    if "windowsapps" in sys.executable.lower():
        # Die Identitaet selbst, nicht ihre Anzahl: ein Zaehler zerbrach schon einmal am
        # naechsten Namen und meldete Zuwachs als Fehler (B16).
        assert any("pythonsoftwarefoundation" in n for n in me), (
            f"packaged, so the package name has to be in there too: {me}")
    assert not (me & set(now["mic"])), f"she is listing herself as a stranger: {me & set(now['mic'])}"

    assert now["call"] is None or now["call"] in cfg.CALL_APPS, f"unlisted call app: {now['call']}"



# --- What changed since last time --------------------------------------------------

STATE = "observe"


def _today(now: dict[str, Any], was: dict[str, Any], seconds: float) -> dict[str, float]:
    """Seconds per program today, carried across ticks.

    Charged to the program that was in front for the interval just ended, not the one
    in front now -- otherwise every switch would credit the new program with the old
    one's time. Resets on the date, not on a rolling window: "today" is the word he
    would use.
    """
    tally = dict(was.get("today", {}))
    if was.get("date") != now["at"][:10]:
        tally = {}
    # Nur was tatsaechlich zwischen zwei Blicken lag. Eine groessere Luecke war kein
    # Durchgang, sondern Standby oder ein toter Daemon -- und die der letzten App
    # gutzuschreiben ergab am 11.09.2026 17,4 h Code.exe an einem Tag (B11).
    if was.get("app") and seconds <= cfg.CHARGE_MAX_S:
        tally[was["app"]] = round(tally.get(was["app"], 0) + seconds, 1)
    return tally


def looked() -> None:
    """Note that she has just had a turn, whatever prompted it.

    The quiet look measures from here and not from the last change: right after a
    conversation there is nothing to catch up on. On disk rather than in the process,
    because a standby in between must not hand her a fresh ten minutes of silence
    (rule 5).
    """
    state = store.read(STATE, {}) or {}
    state["looked_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    store.write(STATE, state)


def quiet_s(now: dict[str, Any]) -> float:
    """Seconds since her last turn. Takes the reading rather than the file: `changes`
    has just written it, and a second read of the same second is a second answer.

    Falls back to the wake-up, which `changes` always sets -- otherwise a machine that
    boots straight into three hours of the same window would never reach a first look.
    """
    return (
        datetime.datetime.now()
        - datetime.datetime.fromisoformat(now.get("looked_at") or now["resumed_at"])
    ).total_seconds()


def changes() -> tuple[list[str], dict[str, Any]]:
    """(what changed, the current reading). An empty list is the normal outcome.

    Only the few things in config/observe.py wake her -- and only with watching switched
    on (`__main__`). Everything else is recorded, never a reason to look up.
    """
    now = look()
    was = store.read(STATE, {}) or {}

    gap = 0.0
    if was.get("at"):
        gap = (
            datetime.datetime.fromisoformat(now["at"])
            - datetime.datetime.fromisoformat(was["at"])
        ).total_seconds()

    what: list[str] = []
    # Ihr letzter Blick, aus demselben Grund ausdruecklich: `hinsehen` schreibt ihn, und
    # dieser Durchgang baut `now` neu.
    now["seen_at"], now["seen_today"] = was.get("seen_at"), was.get("seen_today")
    if was:
        # Welches Programm vorne ist, weckt sie nicht mehr (09.11.2026) -- es steht in
        # `now` und damit in dem, was sie beim Hinsehen liest. Nur ins Log, fuer ihn.
        if was.get("app") != now["app"]:
            log.debug("observe", f"app: {was.get('app') or 'nichts'} -> {now['app'] or 'nichts'}")

        away_before = was.get("idle_s", 0) >= cfg.IDLE_S
        away_now = now["idle_s"] >= cfg.IDLE_S
        if away_now and not away_before:
            what.append(lang.t("obs.away", s=int(now['idle_s'])))
        elif away_before and not away_now:
            what.append(lang.t("obs.back", s=int(was['idle_s'])))

        if was.get("call") != now["call"]:
            nobody = lang.t("obs.nobody")
            what.append(lang.t("obs.call", was=was.get('call') or nobody, now=now['call'] or nobody))

    # Eine grosse Luecke heisst: der Rechner hat geschlafen, oder sie war aus. Beides
    # ist ein Aufwachen -- daran haengen der Gedaechtnislauf und eine frische Sitzung.
    now["resumed_at"] = was.get("resumed_at") or now["at"]
    # Ausdruecklich mitnehmen: `now` kommt frisch aus `look()`, und was hier nicht steht,
    # ist beim Schreiben unten weg. Der Anker des stillen Blicks faellt sonst jeden
    # Durchgang auf das Aufwachen zurueck und feuert nie.
    now["looked_at"] = was.get("looked_at")
    now["resumed"] = False
    if not was or gap > cfg.RESUME_GAP_S:
        now["resumed_at"] = now["at"]
        now["resumed"] = True
        if was:
            log.info("observe", f"aufgewacht -- {int(gap // 60)} min Luecke")

    now["today"] = _today(now, was, gap)
    now["date"] = now["at"][:10]
    now["app_since"] = was.get("app_since", now["at"]) if was.get("app") == now["app"] else now["at"]
    store.write(STATE, now)
    return what, now


def _self_check() -> None:
    """The whitelist is the difference between a stream she reads and a stream she
    reads past, and a comparison that fires on everything is the same as no comparison
    at all.

    One function, not two: this module once had a second `_self_check` above, and the
    later definition silently replaced it -- the readings and B3 went unchecked."""
    _check_reading()

    was = {"app": "code.exe", "at": "2026-01-01T10:00:00",
           "date": "2026-01-01", "today": {"code.exe": 60}}
    now = {"at": "2026-01-01T10:01:00"}
    assert _today(now, was, 60)["code.exe"] == 120, "time is charged to who was in front"
    assert _today({"at": "2026-01-02T10:00:00"}, was, 60).get("code.exe") == 60, "a new day starts over"
    assert _today(now, was, 36_000).get("code.exe") == 60, (
        "a ten-hour gap is standby, not ten hours of work (B11)"
    )

    assert _today(now, {**was, "date": None}, 60).get("code.exe") == 60, (
        "a tally with no date could be from any day, so it does not carry over"
    )

    # Der stille Blick misst ab ihrem letzten Zug, nicht ab der letzten Aenderung: sonst
    # bekaeme sie direkt nach einem Gespraech einen Durchgang "nichts Neues".
    lang_ = (datetime.datetime.now() - datetime.timedelta(minutes=20)).isoformat(timespec="seconds")
    jetzt = datetime.datetime.now().isoformat(timespec="seconds")
    assert quiet_s({"looked_at": lang_, "resumed_at": jetzt}) > 1100, "the quiet look does not count"
    assert quiet_s({"looked_at": jetzt, "resumed_at": lang_}) < 5, (
        "her last turn wins over the wake-up, or every tick after a standby reads as quiet"
    )
    assert quiet_s({"resumed_at": lang_}) > 1100, "without an anchor it has to fall back to waking up"
    assert cfg.QUIET_S > system.TICK_S, "a quiet look every tick is not a quiet look"

    # `changes` baut `now` frisch aus `look()`; was dort nicht ausdruecklich hineingetragen
    # wird, ist beim Schreiben weg. Genau daran fiel der Anker fast jeden Durchgang auf das
    # Aufwachen zurueck -- und ein stiller Blick, der nie faellig wird, sieht aus wie keiner.
    hatte = store.read(STATE, None)
    try:
        store.write(STATE, {**(hatte or {}), "looked_at": "2020-01-01T00:00:00"})
        assert changes()[1].get("looked_at") == "2020-01-01T00:00:00", (
            "the quiet look forgets its anchor between ticks"
        )
    finally:
        store.write(STATE, hatte if hatte is not None else {})

    # A folded observation must not deny that something was said.
    folded = alongside(["back: 900s"], {"app": "", "title": "", "idle_s": 0, "call": None})
    assert folded.startswith(lang.t("obs.folded_header")), f"the folded header must not deny that a message came: {folded[:90]}"

    said = as_message(["back: 900s"], {})
    assert "back: 900s" in said and "{" not in said, said

    # 09.11.2026: eine Meldung traegt, was passiert ist -- den Zustand holt sie sich selbst.
    assert "WINWORD" not in said, "the state rides only on hinsehen"
    stand = {"at": "2026-01-01T18:30:00", "app": "WINWORD.EXE", "title": "Bericht", "idle_s": 4,
             "call": None, "open": ["WINWORD.EXE", "chrome.exe"], "app_since": "2026-01-01T18:00:00",
             "today": {"WINWORD.EXE": 3000, "chrome.exe": 900},
             "seen_at": "2026-01-01T18:05:00", "seen_today": {"WINWORD.EXE": 1800, "chrome.exe": 900}}
    blick = status(stand)
    assert "WINWORD.EXE" in blick and lang.t("obs.open", apps="chrome.exe") in blick, blick
    assert lang.t("obs.since_look", ago=lang.t("obs.ago", t="25min"), apps="WINWORD.EXE 20min") in blick, (
        f"what came since her last look is the point of looking again: {blick}")
    assert lang.t("obs.ago", t="25min") in nudge(stand) and "hinsehen" in nudge(stand), nudge(stand)
    assert lang.t("obs.not_seen") in nudge({**stand, "seen_at": "2025-12-31T23:00:00"}), "yesterday's look is not today's"
    # `changes` baut `now` neu -- ihr letzter Blick muss den Durchgang ueberleben wie der Anker oben.
    hatte = store.read(STATE, None)
    try:
        store.write(STATE, {**(hatte or {}), "seen_at": "2020-01-01T00:00:00"})
        assert changes()[1].get("seen_at") == "2020-01-01T00:00:00", "her last look is forgotten between ticks"
        seen()
        assert store.read(STATE, {})["seen_at"][:10] == datetime.date.today().isoformat(), "looking has to count"
    finally:
        store.write(STATE, hatte if hatte is not None else {})


def _spell(seconds: float) -> str:
    """Seconds as he would say them."""
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}min"
    return f"{minutes // 60}h{minutes % 60:02d}"


def alongside(what: list[str], now: dict[str, Any]) -> str:
    """The same events, but as background to a message he just typed.

    Only the header differs, and it has to: the normal one says "he has said nothing",
    which is false in exactly this case.
    """
    return as_message(what, now, lang.t("obs.folded_header"))


def as_message(what: list[str], now: dict[str, Any], header: str = "") -> str:
    """What happened, in the words she will read -- the events and what belongs to them,
    not the state of the machine. That she reads when she looks (`glance`).

    The header comes from config, not from here: a sentence she reads is a setting like
    any number, and one scattered across two files drifts.
    """
    lines = [(header or lang.t("obs.event_header")).format(owner=mode.owner())]
    lines += [lang.t("obs.changed", what=w) for w in what]
    return "\n".join(lines)


def seen() -> None:
    """Mark that she looked -- `hinsehen` or a screenshot. The nudge tells her how long
    ago, and the next look what came since. On disk, so a new session still knows."""
    state = store.read(STATE, {}) or {}
    state["seen_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    state["seen_today"] = dict(state.get("today", {}))
    store.write(STATE, state)


def _seen_ago(now: dict[str, Any]) -> str:
    at = now.get("seen_at")
    if not at or at[:10] != now["at"][:10]:
        return lang.t("obs.not_seen")
    took = (datetime.datetime.fromisoformat(now["at"]) - datetime.datetime.fromisoformat(at)).total_seconds()
    return lang.t("obs.seen_ago", ago=_ago(now))


def nudge(now: dict[str, Any]) -> str:
    """The header of a nudge: that it is one, and when she last looked."""
    return lang.t("obs.nudge", seen=_seen_ago(now), owner=mode.owner())


def glance() -> str:
    """What is going on right now, for `hinsehen` -- and the mark that she looked.

    The window and idle time fresh from Windows, the day's tally from the last tick (at
    most one tick old): reading the machine twice in one tick would charge time twice."""
    was = store.read(STATE, {}) or {}
    now = {**was, **look()}
    if now["app"] != was.get("app"):
        now["app_since"] = now["at"]
    text = status(now)
    seen()
    return text


def status(now: dict[str, Any]) -> str:
    """The state of the machine in her words: what is in front and since when, idle,
    microphone, what else is open, the day so far, and what came since she
    last looked."""
    lines = [lang.t("obs.front", app=now["app"] or lang.t("obs.nothing"), title=now["title"])]
    if now.get("app_since"):
        lines[-1] += lang.t("obs.front_since", t=now['app_since'][11:16])
    lines.append(lang.t("obs.idle", s=int(now['idle_s'])))
    if now["call"]:
        lines.append(lang.t("obs.mic", app=now['call']))
    others = [a for a in now.get("open", []) if a != now["app"]]
    if others:
        lines.append(lang.t("obs.open", apps=", ".join(others)))
    if now.get("today"):
        top = sorted(now["today"].items(), key=lambda kv: -kv[1])[:4]
        lines.append(lang.t("obs.today", apps=", ".join(f"{a} {_spell(s)}" for a, s in top)))
    lines.append(_since_seen(now))
    return "\n".join(lines)


def _since_seen(now: dict[str, Any]) -> str:
    """Where the time went since her last look -- the part a body double would notice."""
    if not now.get("seen_at") or now["seen_at"][:10] != now["at"][:10]:
        return lang.t("obs.first_look")
    before = now.get("seen_today") or {}
    moved = {a: s - before.get(a, 0) for a, s in now.get("today", {}).items()}
    top = sorted(((a, s) for a, s in moved.items() if s >= 60), key=lambda kv: -kv[1])[:4]
    said = ", ".join(f"{a} {_spell(s)}" for a, s in top) or lang.t("obs.little")
    return lang.t("obs.since_look", ago=_ago(now), apps=said)


def _ago(now: dict[str, Any]) -> str:
    took = (datetime.datetime.fromisoformat(now["at"]) - datetime.datetime.fromisoformat(now["seen_at"])).total_seconds()
    return lang.t("obs.ago", t=_spell(max(took, 0)))
