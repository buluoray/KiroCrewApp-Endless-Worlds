"""Guards on where the world's law reaches the narrator: the read, never the message.

Measured on the live narrator sessions (dashboard_endless-run-*.jsonl, 28 lives):
a re-brief user message carried the rulebook and the state shape, median 8.6 KB
and up to 21 KB, in the player-visible transcript, while the read that followed
named both as held. The rulebook now rides only in a full ``endless_read_runtime``
(see test_context_dedupe), so no user message carries it, on any turn, in any
conversation. These tests pin that the message stays a few lines whatever the
slot's history, and that a replaced conversation still keeps the saved life.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import narrator  # noqa: E402
from narrator import (  # noqa: E402
    APP_NAME,
    MEMORY_MODE,
    ensure_narrator_slot,
    ensure_narrator_slot_ex,
)
from store import RunStore  # noqa: E402
from turn import advance_turn, compose_prompt  # noqa: E402

RULEBOOK = "the world does not revolve around the player"


class FakeSlot:
    def __init__(self, key):
        self.key = key
        self._app = APP_NAME
        self.memory_mode = MEMORY_MODE
        self.project = ""


class FakeState:
    def __init__(self):
        self.slots = {}
        self._slots = self.slots

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, agent="", app="", memory_mode=None, **kw):
        slot = FakeSlot(name)
        slot.memory_mode = memory_mode or "persistent"
        slot._app = app
        self.slots[name] = slot
        return slot


@pytest.fixture()
def store(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    return RunStore(AppStorage(APP_NAME, data), data)


@pytest.fixture()
def run(store):
    return store.create_run(
        {"turn": 0, "worldId": "w", "status": "awaiting-opening"},
        {"worldId": "w", "title": "a life"},
    )


def _prompts(sent: list[str]):
    def dispatch(state, slot, prompt, **_kw):
        sent.append(prompt)
        return True

    return dispatch


def _advance(state_obj, store, run_id, dispatch):
    return asyncio.run(
        advance_turn(
            state_obj=state_obj,
            store=store,
            run_id=run_id,
            dispatch=dispatch,
            inline_wait_secs=0.3,
        )
    )


# ── no message carries the rulebook ─────────────────────────────────────────


def _commit(store, run, turn):
    store.commit_state(run, {**store.read_state(run), "turn": turn})
    store.append_turn(run, {"turn": turn, "prose": "the snow stopped"})


def _assert_thin(prompt: str, run: str) -> None:
    from content import Content

    assert run in prompt, "the run id must be in every message"
    assert Content("en")("turn.read") in prompt
    assert RULEBOOK not in prompt
    assert len(prompt.encode("utf-8")) < 400, f"a turn message grew to {len(prompt)} chars"


def test_no_turn_message_carries_the_rulebook_in_a_fresh_or_kept_conversation(store, run):
    """First turn on a new slot, the next turn on the same slot, and a turn on a
    rebuilt slot: the message is the same few lines in all three."""
    state_obj = FakeState()
    sent: list[str] = []
    _advance(state_obj, store, run, _prompts(sent))
    _commit(store, run, 1)
    _advance(state_obj, store, run, _prompts(sent))
    _commit(store, run, 2)
    _advance(FakeState(), store, run, _prompts(sent))  # gateway restart: new slot

    assert len(sent) == 3
    for prompt in sent:
        _assert_thin(prompt, run)


def test_a_turn_message_has_no_channel_for_a_rulebook():
    """The parameter itself is gone, so no caller can push one back in."""
    import inspect

    params = set(inspect.signature(compose_prompt).parameters)
    assert not params & {"rulebook", "shape", "chronicle", "fresh"}, params
    assert not {"rulebook", "shape"} & set(inspect.signature(advance_turn).parameters)


def test_app_update_replaces_the_slot_but_keeps_the_saved_life(store, run, monkeypatch):
    purged: list[str] = []

    async def record_purge(_state, run_id):
        purged.append(run_id)
        return True

    state_obj = FakeState()
    sent: list[str] = []
    _advance(state_obj, store, run, _prompts(sent))
    old_slot = state_obj.slots[narrator.narrator_slot_key(run)]

    saved = {**store.read_state(run), "turn": 1, "kept": "the life survives"}
    store.commit_state(run, saved)
    store.append_turn(run, {"turn": 1, "prose": "the first month remains"})
    before_chronicle = store.read_chronicle(run)

    monkeypatch.setattr(narrator, "purge_narrator_session", record_purge)
    monkeypatch.setattr(narrator, "app_install_generation", lambda: "updated-install")
    _advance(state_obj, store, run, _prompts(sent))

    new_slot = state_obj.slots[narrator.narrator_slot_key(run)]
    assert new_slot is not old_slot, "the pre-update conversation was reused"
    assert purged == [run], "the pre-update persisted conversation was not purged"
    assert store.narrator_generation(run) == "updated-install"
    _assert_thin(sent[1], run)
    assert store.read_state(run) == saved, "slot replacement changed the save"
    assert store.read_chronicle(run) == before_chronicle


def test_the_turn_loop_writes_no_rulebook_marker(store, run):
    """Nothing reads the old delivery marker any more, so nothing writes it."""
    _advance(FakeState(), store, run, _prompts([]))
    assert store.briefed_slot(run) == ""


# ── the signal the decision rests on ────────────────────────────────────────


def test_the_slot_helper_reports_only_a_creation_as_new():
    state = FakeState()
    slot_a, created_a = ensure_narrator_slot_ex(state, "r" * 32)
    slot_b, created_b = ensure_narrator_slot_ex(state, "r" * 32)

    assert created_a is True, "the first call had nothing to find"
    assert created_b is False, "the second call found the slot the first one made"
    assert slot_a is slot_b


def test_the_plain_helper_still_returns_just_a_slot():
    """A caller that does not care about the distinction should not have to unpack
    it — and every existing caller and test uses this name."""
    slot = ensure_narrator_slot(FakeState(), "r" * 32)
    assert not isinstance(slot, tuple)
    assert getattr(slot, "key", "")
