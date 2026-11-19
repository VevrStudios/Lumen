"""Ihre Stimme. Der eine Weg aus dem Prozess in die Lautsprecher.

Azure Neural TTS über REST -- SSML rein, WAV raus, abgespielt mit `winsound`. Kein
neues Dependency und kein Cache: es gibt kein Credit-Budget mehr, das ein Cache schonen
müsste (Regel 1), und ein Satz, der schon einmal gesagt wurde, ist ohnehin der falsche.

Sie spricht nie von selbst hier: gerufen wird sie aus `actions/speak.py` und aus dem Zug,
der auf Gesprochenes antwortet. Was durch die Sperre darf, entscheidet weiter der Guard.

    python -m lumen.voice "text"   -- zum Anhören, ohne Daemon
"""

import re
import sys
import time
import urllib.error
import urllib.request
import winsound
from xml.sax.saxutils import escape

from lumen import lang, log, mode
from lumen.config import system
from lumen.config import voice as cfg

# Zwei Dateien im Wechsel. Nicht aus Ordnungsliebe: `winsound` kann nachweislich nicht
# asynchron aus dem Speicher spielen (`RuntimeError: Cannot play asynchronously from
# memory`, gemessen 15.09.2026) -- weil Python den Puffer freigeben dürfte, während
# Windows noch daraus liest. Also über eine Datei, und über zwei im Wechsel, weil die
# vorige noch offen sein kann, wenn der nächste Satz kommt.
#
# Das ist Zwischenspeicher, kein Zustand: er darf einen Neustart ausdrücklich *nicht*
# überleben, und deshalb geht er nicht durch `store.py`.
_slot = 0
# Until when the last sentence plays. winsound cannot be asked; the window needs to know
# whether his stop button has anything to stop.
_until = 0.0


def start() -> None:
    """Nichts beim Boot. Ohne Schlüssel ist sie stumm und trotzdem nützlich."""


def clean(text: str) -> str:
    """Was gesprochen wird, aus dem, was dasteht. Rein, testbar ohne Netz."""
    words = {"and": lang.t("voice.and"), "to": lang.t("voice.to")}
    for pattern, replacement in cfg.CLEAN:
        text = re.sub(pattern, replacement.format(**words) if "{" in replacement else replacement, text)
    return text.strip()


def ready() -> bool:
    """Ist ein Azure-Konto eingetragen? Ohne bleibt sie stumm, und das ist kein Fehler."""
    return bool(system.secret("AZURE_SPEECH_KEY") and system.secret("AZURE_SPEECH_REGION"))


def _voice() -> tuple[str, str]:
    """(Azure-Stimme, Tonhöhe) aus den Einstellungen. Eine unbekannte Wahl ist die Vorgabe."""
    voices = lang.pack().VOICES
    return voices.get(mode.settings()["voice"]) or voices[cfg.DEFAULT]


def _ssml(text: str) -> str:
    """Was an Azure geht. Rein, damit der Selbst-Check ihn ohne Netz lesen kann -- ein
    kaputtes Element hier hört man erst am Schweigen, und dann sucht man im Netz."""
    name, pitch = _voice()
    return (f"<speak version='1.0' xml:lang='{lang.pack().SSML}'>"
            f"<voice name='{name}'>"
            f"<prosody rate='{cfg.RATE}' pitch='{pitch}'>{escape(text)}</prosody>"
            f"</voice></speak>")


def _fetch(text: str, key: str, region: str) -> bytes:
    ssml = _ssml(text)
    request = urllib.request.Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": cfg.FORMAT,
            "User-Agent": "lumen",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=cfg.TIMEOUT_S) as answer:
        return answer.read()


def audible() -> bool:
    """Spricht sie laut? Nur mit Azure-Konto -- und nur mit Mikrofon: wer es in den
    Einstellungen auf "Aus" stellt, will den Assistenten ganz still, alles steht im Fenster."""
    return ready() and mode.feature("ear")


def say(text: str, test: bool = False) -> bool:
    """Sprich das aus. Wahr, wenn es auch wirklich rauskam. `test`: die Stimmprobe aus den
    Einstellungen, die auch ohne Mikrofon zu hören sein soll.

    Wirft nie. Azure kann weg sein, der Schlüssel abgelaufen, das Netz tot -- keiner
    dieser Fälle darf einen Zug abbrechen, in dem sie sonst alles richtig gemacht hat.
    Sie steht dann im Fenster und kommt nicht aus dem Lautsprecher, und das Log sagt warum.
    """
    spoken = clean(text)
    if not spoken:
        return False

    if not (ready() if test else audible()):
        return False  # kein Azure-Konto oder kein Mikrofon: stumm ist dann der Normalfall
    key, region = system.secret("AZURE_SPEECH_KEY"), system.secret("AZURE_SPEECH_REGION")

    try:
        # Blockiert die eine Uhr für die Dauer der Anfrage: 0,6 s, gemessen 15.09.2026.
        # Kein Thread: ein zweiter Ausführungsstrang wäre teurer als die Wartezeit, und
        # währenddessen wartet ohnehin niemand auf einen Tick, sondern auf ihren Satz.
        audio = _fetch(spoken, key, region)
    except urllib.error.HTTPError as why:
        meaning = {401: "Schlüssel falsch", 403: "Region oder Kontingent",
                   400: "Stimme unbekannt oder SSML abgelehnt",
                   429: "Kontingent erschöpft"}.get(why.code, "")
        log.error("voice", f"azure HTTP {why.code} {meaning}")
        return False
    except OSError as why:
        log.error("voice", f"azure nicht erreichbar: {why}")
        return False

    _play(audio)
    log.debug("voice", f"{len(spoken)} zeichen, {len(audio):,} bytes")
    return True


