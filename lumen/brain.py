"""The one exit to the model.

Every Claude call in this project goes through here. One place knows about the session,
the system prompt and what a turn cost -- and no second model ever sits between her and
what she reads.

Runs on the Claude Agent SDK, which authenticates through the Claude Code login and so
against the subscription. An ANTHROPIC_API_KEY in the environment would silently move
every call onto the API balance instead.
"""

import asyncio
import contextlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import claude_agent_sdk as sdk
from claude_agent_sdk.types import SystemPromptFile

from lumen import act, lang, log, mode, store, thread, voice
from lumen.config import guard, model, system
from lumen.config import observe as obscfg

# The conversation. One session, lazily connected: booting must not require the network.
_client: sdk.ClaudeSDKClient | None = None

# The settings the open session was built for. A switch in the window changes which tools
# exist and what the system prompt says, so a session built for other settings is closed
# before the next turn instead of being told about it per turn.
_built: Any = None

# What she is doing this very moment, for the window. In the process only, and on
# purpose: it is stale the instant the turn ends and worthless after a restart.
_activity: dict[str, Any] = {"busy": False, "job": "", "since": None, "steps": []}
# The interrupt in flight, held so the loop does not drop it half-sent.
_stopping: asyncio.Task | None = None
# Each of her turns once it ended, with every tool call: the window's activity column.
ACTS = "acts"

# The persona is cut in two at its language's REGISTER mark. Everything before it is who
# she is and goes first; from the mark on is her register -- the sample utterances -- and
# goes behind the memory block, for the reason "mech.after_memory" is there: the last thing
# she reads wins. Measured on the original: a form rule only in the persona did not carry.


def start() -> None:
    """Nothing to do at boot. Connecting happens on the first question, so a machine
    with no network still comes up and still logs why it cannot think."""
    system.MEMORY.mkdir(parents=True, exist_ok=True)


def _memory() -> str:
    """The whole memory folder as one string. Flat and small by design: every note rides
    in the prompt, so she never claims not to know what is written down."""
    return "\n\n".join(
        f"--- {path.name} ---\n{path.read_text(encoding='utf-8')}"
        for path in sorted(system.MEMORY.glob("*.md"))
    )


