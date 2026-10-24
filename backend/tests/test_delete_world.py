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
import time
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
    "panels": [
        {
            "id": "status",
            "always": True,
            "fields": [{"id": "age", "label": "Age", "primitive": "field"}],
        }
    ],
    "endings": [{"id": "died", "when": "state.alive == false"}],
}


def world_file(header: dict | None = None) -> str:
    return f"---\n{json.dumps(header or HEADER, ensure_ascii=False)}\n---\n{PROSE}"


# -- harness --------------------------------------------------------------


class FakeRequest:
    """Only what the handlers touch: an authenticated user, path params, a body."""

    def __init__(self, *, match=None, body=None, user="someone", query=None):
        self.match_info = match or {}
        self.query = query or {}
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
        routes_mod.delete_world,
        world["ctx"],
        match={"world_id": world_id},
        body={"confirm": confirm, "lives": lives},
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


def test_a_world_that_would_fail_halfway_is_refused_whole(world):
    """delete_run is irreversible and the lives loop cannot roll back — so a
    world holding one undeletable life must be refused with EVERY life intact,
    not left on the shelf minus the lives the loop got through."""
    import os
    import stat

    healthy = a_life(world)
    locked = a_life(world)
    locked_dir = world["data"] / "runs" / locked
    assert locked_dir.is_dir(), "the pre-flight needs a real directory to judge"
    mode = locked_dir.stat().st_mode
    locked_dir.chmod(stat.S_IREAD | stat.S_IEXEC)  # unwritable: children can't go
    if os.access(locked_dir, os.W_OK):
        pytest.skip("running as a user the chmod cannot restrict (root/CAP_DAC)")

    try:
        res = delete(world, lives=2)

        assert res.status == 409
        body = body_of(res)
        assert body["code"] == "lives_not_erasable"
        assert [f["runId"] for f in body["failed"]] == [locked]
        # The whole point: NOTHING was destroyed, including the healthy life.
        index_ids = {r.get("runId") for r in world["store"].read_index()}
        assert index_ids == {healthy, locked}
        assert (world["data"] / "runs" / healthy).is_dir()
    finally:
        locked_dir.chmod(mode)


def test_deleting_a_world_erases_the_lives_lived_in_it(world):
    run_id = a_life(world)
    world["store"].mark_briefed(run_id, slot="endless-run-x")

    res = delete(world, lives=1)

    assert res.status == 200
    assert body_of(res)["livesRemoved"] == [run_id]
    assert world["store"].read_index() == []
    assert not (world["data"] / "runs" / run_id).exists()
    # Every key the store writes, not just the obvious two.
    for key in (
        f"run.{run_id}.state",
        f"run.{run_id}.prev",
        f"briefed-{run_id}",
        f"pending-{run_id}",
    ):
        assert world["ctx"].storage.get(key) is None, f"{key} was left behind"


def test_a_life_that_claims_the_world_only_in_its_index_row_is_still_swept(world):
    """A real run reached ``worldId: None`` in state while its index row still named
    the world. Matching on the state alone would leave it stranded forever, because
    the world that could have cleaned it up would be gone."""
    run_id = a_life(world, state_world=None)

    facts = body_of(call(routes_mod.world_deletion, world["ctx"], match={"world_id": "test-world"}))
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

    facts = body_of(call(routes_mod.world_deletion, world["ctx"], match={"world_id": "test-world"}))

    assert facts["liveCount"] == 2
    assert len(facts["lives"]) == 2
    assert facts["title"] == "Test World"
    assert facts["restorable"] is True
    assert facts["onShelf"] is True


def test_a_world_with_no_seed_is_reported_as_unrecoverable(world):
    """The dialog's wording turns on this: "can be put back" must not be said about
    a world nothing can put back."""
    (world["seeds"] / "test-world.md").unlink()

    facts = body_of(call(routes_mod.world_deletion, world["ctx"], match={"world_id": "test-world"}))

    assert facts["restorable"] is False


