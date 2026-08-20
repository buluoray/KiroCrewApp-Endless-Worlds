"""Player-chosen narrator settings: which model writes the story, and at what
reasoning effort.

A single small JSON at ``<data>/settings.json``. Deliberately NOT part of a run's
state — it is an app-wide preference the player sets once on the home page, applied
to every life's narrator slot at dispatch. Empty strings mean "leave the agent's
own default", so a fresh install narrates on ``auto`` with no effort override until
the player chooses otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The reasoning-effort levels the narrator may run at. Mirrors core's
#: ``kiro_crew.effort.EFFORT_LEVELS`` plus "" for "the model's default". Kept as a
#: local constant so the app validates without importing a dashboard-internal, but
#: the set is the one core accepts.
REASONING_EFFORTS: tuple[str, ...] = ("", "low", "medium", "high", "xhigh", "max")

_DEFAULT: dict[str, str] = {"model": "", "reasoningEffort": "", "painterModel": ""}


def _path(data_dir: Path) -> Path:
    return data_dir / "settings.json"


def read_settings(data_dir: Path) -> dict[str, str]:
    """The saved settings, or the empty defaults. A damaged file reads as default
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
    return {
        "model": model if isinstance(model, str) else "",
        "reasoningEffort": (
            effort if isinstance(effort, str) and effort in REASONING_EFFORTS else ""
        ),
        # The illustrator's model, chosen separately from the narrator's: drawing an
        # SVG is a different job than writing prose, and a player may want a cheaper
        # or faster model for the background art. Empty = inherit the agent default.
        "painterModel": painter if isinstance(painter, str) else "",
    }


def write_settings(
    data_dir: Path, *, model: str, reasoning_effort: str, painter_model: str = ""
) -> dict[str, str]:
    """Persist the settings (atomic tmp+rename). Returns what was written.

    ``reasoning_effort`` is validated against the known set; an unknown value is
    coerced to "" (the default) rather than smuggled onward — it becomes a
    subprocess argument downstream. ``model`` and ``painter_model`` are explicit
    picks from the advertised list, so they are stored verbatim (empty = inherit
    the agent default).
    """
    written = {
        "model": model if isinstance(model, str) else "",
        "reasoningEffort": reasoning_effort if reasoning_effort in REASONING_EFFORTS else "",
        "painterModel": painter_model if isinstance(painter_model, str) else "",
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = _path(data_dir).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(written, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path(data_dir))
    return written
