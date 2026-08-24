"""Guards on statePatch: the write-side twin of read_runtime's ``since``.

Measured on a real life, re-declaring the whole state was 22 KB per
endless_advance_turn call — the single largest line in the narrator's
transcript, re-paid in full by every retry. A statePatch says the same thing in
the tokens the change actually needs, vouching for everything unmentioned with
the fingerprint it read (``basedOn``). The certification is the same as the read
side: a narrator that can still produce the fingerprint is patching the state it
believes it is patching; one that cannot is refused and told to re-read, never
left to guess.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from mcp_server import _merge_patch  # noqa: E402

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


def _full_turn(run, n, state):
    return call(
        "endless_advance_turn",
        runId=run,
        turn=n,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state=state,
    )


def _patch_turn(run, n, patch, based_on):
    return call(
        "endless_advance_turn",
        runId=run,
        turn=n,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        statePatch=patch,
        basedOn=based_on,
    )


# ── unit: the recursive merge ────────────────────────────────────────────────


def test_merge_patch_sets_retires_and_keeps():
    base = {"a": {"x": 1, "y": 2}, "b": 3, "keep": "as-is"}
    out = _merge_patch(base, {"a": {"y": 5, "z": 6}, "b": None, "new": 7})
    assert out == {"a": {"x": 1, "y": 5, "z": 6}, "keep": "as-is", "new": 7}
    assert base == {"a": {"x": 1, "y": 2}, "b": 3, "keep": "as-is"}, "base is not mutated"


def test_merge_patch_replaces_when_shapes_disagree():
    assert _merge_patch({"a": {"x": 1}}, {"a": [1, 2]}) == {"a": [1, 2]}
    assert _merge_patch({"a": 1}, {"a": {"x": 2}}) == {"a": {"x": 2}}


def test_merge_patch_keeps_an_empty_string_leaf():
    # "" retires a digest entry in _merge_forward; a general state leaf may
    # legitimately hold "", so statePatch must not treat it as a retirement.
    assert _merge_patch({"a": "old"}, {"a": ""}) == {"a": ""}


# ── end to end ───────────────────────────────────────────────────────────────


def test_a_patch_commits_only_what_moved(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _full_turn(run, 1, {"status": {"age": 1, "mood": "calm"}, "gold": 10})

    fp = call("endless_read_runtime", runId=run)["fingerprint"]
    out = _patch_turn(run, 2, {"status": {"age": 2}}, fp)
    assert out["committed"] is True

    after = store.read_state(run)
    assert after["status"] == {"age": 2, "mood": "calm"}, "unmentioned leaves survive"
    assert after["gold"] == 10
    assert after["turn"] == 2


def test_a_patch_null_retires_a_leaf(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _full_turn(run, 1, {"status": {"age": 1}, "curse": "marked"})
    fp = call("endless_read_runtime", runId=run)["fingerprint"]
    _patch_turn(run, 2, {"curse": None}, fp)
    assert "curse" not in store.read_state(run)


def test_a_patch_merges_digest_without_resurrecting_retired_entries(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _full_turn(run, 1, {"digest": {"war": "帝国宣战", "trade": "商路如常"}})
    fp = call("endless_read_runtime", runId=run)["fingerprint"]
    # Retire one entry, move the other — through the patch path.
    out = _patch_turn(run, 2, {"digest": {"war": None, "trade": "商路中断"}}, fp)
    assert out["committed"] is True
    assert store.read_state(run)["digest"] == {"trade": "商路中断"}, (
        "a retired entry must not be resurrected by the merge-forward carry"
    )


def test_a_stale_fingerprint_is_refused_with_a_recovery_path(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _full_turn(run, 1, {"status": {"age": 1}})
    fp = call("endless_read_runtime", runId=run)["fingerprint"]
    _patch_turn(run, 2, {"status": {"age": 2}}, fp)  # state moved; fp is now stale

    out = _patch_turn(run, 3, {"status": {"age": 3}}, fp)
    assert out["committed"] is False
    assert out["reason"] == "baseline-mismatch"
    assert store.read_state(run)["status"] == {"age": 2}, "nothing was applied"


def test_a_patch_without_based_on_is_refused(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _full_turn(run, 1, {"status": {"age": 1}})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        statePatch={"status": {"age": 2}},
    )
    assert out["committed"] is False
    assert out["reason"] == "based-on-required"


def test_neither_state_nor_patch_is_refused(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _full_turn(run, 1, {"status": {"age": 1}})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
    )
    assert out["committed"] is False
    assert out["reason"] == "state-required"


def test_patch_and_provenance_compose_on_the_next_delta_read(app):
    # The narrator patches one leaf; the backend writes `turn`. The next delta
    # read must not echo the patched leaf back (the narrator wrote it) — the
    # provenance filter works identically for both declaration forms.
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _full_turn(run, 1, {"status": {"age": 1}})
    full = call("endless_read_runtime", runId=run)
    _patch_turn(run, 2, {"status": {"age": 2}}, full["fingerprint"])

    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert "status" not in delta["changed"]
    assert delta["yours"] == ["status"]


def test_a_string_patch_is_leniently_recovered(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _full_turn(run, 1, {"status": {"age": 1}})
    fp = call("endless_read_runtime", runId=run)["fingerprint"]
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        statePatch=json.dumps({"status": {"age": 2}}),
        basedOn=fp,
    )
    assert out["committed"] is True
    assert srv._store().read_state(run)["status"]["age"] == 2
