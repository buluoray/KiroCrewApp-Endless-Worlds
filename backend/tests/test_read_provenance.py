"""Guards on delta reads sending back only what the APP computed.

Measured on a live life (turn 57): a delta read carried 4223 of a 4696-byte
snapshot — 89% — because the top-level diff re-sent every changed panel whole,
and the biggest changed panels were the ones the narrator had itself declared
that same turn. The narrator remembers its own words; within a surviving session
(which a resolvable baseline proves) re-sending them buys nothing.

So each commit records provenance — the leaf paths where the committed state
differs from the narrator's declaration; those are the backend's amendments
(reserved-key carry, merge results, turn, milestones, systems). A delta read
returns ONLY changed leaves on that list, and NAMES the panels the narrator
changed by its own hand in ``yours``. Provenance that does not describe the
current commit is ignored and the read falls back to whole-panel resends: the
fail-safe direction is more data, never a silently missing fact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from mcp_server import _pluck_paths  # noqa: E402
from store import RunStore  # noqa: E402

#: A world whose milestone fires from committed state — the cleanest
#: backend-written leaf there is: the narrator never declares ``milestones``.
WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "milestones": [{"id": "of-age", "label": "Of age", "when": "state.status.age >= 5"}],
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


def _turn(run, n, state):
    return call(
        "endless_advance_turn",
        runId=run,
        turn=n,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state=state,
    )


# ── unit: the leaf walk and the pluck ───────────────────────────────────────


def test_leaf_diff_paths_flags_exactly_the_moved_leaves():
    before = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": "same"}
    after = {"a": {"x": 1, "y": 3, "z": 4}, "b": [2, 1], "c": "same"}
    assert RunStore.leaf_diff_paths(before, after) == ["a.y", "a.z", "b"]


def test_leaf_diff_paths_treats_a_type_change_as_one_leaf():
    # dict-vs-scalar cannot recurse: the whole key is the change.
    assert RunStore.leaf_diff_paths({"a": {"x": 1}}, {"a": 7}) == ["a"]


def test_pluck_paths_rebuilds_only_the_named_leaves():
    state = {"a": {"x": 1, "y": 2}, "b": 3, "c": {"deep": {"leaf": 4}}}
    out = _pluck_paths(state, ["a.y", "c.deep.leaf", "missing.leaf"])
    assert out == {"a": {"y": 2}, "c": {"deep": {"leaf": 4}}}


# ── end to end: a real commit, then a delta read ────────────────────────────


def test_a_delta_read_returns_computed_leaves_and_names_the_rest(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _turn(run, 1, {"status": {"age": 1}, "mood": "calm"})

    full = call("endless_read_runtime", runId=run)
    assert "state" in full

    # The narrator changes its own panels; the milestone fires from the committed
    # state — the one leaf here the narrator did NOT write.
    _turn(run, 2, {"status": {"age": 5}, "mood": "eager"})

    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert delta["basedOn"] == full["fingerprint"]
    changed = delta["changed"]
    assert "milestones" in changed, "the backend-written milestone must be sent"
    assert "status" not in changed, "the narrator's own declaration must not echo back"
    assert "mood" not in changed
    assert sorted(delta["yours"]) == ["mood", "status"]
    assert "turn" not in changed, "turn already rides at the top level"
    assert delta["turn"] == 2


def test_merge_carry_is_not_resent_and_own_entries_are_named(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _turn(run, 1, {"digest": {"war": "帝国宣战", "trade": "商路如常"}})
    full = call("endless_read_runtime", runId=run)

    # One entry moves; the carried entry is unchanged vs the baseline and the
    # moved one is the narrator's own declaration — nothing to re-send.
    _turn(run, 2, {"digest": {"war": "战事平息"}})
    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert "digest" not in delta["changed"]
    assert "digest" in delta["yours"]
    # The merge itself still happened on disk.
    assert store.read_state(run)["digest"] == {"war": "战事平息", "trade": "商路如常"}


def test_stale_provenance_falls_back_to_whole_panels(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _turn(run, 1, {"status": {"age": 1}})
    full = call("endless_read_runtime", runId=run)
    _turn(run, 2, {"status": {"age": 2}})

    # Provenance describing some OTHER commit must not be trusted.
    store.mark_provenance(run, turn=999, paths=["status.age"])
    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert delta["changed"].get("status") == {"age": 2}, (
        "without trustworthy provenance the whole changed panel is sent"
    )
    assert "yours" not in delta


def test_a_full_read_still_carries_the_whole_state(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _turn(run, 1, {"status": {"age": 1}})
    out = call("endless_read_runtime", runId=run)
    assert out["state"]["status"] == {"age": 1}
    assert "yours" not in out


def test_provenance_round_trip_and_deletion(app, tmp_path):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    store.mark_provenance(run, turn=3, paths=["b", "a.x"])
    assert store.provenance(run) == (3, ["a.x", "b"])
    store.delete_run(run)
    assert store.provenance(run) == (0, [])
