"""A gone or damaged life answers a status code, never a traceback.

``RunStore.read_state`` never returns a falsy value — it raises. The play page
polls ``GET /runs/{id}`` on a 3s loop, so one deleted life whose poll is still
in flight (another tab, a stale bookmark) must poll as a clean 404 the SPA can
act on, not a 500 storm. Every player-reachable handler that loads run state
goes through ``routes._load_run_state`` for exactly this reason; these tests
execute the handlers the way ``test_delete_life`` does, because this suite's
blind spot around handler bodies has shipped live bugs before.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import routes as routes_mod  # noqa: E402
from scenes import SceneLedger  # noqa: E402
from store import RunStore  # noqa: E402
from test_delete_world import FakeCtx, FakeRequest, body_of, call  # noqa: E402

GHOST = "0" * 32


def call_advance(ctx, **kw):
    """`advance_run_turn` checks the chat runtime (`request.app["state"]`) before
    the run; hand it a non-None one so the test reaches the state guard."""
    import asyncio

    req = FakeRequest(**kw)
    req.app = {"state": object()}
    return asyncio.run(routes_mod.advance_run_turn(req, ctx))


@pytest.fixture()
def app(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    storage = AppStorage("endless-worlds", data)
    return {"ctx": FakeCtx(data, storage), "store": RunStore(storage, data), "data": data}


def corrupt_life(app) -> str:
    """A run whose state file exists but no longer parses."""
    run_id = app["store"].create_run(
        {"turn": 2, "worldId": "test-world"},
        {"worldId": "test-world", "title": "Test World", "turn": 2},
    )
    state_file = app["store"]._kv_file(RunStore._state_key(run_id))
    state_file.write_text("{ not json", encoding="utf-8")
    return run_id


# -- a life that never existed ------------------------------------------


def test_a_ghost_life_polls_as_404_everywhere(app):
    m = {"run_id": GHOST}
    assert call(routes_mod.get_run, app["ctx"], match=m).status == 404
    assert call(routes_mod.get_backdrop, app["ctx"], match=m).status == 404
    assert call(
        routes_mod.get_scene, app["ctx"], match={**m, "scene_id": "s1"}
    ).status == 404
    assert call_advance(app["ctx"], match=m, body={}).status == 404


def test_a_malformed_run_id_is_a_4xx_not_a_500(app):
    m = {"run_id": "../escape"}
    assert call(routes_mod.get_run, app["ctx"], match=m).status == 404
    assert call(
        routes_mod.answer_scene, app["ctx"], match={**m, "scene_id": "s1"},
        body={"nonce": "n", "choice": "c"},
    ).status == 404


# -- a life whose state no longer parses ---------------------------------


def test_a_damaged_life_answers_422_with_a_readable_error(app):
    run_id = corrupt_life(app)
    res = call(routes_mod.get_run, app["ctx"], match={"run_id": run_id})
    assert res.status == 422
    assert "damaged" in body_of(res)["error"]


def test_advance_on_a_damaged_life_is_422_not_500(app):
    run_id = corrupt_life(app)
    res = call_advance(
        app["ctx"], match={"run_id": run_id}, body={"action": "look around"}
    )
    assert res.status == 422


def test_scene_document_is_response_sandboxed_even_when_navigated_directly(app):
    run_id = app["store"].create_run(
        {"turn": 1, "worldId": "test-world"},
        {"worldId": "test-world", "title": "Test World", "turn": 1},
    )
    SceneLedger(app["data"], run_id).mount(
        "map", {"elements": [{"kind": "text", "text": "safe"}]}
    )

    res = call(
        routes_mod.get_scene,
        app["ctx"],
        match={"run_id": run_id, "scene_id": "map"},
    )

    assert res.status == 200
    csp = res.headers["Content-Security-Policy"]
    assert "sandbox allow-scripts allow-forms" in csp
    assert "allow-same-origin" not in csp
    assert "frame-ancestors 'self'" in csp
    assert res.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert res.headers["Referrer-Policy"] == "no-referrer"
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "SAMEORIGIN"
