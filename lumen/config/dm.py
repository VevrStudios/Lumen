"""Discord-DM über einen eigenen Bot: wie oft nachgesehen wird, was mitkommt.

Bot-Token und die eigene Discord-ID trägt man im Fenster ein; sie stehen dann in der
`.env` (`DISCORD_TOKEN`, `OWN_USER_ID`). Nur mit dem Schalter "Discord" -- und nur der
Besitzer dieser ID kommt durch, jeder andere, der dem Bot schreibt, wird ignoriert.
"""

API = "https://discord.com/api/v10"
GATEWAY = "gateway.discord.gg"

# Wie lange nach einer abgerissenen Verbindung gewartet wird, bevor neu angemeldet wird --
# und bis wohin sich das bei jedem Fehlschlag verdoppelt. Die Decke kommt aus Discords
# Grenze von 1000 Anmeldungen am Tag: bei 300 s sind es höchstens 288, auch wenn der Token
# falsch ist und jeder Versuch scheitert. Darüber setzt Discord den Token zurück.
# placeholder: 5 s. Nach dem Standby ist das Netz ein paar Sekunden weg.
RECONNECT_S = 5
RECONNECT_MAX_S = 300

# Wie lange ein einzelner Abruf dauern darf, Anhänge eingeschlossen.
# placeholder: 30 s.
TIMEOUT_S = 30

# Was an Anhängen geladen wird. placeholder: 25 MB -- kein Bild und kein Dokument, das sie
# lesen kann, ist größer.
MAX_BYTES = 25_000_000

# Der Discord-Status: *was* sie tut, nie *woran*. Den sieht jeder, der mit dem Bot einen
# Server teilt -- also kein Dateiname, kein Fenstertitel, keine Suchanfrage. Eine feste
# Liste statt eines Textes von ihr (Schlüssel in lang/, "dm.*"): "nichts Privates" hält so der Code (Regel 4).
STATUS_TOOL = {
    "Read": "dm.read", "Glob": "dm.read", "Grep": "dm.read",
    "WebSearch": "dm.web_search", "WebFetch": "dm.web_read",
    "screenshot": "dm.screen", "open": "dm.open", "speak": "dm.speak", "schreiben": "dm.write",
}

# Wie oft nachgesehen wird, ob sich der Status geändert hat. Gesendet wird nur bei einer
# Änderung. placeholder: 5 s -- Discord nimmt 120 Meldungen in der Minute an.
STATUS_S = 5

# Mehr nimmt Discord pro Nachricht nicht an.
LIMIT = 2000

# Wo Anhänge landen, relativ zu `data/`. Sie bleiben liegen: der Pfad steht im Faden.
FILES = "dm"