def _spell_s(seconds: int) -> str:
    minutes = seconds // 60
    if minutes < 60:
        return lang.t("time.minutes", n=minutes)
    return lang.t("time.hours" if minutes >= 120 else "time.hour", n=minutes // 60)


def _mechanics(features: dict[str, bool], speaking: bool) -> str:
    """How she runs, with the numbers taken from the modules that hold them -- and only
    the parts whose switch is on. Nothing here is typed twice."""
    blocks = [lang.t("mech.block"), lang.t("mech.voice_on" if speaking else "mech.voice_off")]
    if features["watch"]:
        blocks.append(lang.t("mech.watch"))
    if features["discord"]:
        blocks.append(lang.t("mech.discord"))
    return "\n\n".join(blocks).format(
        owner=mode.owner(), tick=_spell_s(system.TICK_S), gap=_spell_s(guard.SPEAK_GAP_S),
        nudge=_spell_s(obscfg.QUIET_S))


def _system_prompt() -> str:
    """Who she is, how she runs, what she remembers -- and then one page on form.

    All of it is stable, which is the point: it is the cached prefix, and anything that
    changes per turn belongs in the message instead.

    The order is not cosmetic. The last blocks sit **after** the memory because the last
    thing she reads wins, and notes are written in exactly the style she must not talk in.
    """
    persona = lang.persona().replace("{owner}", mode.owner()).replace("{name}", mode.assistant())
    who, mark, register = persona.partition(lang.pack().REGISTER)
    owner = mode.owner()
    return (f"{who.rstrip()}\n\n{_mechanics(mode.settings()['features'], voice.audible())}"
            f"\n\n{lang.t('mech.memory_head')}\n\n"
            f"{lang.t('mech.memory', memory=system.MEMORY, owner=owner)}\n\n{_memory()}"
            f"\n\n{lang.t('mech.after_memory', owner=owner)}\n\n{mark}{register}".rstrip())


def _prompt_file(name: str, text: str) -> SystemPromptFile:
    """A prompt as a file on disk, never as a string in the options.

    The SDK puts a plain string straight onto the command line, and Windows caps a
    command line at 32,767 characters. Past the limit the process fails to start and the
    SDK reports it as CLINotFoundError -- an error about a binary that is sitting right
    there (B1). The persona alone is a third of that; the memory grows.
    """
    return {"type": "file", "path": str(store.write_text(name, text))}


def _options(job: str, writing: str | None = None) -> sdk.ClaudeAgentOptions:
    name, effort = model.job(job)
    if writing:
        # Filing needs the brief and the notes -- not who she is, how she talks or when she
        # may speak. Measured on the original: persona and mechanics rode along on every
        # step of the pass, unread.
        head = lang.t("remember.where", memory=system.MEMORY)
        prompt = _prompt_file("filing_prompt", f"{head}\n\n{_memory() or lang.t('mech.no_notes')}")
    else:
        prompt = _prompt_file("system_prompt", _system_prompt())
    return sdk.ClaudeAgentOptions(
        model=name,
        effort=effort,
        system_prompt=prompt,
        cwd=system.ROOT,
        # Load NOTHING from ~/.claude or the project's .claude. Without this she would
        # inherit the machine owner's own Claude Code setup -- CLAUDE.md, hooks, skills --
        # as if they were instructions to her.
        setting_sources=[],
        # Tools, the offer and the permission check come from act.py. Nothing about what
        # she may do is decided here -- this module is the exit to the model, not the
        # boundary in front of it.
        **act.wire(writing),
        # Anything the guard did not pre-approve is denied rather than prompted: a prompt
        # nobody can answer is a hang, not a safeguard.
        permission_mode="dontAsk",
        # Every tool with its description from the start, none loaded on demand: deferred,
        # she saw only the names and never read a tool's "when" (measured on the original).
        #
        # Her own model for the web tools' reading pass, not Haiku -- a second model reading
        # for her is rule 3.
        #
        # No auto memory: Claude Code would paste the machine owner's dev notes in.
        # No background tasks (B23): a subagent answering into a turn nobody reads.
        # No claude.ai connectors: the login hands every session the owner's Gmail, Drive,
        # Calendar ... -- measured on the original, ~75k tokens per call, all denied.
        env={"ENABLE_TOOL_SEARCH": "auto:100", "ANTHROPIC_DEFAULT_HAIKU_MODEL": name,
             "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
             "ENABLE_CLAUDEAI_MCP_SERVERS": "false"},
        # The CLI echoes each query back into the stream; `_collect` reads from there on (B23).
        extra_args={"replay-user-messages": None},
        # A screenshot comes back through the stream as base64, and the SDK stops reading
        # a line at 1 MB. The API takes 5 MB per image.
        max_buffer_size=32 * 1024 * 1024,
    )


def _measure(result: sdk.ResultMessage, job: str) -> None:
    """Log what a turn cost, in tokens. Rule 1 asks whether the effort fits the job,
    which is unanswerable without numbers. ResultMessage.total_cost_usd is the price of
    the whole SESSION, not of this turn -- the trap v1 fell into four times.

    input_tokens alone reads as 2 on a turn that moved 127k: the system prompt is a stable
    prefix and lands in cache_read after the first turn.
    """
    use = result.usage or {}
    log.info(
        "brain",
        f"{job}: in {use.get('input_tokens', 0)} "
        f"+cache {use.get('cache_read_input_tokens', 0)} "
        f"(wrote {use.get('cache_creation_input_tokens', 0)}) "
        f"out {use.get('output_tokens', 0)} "
        f"in {result.duration_ms} ms",
    )


def activity() -> dict[str, Any]:
    """A copy of what she is doing right now. The window reads it on every poll."""
    return {**_activity, "steps": list(_activity["steps"])}


def _target(args: dict[str, Any]) -> str:
    """What a tool call is aimed at, shortened to something a person can read."""
    raw = str(args.get("file_path") or args.get("pattern") or args.get("path")
              or args.get("query") or args.get("url") or args.get("text") or args.get("exe") or "")
    raw = raw.removeprefix("https://").removeprefix("http://")
    for base in (str(system.MEMORY), str(system.ROOT)):
        raw = raw.replace(base + "\\", "").replace(base.replace("\\", "/") + "/", "")
    return raw[:120]


def _refused(result: sdk.ResultMessage) -> bool:
    """A safety stop ends the turn without is_error, so checking only that makes a
    refusal read as her saying nothing."""
    return result.stop_reason == "refusal"


async def _collect(client: sdk.ClaudeSDKClient, job: str, asked: str = "",
                   label: str = "", sent: str | None = None) -> str:
    """Everything she says in one turn, plus what it cost. Shared by both callers so a
    fix to the measurement lands once -- v1 had four of these.

    Also the one place that sees her tool calls as they happen, so the window's "what is
    she reading" comes from here and nowhere else.

    `sent` is the text just queried into a long-lived session. Everything before the CLI
    echoes it back is left over from an earlier turn and is skipped (B23: one stale turn
    in the stream and every answer after it went to the wrong question, until restart).
    """
    _activity.update(busy=True, job=job, since=datetime.now().isoformat(timespec="seconds"),
                     steps=[], refused=False, stopped=False, label=label, client=client)
    said: list[str] = []
    steps: list[dict[str, str]] = []
    stale = sent is not None
    try:
        # receive_response() ends at the first result, a stale one too -- so read again
        # until the turn that answers `sent` has ended.
        while True:
            async for message in client.receive_response():
                if stale:
                    if isinstance(message, sdk.UserMessage) and message.content == sent:
                        stale = False
                    elif isinstance(message, sdk.ResultMessage):
                        log.warn("brain", f"{job}: alter zug im strom uebersprungen")
                    continue
                if isinstance(message, sdk.AssistantMessage):
                    for block in message.content:
                        if isinstance(block, sdk.TextBlock):
                            said.append(block.text)
                        elif isinstance(block, sdk.ToolUseBlock):
                            steps.append({"tool": block.name, "on": _target(block.input or {}),
                                          "at": datetime.now().strftime("%H:%M")})
                            _activity["steps"] = steps[-16:]
                elif isinstance(message, sdk.ResultMessage):
                    _measure(message, job)
                    if _activity.get("stopped"):
                        log.info("brain", f"{job}: abgebrochen ({message.terminal_reason})")
                    elif message.is_error:
                        log.error("brain", f"{job} failed: {message.errors or message.subtype}")
                    if _refused(message):
                        _activity["refused"] = True
                        log.error("brain", f"{job} REFUSED by a safety stop, asked: {asked[:200]!r}")
            if not stale:
                break
    finally:
        store.append(ACTS, {"at": _activity["since"], "job": job, "label": label,
                            "steps": steps, "testing": mode.testing()}, keep=500)
        _activity.update(busy=False, steps=[], done=steps)
    return "\n".join(said).strip()


async def once(text: str, job: str, writing: str | None = None) -> str:
    """One turn in a session of its own, opened and closed around it -- the write pass.

    Not a second driver: same module, same options builder, same measurement. What it
    adds is a turn with other tools that must not inherit the conversation nor leave
    anything in it.
    """
    client = sdk.ClaudeSDKClient(options=_options(job, writing))
    await client.connect()
    log.info("brain", f"{job} on {model.job(job)[0]}")
    try:
        await client.query(text)
        return await _collect(client, job, text)
    finally:
        try:
            await client.disconnect()
        except Exception as why:  # B6: a dead process cannot be told to go away
            log.warn("brain", f"{job}: sitzung war schon weg: {why}")


def _setup() -> Any:
    """What the session's prompt and tools depend on, besides the memory."""
    return mode.settings(), voice.audible()


async def ask(text: str, job: str = "converse", von: str = guard.OWNER, context: str = "",
              via: str = "", label: str = "", deep: bool = False, _again: bool = True) -> str:
    """Put something to her and return what she says. The only way in.

    `von` says who this turn came from -- the owner, an alarm, or "system" for the clock.
    It is not decoration: the guard lets only the owner set alarms, and only this function
    can tell a message apart from an observation.

    `context` rides with the turn but never enters the thread -- what the clock saw in
    the same tick is background to a message, not something that was said.
    `via` is the entrance it came through, kept with the turn for the window.
    `deep` puts this one turn on Opus (the window's button) and switches back after it.
    """
    global _client, _built

    # What goes into the thread is the message, not the message plus the notes this code
    # is about to stick on it.
    spoken = text

    turn = store.read("turn", {}) or {}
    turn["by"] = von
    if von == guard.OWNER:
        turn["last_user_at"] = datetime.now().isoformat()
    store.write("turn", turn)

    # A switch was flipped in the window: tools and prompt no longer match this session.
    if _client is not None and _built != _setup():
        log.info("brain", "einstellungen geaendert -- neue sitzung")
        await close()

    fresh = _client is None
    if fresh:
        _built = _setup()
        _client = sdk.ClaudeSDKClient(options=_options(job))
        await _client.connect()
        log.info("brain", f"session open on {model.job(job)[0]}")

    # Per-turn state never goes in the system prompt: that is the cached prefix, and a
    # changing word in it throws the whole prefix away each time.
    if context:
        text = f"{context}\n\n{text}"

    # Only into a session's first message. After that the history is in the conversation.
    if fresh and (back := thread.recap()):
        text = f"{back}\n\n{text}"

    if standing := mode.line():
        text = f"[{standing}]\n\n{text}"

    try:
        if deep:
            await _client.set_model(model.DEEP)
        try:
            await _client.query(text)
            if von == guard.OWNER:
                label = lang.t("label.answer", owner=mode.owner()) + (lang.t("label.opus") if deep else "")
            answer = await _collect(_client, job, spoken, label=label or lang.t("label.look"), sent=text)
        finally:
            if deep:
                with contextlib.suppress(Exception):  # a dead session is replaced below anyway
                    await _client.set_model(model.job(job)[0])
    except sdk.CLIConnectionError as why:
        # B6: the claude process can die without anyone noticing -- a standby, a crash, a
        # kill. Without this the dead client stays and every turn after fails the same
        # way, for hours. Drop it and ask once more; the retry also gets the recap.
        if not _again:
            raise
        log.warn("brain", f"sitzung tot, verbinde neu: {why}")
        await close()
        return await ask(spoken, job, von, context, via, label, deep, _again=False)

    # The stop button: no answer -- not in the window, not spoken. The message stays, in
    # the session and in the thread.
    stopped = _activity.get("stopped", False)
    if stopped:
        answer = ""

    # B22: a refusal sticks to the session. Drop it, the next turn opens fresh -- and the
    # refused turn stays out of that fresh session's recap.
    refused = _activity.get("refused", False)
    if refused:
        await close()

    # The thread, and here: `ask` is the one place every turn passes. Only what came from
    # the owner -- observations go to `thought`, and both in one file would be the same
    # turn twice.
    if von == guard.OWNER:
        thread.note(spoken, answer, refused=refused, via=via, stopped=stopped, deep=deep)
    return "" if refused and von != guard.OWNER else answer


def interrupt() -> bool:
    """The stop button: end the turn running in the conversation session, with no answer.

    Interrupt, not close -- the session keeps the message and whatever she had so far.
    Only her conversation: a write pass stopped halfway would have filed half an evening.
    Not awaited: the window's routes are synchronous, and the turn it ends is the one
    awaiting the stream right now; `_collect` then sees the result as usual.
    """
    global _stopping
    if _client is None or not _activity["busy"] or _activity.get("client") is not _client:
        return False
    _activity["stopped"] = True
    _stopping = asyncio.get_running_loop().create_task(_interrupt(_client))
    return True


async def _interrupt(client: sdk.ClaudeSDKClient) -> None:
    try:
        await client.interrupt()
    except Exception as why:  # a dead session ends its turn anyway, through CLIConnectionError
        log.warn("brain", f"abbrechen ging nicht durch: {why}")


async def close() -> None:
    """End the session. Always succeeds at the one thing that matters: afterwards there
    is no client. B6: after a standby the process is dead, and disconnect() raises --
    drop it first, then try to be polite."""
    global _client
    if _client is None:
        return
    dead, _client = _client, None
    try:
        await dead.disconnect()
    except Exception as why:
        log.warn("brain", f"sitzung war schon weg: {why}")
    log.info("brain", "session closed")


def _self_check() -> None:
    """The system prompt is the whole point of this module, and it is assembled from
    files and switches that can change without anyone noticing."""
    for code in lang.LANGS:
        mode.configure(language=code)
        prompt = _system_prompt()
        assert prompt.startswith(f"# {mode.assistant()}"), f"{code}: the persona has to come first"
        assert "{owner}" not in prompt and "{name}" not in prompt and mode.owner() in prompt, f"{code}: names"
        assert str(system.MEMORY) in prompt and _memory() in prompt, f"{code}: the whole memory folder rides along"
        # The order is the rule: the last thing she reads wins, and notes are written in the
        # style she must not talk in.
        after = lang.t("mech.after_memory", owner=mode.owner())
        assert prompt.index(after) > prompt.index(lang.t("mech.memory_head")), f"{code}: form block after memory"
        register = lang.pack().REGISTER
        assert prompt.count(register) == 1 and prompt.index(register) > prompt.index(after), f"{code}: register last"
    mode.configure(language="")

    off = {f: False for f in mode.FEATURES}
    on = {f: True for f in mode.FEATURES}
    assert lang.t("mech.watch").split("\n")[0] not in _mechanics(off, False), \
        "a block about a switched-off feature invites her to try it anyway"
    assert lang.t("mech.watch").split("\n")[0] in _mechanics(on, True)
    assert lang.t("mech.discord").split("\n")[0] in _mechanics(on, True)
    assert lang.t("mech.discord").split("\n")[0] not in _mechanics(off, True)
    assert _mechanics(off, False) != _mechanics(off, True), "voice on and off must read differently"
    assert "{" not in _mechanics(on, True), "an unfilled slot left in the mechanics block"
    assert _spell_s(guard.SPEAK_GAP_S) in _mechanics(off, False), "the gap does not come from the code"
    assert _spell_s(obscfg.QUIET_S) in _mechanics(on, False), "the nudge does not come from the code"

    filing = _options("remember", writing=str(system.MEMORY))
    filed = Path(filing.system_prompt["path"]).read_text(encoding="utf-8")
    assert str(system.MEMORY) in filed and lang.pack().REGISTER not in filed, "filing runs on the brief, not on her"
    assert filing.tools == filing.allowed_tools, "only what it may use is offered at all"
    assert filing.env.get("ENABLE_CLAUDEAI_MCP_SERVERS") == "false"

    opts = _options("converse")
    assert opts.setting_sources == [], "she must not inherit the owner's Claude Code setup"
    assert "mcp__lumen__speak" in opts.allowed_tools and opts.hooks
    assert opts.env.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY") == "1"
    assert opts.env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == opts.model, "rule 3: no Haiku reading for her"
    assert opts.max_buffer_size >= 7 * 1024 * 1024, "a 5 MB image is ~7 MB as base64 in the stream"
    assert opts.extra_args == {"replay-user-messages": None}, "without the echo nothing marks a turn's start"
    assert opts.system_prompt["type"] == "file", "B1: a prompt string blows the Windows command line"
    assert not opts.agents, "no subagents in the public version"

    # B6: close() on a dead process must still leave no client behind. The fake raises
    # without suspending, so one send() runs the coroutine to the end -- this check runs
    # inside the daemon's own loop, where asyncio.run() is not available.
    global _client

    class _Dead:
        async def disconnect(self) -> None:
            raise sdk.CLIConnectionError("exit code: 129")

    kept, _client = _client, _Dead()
    step = close()
    try:
        step.send(None)
    except StopIteration:
        pass
    assert _client is None, "close() on a dead process left the dead client behind (B6)"
    assert activity()["busy"] is False, "idle must not read as busy"
    assert interrupt() is False, "nothing running, nothing to stop"
    _client = kept

    def _result(stop: str | None) -> sdk.ResultMessage:
        return sdk.ResultMessage(subtype="success", duration_ms=0, duration_api_ms=0,
                                 is_error=False, num_turns=1, session_id="", stop_reason=stop)

    assert _refused(_result("refusal")) and not _refused(_result("end_turn"))

    # B23: a turn left in the stream answers the wrong question. The fake replays it: the
    # stale turn and its result, then the echo, then the answer.
    class _Behind:
        def __init__(self) -> None:
            self.turns = [
                [sdk.AssistantMessage(content=[sdk.TextBlock("alt")], model=""), _result("end_turn")],
                [sdk.UserMessage(content="neu"), sdk.AssistantMessage(content=[sdk.TextBlock("richtig")], model=""),
                 _result("end_turn")],
            ]

        async def receive_response(self):
            for message in self.turns.pop(0):
                yield message

    acts = store.tail(ACTS, 500)
    step = _collect(_Behind(), "converse", sent="neu")
    with log.hushed():
        try:
            step.send(None)
        except StopIteration as done:
            answer = done.value
    assert answer == "richtig", "a stale turn in the stream must not answer this one (B23)"
    # The fake turn wrote itself into the activity column; take it back out.
    store.write_text(ACTS, "".join(json.dumps(a, ensure_ascii=False) + "\n" for a in acts), suffix=".jsonl")
    _activity.update(busy=False, refused=False, stopped=False, client=None)
