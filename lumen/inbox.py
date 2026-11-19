"""Die eine Warteschlange in die Uhr.

Die Eingänge legen hier ab -- Fenster, Mikrofon, Discord-DM --, die Uhr holt ab. Keiner
davon ruft selbst das Modell auf, und keiner kennt die anderen. Das ist Regel 2 an
der Stelle, an der sie zählt: es gibt genau einen Besitzer der Frage, wann ein Zug
passiert, und ein zweiter Eingang darf daran nichts ändern.

Die Herkunft reist mit, weil sie die Antwort ändert: was gesprochen hereinkam, wird
gesprochen beantwortet, Getipptes steht nur im Fenster. Bis hierher war das die einzige
Vorkehrung, die für die Sprachausgabe je getroffen wurde -- das Herkunfts-Feld.
"""

import asyncio
import contextlib
from typing import Any

# Vom Beenden-Knopf. Ein Objekt, kein String: was er tippt, geht in dieselbe Schlange,
# und kein Satz von ihm darf sie beenden können.
STOP = object()

# Vom Gedächtnis-Knopf. Auch ein Objekt, aus demselben Grund wie STOP -- und über
# dieselbe Schlange, weil auch das ein Auftrag an die Uhr ist und kein zweiter Weg an
# ihr vorbei. Das Fenster stößt an, die Uhr führt aus (Regel 2).
REMEMBER = object()

TYPED = "getippt"
SPOKEN = "gesprochen"
DM = "discord"

_queue: asyncio.Queue[Any] | None = None


def start() -> None:
    _global_queue()


def _global_queue() -> asyncio.Queue[Any]:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def put(text: str, origin: str, deep: bool = False) -> None:
    """Etwas für die Uhr. Leeres fällt hier raus, nicht erst im Zug -- das Modell würde
    eine leere Nachricht beantworten. `deep`: diese eine Antwort auf Opus (Knopf im Fenster)."""
    if text.strip():
        _global_queue().put_nowait((text, origin, deep))


def stop() -> None:
    _global_queue().put_nowait(STOP)


def remember_now() -> None:
    _global_queue().put_nowait(REMEMBER)


def requeue(item: Any) -> None:
    """Zurücklegen, wortgleich. Was getippt wurde, fallen zu lassen, weil die Uhr gerade
    etwas anderes vorhatte, wäre die schlechteste Stille."""
    _global_queue().put_nowait(item)


async def waiting(timeout: float) -> Any:
    """Der Wartezug der Uhr: `(text, herkunft, gründlich)`, `STOP`, oder `None`, wenn der Takt
    einfach fällig ist.

    Das ersetzt den Schlaf zwischen zwei Ticks. Immer noch eine Uhr -- sie wacht nur
    früher auf, wenn jemand tippt oder redet, statt bis zu zwei Minuten zu warten.
    """
    try:
        return await asyncio.wait_for(_global_queue().get(), timeout)
    except asyncio.TimeoutError:
        return None


@contextlib.contextmanager
def scratch():
    """Die echte Schlange beiseite, eine leere her. Nur für Selbst-Checks.

    Der Check des Beenden-Knopfes legte sonst ein echtes `STOP` in die echte Schlange,
    und sie hörte im ersten Durchgang wieder auf. Vorher ging das gut, weil es die
    Schlange beim Selbst-Check noch gar nicht gab -- der Check prüfte also nichts.
    Gefunden beim ersten echten Boot am 15.09.2026.
    """
    global _queue
    before, _queue = _queue, asyncio.Queue()
    try:
        yield
    finally:
        _queue = before


def _self_check() -> None:
    """Die eine Zusage, die hier zählt: kein getippter Satz kann sie beenden.

    Ohne `asyncio.run`: der Selbst-Check läuft aus `main()` heraus und damit *in* der
    laufenden Schleife. Beim ersten echten Boot am 15.09.2026 kam sie deshalb gar nicht
    hoch -- ein Fehler, den der Check einzeln aufgerufen nie gezeigt hat.
    """
    assert STOP != "STOP" and STOP != "stop", "das Stopp-Signal darf nichts sein, was man tippen kann"
    assert len({TYPED, SPOKEN, DM}) == 3, "die Herkunft muss die Eingänge unterscheiden können"

    with scratch():
        put("   ", TYPED)
        assert _queue.empty(), "Leerzeichen sind kein Zug"
        put("hallo", TYPED)
        assert _queue.get_nowait() == ("hallo", TYPED, False), "was rein geht, muss rauskommen"
        put("wäge ab", TYPED, deep=True)
        assert _queue.get_nowait()[2] is True, "der Opus-Knopf reist mit"
        stop()
        assert _queue.get_nowait() is STOP, "der Beenden-Knopf muss durchkommen"
        remember_now()
        assert _queue.get_nowait() is REMEMBER, "der Gedächtnis-Knopf auch"
        assert _queue.empty(), "und danach ist sie leer"
    assert STOP is not REMEMBER, "zwei Knöpfe, zwei Signale"
