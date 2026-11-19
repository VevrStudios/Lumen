"""Das Ohr. Ein Eingang, keine zweite Uhr.

Das Mikrofon wird hier selbst gelesen (winmm über ctypes), am Pegel in Äußerungen
geschnitten, und jede fertige Äußerung geht genau **einmal** durch `whisper-cli` -- lokal,
auf der CPU. Was zurückkommt, wird auf ihren Namen geprüft und in `inbox` gelegt. Die
Uhr holt es ab. Nichts hier ruft das Modell auf.

Mitgehört wird durchgehend, ans Modell geht nur, was ihren Namen enthält -- dann der ganze
Satz. Alles andere steht im Log und verlässt den Rechner nicht.
"""

import array
import asyncio
import ctypes
import math
import re
import subprocess
import time
import unicodedata
import wave
from ctypes import wintypes
from datetime import datetime
from difflib import SequenceMatcher

from lumen import inbox, lang, log, mode
from lumen.config import ear as cfg
from lumen.config import system

_user32 = ctypes.windll.user32
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
# Beides noetig: ohne argtypes schickt ctypes einen Zeiger statt des Zeichens (Antwort
# immer -1), ohne restype kaeme -1 als 65535 zurueck.
_user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
_user32.VkKeyScanW.restype = ctypes.c_short
_MODIFIERS = {"strg": 0x11, "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
_winmm = ctypes.windll.winmm

# 16 kHz mono 16 bit: was whisper will. Windows rechnet vom Geraeteformat selbst um.
RATE = 16000
_BYTES_PER_S = RATE * 2
_DONE = 0x1  # WHDR_DONE: Windows hat den Puffer voll zurueckgegeben
_WAVE_MAPPER = -1  # WAVE_MAPPER (0xFFFFFFFF als UINT): das Standard-Aufnahmegeraet von Windows


class _Caps(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT), ("szPname", wintypes.WCHAR * 32),
                ("dwFormats", wintypes.DWORD), ("wChannels", wintypes.WORD),
                ("wReserved1", wintypes.WORD)]


class _Format(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD)]


class _Header(ctypes.Structure):
    pass


_Header._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                    ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
                    ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD),
                    ("lpNext", ctypes.POINTER(_Header)), ("reserved", ctypes.c_size_t)]
_HEADER = ctypes.sizeof(_Header)

_mic = ctypes.c_void_p()           # das offene Geraet; None-Wert heisst: sie ist taub
_buffers: list = []                # Windows schreibt hinein -- muessen leben, solange es offen ist
_headers: list[_Header] = []
_loop: asyncio.Task | None = None

# Transkripte laufen der Reihe nach. Zwei Saetze kurz hintereinander duerfen sich nicht
# ueberholen -- am nackten Namen haengt, welcher zuerst kam.
_turn = asyncio.Lock()
_busy = 0                          # wieviele gerade bei whisper liegen, fuer die Anzeige

# Die Sprechtaste. Alles im Prozess und nirgends sonst: ob ein Finger gerade auf einer
# Taste liegt, muss keinen Neustart überleben.
_ptt_keys: tuple[int, ...] = ()
_ptt_down = False
_ptt_since = 0.0
_ptt_locked = False  # nach dem Zeitdeckel: erst loslassen, dann wieder drücken
_ptt_held = False    # der Knopf im Fenster -- dieselbe Taste, nur mit der Maus gehalten

# GetAsyncKeyState: das **hohe** Bit heißt "jetzt unten". Das niedrigste heißt "seit dem
# letzten Aufruf gedrückt" -- ein Flankenzähler, der beim Lesen zurückgesetzt wird und
# bei zwei Lesern gegeneinander läuft (v1s Befund, `ptt.py`).
_DOWN_BIT = 0x8000

# Was zuletzt ankam, fuers Fenster: er soll sehen, ob es angekommen ist, statt zu raten,
# ob die Stille Nachdenken ist oder Taubheit (gemessen am Original).
_last: dict = {}

# Nur der Name gefallen: bis wann die nächste Äußerung als seine Frage gilt. Im Prozess
# und nirgends sonst -- acht Sekunden müssen keinen Neustart überleben (Regel 5 meint
# das Gegenteil davon: was ihn überleben *muss*).
_window_until = 0.0

_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def start() -> None:
    """Nichts beim Boot. Ein Unterprozess braucht eine laufende Schleife, also macht
    `__main__` das Mikrofon mit `listen()` auf -- nach dem Fenster, aus demselben Grund."""


# --- die Sprache ------------------------------------------------------------------

def fold(text: str) -> str:
    """Kleingeschrieben, Umlaute ausgeschrieben, Satzzeichen weg. Nur zum Vergleichen --
    ans Modell geht immer der Originaltext, mit Umlauten und Fragezeichen."""
    # Erst klein, dann falten: die Tabelle kennt nur "ä", und "Ähm" blieb sonst "ähm" --
    # an keinem Füllwort vorbei (gefunden am 28.09.2026).
    text = unicodedata.normalize("NFC", text or "").lower().translate(_UMLAUT)
    return " ".join(_PUNCT.sub(" ", text).split())


