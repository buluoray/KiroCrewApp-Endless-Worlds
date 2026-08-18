"""Text the narrator is spoken to in, keyed by language.

The world pack decides the language. That is not a preference setting: a world
whose header says ``language: zh`` is a Chinese world, its rulebook is Chinese
prose, and asking its narrator for a turn in English would produce a story in the
wrong language for its own source material. So the language travels with the world
pack, and every prompt this app composes is looked up by it.

Keeping the text in JSON rather than in these modules does two things at once. It
keeps the code free of any one language, and it makes a missing translation a
visible gap in a data file instead of a hardcoded string nobody can find.

English is the fallback because it is the table guaranteed to be complete: a key
absent from a language surfaces as English rather than as a blank prompt line,
which would silently drop an instruction the narrator needed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

#: The languages this app has text for. A world declaring anything else is played
#: with the fallback rather than refused — a world is not broken for being written
#: in a language the app has not been translated into yet.
LANGUAGES: tuple[str, ...] = ("en", "zh")

FALLBACK = "en"

_CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


class ContentError(RuntimeError):
    pass


@lru_cache(maxsize=len(LANGUAGES))
def _table(lang: str) -> dict[str, str]:
    path = _CONTENT_DIR / f"{lang}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContentError(f"no content table for {lang!r}") from exc
    except ValueError as exc:
        raise ContentError(f"content table {lang!r} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContentError(f"content table {lang!r} must be an object")
    return {k: str(v) for k, v in raw.items()}


def resolve(language: Any) -> str:
    """The language actually used for a world's ``language`` value."""
    return language if language in LANGUAGES else FALLBACK


class Content:
    """One language's text, with English behind it."""

    def __init__(self, language: Any = FALLBACK) -> None:
        self.language = resolve(language)
        self._table = _table(self.language)
        self._fallback = _table(FALLBACK) if self.language != FALLBACK else self._table

    def __call__(self, key: str, /, **vars: Any) -> str:
        """One line, with ``{name}`` placeholders filled in.

        ``key`` is positional-only, and that matters: a caller filling a
        placeholder literally named ``key`` (``text("turn.state.group", key=...)``)
        would otherwise collide with this parameter and raise. The placeholder
        names come from the content tables, so they cannot be constrained — the
        signature has to get out of their way.

        A missing key returns the key itself rather than an empty string: a prompt
        containing ``turn.ask`` is obviously broken, while a prompt with a silent
        gap where an instruction should be reads as a complete prompt that simply
        never asked for anything.

        An unknown placeholder is left as-is for the same reason — visible, and
        never mistaken for prose.
        """
        raw = self._table.get(key) or self._fallback.get(key) or key
        out = raw
        for name, value in vars.items():
            out = out.replace("{" + name + "}", str(value))
        return out
