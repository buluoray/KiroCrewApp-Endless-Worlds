"""Guards on planned conversation rotation.

One narrator conversation per life grows without bound (2.9 MB by turn 57 on a
measured life) until the harness compacts it at an arbitrary point — mid-scene,
uncontrolled, and the narrator loses its read baseline with it. Rotation
replaces that with a reset at a point of the APP's choosing: a chapter the world
just opened, or a turn budget for worlds that never open one. The fresh
conversation re-briefs and re-anchors with a full read — the same self-healing
path a compaction already triggers, only on purpose.

The marker (``rotation_turn``) makes each boundary fire exactly once: it is
written before dispatch, so a double-tap or refresh for the same turn never
discards the session of the narrator already writing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import turn as turn_mod  # noqa: E402
from narrator import APP_NAME  # noqa: E402
from store import RunStore  # noqa: E402
from turn import ROTATION_MAX_TURNS, _should_rotate  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    return RunStore(AppStorage(APP_NAME, data), data)


@pytest.fixture()
def run(store):
    return store.create_run(
        {"turn": 0, "worldId": "w", "status": "awaiting-opening"},
        {"worldId": "w", "title": "a life"},
    )


def test_a_new_life_never_rotates(store, run):
    assert not _should_rotate(store, run, 0, chapter_crossed=True)


def test_a_chapter_boundary_rotates_exactly_once(store, run):
    assert _should_rotate(store, run, 5, chapter_crossed=True)
    store.mark_rotation(run, turn=5)
    # The same boundary asked again (double-tap, retry): consumed.
    assert not _should_rotate(store, run, 5, chapter_crossed=True)
    # The NEXT boundary rotates again.
    assert _should_rotate(store, run, 9, chapter_crossed=True)


def test_the_turn_budget_is_the_backstop_for_chapterless_worlds(store, run):
    store.mark_rotation(run, turn=10)
    just_under = 10 + ROTATION_MAX_TURNS - 1
    assert not _should_rotate(store, run, just_under, chapter_crossed=False)
    assert _should_rotate(store, run, just_under + 1, chapter_crossed=False)


def test_a_legacy_life_with_no_marker_uses_the_budget_from_zero(store, run):
    assert not _should_rotate(store, run, ROTATION_MAX_TURNS - 1, chapter_crossed=False)
    assert _should_rotate(store, run, ROTATION_MAX_TURNS, chapter_crossed=False)


def test_rotation_marker_round_trip_and_deletion(store, run):
    assert store.rotation_turn(run) == 0
    store.mark_rotation(run, turn=7)
    assert store.rotation_turn(run) == 7
    store.delete_run(run)
    assert store.rotation_turn(run) == 0


def test_module_wires_rotation_into_the_reset_seam():
    # The rotation branch must call the same seam the close branch calls — the
    # one that discards through the LIVE manager and clears the briefed marker.
    # A cheaper source-level pin than a full advance_turn harness; the seam's own
    # behaviour is pinned in test_conversation_reset.py.
    import inspect

    src = inspect.getsource(turn_mod.advance_turn)
    rotation_branch = src.split("_should_rotate", 1)[1]
    assert "reset_narrator_conversation" in rotation_branch.split("elif")[0], (
        "rotation must reuse reset_narrator_conversation, not roll its own teardown"
    )
    assert "mark_rotation" in rotation_branch.split("elif")[0]
