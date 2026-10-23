"""A life that ends stays ended, and every reader says so.

Two ways a narrator closes a life, and each used to leave the readers split:

* ``ending: true`` on a choiceless terminal turn committed the page but wrote no
  ``ended`` into state. ``resolve_ending`` then said the life went on: the play
  view showed a dead page with no choices and no ending, and the turn route would
  narrate a month after the death.
* A world-law ending (``state.alive == false``) closed the life for the play view,
  but the shelf, the life-deletion facts and the story-card spoiler line all read
  only the flag, so the shelf listed a dead life as being lived and offered it as
  "continue".

The commit now stamps the flag; the shelf readers ask ``resolve_ending`` for lives
committed before that.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_delete_world import FakeCtx, body_of, call  # noqa: E402

import routes as routes_mod  # noqa: E402
from store import RunStore  # noqa: E402

WORLD = "age-of-sword-and-flame"
FLAGSHIP = _BACKEND.parent / "seeds" / f"{WORLD}.md"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from kiro_crew.apps.app_storage import AppStorage

    import mcp_server as srv

    if not FLAGSHIP.is_file():
        pytest.skip("flagship seed not present")
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / f"{WORLD}.md").write_text(
        FLAGSHIP.read_text(encoding="utf-8"), encoding="utf-8"
    )
    storage = AppStorage("endless-worlds", data)
    store = RunStore(storage, data)
    monkeypatch.setattr(srv, "_store", lambda: store)
    monkeypatch.setattr(srv, "_DATA", data)
    return {"srv": srv, "store": store, "ctx": FakeCtx(data, storage), "data": data}


def _life(app) -> str:
    store = app["store"]
    run = store.create_run(
        {"turn": 0, "worldId": WORLD, "language": "zh", "alive": True},
        {"worldId": WORLD, "title": WORLD, "turn": 0},
    )
    _commit(app, run, 1, {"alive": True}, choices=[{"id": "go", "label": "走"}])
    return run


def _commit(app, run, turn, state, **extra):
    store = app["store"]
    store.mark_pending(run, turn=turn, slot="s")
    store.note_runtime_read(run, turn=turn)
    out = app["srv"]._advance_turn(
        {
            "runId": run,
            "turn": turn,
            "prose": f"month {turn}",
            "state": {"worldId": WORLD, "language": "zh", **state},
            **extra,
        }
    )
    assert out["committed"] is True, out
    return out


def _view(app, run):
    res = call(routes_mod.get_run, app["ctx"], match={"run_id": run})
    assert res.status == 200
    body = body_of(res)
    return body.get("view", body)


def _shelf_row(app, run):
    rows = body_of(call(routes_mod.list_runs, app["ctx"]))
    rows = rows if isinstance(rows, list) else rows.get("runs", [])
    return next(r for r in rows if r["runId"] == run)


def test_an_ending_marker_closes_the_life_for_every_reader(app):
    run = _life(app)
    _commit(app, run, 2, {"alive": True}, ending=True)

    assert app["store"].read_state(run).get("ended") is True
    view = _view(app, run)
    assert view["ended"] is True and view["endingId"]
    assert _shelf_row(app, run)["ended"] is True
    # The turn route's own gate: a non-empty ending refuses another month instead
    # of narrating past the end.
    from library import WorldLibrary
    from view import resolve_ending

    pack = WorldLibrary(app["data"], FLAGSHIP.parent).read(WORLD, "zh")
    assert resolve_ending(pack.template, app["store"].read_state(run))


def test_a_world_law_ending_names_itself_on_disk(app):
    run = _life(app)
    _commit(app, run, 2, {"alive": False})

    assert app["store"].read_state(run).get("ended") == "line-ended"
    assert _view(app, run)["endingId"] == "line-ended"


def test_a_narrator_ending_id_is_kept(app):
    run = _life(app)
    _commit(app, run, 2, {"alive": True, "ended": "sailed-west"}, ending=True)
    assert app["store"].read_state(run).get("ended") == "sailed-west"


def test_a_living_turn_is_not_stamped(app):
    run = _life(app)
    assert "ended" not in app["store"].read_state(run)
    assert _shelf_row(app, run)["ended"] is False


def test_an_older_world_law_ending_without_the_flag_lists_as_ended(app):
    """A life committed before the stamp: dead by world law, no flag on disk."""
    run = _life(app)
    store = app["store"]
    state = store.read_state(run)
    store.commit_state(run, {**state, "turn": 2, "alive": False})
    assert "ended" not in store.read_state(run)

    assert _view(app, run)["ended"] is True
    assert _shelf_row(app, run)["ended"] is True
    facts = body_of(call(routes_mod.life_deletion, app["ctx"], match={"run_id": run}))
    assert facts["ended"] is True
    world = body_of(call(routes_mod.world_deletion, app["ctx"], match={"world_id": WORLD}))
    assert [life["ended"] for life in world["lives"]] == [True]
