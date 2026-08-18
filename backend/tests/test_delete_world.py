"""Deleting a world — guards on the two ways it can go wrong quietly.

Two failures are specific to THIS feature and neither announces itself.

**A deletion that undoes itself.** ``ensure_seeds_installed`` runs on every read of
the Library page, which is the screen the player lands on right after deleting. Any
seed-backed world removed by unlinking its file alone is copied straight back the
moment they look at the shelf. The world reappears, the lives stay erased, and
nothing logs a thing.

**A life that outlives its world.** ``get_run`` needs the world to resolve panels,
so a life whose world is gone can only ever answer ``422 this world could not be
read`` — and the world that would have cleaned it up no longer exists to be deleted
again. So lives cascade, and they are erased BEFORE the world's file, because that
ordering is the difference between a retryable failure and an unreachable orphan.

Unlike the rest of this suite these tests EXECUTE the route handlers. That blind
spot has already shipped two live bugs in this app — a ``NameError`` on a missing
import and a ``TypeError`` from a keyword the callee never took — both invisible to
a suite that only ever called the layer underneath. The confirmation guards live in
the handlers, so the handlers are what has to run.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import routes as routes_mod  # noqa: E402
from library import WorldLibrary  # noqa: E402
from store import RunStore  # noqa: E402

PROSE = "第一章\n\n世界不围绕玩家存在。\n"

HEADER = {
    "id": "test-world",
    "title": "Test World",
    "version": "1.0",
    "language": "en",
    "clock": {"unit": "month", "label": "{year}/{month}"},
    "styles": [{"id": "standard", "label": "Standard", "default": True}],
    "opening": [{"id": "name", "label": "Name", "kind": "text"}],
    "panels": [{"id": "status", "always": True, "fields": [
        {"id": "age", "label": "Age", "primitive": "field"}]}],
    "endings": [{"id": "died", "when": "state.alive == false"}],
}


def world_file(header: dict | None = None) -> str:
    return f"---\n{json.dumps(header or HEADER, ensure_ascii=False)}\n---\n{PROSE}"


# -- harness --------------------------------------------------------------


class FakeRequest:
    """Only what the handlers touch: an authenticated user, path params, a body."""

    def __init__(self, *, match=None, body=None, user="someone"):
        self.match_info = match or {}
        self._body = body
        self._extra = {"user": user}

    def get(self, key, default=None):
        return self._extra.get(key, default)

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeCtx:
    def __init__(self, data_dir: Path, storage):
        self.data_dir = data_dir
        self.storage = storage


def body_of(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def call(handler, ctx, **kw):
    return asyncio.run(handler(FakeRequest(**kw), ctx))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """A live app: a seed on disk, an installed world, a real store."""
    from kiro_crew.apps.app_storage import AppStorage

    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "test-world.md").write_text(world_file(), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()

    # The route module resolves seeds from the install tree; point it at ours.
    monkeypatch.setattr(routes_mod, "_SEEDS_DIR", seeds)

    lib = WorldLibrary(data, seeds)
    lib.ensure_seeds_installed()
    storage = AppStorage("endless-worlds", data)
    return {
        "ctx": FakeCtx(data, storage),
        "lib": lib,
        "store": RunStore(storage, data),
        "seeds": seeds,
        "data": data,
    }


def a_life(world, *, world_id="test-world", state_world=..., turn=1):
    """One life in the world. ``state_world`` defaults to matching the index row."""
    state = {"turn": turn, "style": "standard"}
    if state_world is ...:
        state["worldId"] = world_id
    elif state_world is not None:
        state["worldId"] = state_world
    run_id = world["store"].create_run(
        state, {"worldId": world_id, "title": "Test World", "turn": turn}
    )
    world["store"].append_turn(run_id, {"turn": turn, "prose": "the snow stopped"})
    return run_id


def delete(world, *, confirm="test-world", lives=0, world_id="test-world"):
    return call(
        routes_mod.delete_world, world["ctx"],
        match={"world_id": world_id}, body={"confirm": confirm, "lives": lives},
    )


# -- the gravestone -------------------------------------------------------


def test_a_removed_world_is_not_reinstalled_by_the_next_shelf_visit(world):
    """THE load-bearing guard. Without the gravestone check in
    ``ensure_seeds_installed`` this feature deletes nothing that stays deleted."""
    assert delete(world).status == 200
    assert not world["lib"].path_for("test-world").is_file()

    report = world["lib"].ensure_seeds_installed()

    assert report.installed == [], "the deleted world was copied back in"
    assert not world["lib"].path_for("test-world").is_file()
    assert report.removed == ["test-world"]


def test_the_gravestone_is_written_before_the_file_is_unlinked(world, monkeypatch):
    """An ordering, and the two orders fail in opposite directions.

    Gravestone first: a failed unlink leaves a world that is present and marked for
    removal — visible, and fixed by pressing delete again. File first: a failed
    gravestone write leaves a world whose deletion the next shelf visit silently
    reverses. Only one of those is diagnosable.
    """
    lib = WorldLibrary(world["data"], world["seeds"])

    def refuse(_ids):
        raise OSError("disk full")

    monkeypatch.setattr(lib, "_write_removed", refuse)
    with pytest.raises(OSError):
        lib.remove("test-world")

    assert lib.path_for("test-world").is_file(), (
        "the file was unlinked before the removal was recorded, so the next shelf "
        "visit will resurrect this world"
    )


def test_an_unreadable_gravestone_does_not_take_the_library_down(world):
    """A damaged record must cost a reappearing world, never the whole shelf."""
    (world["data"] / "removed.json").write_text("{ not json", encoding="utf-8")

    assert world["lib"].removed() == set()
    assert world["lib"].list_worlds()  # the shelf still answers


def test_a_world_still_on_disk_is_still_listed_even_once_marked_removed(world):
    """The deliberate non-filter: hiding it would make a failed unlink invisible."""
    world["lib"]._write_removed({"test-world"})

    rows = world["lib"].list_worlds()

    assert [r["worldId"] for r in rows] == ["test-world"]


def test_restore_brings_the_world_back_on_the_next_listing(world):
    assert delete(world).status == 200

    res = call(routes_mod.restore_world, world["ctx"], match={"world_id": "test-world"})

    assert res.status == 200
    report = world["lib"].ensure_seeds_installed()
    assert report.installed == ["test-world"]
    assert world["lib"].path_for("test-world").is_file()


def test_restore_is_refused_when_there_is_no_seed_to_restore_from(world):
    """A silent no-op would read as a restore that worked."""
    assert delete(world).status == 200
    (world["seeds"] / "test-world.md").unlink()

    res = call(routes_mod.restore_world, world["ctx"], match={"world_id": "test-world"})

    assert res.status == 409
    assert body_of(res)["code"] == "not_restorable"


# -- the confirmation -----------------------------------------------------


def test_a_delete_that_does_not_name_the_world_is_refused(world):
    """Protects the ROUTE, not the player: a retried fetch or a caller holding only
    a path parameter cannot delete anything."""
    res = delete(world, confirm="")

    assert res.status == 400
    assert body_of(res)["field"] == "confirm"
    assert world["lib"].path_for("test-world").is_file()


def test_a_delete_whose_life_count_is_stale_is_refused(world):
    """The precondition. A life begun between the dialog opening and the button
    being pressed must not be destroyed by a confirmation that never mentioned it."""
    a_life(world)

    res = delete(world, lives=0)  # the dialog was shown an empty world

    assert res.status == 409
    assert body_of(res)["code"] == "lives_changed"
    assert body_of(res)["liveCount"] == 1
    assert world["lib"].path_for("test-world").is_file()
    assert len(world["store"].read_index()) == 1, "a life was erased anyway"


def test_a_boolean_is_not_a_life_count(world):
    """``True`` is an ``int`` in Python, so an unguarded check accepts it and reads
    it as 1 — the same trap the tool layer already had to close."""
    a_life(world)

    res = delete(world, lives=True)

    assert res.status == 400
    assert body_of(res)["field"] == "lives"
    assert len(world["store"].read_index()) == 1


def test_a_month_being_written_blocks_the_delete(world):
    """The narrator would commit into a run that no longer exists and lose the turn.
    Cannot deadlock: the pending record ages out on its own."""
    run_id = a_life(world)
    world["store"].mark_pending(run_id, turn=2, slot="endless-run-x")

    res = delete(world, lives=1)

    assert res.status == 409
    assert body_of(res)["code"] == "turn_in_flight"
    assert world["lib"].path_for("test-world").is_file()
    assert len(world["store"].read_index()) == 1


# -- the cascade ----------------------------------------------------------


def test_deleting_a_world_erases_the_lives_lived_in_it(world):
    run_id = a_life(world)
    world["store"].mark_briefed(run_id, slot="endless-run-x")

    res = delete(world, lives=1)

    assert res.status == 200
    assert body_of(res)["livesRemoved"] == [run_id]
    assert world["store"].read_index() == []
    assert not (world["data"] / "runs" / run_id).exists()
    # Every key the store writes, not just the obvious two.
    for key in (f"run.{run_id}.state", f"run.{run_id}.prev",
                f"briefed-{run_id}", f"pending-{run_id}"):
        assert world["ctx"].storage.get(key) is None, f"{key} was left behind"


def test_a_life_that_claims_the_world_only_in_its_index_row_is_still_swept(world):
    """A real run reached ``worldId: None`` in state while its index row still named
    the world. Matching on the state alone would leave it stranded forever, because
    the world that could have cleaned it up would be gone."""
    run_id = a_life(world, state_world=None)

    facts = body_of(call(
        routes_mod.world_deletion, world["ctx"], match={"world_id": "test-world"}
    ))
    assert facts["liveCount"] == 1

    assert delete(world, lives=1).status == 200
    assert world["store"].read_index() == []
    assert run_id not in [r.get("runId") for r in world["store"].read_index()]


def test_a_life_in_another_world_is_left_alone(world):
    """The cascade must be a cascade, not a sweep."""
    (world["seeds"] / "other.md").write_text(
        world_file({**HEADER, "id": "other-world", "title": "Other"}), encoding="utf-8"
    )
    world["lib"].ensure_seeds_installed()
    other = a_life(world, world_id="other-world")

    assert delete(world, lives=0).status == 200

    assert [r["runId"] for r in world["store"].read_index()] == [other]
    assert world["lib"].path_for("other-world").is_file()


def test_the_world_is_kept_when_a_life_cannot_be_erased(world, monkeypatch):
    """Lives first, and the world only if they all went. A world removed while one
    of its lives survives leaves a shelf row that can only ever error, with nothing
    left to delete that would clean it up."""
    a_life(world)

    def refuse(_run_id):
        raise OSError("read-only")

    monkeypatch.setattr(RunStore, "delete_run", lambda self, rid: refuse(rid))

    res = delete(world, lives=1)

    assert res.status == 500
    assert body_of(res)["code"] == "lives_not_erased"
    assert world["lib"].path_for("test-world").is_file(), "the world outlived its life"


# -- what the dialog is told ---------------------------------------------


def test_the_preflight_names_every_life_it_would_end(world):
    """A count alone does not tell the player which life they are ending."""
    a_life(world)
    a_life(world)

    facts = body_of(call(
        routes_mod.world_deletion, world["ctx"], match={"world_id": "test-world"}
    ))

    assert facts["liveCount"] == 2
    assert len(facts["lives"]) == 2
    assert facts["title"] == "Test World"
    assert facts["restorable"] is True
    assert facts["onShelf"] is True


def test_a_world_with_no_seed_is_reported_as_unrecoverable(world):
    """The dialog's wording turns on this: "can be put back" must not be said about
    a world nothing can put back."""
    (world["seeds"] / "test-world.md").unlink()

    facts = body_of(call(
        routes_mod.world_deletion, world["ctx"], match={"world_id": "test-world"}
    ))

    assert facts["restorable"] is False