def _noise(text: str) -> bool:
    """Ein Schnipsel, der garantiert keine Frage ist. Lokal und gratis.

    Klammern und Sternchen sind kein Gesprochenes, sondern whispers Beschreibung von
    Geräuschen -- am 15.09.2026 kamen auf dem leeren Mikro "[Aufregende Musik]",
    "[Aufregung]" und "* Musik *". Als Muster und nicht als Liste: die Beschreibung
    selbst ist beliebig, die Klammern drumherum sind es nicht.
    """
    if text.strip()[:1] in ("[", "*", "("):
        return True
    folded = fold(text)
    if not folded:
        return True
    # Enthalten, nicht gleich: am 15.09.2026 kam "Untertitelung des ZDF, 2020" durch,
    # weil die Jahreszahl den exakten Vergleich verfehlte. v1 verglich exakt und hatte
    # dieselbe Phrase deshalb zweimal in der Liste, einmal mit und einmal ohne Jahr.
    if any(phrase in folded for phrase in lang.pack().HALLUCINATIONS):
        return True
    return len(folded.split()) <= cfg.FILLER_WORDS and folded in lang.pack().FILLER


def _aliases() -> tuple[str, ...]:
    """Ihr Name aus den Einstellungen -- und die gesammelten Verhörer nur für den
    voreingestellten, an dem sie gesammelt wurden."""
    name = fold(mode.assistant())
    return (name, *cfg.ALIASES) if name == fold(system.NAME) else (name,)


def _alias(heard: str) -> float:
    """Wie sehr klingt das nach ihrem Namen? 1,0 = genau so, 0 = gar nicht."""
    aliases = _aliases()
    if heard in aliases:
        return 1.0
    best = 0.0
    for alias in aliases:
        if abs(len(alias) - len(heard)) > 3:
            continue  # billige Vorfilterung: so verschieden lang kann es nicht reichen
        best = max(best, SequenceMatcher(None, heard, alias).ratio())
    return best if best >= cfg.FUZZ else 0.0


def named(text: str) -> tuple[bool, bool]:
    """Fällt ihr Name -- und ist er alles, was gesagt wurde?

    **Überall im Satz, nicht nur am Anfang.** whisper stellt gern etwas voran -- ein
    "Ähm", ein abgebrochenes Wort --, und mit einer Anfangspflicht ging die Frage dann
    verloren; das war v1s häufigster Fehlschlag (Regel gestrichen am 23.08.2026). Der
    Preis ist ehrlich: "ich hab Lumen gefragt" gilt damit als Ansprache. Das kostet einen
    Zug, der zu dem Schluss kommt, dass er nicht gemeint war -- und ein Zug ohne `speak`
    verlässt das Programm nicht.

    Nackt heißt: außer dem Namen nur Füllwörter. Bis zum 28.09.2026 zählte hier, was
    *hinter* dem Namen stand -- "Kannst du mal gucken, Lumen?" hatte dahinter nichts, galt
    als nackter Name, und die Frage fiel weg.
    """
    words = fold(text).split()
    for i in range(len(words)):
        hits = []
        for n in range(1, min(cfg.ALIAS_MAX_TOKENS, len(words) - i) + 1):
            if score := _alias(" ".join(words[i:i + n])):
                hits.append((score, n))
        if hits:
            # Der bessere Treffer gewinnt, die Länge entscheidet nur den Gleichstand --
            # würde die Länge gewinnen, verschwände ein Wort der Frage im Namen.
            n = max(hits)[1]
            rest = " ".join(words[:i] + words[i + n:])
            return True, not rest or rest in lang.pack().FILLER
    return False, False


def addressed(text: str, now: float | None = None) -> str:
    """Was von dieser Äußerung an sie gerichtet ist. Leer heißt: nicht gemeint.

    **Fällt ihr Name, geht der ganze Satz an sie** -- auch was vor dem Namen stand, und
    der Name selbst (am Original entschieden). Vorher wurde ab dem Namen geschnitten,
    und "das hier, Lumen, kannst du das prüfen?" kam ohne "das hier" an.

    Vier Wege, in dieser Reihenfolge -- Dauerzuhören, Name im Satz, nackter Name, offenes
    Nachlauf-Fenster. Das Nachlauf-Fenster verbraucht sich sofort, egal ob die Äußerung
    etwas taugt: sonst verlängerte ein Räuspern nach dem Namen es still weiter.

    **Dauerzuhören steht ganz vorn**: dort ist der ganze Satz die Nachricht, mit oder ohne
    Namen. Es ist ein Schalter im Fenster und kein Weckwort -- was v1 verworfen hat, ist
    das *gesprochene* "wach auf", weil man das Zurückschalten vergisst und niemand es
    sieht. Dieser hier liegt auf Platte, steht im Banner, steht in jedem Zug, den sie
    liest, und läuft von selbst ab.
    """
    global _window_until
    now = time.monotonic() if now is None else now

    if mode.convo():
        return text

    hit, bare = named(text)
    if hit and not bare:
        _window_until = 0.0
        return text
    if hit:
        _window_until = now + cfg.WINDOW_S
        return ""
    if _window_until:
        # Auch ein abgelaufenes Fenster wird geschlossen und nicht nur ignoriert. Sonst
        # bleibt ein Zeitpunkt von vorhin stehen, und der naechste Vergleich laeuft gegen
        # eine Zahl, die mit dieser Aeusserung nichts mehr zu tun hat (B9, 17.09.2026).
        was_open = now <= _window_until
        _window_until = 0.0
        if was_open:
            return text
    return ""


