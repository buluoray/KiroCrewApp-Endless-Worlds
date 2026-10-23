"""Story measurements use declarations, including structured memory events."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import halo  # noqa: E402


def event(key: str) -> dict[str, str]:
    return {"key": key, "title": key, "summary": "A declared change", "disclosure": "known"}


def test_memory_only_events_do_not_report_a_quiet_life():
    history = [
        {"turn": turn, "events": [], "memory": {"events": [event(f"change-{turn}")]}}
        for turn in range(1, 7)
    ]
    reading = halo.event_density(history)
    assert reading == {"turns": 6, "events": 6, "perTurn": 1.0, "busy": False, "quiet": False}
    assert halo.compose_restraint(history) == ""


def test_memory_event_density_reaches_the_existing_busy_reading():
    history = [
        {"turn": turn, "memory": {"events": [event(f"change-{i}") for i in range(3)]}}
        for turn in range(1, 7)
    ]
    reading = halo.event_density(history)
    assert reading["events"] == 18
    assert reading["busy"] is True
    assert reading["quiet"] is False
    assert halo.compose_restraint(history)


@pytest.mark.parametrize("marked", [["one", "two"], 2])
def test_parallel_event_declarations_use_a_lower_bound_not_a_sum(marked):
    history = [{"turn": 1, "events": marked, "memory": {"events": [event("one")]}}]
    assert halo.event_density(history)["events"] == 2
    history[0]["memory"]["events"] += [event("two"), event("three")]
    assert halo.event_density(history)["events"] == 3


def test_memory_observations_and_legacy_events_share_the_same_window():
    history = [{"turn": 1, "memory": {"events": [event("old")]}}]
    history += [{"turn": turn, "events": []} for turn in range(2, 8)]
    assert halo.event_density(history)["quiet"] is True
    assert halo.event_density(history, window=7)["events"] == 1
    assert halo.event_density(history, window=0)["events"] == 0


@pytest.mark.parametrize("memory", [None, [], "encoded text", {"events": "encoded text"}])
def test_malformed_memory_does_not_break_density(memory):
    assert halo.event_density([{"events": ["legacy"], "memory": memory}])["events"] == 1


def test_only_described_memory_events_count_not_entities_or_empty_fragments():
    history = [
        {
            "memory": {
                "entities": [{"id": "someone", "summary": "An established person"}],
                "events": [None, "bad", {}, {"title": " "}, {"title": 3}, event("change")],
            }
        }
    ]
    assert halo.event_density(history)["events"] == 1


def test_a_summary_only_memory_event_remains_an_observation():
    assert (
        halo.event_density([{"memory": {"events": [{"summary": "A real change"}]}}])["events"] == 1
    )


def test_readings_leave_story_and_declarations_untouched():
    history = [
        {
            "turn": 1,
            "prose": "An ordinary quiet afternoon.",
            "events": [],
            "memory": {"events": [event("change")]},
        }
    ]
    original = copy.deepcopy(history)
    halo.event_density(history)
    halo.compose_restraint(history)
    assert history == original
    history[0]["prose"] *= 1000
    assert halo.event_density(history) == halo.event_density(original)


def test_full_runtime_read_delivers_memory_density_without_rewriting_history(tmp_path, monkeypatch):
    from kiro_crew.apps.app_storage import AppStorage

    import mcp_server as srv
    from store import RunStore

    data = tmp_path / "data"
    data.mkdir()
    store = RunStore(AppStorage("endless-worlds", data), data)
    run = store.create_run({"turn": 0}, {"title": "A life"})
    for turn in range(1, 7):
        store.commit_state(run, {"turn": turn})
        store.append_turn(
            run,
            {"turn": turn, "events": [], "memory": {"events": [event(f"change-{turn}")]}},
        )
    before = store.read_chronicle(run)
    monkeypatch.setattr(srv, "_store", lambda: store)
    monkeypatch.setattr(srv, "_DATA", data)

    reading = srv._read_runtime({"runId": run})
    assert reading["restraint"]["density"]["events"] == 6
    assert reading["restraint"]["density"]["quiet"] is False
    assert reading["restraint"]["note"] == ""
    assert store.read_chronicle(run) == before
    delta = srv._read_runtime({"runId": run, "since": reading["fingerprint"]})
    assert "restraint" not in delta
