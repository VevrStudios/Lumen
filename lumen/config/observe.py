"""What counts as something happening.

A **whitelist**, not "everything except". The difference is the whole design: a list of
what wakes her can be read and argued with, while "everything except" quietly grows a
new trigger every time the machine learns a new way to change.

Only with "Beobachten" switched on in the settings. Off, nothing here wakes her; the
clock still notices a wake-up from standby, because the memory pass hangs on that.
"""

from lumen.config import system

# Programs that mean "in a call" when they hold the microphone. A named list, not
# "anything holding the microphone": OBS, a recorder or a noise filter hold it for hours
# without anyone being in a conversation, and going quiet for those would be a bug that
# reads like a policy.
CALL_APPS = frozenset({"discord.exe", "teams.exe", "ms-teams.exe", "zoom.exe", "slack.exe"})

# Windows internals with a window that nobody "has open".
NOT_A_PROGRAM = frozenset({
    "applicationframehost.exe",
    "textinputhost.exe",
    "shellexperiencehost.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "systemsettings.exe",
    "lockapp.exe",
})

# From which gap between two passes the machine has slept. The tick is two minutes; half
# an hour of gap means standby or a restart, nothing else.
RESUME_GAP_S = 1800

# When "away" starts. Below this someone is at the machine, above it not.
# placeholder: five minutes is a guess.
IDLE_S = 300

# The nudge: this long without a turn, and it is her turn -- she decides herself whether
# to look (`hinsehen`). Only while someone is at the machine: a look at an empty screen
# overnight is nothing. The crossing away->back fires on its own as `back`.
# placeholder: ten minutes.
QUIET_S = 600

# Longer gaps are charged to no program. A gap bigger than a few passes was no pass:
# standby, restart, daemon off. Measured on the original: 17.4 h for the editor in one
# day -- the night, charged to the window in front when the machine went to sleep (B11).
CHARGE_MAX_S = 3 * system.TICK_S

# --- What wakes her ---------------------------------------------------------------
#
#   away     nobody at the machine any more
#   back     somebody again
#   call     a call program took or released the microphone
#
# Which program is in front, and its title, does not: it is recorded every tick and she
# reads it when she looks (`hinsehen`), on the nudge every QUIET_S.


# --- Wortlaut ---------------------------------------------------------------------
#
# Die Sätze, die sie liest, stehen in lang/<sprache>.py unter "obs.*". Warum sie so lauten:
#  - der Kopf jeder Meldung sagt, wer spricht -- sonst liest sie die Meldung als Nachricht
#    (am Original: auf "Wer bist du?" kam dreimal der Name des Besitzers);
#  - eine Meldung neben einer Nachricht heißt Hintergrund, nicht "es wurde nichts gesagt" (B10);
#  - der Anstoß sagt, dass sie hinsehen kann: die Werkzeugbeschreibung allein trug nicht
#    (0 von 3 Läufen sahen hin);
#  - der Wecker sagt, was sie darin darf, damit sie nicht aus Gewohnheit erst nachfragt.
