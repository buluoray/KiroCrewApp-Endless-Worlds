"""Guards on the idle rotation and the patch a fresh conversation commits with.

Every model call in a turn re-sends the conversation so far, and the prompt cache
that makes that cheap lives minutes, while players pause far longer (measured: 55%
of gaps over 5 min). So after a pause the next turn starts a fresh conversation
and re-anchors with one full read. Three things must hold for that to be a saving
and not a regression: the boundary rotates once, every "already sent" marker is
forgotten with the old conversation, and the fresh narrator commits a patch on the
full read's fingerprint instead of re-declaring the whole state.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
import narrator  # noqa: E402
from content import Content  # noqa: E402
from perf import TurnPerf  # noqa: E402
from turn import (  # noqa: E402
    IDLE_ROTATION_SECS,
    ROTATION_MAX_TURNS,
    _should_rotate,
    advance_turn,
)

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"},
                        {"id": "mood", "label": "Mood", "primitive": "field"}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
The hero does not always win.
"""


@pytest.fixture()
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    monkeypatch.setattr(narrator, "app_install_generation", lambda: "g")
    return data


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


def _life(turns=2):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    for n in range(1, turns + 1):
        out = call(
            "endless_advance_turn",
            runId=run,
            turn=n,
            prose=f"month {n}",
            choices=[{"id": "go", "label": "go"}],
            state={"status": {"age": n, "mood": "calm"}},
        )
        assert out.get("committed") is True, out
    store.mark_narrator_generation(run, "g")
    return store, run


def _age_last_commit(store, run, secs):
    """Date the last commit ``secs`` in the past, on the RECORD, not the clock."""
    key = f"provenance-{run}"
    raw = store._kv.get(key)
    raw["at"] = float(raw["at"]) - secs
    store._kv.set(key, raw)


class _Slot:
    def __init__(self, key):
        self.key = key
        self._app = narrator.APP_NAME
        self.memory_mode = narrator.MEMORY_MODE
        self.project = ""

    def enqueue_or_run_prompt(self, prompt, runner, state):
        state.prompts.append(prompt)
        return True


class _Sessions:
    def __init__(self):
        self.discarded: list[tuple[str, bool]] = []

    async def discard_conversation(self, key, *, replay=True):
        self.discarded.append((key, replay))


class _State:
    def __init__(self):
        self.slots = {}
        self._slots = self.slots
        self.prompts: list[str] = []
        self.sessions = _Sessions()

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, **_kw):
        self.slots.setdefault(name, _Slot(name))
        return self.slots[name]


def _dispatch(st, slot, prompt, **_kw):
    return slot.enqueue_or_run_prompt(prompt, None, st)


def _ask(store, run, state, action="wait"):
    return asyncio.run(
        advance_turn(
            state_obj=state,
            store=store,
            run_id=run,
            rulebook="THE LAW",
            shape="THE SHAPE",
            dispatch=_dispatch,
            inline_wait_secs=0.01,
            action=action,
        )
    )


def _rotations(store, run):
    rows = TurnPerf(store.data_dir, run).rows()
    return [r.get("reason") for r in rows if r.get("step") == "rotation"]


# -- the rule ------------------------------------------------------------------


def test_a_pause_past_the_threshold_rotates_and_a_short_one_does_not(app):
    store, run = _life()
    committed = store.committed_at(run, 2)
    assert committed is not None
    soon = committed + IDLE_ROTATION_SECS - 1
    late = committed + IDLE_ROTATION_SECS + 1
    assert _should_rotate(store, run, 2, chapter_crossed=False, now=soon) == ""
    assert _should_rotate(store, run, 2, chapter_crossed=False, now=late) == "idle"


def test_an_idle_boundary_rotates_exactly_once(app):
    store, run = _life()
    late = store.committed_at(run, 2) + IDLE_ROTATION_SECS + 60
    assert _should_rotate(store, run, 2, chapter_crossed=False, now=late) == "idle"
    store.mark_rotation(run, turn=2)
    # The same month asked again (retry, double tap): consumed.
    assert _should_rotate(store, run, 2, chapter_crossed=False, now=late + 600) == ""


def test_idle_never_discards_a_narrator_still_writing_the_month(app):
    store, run = _life()
    store.mark_pending(run, turn=3, slot=narrator.narrator_slot_key(run))
    late = store.committed_at(run, 2) + IDLE_ROTATION_SECS + 60
    assert _should_rotate(store, run, 2, chapter_crossed=False, now=late) == ""


