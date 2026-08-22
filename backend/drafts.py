"""World drafts: the paste-a-rulebook → clean-and-compile → review flow.

A draft is a life-in-miniature of the run store's own discipline (turn.py): the
record is written to disk BEFORE the worldsmith agent is dispatched, so a gateway
that dies mid-compile leaves a retryable draft rather than nothing, and the
player can leave the page and come back to a draft still being worked (mirrors
``store.mark_pending`` + the "generating" read path).

Two processes touch a draft and neither imports the other:

* the **backend route** process creates the draft, marks it pending, dispatches
  the worldsmith, and installs the accepted world;
* the **MCP server** process (a separate interpreter — see ``mcp_server.py``)
  is where the worldsmith reads the pasted prose and submits its compiled result.

So this module depends on nothing but the standard library and reaches the same
files from either side by being handed the data dir. The compile itself lives in
``compile.py`` and is called by the MCP handler, never here — this module only
stores what that call produced.

On disk::

    <data>/world-drafts/<draftId>/raw.md      the pasted text, verbatim
    <data>/world-drafts/<draftId>/record.json status, progress, result summary
    <data>/world-drafts/<draftId>/world.md    the accepted world file (once ready)
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

#: A draft id becomes a path segment and later a chat-slot key, so it is validated
#: the same way run ids and world ids are — before it can flow into either.
_DRAFT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: The pasted text is a whole rulebook — the shipped flagship is ~61 KB — but not
#: unbounded: a paste this large is a mistake or an attack, not a world.
MAX_RAW_BYTES = 400_000

#: A draft still "generating" past this age is treated as timed out on read, so a
#: gateway that died mid-compile shows a retryable failure instead of an eternal
#: spinner. Compiling a long rulebook is heavier than an opening turn, so this sits
#: well above the opening deadline (turn.OPENING_DEADLINE_SECS = 300).
STALE_SECS = 1200


class DraftError(ValueError):
    """A draft operation could not be completed. Names what and why."""


def new_draft_id() -> str:
    """A fresh, path-safe, slug-shaped id. Time-prefixed so a directory listing
    sorts oldest-first without reading every record."""
    return f"wd-{int(time.time())}-{secrets.token_hex(3)}"


def _valid_id(draft_id: str) -> str:
    if not isinstance(draft_id, str) or not _DRAFT_ID_RE.match(draft_id):
        raise DraftError(f"not a draft id: {draft_id!r}")
    return draft_id


class DraftStore:
    """Filesystem-backed store for world drafts. Handed the app data dir so the
    route process and the MCP process reach the same files."""

    def __init__(self, data_dir: Path | str) -> None:
        self._root = Path(data_dir) / "world-drafts"

    def _dir(self, draft_id: str) -> Path:
        return self._root / _valid_id(draft_id)

    # ── create / read raw ─────────────────────────────────────────────────

    def create(self, raw_text: str, *, title: str = "") -> str:
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise DraftError("a world needs some text to start from")
        size = len(raw_text.encode("utf-8"))
        if size > MAX_RAW_BYTES:
            raise DraftError(f"that text is too long ({size} bytes; max {MAX_RAW_BYTES})")
        draft_id = new_draft_id()
        d = self._dir(draft_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "raw.md").write_text(raw_text, encoding="utf-8")
        self._write_record(
            draft_id,
            {
                "draftId": draft_id,
                "title": title.strip(),
                "status": "new",  # not yet dispatched
                "createdAt": time.time(),
                "steps": 0,
                "lastTool": "",
                "stage": "",
            },
        )
        return draft_id

    def read_raw(self, draft_id: str) -> str:
        try:
            return (self._dir(draft_id) / "raw.md").read_text(encoding="utf-8")
        except FileNotFoundError:
            raise DraftError(f"no such draft: {draft_id}") from None

    def exists(self, draft_id: str) -> bool:
        return (self._dir(draft_id) / "record.json").exists()

    # ── record read / write ───────────────────────────────────────────────

    def _record_path(self, draft_id: str) -> Path:
        return self._dir(draft_id) / "record.json"

    def _write_record(self, draft_id: str, record: dict[str, Any]) -> None:
        path = self._record_path(draft_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _read_record(self, draft_id: str) -> dict[str, Any]:
        try:
            raw = self._record_path(draft_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise DraftError(f"no such draft: {draft_id}") from None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise DraftError(f"draft {draft_id} is corrupt") from None
        return data if isinstance(data, dict) else {}

    def patch(self, draft_id: str, **fields: Any) -> dict[str, Any]:
        """Read-modify-write a few fields. Last-writer-wins, but the two writers
        (route + MCP) touch disjoint fields in practice."""
        record = self._read_record(draft_id)
        record.update(fields)
        self._write_record(draft_id, record)
        return record

    def record(self, draft_id: str) -> dict[str, Any]:
        """The record with its status resolved: a draft that has been generating
        past STALE_SECS reads as failed, so a dead gateway self-heals."""
        record = self._read_record(draft_id)
        return self._resolve(record)

    def _resolve(self, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("status") == "generating":
            asked = float(record.get("askedAt") or 0)
            if asked and time.time() - asked > STALE_SECS:
                out = dict(record)
                out["status"] = "failed"
                out["problem"] = out.get("problem") or (
                    "the world took too long to compile — try again"
                )
                return out
        if record.get("status") == "new":
            # A draft is `new` only in the moment between creation and the compile
            # dispatch. One stuck here means the dispatch call was lost (client
            # navigated away, gateway refused the slot) — without this clause the
            # review screen polls a frozen progress bar forever.
            created = float(record.get("createdAt") or 0)
            if created and time.time() - created > STALE_SECS:
                out = dict(record)
                out["status"] = "failed"
                out["problem"] = out.get("problem") or ("the compile never started — try again")
                return out
        return record

    # ── lifecycle ─────────────────────────────────────────────────────────

    def mark_pending(self, draft_id: str) -> None:
        """Written BEFORE the worldsmith is dispatched (never after), so the
        draft reads as generating the instant the job is asked for."""
        self.patch(
            draft_id,
            status="generating",
            askedAt=time.time(),
            steps=0,
            lastTool="",
            stage="reading",
            problem="",
            field="",
        )

    def note_step(self, draft_id: str, tool: str, *, stage: str = "") -> None:
        """Best-effort progress bump, mirroring store.note_tool_call. Only counts
        while the draft is actually generating; never raises into a tool call."""
        try:
            record = self._read_record(draft_id)
        except DraftError:
            return
        if record.get("status") != "generating":
            return
        record["steps"] = int(record.get("steps") or 0) + 1
        record["lastTool"] = tool
        if stage:
            record["stage"] = stage
        try:
            self._write_record(draft_id, record)
        except OSError:
            pass

    def store_ready(
        self,
        draft_id: str,
        *,
        world_text: str,
        world_id: str,
        preview: dict[str, Any],
        warnings: list[str],
        referenced_paths: list[str],
        dropped: list[str] | None = None,
    ) -> None:
        (self._dir(draft_id) / "world.md").write_text(world_text, encoding="utf-8")
        self.patch(
            draft_id,
            status="ready",
            worldId=world_id,
            preview=preview,
            warnings=list(warnings or []),
            referencedPaths=list(referenced_paths or []),
            dropped=list(dropped or []),
            problem="",
            field="",
            stage="",
        )

    def store_failed(self, draft_id: str, problem: str, *, field: str = "") -> None:
        self.patch(draft_id, status="failed", problem=problem, field=field, stage="")

    def world_text(self, draft_id: str) -> str:
        try:
            return (self._dir(draft_id) / "world.md").read_text(encoding="utf-8")
        except FileNotFoundError:
            raise DraftError(f"draft {draft_id} has no compiled world yet") from None

    def mark_installed(self, draft_id: str, world_id: str) -> None:
        self.patch(draft_id, status="installed", worldId=world_id)

    def set_title(self, draft_id: str, title: str) -> dict[str, Any]:
        return self.patch(draft_id, title=str(title or "").strip())

    def delete(self, draft_id: str) -> None:
        d = self._dir(draft_id)
        for name in ("raw.md", "record.json", "record.json.tmp", "world.md"):
            try:
                (d / name).unlink()
            except FileNotFoundError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass

    def list(self) -> list[dict[str, Any]]:
        """All drafts, oldest-first (the id is time-prefixed). Installed drafts are
        omitted — once installed, the world itself is on the shelf."""
        if not self._root.exists():
            return []
        rows: list[dict[str, Any]] = []
        for child in sorted(self._root.iterdir()):
            if not child.is_dir():
                continue
            try:
                record = self._resolve(self._read_record(child.name))
            except DraftError:
                continue
            if record.get("status") in ("installed",):
                continue
            rows.append(_row(record))
        return rows


def _row(record: dict[str, Any]) -> dict[str, Any]:
    """The shelf-facing subset — enough to render a card and its progress."""
    return {
        "draftId": record.get("draftId", ""),
        "title": record.get("title") or "",
        "status": record.get("status", "new"),
        "steps": int(record.get("steps") or 0),
        "lastTool": record.get("lastTool") or "",
        "stage": record.get("stage") or "",
        "problem": record.get("problem") or "",
    }


def worldsmith_prompt(draft_id: str) -> str:
    """The dispatch prompt. Tiny on purpose — the worldsmith PULLS the pasted text
    with ``endless_read_draft`` rather than having a whole rulebook pushed into the
    transcript, the same pull-not-push discipline as the opening turn."""
    return (
        f"A player pasted raw text to turn into a new, playable world. "
        f"The draft id is {draft_id!r}.\n\n"
        f"1. Call endless_read_draft with that draftId to read the pasted text.\n"
        f"2. Clean it and compile it per your instructions: keep only what is "
        f"playable in this framework, drop anything that is not, and work out the "
        f"world's structure.\n"
        f"3. Call endless_submit_world_draft with that draftId, the cleaned rulebook "
        f"prose, and the compiled header.\n\n"
        f"When it is stored, reply with ONE short line and nothing else."
    )
