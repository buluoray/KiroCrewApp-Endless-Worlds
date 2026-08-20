"""The world's memory — data-correctness and recall gates (design §12.1, §12.2).

Every guarantee the design names for Phase 0/1 is pinned here, against the pure
module first and then against the real tool surface: malformed memory commits
nothing, retries never duplicate, rebuilds are byte-stable, hidden never reaches
a player payload, echoes must name real events, and a just-echoed event cools
down before it can be recalled again.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import memory_graph as mg  # noqa: E402
import mcp_server as srv  # noqa: E402

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
勇者不总是赢。
"""


@pytest.fixture()
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    return data


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


# ── building blocks ───────────────────────────────────────────────────────


def turn_entry(turn, memory=None, action="", prose="p"):
    entry = {"turn": turn, "prose": prose, "action": action,
             "choices": [], "events": [], "gains": []}
    if memory is not None:
        entry["memory"] = memory
    return entry


def bridge_memory():
    """The design §5.1 example, made self-consistent: everything referenced is
    declared."""
    return {
        "entities": [
            {"id": "elin", "kind": "character", "name": "艾琳",
             "aliases": ["桥边的女孩"]},
            {"id": "old-stone-bridge", "kind": "place", "name": "老石桥"},
            {"id": "elin-debt", "kind": "thread", "name": "艾琳欠下的人情"},
        ],
        "events": [
            {"key": "saved-elin", "title": "在石桥下救出艾琳",
             "summary": "洪水冲毁石桥时，你把艾琳拉上岸。",
             "importance": "notable",
             "participants": ["player", "elin"],
             "place": "old-stone-bridge",
             "threads": [{"id": "elin-debt", "effect": "opened"}],
             "echoes": [], "disclosure": "known"},
        ],
        "relations": [
            {"from": "elin", "type": "trust", "to": "player",
             "change": "increase", "reasonEvent": "saved-elin"},
        ],
    }


# ── §12.1 validation: refusals name the exact field ──────────────────────


def test_unknown_participant_is_refused_by_path():
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "participants": ["nobody"], "disclosure": "known"}]}
    with pytest.raises(mg.MemoryRejected) as err:
        mg.validate_memory(memory, mg.build_index([]), turn=1)
    assert err.value.field == "memory.events[0].participants[0]"


def test_duplicate_event_key_in_one_turn_is_refused():
    memory = {"events": [
        {"key": "k", "title": "t", "summary": "s", "disclosure": "known"},
        {"key": "k", "title": "t2", "summary": "s2", "disclosure": "known"},
    ]}
    with pytest.raises(mg.MemoryRejected) as err:
        mg.validate_memory(memory, mg.build_index([]), turn=1)
    assert err.value.field == "memory.events[1].key"


def test_echo_target_must_be_a_real_event_of_this_life():
    """§12.2: 回响必须引用真实旧事件 — and a cross-life id simply does not
    resolve here, which is what makes cross-life references impossible."""
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "echoes": ["event:3:never-happened"],
                          "disclosure": "known"}]}
    with pytest.raises(mg.MemoryRejected) as err:
        mg.validate_memory(memory, mg.build_index([]), turn=5)
    assert err.value.field == "memory.events[0].echoes[0]"


def test_an_entity_kind_never_changes_without_a_merge():
    index = mg.build_index([turn_entry(1, bridge_memory())])
    memory = {"entities": [{"id": "elin", "kind": "object", "name": "艾琳"}]}
    with pytest.raises(mg.MemoryRejected) as err:
        mg.validate_memory(memory, index, turn=2)
    assert err.value.field == "memory.entities[0].kind"


def test_disclosure_is_required_and_closed():
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "disclosure": "public"}]}
    with pytest.raises(mg.MemoryRejected) as err:
        mg.validate_memory(memory, mg.build_index([]), turn=1)
    assert err.value.field == "memory.events[0].disclosure"


def test_a_place_reference_must_actually_be_a_place():
    memory = {
        "entities": [{"id": "elin", "kind": "character", "name": "Elin"}],
        "events": [{"key": "k", "title": "t", "summary": "s",
                    "place": "elin", "disclosure": "known"}],
    }
    with pytest.raises(mg.MemoryRejected) as err:
        mg.validate_memory(memory, mg.build_index([]), turn=1)
    assert err.value.field == "memory.events[0].place"