def test_requested_art_withholds_the_new_page_until_its_exact_commit(world):
    """The store may hold turn 2, but GET publishes turn 1 until turn 2 art lands."""
    from backdrop import BackdropStore

    store = world["store"]
    run_id = store.create_run(
        {"turn": 1, "worldId": "test-world", "style": "standard", "status": {"age": "one"}},
        {"worldId": "test-world", "title": "Test World", "turn": 1},
    )
    store.append_turn(run_id, {"turn": 1, "prose": "the old page"})
    store.commit_state(
        run_id,
        {"turn": 2, "worldId": "test-world", "style": "standard", "status": {"age": "two"}},
    )
    store.append_turn(run_id, {"turn": 2, "prose": "the hidden page"})
    store.request_backdrop(run_id, turn=2, brief="a red gate closes")

    waiting = body_of(call(routes_mod.get_run, world["ctx"], match={"run_id": run_id}))
    assert waiting["turn"] == 1
    assert waiting["prose"] == "the old page"
    assert waiting["generating"]["stage"] == "painting"
    waiting_history = body_of(
        call(routes_mod.get_chronicle, world["ctx"], match={"run_id": run_id})
    )
    assert [entry["turn"] for entry in waiting_history["turns"]] == [1]

    BackdropStore(world["data"], run_id).set(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
        turn=2,
    )
    store.clear_backdrop_request(run_id)

    published = body_of(call(routes_mod.get_run, world["ctx"], match={"run_id": run_id}))
    assert published["turn"] == 2
    assert published["prose"] == "the hidden page"
    assert published["generating"] is None
    assert published["backdrop"]["version"] == 1
    published_history = body_of(
        call(routes_mod.get_chronicle, world["ctx"], match={"run_id": run_id})
    )
    assert [entry["turn"] for entry in published_history["turns"]] == [2, 1]


def test_two_failed_illustrators_notify_the_same_narrator_behind_the_gate(world, monkeypatch):
    from backdrop import BackdropStore

    store = world["store"]
    run_id = store.create_run(
        {"turn": 1, "worldId": "test-world", "style": "standard"},
        {"worldId": "test-world", "title": "Test World", "turn": 1},
    )
    store.request_backdrop(run_id, turn=1, brief="a red gate closes")

    class FinishedWithoutArt:
        def __init__(self):
            self.calls = []

        async def run(self, task, *, agent, silent, model):
            self.calls.append((task, agent, silent, model))
            return f"spawn-{len(self.calls)}"

        def is_done(self, _spawn_id):
            return True

    spawn = FinishedWithoutArt()
    world["ctx"].spawn = spawn
    slot = object()
    prompts = []

    monkeypatch.setattr(routes_mod, "ensure_narrator_slot_ex", lambda *a, **k: (slot, False))

    def fake_dispatcher(_runner):
        def dispatch(_state, got_slot, prompt, **_kw):
            assert got_slot is slot
            gated = store.read_backdrop_request(run_id)
            assert gated["fallbackAllowed"] is True
            prompts.append(prompt)
            BackdropStore(world["data"], run_id).set(
                '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
                turn=1,
            )
            store.clear_backdrop_request(run_id)
            return True

        return dispatch

    monkeypatch.setattr(routes_mod, "make_dispatcher", fake_dispatcher)
    monkeypatch.setattr(routes_mod, "_narrator_runner", lambda: object())
    asyncio.run(
        routes_mod._recover_backdrop(
            world["ctx"],
            store,
            object(),
            run_id,
            painter_model="paint-model",
            narrator_model="story-model",
            reasoning_effort="high",
        )
    )

    assert len(spawn.calls) == 2
    assert all(call[1] == "endless-illustrator" for call in spawn.calls)
    for task, _agent, _silent, _model in spawn.calls:
        assert "In LANE: scene, first call endless_trace_reference" in task
        assert "in LANE: motif, draw directly without tracing" in task
        assert task.index("endless_trace_reference") < task.index("endless_submit_backdrop_draft")
        assert "First call endless_submit_backdrop_draft" not in task
        assert "draw directly from the brief" not in task
    assert len(prompts) == 1
    assert "do NOT narrate" in prompts[0]
    assert "endless_commit_fallback_backdrop" in prompts[0]
    assert store.read_backdrop_request(run_id) is None


