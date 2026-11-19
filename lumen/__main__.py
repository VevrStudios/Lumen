"""Boot and the one clock.

Every module is imported and started here, by hand, in this order. There is no
discovery and no registry. A timer or thread anywhere else is a bug, not a feature:
two clocks drift against each other and the failures are not reproducible.

The loop is async because the session to the model is, and that session has to outlive
a single turn. It is still one clock -- one loop, one owner of "what happens next".
"""

import asyncio

from lumen import act, brain, dm, ear, inbox, lang, log, mode, observe, remember, shortcut, store, thread, voice, web
from lumen.actions import speak, wecker
from lumen.config import guard, model
from lumen.config import observe as obscfg
from lumen.config import system


def _self_check() -> None:
    """Every invariant that would otherwise fail hours into a run.

    Runs on every boot: asserts are cheap, and a daemon that comes up with a broken
    config is worse than one that refuses to come up.

    Two wrappers, both so a check tests the code and not the machine it runs on:
    `log.hushed` keeps the checks out of the log, `mode.off` keeps the switches and
    settings on disk out of the checks (B9).
    """
    with log.hushed(), mode.off():
        _checks()


def _checks() -> None:
    log._self_check()
    lang._self_check()
    assert system.TICK_S > 0, "the clock has to advance"
    model._self_check()
    store._self_check()
    mode._self_check()
    observe._self_check()
    thread._self_check()
    remember._self_check()
    web._self_check()
    inbox._self_check()
    voice._self_check()
    dm._self_check()
    shortcut._self_check()
    ear._self_check()
    act._self_check()
    brain._self_check()


async def _tick(n: int, heard: tuple[str, str, bool] | None) -> None:
    """One turn of the clock.

    Three things can start it: a message from the window, a sentence into the microphone,
    or the observer seeing a change. None of them runs itself -- both entrances only
    queue, and this is still the one place that decides a turn happens.

    An observation goes to her as thinking: her text is logged, not spoken. If she wants
    to reach anyone she has to call `speak`, and that goes through the guard.
    """
    # On request from the window. Here and not in the queue: the write pass is a turn like
    # any other, and the clock decides that one happens. Then a fresh session with the new
    # notes, instead of a history that grows all evening and leaves the persona far behind.
    if heard is inbox.REMEMBER:
        log.info("clock", f"tick {n}: gedaechtnis auf zuruf")
        if await remember.run():
            await brain.close()
        return

    what, now = observe.changes()
    # Watching switched off: the machine is still read (a wake-up from standby matters
    # below), but nothing it shows wakes her.
    watching = mode.feature("watch")
    if not watching:
        what = []
    said, von, deep = heard if isinstance(heard, tuple) else (None, "", False)

    # Woken up: the old session is wrong twice. In content, because a whole previous day
    # is in it -- and technically, because after hours in standby the connection is dead.
    if now.get("resumed"):
        await brain.close()

    # A new session starts with memory, not with conversation: otherwise it talks from
    # notes that do not know yesterday evening yet.
    if n == 1 or now.get("resumed"):
        await remember.run()

    if said is not None:
        log.info("clock", f"tick {n}: nachricht, {von}")
        # The message comes first; the observation does not get dropped because of it.
        # It rides along as background (B10).
        alongside = [observe.alongside(what, now) if what else "", wecker.line(),
                     lang.t("note.spoken") if von == inbox.SPOKEN else "",
                     lang.t("note.dm") if von == inbox.DM else ""]
        answer = await brain.ask(said, von=guard.OWNER, via=von, deep=deep,
                                 context="\n\n".join(note for note in alongside if note))
        log.debug("reply", answer or "(nichts gesagt)")

        # Asked aloud means answered aloud -- and only then. Reading typed text out loud
        # is the kind of helpfulness one wants off as soon as anyone else is in the room.
        if von == inbox.SPOKEN:
            voice.say(answer)
        # From the DM means back into the DM, as well as the window. Not the other way
        # round: whoever types in the window sits in front of it.
        elif von == inbox.DM:
            await dm.send(answer)
        if what:
            store.append("thought", {"at": now["at"], "saw": what,
                                     "thought": lang.t("obs.folded_note"), "testing": mode.testing()})

    # After a message, before any observation: an alarm was asked for.
    elif fällig := wecker.due():
        await _observed(n, fällig + what, now, lang.t("obs.alarm_header"), von=guard.ALARM)

    elif what:
        await _observed(n, what, now)

    # The nudge: this long without a turn, and it is her turn to decide whether to look.
    # Only while someone is at the machine; an empty screen has nothing to show.
    elif watching and observe.quiet_s(now) >= obscfg.QUIET_S and now["idle_s"] < obscfg.IDLE_S:
        await _observed(n, [], now, observe.nudge(now))

    else:
        log.debug("clock", f"tick {n}")
        return

    # Only a tick that had a turn gets here. From here the silence counts anew.
    observe.looked()


async def _observed(n: int, what: list[str], now: dict, header: str = "",
                    von: str = "system") -> None:
    saw = what or [lang.t("label.nudge")]
    log.info("clock", f"tick {n}: {'; '.join(saw)}")
    message = "\n".join(
        line for line in [observe.as_message(what, now, header), wecker.line(),
                          remember.pending_line(), act.standing(von)]
        if line
    )
    spoke = speak.state().get("last")
    thought = await brain.ask(message, von=von, label=lang.t("label.alarm") if von == guard.ALARM else "")

    # The thinking record, kept with the thing that prompted it -- a thought without its
    # trigger cannot be read back. This is what the window's notes column shows.
    store.append(
        "thought",
        {"at": now["at"], "saw": saw, "thought": thought, "testing": mode.testing(),
         "spoke": speak.state().get("last") != spoke},
    )
    if thought:
        log.debug("thought", thought)


async def main() -> None:
    log.start()
    # Before anything else, the self-checks too: they briefly rewrite real state files,
    # and a second instance in between would overwrite one another's state (B5).
    if not store.claim():
        log.info("boot", "es laeuft schon eine instanz -- diese beendet sich")
        return
    store.start()
    mode.start()
    thread.start()
    remember.start()
    voice.start()
    inbox.start()
    web.start()
    ear.start()
    dm.start()
    observe.start()
    act.start()
    brain.start()
    try:
        _self_check()
    except Exception:
        # Refusing to come up is right; doing it silently is not. Started hidden, the
        # traceback goes to a console nobody sees.
        log.exception("boot", "self-check failed, does not come up")
        raise
    log.info("boot", f"{mode.assistant()} up, tick every {system.TICK_S}s, settings {mode.settings()}")

    await web.serve()
    await ear.listen()
    await dm.listen()

    n, heard = 0, None
    try:
        while True:
            n += 1
            try:
                await _tick(n, heard)
            except Exception:
                # One bad tick must not end a process that is meant to run for weeks.
                log.exception("clock", f"tick {n} failed, carrying on")
            # The tick, or earlier when someone types or talks or an alarm is due. Still
            # one clock -- it just waits for more than one thing.
            heard = await inbox.waiting(min(system.TICK_S, wecker.next_s()))
            if heard is inbox.STOP:
                log.info("boot", f"beendet aus dem fenster, nach {n} ticks")
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("boot", f"stopped after {n} ticks")
    finally:
        await ear.close()
        await dm.close()
        await brain.close()


if __name__ == "__main__":
    asyncio.run(main())
