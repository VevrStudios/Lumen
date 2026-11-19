"""The process itself: where things live and how fast the clock runs.
One config module per axis -- this is the axis that belongs to no single module.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The assistant's name until someone picks another in the settings (`mode.assistant()`
# is what everything reads). Neither male nor female -- the voice decides that.
NAME = "Lumen"

# The memory: a flat folder of plain Markdown notes. No Obsidian, no index, no filing
# rules -- small enough that the whole folder rides in the prompt.
MEMORY = ROOT / "memory"
DATA = ROOT / "data"  # its own operating state, which is not memory
LOGS = ROOT / "logs"

# Inside the memory folder: text a write pass replaced. The folder is not versioned, so
# this is the only way back. Never in the prompt -- it is a way back, not memory.
BACKUP = "_backup"

# How often the one clock ticks. Everything timed hangs off this, so it is also the
# resolution of every due-time she can honour -- not just of observation.
#
# Two minutes, measured on the original: at seven, a three-hour session produced no entry
# at all -- every switch to another program and back happened between two samples.
TICK_S = 120

# v1's log reached 28.5 MB, at which point nobody read it any more.
LOG_MAX_BYTES = 5_000_000
LOG_KEEP = 3

# Wie lange das Dauerzuhören anbleibt, bevor es sich selbst abschaltet.
# placeholder: 30 Minuten. Der Wert kommt aus dem Schaden beim Vergessen, nicht aus der
# Länge eines Gesprächs: bleibt es an, während er in einem Call sitzt, hört sie seine
# Hälfte davon und hält jeden Satz für einen an sich. Anklicken kostet eine Sekunde,
# Vergessen kostet einen Abend.
CONVO_MINUTES = 30

# Wie lange "Nicht zugucken" an bleibt, bevor sie wieder hinsieht (28.09.2026).
# placeholder: 30 Minuten. Auch hier entscheidet der Schaden beim Vergessen: sie sieht
# dann still nicht mehr hin, und das Hinsehen ist der Grund, aus dem sie läuft. Dauert
# ein Chat länger, ist erneut Klicken billiger als ein Abend ohne sie.
BLIND_MINUTES = 30

# How long a test run stays on before it switches itself off.
# placeholder: two hours is a guess about how long he tests in one sitting. It only has
# to be short enough that forgetting costs an afternoon and not a week.
TEST_MINUTES = 120


# --- Geheimnisse ------------------------------------------------------------------

_ENV: dict[str, str] | None = None


def secret(name: str, default: str = "") -> str:
    """One value out of .env.

    Hand-rolled rather than python-dotenv: eight lines against a dependency, and the
    dependency budget is one package (rule: stdlib until stdlib demonstrably does not
    reach). v1 did the same for the same reason.

    The file is read once and kept until the window writes a new key (`store.save_secrets`).
    The model cannot open it: '.env' is in guard.NEVER, so any tool that reaches for it is
    refused.
    """
    global _ENV
    if _ENV is None:
        _ENV = {}
        if ENV.exists():
            for raw in ENV.read_text(encoding="utf-8").splitlines():
                line = raw.split("#", 1)[0].strip()
                if "=" in line:
                    key, _, value = line.partition("=")
                    _ENV[key.strip()] = value.strip()
    return _ENV.get(name) or default


ENV = ROOT / ".env"


def secrets_changed() -> None:
    """Read .env again on the next `secret()` -- the window just saved a key."""
    global _ENV
    _ENV = None