def test_fast_art_quality_dispatches_one_illustrator_and_skips_the_revision_pass(
    world, monkeypatch
):
    """The player's fast tier is enforced at the recovery loop, not suggested:
    one illustrator attempt (standard gets two), and that attempt's task tells it
    to ship its first competent draft instead of spending a revision pass."""
    from backdrop import BackdropStore

    store = world["store"]
    run_id = store.create_run(
        {"turn": 1, "worldId": "test-world", "style": "standard"},
        {"worldId": "test-world", "title": "Test World", "turn": 1},
    )
    store.request_backdrop(run_id, turn=1, brief="a red gate closes")

    class FinishedWithoutArt:
        def __init__(self):
            self.calls = []

        async def run(self, task, *, agent, silent, model):
            self.calls.append((task, agent, silent, model))
            return f"spawn-{len(self.calls)}"

        def is_done(self, _spawn_id):
            return True

    spawn = FinishedWithoutArt()
    world["ctx"].spawn = spawn
    slot = object()

    monkeypatch.setattr(routes_mod, "ensure_narrator_slot_ex", lambda *a, **k: (slot, False))

    def fake_dispatcher(_runner):
        def dispatch(_state, _slot, _prompt, **_kw):
            # The narrator repair commits art, ending the recovery loop.
            BackdropStore(world["data"], run_id).set(
                '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
                turn=1,
            )
            store.clear_backdrop_request(run_id)
            return True

        return dispatch

    monkeypatch.setattr(routes_mod, "make_dispatcher", fake_dispatcher)
    monkeypatch.setattr(routes_mod, "_narrator_runner", lambda: object())
    asyncio.run(
        routes_mod._recover_backdrop(
            world["ctx"],
            store,
            object(),
            run_id,
            painter_model="paint-model",
            narrator_model="story-model",
            reasoning_effort="high",
            art_quality="fast",
        )
    )

    assert len(spawn.calls) == 1, "fast tier must cap the illustrators at one attempt"
    task = spawn.calls[0][0]
    assert "fast art mode: no revision pass" in task
    assert "revise at most once" not in task


# -- late illustrator commit grace ------------------------------------------------


_ART = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'


class _Illustrator:
    """A spawn double: alive until it commits (or forever), optionally drafting."""

    def __init__(self, world, run_id, *, commit_after=None, alive=True):
        self.world = world
        self.run_id = run_id
        self.commit_after = commit_after
        self.alive = alive
        self.calls = []

    async def run(self, task, *, agent, silent, model):
        from backdrop import BackdropStore

        self.calls.append(agent)
        if self.commit_after is not None:

            def commit():
                BackdropStore(self.world["data"], self.run_id).set(_ART, turn=1)
                self.alive = False

            asyncio.get_running_loop().call_later(self.commit_after, commit)
        return f"spawn-{len(self.calls)}"

    def is_done(self, _spawn_id):
        return not self.alive


def _recover_with(world, monkeypatch, spawn, *, drafted, grace):
    """Run one recovery with a tiny model budget; return the narrator prompts."""
    from backdrop import BackdropDraftStore, BackdropStore

    store = world["store"]
    run_id = spawn.run_id
    store.request_backdrop(run_id, turn=1, brief="a red gate closes")
    if drafted:
        BackdropDraftStore(world["data"], run_id)._save(
            {"draftId": "d1", "turn": 1, "previews": {}}
        )
    world["ctx"].spawn = spawn
    monkeypatch.setattr(routes_mod, "_BACKDROP_FALLBACK_SECS", 0.1)
    monkeypatch.setattr(routes_mod, "_BACKDROP_POLL_SECS", 0.01)
    monkeypatch.setattr(routes_mod, "_BACKDROP_LATE_COMMIT_GRACE_SECS", grace)
    monkeypatch.setattr(routes_mod, "ensure_narrator_slot_ex", lambda *a, **k: (object(), False))
    prompts = []

    def fake_dispatcher(_runner):
        def dispatch(_state, _slot, prompt, **_kw):
            prompts.append(prompt)
            BackdropStore(world["data"], run_id).set(_ART, turn=1)
            store.clear_backdrop_request(run_id)
            return True

        return dispatch

    monkeypatch.setattr(routes_mod, "make_dispatcher", fake_dispatcher)
    monkeypatch.setattr(routes_mod, "_narrator_runner", lambda: object())
    asyncio.run(
        routes_mod._recover_backdrop(
            world["ctx"],
            store,
            object(),
            run_id,
            painter_model="",
            narrator_model="",
            reasoning_effort="",
        )
    )
    return prompts


