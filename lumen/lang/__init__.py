"""Every word the assistant or its window says, in one file per language.

Code asks for a text by key (`t("guard.muted")`); the language comes from the settings,
English unless someone chooses otherwise. A new language is a new file next to these two,
with the same keys -- the self-check refuses one that misses a key or a placeholder.

The window works the other way round (`UI`): its German wording is the key, and a language
file maps it to its own. German needs no table for that.
"""

import re
import string
from types import ModuleType

from lumen.lang import de, en

LANGS: dict[str, ModuleType] = {"en": en, "de": de}
DEFAULT = "en"
FOLDER = __path__[0]


def code() -> str:
    """The language in the settings. Imported late: `mode` must never need this module."""
    from lumen import mode
    chosen = mode.settings().get("language")
    return chosen if chosen in LANGS else DEFAULT


def pack(lang: str | None = None) -> ModuleType:
    return LANGS.get(lang or code(), LANGS[DEFAULT])


def t(key: str, lang: str | None = None, **values: object) -> str:
    """One text. A missing key raises -- a silent fallback would hide a typo in a prompt."""
    text = pack(lang).TEXT[key]
    return text.format(**values) if values else text


def persona(lang: str | None = None) -> str:
    with open(f"{FOLDER}/{pack(lang).PERSONA}", encoding="utf-8") as f:
        return f.read()


def _slots(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _self_check() -> None:
    """Same keys, same placeholders, everywhere -- or a prompt breaks only in one language."""
    keys = set(en.TEXT)
    for name, module in LANGS.items():
        assert set(module.TEXT) == keys, f"{name}: keys differ: {set(module.TEXT) ^ keys}"
        for key in keys:
            assert _slots(module.TEXT[key]) == _slots(en.TEXT[key]), f"{name}/{key}: placeholders differ"
        assert set(module.VOICES) == {"female", "male"}, f"{name}: one female and one male voice"
        assert all(v.startswith(module.SSML + "-") for v, _ in module.VOICES.values()), f"{name}: voice language"
        assert module.REGISTER in persona(name), f"{name}: the persona has no {module.REGISTER} mark"
        assert "{owner}" in persona(name) and "{name}" in persona(name), f"{name}: persona without names"
        assert re.fullmatch(r"[a-z]{2}", module.WHISPER), f"{name}: whisper wants a two-letter code"
    assert not de.UI, "German is the window's source text, it needs no table"
    assert t("time.minutes", "de", n=5) == "5 Minuten" and t("time.minutes", "en", n=5) == "5 minutes"
