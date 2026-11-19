"""Das Fenster: wo es lauscht und wie oft die Seite nachfragt.

Kein Transport-Knopf. Polling ist entschieden, nicht konfiguriert.
"""

# Nur die Loopback-Adresse. Nicht konfigurierbar, und das ist der Punkt: eine Adresse,
# die man auf 0.0.0.0 stellen kann, wird irgendwann auf 0.0.0.0 gestellt. Es gibt keine
# Anmeldung und keine Rechteprüfung -- wer die Seite erreicht, redet als Besitzer.
HOST = "127.0.0.1"
PORT = 8770

# Wie oft die Seite nachfragt. 0,5 s, seit das Fenster zeigt, ob sie gerade aufnimmt:
# bei 1,5 s kam "nimmt auf" oft erst, als der Satz schon fertig war. Eine Antwort kostet
# gemessene 5 ms, alle halbe Sekunde also 1 % der einen Schleife.
POLL_MS = 500

# Wie viele Einträge das Fenster je Spalte zeigt. placeholder: 60.
SHOW = 60

# Anhänge aus dem Fenster: wohin unter data/, und wie groß höchstens.
FILES = "uploads"
MAX_BYTES = 25_000_000
