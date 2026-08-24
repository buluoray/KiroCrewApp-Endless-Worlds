"""Per-page timing of the backdrop pipeline, for auditing where the wait goes.

The backdrop for a page is produced by several steps that live in different
processes: the route that dispatches the illustrator, the illustrator's own tool
calls (trace → select → draft → commit), and a possible server-side fallback.
None of them alone could see the whole wall-clock, so "which step stuck the
longest" was unanswerable — the only signal was the 3-minute timeout firing.

This module records one append-only timeline per run, tagged by turn and step,
with the wall-clock instant of each event. The GAP between two consecutive events
is the thing worth reading: a long gap after ``tool:endless_trace_reference``
returned is the model thinking about which candidate to pick; a long gap with no
event at all is the model generating SVG markup before it submits. Server-side
work (the trace itself, the render) is recorded as its own measured duration on
the event, so the two are told apart rather than blurred into one number.

Best-effort throughout: a timing write must never fail or slow the tool it is
measuring, so every method swallows its own I/O errors. The log is diagnostic,
not load-bearing — nothing reads it to make a decision, only to explain one.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Same shape the other run-scoped stores accept, so a timeline can never be
#: opened on a path outside the run's own directory.
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: A page's timeline is bounded — a handful of tool calls plus recovery events —
#: but a wedged run that never commits could append forever. Cap the file so a
#: pathological run cannot grow it without bound; the newest events are the ones
#: an audit wants, so the cap drops the oldest.
_MAX_EVENTS = 400


class BackdropTimeline:
    """One run's append-only backdrop timing log."""

    def __init__(self, data_dir: Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
            raise ValueError(f"not a run id: {run_id!r}")
        self._path = data_dir / "runs" / run_id / "backdrop-timeline.jsonl"

    def mark(self, turn: int, step: str, **fields: Any) -> None:
        """Append one timeline event. Never raises: timing is diagnostic."""
        try:
            event: dict[str, Any] = {
                "turn": int(turn),
                "step": str(step),
                "at": round(time.time(), 3),
            }
            for key, value in fields.items():
                if value is not None:
                    event[key] = value
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 — timing must never break a tool
            logger.debug("backdrop timeline write failed for turn %s: %s", turn, exc)

    def read(self, turn: int) -> list[dict[str, Any]]:
        """The events for one turn, oldest first, each annotated with the gap in
        milliseconds since the previous event of that turn (``gapMs``).

        The gap is the audit's whole point: it is the time NOT spent inside a
        measured server step — i.e. the model thinking, generating, or reading
        previews between two tool calls.
        """
        events = [e for e in self._all() if int(e.get("turn", -1)) == int(turn)]
        events.sort(key=lambda e: float(e.get("at") or 0.0))
        prev: float | None = None
        for event in events:
            now = float(event.get("at") or 0.0)
            event["gapMs"] = None if prev is None else int((now - prev) * 1000)
            prev = now
        return events

    def events(self) -> list[dict[str, Any]]:
        """Every recorded event, oldest first — the perf page's join source."""
        return self._all()

    def _all(self) -> list[dict[str, Any]]:
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
        return out[-_MAX_EVENTS:]

    def clear(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass
