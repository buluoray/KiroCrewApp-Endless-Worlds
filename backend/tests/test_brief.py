"""Guards on delivering the world's law once instead of every turn.

Measured on a live run before this change, from the narrator's own session file:

    dashboard_endless-run-9856fa….jsonl   643 KB, one conversation, every turn of it
      user  15,306 chars   carries the rulebook
      user  17,036 chars   carries the rulebook
      user  19,149 chars   carries the rulebook
      user  20,807 chars   carries the rulebook
      user  21,734 chars   carries the rulebook

One conversation per life, and the whole 15,000-character rulebook re-sent inside
every message in it — 70% of the prompt by turn four, growing without bound while
changing never. The narrator was already holding it from turn one.

The risk of the fix is the opposite failure, and it is much worse than the waste: a
life whose narrator never received its world narrates a different world. So these
tests are mostly about the conditions under which the rulebook MUST be sent again,
not about the saving.
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
    def dispatch(state, slot, prompt):
        sent.append(prompt)
        return True

    return dispatch


def _advance(state_obj, store, run_id, dispatch):
    return asyncio.run(
        advance_turn(
            state_obj=state_obj,
            store=store,
            run_id=run_id,
            rulebook=RULEBOOK,
            dispatch=dispatch,
            inline_wait_secs=0.3,
            shape="declare state in this shape: status",
        )
    )


# ── the saving ──────────────────────────────────────────────────────────────


def test_the_first_turn_of_a_life_carries_the_rulebook(store, run):
    sent: list[str] = []
    _advance(FakeState(), store, run, _prompts(sent))

    assert len(sent) == 1
    assert RULEBOOK in sent[0], "a narrator's first turn must arrive with its world"


def test_the_next_turn_does_not_repeat_it(store, run):
    """The measured waste, removed. The conversation is the same one; the rulebook is
    still in it."""
    state_obj = FakeState()
    sent: list[str] = []
    _advance(state_obj, store, run, _prompts(sent))

    # The narrator commits turn 1, so the next call asks for turn 2 rather than
    # attaching to the one in flight.
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "the snow stopped"})

    _advance(state_obj, store, run, _prompts(sent))

    assert len(sent) == 2
    assert RULEBOOK not in sent[1], "the rulebook was sent twice to one conversation"
    # And the turn is still fully specified without it: which life, which month, and
    # an instruction to go and read the rest.
    from content import Content

    assert run in sent[1], "the run id must survive the trimming"
    assert Content("en")("turn.ask", turn=2) in sent[1], (
        "the narrator must still be told which month it is writing"
    )
    assert Content("en")("turn.pull") not in sent[1], (
        "the pull instruction is in the system prompt (narrator.json), not repeated each turn"
    )


def test_omitting_the_rulebook_omits_its_heading_too(store, run):
    """A label with nothing under it reads as a world with no rules — worse than
    either sending the text or saying nothing."""
    from content import Content

    heading = Content("en")("turn.rulebook")
    with_book = compose_prompt(
        run_id="run-1", rulebook=RULEBOOK, state={}, chronicle=[], language="en"
    )
    without = compose_prompt(run_id="run-1", rulebook="", state={}, chronicle=[], language="en")
    assert heading in with_book
    assert heading not in without


# ── when it must be sent again ──────────────────────────────────────────────


def test_a_replaced_conversation_gets_the_rulebook_again(store, run):
    """A slot created by this call has nothing behind it, whatever a marker says.

    This is the gateway-restart case, and it is the one where being wrong is
    expensive: a life narrated without its world is not a slow life, it is a
    different world.
    """
    first = FakeState()
    sent: list[str] = []
    _advance(first, store, run, _prompts(sent))
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "p"})

    # A brand-new state object: the slot does not exist and has to be created.
    _advance(FakeState(), store, run, _prompts(sent))

    assert RULEBOOK in sent[1], (
        "a narrator with a fresh conversation was asked to continue a life whose "
        "rules it had never been told"
    )


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
    assert RULEBOOK in sent[1], "the new conversation was not re-briefed"
    assert store.read_state(run) == saved, "slot replacement changed the save"
    assert store.read_chronicle(run) == before_chronicle


def test_a_marker_naming_another_slot_does_not_count(store, run):
    """A rulebook read into a conversation that is not this one has not been
    delivered to this one."""
    store.mark_briefed(run, slot="endless-run-somebody-else")

    sent: list[str] = []
    _advance(FakeState(), store, run, _prompts(sent))
    assert RULEBOOK in sent[0]


def test_the_marker_is_written_after_the_prompt_that_carries_it(store, run):
    """Order, and the direction of the failure.

    Marking first and failing to dispatch would leave a life permanently convinced
    its narrator had been briefed. Marking after costs one redundant re-send if the
    process dies in between — which is the safe way to be wrong.
    """
    seen: dict[str, str] = {}

    def dispatch(state, slot, prompt):
        seen["at_dispatch"] = store.briefed_slot(run)
        return True

    _advance(FakeState(), store, run, dispatch)

    assert seen["at_dispatch"] == "", (
        "the run was marked as briefed before the prompt carrying the rulebook was even handed over"
    )
    assert store.briefed_slot(run), "the marker was never written"


def test_the_marker_names_the_conversation_it_was_read_to(store, run):
    sent: list[str] = []
    _advance(FakeState(), store, run, _prompts(sent))
    assert run in store.briefed_slot(run)


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
