"""Ending ONE life, leaving its world alone.

The world-level delete cannot reach two cases, and this route exists for both.

**A life the player is done with.** Deleting the world to drop one of its lives
takes the world and every other life in it — an axe where the ask was a scalpel.

**A life too damaged to open.** ``get_run`` needs the world to resolve panels, so a
life whose ``worldId`` is missing answers ``422`` and nothing more. A real run
reached exactly that state. A delete offered only on the play page could never
reach it, because opening it is the thing that fails — which is why the affordance
belongs on the shelf and why an unreadable life must be deletable here.

These tests EXECUTE the route handlers. The suite's blind spot around them has
already shipped two live bugs in this app (a missing import, a keyword the callee
never took), and the confirmation guards live in the handlers.
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


@pytest.fixture()
def app(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    storage = AppStorage("endless-worlds", data)
    return {"ctx": FakeCtx(data, storage), "store": RunStore(storage, data), "data": data}


def a_life(app, *, turn=3, world_id="test-world"):
    run_id = app["store"].create_run(
        {"turn": turn, "style": "standard", "worldId": world_id},
        {"worldId": world_id, "title": "Test World", "turn": turn},
    )
    app["store"].append_turn(run_id, {"turn": turn, "prose": "the snow stopped"})
    return run_id


def wipe(app, run_id, *, confirm=None, turn=3):
    return call(
        routes_mod.delete_life,
        app["ctx"],
        match={"run_id": run_id},
        body={"confirm": run_id if confirm is None else confirm, "turn": turn},
    )


# -- the happy path -------------------------------------------------------


def test_one_life_is_erased_and_its_world_is_untouched(app, tmp_path):
    """The whole point: a scalpel, not the axe the world delete is."""
    keep = a_life(app)
    drop = a_life(app)
    app["store"].mark_briefed(drop, slot="endless-run-x")

    res = wipe(app, drop)

    assert res.status == 200
    assert body_of(res)["deleted"] is True
    assert [r["runId"] for r in app["store"].read_index()] == [keep]
    assert not (app["data"] / "runs" / drop).exists()
    # Every key the store writes for that life, not just the obvious two.
    for key in (f"run.{drop}.state", f"run.{drop}.prev", f"briefed-{drop}", f"pending-{drop}"):
        assert app["ctx"].storage.get(key) is None, f"{key} was left behind"
    # The life that was kept is fully intact.
    assert app["store"].read_state(keep)["turn"] == 3
    assert len(app["store"].read_chronicle(keep)) == 1


def test_a_life_too_damaged_to_open_can_still_be_erased(app):
    """The case with no other exit.

    ``get_run`` answers 422 for a life whose world cannot be resolved, so the play
    page can never offer a control for it. Before this route there was nothing that
    could remove it — it sat on the shelf forever, listed and unopenable.
    """
    run_id = a_life(app)
    # Corrupt the state the way a real run got corrupted: unreadable bytes.
    (app["data"] / "kv" / f"run.{run_id}.state.json").write_text("{ not json", encoding="utf-8")

    facts = body_of(call(routes_mod.life_deletion, app["ctx"], match={"run_id": run_id}))
    assert facts["unreadable"] is True
    assert facts["turn"] == 0

    res = wipe(app, run_id, turn=0)

    assert res.status == 200
    assert app["store"].read_index() == []


# -- the confirmation -----------------------------------------------------


def test_a_delete_that_does_not_name_the_life_is_refused(app):
    """Protects the ROUTE: a retried fetch or a caller holding only a path
    parameter cannot erase anything."""
    run_id = a_life(app)

    res = wipe(app, run_id, confirm="")

    assert res.status == 400
    assert body_of(res)["field"] == "confirm"
    assert len(app["store"].read_index()) == 1


def test_a_delete_whose_month_is_stale_is_refused(app):
    """Protects the PLAYER: a life that advanced while the dialog was open holds
    more story than the dialog described."""
    run_id = a_life(app, turn=3)
    state = app["store"].read_state(run_id)
    app["store"].commit_state(run_id, {**state, "turn": 4})

    res = wipe(app, run_id, turn=3)  # the dialog was shown month 3

    assert res.status == 409
    assert body_of(res)["code"] == "turn_changed"
    assert body_of(res)["turn"] == 4
    assert len(app["store"].read_index()) == 1, "a life was erased anyway"


def test_a_boolean_is_not_a_month(app):
    """``True`` is an ``int`` in Python, so an unguarded check accepts it and reads
    it as 1 — the same trap the tool layer and the world delete both had to close."""
    run_id = a_life(app, turn=1)

    res = wipe(app, run_id, turn=True)

    assert res.status == 400
    assert body_of(res)["field"] == "turn"
    assert len(app["store"].read_index()) == 1


def test_a_month_being_written_blocks_the_delete(app):
    """The narrator would commit into a run that no longer exists and lose the turn.
    Cannot deadlock: the pending record ages out on its own."""
    run_id = a_life(app)
    app["store"].mark_pending(run_id, turn=4, slot="endless-run-x")

    res = wipe(app, run_id)

    assert res.status == 409
    assert body_of(res)["code"] == "turn_in_flight"
    assert len(app["store"].read_index()) == 1


def test_a_life_that_does_not_exist_is_a_404_not_a_500(app):
    """An id the index has never heard of must not reach the store's own errors."""
    ghost = "0" * 32

    assert call(routes_mod.life_deletion, app["ctx"], match={"run_id": ghost}).status == 404
    assert wipe(app, ghost, turn=0).status == 404


