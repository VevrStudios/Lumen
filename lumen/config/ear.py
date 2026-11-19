"""Das Ohr: welches Mikrofon, welches Modell, und woran sie merkt, dass sie gemeint ist.

Nur mit "Zuhören" in den Einstellungen. Whisper läuft lokal auf der CPU -- kein Audio
verlässt den Rechner, und es braucht keine bestimmte Grafikkarte.
"""

import os

from lumen.config import system

# --- der Aufbau ------------------------------------------------------------------

# Nicht im Repo (`tools/` steht in `.gitignore`) und kein Python-Dependency: der fertige
# CPU-Build von whisper.cpp. `tools/install-whisper.ps1` lädt ihn samt Modell hierher.
WHISPER = system.ROOT / "tools" / "whisper"
EXE = WHISPER / "whisper-cli.exe"

# small, quantisiert (190 MB). Gemessen am Original auf der CPU, 8 Threads:
#
#   | Modell                     | Encoder je Äußerung |
#   |----------------------------|---------------------|
#   | large-v3-turbo-q5_0        |     9 202 ms        |
#   | small-q5_1                 |     2 231 ms        |
#
# turbo hört Eigennamen besser, aber neun Sekunden Warten auf jeden Satz sind zu viel.
# Wer eine starke CPU hat und Fachbegriffe braucht, legt das turbo-Modell daneben und
# trägt es hier ein.
MODEL = WHISPER / "ggml-small-q5_1.bin"

# Gerätename oder ein Teil davon; leer heißt: das Standard-Mikrofon von Windows. Ein
# Name, kein Index -- Windows zählt die Geräte in der Reihenfolge, in der sie angesteckt
# wurden, und ein Index verschiebt sich still.
DEVICE = ""

