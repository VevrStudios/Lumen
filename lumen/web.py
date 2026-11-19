"""The window. An input, not a second clock.

It never calls the model. A message goes into `inbox`, the one clock takes it out and
answers it, and the page finds the answer on its next poll. That keeps rule 2 intact
where it actually matters: one owner of "when is a turn over".

Hand-rolled HTTP on asyncio rather than http.server in a thread -- the stdlib server is
blocking, and a thread here would be a second thing running on its own. It serves one
page and a few endpoints to one person on the loopback address.
"""

import asyncio
import json
import mimetypes
import re
import time
import urllib.parse
from typing import Any

from lumen import brain, dm, ear, inbox, lang, log, mode, shortcut, store, thread, voice
from lumen.config import system
from lumen.config import voice as voicecfg
from lumen.config import web as cfg

_server: asyncio.AbstractServer | None = None


def start() -> None:
    """Nothing at boot. Listening needs a running loop, so `__main__` awaits `serve()`."""


async def serve() -> None:
    global _server
    try:
        _server = await asyncio.start_server(_handle, cfg.HOST, cfg.PORT)
    except OSError as why:
        # A window that will not open must not take the daemon down with it.
        log.error("web", f"fenster nicht aufgegangen: {why}")
        return
    log.info("web", f"fenster auf http://{cfg.HOST}:{cfg.PORT}")


