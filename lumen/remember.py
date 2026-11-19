"""The write pass into memory. Runs when a session begins -- and earlier, in a pause,
when she decides to, and before standby.

The start is the one that cannot fail. A pass at the end of a session only happens if the
session gets to end: a crash, a flat quota or a killed process takes the day with it.
The raw wording is already on disk (`thread.py`), so the *next* start reads it and
files it -- and whatever went wrong in between costs nothing but a delay.
"""

import datetime

from lumen import brain, lang, log, mode, store, thread
from lumen.config import remember as cfg
from lumen.config import system

STATE = "remember"


def start() -> None:
    """Nothing at boot. The pass needs the model, and a machine with no network still
    has to come up."""


def _last() -> str | None:
    return (store.read(STATE, {}) or {}).get("at")


def _stamp() -> dict[str, bytes]:
    """Every note and its bytes, to tell what a pass changed and to back up the old. The
    folder is not versioned, so this is the only way to answer "did the pass do anything"."""
    return {p.name: p.read_bytes() for p in system.MEMORY.glob("*.md")}


def _diff(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    """New, edited and deleted notes alike -- a deletion is the one change with no undo."""
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def _back_up(changed: list[str], before: dict[str, bytes]) -> None:
    """The old wording of every note the pass edited or deleted, appended under today's
    date. Done here and not by her: a request to copy first is a request (rule 4).
    shortcut: whole old files, not just the removed lines -- lossless and simple."""
    day = datetime.date.today().isoformat()
    for name in (p for p in changed if p in before):
        path = system.MEMORY / system.BACKUP / name
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        block = f"\n\n## {day}, before write pass\n\n" + before[name].decode("utf-8", errors="replace")
        store.write_at(path, old + block)


def pending_line() -> str:
    """In a pause, what is not filed yet -- so she can file it now instead of leaving it
    all to the next start. Empty while someone is talking, and when there is nothing."""
    if mode.testing() or not (material := thread.since(_last())):
        return ""
    last = (store.read("turn", {}) or {}).get("last_user_at")
    if last and (datetime.datetime.now()
                 - datetime.datetime.fromisoformat(last)).total_seconds() < cfg.PAUSE_S:
        return ""
    return lang.t("remember.pending", n=len(material), since=material[0]["at"][11:16])


def _brief() -> str:
    return lang.t("remember.brief", name=mode.assistant(), owner=mode.owner())


async def run() -> bool:
    """One pass. Does nothing when there is nothing, which is the common case. True if
    there was something to file -- the clock then starts her next session fresh."""
    if mode.testing():
        log.warn(STATE, "testlauf -- es wird nichts eingetragen")
        return False

    material = thread.since(_last())
    if not material:
        log.debug(STATE, "nichts neues zu sortieren")
        return False

    before = _stamp()
    text = f"{_brief()}\n\n{lang.t('remember.material')}\n\n{thread.spell(material)}"
    log.info(STATE, f"{len(material)} zuege werden einsortiert")

    said = await brain.once(text, job=STATE, writing=str(system.MEMORY))

    # The boundary is the last turn the pass saw, not the clock: anything said while the
    # pass ran would otherwise be marked done without being done.
    store.write(STATE, {"at": material[-1]["at"], "turns": len(material)})

    changed = _diff(before, _stamp())
    log.info(STATE, f"geaendert: {', '.join(changed) if changed else 'nichts'}")
    _back_up(changed, before)
    store.append(STATE, {
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        "turns": len(material),
        "changed": changed,
        "said": said,
    })
    if said:
        log.debug(STATE, said)
    return True


def _self_check() -> None:
    """The two ways this fails silently: filing the same material twice, and filing
    something from a test run."""
    before = store.read(STATE, {}) or {}
    try:
        # The boundary is a timestamp, and exclusive -- otherwise the last turn came along
        # on every pass and ended up twice in memory.
        store.write(STATE, {"at": "2099-01-01T00:00:00"})
        assert thread.since(_last()) == [], "everything before the boundary is done"

        store.write(STATE, {})
        assert _last() is None, "without a pass there is no boundary"

        turn = store.read("turn", None)
        try:
            store.write(STATE, {"at": "2000-01-01T00:00:00"})
            jetzt = datetime.datetime.now()
            store.write("turn", {"last_user_at": jetzt.isoformat()})
            assert pending_line() == "", "no filing in the middle of a conversation"
            store.write("turn", {"last_user_at": (jetzt - datetime.timedelta(seconds=cfg.PAUSE_S + 60)).isoformat()})
            if thread.since(_last()):
                assert pending_line(), "in a pause she has to learn of it"
            store.write(STATE, {"at": "2099-01-01T00:00:00"})
            assert pending_line() == "", "all filed, nothing to say"
        finally:
            store.write("turn", turn if turn is not None else {})
    finally:
        store.write(STATE, before)

    brief = _brief()
    assert "{" not in brief and mode.assistant() in brief and mode.owner() in brief, "an unfilled slot in the brief"
    assert "`_backup/`" in brief, "without the backup folder in the brief she deletes without a way back"
    assert str(system.MEMORY) in lang.t("remember.where", memory=system.MEMORY), "the path has to go along"

    assert _diff({"a.md": b"1", "b.md": b"2"}, {"a.md": b"1", "b.md": b"3", "c.md": b"4"}) == ["b.md", "c.md"]
    assert _diff({"a.md": b"1"}, {}) == ["a.md"], "a deleted note is a change"
    assert system.BACKUP not in _stamp(), "the backup must not back itself up"
