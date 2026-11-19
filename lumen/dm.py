"""Discord-DM über den eigenen Bot: ein Eingang in die eine Schlange, und ein Weg hinaus.

Was der Besitzer per DM schreibt, landet in `inbox` wie Getipptes aus dem Fenster --
derselbe Faden, dasselbe Gespräch. Die Antwort auf eine DM geht in die DM zurück; von
selbst schreibt sie über `actions/schreiben.py`. Jeder andere, der dem Bot schreibt, wird
ignoriert.

Hinein über den Gateway, hinaus über REST. Websocket und HTTPS von Hand auf asyncio wie
`web.py`: die stdlib hat keinen Websocket, `urllib` hielte die Uhr an, und ein Thread wäre
ein zweiter Strang (Regel 2).
"""

import asyncio
import base64
import contextlib
import json
import os
import random
import re
import ssl
import urllib.parse
from typing import Any

from lumen import brain, inbox, lang, log, mode, store
from lumen.config import dm as cfg
from lumen.config import system

STATE = "dm"

# Nur DMs. Serverkanäle sieht sie nicht, und den Nachrichtentext einer DM gibt Discord
# auch ohne den privilegierten Message-Content-Intent heraus.
_INTENTS = 1 << 12

_SSL = ssl.create_default_context()
_channel = ""  # der DM-Kanal zum Besitzer, beim ersten Gebrauch geholt
_runner: asyncio.Task | None = None
_down = False  # ein totes Netz steht einmal im Log, nicht bei jedem Versuch
_online = False  # für das Fenster: kam die Verbindung bis READY?


def start() -> None:
    """Nichts beim Boot. Verbinden braucht die laufende Schleife, also `listen()`."""


def _owner() -> str:
    return system.secret("OWN_USER_ID")


def ready() -> bool:
    """Sind Token und ID eingetragen?"""
    return bool(system.secret("DISCORD_TOKEN") and _owner())


def status() -> str:
    """Fürs Fenster: aus, nicht eingerichtet, verbunden oder getrennt."""
    if not mode.feature("discord"):
        return "aus"
    if not ready():
        return "nicht eingerichtet"
    return "verbunden" if _online else "verbindet…"


async def listen() -> None:
    """Online gehen, wenn Discord eingeschaltet und eingerichtet ist. Ohne läuft sie ohne
    DM weiter -- das Fenster ist der Weg hinein, der nie ausfällt."""
    enable(mode.feature("discord"))


def enable(on: bool) -> None:
    """An oder aus, aus dem Fenster -- auch nach einem neuen Token (aus, dann an).
    Synchron, weil die Routen des Fensters es sind; die Verbindung ist eine Leitung auf der
    einen Schleife, keine Uhr."""
    global _runner, _online
    if _runner:
        _runner.cancel()
        _runner, _online = None, False
    if on and ready():
        _runner = asyncio.get_running_loop().create_task(_run())
    elif on:
        log.info("dm", "discord an, aber kein token oder keine id eingetragen")


async def close() -> None:
    """Abmelden, damit Discord sofort offline zeigt und nicht erst nach einer Minute."""
    global _runner
    if _runner:
        _runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _runner
        _runner = None


async def send(text: str) -> bool:
    """In die DM an den Besitzer. Wahr, wenn alles ankam.

    Wirft nie, wie `voice.say`: ist Discord weg, steht ihr Satz trotzdem im Fenster, und
    das Log sagt warum. Kein Zug darf daran scheitern, dass ein Nebenausgang zu ist.
    """
    if not text.strip() or not ready() or not mode.feature("discord"):
        return False
    try:
        channel = await _open()
        for part in _split(text):
            status_, data = await _api("POST", f"/channels/{channel}/messages", {"content": part})
            if status_ != 200:
                raise RuntimeError(f"HTTP {status_} {data}")
    except Exception as why:
        log.error("dm", f"nicht angekommen: {why!r}")
        return False
    return True


# --- der Gateway ------------------------------------------------------------------