def _new_life(world):
    return world["store"].create_run(
        {"turn": 1, "worldId": "test-world", "style": "standard"},
        {"worldId": "test-world", "title": "Test World", "turn": 1},
    )


def test_a_drafted_illustrator_finishing_late_is_waited_for_not_repaired(world, monkeypatch):
    """The budget fires while the illustrator is one commit away: its commit lands
    inside the grace, so no narrator repair turn is paid for and no second artist
    paints over the page."""
    from backdrop_timing import BackdropTimeline

    run_id = _new_life(world)
    spawn = _Illustrator(world, run_id, commit_after=0.3)
    prompts = _recover_with(world, monkeypatch, spawn, drafted=True, grace=5.0)

    assert prompts == []
    assert spawn.calls == ["endless-illustrator"]
    assert world["store"].read_backdrop_request(run_id) is None
    steps = [e["step"] for e in BackdropTimeline(world["data"], run_id).read(1)]
    assert steps[-1] == "recover:illustrator-late-commit"


def test_an_illustrator_with_no_draft_gets_no_grace(world, monkeypatch):
    """Still drawing, nothing submitted: no commit is on its way, so the repair is
    not delayed by the grace."""
    import time as _time

    run_id = _new_life(world)
    spawn = _Illustrator(world, run_id)
    started = _time.monotonic()
    prompts = _recover_with(world, monkeypatch, spawn, drafted=False, grace=30.0)

    assert len(prompts) == 1
    assert _time.monotonic() - started < 10.0


def test_an_ended_illustrator_gets_no_grace_even_with_a_draft(world, monkeypatch):
    """A draft left by an illustrator that has already ended will never be
    committed, so the narrator repair runs at once."""
    import time as _time

    run_id = _new_life(world)
    spawn = _Illustrator(world, run_id, alive=False)
    started = _time.monotonic()
    prompts = _recover_with(world, monkeypatch, spawn, drafted=True, grace=30.0)

    assert len(prompts) == 1
    assert _time.monotonic() - started < 10.0


# -- the illustrator starts with the brief, not after the prose ------------------


def _svg_of(color):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<rect fill="{color}" width="10" height="10"/></svg>'
    )


class _Recorder:
    """A spawn double that records each task; alive until told otherwise."""

    def __init__(self, *, alive=True):
        self.alive = alive
        self.tasks = []
        self.turns_at_dispatch = []
        self.store = None
        self.run_id = ""

    async def run(self, task, *, agent, silent, model):
        self.tasks.append(task)
        if self.store is not None:
            self.turns_at_dispatch.append(int(self.store.read_state(self.run_id)["turn"]))
        return f"spawn-{len(self.tasks)}"

    def is_done(self, _spawn_id):
        return not self.alive


def _writing_page_two(world, brief="LANE: motif\nTHESIS: a gate closes"):
    """A life on page 1 whose narrator is writing page 2 and has briefed its art."""
    store = world["store"]
    run_id = store.create_run(
        {"turn": 1, "worldId": "test-world", "style": "standard", "status": {"age": "one"}},
        {"worldId": "test-world", "title": "Test World", "turn": 1},
    )
    store.append_turn(run_id, {"turn": 1, "prose": "the old page"})
    store.mark_pending(run_id, turn=2, slot="endless-run-x")
    pending_at = store.read_pending(run_id)["askedAt"]
    store.request_backdrop(run_id, turn=2, brief=brief, pending_at=pending_at)
    return run_id


def _commit_page_two(store, run_id):
    store.commit_state(
        run_id,
        {"turn": 2, "worldId": "test-world", "style": "standard", "status": {"age": "two"}},
    )
    store.append_turn(run_id, {"turn": 2, "prose": "the new page"})
    store.clear_pending(run_id)


def _with_spawn(world, run_id, spawn):
    spawn.store = world["store"]
    spawn.run_id = run_id
    world["ctx"].spawn = spawn
    return spawn


def _stop_recovery(run_id):
    task = routes_mod._BACKDROP_RECOVERY_TASKS.get(run_id)
    if task is not None:
        task.cancel()


