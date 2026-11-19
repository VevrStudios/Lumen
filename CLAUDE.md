# CLAUDE.md — Lumen

Lumen ist die verkleinerte Ausgabe eines größeren privaten Assistenten. Kommentare im
Code verweisen auf Befunde von dort (B1–B23, „gemessen am Original“). Was er ist und kann, steht in [README.md](README.md). Sein Name ist eine Einstellung
(`mode.assistant()`, Vorgabe `system.NAME`), nie ein Literal im Code oder in einem Prompt.

## Harte Regeln

Architektur, keine Präferenz. Verletzung heißt Umbau, nicht Patch.

1. **Usage ist ein Kontingent, kein Preis.** Modell nach Aufgabe, Zuordnung nur in
   `config/model.py`; `brain.py` loggt Token pro Call.
2. **Eine Uhr.** Ein Tick in `__main__.py` treibt alles. Kein Modul startet einen eigenen
   Timer oder Thread.
3. **Ein Ausgang zum Modell.** Jeder Claude-Call geht durch `brain.py`. Kein Zwischenmodell,
   keine Subagents.
4. **Eine Grenze ist Code, kein Prompt-Satz.** Was nicht passieren darf, verhindert
   `config/guard.py` als `PreToolUse`-Hook.
5. **Kein Zustand nur im Prozess.** Was einen Neustart überleben muss, geht über `store.py`.
6. **Ein Knopf ist eine nicht getroffene Entscheidung.** Ausnahme mit Absicht: die
   Feature-Schalter in `mode.FEATURES` — er läuft auf fremden Rechnern, und Zusehen,
   Zuhören und Discord muss jeder selbst einschalten. Jeder Schalter sperrt im Guard
   (`guard.FEATURE_OF`) und nimmt das Werkzeug aus dem Angebot (`act.offered`).

## Konventionen

- Python, stdlib plus `claude-agent-sdk`. Win32 über `ctypes`/`winreg`.
- Module werden in `__main__.py` explizit importiert und gestartet. Ein Modul = eine Datei.
- Aktionen sind Daten: `actions/`, eine Datei pro Verb, wird eingelesen.
- Ein Config-Modul pro Achse. Ungemessene Zahlen als `placeholder:` markieren.
- Logging über `log.py`, Persistenz über `store.py`.
- `_self_check()` pro Modul mit plain `assert`, läuft bei jedem Start.
- Code, Bezeichner, Kommentare, Commits: englisch. Doku, Prompts, Chat: deutsch.
- Prompt-Texte nennen den Menschen nie mit Pronomen, sondern über `mode.owner()` (`{owner}`).
- Das Fenster läuft auf Port 8770. Es nimmt nur Anfragen an, die an diesen Port gerichtet sind
  und von der eigenen Seite kommen (`web._foreign`).