# --- der Schnitt ------------------------------------------------------------------

def _level(pcm: bytes) -> float:
    """RMS eines Puffers, 0..1. `audioop` gibt es seit 3.13 nicht mehr; 480 Werte je
    30 ms rechnet Python nebenbei."""
    samples = array.array("h", pcm)
    if not samples:
        return 0.0
    return math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768


class _Cut:
    """Aus Puffern Äußerungen. **Der eine Ort, der eine Äußerung für beendet erklärt**
    (Regel 2) -- zwei Wege dorthin:

      - die Sprechtaste geht hoch. Alles seit dem Drücken ist ein Stück, auch die
        Pausen, und es braucht ihren Namen nicht: das Halten *ist* die Ansprache;
      - END_S lang Stille. Eine Atempause darunter gehört zum Satz.

    Rein: kein Mikrofon, keine Uhr. Der Selbst-Check füttert ihn mit erfundenen Puffern.
    """

    def __init__(self) -> None:
        self.lead: list[bytes] = []   # die letzten LEAD_S, solange nichts läuft
        self.pcm: list[bytes] = []
        self.on = self.ptt = False
        self.loud = self.quiet = self.peak = 0.0
        self.began = 0.0

    def feed(self, pcm: bytes, level: float, ptt: bool, now: float, deaf: bool = False):
        """Ein Puffer. Zurück kommt `(ton, taste, beginn, spitze)`, sobald eine Äußerung
        fertig ist, sonst None."""
        if deaf and not ptt and not self.ptt:
            # Sein Mikro ist aus: ohne Taste wird nichts gesammelt, auch kein Vorlauf. Sonst
            # hing die Taste an, was er davor gesagt hatte (am Original gefunden).
            self.__init__()
            return None
        frame_s = len(pcm) / _BYTES_PER_S
        if not self.on:
            # Vorlauf zuerst, dann die Prüfung: so steckt der auslösende Puffer genau
            # einmal drin. v1 hing ihn zusätzlich an -- 20 ms doppelter Ton am Anfang.
            self.lead.append(pcm)
            del self.lead[:-max(1, round(cfg.LEAD_S / frame_s))]
            # Abklingen statt Nullsetzen: Sprache hat Lücken zwischen Silben, einzelne
            # Klicks sollen sich trotzdem nicht aufaddieren (v1).
            self.loud = (self.loud + frame_s if level >= cfg.LEVEL_ON
                         else max(0.0, self.loud - frame_s))
            if not ptt and self.loud < cfg.ATTACK_S:
                return None
            self.on, self.ptt, self.pcm, self.lead = True, ptt, self.lead, []
            self.quiet, self.peak = 0.0, level
            self.began = now - len(self.pcm) * frame_s
            return None

        if self.ptt and not ptt:
            return self._end(0)  # losgelassen: fertig, sofort, ohne Nachlauf
        # Mitten im Satz gedrückt: dasselbe Stück Ton, also derselbe Gedanke.
        self.ptt = self.ptt or ptt
        self.pcm.append(pcm)
        self.peak = max(self.peak, level)
        self.quiet = 0.0 if self.ptt or level >= cfg.LEVEL_ON else self.quiet + frame_s
        if self.quiet >= cfg.END_S:
            # Die Stille am Ende geht nicht mit: sie trägt nichts, und auf langes
            # Rauschen erfindet whisper Untertitel.
            return self._end(round((self.quiet - cfg.TAIL_S) / frame_s))
        if not self.ptt and len(self.pcm) * frame_s >= cfg.MAX_S:
            return self._end(0)  # die Taste deckelt `_ptt` selbst
        return None

    def _end(self, drop: int):
        said = (b"".join(self.pcm[:len(self.pcm) - drop]), self.ptt, self.began, self.peak)
        self.pcm, self.on, self.ptt, self.loud, self.quiet = [], False, False, 0.0, 0.0
        return said


_cut = _Cut()
_tasks: set[asyncio.Task] = set()  # sonst darf der Garbage Collector sie mittendrin holen


# --- das Mikrofon -----------------------------------------------------------------

def devices() -> list[str]:
    """Die Aufnahmegeräte, wie Windows sie nennt -- für die Auswahl im Fenster. Windows
    kürzt die Namen auf 31 Zeichen; gespeichert und gesucht wird genau diese Form."""
    names, caps = [], _Caps()
    for device in range(_winmm.waveInGetNumDevs()):
        if not _winmm.waveInGetDevCapsW(device, ctypes.byref(caps), ctypes.sizeof(caps)):
            names.append(caps.szPname)
    return names


