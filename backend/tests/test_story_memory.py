"""A world that remembers: the player's fateful picks, the people around them,
and the voice their life is told in.

Every test here measures code behaviour — what is recorded, recalled, carried or
refused — never the wording of a prompt line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
import memory_graph as mg  # noqa: E402
from opening import DEFAULT_VOICE, VOICES, OpeningError, build_initial_state  # noqa: E402
from world import read_world  # noqa: E402

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
The brave do not always win.
"""

VOW = {"id": "vow", "label": "I swear the oath", "fateful": True}
REST = {"id": "rest", "label": "I rest"}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    return data


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


def new_run(store, **state):
    base = {"turn": 0, "worldId": "w", "language": "en", "alive": True}
    return store.create_run({**base, **state}, {"runId": "r"})


def play(store, run, turn, action="", choices=None, memory=None):
    """One turn the way the loop runs it: the ask is recorded, the narrator
    looks, then commits."""
    store.mark_pending(run, turn=turn, slot="s", action=action)
    store.note_runtime_read(run, turn=turn)
    args = {
        "runId": run,
        "turn": turn,
        "prose": f"turn {turn}",
        "choices": choices if choices is not None else [dict(REST)],
        "state": {"alive": True},
    }
    if memory is not None:
        args["memory"] = memory
    out = call("endless_advance_turn", **args)
    store.clear_pending(run)
    return out


# ── 1. choices the world remembers ───────────────────────────────────────


def test_a_fateful_pick_is_recorded_and_becomes_a_decision_event(app):
    store = srv._store()
    run = new_run(store)
    play(store, run, 1, choices=[dict(VOW), dict(REST)])
    out = play(store, run, 2, action="I swear the oath")
    assert out["committed"] is True

    line = store.read_chronicle(run)[-1]
    assert line["picked"] == {"id": "vow", "label": "I swear the oath", "fateful": True}

    ev = mg.build_index(store.read_chronicle(run))["events"]["event-2-decision"]
    assert ev["title"] == "I swear the oath"
    assert ev["importance"] == "major" and ev["disclosure"] == "known"
    assert ev["origin"] == mg.DECISION_ORIGIN
    assert ev["participants"] == []


def test_free_text_records_no_pick_and_a_plain_pick_no_event(app):
    store = srv._store()
    run = new_run(store)
    play(store, run, 1, choices=[dict(VOW), dict(REST)])
    play(store, run, 2, action="I climb the tower instead")
    assert "picked" not in store.read_chronicle(run)[-1]

    play(store, run, 3, action="I rest")
    assert store.read_chronicle(run)[-1]["picked"]["fateful"] is False
    events = mg.build_index(store.read_chronicle(run))["events"]
    assert not any(e.get("origin") == mg.DECISION_ORIGIN for e in events.values())


def test_only_the_page_just_before_counts(app):
    """An older page's buttons were never on screen for this action."""
    store = srv._store()
    run = new_run(store)
    play(store, run, 1, choices=[dict(VOW), dict(REST)])
    play(store, run, 2, action="I rest", choices=[{"id": "go", "label": "I go on"}])
    play(store, run, 3, action="I swear the oath")
    assert "picked" not in store.read_chronicle(run)[-1]


def test_a_dormant_decision_comes_back_through_recall(app):
    store = srv._store()
    run = new_run(store)
    play(store, run, 1, choices=[dict(VOW), dict(REST)])
    play(store, run, 2, action="I swear the oath")
    for t in range(3, 3 + mg.DORMANT_AFTER_TURNS):
        play(store, run, t)
    got = call("endless_read_runtime", runId=run)
    rows = {c["id"]: c for c in got.get("memoryCandidates") or []}
    assert "event-2-decision" in rows
    assert rows["event-2-decision"]["origin"] == mg.DECISION_ORIGIN

    # The existing recall-sent path holds it on a delta read.
    delta = call("endless_read_runtime", runId=run, since=got["fingerprint"])
    held = {c["id"]: c for c in delta.get("memoryCandidates") or []}
    assert held["event-2-decision"].get("held") is True
    assert "summary" not in held["event-2-decision"]


