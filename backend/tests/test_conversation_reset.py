"""Guards on the three ways a narrator conversation is replaced mid-life.

Update: ``app_install_generation`` is a FUNCTION evaluated per call, because App
Store Sync swaps the app's files without re-importing the module — proven on a
live gateway where an import-time constant kept naming the pre-update install,
the first post-update turn persisted that stale value as the run's marker, and
the reset the update should have triggered could then never fire again.

Close: the player closing the story's tab asks for a fresh storyteller. Core
preserves a closed slot's resume pointer (a reopened tab continues), so the app
has to act — but it must not act on the slot's mere ABSENCE. The bulk
idle-archive sweep removes app slots too and stamps the same ``closed_at``, so
absence cannot tell "the player closed this" from "this was quiet for three
days", and only the first should cost a conversation. Core already draws that
line by which call site fires: ``notify_slot_closed`` runs for a deliberate
dismissal and deliberately not for the sweep. So the app registers a hook and is
TOLD, rather than inferring.

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
    _SLOT_PREFIX,
    APP_NAME,
    MEMORY_MODE,
    ensure_narrator_slot_ex,
    install_close_hook,
    narrator_slot_key,
    reset_narrator_conversation,
    run_id_from_slot_key,
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
        self.replays: list[bool] = []

    async def discard_conversation(self, key: str, *, replay: bool = True) -> None:
        self.discarded.append(key)
        self.replays.append(replay)


class LegacyFakeSessions:
    """A core build predating the ``replay`` knob (#5736)."""

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
    """Leave no hook behind in core's registry.

    It is process memory keyed by app name, so a test that reaches the real
    registry (rather than the stand-in these tests inject) would hand the next
    test a live hook closed over a dead store.
    """

    def _drop():
        try:
            from kiro_crew.apps.teardown import unregister_slot_close_hook

            unregister_slot_close_hook(APP_NAME)
        except Exception:  # noqa: BLE001 — no core in this environment
            pass

    _drop()
    yield
    _drop()


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


# ── being TOLD about a close, rather than inferring one ─────────────────────


def _register_hook(state, store, monkeypatch):
    """Install the hook against a stand-in core registry; return what it holds."""
    import types

    registry: dict = {}
    fake = types.ModuleType("kiro_crew.apps.teardown")
    fake.register_slot_close_hook = lambda app, hook: registry.__setitem__(app, hook)
    monkeypatch.setitem(sys.modules, "kiro_crew.apps.teardown", fake)
    install_close_hook(state, store)
    return registry


def test_the_run_is_recovered_from_the_slot_key():
    run = "a" * 32
    assert run_id_from_slot_key(narrator_slot_key(run)) == run
    # Core hands the hook a slot NAME, and one that does not decode to a real run
    # id must be ignored rather than reached into the store with. Note the trap the
    # bad-id test below also names: lowercase-and-hyphens MATCHES the run-id
    # grammar, so a suffixed key decodes to a DIFFERENT valid run, not to nothing.
    assert run_id_from_slot_key("chat-1-1787551170") == ""
    assert run_id_from_slot_key(f"{_SLOT_PREFIX}Upper") == ""
    assert run_id_from_slot_key(f"{_SLOT_PREFIX}../escape") == ""
    assert run_id_from_slot_key(_SLOT_PREFIX + "a" * 49) == ""
    assert run_id_from_slot_key(_SLOT_PREFIX) == ""
    assert run_id_from_slot_key("") == ""


def test_the_hook_is_registered_under_this_app(store, run, monkeypatch):
    state = FakeState()
    registry = _register_hook(state, store, monkeypatch)
    assert list(registry) == [APP_NAME], (
        "core keys the registry by app name; registering under anything else means "
        "the close is never delivered and the reset silently stops happening"
    )


def test_a_dismissal_delivered_by_core_resets_the_conversation(store, run, monkeypatch):
    import types

    chat_utils = types.ModuleType("kiro_crew.dashboard.chat_utils")
    chat_utils._history_key_for = lambda key: key
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.chat_utils", chat_utils)

    state = FakeState()
    ensure_narrator_slot_ex(state, run)
    key = narrator_slot_key(run)
    store.mark_briefed(run, slot=key)
    store.commit_state(run, {**store.read_state(run), "turn": 7})

    hook = _register_hook(state, store, monkeypatch)[APP_NAME]
    asyncio.run(hook(key))

    assert state.sessions.discarded == [key]
    assert store.briefed_slot(run) == "", "the fresh conversation must re-brief"
    assert store.rotation_turn(run) == 7, (
        "the rotation marker must record this turn, or the next turn's planned "
        "rotation discards the conversation this just created"
    )


def test_a_foreign_slot_name_is_ignored(store, run, monkeypatch):
    """Core hands the hook every slot name this app owns, and an app can own more
    than one kind. A name that is not a run's slot must not be decoded into one.

    The reset seam is deliberately reachable here (its import is satisfied), so the
    name guard is the only thing standing between this call and a discard.
    """
    import types

    chat_utils = types.ModuleType("kiro_crew.dashboard.chat_utils")
    chat_utils._history_key_for = lambda key: key
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.chat_utils", chat_utils)

    state = FakeState()
    hook = _register_hook(state, store, monkeypatch)[APP_NAME]

    asyncio.run(hook("chat-1-1787551170"))

    assert state.sessions.discarded == []


def test_a_failing_reset_does_not_block_the_dismissal(store, run, monkeypatch):
    """Core refuses a close whose hook raises. That is right for an app whose hook
    pauses a worker and wrong for ours: the player wants the tab gone, and a stale
    pointer is the behaviour that shipped before this existed."""
    state = FakeState()

    async def boom(*_a, **_kw):
        raise RuntimeError("session store is wedged")

    monkeypatch.setattr(narrator, "reset_narrator_conversation", boom)
    hook = _register_hook(state, store, monkeypatch)[APP_NAME]

    asyncio.run(hook(narrator_slot_key(run)))  # must not raise


def test_no_dashboard_runtime_is_a_no_op(store, monkeypatch):
    """Unit-test environments have no core to register with."""
    monkeypatch.setitem(sys.modules, "kiro_crew.apps.teardown", None)
    install_close_hook(FakeState(), store)  # must not raise


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
    assert state.sessions.replays == [False], (
        "replay must be suppressed: clearing the resume pointer is exactly what "
        "makes core's next cold start rebuild the discarded transcript as a "
        "[CONVERSATION HISTORY] block, so a reset that leaves replay on hands the "
        "fresh narrator a reconstruction of the pages it just forgot"
    )


def test_reset_still_runs_on_a_core_without_the_replay_knob(store, run, monkeypatch):
    """``replay`` only exists on core builds carrying the conversation-reset knob.

    On an older one the reset must still happen — with replay, which is the old
    behaviour — rather than raising a TypeError the caller reads as a failed reset.
    """
    import types

    fake = types.ModuleType("kiro_crew.dashboard.chat_utils")
    fake._history_key_for = lambda key: key
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.chat_utils", fake)

    state = FakeState()
    state.sessions = LegacyFakeSessions()
    ensure_narrator_slot_ex(state, run)
    key = narrator_slot_key(run)
    done = asyncio.run(reset_narrator_conversation(state, store, run))
    assert done, "a core without the knob must still get its conversation reset"
    assert state.sessions.discarded == [key]


def test_a_kwargs_forwarding_manager_is_offered_the_knob():
    """A ``**kwargs`` signature forwards, so it must be treated as accepting it —
    otherwise a wrapper around core silently downgrades every reset to replay-on."""
    from narrator import _accepts_replay

    async def forwards(key, **kw):  # pragma: no cover - signature only
        ...

    async def positional_only(key):  # pragma: no cover - signature only
        ...

    assert _accepts_replay(forwards)
    assert not _accepts_replay(positional_only)
    # Unintrospectable degrades to the pre-knob call rather than raising.
    assert not _accepts_replay(object())


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


# ── the wiring: a dismissal reaches the turn loop through the hook ──────────


def test_a_dismissed_tab_gets_a_fresh_conversation_on_the_next_turn(store, run, monkeypatch):
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
                inline_wait_secs=0.3,
                shape="declare state in this shape: status",
            )
        )

    import types

    chat_utils = types.ModuleType("kiro_crew.dashboard.chat_utils")
    chat_utils._history_key_for = lambda key: key
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.chat_utils", chat_utils)

    registry: dict = {}
    teardown = types.ModuleType("kiro_crew.apps.teardown")
    teardown.register_slot_close_hook = lambda app, hook: registry.__setitem__(app, hook)
    monkeypatch.setitem(sys.modules, "kiro_crew.apps.teardown", teardown)

    advance()
    assert RULEBOOK in sent[0]
    assert APP_NAME in registry, "the turn path must arm the hook, since core forgets it"
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "the snow stopped"})

    # The player dismisses the tab between turns. Core tells us, then pops the slot.
    key = narrator_slot_key(run)
    asyncio.run(registry[APP_NAME](key))
    state.slots.pop(key)
    assert state.sessions.discarded == [key], "a dismissal must discard the conversation"

    advance()
    assert RULEBOOK in sent[1], "the fresh conversation must be re-briefed"

    # A third turn on the SAME (reopened) tab must not rotate again: the dismissal
    # recorded its turn, so the planned rotation sees the boundary already spent.
    store.commit_state(run, {**store.read_state(run), "turn": 2})
    store.append_turn(run, {"turn": 2, "prose": "spring"})
    advance()
    assert len(state.sessions.discarded) == 1, "one dismissal, one reset"
    assert RULEBOOK not in sent[2]


