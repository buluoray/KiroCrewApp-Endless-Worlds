"""BackdropTimeline: the per-page timing log the backdrop audit reads."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from backdrop_timing import BackdropTimeline  # noqa: E402

_RUN = "a" * 32


def test_events_are_scoped_to_their_turn_and_ordered_with_gaps(tmp_path):
    """read() returns only the asked turn's events, oldest first, each annotated
    with the wait (``gapMs``) since the previous event — the audit's whole point."""
    tl = BackdropTimeline(tmp_path, _RUN)
    tl.mark(1, "requested", lane="scene")
    tl.mark(1, "tool:endless_trace_reference", serverMs=1200)
    tl.mark(2, "requested")  # a different page must not bleed in

    events = tl.read(1)
    assert [e["step"] for e in events] == ["requested", "tool:endless_trace_reference"]
    assert events[0]["gapMs"] is None, "the first event has no prior wait"
    assert events[1]["gapMs"] is not None, "the wait before the trace call is recorded"
    assert events[1]["serverMs"] == 1200
    assert events[0]["lane"] == "scene"

    assert [e["step"] for e in tl.read(2)] == ["requested"]


def test_reading_an_unknown_run_is_empty_not_an_error(tmp_path):
    assert BackdropTimeline(tmp_path, _RUN).read(1) == []


def test_a_bad_run_id_is_refused_at_construction(tmp_path):
    with pytest.raises(ValueError):
        BackdropTimeline(tmp_path, "../escape")


def test_a_write_never_raises_into_the_tool_path(tmp_path):
    """Timing is diagnostic: a failed write must not break the tool it measures."""
    tl = BackdropTimeline(tmp_path / "nonexistent-parent", _RUN)
    # No exception even though the parent path did not exist; mark() creates it.
    tl.mark(1, "requested")
    assert [e["step"] for e in tl.read(1)] == ["requested"]
