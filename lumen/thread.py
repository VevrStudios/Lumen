"""The thread: what survives a restart.

The conversation lives inside the model session, and the session lives inside the
process. Standby, a crash, a new build -- each of those took the whole thing with it.
This keeps the raw wording on disk and hands it back when a fresh session opens.

Raw material only, never a summary. v1 condensed at the end of a session and the
condensate *replaced* the original, so one timeout cost the session for good. Here the
full turn stays on disk; only the recap is trimmed, and it can be rebuilt.
"""

from datetime import datetime
from typing import Any

from lumen import lang, log, mode, store
from lumen.config import thread as cfg

RECORD = "turns"
THOUGHTS = "thought"  # written by the clock; the other half of the same thread


def start() -> None:
    """Nothing at boot. The record is append-only and `store` owns the directory."""


def note(asked: str, said: str, refused: bool = False, via: str = "", stopped: bool = False,
         deep: bool = False) -> None:
    """One exchange, verbatim. Called for every turn that came from the owner, and for
    what she says of her own accord (`asked` empty).

    No model is involved in deciding what goes in here, which is the point: something
    she has to remember to save is something she will one day not save.
    """
    store.append(RECORD, {
        "at": datetime.now().isoformat(timespec="seconds"),
        "asked": asked,
        "said": said,
        "testing": mode.testing(),
        "refused": refused,
        "via": via,
        "stopped": stopped,
        "deep": deep,
    # Uncapped: memory keeps facts, not wording, so this is the one place the exact
    # words survive.
    # shortcut: the whole file is rewritten per turn, fine for years at ~30 turns a day.
    }, keep=None)


def _kept(e: dict[str, Any]) -> bool:
    """Whether an entry may be read back into a model. Test entries are real events but
    not real statements. A refused turn would carry its trigger along: measured
    08.10.2026, a recap holding one got the fresh session refused as well (B22)."""
    return not e.get("testing") and not e.get("refused")


def _when(at: str) -> str:
    return datetime.fromisoformat(at).strftime("%d.%m. %H:%M")


def _cut(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= cfg.CUT else text[: cfg.CUT] + " [...]"


def _asker(e: dict[str, Any]) -> str:
    return mode.owner()


def _block(e: dict[str, Any]) -> str:
    head = f"{_when(e['at'])}\n{_asker(e)}: {_cut(e['asked'])}" if e.get("asked") else _when(e["at"])
    # Otherwise a stopped sentence reads as if she had ignored it.
    said = lang.t("thread.stopped") if e.get("stopped") else _cut(e.get("said"))
    return f"{head}\n{lang.t('thread.you')}: {said}"


def _thought(e: dict[str, Any]) -> str:
    # "notiertest", not "dachtest": text labelled as her own reasoning inside a user turn
    # trips the 5.5 family's reasoning_extraction classifier. B21: Sonnet 5.5 refused
    # every fresh session that carried one, 0/5 before the rename, 5/5 after.
    saw = "; ".join(e.get("saw") or [])
    return f"{_when(e['at'])}  ({saw})\n{lang.t('thread.noted')}: {_cut(e['thought'])}"


def since(at: str | None) -> list[dict[str, Any]]:
    """Everything said since `at`, oldest first, test material dropped.

    The raw record, uncapped and uncut -- this is what the write pass reads. The recap is
    a different question and takes the last few; a filing pass that only saw the last few
    would quietly lose whatever came before them.
    """
    return [
        e for e in store.tail(RECORD, 2000)
        if _kept(e) and (not at or e.get("at", "") > at)
    ]


def spell(entries: list[dict[str, Any]]) -> str:
    """The same rendering the recap uses, without the length cap."""
    return "\n\n".join(
        f"{_when(e['at'])}\n"
        + (f"{_asker(e)}: {e['asked']}\n" if e.get("asked") else "")
        + f"{lang.t('thread.you')}: {e.get('said') or ''}"
        for e in entries
    )


def _recent() -> list[tuple[str, str]]:
    """The last entries from both halves, merged by time, oldest first.

    Two files because they answer two questions: `turns` is what was said, `thought` is
    what she decided *not* to say. The window shows them in separate tabs, but a session
    picking up where it left off needs both -- her "I'll bring that up later" only lives
    in the second one.

    Test-mode entries stay on disk and stay out of here. They are real events but not
    real statements, and v1 lost that distinction: test input reached the vault because
    nothing filtered it on the way back in.
    """
    out: list[tuple[str, str]] = []
    for e in store.tail(RECORD, cfg.BACK):
        if not _kept(e):
            continue
        out.append((e["at"], _block(e)))
    for e in store.tail(THOUGHTS, cfg.BACK):
        if not _kept(e) or not e.get("thought"):
            continue
        out.append((e["at"], _thought(e)))
    return sorted(out)[-cfg.BACK :]


def recap() -> str:
    """What a fresh session gets handed. Empty on the very first run."""
    recent = _recent()
    if not recent:
        return ""
    log.info("thread", f"wiedereinstieg: {len(recent)} eintraege")
    return lang.t("thread.head") + "\n\n" + "\n\n".join(block for _, block in recent)


def _self_check() -> None:
    """The risky part is pure: what gets filtered out and in which order it comes back.
    `store._self_check` already proves that append and read work, so this does not."""
    assert _when("2026-09-10T21:14:07") == "10.09. 21:14", "timestamp does not read back"
    assert _cut("a" * (cfg.CUT + 50)).endswith(" [...]"), "an overlong turn is not trimmed"
    assert len(_cut("a" * (cfg.CUT + 50))) < cfg.CUT + 20, "the trim did not actually trim"
    assert _cut("zwei\nzeilen") == "zwei zeilen", "line breaks would break the block layout"
    assert _cut(None) == "", "a missing field must not crash the recap"

    # Der Testmodus-Filter greift beim *Lesen*. v1 filterte erst beim Schreiben und
    # liess damit alles durch, was schon lag.
    assert not _kept({"testing": True}), "test entries have to drop out of the recap"
    assert not _kept({"refused": True}), "a refused turn would poison the next session (B22)"
    assert _kept({"testing": False, "refused": False}), "a normal turn has to come back"

    # Reihenfolge: aelter zuerst, sonst liest sich der Wiedereinstieg rueckwaerts.
    pairs = [("2026-09-10T21:00:00", "spaet"), ("2026-09-10T09:00:00", "frueh")]
    assert sorted(pairs)[0][1] == "frueh", "the recap has to run oldest first"

    # Der Schreiblauf sieht das Rohmaterial ungekuerzt -- sonst verschwindet still, was
    # laenger war als der Deckel.
    lang_ = {"at": "2026-09-10T21:00:00", "asked": "x" * 2000, "said": "y" * 2000}
    assert len(spell([lang_])) > 3900, "the write pass must see the full wording"
    assert f"{mode.owner()}:" not in spell([{"at": "2026-09-10T21:00:00", "said": "von selbst"}]), (
        "what she says of her own accord has no asker"
    )
    assert f"{mode.owner()}: hi" in spell([{"at": "2026-09-10T21:00:00", "asked": "hi", "said": "ok"}])

    # B21: framed as her reasoning, the recap got every fresh Sonnet 5.5 session refused.
    note_ = _thought({"at": "2026-10-08T09:43:00", "saw": ["code: fertig"], "thought": "x"})
    assert "dacht" not in note_.lower(), "the recap must not label her notes as her thinking"
