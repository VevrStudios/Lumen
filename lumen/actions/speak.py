"""Reach him unprompted.

Only for that. When he asks something, her answer comes back through the turn itself
and needs no action -- this is the one way to start a conversation he did not start.

So the gate on it is narrow on purpose. While he is in a call she still hears him and
still answers; what she may not do is interrupt with something of her own. Nothing here
ever silences a reply, because a reply never comes through here.

That is also why the whole observation loop can stay quiet for free: an event produces a
turn, the turn is thinking, and unless she calls this, nothing leaves the process.
"""

from datetime import datetime, timezone
from typing import Any

from claude_agent_sdk import tool

from lumen import lang, log, store, thread, voice

STATE = "speak"


def state() -> dict[str, Any]:
    return store.read(STATE, {}) or {}


def since_spoken_s() -> float | None:
    """Seconds since she last spoke unprompted, or None if she never has."""
    last = state().get("last")
    if not last:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()


@tool(
    "speak",
    "tool.speak",
    {"text": str},
)
async def speak(args: dict[str, Any]) -> dict[str, Any]:
    text = args["text"]

    # Into the same record as an ordinary exchange -- what she says of her own accord is
    # part of the conversation, not a separate channel, and it has to survive a restart
    # for the same reason his half does. No `asked`, because nobody asked.
    thread.note("", text)
    log.info("speak", text)

    # Und laut. Ungefragt heisst gesprochen: im Fenster stuende sie sonst da und wartete
    # darauf, dass er hinsieht -- was genau der Fall ist, gegen den es `speak` gibt.
    # Der Text bleibt auch dann stehen, wenn Azure weg ist; `say` faellt still zurueck.
    voice.say(text)

    store.write(STATE, {**state(), "last": datetime.now(timezone.utc).isoformat()})
    return {"content": [{"type": "text", "text": lang.t("reply.said")}]}


TOOL = speak
