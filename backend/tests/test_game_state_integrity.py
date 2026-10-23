"""State ownership and fact preservation across commit and inheritance."""

import json
from types import SimpleNamespace

import pytest

import legacy
import mcp_server as srv
import memory_graph as mg
import story_cards as cards
from keepsakes import KeepsakeStore
from systems import apply_systems
from template import Condition, System


@pytest.fixture
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    header = {
        "id": "w",
        "title": "World",
        "version": "1.0",
        "language": "en",
        "clock": {"unit": "month", "label": "{year}"},
        "styles": [{"id": "s", "label": "S", "default": True}],
        "opening": [{"id": "name", "label": "Name", "kind": "text"}],
        "panels": [
            {
                "id": "hero",
                "always": True,
                "fields": [{"id": "xp", "label": "Experience", "primitive": "field"}],
            }
        ],
        "endings": [{"id": "died", "when": "state.alive == false"}],
        "systems": [{"id": "xp", "kind": "accrual", "into": "state.hero.xp"}],
        "milestones": [{"id": "trained", "label": "Trained", "when": "state.hero.xp >= 10"}],
    }
    (data / "worlds" / "w.md").write_text("---\n" + json.dumps(header) + "\n---\nA world.\n")
    monkeypatch.setattr(srv, "_DATA", data)
    return srv._store()


def commit(store, run, payload, *, patch=False, gains=None):
    args = {
        "runId": run,
        "turn": int(store.read_state(run).get("turn", 0)) + 1,
        "prose": "A day passes.",
        "choices": [{"id": "go", "label": "Go"}],
        "gains": gains or [],
    }
    if patch:
        args.update(statePatch=payload, basedOn=store.fingerprint(store.read_state(run)))
    else:
        args["state"] = payload
    result = json.loads(srv.call_tool("endless_advance_turn", args))
    assert result.get("committed") is True, result
    return store.read_state(run)


@pytest.mark.parametrize("patch", [False, True])
@pytest.mark.parametrize("value", [None, "invented"])
def test_app_metadata_cannot_be_replaced_or_removed(app, patch, value):
    fixed = {
        "worldId": "w",
        "language": "en",
        "style": "s",
        "opening": {"name": "River"},
        "role": "wanderer",
        "granted": {"gold": 2},
    }
    run = app.create_run({**fixed, "turn": 0}, {})
    payload = {k: value for k in fixed}
    payload["runId"] = value
    payload["status"] = {"mood": "calm"}
    after = commit(app, run, payload, patch=patch)
    assert {k: after[k] for k in fixed} == fixed
    assert after["runId"] == run
    assert after["status"] == {"mood": "calm"}


def test_run_identity_survives_an_omitted_full_declaration(app):
    run = app.create_run({"worldId": "w", "turn": 0}, {})
    assert commit(app, run, {"hero": {"xp": 0}})["runId"] == run


@pytest.mark.parametrize("patch", [False, True])
@pytest.mark.parametrize(
    "prior,gain,declared,expected", [(0, "0", 999, []), (9, "1", 0, ["trained"])]
)
def test_milestones_observe_computed_system_values(app, patch, prior, gain, declared, expected):
    run = app.create_run({"worldId": "w", "turn": 0, "hero": {"xp": prior}}, {})
    after = commit(
        app,
        run,
        {"hero": {"xp": declared}},
        patch=patch,
        gains=[{"field": "xp", "amount": gain}],
    )
    assert after["milestones"] == expected


def test_undeclared_milestones_cannot_be_invented_without_a_world(app):
    run = app.create_run({"turn": 0}, {})
    after = commit(app, run, {"milestones": ["invented"]})
    assert not after.get("milestones")


def test_a_false_unlock_overwrites_a_narrator_grant():
    rule = System(
        id="gate",
        kind="unlock",
        into="state.magic.awake",
        when=Condition.parse("state.hero.xp >= 10"),
    )
    state = {"hero": {"xp": 0}, "magic": {"awake": True}}
    apply_systems(SimpleNamespace(systems=[rule]), state, {}, [])
    assert state["magic"]["awake"] is False