def test_the_idle_archive_sweep_costs_no_conversation(store, run, monkeypatch):
    """The regression that inference produced.

    The bulk cleanup sweep pops app slots and stamps the same ``closed_at`` as a
    real close, so a slot's absence cannot mean "the player asked for this". A
    life left alone past the sweep's threshold and then tidied away must come back
    with its conversation, not a blank storyteller.
    """
    from turn import advance_turn

    state = FakeState()

    def dispatch(_state, _slot, prompt):
        return True

    def advance():
        return asyncio.run(
            advance_turn(
                state_obj=state,
                store=store,
                run_id=run,
                rulebook="rules",
                dispatch=dispatch,
                inline_wait_secs=0.3,
                shape="declare state in this shape: status",
            )
        )

    import types

    chat_utils = types.ModuleType("kiro_crew.dashboard.chat_utils")
    chat_utils._history_key_for = lambda key: key
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.chat_utils", chat_utils)
    teardown = types.ModuleType("kiro_crew.apps.teardown")
    teardown.register_slot_close_hook = lambda app, hook: None
    monkeypatch.setitem(sys.modules, "kiro_crew.apps.teardown", teardown)

    advance()
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "quiet"})

    # The sweep removes the slot WITHOUT calling the close hook. That is core's
    # deliberate distinction, and it is the whole reason we no longer infer.
    state.slots.pop(narrator_slot_key(run))

    advance()
    assert state.sessions.discarded == [], (
        "a tidied-away tab is not a dismissal; discarding here would lose a "
        "conversation the player never asked to end"
    )