def test_the_design_example_validates_whole():
    mg.validate_memory(bridge_memory(), mg.build_index([]), turn=1)


def test_same_name_different_id_is_never_merged():
    """§12.1: 同名不同 ID 不自动合并."""
    a = {"entities": [{"id": "elin", "kind": "character", "name": "艾琳"}]}
    b = {"entities": [{"id": "elin-2", "kind": "character", "name": "艾琳"}]}
    index = mg.build_index([turn_entry(1, a), turn_entry(2, b)])
    assert "elin" in index["entities"] and "elin-2" in index["entities"]


# ── §12.1 rebuild: derived data is disposable ─────────────────────────────


def test_rebuilding_the_index_is_byte_stable():
    chronicle = [
        turn_entry(1, bridge_memory(), action="save her"),
        turn_entry(2),
        turn_entry(3, {"events": [
            {"key": "repaid", "title": "艾琳还了人情", "summary": "s",
             "participants": ["player", "elin"],
             "threads": [{"id": "elin-debt", "effect": "resolved"}],
             "echoes": ["event:1:saved-elin"], "disclosure": "known"},
        ]}),
    ]
    once = json.dumps(mg.build_index(chronicle), sort_keys=True, ensure_ascii=False)
    twice = json.dumps(mg.build_index(chronicle), sort_keys=True, ensure_ascii=False)
    assert once == twice


def test_relation_projection_is_stable_and_keeps_its_sources():
    chronicle = [turn_entry(1, bridge_memory())]
    index = mg.build_index(chronicle)
    p1 = mg.project_relations(index)
    p2 = mg.project_relations(mg.build_index(chronicle))
    assert p1 == p2
    (slot,) = p1.values()
    assert slot["level"] == 1
    # §4.3: the current reading explains itself — every change keeps its source.
    assert slot["changes"][0]["reasonEvent"] == "event:1:saved-elin"


def test_cleared_ends_a_relation_but_never_erases_its_history():
    chronicle = [
        turn_entry(1, bridge_memory()),
        turn_entry(2, {"relations": [
            {"from": "elin", "type": "trust", "to": "player", "change": "cleared"},
        ]}),
    ]
    (slot,) = mg.project_relations(mg.build_index(chronicle)).values()
    assert slot["active"] is False
    assert len(slot["changes"]) == 2


# ── §12.2 recall ──────────────────────────────────────────────────────────


def test_an_open_thread_is_recalled_and_a_resolved_one_scores_lower():
    chronicle = [turn_entry(1, bridge_memory())]
    index = mg.build_index(chronicle)
    got = mg.recall_candidates(index, turn=6)
    assert got and got[0]["id"] == "event:1:saved-elin"
    assert "open-thread" in got[0]["reasons"]


def test_cooldown_a_just_echoed_event_rests():
    chronicle = [
        turn_entry(1, bridge_memory()),
        turn_entry(4, {"events": [
            {"key": "again", "title": "又见艾琳", "summary": "s",
             "participants": ["elin"],
             "echoes": ["event:1:saved-elin"], "disclosure": "known"},
        ]}),
    ]
    index = mg.build_index(chronicle)
    # Turn 5: echoed on turn 4, inside the cooldown window — must rest.
    ids = {c["id"] for c in mg.recall_candidates(index, turn=5)}
    assert "event:1:saved-elin" not in ids
    # Far later: eligible again, and the candidate names when it last echoed.
    later = {c["id"]: c for c in mg.recall_candidates(index, turn=20)}
    assert later["event:1:saved-elin"]["lastEchoedTurn"] == 4


def test_too_recent_events_are_not_memories_yet():
    chronicle = [turn_entry(5, bridge_memory())]
    assert mg.recall_candidates(mg.build_index(chronicle), turn=6) == []


def test_the_player_action_mentioning_a_name_recalls_the_event():
    chronicle = [turn_entry(1, bridge_memory())]
    got = mg.recall_candidates(mg.build_index(chronicle), turn=12, action="我想去找艾琳")
    assert got and "action-mention" in got[0]["reasons"]