# Die Hälfte der Kerne, höchstens acht: whisper skaliert darüber kaum, und der Rechner
# soll beim Zuhören nicht stocken.
THREADS = max(1, min(8, (os.cpu_count() or 4) // 2))

# Wie lange ein Satz beim Transkribieren höchstens dauern darf, bevor whisper-cli
# abgeschossen wird. placeholder: 60 s -- ein hängender Prozess darf das Ohr nicht für
# immer belegen, mehr soll die Zahl nicht.
TRANSCRIBE_TIMEOUT_S = 60

# --- wie aus dem Pegel eine Äußerung wird -----------------------------------------

# Das Mikrofon wird selbst gelesen, 16 kHz mono, und hier geschnitten -- jede Äußerung
# geht danach genau **einmal** durch whisper. Bis zum 28.09.2026 schnitt `whisper-stream`:
# es transkribierte bei jeder Atempause die letzten 8 s neu, und derselbe Satzschwanz kam
# als zwei, drei Nachrichten an (06:47:32/35/40 an dem Morgen). Sie brach dafür ihre
# eigene Antwort ab. v1 hatte schon eigene Schnitte und wurde als besser erkannt.

# Ein Puffer. 30 ms wie der Takt der Sprechtaste: feiner braucht es nicht, gröber
# schneidet es den Anfang ab.
FRAME_MS = 30

# Wieviele Puffer Windows füllen darf, bevor gelesen wird. 200 x 30 ms = 6 s: solange
# darf die eine Schleife hängen (Azure blockiert sie 0,6 s je Satz), ohne dass Ton fehlt.
FRAMES_QUEUED = 200

# Ab welchem Pegel (RMS, 0..1) es Sprache sein kann. Am Original-Mikrofon gemessen:
# Grundrauschen 0,005, Sprache 0,08 bis 0,19. Eher tief: ein Fehlstart kostet zwei
# Sekunden CPU und fliegt dann am fehlenden Namen raus, ein verpasster Satzanfang kostet
# die Frage. placeholder für jedes andere Mikrofon -- die Pegel stehen im Log.
LEVEL_ON = 0.015

# Wie lange laut, bevor eine Äußerung anfängt. Ein Klick ist ein Puffer, ein Wort ist
# mehrere. v1: 120 ms.
ATTACK_S = 0.15

# Was vor dem Auslösen mitgeht. Der Pegel steigt erst mitten im ersten Laut über die
# Schwelle; ohne Vorlauf hört whisper den Namen ohne seinen ersten Laut (v1, 300 ms).
LEAD_S = 0.3

# Wie lange still, bevor der Satz zu Ende ist. Am Original entschieden: zwei Sekunden
# Atempause sind mitten im Satz, fünf sind das Minimum für fertig. Der Preis sind 5 s,
# bevor sie anfängt zu denken -- die Anzeige im Fenster zeigt sie, damit Warten nicht nach
# Taubheit aussieht. Wer schneller will, hält die Sprechtaste.
END_S = 5.0

# Was von der Stille am Ende mitgeht. Fünf Sekunden Rauschen sind für whisper eine
# Einladung zu "Untertitel im Auftrag des ZDF".
TAIL_S = 0.3

# Deckel für eine Äußerung, mit oder ohne Taste. Ein Fernseher im Hintergrund oder eine
# verklemmte Taste darf nicht heißen, dass sie den Abend sammelt. placeholder: v1s Wert.
MAX_S = 120

# --- woran sie merkt, dass sie gemeint ist ----------------------------------------

# Ihr Name, unscharf. Der Name selbst kommt aus den Einstellungen (`mode.assistant`) und
# trifft über die Unschärfe unten auch leichte Verschreiber. Diese Liste kommt nur für den
# voreingestellten Namen dazu. placeholder: geraten, nicht an Transkripten gemessen -- was
# im Log unter "ear" als Fast-Treffer steht, gehört hierher.
ALIASES = ("lumen", "lumin", "lumens", "loomen", "luhmen", "lu men")

# Ab welcher Ähnlichkeit ein gehörtes Wort als ihr Name gilt. 0,78 ist am Original
# gemessen: darunter fingen Alltagswörter an mitzuspielen.
FUZZ = 0.78

# Wieviele Wörter ein Alias lang sein darf ("lu men").
ALIAS_MAX_TOKENS = 2

# Nur der Name, sonst nichts: der häufigste Fall überhaupt, weil whisper an
# Sprechpausen schneidet und man nach dem Namen eine macht. Dann gilt die nächste
# Äußerung als die Frage, statt sie zu verlieren. Verbraucht sich sofort -- sonst
# verlängert ein Räuspern das Fenster still, und sie antwortet auf einen Satz von
# zwei Minuten später.
WINDOW_S = 8.0

# Kurze Bestätigungen und was whisper aus einem Räuspern macht, gelten nur bis zu so vielen
# Wörtern als Füllsel -- damit "ja genau, und wie war das nochmal" durchgeht. Die Wörter
# selbst hängen an der Sprache (lang/<sprache>.py: FILLER, HALLUCINATIONS).
FILLER_WORDS = 3



# --- die Sprechtaste --------------------------------------------------------------

# Solange sie unten ist, wird nicht geschnitten: alles zwischen Druecken und Loslassen
# ist EINE Aeusserung und braucht ihren Namen nicht -- das Halten *ist* die Ansprache.
# Der Anlass steht in v1s `ptt.py` und kam am 16.09.2026 unveraendert wieder: Whisper
# schneidet an Sprechpausen, und eine Erklaerung hat Sprechpausen. Dagegen hilft keine
# bessere Schaetzung, sondern eine Ansage.
#
# **Gepollt, nicht gehookt** (v1s Messung, uebernommen): `GetAsyncKeyState` braucht
# weder Fenster noch Nachrichtenschleife. Ein `WH_KEYBOARD_LL`-Hook koennte die Taste
# zusaetzlich verschlucken, verlangt aber eine Nachrichtenschleife in genau dem Thread,
# der ihn setzt -- und Windows wirft ihn raus, sobald die je haengt.
#
# Preis des Pollens: die Taste kommt im Vordergrundprogramm mit an. **Alt haelt in den
# meisten Windows-Programmen die Menueleiste auf**, und hier wird es Sekunden gehalten;
# v1 hatte aus genau dem Grund `strg+ss` gemessen. Am Original trotzdem so gewählt,
# und sie ist diese eine Zeile -- wenn eine Menueleiste aufblitzt, steht hier morgen
# etwas anderes.
PTT_HOTKEY = "alt+y"

# Wie oft der Tastenzustand abgefragt wird. v1s Wert, dort nie beanstandet: schnell
# genug, dass das Loslassen nicht nachhinkt, langsam genug, dass es nichts kostet.
PTT_TICK_S = 0.03
