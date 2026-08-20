"""One simulated life, end to end — the whole memory-graph chain (design §11).

This file plays the narrator's part with scripted turns and drives the REAL
surfaces in order: the MCP tool entry (``call_tool``), the play-view assembly,
and the HTTP handlers (with a minimal fake request), from birth through echo,
keepsake, star map, story card, ending, and the legacy bridge into an heir.

It exists to catch what unit tests structurally cannot: a seam where two
modules each behave to spec but disagree about a shared fact — e.g. what
"this life has ended" means to the ending page versus to the legacy gates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
import memory_graph as mg  # noqa: E402
import memory_routes  # noqa: E402
from view import build_play_view  # noqa: E402
from world import read_world  # noqa: E402

kc_storage = pytest.importorskip("kiro_crew.apps.app_storage")

WORLD = """---
{"id": "w", "title": "石桥世界", "version": "1.0", "language": "zh", "lineage": true,
 "clock": {"unit": "year", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "名字", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "年岁", "primitive": "field"}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
勇者不总是赢。
"""


class FakeRequest:
    """The slice of aiohttp's Request the handlers actually touch."""

    def __init__(self, *, match=None, body=None, query=None):
        self.match_info = match or {}
        self._body = body or {}
        self.query = query or {}

    def get(self, key, default=None):
        return {"user": "player"}.get(key, default)

    async def json(self):
        return self._body


def handle(handler, ctx, **kw):
    """Run one async handler to completion. Sync on purpose: this suite has no
    async plugin, and one event loop per call keeps the acts independent."""
    import asyncio

    async def _go():
        return await handler(FakeRequest(**kw), ctx)

    resp = asyncio.run(_go())
    body = resp.body.decode("utf-8") if resp.body else ""
    try:
        return resp.status, json.loads(body)
    except ValueError:
        return resp.status, body


@pytest.fixture()
def world(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    ctx = SimpleNamespace(
        storage=kc_storage.AppStorage("endless-worlds", data), data_dir=data
    )
    return ctx


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


def narrate(run, turn, prose, state, memory=None):
    args = {"runId": run, "turn": turn, "prose": prose, "state": state,
            "choices": [{"id": "go", "label": "go on"}]}
    if memory is not None:
        args["memory"] = memory
    out = call("endless_advance_turn", **args)
    assert out.get("committed") is True, f"turn {turn} refused: {out}"
    return out


def test_one_life_from_birth_to_inheritance(world):
    ctx = world
    store = srv._store()
    pack = read_world(WORLD)

    # ── Act I · 相遇 ────────────────────────────────────────────────────
    run = store.create_run(
        {"turn": 0, "worldId": "w", "language": "zh", "alive": True},
        {"runId": "", "worldId": "w", "title": "石桥世界", "turn": 0},
    )
    narrate(run, 1, "洪水冲桥，你把艾琳拉上岸。", {"alive": True, "age": 16}, memory={
        "entities": [
            {"id": "elin", "kind": "character", "name": "艾琳"},
            {"id": "bridge", "kind": "place", "name": "老石桥"},
            {"id": "debt", "kind": "thread", "name": "艾琳欠下的人情"},
        ],
        "events": [
            {"key": "saved", "title": "在石桥下救出艾琳", "summary": "你把她拉上岸。",
             "importance": "major", "participants": ["player", "elin"],
             "place": "bridge", "threads": [{"id": "debt", "effect": "opened"}],
             "disclosure": "known"},
        ],
        "relations": [
            {"from": "elin", "type": "trust", "to": "player",
             "change": "increase", "reasonEvent": "saved"},
        ],
    })

    # ── Act II · 静默的岁月 ─────────────────────────────────────────────
    narrate(run, 2, "平静的一年。", {"alive": True, "age": 17})
    narrate(run, 3, "又一年。", {"alive": True, "age": 18})

    # ── Act III · 回响 ──────────────────────────────────────────────────
    runtime = call("endless_read_runtime", runId=run)
    candidate_ids = {c["id"] for c in runtime.get("memoryCandidates") or []}
    assert "event:1:saved" in candidate_ids, "the open thread was not recalled"

    narrate(run, 4, "多年后，她记得那一天。", {"alive": True, "age": 19}, memory={
        "events": [
            {"key": "repaid", "title": "艾琳还了人情", "summary": "她记得石桥下的那一天。",
             "participants": ["player", "elin"],
             "threads": [{"id": "debt", "effect": "resolved"}],
             "echoes": ["event:1:saved"], "disclosure": "known"},
        ],
    })
    view = build_play_view(pack.template, store.read_state(run),
                           chronicle=store.read_chronicle(run))
    (marker,) = view["echoes"]
    assert marker["sourceTurn"] == 1 and marker["currentId"] == "event:4:repaid"

    # ── Act IV · 收藏与星图 ─────────────────────────────────────────────
    status, kp = handle(
        memory_routes.create_keepsake, ctx,
        match={"run_id": run},
        body={"kind": "echo", "title": "石桥下的因果",
              "cites": [marker["sourceId"], marker["currentId"]]},
    )
    assert status == 200, kp

    status, star = handle(
        memory_routes.get_star, ctx, match={"run_id": run},
    )
    assert status == 200
    node_ids = {n["id"] for n in star["nodes"]}
    assert {"event:1:saved", "event:4:repaid", "elin", "bridge", "debt"} <= node_ids
    assert len(star["keepsakes"]) == 1
    assert any(e["type"] == "echoes" for e in star["edges"])

    # ── Act V · 故事卡 ─────────────────────────────────────────────────
    status, drafted = handle(
        memory_routes.preview_story_card, ctx,
        match={"run_id": run}, body={"keepsakeId": kp["id"]},
    )
    assert status == 200, drafted
    card_id = drafted["card"]["id"]

    status, edited = handle(
        memory_routes.edit_story_card, ctx,
        match={"run_id": run, "card_id": card_id},
        body={"title": "那一天", "coverLine": "有些事，世界一直记得。",
              "entities": {"elin": {"display": "少女A"}}},
    )
    assert status == 200, edited

    status, html_out = handle(
        memory_routes.export_story_card, ctx,
        match={"run_id": run, "card_id": card_id}, query={"format": "html"},
    )
    assert status == 200
    assert "少女A" in html_out and "艾琳" not in html_out
    assert run not in html_out and "<script" not in html_out.lower()

    # ── Act VI · 终章（由世界的 ending 条件触发，narrator 未写 ended） ──
    narrate(run, 5, "她陪你走完最后一程。", {"alive": False, "age": 80}, memory={
        "events": [
            {"key": "farewell", "title": "落幕", "summary": "一生走到了尽头。",
             "participants": ["player", "elin"], "disclosure": "known"},
        ],
    })
    view = build_play_view(pack.template, store.read_state(run),
                           chronicle=store.read_chronicle(run))
    assert view["ended"] is True and view["lineage"] is True, (
        "the ending page would offer the bridge…"
    )

    status, cands = handle(
        memory_routes.get_legacy_candidates, ctx, match={"run_id": run},
    )
    assert status == 200, (
        f"…but the candidates gate answered {status}: {cands} — the ending "
        "page and the legacy gate disagree about what 'ended' means"
    )
    offered = {row["id"] for rows in cands["candidates"].values() for row in rows}
    assert "elin" in offered

    # ── Act VII · 传承 ─────────────────────────────────────────────────
    import routes as routes_mod

    src_chronicle_path = ctx.data_dir / "runs" / run / "chronicle.jsonl"
    src_before = src_chronicle_path.read_bytes()

    status, created = handle(
        routes_mod.create_run, ctx,
        body={"worldId": "w", "language": "zh",
              "legacy": {"fromRunId": run, "selected": ["elin", "debt"]}},
    )
    assert status == 201, created
    heir = created["runId"]

    heir_runtime = call("endless_read_runtime", runId=heir)
    inherited = {e["id"] for e in heir_runtime["legacy"]["entities"]}
    assert inherited == {"elin", "debt"}
    blob = json.dumps(heir_runtime, ensure_ascii=False)
    assert run not in blob, "the ancestor's run id reached the heir's narrator"

    # The heir lives; the ancestor never changes.
    narrate(heir, 1, "新的一生，从熟悉的名字开始。", {"alive": True, "age": 0})
    assert src_chronicle_path.read_bytes() == src_before

    # And the heir's own star map shows the inheritance as a real, known event.
    status, heir_star = handle(
        memory_routes.get_star, ctx, match={"run_id": heir},
    )
    assert status == 200
    heir_nodes = {n["id"] for n in heir_star["nodes"]}
    assert "elin" in heir_nodes and "event:0:legacy-bridge" in heir_nodes
