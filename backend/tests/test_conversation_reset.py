"""Guards on the three ways a narrator conversation is replaced mid-life.

Update: ``app_install_generation`` is a FUNCTION evaluated per call, because App
Store Sync swaps the app's files without re-importing the module — proven on a
live gateway where an import-time constant kept naming the pre-update install,
the first post-update turn persisted that stale value as the run's marker, and
the reset the update should have triggered could then never fire again.

Close: the player closing the story's tab asks for a fresh storyteller. Core
deliberately preserves a closed slot's resume pointer, so the app detects the
close itself — a process-local registry, because the narrator's temporary-mode
slot is never in ``open_slots.json`` (its persist filter keeps only
``persistent`` slots) and a restart must keep reading as "continue", not "closed".

Manual: one seam, ``reset_narrator_conversation``, discards the conversation
through the LIVE manager and clears the briefed marker in the same call — a
discarded conversation that kept its slot would otherwise never re-brief
(``brief_now = fresh_slot or briefed != slot_key`` stays False on both arms).
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
    consume_closed_slot,
    ensure_narrator_slot_ex,
    narrator_slot_key,
    reset_narrator_conversation,
)
from store import RunStore  # noqa: E402


class FakeSlot:
    def __init__(self, key):
        self.key = key
        self._app = APP_NAME
        self.memory_mode = MEMORY_MODE
        self.project = ""


class FakeSessions:
    def __init__(self):
        self.discarded: list[str] = []

    async def discard_conversation(self, key: str) -> None:
        self.discarded.append(key)


class FakeState:
    def __init__(self):
        self.slots = {}
        self._slots = self.slots
        self.sessions = FakeSessions()

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


@pytest.fixture(autouse=True)
def _clean_registry():
    narrator._LIVE_SLOT_KEYS.clear()
    yield
    narrator._LIVE_SLOT_KEYS.clear()


# ── the generation is read from the CURRENT files, not from import time ─────


def _install(tmp_path: Path) -> Path:
    root = tmp_path / "install"
    (root / "backend").mkdir(parents=True)
    (root / "app.json").write_text('{"name": "endless-worlds", "version": "1.0.0"}')
    (root / "backend" / "narrator.py").write_text("# app code\n")
    return root


def test_generation_changes_when_a_file_changes(tmp_path, monkeypatch):
    root = _install(tmp_path)
    monkeypatch.setattr(narrator, "_APP_ROOT", root)
    narrator._GENERATION_CACHE = None
    before = narrator.app_install_generation()
    # Same tree asked again: same answer (and the memoized path, see next test).
    assert narrator.app_install_generation() == before
    (root / "app.json").write_text(
        '{"name": "endless-worlds", "version": "1.0.1", "updated": true}'
    )
    after = narrator.app_install_generation()
    assert after != before, "an updated install must change the generation"


def test_generation_is_memoized_on_unchanged_metadata(tmp_path, monkeypatch):
    root = _install(tmp_path)
    monkeypatch.setattr(narrator, "_APP_ROOT", root)
    narrator._GENERATION_CACHE = None
    narrator.app_install_generation()
    calls: list[int] = []
    real = narrator._installation_generation

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(narrator, "_installation_generation", counting)
    narrator.app_install_generation()
    assert not calls, "unchanged metadata must not re-read every file's bytes"
    # A metadata change (mtime bump) re-runs the full digest exactly once.
    target = root / "app.json"
    stat = target.stat()
    import os

    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    narrator.app_install_generation()
    assert len(calls) == 1


# ── close detection: process-local, one answer per close ────────────────────


def test_a_closed_slot_is_detected_once(store, run):
    state = FakeState()
    ensure_narrator_slot_ex(state, run)
    key = narrator_slot_key(run)
    assert not consume_closed_slot(state, run), "an open slot is not a close"
    state.slots.pop(key)
    assert consume_closed_slot(state, run), "created-then-gone is a close"
    assert not consume_closed_slot(state, run), "a close is consumed, not repeated"
    # Re-created and closed again: detected again.
    ensure_narrator_slot_ex(state, run)
    state.slots.pop(key)
    assert consume_closed_slot(state, run)


def test_a_restart_is_not_a_close(store, run):
    # A fresh registry (what a gateway restart produces) never reports a close,
    # even though the slot is absent — restart resumes, close resets.
    state = FakeState()
    assert not consume_closed_slot(state, run)


def test_a_reused_slot_registers_for_close_detection(store, run):
    # The slot predates this module's registry (module reload): the reuse path
    # must register it, or a later close would be invisible.
    state = FakeState()
    state.slots[narrator_slot_key(run)] = FakeSlot(narrator_slot_key(run))
    ensure_narrator_slot_ex(state, run)
    state.slots.pop(narrator_slot_key(run))
    assert consume_closed_slot(state, run)


# ── the reset seam: live manager, and the briefed marker dies with it ───────


def test_reset_discards_through_the_live_manager(store, run, monkeypatch):
    # ``chat_utils`` transitively imports messaging SDKs this test environment
    # does not ship, so the seam's import is satisfied from ``sys.modules`` with
    # a module exposing the one name it needs. The transform is identity — what
    # is under test is the seam's contract, not core's filename sanitiser.
    import types

    fake = types.ModuleType("kiro_crew.dashboard.chat_utils")
    fake._history_key_for = lambda key: key
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.chat_utils", fake)

    state = FakeState()
    ensure_narrator_slot_ex(state, run)
    key = narrator_slot_key(run)
    store.mark_briefed(run, slot=key)
    done = asyncio.run(reset_narrator_conversation(state, store, run))
    assert done
    assert state.sessions.discarded == [key]
    assert store.briefed_slot(run) == "", "a discarded conversation must re-brief"
    assert key in state.slots, "the tab (slot) survives a conversation reset"


def test_reset_survives_a_missing_runtime(store, run):
    class NoSessions:
        _slots: dict = {}

    assert not asyncio.run(reset_narrator_conversation(NoSessions(), store, run))


def test_reset_refuses_a_bad_run_id(store):
    # "not-a-run-id" would be a trap here: lowercase-and-hyphens MATCHES the run
    # id grammar. Use shapes the grammar actually refuses.
    state = FakeState()
    assert not asyncio.run(reset_narrator_conversation(state, store, "../escape"))
    assert not asyncio.run(reset_narrator_conversation(state, store, "Upper"))
    assert not asyncio.run(reset_narrator_conversation(state, store, ""))


def test_clear_briefed_round_trip(store, run):
    store.mark_briefed(run, slot="some-slot")
    assert store.briefed_slot(run) == "some-slot"
    store.clear_briefed(run)
    assert store.briefed_slot(run) == ""
    store.clear_briefed(run)  # idempotent
    assert store.briefed_slot(run) == ""


# ── the wiring: a close observed by the TURN LOOP resets the conversation ───


def test_a_closed_tab_gets_a_fresh_conversation_on_the_next_turn(store, run, monkeypatch):
    from turn import advance_turn

    RULEBOOK = "the world does not revolve around the player"
    state = FakeState()
    sent: list[str] = []

    def dispatch(_state, _slot, prompt):
        sent.append(prompt)
        return True

    def advance():
        return asyncio.run(
            advance_turn(
                state_obj=state,
                store=store,
                run_id=run,
                rulebook=RULEBOOK,
                dispatch=dispatch,
                deadline_secs=0.3,
                shape="declare state in this shape: status",
            )
        )

    import types

    fake = types.ModuleType("kiro_crew.dashboard.chat_utils")
    fake._history_key_for = lambda key: key
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.chat_utils", fake)

    advance()
    assert RULEBOOK in sent[0]
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "the snow stopped"})

    # The player closes the tab between turns.
    key = narrator_slot_key(run)
    state.slots.pop(key)

    advance()
    assert state.sessions.discarded == [key], "a closed tab must discard the conversation"
    assert RULEBOOK in sent[1], "the fresh conversation must be re-briefed"

    # And a third turn on the SAME (reopened) tab does not reset again.
    store.commit_state(run, {**store.read_state(run), "turn": 2})
    store.append_turn(run, {"turn": 2, "prose": "spring"})
    advance()
    assert len(state.sessions.discarded) == 1, "one close, one reset"
    assert RULEBOOK not in sent[2]
