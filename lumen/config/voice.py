"""Ihre Stimme: welche, und was vor dem Sprechen aus dem Text raus muss.

Azure Neural TTS, nur wenn in den Einstellungen ein Azure-Konto eingetragen ist --
Schlüssel und Region stehen dann in der `.env` und kommen über `system.secret`. Ohne
Konto bleibt sie stumm und schreibt nur ins Fenster.

Die Ersetzungen sind Text, keine Logik, und stehen deshalb hier und nicht in `voice.py`.
"""

# Die Wahl im Fenster: weiblich oder männlich. Welche Azure-Stimme das ist, hängt an der
# Sprache und steht in lang/<sprache>.py (VOICES). Der Name ihres Programms ist mit Absicht
# weder männlich noch weiblich; das entscheidet erst die Stimme.
DEFAULT = "female"

# Wie schnell sie redet, relativ zur Normalgeschwindigkeit. Am Original aus Hörproben von
# +0 bis +25 % gewählt.
RATE = "+10%"

# WAV, nicht MP3: `winsound` spielt nur RIFF ab, und damit bleibt die Wiedergabe stdlib.
# 24 kHz mono reicht für Sprache, die aus Desktop-Lautsprechern kommt.
FORMAT = "riff-24khz-16bit-mono-pcm"

# placeholder: 20 s. Azure antwortet in unter zwei Sekunden; der Wert ist die Grenze, ab
# der Schweigen besser ist als ein hängender Zug -- sie blockiert die eine Uhr so lange.
TIMEOUT_S = 20


# Was vor dem Sprechen ersetzt wird. Reguläre Ausdrücke, keine festen Paare -- wegen des
# Schrägstrichs: blank ersetzt macht er aus `notizen/plan/umzug.md` "notizen zu plan zu
# ark punkt md". Ein Mechanismus, zwei Sorten Regel wären eine zu viel.
#
# Die Reihenfolge trägt: erst die Linkliste als Ganzes, dann einzelne Links, dann Zeichen.
# Gemessen am 11.09.2026 an echten Antworten -- sie liest brav vor, was dasteht.
CLEAN = [
    # Die Websuche hängt ihrer Antwort eine *Sources:*-Liste an -- nicht aus der Persona,
    # sondern aus der Anweisung des Werkzeugs. Im Fenster nützlich, vorgelesen sinnlos.
    (r"(?is)\n\s*(?:sources?|quellen)\s*:.*$", ""),
    (r"\[([^\]]+)\]\([^)]+\)", r"\1"),        # Markdown-Link: der Text bleibt, die Adresse geht
    (r"https?://\S+", ""),                     # nackte Adresse: buchstabengetreu vorgelesen
    (r"\*+", ""),                              # Fettdruck; gesprochen gibt es keinen
    (r"`", ""),
    (r"_", " "),                               # ark_map_v3 -> "ark unterstrich map ..."
    (r"↔", "{and}"),                           # sonst "Pfeil nach links und rechts"
    (r"→", "{to}"),
    (r"·", ","),
    (r"(?<=\d)\s*/\s*(?=\d)", "{to}"),         # 90/10 wurde "90 Schrägstrich 10"
    (r"[ \t]{2,}", " "),                       # was das Rausnehmen an Lücken hinterlässt
]
