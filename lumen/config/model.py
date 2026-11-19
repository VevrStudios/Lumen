"""Which model does which job, and how hard it thinks.

The only place in the project that names a model. Everything else asks for a job by
name, so changing a choice is one edit here and nothing else moves.

Rule 1: usage is a quota, not a price. Nothing here is chosen to save money -- it is
chosen so the 5-hour window is still there for the jobs that actually need the
thinking. Both jobs are on Opus: each one was moved there on a measured failure on
Sonnet in the original, not on principle.
"""

# The SDK takes an alias ("opus" / "sonnet" / "haiku") or a full model id.
# Full ids, so an alias moving under us cannot silently change a job's model.
OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"

# Job -> (model, effort). Effort is the SDK's thinking depth: low | medium | high | xhigh | max.
JOBS = {
    # Talking, and thinking about an observation. The bulk of every day, so Sonnet: it
    # answers faster and leaves most of a Pro plan's window free. One answer at a time can
    # go to Opus from the window (DEEP) -- where an objection or a weighing matters.
    "converse": (SONNET, "medium"),
    # Deriving notes from a conversation and filing them into memory. Few runs a day,
    # and a wrong note costs more than a slow one.
    "remember": (OPUS, "high"),
}


# The window's "Opus" button: this one answer on Opus, in the same session (set_model),
# then back. The session keeps its history; only that turn costs Opus.
DEEP = OPUS


def job(name: str) -> tuple[str, str]:
    """Model and effort for one job. Unknown name is a bug, not a fallback --
    a silent default would hide a typo until someone read the token log."""
    if name not in JOBS:
        raise KeyError(f"no such job: {name!r}. Known: {', '.join(sorted(JOBS))}")
    return JOBS[name]


def _self_check() -> None:
    """One runnable check: a job that names a model nothing serves is a runtime failure
    hours later, when she finally tries to think."""
    known = {OPUS, SONNET}
    for name, (model, effort) in JOBS.items():
        assert model in known, f"job {name!r} names an unknown model: {model}"
        assert effort in ("low", "medium", "high", "xhigh", "max"), (
            f"job {name!r} has an invalid effort: {effort}"
        )

    assert set(JOBS) == {"converse", "remember"}, "two jobs: talking and filing"
    assert DEEP != job("converse")[0], "the Opus button must switch to something else"

    try:
        job("does_not_exist")
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown job must raise, not fall back to a default")
