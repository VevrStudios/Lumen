"""File what was said into memory now, instead of leaving it all to the next start.

Only marks it: the pass is a session of its own, and it cannot run inside her turn. The
clock runs it once the turn is over and then starts her next session fresh, with the new
index (rule 2: the clock owns what happens next). The window's button takes the same way.
"""

from typing import Any

from claude_agent_sdk import tool

from lumen import inbox, lang, log


@tool(
    "einsortieren",
    "tool.einsortieren",
    {},
)
async def einsortieren(args: dict[str, Any]) -> dict[str, Any]:
    inbox.remember_now()
    log.info("act", "einsortieren vorgemerkt")
    return {"content": [{"type": "text", "text": lang.t("reply.filed")}]}


TOOL = einsortieren
