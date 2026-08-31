"""Per-turn performance ledger — what a month actually cost.

One append-only ``perf.jsonl`` per run, same shape of contract as the backdrop
timeline beside it: rows are diagnostic, writes never raise, and TWO processes
append (the MCP server owns the ``commit`` row because only it sees the commit
happen; the gateway owns the ``context`` and ``rotation`` rows because only it
can see the narrator slot's context meter and the reset branches). Append-only
lines are how the backdrop timeline already shares a file across the same two
processes.

Credits are deliberately never RECORDED here: the host's usage ledger is the
one authority on billing, and a second copy would be a second place for the two
to disagree. When the host exposes a per-turn usage reader, :func:`join_usage`
attaches each turn's credits at read time; when it does not, the page falls
back to tokens and labels them as the proxy they are.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import datetime
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


#: The rows that END a turn's art span, and whether reaching one counts as a
#: fallback. All three publish a real backdrop; they differ only in who drew it —
#: the illustrator, the narrator by hand, or the server from the traced underlay
#: after the model's budget ran out. The server's row is a terminal like the other
#: two: leaving it out does not merely mislabel such a turn, it leaves the span
#: open forever, so the page reports the art as still being painted and never
#: reports how long it took — on exactly the slow turns an audit is opened for.
_ART_TERMINALS: dict[str, str] = {
    "tool:endless_commit_backdrop": "committed",
    "tool:endless_commit_fallback_backdrop": "fallback",
    "server-fallback-commit": "fallback",
}


def art_spans(timeline_events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Per-turn art timing derived from the backdrop timeline's existing rows.

    Derived at read time rather than recorded twice: the timeline is already the
    authority on what the art lane did, and a second recording of the same span
    is a second place for the two to disagree. A turn's span runs from its
    ``requested`` row to its last terminal row — a commit by whoever drew it —
    and reports which terminal it was; a turn with a request and no terminal yet
    is in flight and reported without a duration.
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
        elif step in _ART_TERMINALS:
            slot["committedAt"] = at
            slot["outcome"] = _ART_TERMINALS[step]
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
            for key in ("storyMs", "readMs", "form", "declaredBytes", "toolCalls", "tools", "at"):
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


#: A turn's usage row is written when the narrator's conversation turn ENDS,
#: which trails the commit by however long the closing narration and the art
#: hand-off take. Beyond this gap the row cannot be confidently attributed.
_USAGE_JOIN_CAP_SECS = 1800.0


def _usage_epoch(raw: Any) -> float | None:
    """A usage row's ``ts`` as an epoch, or ``None`` when unparseable.

    Mirrors the host ledger's own spelling (``Z`` rewritten to ``+00:00``; a
    naive stamp read in local time via ``.timestamp()``) so both sides date a
    row identically.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts_str = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        return datetime.fromisoformat(ts_str).timestamp()
    except ValueError:
        return None


def join_usage(
    turns: list[dict[str, Any]], usage_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach per-turn ``credits``/``cost`` from the host's usage ledger.

    A ledger row marks when a conversation turn ENDED; a perf row's ``at``
    marks when the turn COMMITTED. The turn that committed is the next row to
    end, so the join walks both lists oldest-first and gives each committed
    turn the first unclaimed row at or after its commit — bounded by
    ``_USAGE_JOIN_CAP_SECS`` and by the next turn's commit, so a missing row
    (window expired, ledger gap) leaves its turn blank instead of stealing the
    following turn's row. Rows before a turn's commit are skipped, not
    claimed: those are earlier turns or injected recovery turns in the same
    conversation, which commit nothing.

    Mutates and returns ``turns``. Turns without a numeric ``at`` (rotation-only
    rows) are never credited.
    """
    dated: list[tuple[float, dict[str, Any]]] = []
    for row in usage_rows:
        ts = _usage_epoch(row.get("ts"))
        if ts is not None:
            dated.append((ts, row))
    dated.sort(key=lambda pair: pair[0])
    committed = [
        t
        for t in turns
        if isinstance(t.get("at"), (int, float)) and not isinstance(t.get("at"), bool)
    ]
    committed.sort(key=lambda t: float(t["at"]))
    i = 0
    for idx, turn in enumerate(committed):
        at = float(turn["at"])
        while i < len(dated) and dated[i][0] < at:
            i += 1
        if i >= len(dated):
            break
        ts, row = dated[i]
        if ts - at > _USAGE_JOIN_CAP_SECS:
            continue
        if idx + 1 < len(committed) and ts >= float(committed[idx + 1]["at"]):
            continue
        for field in ("credits", "cost"):
            value = row.get(field)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) or (isinstance(value, float) and math.isfinite(value)):
                turn[field] = value
        i += 1
    return turns