def _open() -> bool:
    """Das gemeinte Mikrofon auf: das in den Einstellungen gewählte, sonst DEVICE aus der
    Config, sonst das Standardgerät von Windows. Gesucht über den Namen, nie den Index.
    Scheitert es, bleibt sie taub und sagt es -- sie ist ohne Ohr immer noch nützlich."""
    global _buffers, _headers
    wanted = mode.settings()["mic"] or cfg.DEVICE
    names = []
    caps = _Caps()
    for device in range(_winmm.waveInGetNumDevs()):
        if _winmm.waveInGetDevCapsW(device, ctypes.byref(caps), ctypes.sizeof(caps)):
            continue
        names.append(caps.szPname)
        if wanted and wanted.lower() in caps.szPname.lower():
            break
    else:
        if wanted or not names:
            log.error("ear", f"{wanted or 'ein mikrofon'} nicht gefunden, sie hoert nicht zu -- "
                             f"da sind: {', '.join(names) or 'keine geraete'}")
            return False
        device, caps.szPname = _WAVE_MAPPER, "Standard-Mikrofon"

    shape = _Format(1, 1, RATE, _BYTES_PER_S, 2, 16, 0)  # 1 = PCM
    if error := _winmm.waveInOpen(ctypes.byref(_mic), device, ctypes.byref(shape), 0, 0, 0):
        log.error("ear", f"{caps.szPname} geht nicht auf (MMRESULT {error}) -- sie hoert nicht zu")
        return False

    size = _BYTES_PER_S * cfg.FRAME_MS // 1000
    _buffers = [ctypes.create_string_buffer(size) for _ in range(cfg.FRAMES_QUEUED)]
    _headers = [_Header(ctypes.cast(buffer, ctypes.c_void_p), size) for buffer in _buffers]
    for header in _headers:
        _winmm.waveInPrepareHeader(_mic, ctypes.byref(header), _HEADER)
        _winmm.waveInAddBuffer(_mic, ctypes.byref(header), _HEADER)
    _winmm.waveInStart(_mic)
    log.info("ear", f"mikrofon #{device}: {caps.szPname}")
    return True


async def listen() -> None:
    """Das Mikrofon aufmachen, wenn Zuhören eingeschaltet ist. Fehlt etwas davon, bleibt
    sie taub und läuft weiter -- das Fenster ist der Weg hinein, der nie ausfällt."""
    enable(mode.feature("ear"))


def enable(on: bool) -> None:
    """Zuhören an oder aus, aus dem Fenster. Synchron, weil die Routen des Fensters es
    sind; der Leser des Mikrofons ist ein Eingabegerät auf der einen Schleife, keine Uhr."""
    global _loop
    if not on:
        _shut()
        return
    if _mic.value:
        return
    if not ready():
        log.error("ear", f"whisper fehlt unter {cfg.WHISPER} -- tools/install-whisper.ps1 ausfuehren")
        return
    if not _open():
        return
    _keys()
    _loop = asyncio.get_running_loop().create_task(_run())
    log.info("ear", f"hoert mit, {_model().name}, satzende nach {cfg.END_S:.0f} s stille")


def ready() -> bool:
    """Ist whisper da? Fürs Fenster: ohne ist der Schalter sinnlos."""
    return cfg.EXE.exists() and bool(models())


def models() -> list[str]:
    """The whisper models lying next to the program, by name ("small-q5_1"). Which ones
    there are is whatever install-whisper.ps1 fetched -- the window offers exactly those."""
    return sorted(p.stem.removeprefix("ggml-") for p in cfg.WHISPER.glob("ggml-*.bin"))


def _model():
    """The model chosen in the settings, if it is there; else the default; else any."""
    chosen = mode.settings()["whisper_model"]
    for name in (chosen, cfg.MODEL.stem.removeprefix("ggml-"), *models()):
        if name and (path := cfg.WHISPER / f"ggml-{name}.bin").exists():
            return path
    return cfg.MODEL


async def close() -> None:
    _shut()


def _shut() -> None:
    """Immer erfolgreich in dem einen, worauf es ankommt: danach hält niemand mehr das
    Mikrofon."""
    global _loop
    if _loop:
        _loop.cancel()
        _loop = None
    if _mic.value:
        _winmm.waveInReset(_mic)
        for header in _headers:
            _winmm.waveInUnprepareHeader(_mic, ctypes.byref(header), _HEADER)
        _winmm.waveInClose(_mic)
        _mic.value = None
        log.info("ear", "mikrofon zu")


async def _run() -> None:
    """Die Schleife des Ohrs: Taste abfragen, volle Puffer abholen, schneiden.

    **Kein zweiter Scheduler** (Regel 2): hier wird nie entschieden, *dass* ein Zug
    passiert -- eine fertige Äußerung geht in `inbox`, und die Uhr holt sie ab. Ein
    Eingabegerät, das abgefragt wird.

    **Gepollt, nicht gehookt** (v1s Befund): `GetAsyncKeyState` braucht weder Fenster
    noch Nachrichtenschleife, und die Puffer meldet Windows über ein Flag, das man
    ansehen kann. Ein Rückruf käme in einem fremden Thread an.
    """
    i = 0
    while True:
        await asyncio.sleep(cfg.PTT_TICK_S)
        now = time.monotonic()
        ptt = _ptt(now)
        deaf = mode.deaf()
        n = 0
        while _headers[i].dwFlags & _DONE:
            header = _headers[i]
            pcm = ctypes.string_at(header.lpData, header.dwBytesRecorded)
            header.dwFlags &= ~_DONE
            _winmm.waveInAddBuffer(_mic, ctypes.byref(header), _HEADER)
            i, n = (i + 1) % len(_headers), n + 1
            if said := _cut.feed(pcm, _level(pcm), ptt, now, deaf):
                task = asyncio.create_task(_hear(*said))
                _tasks.add(task)
                task.add_done_callback(_tasks.discard)
        if n == len(_headers):
            log.warn("ear", f"alle {n} puffer waren voll -- die schleife hing, ton fehlt")


