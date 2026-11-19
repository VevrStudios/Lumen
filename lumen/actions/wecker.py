"""His alarms: at a time he names, one turn in which she does what he asked for then.

One-off, as many as he likes, on disk (rule 5). No timer of its own: the clock asks
`next_s` how long it may sleep and `due` what has come up (rule 2). A due alarm's turn
counts as his (`guard.ALARM`), so only he sets, changes or deletes one -- the guard.
"""

import datetime as dt
from typing import Any

from claude_agent_sdk import tool

from lumen import lang, log, store

STATE = "wecker"

_WANN = {
    "um": {"type": "string",
           "description": "HH:MM (the next such time) or YYYY-MM-DD HH:MM"},
    "in_minuten": {"type": "integer", "description": "instead of `um`: in this many minutes"},
}


def _read() -> dict[str, Any]:
    return store.read(STATE, {}) or {}


def waiting() -> list[dict[str, Any]]:
    return sorted(_read().get("open", []), key=lambda w: w["um"])


def _at(iso: str) -> str:
    return dt.datetime.fromisoformat(iso).strftime(lang.pack().DATE)


def line() -> str:
    """His alarms still to come, for her messages -- she changes them by number. Empty if none."""
    if not (open_ := waiting()):
        return ""
    return lang.t("alarm.list", alarms=" · ".join(f"[{w['n']}] {_at(w['um'])} {w['was']}" for w in open_))


def next_s() -> float:
    """Seconds until the next alarm, so the clock wakes for it instead of up to a tick late."""
    if not (open_ := waiting()):
        return float("inf")
    return max(0.0, (dt.datetime.fromisoformat(open_[0]["um"]) - dt.datetime.now()).total_seconds())


def due() -> list[str]:
    """Every alarm whose time has come, off the list and spelled for her turn.

    Off before the turn, not after: one-off means one attempt. A turn that fails halfway
    must not open the program again on every tick after it.
    """
    now, jetzt = _read(), dt.datetime.now()
    fällig = [w for w in now.get("open", []) if dt.datetime.fromisoformat(w["um"]) <= jetzt]
    if not fällig:
        return []
    store.write(STATE, {**now, "open": [w for w in now["open"] if w not in fällig]})
    for w in fällig:
        log.info("wecker", f"[{w['n']}] faellig: {w['was']}")
    # Beide Zeiten: hat der Rechner geschlafen, ist ein Wecker Stunden zu spät, und ob er
    # dann noch Sinn hat, sieht sie nur so.
    return [lang.t("alarm.due", n=w["n"], set=_at(w["gestellt"]), at=_at(w["um"]),
                   now=_at(jetzt.isoformat()), what=w["was"]) for w in fällig]


def _when(args: dict[str, Any]) -> dt.datetime:
    """`in_minuten` or `um`. A bare time is the next one, so "18:00" said at 19:00 is tomorrow."""
    jetzt = dt.datetime.now().replace(microsecond=0)
    um, minuten = str(args.get("um") or "").strip(), args.get("in_minuten")
    if bool(um) == (minuten is not None):
        raise ValueError(lang.t("alarm.one_of"))
    if minuten is not None:
        at = jetzt + dt.timedelta(minutes=int(minuten))
    else:
        try:
            at = dt.datetime.combine(jetzt.date(), dt.time.fromisoformat(um))
            at += dt.timedelta(days=1) if at <= jetzt else dt.timedelta()
        except ValueError:
            at = dt.datetime.fromisoformat(um)
            at = at.astimezone().replace(tzinfo=None) if at.tzinfo else at
    if at <= jetzt:
        raise ValueError(lang.t("alarm.past", at=_at(at.isoformat())))
    return at


def _reply(text: str, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], **({"is_error": True} if error else {})}


def keep(was: str, um: dt.datetime) -> int:
    now = _read()
    n = now.get("next", 1)
    kept = now.get("open", []) + [{"n": n, "um": um.isoformat(timespec="seconds"), "was": was,
                                   "gestellt": dt.datetime.now().isoformat(timespec="seconds")}]
    store.write(STATE, {"open": kept, "next": n + 1})
    return n