# -- what the dialog is told ---------------------------------------------


def test_the_preflight_says_which_month_this_life_reached(app):
    """The dialog has to name what is being lost, and for one life that is the
    months behind it."""
    run_id = a_life(app, turn=7)

    facts = body_of(call(routes_mod.life_deletion, app["ctx"], match={"run_id": run_id}))

    assert facts["runId"] == run_id
    assert facts["turn"] == 7
    assert facts["unreadable"] is False
    assert facts["generating"] is False
    assert facts["worldId"] == "test-world"


def test_both_deletion_bodies_carry_every_field_the_dialogs_read(app, tmp_path):
    """The cross-file contract for the confirmation dialogs.

    Both dialogs read their server payload through a variable named ``facts``, so the
    contract is against the UNION of the two bodies — a key either dialog reads must
    come from one of them. This closes a gap the world-deletion work left open: the
    existing guards cover the world row, the play view, the life row and the digest
    row, and nothing covered these two.

    The failure being prevented is specific and has happened twice in this app: a
    renamed field leaves the UI reading a key that no longer arrives, and the
    dashboard renders a throwing app as ONE error card — so a stale name in a
    confirmation dialog costs the player the whole page, not just the dialog.
    """
    import uisrc

    if not uisrc.WEB_SRC.is_dir():
        pytest.skip("web/src not present")

    run_id = a_life(app, turn=2)
    life_body = body_of(call(routes_mod.life_deletion, app["ctx"], match={"run_id": run_id}))

    # The world-deletion body, built from its own real library + store.
    from test_delete_world import HEADER, world_file

    seeds = tmp_path / "wseeds"
    seeds.mkdir()
    (seeds / "test-world.md").write_text(world_file(HEADER), encoding="utf-8")
    from library import WorldLibrary

    WorldLibrary(app["data"], seeds).ensure_seeds_installed()
    import routes as _routes

    _routes._SEEDS_DIR = seeds
    world_body = body_of(
        call(routes_mod.world_deletion, app["ctx"], match={"world_id": "test-world"})
    )

    sent = set(life_body) | set(world_body)
    read = uisrc_reads(uisrc.module("confirm.tsx"), "facts")
    missing = sorted(read - sent - {"length", "map", "filter", "trim"})
    assert not missing, f"the dialogs read fields no deletion body sends: {missing}"


def uisrc_reads(src: str, obj: str) -> set[str]:
    """Field names read off ``obj``, including the optional-chained form.

    Mirrors ``test_view_contract._reads``: ``obj?.field`` must count, because a guard
    stops the crash without making a wrong name correct. Occurrences preceded by a
    quote or a word character are skipped so a namespaced string key
    (``t('life.delete.title')``) does not read as a property.
    """
    import re

    return set(re.findall(rf"(?<![\w'\"]){re.escape(obj)}\??\.([a-zA-Z][a-zA-Z0-9]*)", src))