def _steps(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Tool calls as a person reads them. `tool` stays along for the column's filters."""
    steps = []
    for step in raw:
        if step["tool"] == "ToolSearch":
            continue  # loading a tool is mechanics, nothing anyone needs to see
        name = step["tool"].split("__")[-1]
        on = f"„{step['on']}“" if step["tool"] == "WebSearch" else step["on"]
        verb = lang.pack().TEXT.get(f"verb.{name}", name)  # an unknown tool shows its name
        steps.append({"tool": name, "verb": verb, "on": on,
                      "at": step.get("at", "")})
    return steps


def _doing() -> dict[str, Any]:
    now = brain.activity()
    return {"busy": now["busy"], "job": now["job"], "since": now["since"],
            "label": now.get("label", ""), "steps": _steps(now["steps"])}


def _acts() -> list[dict[str, Any]]:
    return [{**a, "steps": _steps(a.get("steps") or [])} for a in store.tail(brain.ACTS, cfg.SHOW)]


def _settings() -> dict[str, Any]:
    """What the settings panel shows. Never the key itself -- only whether there is one."""
    chosen = mode.settings()
    return {**chosen, "owner": mode.owner(), "assistant": mode.assistant(),
            "voice": chosen["voice"] or voicecfg.DEFAULT, "voices": list(lang.pack().VOICES),
            "language": lang.code(), "languages": {k: m.LABEL for k, m in lang.LANGS.items()},
            "azure": voice.ready(), "region": system.secret("AZURE_SPEECH_REGION"),
            "whisper": ear.ready(), "mics": ear.devices(), "models": ear.models(),
            "model": ear._model().stem.removeprefix("ggml-"), "discord": dm.status(), "discord_ready": dm.ready(),
            "discord_user": system.secret("OWN_USER_ID"), "autostart": shortcut.autostart()}


def _state() -> dict[str, Any]:
    """Everything the page shows, in one answer. One endpoint rather than four: the page
    is a view of her state, and four half-synchronised views of it is how v1 got two
    UIs that disagreed."""
    seen = store.read("observe", {}) or {}
    return {
        "chat": store.tail(thread.RECORD, cfg.SHOW),
        "thoughts": store.tail(thread.THOUGHTS, cfg.SHOW),
        "mode": {"testing": mode.testing(), "muted": mode.muted(),
                 "convo": mode.convo(), "deaf": mode.deaf(), "blind": mode.blind(),
                 "line": mode.line(), "until": store.read(mode.STATE, {}) or {}},
        "settings": _settings(),
        # The window's words: German is its source text, other languages map from it.
        "ui": lang.pack().UI,
        "poll_ms": cfg.POLL_MS,
        "denkt": _doing(),
        "spricht": voice.speaking(),
        "acts": _acts(),
        "ohr": ear.status(),
        "gesehen": {"at": seen.get("at"), "app": seen.get("app"), "titel": seen.get("title")},
    }


def _name(filename: str) -> str:
    """A file name that leads nowhere but into the uploads folder."""
    return re.sub(r"[^\w.\-]", "_", filename or "datei")[-80:]


def _configure(want: dict[str, Any]) -> tuple[bool, str]:
    """The settings panel. Validated here, at the edge: the region goes into a host name,
    so anything but letters and digits would send the key somewhere else."""
    key, region = str(want.get("azure_key") or "").strip(), str(want.get("azure_region") or "").strip().lower()
    if key and not re.fullmatch(r"[A-Za-z0-9]{16,128}", key):
        return False, lang.t("err.key")
    if region and not re.fullmatch(r"[a-z0-9]{2,40}", region):
        return False, lang.t("err.region")
    if "voice" in want and want["voice"] not in lang.pack().VOICES:
        return False, lang.t("err.voice")
    assistant = want.get("assistant")
    if assistant is not None and not (isinstance(assistant, str) and (
            not assistant.strip() or re.fullmatch(mode.ASSISTANT_NAME, assistant.strip()))):
        return False, lang.t("err.name")
    token, user = str(want.get("discord_token") or "").strip(), str(want.get("discord_user") or "").strip()
    if token and not re.fullmatch(r"[A-Za-z0-9._-]{50,100}", token):
        return False, lang.t("err.token")
    if user and not re.fullmatch(r"\d{15,22}", user):
        return False, lang.t("err.user")
    if want.get("discord_clear"):
        store.save_secrets({"DISCORD_TOKEN": "", "OWN_USER_ID": ""})
        # Its switch is hidden without a token, so it must not stay on unseen.
        mode.configure(features={"discord": False})
    elif token or user:
        store.save_secrets({k: v for k, v in (("DISCORD_TOKEN", token), ("OWN_USER_ID", user)) if v})
    if want.get("azure_clear"):
        store.save_secrets({"AZURE_SPEECH_KEY": "", "AZURE_SPEECH_REGION": ""})
    elif key or region:
        store.save_secrets({k: v for k, v in (("AZURE_SPEECH_KEY", key), ("AZURE_SPEECH_REGION", region)) if v})
    language = want.get("language")
    if language is not None and language not in lang.LANGS:
        return False, lang.t("err.language")
    model = want.get("whisper_model")
    if model is not None and model not in ear.models():
        return False, lang.t("err.model")
    mic = want.get("mic")
    if mic is not None and not (isinstance(mic, str) and (mic == "" or mic in ear.devices())):
        return False, lang.t("err.mic")
    features = want.get("features") if isinstance(want.get("features"), dict) else None
    mode.configure(name=want["name"] if isinstance(want.get("name"), str) else None,
                   voice=want.get("voice"), features=features, welcomed=want.get("welcomed") is True,
                   mic=mic, language=language, whisper_model=model,
                   assistant=assistant.strip() if isinstance(assistant, str) else None)
    if mic is not None or (features and "ear" in features):
        ear.enable(False)  # an other device needs a fresh open, not "already open"
        ear.enable(mode.feature("ear"))
    if "autostart" in want and not shortcut.set_autostart(bool(want["autostart"])):
        return False, lang.t("err.autostart")
    # A new token or ID means a new login; the switch means on or off.
    if (features and "discord" in features) or token or user or want.get("discord_clear"):
        dm.enable(mode.feature("discord"))
    return True, ""


def _route(method: str, path: str, body: bytes) -> tuple[int, str, bytes]:
    url = urllib.parse.urlsplit(path)
    path = url.path
    if method == "GET" and path in ("/", "/index.html"):
        page = (system.ROOT / "lumen" / "web.html").read_bytes()
        return 200, "text/html; charset=utf-8", page

    if method == "GET" and path == "/preact.js":
        # Preact + htm, vendored: the page renders without a CDN and without a build step.
        return 200, "text/javascript; charset=utf-8", (system.ROOT / "lumen" / "preact.js").read_bytes()

    if method == "GET" and path.startswith("/state"):
        return 200, "application/json; charset=utf-8", _json(_state())

    if method == "POST" and path == "/upload":
        # An attachment: the path goes into the message as [Anhang: ...], and she looks at
        # it with Read.
        if not body or len(body) > cfg.MAX_BYTES:
            return 413, "application/json", _json({"ok": False})
        name = _name(urllib.parse.parse_qs(url.query).get("name", [""])[0])
        kept = store.write_bytes(f"{cfg.FILES}/web_{int(time.time() * 1000)}_{name}", body)
        return 200, "application/json", _json({"ok": True, "path": str(kept)})

    if method == "GET" and path.startswith("/file/"):
        # Only from the uploads folder: `_name` lets no separator through.
        kept = system.DATA / cfg.FILES / _name(urllib.parse.unquote(path[6:]))
        if not kept.is_file():
            return 404, "text/plain; charset=utf-8", "nichts hier".encode()
        return 200, mimetypes.guess_type(kept.name)[0] or "application/octet-stream", kept.read_bytes()

    if method == "POST" and path == "/ptt":
        ear.hold(bool(json.loads(body or b"{}").get("down")))
        return 200, "application/json", _json({"ok": True})

    if method == "POST" and path == "/say":
        said = json.loads(body or b"{}")
        text = (said.get("text") or "").strip()
        inbox.put(text, inbox.TYPED, deep=said.get("deep") is True)
        return 200, "application/json", _json({"ok": bool(text)})

    if method == "POST" and path == "/settings":
        ok, why = _configure(json.loads(body or b"{}"))
        return (200 if ok else 400), "application/json", _json({"ok": ok, "why": why, "settings": _settings()})

    if method == "POST" and path == "/desktop":
        made = shortcut.desktop()
        return 200, "application/json", _json({"ok": made, "why": "" if made else
                                               lang.t("err.desktop")})

    if method == "POST" and path == "/voicetest":
        # Blocks the one loop for the request, ~0.6 s -- someone is waiting for exactly this.
        said = voice.say(lang.t("voice.test", owner=mode.owner(), name=mode.assistant()), test=True)
        return 200, "application/json", _json({"ok": said})

    if method == "POST" and path == "/mode":
        want = json.loads(body or b"{}")
        # The switches live in mode.py and are loud there. The page only flips them -- it
        # does not keep its own copy, or there would be two answers to "is she muted".
        if "muted" in want:
            mode.mute(bool(want["muted"]))
        if "test" in want:
            mode.test_on(int(want["test"])) if want["test"] else mode.test_off()
        if "deaf" in want:
            mode.deafen(bool(want["deaf"]))
        if "convo" in want:
            mode.convo_on(int(want["convo"])) if want["convo"] else mode.convo_off()
        if "blind" in want:
            mode.blind_on(int(want["blind"])) if want["blind"] else mode.blind_off()
        return 200, "application/json", _json({"mode": mode.line()})

    if method == "POST" and path == "/stop":
        # Not by itself: the window is an input, not a second owner of the clock. The
        # request goes into the same queue, and the clock stops once the turn is done.
        inbox.stop()
        log.info("web", "beenden aus dem fenster angefragt")
        return 200, "application/json", _json({"ok": True})

    if method == "POST" and path == "/cancel":
        # The stop button. Not through the queue: the clock reads it only once the turn
        # is over -- exactly what nobody wants to wait for.
        stopped, hushed = brain.interrupt(), voice.hush()
        log.info("web", f"abbrechen: zug {'gestoppt' if stopped else '-'}, stimme {'aus' if hushed else '-'}")
        return 200, "application/json", _json({"ok": True, "stopped": stopped, "hushed": hushed})

    if method == "POST" and path == "/remember":
        # Same way as a message: into the queue, the clock runs it. A second write pass
        # at the same time would be a second session on the same material.
        inbox.remember_now()
        log.info("web", "gedaechtnis auf zuruf angefragt")
        return 200, "application/json", _json({"ok": True})

    return 404, "text/plain; charset=utf-8", "nichts hier".encode()


def _json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _foreign(method: str, headers: dict[str, str]) -> bool:
    """Did this request come from somewhere other than the window itself?

    Loopback alone is not a boundary: every web page open in the browser can send requests
    to 127.0.0.1. Two checks close that:
      - Host must name this machine and port. A DNS-rebinding page arrives with its own
        host name and could otherwise read /state, the whole chat.
      - Anything but GET must come from this page. A browser always sends Origin on a
        cross-site POST; without this check any page could post to /say or swap in its own
        Discord bot via /settings. No Origin at all is a local program, not a browser page --
        and a local program could read the files directly anyway.
    """
    ours = {f"127.0.0.1:{cfg.PORT}", f"localhost:{cfg.PORT}"}
    if headers.get("host", "").lower() not in ours:
        return True
    origin = headers.get("origin")
    return method != "GET" and origin is not None and origin.lower() not in {f"http://{h}" for h in ours}


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request = (await reader.readline()).decode("latin-1").split()
        if len(request) < 2:
            return
        method, path = request[0], request[1]

        headers: dict[str, str] = {}
        while True:
            raw = await reader.readline()
            if raw in (b"\r\n", b"\n", b""):
                break
            name, _, value = raw.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length") or 0)
        body = await reader.readexactly(length) if length else b""

        if _foreign(method, headers):
            log.warn("web", f"fremde anfrage abgewiesen: {method} {path} host={headers.get('host')!r} "
                            f"origin={headers.get('origin')!r}")
            status, ctype, payload = 403, "text/plain; charset=utf-8", "nicht von hier".encode()
        else:
            status, ctype, payload = _route(method, path, body)
    except Exception:
        log.exception("web", "anfrage fehlgeschlagen")
        status, ctype, payload = 500, "text/plain; charset=utf-8", "kaputt".encode()

    head = (
        f"HTTP/1.1 {status} OK\r\n"
        f"Content-Type: {ctype}\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    )
    try:
        writer.write(head.encode("latin-1") + payload)
        await writer.drain()
    except (ConnectionError, OSError):
        pass  # page reloaded mid-answer; nothing to do and nothing to report
    finally:
        writer.close()


def ui_keys() -> set[str]:
    """Every German text the page passes through tr(), plus the tables it translates at use
    (FEATURES, VIA, VOICE_LABEL, LOOK). A language without an entry for one shows German."""
    page = (system.ROOT / "lumen" / "web.html").read_text(encoding="utf-8")
    keys = set(re.findall(r'tr\("((?:[^"\\]|\\.)*)"', page))
    for table in re.findall(r"const (?:FEATURES|VIA|VOICE_LABEL|LOOK) = (.*?);\n", page, re.S):
        keys |= {s for s in re.findall(r'"((?:[^"\\]|\\.)*)"', table)
                 if s not in ("watch", "open", "discord", "getippt", "gesprochen", "female", "male")}
    return {k.replace('\\"', '"').replace("\\\\", "\\") for k in keys}


def _self_check() -> None:
    """The routing table and the page. A window that answers 200 with an empty body is
    the failure mode that looks like a browser problem for an hour."""
    page = system.ROOT / "lumen" / "web.html"
    assert page.exists(), f"the page is missing at {page}"

    # Everything behind this line queues, and two of those mean it: the stop button
    # would halt her again in the first tick.
    with inbox.scratch():
        _routes()


def _routes() -> None:
    status, ctype, payload = _route("GET", "/", b"")
    assert status == 200 and b"<title>" in payload, "the page does not come back"
    assert "html" in ctype, "the page is served as the wrong type"

    status, _, payload = _route("GET", "/state", b"")
    state = json.loads(payload)
    assert status == 200, "state has to answer"
    for key in ("chat", "thoughts", "mode", "settings", "gesehen", "poll_ms",
                "denkt", "acts", "spricht", "ohr"):
        assert key in state, f"the page needs {key} and it is not in the state"
    secret = system.secret("AZURE_SPEECH_KEY")
    assert not (secret and secret in payload.decode()) and "key" not in state["settings"], \
        "the key never leaves the machine's .env, not even to the window"
    assert _route("GET", "/preact.js", b"")[0] == 200, "without preact.js the page stays blank"
    assert _steps([{"tool": "mcp__lumen__open", "on": "Spotify"}, {"tool": "ToolSearch", "on": "x"}]) == \
        [{"tool": "open", "verb": lang.t("verb.open"), "on": "Spotify", "at": ""}], "her tools read in plain words"

    # The uploads folder is the only one the window serves.
    assert _route("GET", "/file/..%5C..%5C.env", b"")[0] == 404, "a file outside the uploads"
    assert _route("GET", "/file/..", b"")[0] == 404, "the uploads folder's parent"
    assert _route("POST", "/upload?name=x.png", b"")[0] == 413, "an empty upload must not land"

    # The region becomes a host name: nothing but letters and digits may reach it.
    for bad in ({"azure_region": "evil.example/x#"}, {"azure_key": "abc\nX=1"}, {"voice": "robot"},
                {"assistant": "Hey du"}, {"assistant": 7}, {"discord_user": "abc"},
                {"discord_token": "kurz"}, {"mic": "Gibt es nicht 123"}, {"language": "xx"},
                {"whisper_model": "../../evil"}):
        assert _route("POST", "/settings", json.dumps(bad).encode())[0] == 400, f"let through: {bad}"

    assert _route("GET", "/nope", b"")[0] == 404, "an unknown path must not answer 200"
    for code, module in lang.LANGS.items():
        if code != "de":  # German is the page's source text
            gaps = ui_keys() - set(module.UI)
            assert not gaps, f"{code}: the window shows these in German: {sorted(gaps)[:5]}"
    assert not json.loads(_route("POST", "/say", b'{"text":"   "}')[2])["ok"], \
        "blank input has to be dropped, not queued"

    assert cfg.HOST == "127.0.0.1", "the window must not listen beyond this machine"
    here = {"host": f"127.0.0.1:{cfg.PORT}"}
    assert not _foreign("GET", here) and not _foreign("POST", {**here, "origin": f"http://127.0.0.1:{cfg.PORT}"})
    assert not _foreign("POST", here), "a local program sends no Origin and may post"
    assert _foreign("POST", {**here, "origin": "https://evil.example"}), "a foreign page must not post"
    assert _foreign("GET", {"host": f"evil.example:{cfg.PORT}"}), "DNS rebinding must not read the chat"
    assert _foreign("GET", {}), "no Host header, no answer"
    assert _route("POST", "/stop", b"")[0] == 200, "the stop button needs a route"
    assert json.loads(_route("POST", "/cancel", b"")[2]) == {"ok": True, "stopped": False, "hushed": False}, \
        "the stop button with nothing running must stop nothing"
    assert _route("POST", "/remember", b"")[0] == 200, "the memory button needs a route"
