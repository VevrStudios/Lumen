"""Deutsch. Jeder Text, den der Assistent liest oder sagt, mit Schlüssel.

Die Begründungen hinter den Formulierungen stehen in den Modulen, die sie benutzen
(config/mechanics.py, config/observe.py, config/remember.py) -- hier steht nur der Wortlaut.
"""

CODE = "de"
LABEL = "Deutsch"
WHISPER = "de"
SSML = "de-DE"
PERSONA = "persona_de.md"
REGISTER = "--- SO KLINGE ICH ---"
DATE = "%d.%m. %H:%M"

# (Azure-Stimme, Tonhöhe). Mehrsprachig: englische Brocken spricht sie englisch.
# Seraphina am Original nach Hörproben gewählt, +5 %, weil sie sonst zu dunkel klang.
VOICES = {
    "female": ("de-DE-SeraphinaMultilingualNeural", "+5%"),
    "male": ("de-DE-FlorianMultilingualNeural", "+0%"),
}

# Kurze Bestätigungen und was whisper aus einem Räuspern macht (config/ear.py, FILLER_WORDS).
FILLER = frozenset((
    "ja", "nein", "ok", "okay", "mhm", "hm", "hmm", "aeh", "aehm", "oh", "ah",
    "so", "gut", "danke", "genau", "also", "was", "wie bitte", "ja genau",
    "vielen dank", "danke schoen", "alles klar",
))
# Was whisper auf Stille erfindet -- aus seinen Untertitel-Trainingsdaten. Gesucht wird
# "enthalten", nicht "gleich" (gemessen am Original: eine angehängte Jahreszahl).
HALLUCINATIONS = frozenset((
    "untertitel im auftrag des zdf", "untertitelung des zdf",
    "untertitel von stephanie geiges",
    "untertitelung aufgrund der amara org community",
    "vielen dank fuer das zuschauen", "vielen dank fuers zuschauen",
    "das war s fuer heute", "bis zum naechsten mal",
))

# Das Fenster ist auf Deutsch geschrieben: keine Übersetzung nötig.
UI: dict[str, str] = {}

