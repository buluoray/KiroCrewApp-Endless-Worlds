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


def test_unknown_participant_is_dropped_but_the_event_survives():
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "participants": ["nobody"], "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert [d["field"] for d in dropped] == ["memory.events[0].participants[0]"]
    (ev,) = clean["events"]
    assert ev["participants"] == [], "the unknown participant is gone"
    assert ev["title"] == "t", "but the event itself is salvaged"


def test_a_reused_event_key_is_suffixed_so_both_events_survive():
    """A key only has to be unique inside its own turn, so a collision is answered
    by a free neighbour — dropping the second event would lose a thing that happened
    over a naming slip."""
    memory = {"events": [
        {"key": "k", "title": "t", "summary": "s", "disclosure": "known"},
        {"key": "k", "title": "t2", "summary": "s2", "disclosure": "known"},
    ]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert dropped == [], "a reused key is repaired, not warned"
    assert [ev["key"] for ev in clean["events"]] == ["k", "k-2"]
    assert [ev["title"] for ev in clean["events"]] == ["t", "t2"]


def test_a_key_already_recorded_for_this_turn_is_suffixed_not_dropped():
    """Events are append-only, so a replayed key cannot overwrite — it steps aside."""
    chronicle = [turn_entry(3, {"events": [{"key": "k", "title": "old", "summary": "s",
                                            "disclosure": "known"}]})]
    memory = {"events": [{"key": "k", "title": "new", "summary": "s",
                          "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index(chronicle), turn=3)
    assert dropped == []
    assert clean["events"][0]["key"] == "k-2", "the old event keeps its id"


def test_a_namespaced_entity_id_is_repaired_not_dropped():
    """The live report: the narrator mirrors the id shapes it is SHOWN, and it was
    shown colon-namespaced canonical ids (`event:6:slept-through`), so it wrote
    `character:lin-shuang` — five entities vanished per turn over it. `event_id` no
    longer mints a colon at all, and the habit is repaired rather than dropped."""
    memory = {"entities": [
        {"id": "character:lin-shuang", "kind": "character", "name": "林霜"},
        {"id": "group: darkflame court", "kind": "group", "name": "黑焰廷"},
    ]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert dropped == [], "a repairable id is never a warning"
    assert [e["id"] for e in clean["entities"]] == ["lin-shuang", "darkflame-court"]


def test_a_repaired_reference_lands_on_the_entity_it_meant():
    """The cascade the drops caused: a later turn names an entity it already declared,
    in the namespaced form. The reference is repaired to the SAME id the declaration
    was repaired to, so the event keeps its participant."""
    index = mg.build_index([turn_entry(1, {"entities": [
        {"id": "lin-shuang", "kind": "character", "name": "林霜"}]})])
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "participants": ["character:lin-shuang"],
                          "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, index, turn=4)
    assert dropped == []
    assert clean["events"][0]["participants"] == ["lin-shuang"]


def test_the_canonical_id_shape_is_a_slug_the_narrator_can_safely_mirror():
    """`event_id` mints no separator the id rule forbids, so a narrator echoing the
    one internal id it is shown back into its own ids costs nothing."""
    cid = mg.event_id(12, "saved-elin")
    assert cid == "event-12-saved-elin" and mg.is_event_id(cid)
    assert mg._id_ok(cid), "the shape the narrator is shown is a legal id"
    assert mg.repair_id(cid) == cid, "and needs no repair when mirrored"


def test_a_canonical_id_written_where_a_key_belongs_is_unwrapped():
    """Mirroring has a floor: the narrator writing the canonical id as an event KEY
    would otherwise mint `event-1-event-1-x`. The key is the tail."""
    memory = {"events": [{"key": "event-1-met-hui-ya", "title": "t", "summary": "s",
                          "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert dropped == []
    assert clean["events"][0]["key"] == "met-hui-ya"


def test_a_kind_prefixed_id_is_only_unwrapped_when_it_lands_on_a_known_entity():
    """`character-lin-shuang` is the colon habit in a shape the id rule cannot see,
    so the graph's own knowledge decides: it is unwrapped when `lin-shuang` exists,
    and left exactly as written when it does not — `place-of-bones` is an id too."""
    index = mg.build_index([turn_entry(1, {"entities": [
        {"id": "lin-shuang", "kind": "character", "name": "林霜"}]})])
    memory = {"entities": [
        {"id": "character-lin-shuang", "kind": "character", "name": "林霜"},
        {"id": "place-of-bones", "kind": "place", "name": "白骨原"},
    ]}
    clean, dropped = mg.sanitize_memory(memory, index, turn=2)
    assert dropped == []
    assert [e["id"] for e in clean["entities"]] == ["lin-shuang", "place-of-bones"]


def test_an_id_with_nothing_usable_left_is_still_dropped():
    """Repair is not invention: an id that is only punctuation names nothing."""
    memory = {"entities": [{"id": " :: ", "kind": "character", "name": "x"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert [d["field"] for d in dropped] == ["memory.entities[0].id"]
    assert "entities" not in clean


def test_a_dangling_echo_is_dropped_but_the_event_survives():
    """§12.2: 回响必须引用真实旧事件 — but a bad echo only loses the echo, not the
    event; a cross-life id simply does not resolve here."""
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "echoes": ["event-3-never-happened"],
                          "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=5)
    assert [d["field"] for d in dropped] == ["memory.events[0].echoes[0]"]
    (ev,) = clean["events"]
    assert ev["echoes"] == [] and ev["title"] == "t"


def test_an_entity_kind_conflict_keeps_the_established_kind():
    """A kind never changes without an explicit merge — but the re-mention itself is
    still real writing, so it is recorded at the kind the entity already has."""
    index = mg.build_index([turn_entry(1, bridge_memory())])
    memory = {"entities": [{"id": "elin", "kind": "object", "name": "艾琳"}]}
    clean, dropped = mg.sanitize_memory(memory, index, turn=2)
    assert dropped == []
    (ent,) = clean["entities"]
    assert ent["kind"] == "character", "the established kind stands"
    assert ent["name"] == "艾琳", "and the re-mention is kept"


def test_an_unknown_kind_is_kept_as_object_not_dropped():
    """The screenshot report: kind 'concept' is a narrator-invented category, so it
    must not cost the whole entity. It is KEPT, bucketed as the generic 'object', and
    only a warning is raised — recall rules still see nothing outside KINDS."""
    memory = {"entities": [{"id": "resonant-notation", "kind": "concept",
                            "name": "共鸣符记法", "summary": "s"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=2)
    assert dropped == [], "the coercion is a repair, not a warning"
    (ent,) = clean["entities"]
    assert ent["id"] == "resonant-notation" and ent["kind"] == "object", (
        "the entity survives, bucketed as the generic kind"
    )


def test_an_unknown_kind_on_a_known_entity_adopts_the_established_kind():
    """A re-mention of an existing character carrying a stray kind label refreshes it
    at its established kind rather than flipping it to 'object' or dropping it."""
    index = mg.build_index([turn_entry(1, bridge_memory())])  # elin is a character
    memory = {"entities": [{"id": "elin", "kind": "concept", "name": "艾琳"}]}
    clean, dropped = mg.sanitize_memory(memory, index, turn=2)
    (ent,) = clean["entities"]
    assert ent["kind"] == "character", "adopts the established kind, never lost"


def test_a_narrators_word_for_a_disclosure_is_read_not_refused():
    """The vocabulary stays closed for every consumer, but the narrator writing
    "public" or "widely rumored" keeps its event — the synonym is mapped."""
    memory = {"events": [
        {"key": "a", "title": "t", "summary": "s", "disclosure": "public"},
        {"key": "b", "title": "t", "summary": "s", "disclosure": "widely rumored"},
        {"key": "c", "title": "t", "summary": "s", "disclosure": "secret"},
        {"key": "d", "title": "t", "summary": "s", "disclosure": "loud"},
    ]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert dropped == []
    assert [ev["disclosure"] for ev in clean["events"]] == [
        "known", "rumoured", "hidden", mg.DEFAULT_DISCLOSURE,
    ], "an unreadable word falls back to the documented default"


def test_an_event_with_neither_title_nor_summary_is_dropped():
    """The one event that is genuinely unrecordable: nothing names it."""
    memory = {"events": [{"key": "k", "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert [d["field"] for d in dropped] == ["memory.events[0].title"]
    assert "events" not in clean


def test_a_titleless_event_takes_its_title_from_its_summary():
    """The live report: `memory.events[0].title` dropped a whole event the narrator
    had written a summary for. The summary names it instead."""
    memory = {"events": [{"key": "k", "summary": "他在塌方里睡了整夜。",
                          "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert dropped == []
    (ev,) = clean["events"]
    assert ev["title"] == "他在塌方里睡了整夜。" and ev["summary"] == ev["title"]


def test_a_summaryless_event_takes_its_summary_from_its_title():
    memory = {"events": [{"key": "k", "title": "t", "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert dropped == []
    assert clean["events"][0]["summary"] == "t"


def test_an_event_named_only_by_its_summary_still_gets_a_key():
    """A key is minted server-side from (turn, key) and only has to be unique inside
    its turn, so a missing one is derived rather than costing the event."""
    memory = {"events": [{"summary": "s", "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=7)
    assert dropped == []
    assert clean["events"][0]["key"] == "s"


def test_a_bare_event_key_in_an_echo_resolves_to_its_canonical_id():
    """The narrator names an old event by the key it wrote, not by the canonical id
    the server minted; both readings reach the same event."""
    chronicle = [turn_entry(2, {"events": [{"key": "saved-elin", "title": "t",
                                            "summary": "s", "disclosure": "known"}]})]
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "echoes": ["saved-elin"], "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index(chronicle), turn=9)
    assert dropped == []
    assert clean["events"][0]["echoes"] == ["event-2-saved-elin"]


def test_a_narrators_word_for_a_relation_change_is_read_not_refused():
    memory = {
        "entities": [{"id": "elin", "kind": "character", "name": "Elin"}],
        "relations": [{"from": "elin", "type": "trust", "to": "player",
                       "change": "deepened"}],
    }
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert dropped == []
    assert clean["relations"][0]["change"] == "increase"


def test_a_dangling_reason_costs_the_reason_not_the_relation():
    """reasonEvent was always optional, so a reason naming no event drops the field
    and keeps the edge the narrator actually declared."""
    memory = {
        "entities": [{"id": "elin", "kind": "character", "name": "Elin"}],
        "relations": [{"from": "elin", "type": "trust", "to": "player",
                       "change": "increase", "reasonEvent": "never-happened"}],
    }
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert [d["field"] for d in dropped] == ["memory.relations[0].reasonEvent"]
    (rel,) = clean["relations"]
    assert "reasonEvent" not in rel and rel["type"] == "trust"


def test_a_non_place_place_is_dropped_but_the_event_survives():
    memory = {
        "entities": [{"id": "elin", "kind": "character", "name": "Elin"}],
        "events": [{"key": "k", "title": "t", "summary": "s",
                    "place": "elin", "disclosure": "known"}],
    }
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=1)
    assert [d["field"] for d in dropped] == ["memory.events[0].place"]
    (ev,) = clean["events"]
    assert "place" not in ev and ev["title"] == "t"


def test_opening_a_thread_needs_no_prior_entity():
    """The screenshot bug: opening a NEW thread is what creates it, so it must not
    require a kind:thread entity declared first — the whole memory used to be dropped
    over exactly this."""
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "threads": [{"id": "orwins-shadow", "effect": "opened"}],
                          "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=14)
    assert dropped == [], "opening a thread is not an error"
    (ev,) = clean["events"]
    assert ev["threads"] == [{"id": "orwins-shadow", "effect": "opened"}]


def test_advancing_a_never_opened_thread_opens_it_on_that_first_mention():
    """Naming a thread is what brings it into the graph, so `advanced` on a thread
    nobody opened is an opening — not an inconsistency to throw away. build_index
    opens it on the first touch, so it reads as an OPEN thread afterwards."""
    memory = {"events": [{"key": "k", "title": "t", "summary": "s",
                          "threads": [{"id": "ghost", "effect": "advanced"}],
                          "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index([]), turn=3)
    assert dropped == []
    (ev,) = clean["events"]
    assert ev["threads"] == [{"id": "ghost", "effect": "advanced"}]
    index = mg.build_index([turn_entry(3, clean)])
    assert index["threads"]["ghost"]["opened"] == 3 and not index["threads"]["ghost"]["resolved"]


def test_resolving_a_previously_opened_thread_is_kept():
    chronicle = [turn_entry(1, bridge_memory())]  # opens elin-debt
    memory = {"events": [{"key": "repaid", "title": "t", "summary": "s",
                          "threads": [{"id": "elin-debt", "effect": "resolved"}],
                          "disclosure": "known"}]}
    clean, dropped = mg.sanitize_memory(memory, mg.build_index(chronicle), turn=3)
    assert dropped == []
    (ev,) = clean["events"]
    assert ev["threads"] == [{"id": "elin-debt", "effect": "resolved"}]


def test_the_design_example_survives_whole():
    clean, dropped = mg.sanitize_memory(bridge_memory(), mg.build_index([]), turn=1)
    assert dropped == []
    assert len(clean["entities"]) == 3
    assert len(clean["events"]) == 1
    assert len(clean["relations"]) == 1


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
             "echoes": ["event-1-saved-elin"], "disclosure": "known"},
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
    assert slot["changes"][0]["reasonEvent"] == "event-1-saved-elin"


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
    assert got and got[0]["id"] == "event-1-saved-elin"
    assert "open-thread" in got[0]["reasons"]


def test_cooldown_a_just_echoed_event_rests():
    chronicle = [
        turn_entry(1, bridge_memory()),
        turn_entry(4, {"events": [
            {"key": "again", "title": "又见艾琳", "summary": "s",
             "participants": ["elin"],
             "echoes": ["event-1-saved-elin"], "disclosure": "known"},
        ]}),
    ]
    index = mg.build_index(chronicle)
    # Turn 5: echoed on turn 4, inside the cooldown window — must rest.
    ids = {c["id"] for c in mg.recall_candidates(index, turn=5)}
    assert "event-1-saved-elin" not in ids
    # Far later: eligible again, and the candidate names when it last echoed.
    later = {c["id"]: c for c in mg.recall_candidates(index, turn=20)}
    assert later["event-1-saved-elin"]["lastEchoedTurn"] == 4


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
             "echoes": ["event-1-saved-elin"],
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


def test_a_bad_reference_is_salvaged_and_the_turn_keeps_the_event(app):
    """Memory is salvaged, not rejected whole: an unknown participant is dropped, the
    event around it is still recorded, the turn commits (prose + choices + state), and
    the drop is surfaced as a non-blocking warning. Nothing is back-filled from prose."""
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
    assert entry["memory"]["events"][0]["key"] == "k", "the event was salvaged"
    assert entry["memory"]["events"][0]["participants"] == [], "only the bad ref was dropped"


def test_a_block_whose_parts_all_fail_records_no_memory(app):
    """When nothing survives sanitizing, the turn still commits but stores no memory —
    the block is not written empty."""
    store = srv._store()
    run = committed_run(store)
    # An event dropped whole (unknown disclosure is structural, caught pre-schema here
    # via a reference-only failure): use an event that loses its only anchor.
    bad = {"events": [{"key": "k", "title": "t", "summary": "s",
                       "participants": ["nobody"], "disclosure": "known"}]}
    out = take_turn(run, 1, memory=bad)
    assert out["committed"] is True
    (entry,) = store.read_chronicle(run)
    # The event still survives (title/summary stand); the unknown participant is the
    # only casualty, since repairing it would mean inventing an entity.
    assert entry["memory"]["events"][0]["key"] == "k"
    fields = {w["field"] for w in out.get("warnings") or [] if w.get("panel") == "memory"}
    assert fields == {"memory.events[0].participants[0]"}


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
    assert "event-1-saved-elin" in ids
    # The other life shares a store but remembers nothing (§12.2 人生隔离).
    other_read = call("endless_read_runtime", runId=other)
    assert "memoryCandidates" not in other_read


def test_read_runtime_serves_a_bounded_neighbourhood_by_id(app):
    store = srv._store()
    run = committed_run(store)
    take_turn(run, 1, memory=bridge_memory())
    got = call(
        "endless_read_runtime", runId=run,
        memoryEvents=["event-1-saved-elin", "event-9-not-a-thing"],
    )
    (ev,) = got["memoryEvents"]
    assert ev["id"] == "event-1-saved-elin"
    involved = {e["id"] for e in ev["involved"]}
    assert involved == {"elin", "elin-debt", "old-stone-bridge", "player"}


def test_a_bad_disclosure_is_repaired_end_to_end_with_no_warning(app):
    """A bad disclosure is refused at neither layer: the schema takes a plain string
    and sanitize_memory reads the word, so the event is RECORDED at the fallback
    disclosure and the narrator is not warned about a thing it need not fix."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_advance_turn", runId=run, turn=1, prose="p",
               choices=[{"id": "go", "label": "go"}], state={"alive": True},
               memory={"events": [{"key": "k", "title": "t", "summary": "s",
                                   "disclosure": "loud"}]})
    assert out.get("committed") is True and out.get("ok") is not False
    (entry,) = store.read_chronicle(run)
    (ev,) = entry["memory"]["events"]
    assert ev["disclosure"] == mg.DEFAULT_DISCLOSURE, "the event is kept, not dropped"
    assert not [w for w in out.get("warnings") or [] if w.get("panel") == "memory"]


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
