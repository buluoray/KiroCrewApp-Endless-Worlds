"""The scene ledger — what a mounted scene is, and nothing else.

This module exists to make a boundary structural rather than promised. The scene
tools need to record what is on screen, but they must not be able to touch run
state: panels, chronicle and facts change only at a turn boundary, because the
turn loop's idempotence and rewind both assume it. Giving the scene tools a
handle that can reach exactly one file is what makes "a scene call cannot write
panels" true by construction instead of by review.

Widget SPECS are stored; compiled HTML never is. A spec is what the app's own
compiler turns into markup later, which is what keeps "widget bytes are always
locally produced" true even for a world pack that came from someone else.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import UTC
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

logger = logging.getLogger(__name__)


def slugify_id(value: Any, fallback: str) -> str:
    """Coerce any string into the id-slug shape, or return ``fallback``.

    Lowercase, non-slug runs collapse to a single hyphen, leading/trailing hyphens
    trimmed, capped at 64 chars. This is the ONE place a mangled id is repaired, so
    the ledger key, the widget path, the scene URL and the compiled button all read
    the same slug — coercing at render time instead would let the button and the
    answer channel disagree about what a click means.
    """
    if isinstance(value, str):
        s = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
        s = re.sub(r"-+", "-", s).strip("-")[:64].strip("-")
        if s and _ID_RE.match(s):
            return s
    return fallback


def slugify_scene_id(value: Any) -> str:
    """The scene id as stored: a slug, always. Falls back to ``scene`` for an id
    that has no sluggable content at all."""
    return slugify_id(value, "scene")


def normalize_choice_ids(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``spec`` whose every ``choice`` element carries a valid,
    unique slug id.

    Normalized in the STORED spec once, at the mount/update boundary, so the three
    readers of a choice id — the stored spec, the compiled button's ``data-choice``,
    and the answer channel's offered set — can never disagree. A non-slug id is
    slugified; an unsluggable or colliding one becomes ``choice-{index}``.
    """
    if not isinstance(spec, dict):
        return spec
    elements = spec.get("elements")
    if not isinstance(elements, list):
        return spec
    out = dict(spec)
    new_elements: list[Any] = []
    seen: set[str] = set()
    for i, el in enumerate(elements):
        if isinstance(el, dict) and el.get("kind") == "choice":
            el = dict(el)
            cid = slugify_id(el.get("id"), f"choice-{i}")
            if cid in seen:
                cid = f"choice-{i}"
                while cid in seen:
                    cid = f"{cid}-x"
            seen.add(cid)
            el["id"] = cid
        new_elements.append(el)
    out["elements"] = new_elements
    return out


class SceneLedgerError(RuntimeError):
    pass


class StaleScene(SceneLedgerError):
    """An answer aimed at a mount that has been replaced."""


class AlreadyAnswered(SceneLedgerError):
    """First result only. A second is refused, never allowed to overwrite."""


