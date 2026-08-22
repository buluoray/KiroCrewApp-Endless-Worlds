"""RunStore tests.

Runs against the REAL AppStorage. If the gateway package is not importable in
this environment the whole module skips rather than silently testing a stand-in:
the behaviours under test here are precisely the ones that depend on
AppStorage's real semantics (atomic set, and get() returning None for BOTH
"absent" and "unparseable JSON").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "kiro_crew.apps.app_storage",
    reason="gateway package not importable here; RunStore needs the real AppStorage",
)

from kiro_crew.apps.app_storage import AppStorage  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import (  # noqa: E402
    CorruptRunState,
    RunStore,
    StoreError,
    new_run_id,
)


@pytest.fixture()
def store(tmp_path: Path) -> RunStore:
    return RunStore(AppStorage("endless-worlds", tmp_path), tmp_path)


def _state(turn: int = 1) -> dict:
    return {"turn": turn, "panels": {"status": {"renown": turn * 10}}}


# -- round trip -----------------------------------------------------------


def test_create_and_read_round_trip(store: RunStore) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t", "character": "阿岩"})
    got = store.read_state(run_id)
    assert got["turn"] == 1
    assert got["runId"] == run_id, "create_run must stamp the id into the state"
    assert [r["runId"] for r in store.read_index()] == [run_id]


def test_unicode_survives_round_trip(store: RunStore) -> None:
    run_id = store.create_run({"name": "莉安", "place": "精灵王庭"}, {"templateId": "t"})
    assert store.read_state(run_id)["name"] == "莉安"


# -- the crash story ------------------------------------------------------


def test_commit_preserves_outgoing_state_as_rollback_point(store: RunStore) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t"})
    store.commit_state(run_id, _state(2))
    assert store.read_state(run_id)["turn"] == 2
    assert store.rollback(run_id)["turn"] == 1, "prev must hold the OUTGOING state"
    assert store.read_state(run_id)["turn"] == 1, "rollback must take effect"


def test_crash_between_prev_and_state_leaves_both_consistent(
    store: RunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write order is the whole crash story.

    prev is written first, then state. A crash in between must leave BOTH
    holding the outgoing state — consistent, costing only the turn in flight.
    Falsification: reversing the order in commit_state makes this red, because
    prev would then hold the NEW state and the rollback point would be gone.
    """
    run_id = store.create_run(_state(1), {"templateId": "t"})

    real_set = store._kv.set
    calls: list[str] = []

    def exploding_set(key: str, value):  # type: ignore[no-untyped-def]
        calls.append(key)
        if key.endswith(".state"):
            raise OSError("simulated crash before the state write landed")
        return real_set(key, value)

    monkeypatch.setattr(store._kv, "set", exploding_set)
    with pytest.raises(OSError):
        store.commit_state(run_id, _state(2))
    monkeypatch.undo()

    assert calls[0].endswith(".prev"), "prev must be written before state"
    assert store.read_state(run_id)["turn"] == 1
    assert store.rollback(run_id)["turn"] == 1


def test_rollback_without_a_prior_commit_is_refused(store: RunStore) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t"})
    with pytest.raises(StoreError):
        store.rollback(run_id)


# -- corrupt vs absent ----------------------------------------------------


def test_corrupt_state_is_reported_and_never_rewritten(store: RunStore, tmp_path: Path) -> None:
    """AppStorage.get() returns None for BOTH absent and unparseable JSON.

    Conflating them would let a damaged save be mistaken for a new run and
    overwritten (R16.2). The store must tell them apart.
    """
    run_id = store.create_run(_state(1), {"templateId": "t"})
    kv_file = tmp_path / "kv" / f"run.{run_id}.state.json"
    kv_file.write_text("{ not json", encoding="utf-8")

    with pytest.raises(CorruptRunState) as excinfo:
        store.read_state(run_id)
    assert run_id in excinfo.value.key
    assert kv_file.read_text(encoding="utf-8") == "{ not json", "must not rewrite it"


def test_absent_run_is_a_plain_error_not_a_corruption_claim(store: RunStore) -> None:
    with pytest.raises(StoreError) as excinfo:
        store.read_state(new_run_id())
    assert not isinstance(excinfo.value, CorruptRunState)


# -- ids ------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["", "../escape", "run/1", "RUN", "abc", "g" * 32, new_run_id() + "x"]
)
def test_malformed_run_ids_are_refused(store: RunStore, bad: str) -> None:
    with pytest.raises(StoreError):
        store.read_state(bad)


# -- chronicle ------------------------------------------------------------


def test_chronicle_appends_in_order(store: RunStore) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t"})
    for turn in (1, 2, 3):
        store.append_turn(run_id, {"turn": turn, "summary": f"第{turn}回"})
    assert [e["turn"] for e in store.read_chronicle(run_id)] == [1, 2, 3]


def test_a_torn_trailing_line_costs_only_that_line(store: RunStore, tmp_path: Path) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t"})
    store.append_turn(run_id, {"turn": 1})
    store.append_turn(run_id, {"turn": 2})
    path = tmp_path / "runs" / run_id / "chronicle.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"turn": 3, "summ')  # power loss mid-append

    assert [e["turn"] for e in store.read_chronicle(run_id)] == [1, 2]