async def _run() -> None:
    """Verbunden bleiben. Reißt die Verbindung ab -- nach dem Standby der Normalfall --,
    wird neu verbunden, bei jedem Fehlschlag mit doppelter Wartezeit. Discord erlaubt
    1000 Anmeldungen am Tag und setzt den Token zurück, wenn es mehr werden."""
    global _down, _online
    wait = cfg.RECONNECT_S
    while True:
        try:
            if await _session():
                wait = cfg.RECONNECT_S  # es war eine Verbindung, kein Fehlschlag
        except Exception as why:
            if not _down:
                log.error("dm", f"discord getrennt, verbinde weiter neu: {why!r}")
            _down = True
            wait = min(wait * 2, cfg.RECONNECT_MAX_S)
        _online = False
        await asyncio.sleep(wait)


async def _session() -> bool:
    """Eine Verbindung, von der Anmeldung bis sie endet. Wahr, wenn sie bis READY kam.
    Nichts hier entscheidet, *dass* ein Zug passiert: Nachrichten gehen in die Schlange."""
    global _down, _online
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(cfg.GATEWAY, 443, ssl=_SSL), cfg.TIMEOUT_S)
    beat = show = None
    seen = False
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write((f"GET /?v=10&encoding=json HTTP/1.1\r\nHost: {cfg.GATEWAY}\r\n"
                      "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), cfg.TIMEOUT_S)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"kein websocket: {head[:80]!r}")

        hello = await asyncio.wait_for(_recv(reader, writer), cfg.TIMEOUT_S)
        pulse = {"seq": None, "acked": True}
        beat = asyncio.create_task(_beat(writer, hello["d"]["heartbeat_interval"] / 1000, pulse))
        await _send(writer, {"op": 2, "d": {
            "token": system.secret("DISCORD_TOKEN"), "intents": _INTENTS,
            "properties": {"os": "windows", "browser": "lumen", "device": "lumen"},
            "presence": _presence(lang.t("dm.idle"))}})

        while (event := await _recv(reader, writer)) is not None:
            if event.get("s") is not None:
                pulse["seq"] = event["s"]
            op, kind = event["op"], event.get("t")
            if op == 11:
                pulse["acked"] = True
            elif op == 1:
                await _send(writer, {"op": 1, "d": pulse["seq"]})
            elif op in (7, 9):
                return seen  # Discord will eine neue Verbindung
            elif kind == "READY":
                seen, _down, _online = True, False, True
                log.info("dm", "discord verbunden, online")
                show = asyncio.create_task(_show(writer))
                # Was geschrieben wurde, während sie aus war oder im Standby lag.
                await _fetch()
            elif kind == "MESSAGE_CREATE":
                await _take(event["d"])
        return seen
    finally:
        for task in (beat, show):
            if task:
                task.cancel()
        # Sauber abmelden (1000), dann ist der Bot sofort offline statt nach einer Minute.
        with contextlib.suppress(Exception):
            _frame(writer, 8, (1000).to_bytes(2, "big"))
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), 2)


async def _beat(writer: asyncio.StreamWriter, interval: float, pulse: dict[str, Any]) -> None:
    """Der Herzschlag, den der Gateway verlangt. Kam auf den letzten keine Antwort, ist
    die Leitung tot -- nach dem Standby hängt sie so, ohne dass ein Lesen je scheitert.
    Also hart zu, damit `_run` neu verbindet."""
    try:
        await asyncio.sleep(interval * random.random())  # so will es Discord
        while pulse["acked"]:
            pulse["acked"] = False
            await _send(writer, {"op": 1, "d": pulse["seq"]})
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    writer.transport.abort()


def _status() -> str:
    """Was sie gerade tut, in einem Wort aus der festen Liste -- ohne das Worauf."""
    now = brain.activity()
    if not now["busy"]:
        return lang.t("dm.idle")
    if now["job"] == "remember":
        return lang.t("dm.remember")
    tool = now["steps"][-1]["tool"].split("__")[-1] if now["steps"] else ""
    return lang.t(cfg.STATUS_TOOL.get(tool, "dm.busy"))


def _presence(text: str) -> dict[str, Any]:
    return {"status": "online", "since": None, "afk": False,
            "activities": [{"type": 4, "name": "Custom Status", "state": text}]}


