# Lumen

A desktop assistant for Windows that runs in the background: you write to it in its window,
over Discord or by voice, and it answers, remembers what matters, sets alarms, searches the
web and — if you allow it — keeps an eye on what you're working on. The thinking is done by
Claude, through your own Claude subscription.

It's called **Lumen** until you give it another name in the settings; the name is also the
wake word for the microphone. English and German are built in (Settings → Language).

## What you need

- Windows 10 or 11
- Python 3.11 or newer (python.org or the Microsoft Store)
- A Claude subscription (Pro or Max) and Claude Code, signed in once
- Optional: an Azure account for the voice (the free tier is enough), your own Discord bot

## Setup

1. Put the folder anywhere, e.g. `C:\Lumen`.
2. Open a command prompt in that folder and run `pip install -e .`
3. Install [Claude Code](https://claude.com/claude-code), run `claude` once and sign in with
   your Claude account. Lumen uses that sign-in. **Don't set an `ANTHROPIC_API_KEY`** — it
   would bill API credit instead of your subscription.
4. Double-click `start.vbs`. The window opens after a few seconds.
5. On the first start the settings open: name it, tell it your name, pick a language and a
   voice, switch features on. **Start with Windows** and **Add to desktop** are there too.

Conversations run on Claude Sonnet. The **Opus** button next to Send puts the next answer on
Claude Opus — more thorough, slower, uses more of your plan. Filing into memory always uses
Opus.

### Voice input (optional)

Whisper listens locally on the CPU — no audio leaves the computer.

1. Run `tools\install-whisper.ps1` (right-click → "Run with PowerShell"). Downloads ~200 MB.
2. Restart, then pick a microphone under **Settings → Microphone**.
3. Say the name ("Lumen, …"), or hold `Alt+Y` and speak.

More speech models can sit side by side and be chosen in the settings:
`tools\install-whisper.ps1 -Model large-v3-turbo-q5_0` (more accurate, slow on a CPU) or
`-Model base-q5_1` (faster, less accurate).

**On laptops we recommend leaving the microphone off**: Whisper listens all the time and
costs battery and CPU. With the microphone off, Lumen also stays silent and only writes.

### Voice output (optional)

Without an Azure account Lumen answers in writing only. With one:

1. In the [Azure portal](https://portal.azure.com) create a **Speech** service (tier F0 is
   free, 500,000 characters a month).
2. Under "Keys and Endpoint" copy a key and the region.
3. Enter both in the settings and press "Test voice". Female or male is chosen there too.

### Discord (optional)

With your own bot you can DM Lumen, and it reaches out there on its own. Only your own
Discord ID gets through; anyone else writing to the bot is ignored.

1. In the [Discord Developer Portal](https://discord.com/developers/applications) create an
   application and copy the token under **Bot**.
2. Under **OAuth2 → URL Generator** pick the scope `bot` and invite the bot to a server
   you're on (otherwise it can't DM you).
3. In Discord turn on developer mode, right-click yourself → "Copy User ID".
4. Enter token and ID in the settings and switch **Discord** on.

Keys and tokens are stored in `.env` in the folder and are never handed to the model.

## What it may do

Switchable in the settings. On the first start:

| Feature | Start | What it does |
|---|---|---|
| Open programs | on | start programs, open addresses in the browser |
| Microphone | off | wake word, push-to-talk `Alt+Y`; also decides whether it speaks aloud |
| Watching | off | checks now and then what's in front; may take screenshots |
| Discord | off | DMs through your own bot (shown once a token is entered) |

Always there: chat in the window, memory, alarms, web search, reading files on disk (never
`.env`, SSH keys or the like). It can only write into its own memory.

The window also has time-limited switches: **Muted**, **Mic off**, **Always listening**,
**Not watching** and **Test run** (nothing goes into memory).

## Memory

A folder `memory\` of plain Markdown notes. Filing happens on the next start, before standby
or on "Remember". You can read and edit the notes in any editor; what a run overwrote lands
in `memory\_backup\`.

## Languages

Every word Lumen reads or says lives in `lumen\lang\`: one file per language (`en.py`,
`de.py`), a persona each (`persona_en.md`, `persona_de.md`) and a table for the window
(`en_ui.py`). A new language is a new set of files with the same keys — the start-up
self-check names any key that's missing.

## Where things live

| Folder | Contents |
|---|---|
| `lumen\` | the program |
| `memory\` | the memory |
| `data\` | conversation history, settings, attachments |
| `logs\` | the log — look here first when something's wrong |
| `tools\whisper\` | Whisper and its speech models |

The window runs at <http://127.0.0.1:8770> and only answers requests from its own page on
this computer.

## License

Copyright (C) 2026 Vevr Studios (Minerib)

Lumen is free software: you may use, change and share it under the terms of the
[GNU General Public License](LICENSE), version 3 or (at your option) any later version. If
you pass on a changed version, it has to be under the GPL too, with its source. It comes
with no warranty. Third-party code in this repository: [THIRD_PARTY.md](THIRD_PARTY.md).
