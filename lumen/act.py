"""What she can do, and the boundary in front of it.

Two jobs that belong together and nowhere else:

  - collect `actions/` into one MCP server, so what lies in that folder is what she can
    reach and nothing else does -- minus what the settings switched off;
  - answer, for every tool call she makes, whether it goes through.

The second one is rule 4, and it happens in exactly one place -- see `wire()` for
why the obvious second place turned out to be decorative.
"""

import dataclasses
import importlib
import pkgutil
from typing import Any

import claude_agent_sdk as sdk

from lumen import lang, log, mode, observe
from lumen import store
from lumen.actions import speak as speak_action
from lumen.config import guard, system

SERVER = "lumen"  # tools reach her as mcp__lumen__<name>

_tools: list[Any] = []


def start() -> None:
    """Read `actions/` once. Modules are imported by hand elsewhere in this project;
    actions are data, and a folder of them is a list, not a boot order."""
    global _tools
    _tools = []
    import lumen.actions as package

    for found in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"lumen.actions.{found.name}")
        if not hasattr(module, "TOOL"):
            log.warn("act", f"actions/{found.name}.py has no TOOL, skipped")
            continue
        _tools.append(module.TOOL)
        _tools.extend(getattr(module, "EXTRA_TOOLS", []))
    log.info("act", f"{len(_tools)} actions: {', '.join(t.name for t in _tools)}")


def _switched_on(features: dict[str, bool]) -> list[Any]:
    """The actions whose switch is on. An action without a switch is always there."""
    return [t for t in _tools if features.get(guard.FEATURE_OF.get(t.name, ""), True)]


def server(features: dict[str, bool]) -> sdk.McpSdkServerConfig:
    """The actions she may use, each described in her language. An action's `description` in
    its file is the key into lang/ -- the words are chosen when the session is built."""
    tools = [dataclasses.replace(t, description=lang.t(t.description)) for t in _switched_on(features)]
    return sdk.create_sdk_mcp_server(name=SERVER, version="1.0.0", tools=tools)


def offered(features: dict[str, bool]) -> list[str]:
    """The tool names she is allowed to see. Built from the folder and from the free
    list, never typed out a second time -- v1 kept a tool list in the prompt beside a
    folder of actions and needed a singleton to stop the two drifting apart."""
    return (sorted(guard.FREE_TOOLS | guard.WEB_TOOLS)
            + [f"mcp__{SERVER}__{t.name}" for t in _switched_on(features)])


def _state(writing: str | None = None) -> dict[str, Any]:
    """What the guard needs to know about the world right now.

    Gathered here so `guard.may` stays a pure decision and can be checked without a
    daemon: the whole permission table is testable with a dict.
    """
    turn = store.read("turn", {}) or {}
    return {
        "features": mode.settings()["features"],
        "lang": lang.code(),
        "muted": mode.muted(),
        "blind": mode.blind(),
        "since_spoken_s": speak_action.since_spoken_s(),
        "call": observe.on_call(),
        "last_user_at": turn.get("last_user_at"),
        # Who started the running turn -- "owner", "wecker" or "system".
        "by": turn.get("by"),
        # Only set in the write pass, and then the path itself. See wire().
        "writing": writing,
    }


def standing(by: str = "system") -> str:
    """One line saying whether `speak` would go through in the turn about to start.

    `by` is that turn's starter: the file still names the last one, and an alarm lifts the
    gap that an observation would not.

    Rides with the message, never in the system prompt: this changes every turn, and a
    changing word in the cached prefix throws the cache away on every event.
    """
    ok, why = guard.may(f"mcp__{SERVER}__speak", {"text": ""}, {**_state(), "by": by})
    return lang.t("act.standing_ok") if ok else lang.t("act.standing_no", why=why)


def _hook(writing: str | None):
    """The PreToolUse hook for one wiring. A closure, so the write path travels with the
    hook rather than sitting in a module variable that two sessions would share."""

    async def pre_tool_use(payload: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        tool, args = payload.get("tool_name", "?"), payload.get("tool_input", {})
        ok, why = guard.may(tool, args, _state(writing))
        log.info("guard", f"{'allow' if ok else 'DENY '} {tool}: {why}")
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if ok else "deny",
                "permissionDecisionReason": why,
            }
        }

    return pre_tool_use


def wire(writing: str | None = None) -> dict[str, Any]:
    """The options this module owns, for brain.py to merge in.

    A PreToolUse hook and nothing else. `can_use_tool` was here too once, and the SDK said
    out loud that an allowed_tools entry shadows it:

        CanUseToolShadowedWarning: can_use_tool will not be invoked for: Glob, Grep,
        Read, mcp__<server>__speak. ... To gate every tool call, use a PreToolUse hook.

    A decoration that reads like a safeguard is worse than none, because the next person
    counts two and there is one (B2).

    Two shapes, and the difference is the point. The write pass gets Write/Edit and
    **no** actions at all -- it files, it does not talk. A tool that is never wired in
    cannot be refused wrongly and cannot be argued with; the guard is the second barrier
    behind that, not the first.
    """
    hooks = {"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[_hook(writing)])]}
    if writing:
        # `tools`, not only `allowed_tools`: every built-in Claude Code ships otherwise
        # goes out with its full schema on every step (measured: 27 built-ins, 132k chars).
        files = sorted(guard.FREE_TOOLS | guard.MEMORY_TOOLS)
        return {"tools": files, "allowed_tools": files, "hooks": hooks}
    features = mode.settings()["features"]
    return {
        "mcp_servers": {SERVER: server(features)},
        "tools": sorted(guard.FREE_TOOLS | guard.WEB_TOOLS),
        "allowed_tools": offered(features),
        "hooks": hooks,
    }


def _self_check() -> None:
    """The folder is the truth, so an action that fails to load is a capability that
    silently is not there."""
    guard._self_check()

    start()
    assert _tools, "no actions loaded -- the folder is empty or nothing exposes TOOL"
    import lumen.actions as package

    for found in pkgutil.iter_modules(package.__path__):
        check = getattr(importlib.import_module(f"lumen.actions.{found.name}"), "_self_check", None)
        if check:
            check()
    named = {t.name for t in _tools}
    for t in _tools:  # every action's description is a key both languages have
        assert lang.t(t.description, "de") and lang.t(t.description, "en"), t.name
    assert set(guard.FEATURE_OF) <= named, f"a switch for an action that does not exist: {set(guard.FEATURE_OF) - named}"

    defaults = mode.FEATURES
    names = offered(defaults)
    assert "mcp__lumen__speak" in names, f"speak did not make it into the offer: {names}"
    assert "Read" in names and "Bash" not in names and "Agent" not in names, "the free list is the free list"
    assert "mcp__lumen__screenshot" not in names, "watching starts off -- no screenshot on offer"
    assert "mcp__lumen__screenshot" in offered({**defaults, "watch": True}), "switched on, it is offered"

    opts = wire()
    assert "can_use_tool" not in opts, "shadowed by allowed_tools -- B2, do not put it back"
    assert set(opts["allowed_tools"]) == set(offered(mode.settings()["features"])), "one place for the offer"
    assert "Write" not in opts["allowed_tools"], "the conversation must not be able to write"
    assert "WebSearch" in opts["allowed_tools"], "the conversation can search the web"

    filing = wire(str(system.MEMORY))
    assert "Write" in filing["allowed_tools"] and filing["tools"] == filing["allowed_tools"]
    assert "WebSearch" not in filing["allowed_tools"], "the write pass cannot search (not even offered)"
    assert "mcp_servers" not in filing, "filing does not speak -- no actions in the write pass"