def test_chronicle_of_a_fresh_run_is_empty_not_an_error(store: RunStore) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t"})
    assert store.read_chronicle(run_id) == []


# -- index ----------------------------------------------------------------


def test_index_upsert_replaces_and_promotes(store: RunStore) -> None:
    a = store.create_run(_state(1), {"templateId": "t", "character": "甲"})
    b = store.create_run(_state(1), {"templateId": "t", "character": "乙"})
    assert [r["runId"] for r in store.read_index()] == [b, a]

    store.upsert_index({"runId": a, "templateId": "t", "character": "甲", "turn": 9})
    rows = store.read_index()
    assert [r["runId"] for r in rows] == [a, b], "most recently played first"
    assert len([r for r in rows if r["runId"] == a]) == 1, "no duplicate row"
    assert rows[0]["turn"] == 9
    assert "lastPlayed" in rows[0]


def test_created_at_is_written_once_and_survives_being_played(store: RunStore) -> None:
    """The shelf offers two orderings, and they are only different if one of the two
    timestamps stands still. `lastPlayed` moves with every month written; `createdAt`
    is the life's beginning and must not, or "by when I started it" would be a second
    spelling of "most recent" and the toggle would do nothing."""
    a = store.create_run(_state(1), {"templateId": "t", "character": "甲"})
    born = next(r for r in store.read_index() if r["runId"] == a)["createdAt"]
    assert born > 0

    store.upsert_index({"runId": a, "templateId": "t", "character": "甲", "turn": 9})
    row = next(r for r in store.read_index() if r["runId"] == a)
    assert row["createdAt"] == born, "a month written does not move the beginning"
    assert row["lastPlayed"] > born or row["lastPlayed"] >= born
    assert row["turn"] == 9, "the rest of the row still refreshes"


def test_a_row_from_before_created_at_existed_gets_one_without_losing_its_place(
    store: RunStore,
) -> None:
    """No migration: Endless Worlds' lives are throwaway test data. But a row already
    on disk must not be dropped or reordered by the new field appearing — it simply
    gains one on its next write, and until then the client falls back to lastPlayed."""
    a = store.create_run(_state(1), {"templateId": "t", "character": "甲"})
    rows = store.read_index()
    for row in rows:
        row.pop("createdAt", None)  # a row as an older build wrote it
    store._kv.set("index", {"runs": rows})
    assert "createdAt" not in store.read_index()[0], "the old shape is what we start from"

    store.upsert_index({"runId": a, "templateId": "t", "character": "甲", "turn": 2})
    row = next(r for r in store.read_index() if r["runId"] == a)
    assert row["createdAt"] > 0, "the next write supplies one"


def test_patch_index_merges_metadata_without_reordering(store: RunStore) -> None:
    a = store.create_run(_state(1), {"templateId": "t", "character": "甲"})
    b = store.create_run(_state(1), {"templateId": "t", "character": "乙"})
    before = next(r for r in store.read_index() if r["runId"] == a)["lastPlayed"]

    assert store.patch_index(a, {"label": "当上宰相的那一世", "archived": True}) is True
    rows = store.read_index()
    # Order is unchanged: renaming is not playing, so recency does not move.
    assert [r["runId"] for r in rows] == [b, a]
    row_a = next(r for r in rows if r["runId"] == a)
    assert row_a["label"] == "当上宰相的那一世"
    assert row_a["archived"] is True
    assert row_a["lastPlayed"] == before, "a metadata patch must not bump lastPlayed"
    assert row_a["character"] == "甲", "other fields are left intact"


def test_patch_index_reports_a_missing_life(store: RunStore) -> None:
    assert store.patch_index(new_run_id(), {"archived": True}) is False


def test_read_prev_is_empty_before_a_commit_then_holds_the_outgoing_state(
    store: RunStore,
) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t"})
    # No commit yet: nothing to peek at, which is what lets a caller tell "opened
    # this month" from "open since birth".
    assert store.read_prev(run_id) == {}
    store.commit_state(run_id, _state(2))
    assert store.read_prev(run_id)["turn"] == 1, "prev holds the outgoing state"
    assert store.read_state(run_id)["turn"] == 2, "read_prev must not mutate current"


# -- process lifetime -----------------------------------------------------


def test_store_has_no_process_lifetime_per_run_lock_table(store: RunStore) -> None:
    assert not hasattr(store, "_locks")
    assert not hasattr(store, "lock")


# -- deletion -------------------------------------------------------------


def test_delete_removes_state_index_row_and_chronicle(store: RunStore, tmp_path: Path) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t"})
    store.commit_state(run_id, _state(2))
    store.append_turn(run_id, {"turn": 1})
    store.mark_narrator_generation(run_id, "install-a")

    store.delete_run(run_id)

    assert store.read_index() == []
    assert store.narrator_generation(run_id) == ""
    assert not (tmp_path / "runs" / run_id).exists()
    with pytest.raises(StoreError):
        store.read_state(run_id)
    assert json.loads(json.dumps({})) == {}  # sanity: no stray state leaked
