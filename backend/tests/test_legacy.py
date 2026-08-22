"""Legacy bridge gates (design §9 + the §11 Phase 4 completion bar).

The bar, verbatim: 普通平行人生仍完全隔离；只有显式桥接的数据可跨 run 读取。
Pinned here as: two lives sharing a store share zero graph; a bridge copies
exactly the selection, stamped with provenance; the source life's bytes never
change; and the narrator has no path to forge an inheritance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import legacy as lg  # noqa: E402
import mcp_server as srv  # noqa: E402
import memory_graph as mg  # noqa: E402

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en", "lineage": true,
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


def turn_entry(turn, memory=None, action="", prose="p"):
    entry = {
        "turn": turn,
        "prose": prose,
        "action": action,
        "choices": [],
        "events": [],
        "gains": [],
    }
    if memory is not None:
        entry["memory"] = memory
    return entry


def ancestor_chronicle():
    """A finished life: a sword, a friend with trust, a rival left behind,
    and a secret the player never learned."""
    return [
        turn_entry(
            1,
            {
                "entities": [
                    {"id": "elin", "kind": "character", "name": "艾琳"},
                    {"id": "rival", "kind": "character", "name": "对头"},
                    {"id": "sword", "kind": "object", "name": "祖传的剑"},
                ],
                "events": [
                    {
                        "key": "meet",
                        "title": "相遇",
                        "summary": "s",
                        "participants": ["player", "elin", "rival"],
                        "disclosure": "known",
                    },
                    {
                        "key": "sword-found",
                        "title": "得剑",
                        "summary": "s",
                        "importance": "major",
                        "participants": ["player", "sword"],
                        "disclosure": "known",
                    },
                ],
                "relations": [
                    {
                        "from": "elin",
                        "type": "trust",
                        "to": "player",
                        "change": "increase",
                        "reasonEvent": "meet",
                    },
                    {
                        "from": "rival",
                        "type": "grudge",
                        "to": "player",
                        "change": "increase",
                        "reasonEvent": "meet",
                    },
                ],
            },
        ),
        turn_entry(
            2,
            {
                "entities": [
                    {"id": "watcher", "kind": "character", "name": "暗中的人"},
                ],
                "events": [
                    {
                        "key": "shadow",
                        "title": "无人知晓的注视",
                        "summary": "s",
                        "participants": ["watcher"],
                        "disclosure": "hidden",
                    },
                ],
            },
        ),
    ]


SOURCE_RUN = "a" * 32


def bridge(selected):
    index = mg.build_index(ancestor_chronicle())
    return lg.build_bridge_record(index, source_run_id=SOURCE_RUN, selected=selected, language="zh")


# ── candidates (§9 step 1) ───────────────────────────────────────────────


def test_candidates_group_the_visible_and_hide_the_unlived():
    got = lg.candidates(mg.build_index(ancestor_chronicle()))
    names = {row["id"] for rows in got.values() for row in rows}
    assert names == {"elin", "rival", "sword"}
    assert "watcher" not in names, "an entity lived only in hidden events leaked (§5.4)"
    (elin,) = [r for r in got["characters"] if r["id"] == "elin"]
    assert elin["relations"] == [{"type": "trust", "level": 1, "value": ""}]


# ── the copy is exactly the selection, with provenance (§9 steps 3–4) ────


def test_the_bridge_carries_the_selection_and_only_the_selection():
    record = bridge(["elin", "sword"])
    ids = {e["id"] for e in record["memory"]["entities"]}
    assert ids == {"elin", "sword"}
    blob = json.dumps(record, ensure_ascii=False)
    assert "rival" not in blob and "对头" not in blob


def test_every_copied_node_names_its_source():
    record = bridge(["elin", "sword"])
    for ent in record["memory"]["entities"]:
        prov = ent["inheritsFrom"]
        assert prov["runId"] == SOURCE_RUN
        assert prov["nodeId"] == ent["id"]
        assert prov["turn"] == 1


def test_an_unlived_or_unknown_selection_is_refused_whole():
    with pytest.raises(lg.LegacyError) as err:
        bridge(["elin", "watcher"])
    assert err.value.field == "selected[1]"
    with pytest.raises(lg.LegacyError):
        bridge([])


def test_relations_cross_only_when_everything_they_touch_did():
    record = bridge(["elin"])
    rels = record["memory"]["relations"]
    assert [r["from"] for r in rels] == ["elin"], "the rival's grudge crossed without the rival"
    assert rels[0]["reasonEvent"] == lg.BRIDGE_KEY


def test_the_bridge_record_rebuilds_into_a_working_graph():
    """The record is a normal canonical entry: index it and everything works —
    provenance survives, the bridge event anchors, the relation projects with
    the bridge as its evidence (§4.3 for inherited relations)."""
    record = bridge(["elin", "sword"])
    index = mg.build_index([record])
    assert index["entities"]["elin"]["inheritsFrom"]["runId"] == SOURCE_RUN
    bridge_id = f"event-0-{lg.BRIDGE_KEY}"
    assert bridge_id in index["events"]
    (slot,) = mg.project_relations(index).values()
    assert slot["changes"][0]["reasonEvent"] == bridge_id
    summary = lg.narrator_summary(index, "zh")
    assert {e["id"] for e in summary["entities"]} == {"elin", "sword"}
    assert SOURCE_RUN not in json.dumps(summary), (
        "the ancestor's run id leaked into the narrator summary (§9 step 5)"
    )


# ── isolation: the completion bar itself ─────────────────────────────────


def test_parallel_lives_share_nothing(app):
    store = srv._store()
    rich = store.create_run({"turn": 0, "worldId": "w", "language": "en"}, {"runId": ""})
    for entry in ancestor_chronicle():
        store.append_turn(rich, entry)
    plain = store.create_run({"turn": 0, "worldId": "w", "language": "en"}, {"runId": ""})
    index = mg.build_index(store.read_chronicle(plain))
    assert len(index["entities"]) == 1  # the implicit player, nothing else
    got = call("endless_read_runtime", runId=plain)
    assert "memoryCandidates" not in got and "legacy" not in got


def test_a_bridged_life_reads_only_what_was_carried(app):
    store = srv._store()
    heir = store.create_run({"turn": 0, "worldId": "w", "language": "en"}, {"runId": ""})
    store.append_turn(heir, bridge(["elin", "sword"]))
    got = call("endless_read_runtime", runId=heir)
    inherited = {e["id"] for e in got["legacy"]["entities"]}
    assert inherited == {"elin", "sword"}
    blob = json.dumps(got, ensure_ascii=False)
    assert SOURCE_RUN not in blob, "the ancestor's run id reached the narrator"
    assert "rival" not in blob and "watcher" not in blob


def test_the_source_life_is_never_modified_by_the_bridge_or_the_heir(app):
    store = srv._store()
    source = store.create_run(
        {"turn": 2, "worldId": "w", "language": "en", "ended": True}, {"runId": ""}
    )
    for entry in ancestor_chronicle():
        store.append_turn(source, entry)
    src_path = app / "runs" / source / "chronicle.jsonl"
    before = src_path.read_bytes()

    heir = store.create_run({"turn": 0, "worldId": "w", "language": "en"}, {"runId": ""})
    index = mg.build_index(store.read_chronicle(source))
    store.append_turn(
        heir, lg.build_bridge_record(index, source_run_id=source, selected=["elin"], language="zh")
    )
    # The heir lives on; the ancestor's record stays byte-identical (§9:
    # 上一代后续不会被下一代反向修改).
    call(
        "endless_advance_turn", runId=heir, turn=1, prose="新的一生开始了。", state={"alive": True}
    )
    assert src_path.read_bytes() == before


def test_deleting_the_heir_leaves_no_bridge_residue(app):
    store = srv._store()
    heir = store.create_run({"turn": 0, "worldId": "w", "language": "en"}, {"runId": ""})
    store.append_turn(heir, bridge(["elin"]))
    store.delete_run(heir)
    assert store.read_chronicle(heir) == []
    assert not (app / "runs" / heir).exists()


# ── the narrator cannot forge an inheritance ─────────────────────────────


def test_the_tool_schema_refuses_a_narrator_declared_inheritance(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w", "language": "en"}, {"runId": ""})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        state={},
        memory={
            "entities": [
                {
                    "id": "fake",
                    "kind": "object",
                    "name": "伪造的传家宝",
                    "inheritsFrom": {"runId": "b" * 32, "nodeId": "fake", "turn": 1},
                }
            ],
            "events": [],
            "relations": [],
        },
    )
    assert out["ok"] is False and out["applied"] is False
    assert "inheritsFrom" in out["field"]
    assert store.read_chronicle(run) == []


def test_the_players_page_history_never_shows_turn_zero(app):
    """The bridge is the app's record, not a page anyone lived: the chronicle
    route filters it, pinned here at the storage level the route reads."""
    store = srv._store()
    heir = store.create_run({"turn": 0, "worldId": "w", "language": "en"}, {"runId": ""})
    store.append_turn(heir, bridge(["elin"]))
    lived = [e for e in store.read_chronicle(heir) if int(e.get("turn") or 0) >= 1]
    assert lived == []
