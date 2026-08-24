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
from datetime import UTC, datetime
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from perf import TurnPerf, aggregate, art_spans, join_usage  # noqa: E402

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


def test_art_spans_close_on_the_servers_own_fallback_commit():
    """The server drawing the backdrop itself ENDS the span, like either commit tool.

    Its row is the one the illustrator never writes — the model's budget ran out
    and the server published the traced underlay instead — and it is written by a
    third code path, which is how it came to be missing from the terminal set.
    Treating it as non-terminal does not merely mislabel the turn: the span stays
    open, so the page reports the art as still painting and never reports how
    long it took, on exactly the slowest turns an audit is opened to look at.
    """
    events = [
        {"turn": 7, "step": "requested", "at": 400.0},
        {"turn": 7, "step": "recover:illustrator-dispatched", "at": 402.0, "attempt": 1},
        {"turn": 7, "step": "recover:illustrator-timeout", "at": 461.0, "attempt": 1},
        {"turn": 7, "step": "server-fallback-commit", "at": 523.5, "underlay": "trace"},
    ]
    span = art_spans(events)[7]
    assert span["outcome"] == "fallback", "the server drew it, so the turn fell back"
    assert span["artMs"] == 123500, "and the span it took is reported, not left open"


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


# ── join_usage: real billing joined at read time from the host's ledger ──────


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def test_join_usage_credits_the_committing_turn():
    turns = [{"turn": 1, "at": 100.0}, {"turn": 2, "at": 500.0}]
    usage = [
        {"ts": _iso(130.0), "credits": 3.5, "cost": 0.07},
        {"ts": _iso(540.0), "credits": 2.0},
    ]
    out = join_usage(turns, usage)
    assert out[0]["credits"] == 3.5 and out[0]["cost"] == 0.07
    assert out[1]["credits"] == 2.0 and "cost" not in out[1]


def test_join_usage_skips_uncommitted_conversation_turns():
    # A recovery injection ends a conversation turn between two commits but
    # commits nothing; its row must not be attributed to the next commit.
    turns = [{"turn": 1, "at": 100.0}, {"turn": 2, "at": 500.0}]
    usage = [
        {"ts": _iso(130.0), "credits": 3.0},
        {"ts": _iso(300.0), "credits": 9.9},  # injected turn, no commit
        {"ts": _iso(540.0), "credits": 2.0},
    ]
    out = join_usage(turns, usage)
    assert out[0]["credits"] == 3.0
    assert out[1]["credits"] == 2.0


def test_join_usage_never_steals_the_next_turns_row():
    # Turn 1's row is gone (window expired); the only later row belongs to
    # turn 2 and must stay with turn 2.
    turns = [{"turn": 1, "at": 100.0}, {"turn": 2, "at": 500.0}]
    usage = [{"ts": _iso(540.0), "credits": 2.0}]
    out = join_usage(turns, usage)
    assert "credits" not in out[0]
    assert out[1]["credits"] == 2.0


def test_join_usage_caps_the_attribution_gap():
    turns = [{"turn": 1, "at": 100.0}]
    usage = [{"ts": _iso(100.0 + 3600.0), "credits": 4.0}]
    assert "credits" not in join_usage(turns, usage)[0]


def test_join_usage_ignores_undatable_rows_and_non_numeric_values():
    turns = [{"turn": 1, "at": 100.0}, {"turn": 7, "rotation": "budget"}]
    usage = [
        {"ts": "not-a-date", "credits": 8.0},
        {"ts": _iso(120.0), "credits": True, "cost": float("nan")},
    ]
    out = join_usage(turns, usage)
    # bool is not a count; NaN comes pre-filtered by the host but must not slip
    # through here either. The rotation-only row has no commit to credit.
    assert "credits" not in out[0]
    assert "cost" not in out[0]
    assert "rotation" in out[1] and "credits" not in out[1]


# ── the route's guarded reader: absent, present, and failing hosts ───────────


def test_usage_rows_helper_returns_empty_without_the_host_reader(monkeypatch):
    import types

    import routes

    fake = types.ModuleType("kiro_crew.dashboard.handlers.usage")  # no reader attr
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.handlers.usage", fake)
    assert routes._usage_rows_for("some-life") == []


def test_usage_rows_helper_reads_the_narrator_slot(monkeypatch):
    import types

    import routes
    from narrator import narrator_slot_key

    seen: list[str] = []

    def fake_reader(slot, days=30, **kwargs):
        seen.append(slot)
        return [{"ts": _iso(1.0), "credits": 1.5}]

    fake = types.ModuleType("kiro_crew.dashboard.handlers.usage")
    fake.slot_turn_usage = fake_reader
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.handlers.usage", fake)
    rows = routes._usage_rows_for("some-life")
    assert rows and rows[0]["credits"] == 1.5
    assert seen == [narrator_slot_key("some-life")]


def test_usage_rows_helper_swallows_a_failing_reader(monkeypatch):
    import types

    import routes

    def boom(slot, **kwargs):
        raise RuntimeError("shard unreadable")

    fake = types.ModuleType("kiro_crew.dashboard.handlers.usage")
    fake.slot_turn_usage = boom
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.handlers.usage", fake)
    assert routes._usage_rows_for("some-life") == []
