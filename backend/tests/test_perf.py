"""Guards on the per-turn performance ledger.

Two processes append rows (the MCP server owns ``commit``, the gateway owns
``context`` and ``rotation``), the backdrop timeline is joined at read time
rather than recorded twice, and every write is advisory — a failed row must
never fail the turn it measures. Tokens are the declared credit proxy; the
route says so in ``creditNote`` so the page can never silently dress tokens up
as money.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from perf import TurnPerf, aggregate, art_spans  # noqa: E402

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
勇者不总是赢。
"""


@pytest.fixture()
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    return data


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


# ── unit: the art join ───────────────────────────────────────────────────────


def test_art_spans_join_request_to_commit():
    events = [
        {"turn": 3, "step": "requested", "at": 100.0},
        {"turn": 3, "step": "tool:endless_paint_backdrop", "at": 101.0},
        {"turn": 3, "step": "tool:endless_commit_backdrop", "at": 130.5},
        {"turn": 4, "step": "requested", "at": 200.0},
        {"turn": 4, "step": "tool:endless_commit_fallback_backdrop", "at": 260.0},
        {"turn": 5, "step": "requested", "at": 300.0},
    ]
    spans = art_spans(events)
    assert spans[3] == {"outcome": "committed", "artMs": 30500}
    assert spans[4] == {"outcome": "fallback", "artMs": 60000}
    assert spans[5] == {"outcome": "pending"}, "an uncommitted request has no duration"


def test_art_spans_first_request_wins():
    events = [
        {"turn": 3, "step": "requested", "at": 100.0},
        {"turn": 3, "step": "requested", "at": 120.0},
        {"turn": 3, "step": "tool:endless_commit_backdrop", "at": 130.0},
    ]
    assert art_spans(events)[3]["artMs"] == 30000


# ── unit: the two-writer aggregation ─────────────────────────────────────────


def test_aggregate_joins_both_writers_and_the_art_lane():
    rows = [
        {
            "turn": 2,
            "step": "commit",
            "at": 50.0,
            "storyMs": 42000,
            "readMs": 3000,
            "form": "patch",
            "declaredBytes": 300,
            "toolCalls": 4,
        },
        {"turn": 2, "step": "context", "at": 51.0, "pct": 37, "usedTokens": 74000},
        {"turn": 3, "step": "rotation", "at": 60.0, "reason": "chapter"},
        {"turn": 3, "step": "commit", "at": 99.0, "storyMs": 30000},
    ]
    events = [
        {"turn": 2, "step": "requested", "at": 20.0},
        {"turn": 2, "step": "tool:endless_commit_backdrop", "at": 45.0},
    ]
    out = aggregate(rows, events)
    assert [r["turn"] for r in out] == [2, 3]
    two = out[0]
    assert two["storyMs"] == 42000 and two["pct"] == 37 and two["usedTokens"] == 74000
    assert two["artMs"] == 25000 and two["outcome"] == "committed"
    assert out[1]["rotation"] == "chapter"


def test_aggregate_skips_turns_with_no_commit_anchor():
    rows = [{"turn": 9, "step": "context", "at": 1.0, "pct": 12}]
    assert aggregate(rows, []) == []


def test_rows_survive_a_corrupt_line(tmp_path):
    perf = TurnPerf(tmp_path, "a" * 32)
    perf.mark(1, "commit", storyMs=10)
    path = tmp_path / "runs" / ("a" * 32) / "perf.jsonl"
    with path.open("a") as f:
        f.write("not json\n")
    perf.mark(2, "commit", storyMs=20)
    assert [r["turn"] for r in perf.rows()] == [1, 2]


# ── end to end: a real commit writes the commit row ──────────────────────────


def test_a_commit_records_story_timing_and_form(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    # The app's own ask, then the narrator's read, then the commit — the same
    # order a real turn takes; readAt is stamped by the read itself.
    store.mark_pending(run, turn=1, slot="s", action="I begin")
    call("endless_read_runtime", runId=run)
    call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"status": {"age": 1}},
    )
    rows = TurnPerf(app, run).rows()
    commit = next(r for r in rows if r["step"] == "commit")
    assert commit["turn"] == 1
    assert commit["form"] == "full"
    assert isinstance(commit["storyMs"], int) and commit["storyMs"] >= 0
    assert isinstance(commit["readMs"], int) and commit["readMs"] >= 0
    assert commit["declaredBytes"] > 0


def test_a_patch_commit_is_labelled_patch(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"status": {"age": 1}},
    )
    # Real turn order: the app marks the ask, THEN the narrator reads (stamping
    # readAt on that pending record), then commits — a read before the mark
    # would leave the record read-less and the commit refused.
    store.mark_pending(run, turn=2, slot="s")
    fp = call("endless_read_runtime", runId=run)["fingerprint"]
    call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        statePatch={"status": {"age": 2}},
        basedOn=fp,
    )
    rows = [r for r in TurnPerf(app, run).rows() if r["step"] == "commit"]
    assert rows[-1]["form"] == "patch"
    assert rows[-1]["declaredBytes"] < 100, "the patch's size, not the whole state's"


def test_a_commit_without_a_pending_record_writes_no_row(app):
    # No ask on file → no storyMs to measure; the ledger stays silent rather
    # than inventing a span from nothing.
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"status": {"age": 1}},
    )
    assert TurnPerf(app, run).rows() == []
