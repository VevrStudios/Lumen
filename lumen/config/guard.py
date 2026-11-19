"""What she may do without being asked.

`actions/` says what she *can* do. This says what she may do it *to*. Two different
questions, so two different files: a newly permitted app is a line here, not new code.

Pure policy -- no disk, no clock. Whatever state a decision needs is handed in, so the
whole decision table can be checked without a running daemon.
"""

import os
import re
from typing import Any

from lumen.config import system
from lumen.lang import t as _t

# Read-only built-ins from the Agent SDK. Reading changes nothing, which is the whole
# content of "Lesen und Beobachten frei, jede Änderung fragt".
FREE_TOOLS = frozenset({"Read", "Glob", "Grep"})

# Reading the web is reading, so it is free -- in conversation. Not in the write pass:
# there the evidence is what was said, and a filing run that searches on the side carries
# unchecked facts into memory with the conversation as their apparent source.
# ToolSearch only loads a tool's schema; the call it enables still comes through here.
WEB_TOOLS = frozenset({"WebSearch", "WebFetch", "ToolSearch"})

# The built-ins that change a file. Only ever wired in during the write pass (act.wire),
# and even then only inside the memory folder -- two barriers, because the first one is a
# wiring decision and wiring decisions get changed by accident.
MEMORY_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

# Nothing reads these, whichever tool asks and whatever the reason. A secret that
# reaches the model is a secret in a transcript, and transcripts are kept.
# v1 found that a prompt alone leaked the .env three times out of three.
NEVER = (".env", "credentials", "id_rsa", ".ssh", "cookies", ".pem")

# Which files `open` may open. Programs and addresses all; files only from her memory.
# Starting a program opens a window; opening a file shows content, and what else lies on
# the disk is none of her business.
OPEN_DIRS = (system.MEMORY,)

# Which switch in the settings each action hangs on (mode.FEATURES). Off, the action is
# not offered at all (act.offered) -- and refused here, in case it is offered anyway.
FEATURE_OF = {
    "hinsehen": "watch", "screenshot": "watch",
    "open": "open",
    "schreiben": "discord",
}

# How long she stays quiet after speaking unprompted.
# placeholder: v1 allowed one unprompted message per hour and nobody measured whether
# that was right. It is a number about attention, so it can only be settled by someone
# saying it interrupts too often, or that it stayed silent when it should not have.
SPEAK_GAP_S = 3600

# Who starts a turn when one of the owner's alarms is due (`brain.ask(von=...)`). Such a
# turn carries the owner's word from the moment the alarm was set: in it she may do what
# she otherwise only may on the owner's word. What never goes (NEVER, terminals, muted,
# call, "Nicht zugucken", a switched-off feature) does not go then either.
ALARM = "wecker"
OWNER = "owner"

# The turns in which the owner's word counts: the owner's own, and the owner's alarms.
HIS = (OWNER, ALARM)


def _paths(args: dict[str, Any]) -> list[str]:
    """Every string in the arguments that could be a path. Deliberately crude: it is
    cheaper to check a few harmless strings than to miss the one that mattered."""
    return [v.lower() for v in args.values() if isinstance(v, str)]


def _inside(path: str, root: str) -> bool:
    """Is `path` inside `root`? Pure string work on normalised paths -- `..` collapses
    first, so `memory/../.env` does not read as being in memory."""
    here = os.path.normcase(os.path.normpath(os.path.abspath(path)))
    top = os.path.normcase(os.path.normpath(os.path.abspath(root)))
    return here == top or here.startswith(top + os.sep)


def _filing(ziel: str, folder: str, tool: str, args: dict[str, Any], lang: str | None) -> tuple[bool, str]:
    """Where a write may land in memory: flat, lower-case names, no frontmatter.

    The shape as code, not as a request -- which note a fact belongs in stays her judgement.
    """
    rel = os.path.relpath(os.path.abspath(ziel), os.path.abspath(folder)).replace(os.sep, "/")
    parts = rel.split("/")
    if parts[0] == system.BACKUP:
        return False, _t("guard.backup", lang, rel=rel)
    if len(parts) != 1:
        return False, _t("guard.flat", lang)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*\.md", parts[0]):
        return False, _t("guard.filename", lang, name=parts[0])
    if tool == "Write" and str(args.get("content", "")).lstrip().startswith("---"):
        return False, _t("guard.frontmatter", lang)
    return True, _t("guard.filing_ok", lang)


