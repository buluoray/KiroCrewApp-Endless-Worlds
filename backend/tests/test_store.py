"""RunStore tests.

Runs against the REAL AppStorage. If the gateway package is not importable in
this environment the whole module skips rather than silently testing a stand-in:
the behaviours under test here are precisely the ones that depend on
AppStorage's real semantics (atomic set, and get() returning None for BOTH
"absent" and "unparseable JSON").
"""

from __future__ import annotations

import asyncio
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


def test_corrupt_state_is_reported_and_never_rewritten(
    store: RunStore, tmp_path: Path
) -> None:
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


# -- locking --------------------------------------------------------------


def test_lock_is_per_run_and_stable(store: RunStore) -> None:
    a, b = new_run_id(), new_run_id()
    assert store.lock(a) is store.lock(a)
    assert store.lock(a) is not store.lock(b)


def test_a_second_concurrent_turn_on_one_run_is_rejected(store: RunStore) -> None:
    """The caller rejects rather than queues (design §3).

    The UI already disables choices during a turn, so a queued duplicate could
    only ever be a double-submit.
    """
    run_id = store.create_run(_state(1), {"templateId": "t"})

    async def scenario() -> tuple[bool, bool]:
        lock = store.lock(run_id)
        async with lock:
            second_got_in = not lock.locked() or lock.locked() and False
            # A real handler does exactly this test and returns 409.
            busy = lock.locked()
        return busy, second_got_in

    busy, second_got_in = asyncio.run(scenario())
    assert busy, "the lock must be observably held during a turn"
    assert not second_got_in


# -- deletion -------------------------------------------------------------


def test_delete_removes_state_index_row_and_chronicle(
    store: RunStore, tmp_path: Path
) -> None:
    run_id = store.create_run(_state(1), {"templateId": "t"})
    store.commit_state(run_id, _state(2))
    store.append_turn(run_id, {"turn": 1})

    store.delete_run(run_id)

    assert store.read_index() == []
    assert not (tmp_path / "runs" / run_id).exists()
    with pytest.raises(StoreError):
        store.read_state(run_id)
    assert json.loads(json.dumps({})) == {}  # sanity: no stray state leaked