async def _show(writer: asyncio.StreamWriter) -> None:
    """Den Status nachschieben, wenn er sich ändert. Liest nur mit, was `brain` ohnehin
    fürs Fenster führt, und entscheidet nichts -- eine Leitung, keine Uhr."""
    shown = lang.t("dm.idle")
    with contextlib.suppress(OSError, ConnectionError, RuntimeError):
        while True:
            await asyncio.sleep(cfg.STATUS_S)
            if (now := _status()) != shown:
                await _send(writer, {"op": 3, "d": _presence(now)})
                shown = now


async def _recv(reader: asyncio.StreamReader, writer: Any) -> dict[str, Any] | None:
    """Eine ganze Nachricht vom Gateway, über Fragmente hinweg. Ping wird beantwortet;
    None heißt, der Server hat zugemacht."""
    data = b""
    while True:
        b1, b2 = await reader.readexactly(2)
        n = b2 & 0x7F
        if n == 126:
            n = int.from_bytes(await reader.readexactly(2), "big")
        elif n == 127:
            n = int.from_bytes(await reader.readexactly(8), "big")
        mask = await reader.readexactly(4) if b2 & 0x80 else b""
        payload = await reader.readexactly(n)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        op = b1 & 0x0F
        if op == 8:
            if payload[:2]:
                code = int.from_bytes(payload[:2], "big")
                # 4004 falscher Token, 4013/4014 Intent -- das heilt kein Neuverbinden.
                raise RuntimeError(f"gateway zu mit {code} {payload[2:].decode(errors='replace')}")
            return None
        if op == 9:
            _frame(writer, 10, payload)
        elif op != 10:
            data += payload
            if b1 & 0x80:
                return json.loads(data)