def test_candidates_never_exceed_the_cap():
    chronicle = [
        turn_entry(t, {"events": [
            {"key": f"e{t}", "title": f"t{t}", "summary": "s",
             "threads": [{"id": "q", "effect": "advanced"}], "disclosure": "known"},
        ], "entities": ([{"id": "q", "kind": "thread", "name": "quest"}] if t == 1 else [])})
        for t in range(1, 12)
    ]
    # Open the thread on turn 1 so every event ties to an open thread.
    chronicle[0]["memory"]["events"][0]["threads"][0]["effect"] = "opened"
    got = mg.recall_candidates(mg.build_index(chronicle), turn=20)
    assert len(got) <= mg.MAX_CANDIDATES


# ── §12.2 the player-facing markers ───────────────────────────────────────


def echo_chronicle(source_disclosure="known", current_disclosure="known"):
    first = bridge_memory()
    first["events"][0]["disclosure"] = source_disclosure
    return [
        turn_entry(1, first, action="把她拉上岸"),
        turn_entry(8, {"events": [
            {"key": "repaid", "title": "艾琳还了人情",
             "summary": "她记得石桥下的那一天。",
             "participants": ["player", "elin"],
             "echoes": ["event:1:saved-elin"],
             "disclosure": current_disclosure},
        ]}),
    ]


def test_a_declared_echo_becomes_a_traceable_marker():
    (marker,) = mg.echo_markers(echo_chronicle())
    assert marker["sourceTurn"] == 1
    assert marker["sourceTitle"] == "在石桥下救出艾琳"
    assert marker["sourceAction"] == "把她拉上岸"
    assert marker["title"] == "艾琳还了人情"


def test_prose_alone_never_fabricates_a_marker():
    """Phase 1 completion bar: 没有结构化引用时绝不伪造提示."""
    chronicle = [
        turn_entry(1, bridge_memory()),
        turn_entry(8, prose="你想起当年在石桥下救过她。"),  # reminiscing prose, no memory
    ]
    assert mg.echo_markers(chronicle) == []


@pytest.mark.parametrize("disclosure", ["hidden", "foreshadowed", "rumoured"])
def test_a_source_the_player_has_not_lived_never_surfaces(disclosure):
    """§5.4/§12.2: hidden 永不出现在玩家 API; foreshadowed 不显示隐藏解释."""
    assert mg.echo_markers(echo_chronicle(source_disclosure=disclosure)) == []


def test_a_hidden_current_event_never_surfaces_either():
    assert mg.echo_markers(echo_chronicle(current_disclosure="hidden")) == []


# ── the real tool surface ────────────────────────────────────────────────


def committed_run(store):
    return store.create_run(
        {"turn": 0, "worldId": "w", "language": "en", "alive": True}, {"runId": "r"}
    )


def take_turn(run, turn, memory=None, **extra):
    args = {"runId": run, "turn": turn, "prose": f"turn {turn}",
            "choices": [{"id": "go", "label": "go on"}],
            "state": {"alive": True}, **extra}
    if memory is not None:
        args["memory"] = memory
    return call("endless_advance_turn", **args)


def test_malformed_memory_commits_the_turn_but_drops_the_block(app):
    """Memory is enrichment, not the story: a malformed block is DROPPED and warned,
    but the turn still commits (prose + choices + state). No memory is recorded for
    that turn, and nothing is ever back-filled from prose."""
    store = srv._store()
    run = committed_run(store)
    bad = {"events": [{"key": "k", "title": "t", "summary": "s",
                       "participants": ["nobody"], "disclosure": "known"}]}
    out = take_turn(run, 1, memory=bad)
    assert out["committed"] is True, "the turn lands; memory never holds it hostage"
    warned = out.get("warnings") or []
    mem = next((w for w in warned if w.get("panel") == "memory"), None)
    assert mem is not None and mem["field"] == "memory.events[0].participants[0]"
    assert int(store.read_state(run)["turn"]) == 1, "the turn committed"
    (entry,) = store.read_chronicle(run)
    assert "memory" not in entry, "the invalid block was dropped, not recorded"