def test_a_brief_for_the_page_being_written_starts_its_illustrator_at_once(world):
    """The polling GET that runs while a month is written notices the brief and
    dispatches the illustrator for THAT page, before its prose commits. Started
    only after the commit, the illustrator's whole run sat behind the narrator's."""
    run_id = _writing_page_two(world)
    spawn = _with_spawn(world, run_id, _Recorder())
    brief_id = world["store"].read_backdrop_request(run_id)["briefId"]

    async def main():
        res = await routes_mod.get_run(FakeRequest(match={"run_id": run_id}), world["ctx"])
        await asyncio.sleep(0.05)
        _stop_recovery(run_id)
        return res

    res = asyncio.run(main())

    assert body_of(res)["turn"] == 1
    assert len(spawn.tasks) == 1, "no illustrator started for the page being written"
    assert spawn.turns_at_dispatch == [1], "dispatched only after the prose committed"
    assert "turn: 2" in spawn.tasks[0]
    assert f"briefId: {brief_id}" in spawn.tasks[0]


def test_the_prose_commit_does_not_start_a_second_illustrator(world):
    """One recovery task per run: the commit's own call finds the early task
    running and starts nothing, so the page is painted once."""
    run_id = _writing_page_two(world)
    spawn = _with_spawn(world, run_id, _Recorder())
    store = world["store"]

    async def main():
        routes_mod._ensure_backdrop_recovery(world["ctx"], store, None, run_id, {})
        await asyncio.sleep(0.05)
        _commit_page_two(store, run_id)
        routes_mod._ensure_backdrop_recovery(world["ctx"], store, None, run_id, {})
        await routes_mod.get_run(FakeRequest(match={"run_id": run_id}), world["ctx"])
        await asyncio.sleep(0.05)
        _stop_recovery(run_id)

    asyncio.run(main())
    assert len(spawn.tasks) == 1


def test_a_brief_from_an_abandoned_attempt_starts_nothing(world):
    """A brief bound to an attempt that is no longer the in-flight one (it ended,
    or a retry replaced its record) must not start an illustrator."""
    store = world["store"]

    async def main(run_id):
        routes_mod._ensure_backdrop_recovery(world["ctx"], store, None, run_id, {})
        await asyncio.sleep(0.05)
        _stop_recovery(run_id)

    ended = _writing_page_two(world)
    spawn = _with_spawn(world, ended, _Recorder())
    store.mark_pending_ended(ended)
    asyncio.run(main(ended))
    assert spawn.tasks == []

    # A retry's fresh in-flight record for the same page, before it briefed.
    replaced = _writing_page_two(world)
    spawn = _with_spawn(world, replaced, _Recorder())
    time.sleep(0.01)
    store.mark_pending(replaced, turn=2, slot="endless-run-x")
    asyncio.run(main(replaced))
    assert spawn.tasks == []


def test_art_drawn_early_publishes_with_its_page_and_never_before(world):
    """Art the illustrator commits while the prose is still being written is
    stored for page 2, but no reader shows it until page 2 commits — then the page
    and its art publish together, with no painting wait."""
    from backdrop import BackdropStore

    run_id = _writing_page_two(world)
    store = world["store"]
    art = BackdropStore(world["data"], run_id)
    art.set(_svg_of("#111111"), turn=1)
    art.set(_svg_of("#222222"), turn=2)
    store.clear_backdrop_request(run_id)  # what the illustrator's commit does

    page = body_of(call(routes_mod.get_run, world["ctx"], match={"run_id": run_id}))
    assert page["turn"] == 1
    assert page["backdrop"]["version"] == 1
    shelf = body_of(call(routes_mod.list_runs, world["ctx"]))
    assert [row["backdrop"]["version"] for row in shelf["runs"]] == [1]
    live = call(routes_mod.get_backdrop, world["ctx"], match={"run_id": run_id})
    assert b"#111111" in live.body
    ahead = call(
        routes_mod.get_backdrop, world["ctx"], match={"run_id": run_id}, query={"turn": "2"}
    )
    assert b"#111111" in ahead.body, "the next page's art leaked through ?turn="

    _commit_page_two(store, run_id)

    page = body_of(call(routes_mod.get_run, world["ctx"], match={"run_id": run_id}))
    assert page["turn"] == 2
    assert page["prose"] == "the new page"
    assert page["generating"] is None
    assert page["backdrop"]["version"] == 2
    live = call(routes_mod.get_backdrop, world["ctx"], match={"run_id": run_id})
    assert b"#222222" in live.body