def test_a_narrator_key_named_decision_steps_aside(app):
    store = srv._store()
    run = new_run(store)
    play(store, run, 1, choices=[dict(VOW), dict(REST)])
    memory = {"events": [{"key": "decision", "title": "The oath is heard", "summary": "s"}]}
    play(store, run, 2, action="I swear the oath", memory=memory)
    events = mg.build_index(store.read_chronicle(run))["events"]
    assert events["event-2-decision"]["origin"] == mg.DECISION_ORIGIN
    assert events["event-2-decision-2"]["title"] == "The oath is heard"


def test_a_retried_pick_mints_one_event_and_rebuilds_byte_stable(app):
    store = srv._store()
    run = new_run(store)
    play(store, run, 1, choices=[dict(VOW), dict(REST)])
    play(store, run, 2, action="I swear the oath")
    again = play(store, run, 2, action="I swear the oath")
    assert again["committed"] is False
    chronicle = store.read_chronicle(run)
    first = mg.build_index(chronicle)
    assert sum(1 for e in first["events"].values() if e.get("origin")) == 1
    assert json.dumps(first, sort_keys=True) == json.dumps(
        mg.build_index(chronicle), sort_keys=True
    )


def test_decision_events_do_not_move_the_life_centre():
    """A life written under the protagonist's own id keeps that centre however
    many decisions the player makes."""
    chronicle = [
        {
            "turn": 1,
            "memory": {
                "entities": [{"id": "chen-yu", "kind": "character", "name": "Chen Yu"}],
                "events": [{"key": "a", "title": "a", "summary": "a", "participants": ["chen-yu"]}],
            },
        }
    ]
    for t in range(2, 6):
        chronicle.append({"turn": t, "picked": {"id": "x", "label": f"pick {t}", "fateful": True}})
    index = mg.build_index(chronicle)
    assert len(index["events"]) == 5
    assert mg.life_centre(index)["id"] == "chen-yu"


# ── 2. people who remember you ───────────────────────────────────────────


def _people_chronicle():
    ents = [
        {"id": "elin", "kind": "character", "name": "Elin"},
        {"id": "bo", "kind": "character", "name": "Bo"},
        {"id": "old-wu", "kind": "character", "name": "Old Wu"},
        {"id": "stranger", "kind": "character", "name": "Stranger"},
    ]
    return [
        {
            "turn": 1,
            "memory": {
                "entities": ents,
                "events": [
                    {
                        "key": "met-wu",
                        "title": "t",
                        "summary": "s",
                        "participants": ["player", "old-wu"],
                    },
                    {"key": "met-x", "title": "t", "summary": "s", "participants": ["stranger"]},
                ],
                "relations": [
                    {
                        "from": "old-wu",
                        "type": "trust",
                        "to": "player",
                        "change": "set",
                        "value": "warm",
                    }
                ],
            },
        },
        {
            "turn": 12,
            "memory": {
                "events": [
                    {
                        "key": "lied",
                        "title": "t",
                        "summary": "s",
                        "participants": ["player", "elin"],
                    }
                ],
                "relations": [
                    {
                        "from": "elin",
                        "type": "trust",
                        "to": "player",
                        "change": "decrease",
                        "reasonEvent": "lied",
                    }
                ],
            },
        },
    ]


def test_a_named_person_carries_their_standing_and_when_they_were_last_seen():
    index = mg.build_index(_people_chronicle())
    cards = mg.people_cards(index, turn=13, action="I find Bo and tell him")
    by_id = {c["id"]: c for c in cards}
    # Named in the action: first, even though never in an event.
    assert cards[0]["id"] == "bo" and cards[0]["stance"] == []
    # In last turn's events: present, with the standing toward the player.
    assert by_id["elin"]["lastSeen"] == 12 and by_id["elin"]["lastEvent"] == "event-12-lied"
    assert by_id["elin"]["stance"] == [
        {"from": "elin", "type": "trust", "to": "player", "value": "", "level": -1}
    ]