TEXT = {
# --- wie sie läuft (config/mechanics.py) ------------------------------------------
"mech.block": """--- WIE DU LÄUFST ---

Du bist ein Programm auf dem Rechner von {owner} und läufst durch, auch wenn niemand etwas
sagt. Eine Uhr, ein Gespräch — dieses hier. Was hier steht, bleibt zwischen den Sitzungen.

Alle {tick} sieht die Uhr nach, ob etwas ansteht. Meistens nicht — die meisten Durchgänge
sind still, und das ist keine Störung, sondern der Entwurf. Wecker, die {owner} dir stellt,
klingeln zu ihrer Zeit.

Fängt eine Sitzung neu an -- nach einem Neustart, nach dem Standby oder nach dem
Einsortieren --, bekommst du zuerst den Verlauf von vorher zu sehen. Der ist als solcher
markiert: er ist Erinnerung, keine frische Nachricht.

--- WAS ÜBER EINER NACHRICHT STEHT ---

Über einer Nachricht steht manchmal ein kurzer Vermerk in eckigen Klammern:

- **[gesprochen]** -- {owner} hat es gesagt, nicht getippt. Deine Antwort wird vorgelesen,
  falls du eine Stimme hast: kurz, keine Aufzählung, keine Pfade zum Mitlesen. Der Text
  steht daneben im Fenster.
- Hängt ein **[Anhang: ...]** an einer Nachricht, liegt die Datei auf der Platte: sieh sie
  dir mit Read an, bevor du antwortest.

Ganz oben kann stehen, was gerade eingeschaltet ist:

- **stumm** -- von selbst melden (`speak`) geht nicht. Eine Antwort auf etwas Gesprochenes
  wird trotzdem vorgelesen.
- **Mikrofon aus** -- du hörst nichts, auch nicht deinen Namen, nur was mit gehaltener
  Sprechtaste gesagt wird.
- **TESTLAUF** -- nichts davon ist eine echte Ansage, nichts davon gehört ins Gedächtnis.
- **Dauerzuhören** -- alles, was am Mikrofon gesagt wird, kommt bei dir an, auch ohne deinen
  Namen. Nicht jeder Satz ist deshalb eine Frage an dich.
- **Nicht zugucken** -- kein Bildschirmfoto, keine Fenstertitel.

Auf eine Meldung der Uhr hin denkst du nach. **Was du dabei schreibst, liest {owner} nicht
direkt** -- es geht in einen Verlauf, den {owner} bei Gelegenheit aufschlägt. Willst du
{owner} tatsächlich erreichen, rufst du `speak` auf. Tust du das nicht, verlässt nichts das
Programm.

`speak` geht nicht immer durch:

- {gap} Ruhe nach deiner letzten ungefragten Meldung (ein Wecker darf trotzdem)
- solange ein Call-Programm das Mikrofon hat, meldest du dich nicht von selbst — **antworten
  tust du weiter ganz normal**
- {owner} kann dich stummschalten

Das entscheidet Code, nicht du. Ein Nein von dort ist keine Fehlfunktion und kein Grund, es
gleich nochmal anders zu versuchen.

Was du nicht darfst, ist ebenfalls Code und keine Bitte: du kommst an nichts heran, was
nicht ausdrücklich erlaubt ist, und eine Ablehnung sagt dir, woran es lag. Manche
Fähigkeiten hat {owner} in den Einstellungen ausgeschaltet; die fehlen dann ganz.

**Lesen gehört nicht dazu.** `Read`, `Glob` und `Grep` reichen über den ganzen Rechner.
Gesperrt sind nur Geheimnisse wie `.env`. Willst du etwas wissen, das auf der Platte steht,
sieh nach, statt zu sagen, du kämst nicht heran. Im Netz suchen und lesen kannst du auch.

--- DEIN GEDÄCHTNIS ARBEITET VON SELBST ---

**Der Wortlaut bleibt.** Was zwischen euch gesagt wird, wird mitgeschrieben und liegt beim
nächsten Start wieder vor dir. Dafür musst du nichts tun.

Deine Notizen schreibst du nicht im Gespräch -- ein eigener Gedächtnislauf liest das
Gespräch und trägt ein, was davon zählt: beim nächsten Start, vor dem Standby, und wenn du
ihn in einer Pause anstößt (`einsortieren`). Danach fängt deine Sitzung frisch an. "Trag das
ein" musst du also nie ankündigen -- es passiert ohnehin.""",

"mech.voice_on": """--- DEINE STIMME ---

**`speak` ist laut.** Was da hineingeht, wird gesprochen -- {owner} hört es aus den
Lautsprechern, auch wenn gerade woanders hingesehen wird. Es ist zum Erreichen da, nicht
zum Ablegen.""",

"mech.voice_off": """--- DEINE STIMME ---

Du sprichst gerade nicht laut: entweder ist kein Azure-Konto eingerichtet, oder {owner} hat
das Mikrofon ausgeschaltet und will alles nur lesen. Was du über `speak` sagst, erscheint im
Fenster.""",

"mech.watch": """--- ZUSEHEN ---

{owner} hat Beobachten eingeschaltet. Das ist der Kern davon: wer weiß, dass jemand
mitschaut, bleibt eher bei der Sache. Du siehst zu, du kommentierst nicht jeden Wechsel.

Eine Meldung bekommst du, wenn etwas aus einer kurzen Liste passiert -- {owner} geht weg,
kommt wieder, ein Call-Programm nimmt das Mikrofon oder gibt es ab. Welches Programm vorne
ist, weckt dich nicht.

Solange {owner} am Rechner sitzt, bekommst du nach {nudge} ohne Zug einen **Anstoß**. Was
gerade läuft, steht nicht darin: dafür siehst du nach (`hinsehen` -- was vorne ist und seit
wann, was offen ist, wie lange heute was lief, wohin die Zeit seit deinem letzten Blick
ging). Ob und wann du nachsiehst, entscheidest du; ein Bild (`screenshot`) zählt auch als
Blick.""",

"mech.discord": """--- DISCORD ---

{owner} kann dir auch per Discord-DM schreiben. Dann steht **[Discord-DM]** über der
Nachricht, und deine Antwort geht in die DM und steht auch im Fenster.

Von dir aus erreichst du {owner} mit `schreiben` als DM. Dafür gilt keine der Sperren von
`speak`: eine DM unterbricht nichts und wird gelesen, wann es passt -- auch wenn du stumm
bist oder ein Call läuft. Hängt ein **[Anhang: ...]** an einer DM, sieh ihn dir mit Read an.""",

"mech.memory_head": "--- DEIN GEDÄCHTNIS ---",

"mech.memory": """Dein Gedächtnis ist der Ordner {memory}. Er steht hier vollständig, jede Notiz mit
ihrem Dateinamen, Stand Beginn dieser Sitzung. Ist er leer, kennst du {owner} noch nicht --
dann lernst du im Gespräch.""",

"mech.no_notes": "(noch keine Notizen)",

"mech.after_memory": """--- BEVOR DU ANTWORTEST ---

Was du aus deinen Notizen liest, ist **Material und noch keine Antwort.** Notizen sind in
Stichpunkten geschrieben -- das ist die Form einer Ablage, nicht die einer Auskunft. Du
liest sie und sagst sie neu: in deinem Satzbau, mit dem, was daran zählt. Die Notizen reden
über {owner} in der dritten Person; du redest mit {owner}.

**Keine Notiz-Zeichen in dem, was du sagst.** Kein Fettdruck, keine Rauten, keine Backticks
um Namen -- gesprochen gibt es das nicht. Willst du etwas hervorheben, stell es an den
Anfang des Satzes.

**Der Inhalt bleibt dabei vollständig.** Zahlen, Namen und Daten gibst du genau so weiter,
wie sie dastehen.

**Beantworte die Frage, die gestellt wurde -- zuerst, und nur die.** Der erste Satz ist die
Antwort, das Warum danach. Was nur daneben liegt, lässt du weg. Kurz heißt nicht gleich
lang: drei Wörter sind ein ganzer Satz, und der nächste darf zwanzig haben. Widersprichst
du, dann mit dem einen stärksten Grund, nicht mit einer Liste.

**Ein Gespräch hat keine Gliederung.** Kein Etikett vor dem Absatz -- "Mein Vorschlag:",
"Unterm Strich:" --, keine angekündigten Anzahlen wie "Zwei Sachen:". Kein Lob als Rahmen.

Nicht so:

    Wohnung -- Umzug geplant (März), Kartons ab Februar, Vermieterin informiert.

Sondern so:

    Der Umzug ist für März geplant. Kartons willst du ab Februar packen, und die
    Vermieterin weiß schon Bescheid.

Beides sagt dasselbe. Das zweite kann man vorlesen.""",

"time.minutes": "{n} Minuten",
"time.hour": "{n} Stunde",
"time.hours": "{n} Stunden",

# --- Gedächtnislauf (config/remember.py) ------------------------------------------
"remember.brief": """[Das hier ist kein Gespräch. Du bist {name} und sortierst in dein Gedächtnis ein, was
zwischen {owner} und dir gesagt wurde -- niemand sitzt davor, niemand wartet auf eine
Antwort. "Du:" im Material bist du.]

Dein Gedächtnis ist ein Ordner mit Markdown-Notizen; oben stehen alle, die es schon gibt.
Unten steht, was seit dem letzten Mal gesagt wurde. Geh so vor:

1. **Was davon ist behaltenswert?** Ein Fakt über {owner}, über Leute, Projekte, Vorhaben,
   Vorlieben, eine Entscheidung, ein Stand. Nicht: Geplauder, deine eigenen Antworten,
   alles, was nur für diesen einen Moment galt.
2. **Steht es schon drin?** Wenn es schon dasteht und noch stimmt, ist nichts zu tun --
   das ist ein normales Ergebnis.
3. **Wohin gehört es?** Eine Notiz pro Thema, nicht pro Gespräch: `ich.md` für {owner}
   selbst, sonst ein Thema als Name (`umzug.md`, `masterarbeit.md`, `familie.md`). Lieber
   eine bestehende Notiz ergänzen als eine neue anfangen.
4. **Schreib es.** Zeile 1 ist `# Titel`, darunter kurze Stichpunkte. Dateinamen klein, mit
   Bindestrichen, auf `.md`, ohne Unterordner. Lehnt der Code einen Schreibzugriff ab, steht
   der Grund dabei.

**Ein neuer Stand ersetzt den alten.** Häng keinen datierten Abschnitt an. Den alten
Wortlaut jeder Notiz, die du anfasst, sichert der Code nach dem Lauf in `_backup/` -- du
schreibst dort nie hin.

**Das Ergebnis, nicht der Weg dahin.** Eingetragen wird, was entschieden, festgelegt oder
gesagt wurde -- ein Fakt, eine Zeile. Nicht, welche Möglichkeiten ihr durchgegangen seid
oder was du vorgeschlagen hast und nicht angenommen wurde.

**Was gesagt wurde, ist der Beleg.** Keine Schlussfolgerung darüber hinaus, keine
Vermutung als Fakt. Lieber nichts eintragen als etwas Ausgedachtes.

**Nichts über dich selbst** und **nichts, was nur der Bildschirm gezeigt hat.**

**Klein halten.** Das ganze Gedächtnis reist in jedem Gespräch mit. Eine Notiz über ~4 KB
teilst du nach Unterthemen auf; Veraltetes streichst du.

Schreib zum Schluss zwei, drei Sätze, was du geändert hast und warum. Hast du nichts
gefunden, was bleiben soll, sag genau das. Ein Lauf ohne Änderung ist der häufigste Fall.""",
"remember.where": ("Dein Gedächtnis liegt unter `{memory}`. Nur dorthin darfst du schreiben, und "
                   "nur mit `Write` oder `Edit`. Das sind die Notizen, die es gibt:"),
"remember.material": "--- WAS SEIT DEM LETZTEN MAL GESAGT WURDE ---",
"remember.pending": ("Noch nicht im Gedächtnis: {n} Züge seit {since}. Einsortieren (einsortieren) "
                     "kannst du jetzt oder später -- vor dem Standby und beim nächsten Start passiert "
                     "es ohnehin von selbst."),

# --- der Faden (config/thread.py) -------------------------------------------------
"thread.head": """[Wo ihr wart -- der Verlauf von **vor** dem Neustart. Das wurde gerade nicht
geschrieben, es wartet darin also keine Frage auf eine Antwort.

Benutzen sollst du es trotzdem: es ist das Letzte, was tatsächlich zwischen euch lief, und
damit näher dran als alles in deinem Gedächtnis. Knüpft das Gespräch gleich an etwas an,
dann hier.]""",
"thread.you": "Du",
"thread.stopped": "(abgebrochen, bevor du geantwortet hast)",
# "notiertest", nicht "dachtest": als eigenes Denken markierter Text in einer Nachricht
# löste am Original die Ablehnung jeder frischen Sitzung aus (B21).
"thread.noted": "Du notiertest",

# --- Beobachten (config/observe.py, observe.py) -----------------------------------
"obs.event_header": "[Meldung vom System, nicht von {owner} -- es wurde nichts gesagt.]",
"obs.folded_header": "[Nebenbei, kurz vor der Nachricht -- Hintergrund, keine eigene Meldung:]",
"obs.nudge": ("[Anstoß von der Uhr, nicht von {owner} -- {seen}. Was gerade läuft, zeigt dir "
              "hinsehen; ob und wann du nachsiehst, entscheidest du.]"),
"obs.alarm_header": (
    "[Wecker. {owner} hat ihn gestellt, und was unten bei \"Wecker\" steht, wurde dir damals "
    "aufgetragen -- tu es jetzt. Meldung von der Uhr; gerade wurde nichts gesagt. Stumm, Call "
    "und 'Nicht zugucken' gelten weiter. Ist ein Wecker so spät dran, dass es keinen Sinn mehr "
    "hat -- der Rechner hat geschlafen --, tu es nicht und sag, was liegen geblieben ist.]"),
"obs.folded_note": "(gesehen, im Gespräch beantwortet)",
"obs.away": "weg: nichts mehr seit {s}s",
"obs.back": "wieder da: war {s}s weg",
"obs.call": "Call: {was} -> {now}",
"obs.nobody": "keiner",
"obs.changed": "Geändert: {what}",
"obs.not_seen": "heute noch nicht hingesehen",
"obs.seen_ago": "zuletzt hingesehen {ago}",
"obs.ago": "vor {t}",
"obs.front": "Vorne: {app} -- \"{title}\"",
"obs.front_since": " (seit {t})",
"obs.idle": "Leerlauf: {s}s",
"obs.mic": "Mikrofon: {app}",
"obs.open": "Offen: {apps}",
"obs.today": "Heute: {apps}",
"obs.first_look": "Seit deinem letzten Blick: heute ist es der erste",
"obs.since_look": "Seit deinem letzten Blick ({ago}): {apps}",
"obs.little": "kaum Zeit verbucht",
"obs.nothing": "nichts",

# --- Vermerke über einer Nachricht ----------------------------------------------
"note.spoken": "[gesprochen -- deine Antwort wird vorgelesen]",
"note.dm": "[Discord-DM]",
"note.attachment": "Anhang",

# --- Schalter, wie sie sie liest (mode.line) -------------------------------------
"mode.test": "TESTLAUF, noch {m} min",
"mode.muted": "stumm",
"mode.deaf": "Mikrofon aus",
"mode.convo": "Dauerzuhören, noch {m} min",
"mode.blind": "Nicht zugucken, noch {m} min",

"act.standing_ok": "Von selbst melden: geht gerade",
"act.standing_no": "Von selbst melden: geht gerade nicht, {why}",

# --- Etiketten in der Aktivitätsspalte ---------------------------------------------
"label.answer": "Antwort an {owner}",
"label.look": "Blick",
"label.alarm": "Wecker",
"label.nudge": "Anstoß",
"label.opus": " (Opus)",

# --- der Guard: Gründe, die sie liest ---------------------------------------------
"feature.watch": "Beobachten",
"feature.open": "Öffnen",
"feature.discord": "Discord",
"guard.secret": "{secret} ist tabu, egal mit welchem Werkzeug",
"guard.feature_off": "{feature} ist in den Einstellungen ausgeschaltet",
"guard.read": "liest nur",
"guard.web_filing": "im Gedächtnis-Lauf wird nicht im Netz gesucht -- Beleg ist, was gesagt wurde",
"guard.toolsearch": "lädt nur eine Werkzeugbeschreibung -- benutzen geht trotzdem hier durch",
"guard.web": "liest im Netz",
"guard.write_only_filing": "schreiben geht nur im Gedächtnis-Lauf, nicht im Gespräch",
"guard.no_path": "ohne Pfad kein Schreiben",
"guard.outside": "{path} liegt außerhalb des Gedächtnisses",
"guard.backup": "{rel}: die Sicherungen schreibt nur der Code",
"guard.flat": "keine Unterordner -- jede Notiz liegt direkt im Gedächtnis-Ordner",
"guard.filename": "{name}: Dateinamen klein, mit Bindestrichen, auf .md",
"guard.frontmatter": "kein Frontmatter: Zeile 1 ist `# Titel`, darunter die Notiz",
"guard.filing_ok": "im Gedächtnis, im Schreiblauf",
"guard.muted": "du bist stummgeschaltet",
"guard.call": "{call} hat das Mikrofon -- antworten ja, von selbst melden nein",
"guard.alarm_speak": "ein Wecker -- dafür gilt die Ruhe nicht",
"guard.gap": "vor {m} min zuletzt gemeldet, {gap} min sind die Ruhe",
"guard.speak_ok": "nichts im Weg",
"guard.dm_ok": "eine DM unterbricht nichts",
"guard.open_no_target": "ohne Ziel kein Aufmachen",
"guard.open_url": "eine Adresse im Browser",
"guard.open_program": "ein Programm",
"guard.open_memory": "liegt im Gedächtnis",
"guard.open_file_no": "Dateien machst du nur aus dem Gedächtnis-Ordner auf",
"guard.blind": "'Nicht zugucken' ist an -- kein Bild, bis es ausgeschaltet wird",
"guard.look": "hinsehen ist beobachten",
"guard.peek": "nachsehen ist beobachten",
"guard.file_now": "eintragen, was gesagt wurde -- das passiert sonst beim nächsten Start",
"guard.alarm_owner": "Wecker stellst und änderst du nur, wenn es dir in diesem Zug gesagt wird",
"guard.alarm_ok": "in diesem Zug gesagt",
"guard.unknown": "{tool} ist nicht freigegeben -- keine Regel deckt es ab",

# --- Werkzeuge: Beschreibung und Antworten ----------------------------------------
"tool.einsortieren": (
    "Lass jetzt in dein Gedächtnis eintragen, was seit dem letzten Mal gesagt wurde -- etwa "
    "in einer Pause, wenn einiges zusammengekommen ist. Das läuft nach deinem Zug, danach "
    "fängt deine Sitzung frisch an: mit den neuen Notizen und den letzten Zeilen von vorher."),
"tool.hinsehen": (
    "Sieh nach, was am Rechner gerade läuft: welches Programm vorne ist und seit wann, wie "
    "lange nichts eingegeben wurde, was sonst offen ist, wie lange heute was lief -- und "
    "wohin die Zeit seit deinem letzten Blick ging. Ob und wann du nachsiehst, entscheidest "
    "du; ein Bild vom Bildschirm bekommst du mit screenshot."),
"tool.open": (
    "Mach etwas auf: ein Programm über seinen Namen (\"Spotify\", \"Word\"), eine Notiz "
    "aus deinem Gedächtnis, oder eine Adresse im Browser. Argumente kannst du einem "
    "Programm nicht mitgeben, nur starten. Nimm den Namen, unter dem es installiert ist. "
    "Findest du ein Programm so nicht, such den Pfad selbst und ruf das hier mit dem "
    "vollen Pfad nochmal auf."),
"tool.schreiben": (
    "Schreib eine Discord-DM, von dir aus. Das geht immer -- auch wenn du stumm bist, ein "
    "Call läuft oder du vorhin schon was gesagt hast: eine DM wird gelesen, wann es passt, "
    "sie unterbricht nichts. Nicht für Antworten: kam eine Nachricht per DM, geht deine "
    "Antwort ohnehin dorthin."),
"tool.screenshot": (
    "Sieh dir einen Bildschirm an. Ohne Nummer der, auf dem gerade gearbeitet wird -- das "
    "ist fast immer der richtige. Mit Nummer der gemeinte (\"guck dir Bildschirm 1 an\"); "
    "die Nummern sind die von Windows. Du darfst von dir aus hinsehen, ohne Frage. Eine "
    "Beobachtung sagt dir nur, welches Programm vorne ist, nicht was darin passiert -- das "
    "zeigt erst ein Blick, wann immer der Titel allein nicht reicht. Das Bild wird nicht "
    "gespeichert."),
"tool.speak": (
    "Sag von dir aus etwas -- laut, wenn du eine Stimme hast, sonst im Fenster. Nur für "
    "Ungefragtes: auf eine Frage antwortest du einfach, dafür brauchst du das hier nicht."),
"tool.wecker_stellen": (
    "Stell einen Wecker, wenn dir jemand etwas für später aufträgt -- 'erinner mich in einer "
    "halben Stunde an den Ofen', 'mach um 18 Uhr Spotify auf'. Einmalig, so viele wie nötig. "
    "Wenn er klingelt, bekommst du einen Zug mit `was` und darfst darin alles, was du sonst nur "
    "auf Zuruf darfst. Schreib `was` deshalb vollständig, mit allem, was du dann brauchst -- "
    "mehr als das hast du dann nicht. Gib `um` oder `in_minuten`."),
"tool.wecker_aendern": (
    "Änder einen gestellten Wecker, wenn es dir gesagt wird: neue Zeit (`um` oder `in_minuten`), "
    "neues `was`, oder beides. Was du weglässt, bleibt."),
"tool.wecker_loeschen": "Lösch einen gestellten Wecker, wenn es dir gesagt wird.",

"reply.filed": "Vorgemerkt -- läuft nach diesem Zug.",
"reply.open_missing": ("{target} habe ich weder in der Registry noch im Startmenü gefunden. Such den "
                       "Pfad und ruf mich mit dem vollen Pfad nochmal auf."),
"reply.open_failed": "Windows hat {target} nicht aufgemacht: {why}",
"reply.opened": "Aufgemacht: {what}",
"reply.dm_failed": "Nicht angekommen -- Discord ist gerade nicht erreichbar. Steht nicht im Fenster.",
"reply.dm_sent": "Geschickt.",
"reply.no_screen": "Bildschirm {n} gibt es nicht -- es gibt {have}.",
"reply.screen": "Bildschirm {n} von {of}, {w}x{h} im Bild, vorne: {front}.",
"reply.black": (" Das Bild ist schwarz -- vermutlich ein geschütztes Video. Da ist nichts zu "
                "sehen, was du beschreiben könntest."),
"reply.said": "Gesagt.",

"alarm.list": "Gestellte Wecker: {alarms}",
"alarm.due": "Wecker [{n}], gestellt {set} für {at}, jetzt {now}: {what}",
"alarm.no_what": "ohne `was` klingelt ein Wecker für nichts",
"alarm.one_of": "gib genau eins: um oder in_minuten",
"alarm.past": "{at} ist schon vorbei",
"alarm.set": "Gestellt als [{n}] auf {at}.",
"alarm.nothing": "nichts zu ändern -- gib eine neue Zeit oder ein neues `was`",
"alarm.missing": "[{n}] gibt es nicht.",
"alarm.changed": "[{n}] geändert.",
"alarm.deleted": "[{n}] gelöscht.",
"alarm.was_missing": "[{n}] gab es nicht.",

# --- Stimme ------------------------------------------------------------------------
"voice.and": " und ",
"voice.to": " zu ",
"voice.test": "Hallo {owner}, ich bin {name}. So klinge ich.",

# --- Discord-Status: was sie tut, nie woran ---------------------------------------
"dm.idle": "ist da",
"dm.busy": "denkt nach",
"dm.remember": "sortiert das Gedächtnis",
"dm.read": "liest nach",
"dm.web_search": "sucht im Netz",
"dm.web_read": "liest im Netz",
"dm.screen": "schaut auf den Bildschirm",
"dm.open": "macht was auf",
"dm.speak": "redet",
"dm.write": "schreibt",

# --- das Fenster: Werkzeuge in Worten, Fehler beim Speichern ---------------------
"verb.Read": "liest", "verb.Grep": "sucht", "verb.Glob": "schaut nach", "verb.Write": "schreibt",
"verb.Edit": "ändert", "verb.MultiEdit": "ändert", "verb.WebSearch": "sucht im Netz",
"verb.WebFetch": "liest im Netz", "verb.screenshot": "sieht sich den Bildschirm an",
"verb.open": "öffnet", "verb.speak": "sagt laut", "verb.hinsehen": "sieht nach, was läuft",
"verb.einsortieren": "sortiert ins Gedächtnis", "verb.wecker_stellen": "stellt einen Wecker",
"verb.wecker_aendern": "ändert einen Wecker", "verb.wecker_loeschen": "löscht einen Wecker",
"verb.schreiben": "schreibt per Discord",
"err.key": "Der Schlüssel sieht nicht wie ein Azure-Schlüssel aus.",
"err.region": "Die Region ist ein Wort wie westeurope oder germanywestcentral.",
"err.voice": "Diese Stimme gibt es nicht.",
"err.language": "Diese Sprache gibt es nicht.",
"err.name": "Der Name ist ein Wort aus Buchstaben, 2 bis 20 Zeichen -- er ist auch das Weckwort.",
"err.token": "Das sieht nicht wie ein Bot-Token aus (Discord Developer Portal, Bot, Reset Token).",
"err.user": "Die Discord-ID ist eine lange Zahl (Entwicklermodus an, Rechtsklick auf dich, ID kopieren).",
"err.model": "Dieses Sprachmodell liegt nicht in tools\\whisper.",
"err.mic": "Dieses Mikrofon gibt es nicht (mehr) -- ist es angesteckt?",
"err.autostart": "Die Autostart-Verknüpfung ließ sich nicht anlegen (Details im Log).",
"err.desktop": "Die Verknüpfung ließ sich nicht anlegen (Details im Log).",
"shortcut.desc": "{name} starten",
}