def _keys() -> bool:
    """Die Kombi aus der Config in VK-Codes übersetzen.

    Scheitert das, läuft sie **ohne** Sprechtaste weiter und sagt es laut: ein Ohr ohne
    Taste ist immer noch ein Ohr, und ein Tippfehler in der Config darf sie nicht taub
    machen.
    """
    global _ptt_keys
    try:
        _ptt_keys = _combo(cfg.PTT_HOTKEY)
    except ValueError as why:
        log.error("ear", f"sprechtaste {cfg.PTT_HOTKEY!r}: {why} -- sie laeuft ohne")
        _ptt_keys = ()
        return False
    log.info("ear", f"sprechtaste: {cfg.PTT_HOTKEY} halten, alles dazwischen geht an sie")
    return True


def _combo(text: str) -> tuple[int, ...]:
    """("alt+y") -> VK-Codes. Ein Zeichen geht ueber die aktive Belegung, damit "y" auf
    einem deutschen Layout auch das y ist. Wirft bei Unbekanntem: eine halb erkannte
    Kombination waere eine andere Taste, nicht eine weniger."""
    codes = []
    for part in text.lower().replace(" ", "").split("+"):
        if part in _MODIFIERS:
            codes.append(_MODIFIERS[part])
        elif len(part) == 1 and (code := _user32.VkKeyScanW(part)) != -1:
            codes.append(code & 0xFF)
        elif part[:1] == "f" and part[1:].isdigit() and 1 <= int(part[1:]) <= 12:
            codes.append(0x6F + int(part[1:]))  # VK_F1 = 0x70
        else:
            raise ValueError(f'"{part}" kenne ich als Taste nicht')
    return tuple(codes)


def _keys_down() -> bool:
    """Sind alle Tasten der Kombi JETZT unten?

    Ohne Kombi nie: `all([])` ist True, und das hieße "Taste für immer unten" -- sie
    sammelte dann bis zum Zeitdeckel und sagte nie etwas. Eigene Funktion, damit genau
    dieser Fall prüfbar ist, ohne eine Tastatur zu haben.

    **Alle Tasten der Kombi müssen unten sein**, nicht nur die letzte: wer Alt loslässt
    und Y weiterhält, hat aufgehört zu senden, so wie es jede Sprechtaste hält.
    """
    return _ptt_held or bool(_ptt_keys) and all(
        _user32.GetAsyncKeyState(vk) & _DOWN_BIT for vk in _ptt_keys)


def hold(down: bool) -> None:
    """Die Sprechtaste aus dem Fenster. Kein eigener Weg: `_ptt` liest sie wie die Tasten,
    mit demselben Zeitdeckel -- ein verlorenes Loslassen im Browser hängt nicht für immer."""
    global _ptt_held
    _ptt_held = down


def _ptt(now: float) -> bool:
    """Ist die Sprechtaste gerade gedrückt -- mit Deckel, damit ein vergessener Finger
    nicht heißt, dass sie den Abend sammelt."""
    global _ptt_down, _ptt_since, _ptt_locked
    if not _keys_down():
        if _ptt_down:
            log.debug("ear", f"sprechtaste los nach {now - _ptt_since:.1f} s")
        _ptt_down, _ptt_locked = False, False
    elif _ptt_locked:
        pass  # hängt noch, seit dem Deckel -- erst loslassen zählt wieder
    elif not _ptt_down:
        _ptt_down, _ptt_since = True, now
        log.debug("ear", "sprechtaste unten")
    elif now - _ptt_since > cfg.MAX_S:
        log.warn("ear", f"sprechtaste haengt seit {cfg.MAX_S:.0f} s -- gilt als losgelassen")
        _ptt_down, _ptt_locked = False, True
    return _ptt_down


# --- vom Ton zum Text -------------------------------------------------------------

async def _hear(pcm: bytes, ptt: bool, began: float, peak: float) -> None:
    """Eine fertige Äußerung: einmal transkribieren, dann weiter an `_utterance`."""
    global _busy
    if not _worth(ptt, peak):
        return
    _busy += 1
    try:
        async with _turn:
            text = await _transcribe(pcm)
        log.debug("ear", f"{len(pcm) / _BYTES_PER_S:.1f} s{', taste' if ptt else ''}, "
                         f"pegel bis {peak:.3f}")
        _utterance(text, ptt, began)
    except Exception:
        log.exception("ear", "aeusserung verloren")
    finally:
        _busy -= 1


def _worth(ptt: bool, peak: float) -> bool:
    """Lohnt sich whisper für diesen Ton? Sync und eigen, damit der Selbst-Check es ohne
    Mikrofon und ohne whisper prüfen kann.

    **Nie über die Schwelle gekommen heißt: nichts gesagt.** Nur über die Taste möglich --
    ohne sie fängt keine Äußerung unter der Schwelle an. Am 28.09.2026 kam zweimal "Vertraue
    und glaube, es hilft, es heilt die göttliche Kraft!" bei Pegel 0,000: das Mikrofon war am
    Gerät stumm, er hielt die Taste, und whisper erfindet auf reine Stille einen Satz.
    """
    global _last
    if mode.deaf() and not ptt:
        return False  # spart nur die CPU -- die Sperre selbst steht in `_utterance`
    if peak < cfg.LEVEL_ON:
        log.debug("ear", f"taste ohne ton (pegel bis {peak:.3f}) -- nicht an whisper")
        _last = {"text": "", "stumm": True, "an_sie": False,
                 "at": datetime.now().isoformat(timespec="seconds")}
        return False
    return True


