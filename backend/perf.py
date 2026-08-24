"""Per-turn performance ledger — what a month actually cost.

One append-only ``perf.jsonl`` per run, same shape of contract as the backdrop
timeline beside it: rows are diagnostic, writes never raise, and TWO processes
append (the MCP server owns the ``commit`` row because only it sees the commit
happen; the gateway owns the ``context`` and ``rotation`` rows because only it
can see the narrator slot's context meter and the reset branches). Append-only
lines are how the backdrop timeline already shares a file across the same two
processes.

Credits deliberately do not appear here: the harness exposes no billing signal
to an app, so tokens are the honest proxy and are labelled as such wherever the
page shows them. Inventing a dollar figure from tokens would be a number the
audit could never reconcile with a bill.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")

#: Newest rows are the ones an audit wants; a wedged run cannot grow the file
#: without bound. Two rows per committed turn plus occasional rotation rows
#: makes this roughly 250 turns of history.
_MAX_ROWS = 600


class TurnPerf:
    """One run's append-only per-turn performance rows."""

    def __init__(self, data_dir: Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
            raise ValueError(f"not a run id: {run_id!r}")
        self._path = data_dir / "runs" / run_id / "perf.jsonl"

    def mark(self, turn: int, step: str, **fields: Any) -> None:
        """Append one row. Never raises: performance bookkeeping is diagnostic."""
        try:
            row: dict[str, Any] = {
                "turn": int(turn),
                "step": str(step),
                "at": round(time.time(), 3),
            }
            for key, value in fields.items():
                if value is not None:
                    row[key] = value
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 — must never break the turn it measures
            logger.debug("perf row write failed for turn %s: %s", turn, exc)

    def rows(self) -> list[dict[str, Any]]:
        """All rows, oldest first, capped at the newest ``_MAX_ROWS``."""
        if not self._path.is_file():
            return []
        out: list[dict[str, Any]] = []
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue
                if isinstance(parsed, dict):
                    out.append(parsed)
        except OSError:
            return []
        return out[-_MAX_ROWS:]


def art_spans(timeline_events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Per-turn art timing derived from the backdrop timeline's existing rows.

    Derived at read time rather than recorded twice: the timeline is already the
    authority on what the art lane did, and a second recording of the same span
    is a second place for the two to disagree. A turn's span runs from its
    ``requested`` row to its last terminal row — a commit (illustrator or
    fallback) — and reports which terminal it was; a turn with a request and no
    terminal yet is in flight and reported without a duration.
    """
    by_turn: dict[int, dict[str, Any]] = {}
    for event in timeline_events:
        try:
            turn = int(event.get("turn", -1))
            at = float(event.get("at") or 0.0)
        except (TypeError, ValueError):
            continue
        step = str(event.get("step") or "")
        slot = by_turn.setdefault(turn, {})
        if step == "requested":
            # First request wins: a re-request mid-turn extends the same page.
            slot.setdefault("requestedAt", at)
        elif step in ("tool:endless_commit_backdrop", "tool:endless_commit_fallback_backdrop"):
            slot["committedAt"] = at
            slot["outcome"] = "fallback" if "fallback" in step else "committed"
    spans: dict[int, dict[str, Any]] = {}
    for turn, slot in by_turn.items():
        asked = slot.get("requestedAt")
        if asked is None:
            continue
        done = slot.get("committedAt")
        span: dict[str, Any] = {"outcome": slot.get("outcome") or "pending"}
        if done is not None and done >= asked:
            span["artMs"] = int((done - asked) * 1000)
        spans[turn] = span
    return spans


def aggregate(
    perf_rows: list[dict[str, Any]], timeline_events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One row per committed turn, joining both writers' rows with the art lane.

    The ``commit`` row anchors a turn (no commit row → the turn predates this
    ledger and is left out rather than shown half-empty); ``context`` and
    ``rotation`` rows annotate it; art timing joins from the backdrop timeline.
    """
    turns: dict[int, dict[str, Any]] = {}
    for row in perf_rows:
        try:
            turn = int(row.get("turn", -1))
        except (TypeError, ValueError):
            continue
        step = str(row.get("step") or "")
        if step == "commit":
            entry = turns.setdefault(turn, {"turn": turn})
            for key in ("storyMs", "readMs", "form", "declaredBytes", "toolCalls", "at"):
                if key in row:
                    entry[key] = row[key]
        elif step == "context":
            entry = turns.setdefault(turn, {"turn": turn})
            for key in ("pct", "usedTokens", "windowTokens", "model"):
                if key in row:
                    entry[key] = row[key]
        elif step == "rotation":
            entry = turns.setdefault(turn, {"turn": turn})
            entry["rotation"] = row.get("reason") or "rotated"
    art = art_spans(timeline_events)
    for turn, span in art.items():
        if turn in turns:
            turns[turn].update(span)
    return [turns[t] for t in sorted(turns) if "at" in turns[t] or "rotation" in turns[t]]