def change(n: int, was: str = "", um: dt.datetime | None = None) -> bool:
    now = _read()
    hit = [w for w in now.get("open", []) if w["n"] == n]
    for w in hit:
        if was:
            w["was"] = was
        if um:
            w["um"] = um.isoformat(timespec="seconds")
    store.write(STATE, now)
    return bool(hit)


def drop(n: int) -> bool:
    now = _read()
    rest = [w for w in now.get("open", []) if w["n"] != n]
    store.write(STATE, {**now, "open": rest})
    return len(rest) < len(now.get("open", []))


@tool(
    "wecker_stellen",
    "tool.wecker_stellen",
    {"type": "object", "properties": {"was": {"type": "string"}, **_WANN}, "required": ["was"]},
)
async def wecker_stellen(args: dict[str, Any]) -> dict[str, Any]:
    if not str(args.get("was") or "").strip():
        return _reply(lang.t("alarm.no_what"), error=True)
    try:
        um = _when(args)
    except ValueError as why:
        return _reply(str(why), error=True)
    n = keep(args["was"].strip(), um)
    log.info("act", f"wecker [{n}] {um:%d.%m. %H:%M}: {args['was']}")
    return _reply(lang.t("alarm.set", n=n, at=_at(um.isoformat())))


@tool(
    "wecker_aendern",
    "tool.wecker_aendern",
    {"type": "object", "properties": {"nummer": {"type": "integer"}, "was": {"type": "string"}, **_WANN},
     "required": ["nummer"]},
)
async def wecker_aendern(args: dict[str, Any]) -> dict[str, Any]:
    n, was = args["nummer"], str(args.get("was") or "").strip()
    try:
        um = _when(args) if args.get("um") or args.get("in_minuten") is not None else None
    except ValueError as why:
        return _reply(str(why), error=True)
    if not was and not um:
        return _reply(lang.t("alarm.nothing"), error=True)
    if not change(n, was, um):
        return _reply(lang.t("alarm.missing", n=n), error=True)
    log.info("act", f"wecker [{n}] geaendert: {args}")
    return _reply(lang.t("alarm.changed", n=n))


@tool("wecker_loeschen", "tool.wecker_loeschen", {"nummer": int})
async def wecker_loeschen(args: dict[str, Any]) -> dict[str, Any]:
    n = args["nummer"]
    return _reply(lang.t("alarm.deleted" if drop(n) else "alarm.was_missing", n=n))


TOOL = wecker_stellen
EXTRA_TOOLS = [wecker_aendern, wecker_loeschen]


def _self_check() -> None:
    """Runs against the real file, so it puts back exactly what it found."""
    was = store.read(STATE, None)
    jetzt = dt.datetime.now()
    try:
        store.write(STATE, {})
        assert line() == "" and next_s() == float("inf") and due() == [], "no alarms, nothing due"

        bald = _when({"in_minuten": 30})
        assert 29 * 60 < (bald - jetzt).total_seconds() <= 30 * 60 + 1, "in half an hour is half an hour"
        um = _when({"um": (jetzt - dt.timedelta(minutes=1)).strftime("%H:%M")})
        assert um > jetzt and um - jetzt <= dt.timedelta(days=1), "a passed time today means tomorrow"
        for bad in ({}, {"um": "18:00", "in_minuten": 5}, {"um": "irgendwann"},
                    {"um": "2020-01-01 18:00"}, {"in_minuten": -5}):
            try:
                _when(bad)
                raise AssertionError(f"accepted a time that is none: {bad}")
            except ValueError:
                pass

        a = keep("Spotify aufmachen", bald)
        b = keep("Code-Auftrag xyz", jetzt + dt.timedelta(hours=2))
        assert (a, b) == (1, 2) and "[2]" in line() and 0 < next_s() <= 30 * 60 + 1
        assert change(a, um=jetzt - dt.timedelta(seconds=1)) and not change(99, "x"), "change by number"
        fällig = due()
        assert len(fällig) == 1 and "Spotify aufmachen" in fällig[0], f"exactly the passed one: {fällig}"
        assert due() == [], "one-off: an alarm rings once"
        assert [w["n"] for w in waiting()] == [2] and change(2, "anders") and "anders" in line()
        assert drop(2) and not drop(2) and keep("noch einer", bald) == 3, "numbers are never reused"
    finally:
        store.write(STATE, was if was is not None else {})