def test_one_offstage_person_is_someone_still_tied_to_the_protagonist():
    index = mg.build_index(_people_chronicle())
    cards = mg.people_cards(index, turn=13)
    off = [c for c in cards if c.get("offstage")]
    # old-wu: unseen 12 turns, still trusts the player. stranger: no tie.
    assert [c["id"] for c in off] == ["old-wu"]
    assert "stranger" not in {c["id"] for c in cards}


def test_the_cards_are_capped_with_the_offstage_slot_kept():
    chronicle = _people_chronicle()
    many = [{"id": f"p{i}", "kind": "character", "name": f"P{i}"} for i in range(8)]
    chronicle.append(
        {
            "turn": 13,
            "memory": {
                "entities": many,
                "events": [
                    {
                        "key": "crowd",
                        "title": "t",
                        "summary": "s",
                        "participants": [m["id"] for m in many],
                    }
                ],
            },
        }
    )
    index = mg.build_index(chronicle)
    cards = mg.people_cards(index, turn=14)
    assert len(cards) == mg.MAX_PEOPLE
    assert cards[-1].get("offstage") is True


def test_an_unchanged_card_is_held_and_a_changed_one_is_sent_again(app):
    store = srv._store()
    run = new_run(store)
    memory = {
        "entities": [{"id": "elin", "kind": "character", "name": "Elin"}],
        "events": [
            {"key": "met", "title": "t", "summary": "s", "participants": ["player", "elin"]}
        ],
        "relations": [
            {"from": "elin", "type": "trust", "to": "player", "change": "set", "value": "wary"}
        ],
    }
    play(store, run, 1, memory=memory)
    full = call("endless_read_runtime", runId=run)
    (card,) = [c for c in full["people"] if c["id"] == "elin"]
    assert card["stance"][0]["value"] == "wary" and "held" not in card

    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    (held,) = [c for c in delta["people"] if c["id"] == "elin"]
    assert held == {"id": "elin", "name": "Elin", "held": True}

    moved = {
        "events": [
            {"key": "saved", "title": "t", "summary": "s", "participants": ["player", "elin"]}
        ],
        "relations": [
            {"from": "elin", "type": "trust", "to": "player", "change": "set", "value": "warm"}
        ],
    }
    play(store, run, 2, memory=moved)
    after = call("endless_read_runtime", runId=run, since=delta["fingerprint"])
    (fresh,) = [c for c in after["people"] if c["id"] == "elin"]
    assert "held" not in fresh and fresh["stance"][0]["value"] == "warm"


# ── 4. one voice per life, the player's pick ─────────────────────────────


def _template():
    return read_world(WORLD).template


def test_the_voice_is_the_players_pick_with_a_default():
    assert build_initial_state(_template(), {})["voice"] == DEFAULT_VOICE
    for voice in VOICES:
        assert build_initial_state(_template(), {}, voice=voice)["voice"] == voice
    with pytest.raises(OpeningError) as err:
        build_initial_state(_template(), {}, voice="omniscient")
    assert err.value.field == "voice"


def test_the_voice_is_carried_forward_and_the_narrator_cannot_change_it(app):
    store = srv._store()
    run = new_run(store, voice="third")
    store.note_runtime_read(run, turn=1)
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[dict(REST)],
        state={"alive": True, "voice": "first"},
    )
    assert out["committed"] is True
    assert store.read_state(run)["voice"] == "third"
    play(store, run, 2)
    assert store.read_state(run)["voice"] == "third"


def test_every_read_carries_the_voice_and_its_own_rule(app):
    store = srv._store()
    rules = {}
    for voice in VOICES:
        run = new_run(store, voice=voice)
        full = call("endless_read_runtime", runId=run)
        delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
        assert full["voice"] == delta["voice"] == voice
        assert full["voiceRule"] and full["voiceRule"] != f"voice.{voice}"
        rules[voice] = full["voiceRule"]
    assert len(set(rules.values())) == len(VOICES)


def test_a_life_born_before_voices_reads_a_stable_default(app):
    store = srv._store()
    run = new_run(store)
    assert "voice" not in store.read_state(run)
    reads = [call("endless_read_runtime", runId=run)["voice"] for _ in range(2)]
    assert reads == [DEFAULT_VOICE, DEFAULT_VOICE]