async def _transcribe(pcm: bytes) -> str:
    """Einmal `whisper-cli` je Äußerung. Kein Server: das Modell neu zu laden kostet
    gemessene ~1 s (1,2 s für 13 s Sprache, 28.09.2026), und dafür gibt es keinen
    zweiten Prozess, keinen Port und nichts, was hängen bleiben kann.

    `-sns` unterdrückt whispers Geräuschbeschreibungen ("[Musik]") schon im Modell.
    """
    # ponytail: Modell je Aeusserung neu geladen (~1 s); whisper-server, wenn das spuerbar wird
    path = system.DATA / "_ohr.wav"  # Zwischenspeicher wie `_stimme`, kein Zustand
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)
    return await _whisper(path)


async def _whisper(path) -> str:
    out = await _tool("whisper-cli", str(cfg.EXE), "-m", str(_model()), "-l", lang.pack().WHISPER,
                      "-t", str(cfg.THREADS), "-nt", "-np", "-sns", "-f", str(path))
    return " ".join((out or b"").decode("utf-8", "replace").split())


async def _tool(name: str, *argv: str) -> bytes | None:
    """Ein Werkzeug-Prozess mit Zeitlimit. `None`, wenn er hing, scheiterte oder fehlt."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            # Sie laeuft unter pythonw: ohne das blitzt bei jedem Satz ein Konsolenfenster auf.
            creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as why:
        log.error("ear", f"{name} startet nicht: {why!r}")
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), cfg.TRANSCRIBE_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        log.error("ear", f"{name} hing laenger als {cfg.TRANSCRIBE_TIMEOUT_S} s, abgebrochen")
        return None
    if proc.returncode:
        log.error("ear", f"{name} endete mit {proc.returncode}")
        return None
    return out


def _utterance(text: str, ptt: bool = False, now: float | None = None) -> None:
    """Eine fertige Äußerung. Ins Log geht alles, in die Uhr nur das, was sie meint.
    `now` ist, wann sie *anfing* -- daran misst sich das Nachlauf-Fenster, nicht daran,
    wann whisper fertig wurde."""
    global _last
    now = time.monotonic() if now is None else now
    if not text or _noise(text):
        return
    # Sein Mikro ist aus. Hier und nicht spaeter: vor dem Log. Die Sprechtaste geht durch
    # -- wer sie haelt, meint sie, und ein Verhoerer kann
    # keine Taste druecken.
    if mode.deaf() and not ptt:
        return
    log.debug("ear", text)
    # Die Taste war die Ansprache: kein Namensabgleich, kein Nachlauf-Fenster.
    question = text if ptt else addressed(text, now)
    _last = {"text": text, "an_sie": bool(question),
             "at": datetime.now().isoformat(timespec="seconds")}
    if question:
        log.info("ear", f"{'sprechtaste' if ptt else 'angesprochen'}: {question}")
        inbox.put(question, inbox.SPOKEN)


def status() -> dict:
    """Was das Fenster zeigt: nimmt sie gerade auf, versteht sie gerade, und was kam
    zuletzt an. Ohne das ist Stille nicht zu lesen --
    denkt sie nach, oder kam es nie an?"""
    if not _mic.value:
        state = "aus"
    elif _cut.ptt:
        state = "taste"  # vor "taub": die Taste geht auch bei ausgeschaltetem Mikro durch
    elif mode.deaf():
        state = "taub"
    elif _cut.on:
        state = "hoert"
    elif _busy:
        state = "versteht"
    else:
        state = "bereit"
    # Erst ab einer Sekunde Stille zaehlt die Pause -- davor ist es Luftholen.
    pause = _cut.on and not _cut.ptt and _cut.quiet >= 1.0
    return {"zustand": state, "versteht": _busy > 0,
            "ende_in": round(cfg.END_S - _cut.quiet) if pause else None, "zuletzt": _last}


def _self_check() -> None:
    """Die Ansprache-Erkennung und der Schnitt, ohne Mikrofon. Sie sind das ganze Tor:
    was hier durchfällt, erreicht sie nie, und was zu leicht durchkommt, kostet einen Zug."""
    global _window_until, _last
    _window_until = 0.0
    # The German sentences below test the German tables; English gets its own lines.
    mode.configure(language="en")
    assert _noise("Thanks for watching!") and _noise("Yeah.") and not _noise("yeah and what about the oven")
    mode.configure(language="de")

    assert fold("Möckrit!") == "moeckrit", "Umlaute und Satzzeichen müssen fallen"
    assert fold("Ähm, Öffne") == "aehm oeffne", "auch grosse Umlaute"
    assert named("Lumen, wo stehen wir?")[0], "ihr eigener Name muss sitzen"
    assert named("Lumin, was liegt an?")[0], "ein Verhörer auch"
    assert not named("Wo stehen wir denn heute?")[0], "ohne Namen ist sie nicht gemeint"
    assert not named("")[0], "aus nichts wird keine Ansprache"
    # Ein selbst gewählter Name ist das Weckwort, und der alte zählt dann nicht mehr.
    mode.configure(assistant="Juno")
    try:
        assert named("Juno, wo stehen wir?")[0] and not named("Lumen, wo stehen wir?")[0]
    finally:
        mode.configure(assistant="")

    # Der ganze Satz geht an sie, mit allem vor und hinter dem Namen (28.09.2026).
    assert addressed("Lumen, wo stehen wir?") == "Lumen, wo stehen wir?"
    assert addressed("Ähm, Lumen, guck mal") == "Ähm, Lumen, guck mal", "whisper stellt gern etwas voran"
    assert addressed("das hier, Lumen, kannst du das prüfen?") == \
        "das hier, Lumen, kannst du das prüfen?", "was vor dem Namen steht, gehört zur Frage"
    assert addressed("Kannst du mal gucken, Lumen?") == "Kannst du mal gucken, Lumen?", \
        "der Name am Ende ist kein nackter Name -- die Frage fiel so bis zum 28.09.2026 weg"

    # Nackter Name: die nächste Äußerung ist die Frage.
    now = 1000.0
    assert addressed("Lumen.", now) == "", "nur der Name ist noch keine Frage"
    assert named("Ähm, Lumen?") == (True, True), "Füllwort plus Name ist auch nackt"
    assert addressed("Wie weit ist die Ark?", now + 2) == "Wie weit ist die Ark?", \
        "die Frage nach dem nackten Namen muss durchkommen"
    assert addressed("Und noch was.", now + 3) == "", "das Fenster verbraucht sich sofort"
    addressed("Lumen.", now)
    assert addressed("Zu spät.", now + cfg.WINDOW_S + 1) == "", "ein altes Fenster zählt nicht"

    # Ab hier laeuft wieder die echte Uhr. Bleibt ein Fenster aus der erfundenen offen,
    # vergleicht der naechste Aufruf 1008 gegen `time.monotonic()` -- und das ist die
    # Laufzeit des Rechners. Nach einem Neustart steht sie darunter, also galt jeder Satz
    # als an sie gerichtet und sie kam 17 Minuten lang nicht hoch (B9, vierte Auflage).
    assert _window_until == 0.0, "ein abgelaufenes Fenster muss zu sein, nicht nur wirkungslos"

    # Dauerzuhören: alles zählt, auch ohne Namen. Der Schalter liegt auf Platte, der
    # Check fasst ihn deshalb an und legt ihn hinterher zurück.
    before = mode._read()
    try:
        mode.convo_on(30)
        assert addressed("einfach nur so dahergesagt") == "einfach nur so dahergesagt", (
            "im Dauerzuhören ist der ganze Satz die Nachricht"
        )
    finally:
        mode.store.write(mode.STATE, before)
    assert addressed("einfach nur so dahergesagt") == "", "ohne den Schalter wieder nicht gemeint"

    # Was nie ein Zug werden darf.
    assert _noise("[Aufregende Musik]"), "whispers Geräuschbeschreibung ist kein Satz"
    assert _noise("* Musik *"), "und in Sternchen ist sie auch keiner"
    assert _noise("Untertitel im Auftrag des ZDF"), "die Halluzination auf Stille auch nicht"
    assert _noise("Untertitelung des ZDF, 2020"), "auch mit angehaengter Jahreszahl (15.09.2026)"
    assert _noise("Ja."), "ein Füllwort ist keine Frage"
    assert not _noise("ja genau, und wie war das nochmal"), "ab vier Wörtern geht es durch"

    # --- der Schnitt, mit erfundenen Puffern --------------------------------------
    frame_s = cfg.FRAME_MS / 1000
    samples = RATE * cfg.FRAME_MS // 1000
    loud = array.array("h", [8000, -8000] * (samples // 2)).tobytes()
    still = bytes(samples * 2)
    assert _level(still) == 0.0 and _level(loud) > cfg.LEVEL_ON, "der Pegel muss trennen"

    levels = {loud: _level(loud), still: 0.0}  # einmal gerechnet: der Deckel-Fall sind 4000 Puffer

    def run(cut: _Cut, frames: list[tuple[bytes, bool]], t: float = 0.0, deaf: bool = False) -> list:
        out = []
        for pcm, ptt in frames:
            t += frame_s
            if said := cut.feed(pcm, levels[pcm], ptt, t, deaf):
                out.append(said)
        return out

    def secs(s: float, pcm: bytes, ptt: bool = False) -> list[tuple[bytes, bool]]:
        return [(pcm, ptt)] * round(s / frame_s)

    cut = _Cut()
    assert not run(cut, secs(0.03, loud) + secs(3, still)), "ein Klick ist kein Satz"
    assert not cut.on, "und fängt auch keinen an"

    # Seine Regel vom 28.09.2026: zwei Sekunden Atempause sind mitten im Satz.
    cut = _Cut()
    said = run(cut, secs(1, still) + secs(1, loud) + secs(2, still) + secs(1, loud)
               + secs(cfg.END_S + 1, still))
    assert len(said) == 1, f"ein Satz mit Atempause ist EINE Äußerung, nicht {len(said)}"
    seconds = len(said[0][0]) / _BYTES_PER_S
    assert 4 <= seconds <= 4 + cfg.LEAD_S + cfg.TAIL_S + 0.1, f"Vorlauf + Satz + Rest, nicht {seconds:.2f} s"
    assert said[0][0].startswith(still), "der Vorlauf fängt vor dem ersten Laut an"
    assert not said[0][1], "ohne Taste ist es keine Tasten-Äußerung"

    cut = _Cut()
    assert not run(cut, secs(1, loud) + secs(cfg.END_S - 0.5, still)), "vor END_S ist nichts fertig"
    assert cut.on, "da läuft noch der Satz"

    # Die Taste: leise Denkpausen zählen mit, fertig ist es beim Loslassen, nicht später.
    cut = _Cut()
    said = run(cut, secs(1, loud, True) + secs(cfg.END_S + 2, still, True) + secs(0.03, still))
    assert len(said) == 1 and said[0][1], "Loslassen beendet sofort, als Tasten-Äußerung"
    assert len(said[0][0]) / _BYTES_PER_S >= 1 + cfg.END_S, "die Pause beim Halten ist kein Satzende"

    # Mitten im Satz gedrückt: dasselbe Stück Ton, also eine Äußerung.
    cut = _Cut()
    said = run(cut, secs(1, loud) + secs(1, loud, True) + secs(0.03, still))
    assert len(said) == 1 and said[0][1], "der angefangene Satz wird zur Tasten-Äußerung"
    assert len(said[0][0]) / _BYTES_PER_S >= 2 - 2 * frame_s

    # Mikro aus: nur was nach dem Druecken kommt, nicht der Satz davor (19.10.2026).
    cut = _Cut()
    said = run(cut, secs(2, loud) + secs(1, loud, True) + secs(0.03, still), deaf=True)
    assert len(said) == 1 and said[0][1], "die Taste geht bei Mikro aus durch"
    assert len(said[0][0]) / _BYTES_PER_S <= 1 + frame_s, "was vor dem Druecken lief, geht nicht mit"

    cut = _Cut()
    assert len(run(cut, secs(cfg.MAX_S + 1, loud))) == 1, "ohne Taste greift der Deckel"

    # --- die Sprechtaste ----------------------------------------------------------
    global _ptt_keys
    assert _combo(cfg.PTT_HOTKEY), f"{cfg.PTT_HOTKEY} loest zu keiner Taste auf"  # wirft bei Unsinn
    assert _combo("alt+y") == (0x12, 0x59) and _combo("strg+f5") == (0x11, 0x74)

    merkt = _ptt_keys
    try:
        _ptt_keys = ()
        assert not _keys_down(), "ohne Kombi ist die Taste nie unten -- all([]) ist True"
        hold(True)
        assert _keys_down(), "der Knopf im Fenster ist dieselbe Taste"
    finally:
        hold(False)
        _ptt_keys = merkt

    # Das Nachlauf-Fenster zaehlt ab dem Anfang des Satzes, nicht ab whispers Antwort:
    # mit 5 s Stille plus Transkript waere es sonst immer schon zu.
    with inbox.scratch():
        _utterance("Lumen.", now=500.0)
        _utterance("wie weit ist die Ark?", now=500.0 + cfg.WINDOW_S - 1)
        assert inbox._global_queue().qsize() == 1, "die Frage nach dem nackten Namen kommt an"
    _window_until = 0.0

    # Mikro aus: ihr Name kommt nicht durch, die Sprechtaste schon (28.09.2026).
    mode.deafen(True)
    try:
        with inbox.scratch():
            _utterance("Lumen, das hoert sie jetzt nicht", now=400.0)
            assert inbox._global_queue().qsize() == 0, "bei ausgeschaltetem Mikro zaehlt der Name nicht"
            _utterance("das hoert sie trotzdem", ptt=True, now=410.0)
            assert inbox._global_queue().qsize() == 1, "die Sprechtaste geht bei Mikro aus durch"
        assert not _worth(False, 0.3), "ohne Taste rechnet whisper bei Mikro aus gar nicht erst"
        assert _worth(True, 0.3), "mit Taste schon"
    finally:
        mode.deafen(False)

    # Taste gehalten, Mikro am Geraet stumm: Pegel 0,000, und whisper erfand einen Satz.
    assert not _worth(True, 0.0), "Stille geht nicht an whisper"
    assert _last.get("stumm"), "das Fenster muss zeigen, dass nichts ankam"

    # Die Taste ist die Ansprache: ohne Namen, ohne Dauerzuhören, trotzdem an sie.
    with inbox.scratch():
        _utterance("mach mir den Editor auf", ptt=True, now=200.0)
        assert inbox._global_queue().qsize() == 1, "über die Sprechtaste geht es ohne ihren Namen"
    with inbox.scratch():
        _utterance("mach mir den Editor auf", now=300.0)
        assert inbox._global_queue().qsize() == 0, "ohne Taste und ohne Namen ist sie nicht gemeint"
        assert _last["an_sie"] is False, "das Fenster muss zeigen, dass es nicht an sie ging"
    _window_until = 0.0
    _last = {}
    assert status()["zustand"] in ("aus", "bereit", "taub"), "ohne Ton laeuft nichts"
    assert isinstance(devices(), list) and all(isinstance(d, str) for d in devices())
    assert all(not m.startswith("ggml-") for m in models()), "model names without the file prefix"
    mode.configure(language="")