def may(tool: str, args: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str]:
    """(allowed, why). The why is logged and shown to her.

    In her language (`state["lang"]`, from lang/): she reads these, and a refusal in another
    language is one she has to parse before she can act on it.

    Deny is the default. An unknown tool is one nobody has thought about yet, and the
    safe reading of "nobody thought about it" is no.
    """
    lang = state.get("lang")
    for value in _paths(args):
        for secret in NEVER:
            if secret in value:
                return False, _t("guard.secret", lang, secret=secret)

    name = tool.rsplit("__", 1)[-1] if tool.startswith("mcp__") else ""
    if (feature := FEATURE_OF.get(name)) and not (state.get("features") or {}).get(feature):
        return False, _t("guard.feature_off", lang, feature=_t(f"feature.{feature}", lang))

    if tool in FREE_TOOLS:
        return True, _t("guard.read", lang)

    if tool in WEB_TOOLS:
        if state.get("writing"):
            return False, _t("guard.web_filing", lang)
        if tool == "ToolSearch":
            return True, _t("guard.toolsearch", lang)
        return True, _t("guard.web", lang)

    if tool in MEMORY_TOOLS:
        # `writing` is the only place writing opens up, and it carries the allowed path.
        # No switch, no mode flag: either the write pass runs and handed over the folder,
        # or there is no target.
        folder = state.get("writing")
        if not folder:
            return False, _t("guard.write_only_filing", lang)
        ziel = args.get("file_path") or args.get("path") or ""
        if not ziel:
            return False, _t("guard.no_path", lang)
        if not _inside(ziel, folder):
            return False, _t("guard.outside", lang, path=ziel)
        return _filing(ziel, folder, tool, args, lang)

    if name == "speak":
        if state.get("muted"):
            return False, _t("guard.muted", lang)
        # The name, not a flag: her own process holds the microphone while she listens,
        # and a boolean "mic in use" would read as "in a call" forever (B3).
        if call := state.get("call"):
            return False, _t("guard.call", lang, call=call)
        # An alarm that may not ring because she said something ten minutes ago would be
        # no alarm. The gap protects against the unasked; this was asked for.
        if state.get("by") == ALARM:
            return True, _t("guard.alarm_speak", lang)
        since = state.get("since_spoken_s")
        if since is not None and since < SPEAK_GAP_S:
            return False, _t("guard.gap", lang, m=int(since // 60), gap=SPEAK_GAP_S // 60)
        return True, _t("guard.speak_ok", lang)

    if name == "schreiben":
        # None of speak's gates: muted means "cannot talk", not "cannot reach". A DM is
        # read whenever and interrupts no call and no work.
        return True, _t("guard.dm_ok", lang)

    if name == "open":
        ziel = args.get("ziel", "")
        if not ziel:
            return False, _t("guard.open_no_target", lang)
        if ziel.lower().startswith(("http://", "https://")):
            return True, _t("guard.open_url", lang)
        # Programs all: `os.startfile` passes no arguments, so starting is not running a
        # command. A bare name without a path separator is a program too.
        if ziel.lower().endswith((".exe", ".lnk")) or not ("/" in ziel or "\\" in ziel):
            return True, _t("guard.open_program", lang)
        if any(_inside(ziel, str(root)) for root in OPEN_DIRS):
            return True, _t("guard.open_memory", lang)
        return False, _t("guard.open_file_no", lang)

    if name == "screenshot":
        # Not even on request: the button is the newer word, and a mishearing must not
        # lift it. Whoever wants a picture switches it off.
        if state.get("blind"):
            return False, _t("guard.blind", lang)
        return True, _t("guard.look", lang)

    if name == "hinsehen":
        # With "Nicht zugucken" too: then the title is blanked already (observe.look) --
        # which program is in front she may always see while watching is on.
        return True, _t("guard.peek", lang)

    if name == "einsortieren":
        return True, _t("guard.file_now", lang)

    if name in ("wecker_stellen", "wecker_aendern", "wecker_loeschen"):
        # An alarm carries the owner's word into the future (ALARM), so only the owner
        # sets, changes or deletes one. On her own or from inside an alarm, each would be
        # a way to the owner's rights.
        if state.get("by") != OWNER:
            return False, _t("guard.alarm_owner", lang)
        return True, _t("guard.alarm_ok", lang)

    return False, _t("guard.unknown", lang, tool=tool)


def _self_check() -> None:
    """One runnable check: this is the whole of rule 4 in one function, and a wrong
    answer here is not a bug that shows up in a log, it is something that happened."""
    alles = {"features": {f: True for f in set(FEATURE_OF.values())}}
    quiet = {**alles, "since_spoken_s": 10_000}

    assert may("Read", {"file_path": "memory/projekte.md"}, {})[0]
    assert not may("Read", {"file_path": "C:/lumen/.env"}, {})[0], "the .env must never be readable"
    assert not may("Glob", {"pattern": "**/.ssh/*"}, {})[0], "a free tool is not a free pass"

    assert not may("Bash", {"command": "dir"}, {})[0], "no shell, anywhere"
    assert not may("Write", {"file_path": "x.txt"}, {})[0], "writing is not free"
    assert not may("Agent", {"prompt": "x"}, {})[0], "no subagents in the public version"

    assert may("WebSearch", {"query": "whisper.cpp"}, {})[0], "im Netz lesen ist lesen"
    assert may("WebFetch", {"url": "https://example.com"}, {})[0]
    assert may("ToolSearch", {"query": "select:WebSearch"}, {})[0]
    m = str(system.MEMORY)
    schreiben = {"writing": m}
    assert not may("WebSearch", {"query": "x"}, schreiben)[0], "der Schreiblauf sucht nicht im Netz"
    assert not may("WebFetch", {"url": "https://x.org/.env"}, {})[0], "die Geheimnisliste gilt auch für Adressen"

    # The write pass: only with a target, only in memory, flat, and `..` saves nobody.
    assert may("Edit", {"file_path": f"{m}/projekte.md"}, schreiben)[0], "eine bestehende Notiz"
    assert may("Write", {"file_path": f"{m}/neue-notiz.md", "content": "# Neu\n\nx"}, schreiben)[0]
    for bad, why in [(f"{m}/_backup/x.md", "die Sicherung schreibt der Code"),
                     (f"{m}/sub/x.md", "keine Unterordner"), (f"{m}/Meine Notiz.md", "Dateinamen klein"),
                     (f"{m}/x.txt", "nur .md")]:
        assert not may("Write", {"file_path": bad, "content": "# X"}, schreiben)[0], f"durchgelassen: {why}"
    assert not may("Write", {"file_path": f"{m}/x.md", "content": "---\ntitle: x\n---\n"}, schreiben)[0], \
        "kein Frontmatter"
    assert not may("Edit", {"file_path": str(system.ROOT / "lumen" / "persona.md")}, schreiben)[0], \
        "außerhalb des Gedächtnisses ist außerhalb"
    assert not may("Write", {"file_path": f"{m}/../lumen/brain.py"}, schreiben)[0], "der Umweg über .."
    assert not may("Edit", {"file_path": f"{m}/x.md"}, {})[0], "ohne Schreiblauf schreibt sie gar nicht"
    assert not may("Anything", {}, {})[0], "an unknown tool defaults to no"

    speak = "mcp__lumen__speak"
    assert may(speak, {"text": "hi"}, quiet)[0], "with nothing in the way she may speak"
    assert not may(speak, {"text": "hi"}, {"since_spoken_s": 5})[0], "the gap is not optional"
    assert not may(speak, {"text": "hi"}, {**quiet, "muted": True})[0], "muted means muted"
    assert not may(speak, {"text": "hi"}, {**quiet, "call": "discord.exe"})[0], "not during a call"
    assert may(speak, {"text": "hi"}, {})[0], "never having spoken is not a reason to stay quiet"

    # Features: off means refused, whatever else holds.
    for tool, args, feature in [("mcp__lumen__hinsehen", {}, "watch"), ("mcp__lumen__screenshot", {}, "watch"),
                                ("mcp__lumen__open", {"ziel": "notepad"}, "open")]:
        ok, why = may(tool, args, {})
        assert not ok and why == _t("guard.feature_off", None, feature=_t(f"feature.{feature}")), \
            f"{tool} must be refused with {feature} off"
    assert may("mcp__lumen__open", {"ziel": "notepad"}, alles)[0]
    assert not may("mcp__lumen__schreiben", {"text": "x"}, {})[0], "Discord startet aus"
    assert may("mcp__lumen__schreiben", {"text": "x"},
               {**alles, "muted": True, "call": "discord.exe", "since_spoken_s": 5})[0], \
        "stumm heißt nicht reden, nicht nicht schreiben"

    auf = "mcp__lumen__open"
    assert may(auf, {"ziel": "https://example.com"}, alles)[0], "eine Adresse geht"
    assert may(auf, {"ziel": "C:/Spiele/game.exe"}, alles)[0], "ein Programm mit Pfad auch"
    assert may(auf, {"ziel": f"{m}/projekte.md"}, alles)[0], "das Gedächtnis"
    assert not may(auf, {"ziel": "C:/Users/x/Desktop/privat.pdf"}, alles)[0], "eine Datei außerhalb nicht"
    assert not may(auf, {"ziel": str(system.ROOT / ".env")}, alles)[0], "die Geheimnisliste gilt auch hier"

    assert may("mcp__lumen__screenshot", {}, alles)[0], "looking is observing"
    assert not may("mcp__lumen__screenshot", {}, {**alles, "blind": True})[0], "nicht zugucken heißt kein Bild"
    assert may("mcp__lumen__hinsehen", {}, {**alles, "blind": True})[0], "ohne Titel, aber das Programm"
    assert may("mcp__lumen__einsortieren", {}, {"by": "system"})[0]

    for name in ("wecker_stellen", "wecker_aendern", "wecker_loeschen"):
        assert may(f"mcp__lumen__{name}", {}, {"by": OWNER})[0], f"{name} auf das Wort des Besitzers"
        for by in ("system", ALARM, None):
            assert not may(f"mcp__lumen__{name}", {}, {"by": by})[0], f"{name} von {by} aus nie"
    w = {**alles, "by": ALARM}
    assert may(speak, {"text": "x"}, {**w, "since_spoken_s": 5})[0], "ein Wecker klingelt"
    assert not may(speak, {"text": "x"}, {**w, "muted": True})[0], "stumm bleibt stumm"
    assert not may("mcp__lumen__screenshot", {}, {**w, "blind": True})[0], "nicht zugucken bleibt"
    assert not may("mcp__lumen__screenshot", {}, {"by": ALARM})[0], "ein ausgeschaltetes Feature bleibt aus"

    ok, why = may("Bash", {}, {})
    assert not ok and "Bash" in why, "a refusal has to name what was refused"