def _play(audio: bytes) -> None:
    """Sofort hörbar, ohne die Uhr aufzuhalten. Ein neuer Satz stoppt den alten --
    richtig so: zwei gleichzeitig sind keiner."""
    global _slot, _until
    _slot ^= 1
    path = system.DATA / f"_stimme{_slot}.wav"
    path.write_bytes(audio)
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    _until = time.time() + _seconds(audio)


def _seconds(audio: bytes) -> float:
    """How long a RIFF plays: bytes after the 44-byte header over the byte rate at offset 28."""
    return max(len(audio) - 44, 0) / (int.from_bytes(audio[28:32], "little") or 1)


def speaking() -> bool:
    return time.time() < _until


def hush() -> bool:
    """Stop mid-sentence -- his stop button. True if she was talking."""
    global _until
    was = speaking()
    winsound.PlaySound(None, 0)  # None stops whatever winsound is playing
    _until = 0.0
    return was


def _self_check() -> None:
    """Die Ersetzungstabelle, ohne Netz. Was hier falsch steht, hört man erst im Betrieb --
    und dann ist der Satz schon gesprochen."""
    assert clean("ark_map_v3") == "ark map v3", "Unterstriche werden buchstabiert"
    assert clean("90/10") == "90" + lang.t("voice.to") + "10", "Schrägstrich zwischen Ziffern"
    assert clean("notizen/plan/umzug.md") == "notizen/plan/umzug.md", (
        "der Schrägstrich in Pfaden bleibt -- sonst 'notizen zu plan zu umzug'"
    )
    assert clean("**Petrified** Woods") == "Petrified Woods", "Sternchen werden mitgelesen"
    assert clean("`git log`") == "git log", "Backticks auch"
    assert clean("Word ↔ Excel") == "Word" + lang.t("voice.and") + "Excel", "sonst 'Pfeil nach links und rechts'"
    assert clean("a → b") == "a" + lang.t("voice.to") + "b"

    # Die Websuche hängt ihre Quellenliste an. Im Fenster nützlich, vorgelesen sinnlos.
    assert clean("Das geht.\n\nSources:\n- [Docs](https://x.de/a_b)") == "Das geht.", (
        "die Quellenliste muss ganz weg, nicht nur ihre Adressen"
    )
    assert clean("siehe [die Doku](https://x.de/y)") == "siehe die Doku", (
        "vom Link bleibt der Text, nicht die Adresse"
    )
    assert "http" not in clean("nachzulesen unter https://azure.com/tts"), (
        "eine nackte Adresse wird buchstabengetreu vorgelesen"
    )

    assert say("") is False, "aus nichts wird kein Satz"
    assert say("   `` ") is False, "und aus Zeichen ohne Wörter auch nicht"
    # Die SSML, ohne Netz. Azure lehnt ein kaputtes Element mit HTTP 400 ab -- sie bliebe
    # stumm, und im Log stünde nur "SSML abgelehnt".
    ssml = _ssml("Petrified & Woods")
    assert f"rate='{cfg.RATE}'" in ssml, "das Tempo muss in der SSML ankommen"
    assert f"pitch='{_voice()[1]}'" in ssml, "die Tonhöhe auch"
    assert "&amp;" in ssml and "&&" not in ssml, "Sonderzeichen muessen escaped sein"
    assert ssml.count("<prosody") == ssml.count("</prosody>") == 1, "Element nicht geschlossen"

    # 24 kHz, 16 bit, mono: 48.000 Byte je Sekunde -- daran haengt, ob der Stopp-Knopf zu sehen ist.
    riff = b"RIFF" + bytes(24) + (48_000).to_bytes(4, "little") + bytes(12) + bytes(96_000)
    assert abs(_seconds(riff) - 2.0) < 0.01, "the length of a sentence reads wrong"
    assert not speaking(), "silent at boot"

    assert cfg.DEFAULT in lang.pack().VOICES, "die Vorgabe muss eine der Stimmen sein"
    assert cfg.FORMAT.startswith("riff-"), "winsound spielt nur RIFF -- MP3 bliebe stumm"


if __name__ == "__main__":
    log.start()
    text = " ".join(sys.argv[1:]) or f"Ich bin {mode.assistant()}. So klinge ich, wenn ich etwas sage."
    print(f"{_voice()[0]}: {clean(text)}")
    if say(text):
        input("laeuft -- Enter beendet das Programm (und den Satz)")
