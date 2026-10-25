"""An ask whose narrator run is over without a month stops reading as "being written".

Found by playing: a narrator agent refused at spawn (the host's sandbox could not
start it) left the birth screen cycling "The prologue to this life is unfolding."
for the whole opening budget. The run had ended in under a second, but nothing told
the app — the pending record stayed fresh, its slot still existed, so ``generating``
kept answering "a narrator is writing" and the page had no reason to stop waiting.

The run ending is the one moment the app KNOWS nobody is writing, so the dispatcher
reports it and the advance path marks the ask ended when no month landed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from narrator import APP_NAME, MEMORY_MODE  # noqa: E402
from store import RunStore  # noqa: E402
from turn import (  # noqa: E402
    advance_turn,
    generating,
    make_dispatcher,
    settle_unanswered,
    unanswered,
)


class FakeSlot:
    def __init__(self, key):
        self.key = key
        self._app = APP_NAME
        self.memory_mode = MEMORY_MODE
        self.project = ""
        self.unattended = False
        self.tasks: list = []

    def enqueue_or_run_prompt(self, prompt, runner, state):
        # The host runs the runner as a task; the test drives it explicitly.
        self.tasks.append(runner(state, self, prompt))
        return True


class FakeState:
    def __init__(self):
        self.slots = {}

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, agent="", app="", memory_mode=None, **kw):
        slot = FakeSlot(name)
        slot.memory_mode = memory_mode or "persistent"
        slot._app = app
        self.slots[name] = slot
        return slot

    async def run_background_turn(self, slot, coro):
        return await coro


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


def _drive(state_obj: FakeState) -> None:
    """Run every narrator task the fake host was handed, swallowing its failure."""

    async def _all():
        for slot in state_obj.slots.values():
            for task in slot.tasks:
                try:
                    await task
                except Exception:  # noqa: BLE001 — the refusal is the scenario
                    pass

    asyncio.run(_all())


async def _advance(store, run_id, state_obj, dispatch):
    return await advance_turn(
        state_obj=state_obj,
        store=store,
        run_id=run_id,
        dispatch=dispatch,
        inline_wait_secs=0.3,
    )


def test_a_narrator_refused_at_spawn_ends_the_wait(store, run):
    async def refused(_state, _slot, _prompt):
        raise RuntimeError("the sandbox failed to initialize")

    state_obj = FakeState()
    outcome = asyncio.run(_advance(store, run, state_obj, make_dispatcher(refused)))
    assert outcome.advanced is False
    # Before the run ends the ask is genuinely in flight.
    assert generating(store, run, state_obj) is not None

    _drive(state_obj)

    assert generating(store, run, state_obj) is None, (
        "the narrator's run is over and wrote nothing, yet the life still reads as "
        "being written — the page keeps waiting on a writer that does not exist"
    )
    assert unanswered(store, run) is True


def test_a_run_that_reached_the_tools_is_not_called_unanswered(store, run):
    """Seen in a playtest: the runtime died mid-prompt after the narrator had read
    the life, and the month still committed 75s later from a surviving tool
    process. A run that made any tool call may still have a writer."""

    async def died_after_reading(_state, _slot, _prompt):
        store.note_tool_call(run, "endless_read_runtime")
        raise RuntimeError("runtime process died during prompt")

    state_obj = FakeState()
    asyncio.run(_advance(store, run, state_obj, make_dispatcher(died_after_reading)))
    _drive(state_obj)

    assert unanswered(store, run) is False
    assert generating(store, run, state_obj) is not None


def test_a_run_that_committed_is_not_called_unanswered(store, run):
    async def writes(_state, _slot, _prompt):
        now = store.read_state(run)
        store.commit_state(run, {**now, "turn": 1})
        store.append_turn(run, {"turn": 1, "prose": "the snow stopped"})

    state_obj = FakeState()
    asyncio.run(_advance(store, run, state_obj, make_dispatcher(writes)))
    _drive(state_obj)

    assert unanswered(store, run) is False


def test_a_late_settle_never_closes_a_newer_ask(store, run):
    store.mark_pending(run, turn=1, slot="s")
    first = float(store.read_pending(run)["askedAt"])
    # A retry replaced the record before the first run's callback arrived.
    store.mark_pending(run, turn=1, slot="s")
    store._kv.set(store._pending_key(run), {**store.read_pending(run), "askedAt": first + 5})

    assert settle_unanswered(store, run, 1, first) is False
    assert unanswered(store, run) is False


def test_a_new_ask_clears_the_unanswered_mark(store, run):
    store.mark_pending(run, turn=1, slot="s")
    asked = float(store.read_pending(run)["askedAt"])
    assert settle_unanswered(store, run, 1, asked) is True
    assert unanswered(store, run) is True

    store.mark_pending(run, turn=1, slot="s")
    assert unanswered(store, run) is False
