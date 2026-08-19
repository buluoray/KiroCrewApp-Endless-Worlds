"""Keepsakes — the player's meaning layer over the fact graph (design §8.2).

A keepsake never changes world facts: it cites them. It lives in the run's own
directory, so deleting a life takes its keepsakes with it (the run directory is
removed whole), and it is invisible to the narrator except as a slight recall
weight — the fact layer answers "发生过什么", this layer answers "什么对我重要".

Stored as one JSON file per run, replaced atomically. The design sketches a
``keepsakes.jsonl``; a whole-file JSON array with tmp+rename is chosen instead
because keepsakes are edited and deleted in place (a rename, a thought, a
removal), and an append-only log of player edits would need tombstone replay for
data a player never accumulates more than dozens of.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

#: What a keepsake points at. ``echo`` cites a whole declared echo path (the
#: current event and its source); ``event`` cites one; ``excerpt`` preserves the
#: player's own selected prose alongside the turn it came from.
KINDS = ("event", "echo", "excerpt")

MAX_TITLE = 120
MAX_THOUGHT = 1000
MAX_EXCERPT = 2000


class KeepsakeError(ValueError):
    """A caller mistake, with the field named so the route can answer 422."""

    def __init__(self, field: str, expected: str) -> None:
        super().__init__(f"{field}: {expected}")
        self.field = field
        self.expected = expected


class KeepsakeStore:
    """Per-run keepsake persistence. Reaches nothing but its own file."""

    def __init__(self, data_dir: Path, run_id: str) -> None:
        self._path = data_dir / "runs" / run_id / "keepsakes.json"

    # -- reads -------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt file loses the meaning layer, never the facts — and it
            # must not take the star map down with it.
            return []
        return raw if isinstance(raw, list) else []

    def get(self, keepsake_id: str) -> dict[str, Any] | None:
        for kp in self.list():
            if kp.get("id") == keepsake_id:
                return kp
        return None

    # -- writes ------------------------------------------------------------

    def create(
        self,
        *,
        kind: str,
        title: str,
        cites: list[str] | None = None,
        entities: list[str] | None = None,
        thought: str = "",
        excerpt: str = "",
        turn: int = 0,
        spoiler: bool = False,
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise KeepsakeError("kind", f"one of {', '.join(KINDS)}")
        title = title.strip()
        if not title or len(title) > MAX_TITLE:
            raise KeepsakeError("title", f"1–{MAX_TITLE} characters")
        if len(thought) > MAX_THOUGHT:
            raise KeepsakeError("thought", f"at most {MAX_THOUGHT} characters")
        if kind == "excerpt":
            if not excerpt.strip():
                raise KeepsakeError("excerpt", "the selected passage")
            if len(excerpt) > MAX_EXCERPT:
                raise KeepsakeError("excerpt", f"at most {MAX_EXCERPT} characters")
            if turn < 1:
                raise KeepsakeError("turn", "the turn the passage was selected from")
        elif not cites:
            raise KeepsakeError("cites", "at least one cited event id")

        kp: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "title": title,
            "thought": thought.strip(),
            "cites": [str(c) for c in cites or []],
            "entities": [str(e) for e in entities or []],
            "turn": int(turn),
            "spoiler": bool(spoiler),
            "createdAt": time.time(),
        }
        if kind == "excerpt":
            kp["excerpt"] = excerpt
            # The hash names exactly the text that was saved, so a later edit of
            # rendering (or of the player's memory) cannot silently drift what
            # the keepsake claims was on the page.
            kp["excerptSha256"] = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        rows = self.list()
        rows.append(kp)
        self._write(rows)
        return kp

    def update(self, keepsake_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Rename, edit the thought, or adjust spoiler — never the citations.

        The cited path is what makes a keepsake honest; editing it would turn a
        memento into a claim. To point at something else, make a new keepsake.
        """
        rows = self.list()
        for kp in rows:
            if kp.get("id") != keepsake_id:
                continue
            if "title" in changes:
                title = str(changes["title"]).strip()
                if not title or len(title) > MAX_TITLE:
                    raise KeepsakeError("title", f"1–{MAX_TITLE} characters")
                kp["title"] = title
            if "thought" in changes:
                thought = str(changes["thought"])
                if len(thought) > MAX_THOUGHT:
                    raise KeepsakeError("thought", f"at most {MAX_THOUGHT} characters")
                kp["thought"] = thought.strip()
            if "spoiler" in changes:
                kp["spoiler"] = bool(changes["spoiler"])
            self._write(rows)
            return kp
        return None

    def delete(self, keepsake_id: str) -> bool:
        rows = self.list()
        kept = [kp for kp in rows if kp.get("id") != keepsake_id]
        if len(kept) == len(rows):
            return False
        self._write(kept)
        return True

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)