def _narrator_recorder(world, monkeypatch, run_id):
    """Record the repair prompts and the committed turn each one saw."""
    from backdrop import BackdropStore

    store = world["store"]
    seen = []
    monkeypatch.setattr(routes_mod, "ensure_narrator_slot_ex", lambda *a, **k: (object(), False))

    def fake_dispatcher(_runner):
        def dispatch(_state, _slot, prompt, **_kw):
            seen.append((int(store.read_state(run_id)["turn"]), time.monotonic()))
            BackdropStore(world["data"], run_id).set(_svg_of("#333333"), turn=2)
            store.clear_backdrop_request(run_id)
            return True

        return dispatch

    monkeypatch.setattr(routes_mod, "make_dispatcher", fake_dispatcher)
    monkeypatch.setattr(routes_mod, "_narrator_runner", lambda: object())
    return seen


def _recover(world, run_id):
    return routes_mod._recover_backdrop(
        world["ctx"],
        world["store"],
        object(),
        run_id,
        painter_model="",
        narrator_model="",
        reasoning_effort="",
    )


def test_an_illustrator_for_a_page_that_never_commits_is_dropped_not_repaired(world, monkeypatch):
    """The narrator briefs, the illustrator starts, then the narrator's run ends
    with no month. Recovery stops at once: no second illustrator, no repair prompt
    into a conversation that has no page, no art for a page that never existed."""
    from backdrop import BackdropStore

    run_id = _writing_page_two(world)
    spawn = _with_spawn(world, run_id, _Recorder())
    seen = _narrator_recorder(world, monkeypatch, run_id)
    monkeypatch.setattr(routes_mod, "_BACKDROP_FALLBACK_SECS", 5.0)
    monkeypatch.setattr(routes_mod, "_BACKDROP_POLL_SECS", 0.01)

    async def main():
        asyncio.get_running_loop().call_later(0.2, world["store"].mark_pending_ended, run_id)
        started = time.monotonic()
        await _recover(world, run_id)
        return time.monotonic() - started

    elapsed = asyncio.run(main())

    assert len(spawn.tasks) == 1, "a second illustrator was sent to an abandoned page"
    assert seen == []
    assert elapsed < 2.0, "recovery waited out the budget for an abandoned page"
    assert BackdropStore(world["data"], run_id).exact(2) is None


def test_the_narrator_repair_waits_for_the_page_being_written(world, monkeypatch):
    """The repair prompt goes to the same conversation that is writing the page;
    sent mid-turn, it would interrupt the month it is meant to illustrate."""
    run_id = _writing_page_two(world)
    _with_spawn(world, run_id, _Recorder(alive=False))  # ends without art
    seen = _narrator_recorder(world, monkeypatch, run_id)
    monkeypatch.setattr(routes_mod, "_BACKDROP_FALLBACK_SECS", 0.05)
    monkeypatch.setattr(routes_mod, "_BACKDROP_POLL_SECS", 0.01)

    async def main():
        asyncio.get_running_loop().call_later(0.4, _commit_page_two, world["store"], run_id)
        await _recover(world, run_id)

    asyncio.run(main())
    assert [turn for turn, _at in seen] == [2], "the repair reached the narrator mid-turn"


def test_the_illustrator_budget_runs_from_its_dispatch_not_the_prose_commit(world, monkeypatch):
    """An early start is only worth it if the budget does not restart when the
    prose lands: the page's fallback point is dispatch + budget."""
    run_id = _writing_page_two(world)
    _with_spawn(world, run_id, _Recorder())  # never ends, never drafts
    seen = _narrator_recorder(world, monkeypatch, run_id)
    monkeypatch.setattr(routes_mod, "_BACKDROP_FALLBACK_SECS", 0.8)
    monkeypatch.setattr(routes_mod, "_BACKDROP_POLL_SECS", 0.01)

    async def main():
        asyncio.get_running_loop().call_later(0.5, _commit_page_two, world["store"], run_id)
        started = time.monotonic()
        await _recover(world, run_id)
        return started

    started = asyncio.run(main())
    assert len(seen) == 1
    assert seen[0][1] - started < 1.15, "the budget restarted at the prose commit"
