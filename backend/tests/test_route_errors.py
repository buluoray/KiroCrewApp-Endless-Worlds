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
from backdrop import BackdropStore  # noqa: E402
from scenes import SceneLedger  # noqa: E402
from store import RunStore  # noqa: E402
from test_delete_world import (  # noqa: E402
    FakeCtx, FakeRequest, body_of, call, world_file,
)

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


def _svg(color: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<rect fill="{color}" width="10" height="10"/></svg>'
    )


def test_backdrop_route_selects_variants_and_preserves_legacy_fallback(app):
    run_id = app["store"].create_run(
        {"turn": 5, "worldId": "test-world"},
        {"worldId": "test-world", "title": "Test World", "turn": 5},
    )
    backdrops = BackdropStore(app["data"], run_id)
    backdrops.set(
        _svg("#111"), buttons=_svg("#fed"), turn=1, mobile=_svg("#abc")
    )
    backdrops.set(_svg("#222"), turn=5, mobile=_svg("#def"))
    match = {"run_id": run_id}

    desktop = call(routes_mod.get_backdrop, app["ctx"], match=match)
    mobile = call(
        routes_mod.get_backdrop, app["ctx"], match=match,
        query={"variant": "mobile"},
    )
    historical = call(
        routes_mod.get_backdrop, app["ctx"], match=match,
        query={"turn": "3", "variant": "mobile"},
    )
    buttons = call(
        routes_mod.get_backdrop, app["ctx"], match=match,
        query={"turn": "1", "variant": "mobile", "part": "buttons"},
    )

    assert desktop.status == mobile.status == historical.status == buttons.status == 200
    assert "#222" in desktop.text and "#def" in mobile.text
    assert "#abc" in historical.text
    assert "#fed" in buttons.text, "part=buttons must take precedence over variant"

    legacy_id = app["store"].create_run(
        {"turn": 1, "worldId": "test-world"},
        {"worldId": "test-world", "title": "Legacy", "turn": 1},
    )
    BackdropStore(app["data"], legacy_id).set(_svg("#333"), turn=1)
    legacy_mobile = call(
        routes_mod.get_backdrop, app["ctx"], match={"run_id": legacy_id},
        query={"variant": "mobile"},
    )
    assert legacy_mobile.status == 200 and "#333" in legacy_mobile.text


def test_live_and_chronicle_metadata_report_mobile_and_trace_audit(app):
    worlds = app["data"] / "worlds"
    worlds.mkdir()
    (worlds / "test-world.md").write_text(world_file(), encoding="utf-8")
    run_id = app["store"].create_run(
        {
            "turn": 5, "worldId": "test-world", "style": "standard",
            "status": {"age": "five"},
        },
        {"worldId": "test-world", "title": "Test World", "turn": 5},
    )
    app["store"].append_turn(run_id, {"turn": 1, "prose": "portrait page"})
    app["store"].append_turn(run_id, {"turn": 5, "prose": "desktop page"})
    backdrops = BackdropStore(app["data"], run_id)
    backdrops.set(_svg("#111"), turn=1, mobile=_svg("#abc"))
    trace = {
        "pipeline": "trace",
        "underlay": "base",
        "fragmentId": "0123456789abcdef",
        "query": "moonlit harbor",
        "used": True,
    }
    backdrops.set(_svg("#222"), turn=5, trace=trace)

    live = body_of(call(routes_mod.get_run, app["ctx"], match={"run_id": run_id}))
    history = body_of(
        call(routes_mod.get_chronicle, app["ctx"], match={"run_id": run_id})
    )
    by_turn = {row["turn"]: row for row in history["turns"]}

    assert live["backdrop"]["mobile"] is False
    assert live["backdrop"]["trace"] == trace
    assert by_turn[1]["backdrop"]["mobile"] is True
    assert by_turn[1]["backdrop"]["trace"] is None
    assert by_turn[5]["backdrop"]["mobile"] is False
    assert by_turn[5]["backdrop"]["trace"] == trace
