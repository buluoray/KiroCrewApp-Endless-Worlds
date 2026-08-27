"""Player-chosen app settings: which model writes the story, at what reasoning
effort — and how much of the visual layer runs at all.

A single small JSON at ``<data>/settings.json``. Deliberately NOT part of a run's
state — these are app-wide preferences the player sets once on the home page,
applied to every life at its next turn. Empty strings / defaults mean "leave the
app's own behavior", so a fresh install narrates on ``auto`` with full art until
the player chooses otherwise.

Every knob here is ENFORCED server-side (at the MCP tool gates and the choice
cleaner), never merely suggested to the narrator — a preference that depends on a
model remembering it is not a preference, it is a wish.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The reasoning-effort levels the narrator may run at. Mirrors core's
#: ``kiro_crew.effort.EFFORT_LEVELS`` plus "" for "the model's default". Kept as a
#: local constant so the app validates without importing a dashboard-internal, but
#: the set is the one core accepts.
REASONING_EFFORTS: tuple[str, ...] = ("", "low", "medium", "high", "xhigh", "max")

#: The painting styles a brief may declare — the same closed set ``_STYLE_RE``
#: parses. ``styles`` in the settings is the ENABLED subset: a brief declaring a
#: disabled style is rewritten to the preferred enabled one before the illustrator
#: ever sees it, and disabling ``photo`` also switches the trace pipeline off (no
#: archive search, no network).
PAINT_STYLES: tuple[str, ...] = ("photo", "watercolor", "oil", "minimal")

#: When picking a replacement for a disabled style, prefer the painterly ones —
#: watercolor first (the house favorite), photo last (it needs the network).
_STYLE_PREFERENCE: tuple[str, ...] = ("watercolor", "oil", "minimal", "photo")

#: How often the narrator's backdrop requests are honored. ``normal`` trusts the
#: narrator's own judgment; ``sparse`` adds a server-side floor of
#: ``SPARSE_GAP_TURNS`` turns between committed backdrops — art costs a model run,
#: and a player replaying long lives may prefer the tokens go to prose.
BACKDROP_CADENCES: tuple[str, ...] = ("normal", "sparse")

#: The minimum turns between accepted backdrop requests under ``sparse`` cadence.
SPARSE_GAP_TURNS = 5

#: Prose-length preferences the turn prompt relays to the narrator. "" keeps the
#: world's own pacing.
PROSE_LENGTHS: tuple[str, ...] = ("", "short", "long")

#: How much model time a page's art may spend. ``standard`` keeps the full
#: pipeline (two illustrator attempts, a preview review pass); ``fast`` caps it at
#: ONE attempt and tells the illustrator to publish its first competent draft —
#: the review pass ran ~3 minutes against ~60s of prose on measured pages, and a
#: player who wants the story over the gallery can trade polish for pace.
ART_QUALITIES: tuple[str, ...] = ("standard", "fast")

_DEFAULT: dict[str, Any] = {
    "model": "",
    "reasoningEffort": "",
    "painterModel": "",
    "backdrops": True,
    "styles": list(PAINT_STYLES),
    "backdropCadence": "normal",
    "choiceArt": True,
    "choiceEffects": True,
    "proseLength": "",
    "reducedMotion": False,
    "artQuality": "standard",
}


def _path(data_dir: Path) -> Path:
    return data_dir / "settings.json"


def _clean_styles(raw: Any) -> list[str]:
    """The validated enabled-style list. An empty or damaged value reads as ALL
    enabled: 'no styles' is not a state the UI offers, and failing open here keeps
    a hand-edited file from silently turning every page blank."""
    if not isinstance(raw, list):
        return list(PAINT_STYLES)
    kept = [s for s in PAINT_STYLES if s in raw]
    return kept or list(PAINT_STYLES)


def preferred_style(enabled: list[str]) -> str:
    """The style to substitute when a brief declares a disabled one."""
    for style in _STYLE_PREFERENCE:
        if style in enabled:
            return style
    return "watercolor"


def read_settings(data_dir: Path) -> dict[str, Any]:
    """The saved settings, or the defaults. A damaged file reads as default
    rather than raising — a preference is never worth failing a page over."""
    try:
        raw = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(_DEFAULT)
    if not isinstance(raw, dict):
        return dict(_DEFAULT)
    model = raw.get("model")
    effort = raw.get("reasoningEffort")
    painter = raw.get("painterModel")
    cadence = raw.get("backdropCadence")
    length = raw.get("proseLength")
    return {
        "model": model if isinstance(model, str) else "",
        "reasoningEffort": (
            effort if isinstance(effort, str) and effort in REASONING_EFFORTS else ""
        ),
        # The illustrator's model, chosen separately from the narrator's: drawing an
        # SVG is a different job than writing prose, and a player may want a cheaper
        # or faster model for the background art. Empty = inherit the agent default.
        "painterModel": painter if isinstance(painter, str) else "",
        # Missing (a pre-upgrade file) reads as the default True: art stays on
        # until the player turns it off, never the other way around.
        "backdrops": raw.get("backdrops") is not False,
        "styles": _clean_styles(raw.get("styles")),
        "backdropCadence": (
            cadence if isinstance(cadence, str) and cadence in BACKDROP_CADENCES else "normal"
        ),
        "choiceArt": raw.get("choiceArt") is not False,
        "choiceEffects": raw.get("choiceEffects") is not False,
        "proseLength": (length if isinstance(length, str) and length in PROSE_LENGTHS else ""),
        # Motion stays ON until the player turns it off, mirroring backdrops.
        "reducedMotion": raw.get("reducedMotion") is True,
        "artQuality": (
            raw.get("artQuality") if raw.get("artQuality") in ART_QUALITIES else "standard"
        ),
    }


def write_settings(
    data_dir: Path,
    *,
    model: str,
    reasoning_effort: str,
    painter_model: str = "",
    backdrops: bool = True,
    styles: list[str] | None = None,
    backdrop_cadence: str = "normal",
    choice_art: bool = True,
    choice_effects: bool = True,
    prose_length: str = "",
    reduced_motion: bool = False,
    art_quality: str = "standard",
) -> dict[str, Any]:
    """Persist the settings (atomic tmp+rename). Returns what was written.

    ``reasoning_effort`` is validated against the known set; an unknown value is
    coerced to "" (the default) rather than smuggled onward — it becomes a
    subprocess argument downstream. ``model`` and ``painter_model`` are explicit
    picks from the advertised list, so they are stored verbatim (empty = inherit
    the agent default). The enum-ish knobs coerce the same way: an unknown value
    stores the default, never the raw string.
    """
    written: dict[str, Any] = {
        "model": model if isinstance(model, str) else "",
        "reasoningEffort": reasoning_effort if reasoning_effort in REASONING_EFFORTS else "",
        "painterModel": painter_model if isinstance(painter_model, str) else "",
        "backdrops": bool(backdrops),
        "styles": _clean_styles(styles if styles is not None else list(PAINT_STYLES)),
        "backdropCadence": backdrop_cadence if backdrop_cadence in BACKDROP_CADENCES else "normal",
        "choiceArt": bool(choice_art),
        "choiceEffects": bool(choice_effects),
        "proseLength": prose_length if prose_length in PROSE_LENGTHS else "",
        "reducedMotion": bool(reduced_motion),
        "artQuality": art_quality if art_quality in ART_QUALITIES else "standard",
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = _path(data_dir).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(written, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path(data_dir))
    return written