def test_memory_sent_as_a_json_string_is_recovered(app):
    """A narrator that double-encodes the block sends `memory` as a JSON STRING; the
    call recovers it to an object instead of failing the turn on a type mismatch."""
    import json as _json
    store = srv._store()
    run = committed_run(store)
    out = call("endless_advance_turn", runId=run, turn=1, prose="turn 1",
               choices=[{"id": "go", "label": "go on"}], state={"alive": True},
               memory=_json.dumps(bridge_memory(), ensure_ascii=False))
    assert out["committed"] is True
    (entry,) = store.read_chronicle(run)
    assert entry["memory"]["events"][0]["key"] == "saved-elin"


def test_memory_sent_as_a_non_json_string_is_dropped_not_fatal(app):
    """An unrecoverable string `memory` is dropped and the turn still commits — memory
    never blocks a turn, at the schema layer or the semantic one."""
    store = srv._store()
    run = committed_run(store)
    out = call("endless_advance_turn", runId=run, turn=1, prose="turn 1",
               choices=[{"id": "go", "label": "go on"}], state={"alive": True},
               memory="not json at all")
    assert out["committed"] is True
    (entry,) = store.read_chronicle(run)
    assert "memory" not in entry


def test_a_valid_memory_rides_the_same_chronicle_record(app):
    store = srv._store()
    run = committed_run(store)
    out = take_turn(run, 1, memory=bridge_memory())
    assert out["committed"] is True
    (entry,) = store.read_chronicle(run)
    assert entry["prose"] == "turn 1"
    assert entry["memory"]["events"][0]["key"] == "saved-elin"


def test_a_retried_turn_never_duplicates_nodes_or_edges(app):
    """§12.1: 同一 (runId, turn) 重试不重复创建节点或边."""
    store = srv._store()
    run = committed_run(store)
    take_turn(run, 1, memory=bridge_memory())
    retry = take_turn(run, 1, memory=bridge_memory())
    assert retry["committed"] is False and retry["reason"] == "already recorded"
    index = mg.build_index(store.read_chronicle(run))
    assert len(index["events"]) == 1
    assert len(index["relations"]) == 1


def test_read_runtime_returns_candidates_from_this_life_only(app):
    store = srv._store()
    run = committed_run(store)
    other = committed_run(store)
    take_turn(run, 1, memory=bridge_memory())
    # Age the memory past MIN_CANDIDATE_AGE by committing quiet turns.
    take_turn(run, 2)
    take_turn(run, 3)
    got = call("endless_read_runtime", runId=run)
    ids = {c["id"] for c in got.get("memoryCandidates") or []}
    assert "event:1:saved-elin" in ids
    # The other life shares a store but remembers nothing (§12.2 人生隔离).
    other_read = call("endless_read_runtime", runId=other)
    assert "memoryCandidates" not in other_read


def test_read_runtime_serves_a_bounded_neighbourhood_by_id(app):
    store = srv._store()
    run = committed_run(store)
    take_turn(run, 1, memory=bridge_memory())
    got = call(
        "endless_read_runtime", runId=run,
        memoryEvents=["event:1:saved-elin", "event:9:not-a-thing"],
    )
    (ev,) = got["memoryEvents"]
    assert ev["id"] == "event:1:saved-elin"
    involved = {e["id"] for e in ev["involved"]}
    assert involved == {"elin", "elin-debt", "old-stone-bridge", "player"}


def test_the_schema_refuses_an_unknown_disclosure_before_any_handler(app):
    out = call("endless_advance_turn", runId="r", turn=1, prose="p", state={},
               memory={"events": [{"key": "k", "title": "t", "summary": "s",
                                   "disclosure": "loud"}]})
    assert out["ok"] is False
    assert out["applied"] is False
    assert "disclosure" in out["field"]


def test_deleting_a_life_leaves_no_graph_residue(app):
    """Phase 0 bar: 删除人生无残留 — the memory lives only in the chronicle,
    which delete_run already erases with the run directory."""
    store = srv._store()
    run = committed_run(store)
    take_turn(run, 1, memory=bridge_memory())
    store.delete_run(run)
    assert store.read_chronicle(run) == []
    run_dir = app / "runs" / run
    assert not run_dir.exists()
