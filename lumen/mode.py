"""How she is currently set to behave: muted, and under test.

Both are switches a person flips and then forgets, and both are wrong in *two*
directions -- stuck on without anyone noticing, and quietly off when it mattered. v1 had
each of them once: private mode hung on for ninety minutes and cost six DM turns before
anyone asked, and test remarks landed in the vault because the mode was not on.

Neither is a persistence problem, so persistence alone does not fix it:

  - on disk only          a restart drops you back into recording, silently
  - in the process only   the same, just faster

So all three, together:

  1. **on disk**, so a restart does not quietly change what she does (rule 5);
  2. **loud**, in the boot log, in her own status line and in what she reads, because
     the failure was never the flag, it was that nobody could see the flag;
  3. **with an expiry**, so forgetting to switch it back costs an hour and not a day.
     Running out is logged as loudly as switching on.
"""

import contextlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from lumen import lang, log, store
from lumen.config import system

STATE = "mode"
SETTINGS = "settings"

# What can be switched on in the window's settings, and how it stands on the very first
# start. Unlike the modes below these do not expire: they are decisions, not states one
# forgets. Off means off twice -- the tool is not offered at all (act.offered), and the
# guard refuses it anyway (guard.FEATURE_OF).
FEATURES = {
    "ear": False,      # Zuhören: Mikrofon und whisper -- hört sonst dauerhaft mit
    "watch": False,    # Beobachten: hinsehen, Bildschirmfoto, Anstoß, weg/wieder da
    "open": True,      # Programme, Adressen und Notizen öffnen
    "discord": False,  # DMs über einen eigenen Bot -- braucht Token und ID in den Einstellungen
}


def settings() -> dict[str, Any]:
    """Name, voice and features, with the defaults filled in. Unknown keys on disk are
    dropped rather than trusted -- a feature that no longer exists must not read as on."""
    kept = store.read(SETTINGS, {}) or {}
    chosen = {k: bool(v) for k, v in (kept.get("features") or {}).items() if k in FEATURES}
    assistant = kept.get("assistant", "")
    voice = _OLD_VOICES.get(kept.get("voice", ""), kept.get("voice", ""))
    return {"name": kept.get("name", ""), "voice": voice,
            # Empty means the default (lang.DEFAULT); lang.code() checks it is one it knows.
            "language": str(kept.get("language") or ""),
            "welcomed": bool(kept.get("welcomed")),
            # Which microphone, by Windows' name; empty means Windows' default device.
            "mic": str(kept.get("mic") or ""),
            # Which whisper model, by name; empty means config/ear.py's MODEL.
            "whisper_model": str(kept.get("whisper_model") or ""),
            "assistant": assistant if re.fullmatch(ASSISTANT_NAME, assistant) else "",
            "features": {**FEATURES, **chosen}}


# Voices were stored by their German label before there was a second language.
_OLD_VOICES = {"weiblich": "female", "männlich": "male"}

# Her own name, as the window lets one choose it: one word, letters and hyphens. One word
# because it is also the wake word -- the ear matches it against single heard words.
ASSISTANT_NAME = r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]{1,19}"


def feature(name: str) -> bool:
    """Is this feature on? A typo raises instead of reading as off."""
    return settings()["features"][name]


def owner() -> str:
    """What she calls the person at this machine: the name from the settings, else the
    Windows user name. Never a pronoun -- that would be a guess."""
    return settings()["name"] or os.environ.get("USERNAME") or "du"


def assistant() -> str:
    """Her own name: chosen in the settings, else the default."""
    return settings()["assistant"] or system.NAME


