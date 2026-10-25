"""Closing a life by the player's choice: the ask travels in the app's own
in-flight record, and the commit — the one state writer — ends the life."""

import asyncio
import json

import pytest

import mcp_server as srv
from content import Content
from narrator import APP_NAME, MEMORY_MODE
from turn import advance_turn, compose_prompt, turn_notes
from view import resolve_ending

BASE = {
    "id": "w",
    "title": "World",
    "version": "1.0",
    "language": "en",
    "clock": {"unit": "month", "label": "{year}"},
    "styles": [{"id": "s", "label": "S", "default": True}],
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
FLAGSHIP_LIKE = {
    **BASE,
    "endings": [*BASE["endings"], {"id": "retired", "when": "state.retiredByPlayer == true"}],
}


def _app(tmp_path, monkeypatch, header):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text("---\n" + json.dumps(header) + "\n---\nA world.\n")
    monkeypatch.setattr(srv, "_DATA", data)
    store = srv._store()
    run = store.create_run({"worldId": "w", "turn": 0}, {})
    return store, run


def commit(store, run, **extra):
    args = {
        "runId": run,
        "turn": int(store.read_state(run).get("turn", 0)) + 1,
        "prose": "The bakery's lamps go out one last time.",
        "choices": [{"id": "go", "label": "Go on"}],
        "state": {"status": {"age": "70"}, "alive": True},
        **extra,
    }
    # A narrator answering an app ask reads the runtime first (the commit gate).
    srv.call_tool("endless_read_runtime", {"runId": run})
    return json.loads(srv.call_tool("endless_advance_turn", args))


@pytest.mark.parametrize("header,ending", [(BASE, "retired"), (FLAGSHIP_LIKE, "retired")])
def test_a_close_asked_by_the_player_ends_the_life_at_commit(tmp_path, monkeypatch, header, ending):
    store, run = _app(tmp_path, monkeypatch, header)
    store.mark_pending(run, turn=1, slot="s", close=True)
    # The narrator offered choices and never said the life ended: the player's
    # word, from the app's own record, still closes it.
    result = commit(store, run)
    assert result.get("committed") is True, result
    state = store.read_state(run)
    assert state["ended"] == ending
    assert state["retiredByPlayer"] is True
    assert store.read_chronicle(run)[-1]["choices"] == []
    srv_template = srv.read_world((tmp_path / "data/worlds/w.md").read_text()).template
    assert resolve_ending(srv_template, state) == ending


def test_a_narrator_ending_id_is_kept_on_a_closing_turn(tmp_path, monkeypatch):
    store, run = _app(tmp_path, monkeypatch, BASE)
    store.mark_pending(run, turn=1, slot="s", close=True)
    commit(store, run, ending=True, choices=[], state={"ended": "a-quiet-end", "alive": True})
    assert store.read_state(run)["ended"] == "a-quiet-end"


def test_without_the_players_close_a_living_turn_stays_alive(tmp_path, monkeypatch):
    store, run = _app(tmp_path, monkeypatch, BASE)
    store.mark_pending(run, turn=1, slot="s", action="bake bread")
    assert commit(store, run).get("committed") is True
    state = store.read_state(run)
    assert "ended" not in state and "retiredByPlayer" not in state
    # A close recorded for another month does not close this one.
    store.mark_pending(run, turn=5, slot="s", close=True)
    assert commit(store, run).get("committed") is True
    assert "ended" not in store.read_state(run)


def test_the_close_rides_only_in_the_apps_pending_record(tmp_path, monkeypatch):
    store, run = _app(tmp_path, monkeypatch, BASE)
    store.mark_pending(run, turn=1, slot="s")
    assert "close" not in store.read_pending(run)
    store.mark_pending(run, turn=1, slot="s", close=True)
    assert store.read_pending(run)["close"] is True
    # The narrator's tool has no way to say it: an unknown top-level argument
    # is not a close.
    store.mark_pending(run, turn=1, slot="s")
    commit(store, run, close=True)
    assert "ended" not in store.read_state(run)


def test_the_close_note_is_the_apps_line_not_quoted_player_words():
    notes = turn_notes(language="en", close=True)
    assert Content("en")("turn.close") in notes
    assert Content("en")("turn.action.preamble") not in notes
    assert Content("en")("turn.close") not in turn_notes(language="en")
    # The message itself carries no close line: it reaches the narrator in the read.
    prompt = compose_prompt(state={"turn": 3}, run_id="a" * 32)
    assert Content("en")("turn.close") not in prompt


class _Slot:
    def __init__(self, key):
        self.key = key
        self._app = APP_NAME
        self.memory_mode = MEMORY_MODE
        self.project = ""


class _State:
    def __init__(self):
        self.slots = {}

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, agent="", app="", memory_mode=None, **kw):
        slot = _Slot(name)
        slot.memory_mode = memory_mode or "persistent"
        slot._app = app
        self.slots[name] = slot
        return slot


def test_advance_turn_records_the_close_before_the_narrator_is_asked(tmp_path, monkeypatch):
    store, run = _app(tmp_path, monkeypatch, BASE)
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    seen = {}

    def dispatch(state, slot, prompt, **_kw):
        seen["pending"] = store.read_pending(run)
        seen["prompt"] = prompt
        return True

    asyncio.run(
        advance_turn(
            state_obj=_State(),
            store=store,
            run_id=run,
            dispatch=dispatch,
            inline_wait_secs=0.2,
            close=True,
        )
    )
    assert seen["pending"]["close"] is True and seen["pending"]["turn"] == 2
    assert Content("en")("turn.close") not in seen["prompt"]
    read = json.loads(srv.call_tool("endless_read_runtime", {"runId": run}))
    assert Content("en")("turn.close") in read["thisTurn"], "the read must ask for the epilogue"


def test_a_life_that_has_not_begun_cannot_be_closed(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from kiro_crew.apps.app_storage import AppStorage
    from test_delete_world import FakeCtx, FakeRequest, a_life, body_of, world_file

    import routes as routes_mod
    from library import WorldLibrary
    from store import RunStore

    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "test-world.md").write_text(world_file(), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(routes_mod, "_SEEDS_DIR", seeds)
    WorldLibrary(data, seeds).ensure_seeds_installed()
    storage = AppStorage("endless-worlds", data)
    world = {"ctx": FakeCtx(data, storage), "store": RunStore(storage, data)}
    run_id = a_life(world, turn=0)

    req = FakeRequest(match={"run_id": run_id}, body={"close": True})
    req.app = {"state": object()}
    resp = asyncio.run(routes_mod.advance_run_turn(req, world["ctx"]))
    assert resp.status == 409
    assert body_of(resp)["field"] == "close"
    assert world["store"].read_pending(run_id) is None
