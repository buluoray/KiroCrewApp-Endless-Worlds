"""Agent-authored background art as an inert SVG image.

This is the ONE place the app accepts drawing markup from the narrator instead of
a declared spec (contrast ``widget.py``). It is safe because the markup is served
and shown as an **image** (`<img>`), never as a live document:

* an SVG loaded in an ``<img>`` runs in a NON-SCRIPTED context — ``<script>`` and
  ``on*=`` handlers never execute and external resource loads are disabled — so the
  narrator's SVG cannot run code or exfiltrate anything, with or without a sandbox;
* the page lays the image BEHIND the prose with ``pointer-events: none``, so a
  background that draws a fake control cannot be clicked or cover the real one.

An earlier version wrapped the markup in a sandboxed ``<iframe srcdoc>``. iOS
Safari blank-rendered that frame (empty-sandbox srcdoc, then size-collapse), which
showed as a flat grey background on iPhone. An ``<img>`` renders and sizes
reliably on every browser, so the visual bug and the whole sandbox/CSP surface
both go away — the image context is a stronger boundary than the sandbox was.

A background is decoration: SVG gradients, patterns, and filters. That is all it
needs, so the format is a single self-contained SVG document. Refused as defense
in depth (the image context already neuters them, but the narrator is told, not
silently stripped):

* ``<script>``, ``on*=`` handlers, ``javascript:`` — execution.
* ``<foreignObject>`` — it can embed arbitrary HTML/JS inside the SVG.
* ``<image>``/``<use>``/``href`` pointing off-box (``http(s):`` or protocol-relative)
  — an external fetch. Only self-contained drawing is allowed.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

#: A background is decoration, not a document. Past this it is not a mood.
MAX_BACKDROP_BYTES = 24_000

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'

#: Substrings refused outright (scanned case-insensitively).
_FORBIDDEN_SUBSTRINGS = (
    "<script",
    "<foreignobject",
    "javascript:",
    "<iframe",
    "<html",
    "<body",
)

#: An inline event handler attribute (``onclick=``, ``onload=`` …). At least one
#: letter between ``on`` and ``=`` so ordinary attributes never match.
_HANDLER_RE = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)

#: A reference that leaves the document — an external fetch dressed as a link.
_EXTERNAL_REF_RE = re.compile(r'(?:xlink:href|href)\s*=\s*["\']?\s*(?:https?:|//)', re.IGNORECASE)


class BackdropError(ValueError):
    """A background that cannot be used. Names what was wrong so the narrator can
    fix the one thing, rather than guessing."""


def compile_backdrop(svg: str) -> str:
    """Validate narrator SVG and return it ready to serve as an image.

    The SVG is NOT escaped — it is authored art. Safety is the image context it is
    served into plus this denylist as defense in depth. A missing ``xmlns`` is
    injected rather than rejected, because a data/image-loaded SVG will not render
    without it and forgetting it is an easy mistake, not an attack.
    """
    if not isinstance(svg, str) or not svg.strip():
        raise BackdropError("a background needs an SVG image")

    size = len(svg.encode("utf-8"))
    if size > MAX_BACKDROP_BYTES:
        raise BackdropError(
            f"a background is at most {MAX_BACKDROP_BYTES} bytes, got {size}"
        )

    low = svg.lower()
    if "<svg" not in low:
        raise BackdropError(
            "a background must be a single SVG image (a <svg>…</svg> document)"
        )
    for banned in _FORBIDDEN_SUBSTRINGS:
        if banned in low:
            raise BackdropError(
                f"a background may not contain {banned!r} — it is a self-contained "
                "SVG drawing, never script, HTML, or a nested document"
            )
    if _HANDLER_RE.search(svg):
        raise BackdropError("a background may not carry an inline event handler (on…=)")
    if _EXTERNAL_REF_RE.search(svg):
        raise BackdropError(
            "a background may not link to an external resource — draw it inline"
        )

    # A data/image-loaded SVG needs the namespace declared on its root or it will
    # not render. Inject it when the narrator left it off the first <svg>.
    if "xmlns=" not in low[: low.index("<svg") + 200]:
        svg = re.sub(r"<svg\b", f"<svg {_SVG_NS}", svg, count=1, flags=re.IGNORECASE)

    # A very common narrator mistake: using an `xlink:` attribute (e.g. on a SMIL
    # <animate>) without declaring the xlink namespace. That is an UNDECLARED prefix,
    # which makes the SVG malformed XML — so an <img> cannot decode it and the player
    # sees a broken-image glyph instead of the emblem. Declare it for them rather
    # than reject art that is otherwise fine.
    if "xlink:" in low and "xmlns:xlink" not in low:
        svg = re.sub(
            r"<svg\b",
            '<svg xmlns:xlink="http://www.w3.org/1999/xlink"',
            svg, count=1, flags=re.IGNORECASE,
        )

    # Well-formedness is the last gate. The denylist above catches dangerous
    # content; this catches BROKEN content — an unclosed tag, a stray entity, a
    # prefix still undeclared — which renders as a broken image rather than a
    # picture. Rejecting here means a bad backdrop is refused at the call, and a bad
    # choice `art` is DROPPED by _clean_choices, so neither ever ships as a broken
    # glyph. Parsed after the injections above so a merely-missing xmlns is repaired,
    # not rejected.
    try:
        ET.fromstring(svg)
    except ET.ParseError as exc:
        raise BackdropError(f"the SVG is not well-formed and would not render ({exc})") from None
    return svg


class BackdropStore:
    """One run's current background, persisted as a single JSON file.

    Like the scene ledger, this is a handle that can reach exactly one file and
    nothing else: a backdrop call can never touch panels, chronicle, or facts,
    because it is never handed anything that could. A run has at most one
    background at a time — setting a new one replaces the old.
    """

    def __init__(self, data_dir: Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not _ID_RE.match(run_id):
            raise BackdropError(f"not a run id: {run_id!r}")
        self._path = data_dir / "runs" / run_id / "backdrop.json"

    def _load(self) -> list[dict[str, Any]]:
        """The backdrop history, oldest-first. Each entry is
        ``{turn, markup, buttons?, version}``; an entry with empty ``markup`` is a
        tombstone (the narrator cleared the background at that turn). Migrates the
        old single-object format to a one-entry history, and treats a corrupt file
        as no history rather than an error that would break the play view."""
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if isinstance(data, dict) and isinstance(data.get("history"), list):
            entries = data["history"]
        elif isinstance(data, dict) and isinstance(data.get("markup"), str):
            # Pre-history format: one current backdrop. Treat it as set at turn 0.
            entries = [dict(data, turn=0)]
        else:
            return []
        out: list[dict[str, Any]] = []
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("version"), int):
                out.append(e)
        return out

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"history": entries}, ensure_ascii=False)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)

    @staticmethod
    def _view(entry: dict[str, Any] | None) -> dict[str, Any] | None:
        """Shape an entry as ``{markup, version, buttons}``, or ``None`` for a
        tombstone (empty markup) or a missing entry."""
        if not entry:
            return None
        markup = entry.get("markup")
        version = entry.get("version")
        if not isinstance(markup, str) or not markup.strip() or not isinstance(version, int):
            return None
        buttons = entry.get("buttons")
        return {
            "markup": markup,
            "version": version,
            "buttons": buttons if isinstance(buttons, str) and buttons.strip() else None,
        }

    def current(self) -> dict[str, Any] | None:
        """The LATEST background as ``{markup, buttons, version}``, or ``None`` when
        unset/cleared/unreadable. This is what the home shelf and the live play page
        want — the most recent scene."""
        history = self._load()
        return self._view(history[-1]) if history else None

    def at(self, turn: int) -> dict[str, Any] | None:
        """The background effective on ``turn`` — the latest one set at a turn ≤ it,
        since a backdrop persists until the narrator changes it. ``None`` if the page
        predates any backdrop, or the effective one is a tombstone (cleared)."""
        chosen: dict[str, Any] | None = None
        for e in self._load():
            if int(e.get("turn") or 0) <= turn:
                chosen = e
            else:
                break
        return self._view(chosen)

    def version_at(self, turn: int) -> int:
        """The version effective on ``turn`` (0 when the page has no background). Used
        to stamp each chronicle turn so the history reader restores that page's
        scene and caches it correctly."""
        view = self.at(turn)
        return int(view["version"]) if view else 0

    def set(self, markup: str, buttons: str | None = None, turn: int = 0) -> int:
        """Validate and append a background (and its optional common button motif),
        stamped with the ``turn`` it belongs to, returning the version.

        Bound to the page: re-reading turn N restores the background set at N (or the
        latest before it). Setting twice on the same turn replaces that page's entry
        rather than stacking two. Both SVGs are validated here so the narrator is
        refused at the call it made, not later at render — a rejected background never
        becomes stored — and the button motif travels WITH the backdrop, so a page's
        buttons always match its scene.
        """
        clean_markup = compile_backdrop(markup)  # raises BackdropError on bad input
        clean_buttons = (
            compile_backdrop(buttons)
            if isinstance(buttons, str) and buttons.strip()
            else None
        )
        history = self._load()
        version = (max(int(e.get("version") or 0) for e in history) + 1) if history else 1
        entry: dict[str, Any] = {"turn": int(turn), "markup": clean_markup, "version": version}
        if clean_buttons:
            entry["buttons"] = clean_buttons
        if history and int(history[-1].get("turn") or 0) == int(turn):
            history[-1] = entry  # a second set on the same page replaces it
        else:
            history.append(entry)
        self._save(history)
        return version

    def clear(self, turn: int = 0) -> None:
        """Clear the background FROM this turn onward, keeping earlier pages' scenes.

        Recorded as a tombstone rather than deleting the file, so re-reading a page
        before the clear still restores its backdrop while the live page and home
        show none. Idempotent — clearing when nothing is showing on this page is a
        no-op."""
        history = self._load()
        if self.at(turn) is None:
            return  # nothing effective here to clear
        version = max(int(e.get("version") or 0) for e in history) + 1
        tomb: dict[str, Any] = {"turn": int(turn), "markup": "", "version": version}
        if int(history[-1].get("turn") or 0) == int(turn):
            history[-1] = tomb
        else:
            history.append(tomb)
        self._save(history)