def test_unlocks_observe_computed_values_even_before_the_accrual():
    rules = [
        System(
            id="gate",
            kind="unlock",
            into="state.magic.awake",
            when=Condition.parse("state.hero.xp >= 10"),
        ),
        System(id="xp", kind="accrual", into="state.hero.xp"),
    ]
    for declared, previous, gain, expected in [(999, 0, "0", False), (0, 9, "1", True)]:
        state = {"hero": {"xp": declared}}
        apply_systems(
            SimpleNamespace(systems=rules),
            state,
            {"hero": {"xp": previous}},
            [{"field": "xp", "amount": gain}],
        )
        assert state["magic"]["awake"] is expected


def test_a_tier_below_the_first_threshold_clears_a_narrator_rank():
    rule = System(
        id="xp",
        kind="accrual",
        into="state.hero.xp",
        tiers=[{"at": 10, "name": "trained"}],
        tier_into="state.hero.rank",
    )
    state = {"hero": {"xp": 0, "rank": "invented"}}
    apply_systems(SimpleNamespace(systems=[rule]), state, {"hero": {"xp": 0}}, [])
    assert state["hero"]["rank"] is None


def thread_index():
    return mg.build_index(
        [
            {
                "turn": 2,
                "memory": {
                    "entities": [{"id": "promise", "kind": "thread", "name": "Promise"}],
                    "events": [
                        {
                            "key": "vow",
                            "title": "A vow",
                            "summary": "A promise remains.",
                            "disclosure": "known",
                            "threads": [{"id": "promise", "effect": "opened"}],
                        }
                    ],
                },
            }
        ]
    )


def test_an_inherited_thread_keeps_its_open_state_at_turn_zero():
    record = legacy.build_bridge_record(
        thread_index(), source_run_id="a" * 32, selected=["promise"]
    )
    index = mg.build_index([record])
    assert index["threads"]["promise"]["opened"] == 0
    assert legacy.candidates(index)["threads"][0]["open"] is True
    later = {
        "turn": 1,
        "memory": {
            "events": [
                {
                    "key": "recall",
                    "title": "Remember",
                    "summary": "The vow remains.",
                    "disclosure": "known",
                    "threads": [{"id": "promise", "effect": "advanced"}],
                }
            ]
        },
    }
    assert mg.build_index([record, later])["threads"]["promise"]["opened"] == 0


def test_an_inherited_resolved_thread_stays_resolved():
    index = thread_index()
    index["threads"]["promise"]["resolved"] = 3
    record = legacy.build_bridge_record(index, source_run_id="a" * 32, selected=["promise"])
    inherited = mg.build_index([record])
    assert inherited["threads"]["promise"]["resolved"] == 0
    assert legacy.candidates(inherited)["threads"][0]["open"] is False


def test_card_reorder_cannot_duplicate_a_fact():
    card = cards.build_draft(thread_index(), {"cites": ["event-2-vow"], "title": "Vow"})
    with pytest.raises(cards.StoryCardError):
        cards.apply_edits(card, {"order": ["event-2-vow", "event-2-vow"]})


def test_repeated_citations_do_not_duplicate_card_events():
    card = cards.build_draft(
        thread_index(), {"cites": ["event-2-vow", "event-2-vow"], "title": "Vow"}
    )
    assert len(card["events"]) == 1


def test_nonobject_keepsake_rows_do_not_hide_valid_keepsakes(tmp_path):
    store = KeepsakeStore(tmp_path, "a" * 32)
    kept = store.create(kind="event", title="Vow", cites=["event-2-vow"])
    path = tmp_path / "runs" / ("a" * 32) / "keepsakes.json"
    path.write_text(json.dumps([None, "damaged", kept]))
    assert store.get(kept["id"]) == kept
    assert store.entries() == [kept]
