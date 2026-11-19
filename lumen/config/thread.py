"""Der Faden: wie viel vom Verlauf eine neue Sitzung mitbekommt, und wie er angesagt wird.

Der Wortlaut steht hier, die Einträge liefert `thread.py` aus dem, was tatsächlich lief.
"""

# Wie viele Einträge die neue Sitzung zurückbekommt -- Gespräch und Gedanken zusammen.
# placeholder: zwölf. Genug, dass ein Abend nicht in der Mitte abreißt, wenig genug, dass
# der Wiedereinstieg nicht länger ist als das, worum es gerade geht.
BACK = 12

# Wie lang ein einzelner Beitrag im Rückblick sein darf. **Nur hier gekürzt**, nie auf
# der Platte: das Rohmaterial bleibt vollständig liegen, weil v1 genau andersherum
# verdichtete und das Original verlor.
CUT = 600

# Die Ansage davor steht in lang/<sprache>.py ("thread.head"). Sie muss zwei Sachen
# gleichzeitig sagen, und die erste Fassung am Original sagte nur die eine ("keine neue
# Nachricht") -- daraufhin benutzte sie den Verlauf gar nicht. Also beides: niemand wartet
# auf eine Antwort, **und** es ist das Aktuellste, was sie hat.