def _frame(writer: Any, op: int, payload: bytes) -> None:
    """Ein Frame an den Server -- vom Client immer maskiert, sonst legt er auf."""
    n = len(payload)
    if n < 126:
        size = bytes([0x80 | n])
    elif n < 65536:
        size = bytes([0x80 | 126]) + n.to_bytes(2, "big")
    else:
        size = bytes([0x80 | 127]) + n.to_bytes(8, "big")
    mask = os.urandom(4)
    writer.write(bytes([0x80 | op]) + size + mask
                 + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


async def _send(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    _frame(writer, 1, json.dumps(message).encode())
    await writer.drain()


# --- Nachrichten ------------------------------------------------------------------

def _last() -> str | None:
    return (store.read(STATE, {}) or {}).get("last")


async def _fetch() -> None:
    """Nachholen, was seit der letzten gesehenen Nachricht kam. Läuft bei jeder Anmeldung."""
    last = _last()
    channel = await _open()
    status_, found = await _api(
        "GET", f"/channels/{channel}/messages?" + (f"after={last}&limit=50" if last else "limit=1"))
    if status_ != 200:
        raise RuntimeError(f"HTTP {status_} {found}")
    found = sorted(found, key=lambda m: int(m["id"]))
    # Beim allerersten Mal nur die Stelle merken: sonst beantwortet sie die ganze
    # DM-Geschichte, Nachricht für Nachricht.
    if not last:
        store.write(STATE, {"last": found[-1]["id"] if found else "0"})
        return
    for m in found:
        await _take(m)
        store.write(STATE, {"last": m["id"]})  # auch über ihre eigenen hinweg


async def _take(m: dict[str, Any]) -> None:
    """Eine Nachricht vom Besitzer in die Schlange. Die Stelle wandert mit, auf Platte
    (Regel 5): was während einer Trennung kam, holt `_fetch` nach, und nicht doppelt."""
    if m["author"]["id"] != _owner():
        return  # ihre eigenen Antworten, und Fremde, die dem Bot schreiben
    last = _last()
    if last and int(m["id"]) <= int(last):
        return
    parts = _parts(m)
    # Numbered: Discord names pasted images all "image.png", and the second overwrote the first.
    files = [a for p in parts for a in p.get("attachments") or []]
    notes = [await _keep(f"{m['id']}_{i}", a) for i, a in enumerate(files)]
    texts = [m.get("content") or "", *(f"[weitergeleitet]\n{p.get('content') or ''}".rstrip()
                                       for p in parts[1:])]
    inbox.put("\n".join(x for x in [*texts, *notes] if x), inbox.DM)
    store.write(STATE, {"last": m["id"]})
    log.info("dm", f"nachricht, {len(notes)} anhaenge")


def _parts(m: dict[str, Any]) -> list[dict[str, Any]]:
    """The message and what it forwards. A Discord forward has no content and no
    attachments of its own -- both sit in `message_snapshots`."""
    return [m, *(s.get("message") or {} for s in m.get("message_snapshots") or [])]


async def _open() -> str:
    """Der DM-Kanal zum Besitzer. Beim ersten Gebrauch geholt, nicht beim Boot: nach dem
    Standby ist das Netz ein paar Sekunden weg."""
    global _channel
    if not _channel:
        status_, data = await _api("POST", "/users/@me/channels", {"recipient_id": _owner()})
        if status_ != 200:
            raise RuntimeError(f"dm-kanal: HTTP {status_} {data}")
        _channel = data["id"]
    return _channel


def _name(filename: str) -> str:
    """Ein Dateiname, der nirgends hinführt außer in den eigenen Ordner."""
    return re.sub(r"[^\w.\-]", "_", filename or "datei")[-80:]


async def _keep(msg_id: str, a: dict[str, Any]) -> str:
    """Einen Anhang auf die Platte legen und sagen, wo er liegt -- sie sieht ihn sich mit
    `Read` an, das kann Bilder und PDFs. Wirft nie. Sprachnachrichten sind hier nur Dateien:
    whisper-cli liest kein Opus, und ffmpeg dafür mitzuliefern lohnt sich nicht."""
    name = _name(a.get("filename", ""))
    if (a.get("size") or 0) > cfg.MAX_BYTES:
        return f"[{lang.t('note.attachment')} {name}: {a['size'] / 1e6:.0f} MB]"
    try:
        status_, data = await _http("GET", a["url"])
        if status_ != 200:
            raise RuntimeError(f"HTTP {status_}")
    except Exception as why:
        log.error("dm", f"anhang {name} nicht geladen: {why!r}")
        return f"[{lang.t('note.attachment')} {name}: -]"
    return f"[{lang.t('note.attachment')}: {store.write_bytes(f'{cfg.FILES}/{msg_id}_{name}', data)}]"


# --- HTTPS von Hand ---------------------------------------------------------------

async def _api(method: str, path: str, payload: Any = None, _again: bool = True) -> tuple[int, Any]:
    body = json.dumps(payload).encode() if payload is not None else b""
    status_, raw = await _http(method, cfg.API + path, body, {
        "Authorization": f"Bot {system.secret('DISCORD_TOKEN')}",
        "Content-Type": "application/json"})
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = raw[:200]  # Cloudflare antwortet im Fehlerfall mit HTML
    if status_ == 429 and _again:
        # Discord sagt selbst, wie lange. Einmal abwarten, dann nochmal.
        await asyncio.sleep(float(data.get("retry_after", 5)) if isinstance(data, dict) else 5)
        return await _api(method, path, payload, _again=False)
    return status_, data


async def _http(method: str, url: str, body: bytes = b"",
                headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    """Eine HTTPS-Anfrage, ohne die Uhr anzuhalten. `Connection: close`, also ist die
    Antwort zu Ende, wenn der Server auflegt -- keine Längen raten."""
    u = urllib.parse.urlsplit(url)
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(u.hostname, 443, ssl=_SSL), cfg.TIMEOUT_S)
    try:
        head = {"Host": u.hostname, "User-Agent": "DiscordBot (lumen, 1)", "Connection": "close",
                "Content-Length": str(len(body)), **(headers or {})}
        writer.write(f"{method} {u.path}{'?' + u.query if u.query else ''} HTTP/1.1\r\n".encode()
                     + "".join(f"{k}: {v}\r\n" for k, v in head.items()).encode()
                     + b"\r\n" + body)
        raw = await asyncio.wait_for(reader.read(), cfg.TIMEOUT_S)
    finally:
        writer.close()
    return _parse(raw)


def _parse(raw: bytes) -> tuple[int, bytes]:
    head, _, payload = raw.partition(b"\r\n\r\n")
    status_ = int(head.split(None, 2)[1])
    if b"transfer-encoding: chunked" in head.lower():
        payload = _unchunk(payload)
    return status_, payload


def _unchunk(data: bytes) -> bytes:
    out = bytearray()
    while True:
        size, _, data = data.partition(b"\r\n")
        n = int(size.split(b";")[0], 16)
        if not n:
            return bytes(out)
        out += data[:n]
        data = data[n + 2:]


def _split(text: str) -> list[str]:
    """Discord nimmt höchstens LIMIT Zeichen -- geteilt an Zeilenumbrüchen, wo es geht."""
    parts = []
    while len(text) > cfg.LIMIT:
        cut = text.rfind("\n", 0, cfg.LIMIT)
        if cut <= 0:
            cut = cfg.LIMIT
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts + [text] if text else parts


def _self_check() -> None:
    """Was ohne Netz prüfbar ist: Frames, Teilen, HTTP lesen, Dateinamen, wer rein darf."""
    assert _split("kurz") == ["kurz"]
    lang_ = "\n".join(["x" * 900] * 5)
    assert all(len(p) <= cfg.LIMIT for p in _split(lang_)), "über dem Limit lehnt Discord ab"
    assert "".join(_split(lang_)).replace("\n", "") == lang_.replace("\n", ""), "beim Teilen fällt nichts weg"
    assert all(len(p) <= cfg.LIMIT for p in _split("y" * 4500)), "auch ohne Zeilenumbruch"
    assert _split("") == [], "aus nichts wird keine leere Nachricht"

    assert _parse(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}") == (200, b"{}")
    assert _parse(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                  b"3\r\nabc\r\n2;x=y\r\nde\r\n0\r\n\r\n") == (200, b"abcde"), "chunked"

    # Der Dateiname kommt von außen: kein Trenner darf überleben.
    assert "/" not in _name("../../.env") and "\\" not in _name("..\\x.png")
    assert _name("") == "datei"

    fwd = {"content": "", "message_snapshots": [{"message": {"content": "hi"}}]}
    assert [p.get("content") for p in _parts(fwd)] == ["", "hi"], "eine Weiterleitung trägt ihren Text im Snapshot"

    # Nur der Besitzer: ein Fremder, der dem Bot schreibt, erreicht die Schlange nie.
    with inbox.scratch():
        step = _take({"id": "99999999999999999999", "author": {"id": "1"}, "content": "hallo"})
        try:
            step.send(None)
        except StopIteration:
            pass
        assert inbox._global_queue().empty(), "ein Fremder kam durch"
    assert status() == "aus", "der Schalter steht beim ersten Start auf aus"

    allowed = {lang.t(k) for k in ("dm.idle", "dm.busy", "dm.remember", *cfg.STATUS_TOOL.values())}
    assert _status() in allowed and all(len(t) <= 128 for t in allowed), "der Status kommt aus der Liste"

    # Frames im Kreis: was `_frame` schreibt, muss `_recv` lesen, mit einem Ping dazwischen.
    class _Tape:
        def __init__(self) -> None:
            self.out = b""

        def write(self, data: bytes) -> None:
            self.out += data

    def _drive(step: Any) -> Any:
        try:
            step.send(None)
        except StopIteration as done:
            return done.value
        raise AssertionError("der Frame-Leser hat auf mehr gewartet, als da war")

    sent, back = _Tape(), _Tape()
    message = {"op": 0, "d": "ä" * 300}
    _frame(sent, 9, b"da?")
    _frame(sent, 1, json.dumps(message).encode())
    tape = asyncio.StreamReader()
    tape.feed_data(sent.out)
    assert _drive(_recv(tape, back)) == message, "was hinausgeht, muss zurücklesbar sein"
    assert back.out[0] == 0x80 | 10, "ein Ping will ein Pong"