def test_an_unknown_commit_time_never_rotates_on_idleness(app):
    store, run = _life()
    store._kv.delete(f"provenance-{run}")
    assert store.committed_at(run, 2) is None
    assert _should_rotate(store, run, 2, chapter_crossed=False, now=10**12) == ""


def test_a_commit_time_for_another_month_is_not_trusted(app):
    store, run = _life()
    assert store.committed_at(run, 1) is None


def test_the_budget_caps_a_conversation_at_eight_turns(app):
    store, run = _life()
    assert ROTATION_MAX_TURNS == 8
    store.mark_rotation(run, turn=1)
    soon = store.committed_at(run, 2)
    assert _should_rotate(store, run, 1 + ROTATION_MAX_TURNS - 1, False, now=soon) == ""
    assert _should_rotate(store, run, 1 + ROTATION_MAX_TURNS, False, now=soon) == "budget"


# -- the turn after a pause, end to end ----------------------------------------


def test_the_turn_after_a_pause_starts_fresh_and_forgets_what_was_sent(app):
    store, run = _life()
    slot_key = narrator.narrator_slot_key(run)
    state = _State()
    state.slots[slot_key] = _Slot(slot_key)
    # The old conversation holds the rulebook and some recall bodies.
    store.mark_briefed(run, slot=slot_key, turn=2)
    store.mark_recall_sent(run, ["world:abc", "person:mira:123", "event-1-x"])
    assert store.recall_sent(run)
    _age_last_commit(store, run, IDLE_ROTATION_SECS + 60)

    _ask(store, run, state)

    assert _rotations(store, run) == ["idle"]
    # Discarded once, through the seam, with the transcript replay suppressed.
    assert [replay for _, replay in state.sessions.discarded] == [False]
    assert store.rotation_turn(run) == 2
    # Every "already sent" marker belongs to the discarded conversation.
    assert store.recall_sent(run) == set()
    # The fresh conversation is re-briefed and told to patch.
    prompt = state.prompts[-1]
    assert "THE LAW" in prompt
    assert Content("en")("turn.patch") in prompt

    # A double tap on the same month neither rotates nor discards again.
    _ask(store, run, state)
    assert _rotations(store, run) == ["idle"]
    assert len(state.sessions.discarded) == 1


def test_a_short_pause_keeps_the_conversation(app):
    store, run = _life()
    slot_key = narrator.narrator_slot_key(run)
    state = _State()
    state.slots[slot_key] = _Slot(slot_key)
    store.mark_briefed(run, slot=slot_key, turn=2)
    _age_last_commit(store, run, IDLE_ROTATION_SECS - 60)

    _ask(store, run, state)

    assert _rotations(store, run) == []
    assert state.sessions.discarded == []
    assert Content("en")("turn.patch") not in state.prompts[-1]


def test_the_fresh_narrator_that_follows_the_read_commits_a_patch(app):
    store, run = _life()
    slot_key = narrator.narrator_slot_key(run)
    state = _State()
    state.slots[slot_key] = _Slot(slot_key)
    store.mark_briefed(run, slot=slot_key, turn=2)
    _age_last_commit(store, run, IDLE_ROTATION_SECS + 60)
    _ask(store, run, state)
    assert _rotations(store, run) == ["idle"]

    # A fresh conversation holds no fingerprint: it reads with no `since`.
    read = call("endless_read_runtime", runId=run)
    assert "state" in read, "a fresh conversation must get the whole state"
    assert read["fingerprint"] in read["commitWith"]
    assert "statePatch" in read["commitWith"]

    out = call(
        "endless_advance_turn",
        runId=run,
        turn=3,
        prose="month 3",
        choices=[{"id": "go", "label": "go"}],
        statePatch={"status": {"mood": "tense"}},
        basedOn=read["fingerprint"],
    )
    assert out.get("committed") is True, out
    committed = store.read_state(run)
    assert committed["status"] == {"age": 2, "mood": "tense"}


def test_a_delta_read_carries_no_commit_note(app):
    store, run = _life()
    full = call("endless_read_runtime", runId=run)
    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert "commitWith" not in delta


def test_an_opening_read_carries_no_commit_note(app):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    assert "commitWith" not in call("endless_read_runtime", runId=run)
