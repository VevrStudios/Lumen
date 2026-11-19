"""Write the owner a Discord DM, of her own accord -- through the owner's own bot.

The counterpart to `speak`, and deliberately not the same: `speak` is loud and therefore
hangs on the attention gap. A DM is read whenever, it interrupts nothing -- so muted
means "cannot talk", not "cannot reach". Only with the "Discord" switch on (guard).
"""

from typing import Any

from claude_agent_sdk import tool

from lumen import dm, lang, log, thread


@tool(
    "schreiben",
    "tool.schreiben",
    {"text": str},
)
async def schreiben(args: dict[str, Any]) -> dict[str, Any]:
    text = args["text"]
    if not await dm.send(text):
        return {"content": [{"type": "text", "text": lang.t("reply.dm_failed")}], "is_error": True}
    # In denselben Faden wie `speak`: was sie schreibt, steht auch im Fenster.
    thread.note("", text, via="discord")
    log.info("dm", f"geschrieben: {text}")
    return {"content": [{"type": "text", "text": lang.t("reply.dm_sent")}]}


TOOL = schreiben