class SceneLedger:
    """One run's mounted scenes, persisted as a single JSON file."""

    def __init__(self, data_dir: Path, run_id: str) -> None:
        self._run_id = self._check(run_id, "run id")
        self._path = data_dir / "runs" / self._run_id / "scenes.json"

    @staticmethod
    def _check(value: str, what: str) -> str:
        if not isinstance(value, str) or not _ID_RE.match(value):
            raise SceneLedgerError(f"not a {what}: {value!r}")
        return value

    # -- storage ----------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except ValueError as exc:
            # A damaged optional scene must not take down the life page. Preserve
            # the bytes for diagnosis; the next explicit mount replaces the empty
            # logical ledger through the normal atomic write path.
            logger.warning("scene ledger unreadable at %s: %s", self._path, exc)
            return {}
        except OSError as exc:
            # Permissions and device errors are operational failures, not corrupt
            # content. Hiding them as an empty scene would make repair impossible.
            raise SceneLedgerError(f"scene ledger unreadable: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    # -- the surface the scene tools get ---------------------------------

    def mount(
        self,
        scene_id: str,
        spec: dict[str, Any],
        *,
        asks: bool = False,
        region: str = "",
        label: str = "",
    ) -> str:
        """Mount a scene and return its nonce.

        A fresh nonce per mount is what makes a stale frame harmless: a scene that
        was remounted with a new question must not be answerable by a click that
        was aimed at the old one, and the frame cannot know it has been replaced.

        ``region`` groups the scene under one of the play page's system tabs on a
        phone (``status`` / ``world`` / ``pack`` / ``tasks``, or a custom bucket);
        ``label`` is the short tab/name shown for it. Both are optional and a bare
        remount keeps whatever the scene already had.
        """
        scene_id = slugify_scene_id(scene_id)
        if not isinstance(spec, dict):
            raise SceneLedgerError("a scene spec must be an object")
        self._reject_markup(spec)
        spec = normalize_choice_ids(spec)

        data = self._read()
        existing = data.get(scene_id) or {}
        nonce = secrets.token_hex(8)
        data[scene_id] = {
            "spec": spec,
            "asks": asks,
            "nonce": nonce,
            "region": str(region or existing.get("region") or ""),
            "label": str(label or existing.get("label") or ""),
            # A remount clears a stale answer: the question on screen is new, so
            # an answer to the previous one is not an answer to this.
            "answer": None,
            "mountedAt": existing.get("mountedAt") or _now(),
            "updatedAt": _now(),
            "failures": [],
        }
        self._write(data)
        return nonce

    def nonce(self, scene_id: str) -> str:
        scene_id = slugify_scene_id(scene_id)
        entry = self._read().get(scene_id)
        if not isinstance(entry, dict):
            raise SceneLedgerError(f"no mounted scene {scene_id!r}")
        return str(entry.get("nonce") or "")

    def update(self, scene_id: str, spec: dict[str, Any]) -> None:
        scene_id = slugify_scene_id(scene_id)
        if not isinstance(spec, dict):
            raise SceneLedgerError("a scene spec must be an object")
        self._reject_markup(spec)
        spec = normalize_choice_ids(spec)

        data = self._read()
        if scene_id not in data:
            # Upsert: an update to a scene that is not mounted becomes a mount with
            # a fresh nonce, rather than a refusal the narrator cannot recover from.
            self.mount(scene_id, spec)
            return
        entry = dict(data[scene_id])
        entry["spec"] = spec
        entry["updatedAt"] = _now()
        data[scene_id] = entry
        self._write(data)

    def dismiss(self, scene_id: str) -> None:
        scene_id = slugify_scene_id(scene_id)
        data = self._read()
        if data.pop(scene_id, None) is None:
            return  # already gone; dismissing twice is not an error
        self._write(data)

    def answer(self, scene_id: str) -> Any:
        scene_id = slugify_scene_id(scene_id)
        entry = self._read().get(scene_id)
        if not isinstance(entry, dict):
            raise SceneLedgerError(f"no mounted scene {scene_id!r}")
        return entry.get("answer")

    def spec(self, scene_id: str) -> dict[str, Any]:
        """The stored spec. Read-only by construction — the compiler is handed a
        copy, so a compile pass cannot edit what the narrator declared."""
        scene_id = slugify_scene_id(scene_id)
        entry = self._read().get(scene_id)
        if not isinstance(entry, dict):
            raise SceneLedgerError(f"no mounted scene {scene_id!r}")
        spec = entry.get("spec")
        return dict(spec) if isinstance(spec, dict) else {}

    def mounted(self) -> list[dict[str, Any]]:
        """What is on screen right now, spec included so the narrator can see
        what it already showed rather than re-describing it from memory."""
        return [
            {
                "sceneId": sid,
                "asks": bool(e.get("asks")),
                "answered": e.get("answer") is not None,
                "region": str(e.get("region") or ""),
                "label": str(e.get("label") or ""),
            }
            for sid, e in sorted(self._read().items())
            if isinstance(e, dict)
        ]

    # -- the player's side (written by the app, not by the narrator) ------

    def record_answer(self, scene_id: str, answer: Any, *, nonce: str = "") -> None:
        """Store what the player did. Called by the app's own result channel,
        never by a narrator tool — which is why it is not reachable from any
        handler in ``mcp_server``.

        Enforces the two rules a result channel cannot leave to its caller:

        * the nonce must match this mount, so a click aimed at a replaced scene
          cannot answer the one that took its place
        * **first result only.** A second answer is refused rather than
          overwritten: the narrator may already have read the first, so letting a
          later message replace it would rewrite a decision the story has acted on.
        """
        scene_id = slugify_scene_id(scene_id)
        data = self._read()
        entry = data.get(scene_id)
        if not isinstance(entry, dict):
            raise SceneLedgerError(f"no mounted scene {scene_id!r}")
        if nonce and str(entry.get("nonce") or "") != nonce:
            raise StaleScene(f"{scene_id}: this answer was aimed at a scene that is gone")
        if entry.get("answer") is not None:
            raise AlreadyAnswered(f"{scene_id}: already answered")

        entry = dict(entry)
        entry["answer"] = answer
        entry["answeredAt"] = _now()
        data[scene_id] = entry
        self._write(data)

    def record_failure(self, scene_id: str, reason: str) -> None:
        """A rejected result, kept where the narrator can be told about it.

        Recorded rather than only logged, and recorded WITHOUT touching the
        answer: R20 asks that anything malformed leaves a trace and writes no
        state, and a failure that only reached a log file is a failure the story
        never learns about.
        """
        scene_id = slugify_scene_id(scene_id)
        data = self._read()
        entry = data.get(scene_id)
        if not isinstance(entry, dict):
            return  # nothing to attach it to; the scene is gone
        entry = dict(entry)
        failures = entry.get("failures")
        failures = list(failures) if isinstance(failures, list) else []
        # Bounded: a hostile page could otherwise grow this file without limit.
        failures = (failures + [{"reason": reason, "at": _now()}])[-10:]
        entry["failures"] = failures
        data[scene_id] = entry
        self._write(data)

    def failures(self, scene_id: str) -> list[dict[str, Any]]:
        scene_id = slugify_scene_id(scene_id)
        entry = self._read().get(scene_id)
        if not isinstance(entry, dict):
            return []
        raw = entry.get("failures")
        return [f for f in raw if isinstance(f, dict)] if isinstance(raw, list) else []

    # -- invariants -------------------------------------------------------

    @staticmethod
    def _reject_markup(spec: dict[str, Any]) -> None:
        """A spec carrying markup is refused.

        The whole trust story is that model bytes never reach the DOM: the
        backend compiles a spec into HTML. A spec that smuggles ``html`` in would
        route around that, so it is refused here rather than stripped — stripping
        would silently discard something the narrator believed it had sent.
        """
        for banned in ("html", "innerHTML", "script", "srcdoc"):
            if banned in spec:
                raise SceneLedgerError(
                    f"a scene spec may not carry {banned!r}; describe what to show"
                )


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()