def configure(name: str | None = None, voice: str | None = None,
              features: dict[str, Any] | None = None, assistant: str | None = None,
              welcomed: bool = False, mic: str | None = None,
              language: str | None = None, whisper_model: str | None = None) -> None:
    kept = store.read(SETTINGS, {}) or {}
    if language is not None:
        kept["language"] = language
    if whisper_model is not None:
        kept["whisper_model"] = whisper_model
    if mic is not None:
        kept["mic"] = mic
    if welcomed:
        kept["welcomed"] = True  # the settings opened once on their own; never again
    if assistant is not None:
        if assistant and not re.fullmatch(ASSISTANT_NAME, assistant):
            raise ValueError(f"not a name: {assistant!r}")
        kept["assistant"] = assistant
    if name is not None:
        kept["name"] = " ".join(name.split())[:40]
    if voice is not None:
        kept["voice"] = voice
    if features:
        kept["features"] = {**(kept.get("features") or {}),
                            **{k: bool(v) for k, v in features.items() if k in FEATURES}}
    store.write(SETTINGS, kept)
    log.warn("mode", f"einstellungen: {settings()}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read() -> dict[str, Any]:
    return store.read(STATE, {}) or {}


def testing() -> bool:
    """True while a test is running -- nothing said in this state is a real instruction.

    Checks the expiry on the way, so a run that was never switched off ends on its own
    rather than at the next restart, which might be days.
    """
    state = _read()
    until = state.get("test_until")
    if not until:
        return False
    if _now() >= datetime.fromisoformat(until):
        store.write(STATE, {**state, "test_until": None})
        log.warn("mode", "test mode ran out -- everything from here counts again")
        return False
    return True


def test_on(minutes: int | None = None) -> None:
    minutes = minutes or system.TEST_MINUTES
    until = _now() + timedelta(minutes=minutes)
    store.write(STATE, {**_read(), "test_until": until.isoformat()})
    log.warn("mode", f"TEST MODE on for {minutes} min -- nothing said counts as an instruction")


def test_off() -> None:
    store.write(STATE, {**_read(), "test_until": None})
    log.warn("mode", "test mode off -- everything from here counts again")


def convo() -> bool:
    """True, solange sie ohne ihren Namen zuhört.

    Derselbe Bau wie `testing()` und aus demselben Grund: auf Platte, laut, mit Verfall.
    Der Schaden beim Vergessen ist hier sogar größer -- ohne Namen zählt *jedes* Wort am
    Mikrofon als an sie gerichtet, auch das, was er jemand anderem sagt.
    """
    state = _read()
    until = state.get("convo_until")
    if not until:
        return False
    if _now() >= datetime.fromisoformat(until):
        store.write(STATE, {**state, "convo_until": None})
        log.warn("mode", "dauerzuhoeren abgelaufen -- ab jetzt wieder nur auf ihren namen")
        return False
    return True


def convo_on(minutes: int | None = None) -> None:
    minutes = minutes or system.CONVO_MINUTES
    until = _now() + timedelta(minutes=minutes)
    store.write(STATE, {**_read(), "convo_until": until.isoformat()})
    log.warn("mode", f"DAUERZUHOEREN an fuer {minutes} min -- alles gesagte kommt bei ihr an")


def convo_off() -> None:
    store.write(STATE, {**_read(), "convo_until": None})
    log.warn("mode", "dauerzuhoeren aus -- ab jetzt wieder nur auf ihren namen")


def blind() -> bool:
    """True, solange sie nicht auf seinen Bildschirm sieht -- er chattet, oder es geht sie
    nichts an.

    Derselbe Bau wie `convo()`, mit Verfall: vergessen hieße, sie sieht still nicht mehr
    hin, und genau dafür läuft sie. Durchgesetzt wird es im Code, nicht in ihrem Prompt:
    der Guard sperrt `screenshot`, und `observe` liest keinen Fenstertitel mehr.
    """
    state = _read()
    until = state.get("blind_until")
    if not until:
        return False
    if _now() >= datetime.fromisoformat(until):
        store.write(STATE, {**state, "blind_until": None})
        log.warn("mode", "nicht-zugucken abgelaufen -- sie sieht wieder hin")
        return False
    return True


def blind_on(minutes: int | None = None) -> None:
    minutes = minutes or system.BLIND_MINUTES
    until = _now() + timedelta(minutes=minutes)
    store.write(STATE, {**_read(), "blind_until": until.isoformat()})
    log.warn("mode", f"NICHT ZUGUCKEN fuer {minutes} min -- kein bild, keine fenstertitel")


def blind_off() -> None:
    store.write(STATE, {**_read(), "blind_until": None})
    log.warn("mode", "nicht-zugucken aus -- sie sieht wieder hin")


def muted() -> bool:
    return bool(_read().get("muted"))


def mute(on: bool = True) -> None:
    store.write(STATE, {**_read(), "muted": on})
    log.warn("mode", f"muted: {on}")


def deaf() -> bool:
    """True, wenn SEIN Mikrofon aus ist -- sie hoert nicht mehr mit.

    Das Gegenstueck zu `muted`, und die beiden sind absichtlich getrennt: `muted` heisst
    "sie sagt nichts von selbst", das hier heisst "von ihm kommt nichts an". Wer im Call
    sitzt oder jemandem im Raum etwas erklaert, will das zweite und nicht das erste.
    Die Sprechtaste geht durch: wer sie haelt, meint sie,
    und ein Verhoerer kann keine Taste druecken.

    Ohne Verfall, anders als Testlauf und Dauerzuhoeren -- und das ist kein Versehen:
    diese beiden sind gefaehrlich, wenn man sie vergisst (es wird mitgeschrieben, ohne
    dass jemand es merkt). Ein vergessenes taubes Mikro faellt beim ersten Anruf beim Namen von
    selbst auf, und die Anzeige steht ohnehin im Fenster.
    """
    return bool(_read().get("deaf"))


def deafen(on: bool = True) -> None:
    store.write(STATE, {**_read(), "deaf": on})
    log.warn("mode", f"sein mikro ist {'aus -- sie hoert nichts mehr' if on else 'wieder an'}")


def line() -> str:
    """One line, in the words she reads. Empty when nothing is switched on, so a normal
    run says nothing and an unusual one is impossible to miss.

    Names only. What each switch means stands once in the system prompt (mechanics):
    this rides on every turn and stays in the session, and the full sentences used to
    be ~400 characters per turn, the same each time (measured 08.11.2026)."""
    def left(key: str) -> int:
        return int((datetime.fromisoformat(_read()[key]) - _now()).total_seconds() // 60)

    parts = []
    if testing():
        parts.append(lang.t("mode.test", m=left('test_until')))
    if muted():
        parts.append(lang.t("mode.muted"))
    if deaf():
        parts.append(lang.t("mode.deaf"))
    if convo():
        parts.append(lang.t("mode.convo", m=left('convo_until')))
    if blind():
        parts.append(lang.t("mode.blind", m=left('blind_until')))
    return " · ".join(parts)


@contextlib.contextmanager
def off():
    """Alle Schalter aus, danach wieder wie vorher.

    Für die Self-Checks beim Boot, und dort um *alle* gelegt (`__main__._checks`), nicht
    um einen. Die Schalter liegen auf Platte (Regel 5), also prüft jeder Check, der sie
    nebenbei liest, den Zustand des Rechners statt den des Codes -- und verhindert
    irgendwann den Start. Genau das am 15.09.2026: ein offenes Gesprächsfenster, und
    weder `mode` noch `ear` kamen hoch, beide mit einem Assert, der jahrelang gestimmt
    hatte (B9, dritte Auflage). Ein Schalter, der später dazukommt, kann so keinen Check
    mehr umwerfen -- und keiner muss ihn kennen.
    """
    before, chosen = _read(), store.read(SETTINGS, None)
    store.write(STATE, {})
    store.write(SETTINGS, {})  # the features too: a check must see the defaults, not this machine
    try:
        yield
    finally:
        store.write(STATE, before)
        store.write(SETTINGS, chosen if chosen is not None else {})


def start() -> None:
    """Say out loud what is switched on. This is the whole point of the module: v1's
    two incidents were both invisible states, not wrong ones."""
    if standing := line():
        log.warn("mode", standing)


def _self_check() -> None:
    """One runnable check: a switch that reads as off while it is on is the failure this
    module exists for, so the expiry has to actually expire."""
    with off():
        assert not testing() and not muted() and not convo(), "off has to mean off"
        assert line() == "", "a normal run must say nothing"

        test_on(60)
        assert testing(), "just switched on and it does not read as on"
        assert lang.t("mode.test", m=59) in line() or lang.t("mode.test", m=60) in line(), \
            "a running test has to be visible"

        # Expired by the clock, not by a restart -- that is the ninety-minute incident.
        store.write(STATE, {**_read(), "test_until": (_now() - timedelta(minutes=1)).isoformat()})
        assert not testing(), "an expired test must read as off"
        assert _read().get("test_until") is None, "expiry has to clear the state, not just report it"

        mute(True)
        assert muted() and lang.t("mode.muted") in line(), "muting has to be visible too"

        # Sein Mikro: dasselbe Muster, und vor allem nicht dasselbe wie `muted`. Wer die
        # zwei verwechselt, schaltet ihre Stimme ab, wenn er sein Mikro meinte.
        assert not deaf(), "was nicht gesetzt ist, ist aus"
        deafen(True)
        assert deaf() and lang.t("mode.deaf") in line(), "ein taubes Mikro muss sichtbar sein"
        assert muted(), "sein Mikro auszuschalten macht sie nicht stumm"
        deafen(False)
        assert not deaf() and muted(), "und andersherum genauso"

        # Dauerzuhoeren: derselbe Verfall, derselbe Grund. Bleibt es haengen, haelt sie
        # jedes Wort am Mikrofon fuer eine Frage an sich.
        convo_off()
        assert not convo(), "aus heisst aus"
        convo_on(30)
        assert convo() and line(), "dauerzuhoeren muss sichtbar sein"
        store.write(STATE, {**_read(), "convo_until": (_now() - timedelta(minutes=1)).isoformat()})
        assert not convo(), "ein abgelaufenes dauerzuhoeren muss als aus gelten"
        assert _read().get("convo_until") is None, "der verfall muss den zustand raeumen"

        # Nicht zugucken: derselbe Verfall. Bleibt es haengen, sieht sie still nie mehr hin.
        assert not blind(), "was nicht gesetzt ist, ist aus"
        blind_on(30)
        assert blind() and line(), "nicht-zugucken muss sie lesen"
        store.write(STATE, {**_read(), "blind_until": (_now() - timedelta(minutes=1)).isoformat()})
        assert not blind(), "ein abgelaufenes nicht-zugucken muss als aus gelten"
        assert _read().get("blind_until") is None, "der verfall muss den zustand raeumen"

        # Features: the defaults hold until someone chooses, and a choice holds.
        assert settings()["features"] == FEATURES, "a fresh install starts on the defaults"
        assert not feature("watch") and not feature("ear"), "watching and listening start off"
        configure(features={"watch": True, "nonsense": True})
        assert feature("watch") and "nonsense" not in settings()["features"], "unknown features are dropped"
        configure(name="  Sam   Doe ")
        assert owner() == "Sam Doe" and feature("watch"), "a name change keeps the features"
        try:
            feature("wach")
        except KeyError:
            pass
        else:
            raise AssertionError("a typo in a feature name must raise, not read as off")

        # Her name: the default until chosen, one word only, and junk on disk is ignored.
        assert assistant() == system.NAME, "no choice, the default"
        configure(assistant="Juno")
        assert assistant() == "Juno" and owner() == "Sam Doe", "her name is not his"
        for bad in ("Hey Juno", "J", "R2D2", "x" * 30):
            try:
                configure(assistant=bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"not a usable wake word, let through: {bad!r}")
        store.write(SETTINGS, {**store.read(SETTINGS, {}), "assistant": "zwei worte"})
        assert assistant() == system.NAME, "a broken name on disk falls back to the default"
