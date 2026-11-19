"""Look at what he is doing: the window in front, since when, idle time, what is open,
the day so far -- and where the time went since she last looked.

Hers to call, not pushed at her (09.11.2026, his design): she gets a nudge and decides
whether to look, so he never knows when she does. Until then every window switch came to
her as a message, measured on 08.11.2026 about 160 a day.
"""

from typing import Any

from claude_agent_sdk import tool

from lumen import log, observe


@tool(
    "hinsehen",
    "tool.hinsehen",
    {},
)
async def hinsehen(args: dict[str, Any]) -> dict[str, Any]:
    text = observe.glance()
    log.info("act", "hinsehen")
    return {"content": [{"type": "text", "text": text}]}


TOOL = hinsehen
