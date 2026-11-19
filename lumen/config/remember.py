"""Der Gedächtnis-Lauf: wann er läuft. Was sie dabei gesagt bekommt, steht in
lang/<sprache>.py ("remember.*").

Fester Wortlaut gehört hierher. Das Rohmaterial liefert `remember.py`. Wo und wie eine
Notiz liegt -- flach, kleine Dateinamen, kein Frontmatter --, prüft zusätzlich der Guard
(`guard._filing`).
"""

# Warum das beim nächsten Start läuft und nicht am Ende der Sitzung: eine Sitzung, die am
# Ende noch etwas erledigen muss, erledigt es nicht, wenn der Rechner abstürzt, das
# Kontingent alle ist oder jemand den Prozess abschießt. Das Rohmaterial liegt sowieso
# schon da, und der *nächste* Start wertet es aus.

# Wo geschrieben werden darf. Ohne diesen Satz rät sie den Pfad gegen das
# Arbeitsverzeichnis und läuft mit jedem Edit in eine Ablehnung. Eine Wegbeschreibung,
# keine Sicherheitszusage -- die Grenze bleibt der Guard.


# Ab wann still genug ist, um einzusortieren: so lange kam nichts. Danach steht in jeder
# ihrer Meldungen, was noch nicht eingetragen ist, und sie entscheidet, ob jetzt.
# placeholder: zehn Minuten.
PAUSE_S = 600

