"""Phase 2 gates: keepsakes never touch facts, and one payload feeds all lenses.

Backend-verifiable parts of design §12.1 (delete residue), §12.3 (disclosure is
server-side), §12.4 (three views share one payload — pinned here as: the
endpoint is layout-agnostic and carries no per-view branches).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import memory_graph as mg  # noqa: E402
from keepsakes import KeepsakeError, KeepsakeStore  # noqa: E402


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


def life_chronicle():
    """A life with a major event, an echo pair, a hidden event, an open thread."""
    return [
        turn_entry(
            1,
            {
                "entities": [
                    {"id": "elin", "kind": "character", "name": "艾琳"},
                    {"id": "bridge", "kind": "place", "name": "老石桥"},
                    {"id": "debt", "kind": "thread", "name": "人情"},
                ],
                "events": [
                    {
                        "key": "saved",
                        "title": "救出艾琳",
                        "summary": "s",
                        "importance": "major",
                        "participants": ["player", "elin"],
                        "place": "bridge",
                        "threads": [{"id": "debt", "effect": "opened"}],
                        "disclosure": "known",
                    },
                    {
                        "key": "watcher",
                        "title": "有人在暗处看见了这一幕",
                        "summary": "s",
                        "importance": "major",
                        "participants": ["elin"],
                        "disclosure": "hidden",
                    },
                ],
                "relations": [
                    {
                        "from": "elin",
                        "type": "trust",
                        "to": "player",
                        "change": "increase",
                        "reasonEvent": "saved",
                    },
                ],
            },
            action="把她拉上岸",
            prose="洪水冲桥，你把艾琳拉上岸。",
        ),
        turn_entry(
            5,
            {
                "events": [
                    {
                        "key": "repaid",
                        "title": "艾琳还了人情",
                        "summary": "s",
                        "participants": ["player", "elin"],
                        "threads": [{"id": "debt", "effect": "resolved"}],
                        "echoes": ["event-1-saved"],
                        "disclosure": "known",
                    },
                ],
            },
            prose="多年后，她记得那一天。",
        ),
    ]


# ── star payload (§8.3, §12.3) ───────────────────────────────────────────


def test_hidden_events_never_enter_the_star_payload():
    payload = mg.star_payload(mg.build_index(life_chronicle()))
    ids = {n["id"] for n in payload["nodes"]}
    assert "event-1-saved" in ids and "event-1-repaid" not in ids
    assert "event-5-repaid" in ids
    assert not any("watcher" in i for i in ids), "hidden event leaked (§12.3)"
    blob = json.dumps(payload, ensure_ascii=False)
    assert "暗处" not in blob, "hidden content leaked through an edge or relation"


def test_the_payload_is_layout_agnostic_and_stable():
    """§12.4: three lenses, one payload — so the payload must not know about
    views at all, and two computations of it must be identical."""
    index = mg.build_index(life_chronicle())
    a = json.dumps(mg.star_payload(index), sort_keys=True, ensure_ascii=False)
    b = json.dumps(mg.star_payload(index), sort_keys=True, ensure_ascii=False)
    assert a == b
    assert "view" not in json.loads(a), "the graph payload must not carry a lens"


def test_echo_edges_and_thread_effects_ship():
    payload = mg.star_payload(mg.build_index(life_chronicle()))
    kinds = {(e["type"], e["from"], e["to"]) for e in payload["edges"]}
    assert ("echoes", "event-5-repaid", "event-1-saved") in kinds
    assert ("opened", "event-1-saved", "debt") in kinds
    assert ("resolved", "event-5-repaid", "debt") in kinds


def test_relations_carry_their_visible_evidence_only():
    payload = mg.star_payload(mg.build_index(life_chronicle()))
    (rel,) = payload["relations"]
    assert rel["from"] == "elin" and rel["to"] == "player"
    assert rel["sources"] == ["event-1-saved"], "§4.3: the reading opens into its causes"


def test_a_minor_unechoed_event_stays_out_of_the_sparse_view():
    chronicle = life_chronicle() + [
        turn_entry(
            6,
            {
                "events": [
                    {
                        "key": "meal",
                        "title": "一顿饭",
                        "summary": "s",
                        "importance": "minor",
                        "disclosure": "known",
                    }
                ],
            },
        )
    ]
    payload = mg.star_payload(mg.build_index(chronicle))
    assert "event-6-meal" not in {n["id"] for n in payload["nodes"]}


def test_a_keepsake_pulls_its_cited_event_into_the_view():
    chronicle = life_chronicle() + [
        turn_entry(
            6,
            {
                "events": [
                    {
                        "key": "meal",
                        "title": "一顿饭",
                        "summary": "s",
                        "importance": "minor",
                        "disclosure": "known",
                    }
                ],
            },
        )
    ]
    keepsake = {"cites": ["event-6-meal"], "entities": []}
    payload = mg.star_payload(mg.build_index(chronicle), [keepsake])
    assert "event-6-meal" in {n["id"] for n in payload["nodes"]}


# ── keepsake store (§8.2, §12.1) ─────────────────────────────────────────


@pytest.fixture()
def kp_store(tmp_path):
    return KeepsakeStore(tmp_path, "a" * 32)


def test_create_rename_thought_delete_roundtrip(kp_store):
    kp = kp_store.create(kind="event", title="那一天", cites=["event-1-saved"])
    assert kp_store.get(kp["id"])["title"] == "那一天"
    kp_store.update(kp["id"], {"title": "石桥下", "thought": "一切由此开始"})
    got = kp_store.get(kp["id"])
    assert got["title"] == "石桥下" and got["thought"] == "一切由此开始"
    assert kp_store.delete(kp["id"]) is True
    assert kp_store.entries() == []


def test_the_cited_path_is_immutable(kp_store):
    kp = kp_store.create(kind="event", title="t", cites=["event-1-saved"])
    kp_store.update(kp["id"], {"cites": ["event-9-other"], "title": "t2"})
    assert kp_store.get(kp["id"])["cites"] == ["event-1-saved"]


def test_an_excerpt_keeps_its_content_hash(kp_store):
    kp = kp_store.create(kind="excerpt", title="t", excerpt="那一夜的雨", turn=3)
    import hashlib

    assert kp["excerptSha256"] == hashlib.sha256("那一夜的雨".encode()).hexdigest()


def test_refusals_name_the_field(kp_store):
    with pytest.raises(KeepsakeError) as err:
        kp_store.create(kind="event", title="", cites=["e"])
    assert err.value.field == "title"
    with pytest.raises(KeepsakeError) as err:
        kp_store.create(kind="event", title="t", cites=[])
    assert err.value.field == "cites"
    with pytest.raises(KeepsakeError) as err:
        kp_store.create(kind="excerpt", title="t", excerpt="x", turn=0)
    assert err.value.field == "turn"


def test_a_corrupt_file_loses_the_meaning_layer_never_crashes(kp_store, tmp_path):
    kp_store.create(kind="event", title="t", cites=["event-1-saved"])
    (tmp_path / "runs" / ("a" * 32) / "keepsakes.json").write_text("{not json")
    assert kp_store.entries() == []


def test_keepsakes_live_inside_the_run_dir_so_deletion_leaves_no_residue(tmp_path):
    """§12.1 / Phase 0 bar: a life's keepsakes die with the run directory —
    the same rm-tree ``delete_run`` already performs."""
    store = KeepsakeStore(tmp_path, "b" * 32)
    store.create(kind="event", title="t", cites=["event-1-x"])
    run_dir = tmp_path / "runs" / ("b" * 32)
    assert (run_dir / "keepsakes.json").is_file()
    assert run_dir.resolve().is_relative_to(tmp_path.resolve())
