"""A new narrator conversation is a new slot key, and the old key is removed.

Core keys everything it keeps about a conversation by the slot key: the resume
pointer to the provider session, its own transcript, and the history replay it
builds from that transcript on a cold start. A "fresh" conversation on a reused
key could therefore be handed the old one back by any of the three. The core
stand-in below models exactly those three, so "the new conversation starts with
no prior history" is measured the way core would produce it rather than asserted
from which helper was called.
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_delete_world import FakeCtx, FakeRequest, body_of  # noqa: E402

import narrator  # noqa: E402
import routes as routes_mod  # noqa: E402
from narrator import APP_NAME, MEMORY_MODE, narrator_slot_key  # noqa: E402
from store import RunStore  # noqa: E402
from turn import ROTATION_MAX_TURNS, advance_turn, generating  # noqa: E402

#: Read at import, before the autouse stand-in in conftest replaces it.
_REAL_GATEWAY_API = narrator._gateway_api


def _hkey(slot_key: str) -> str:
    return f"dashboard:{slot_key}"


class Core:
    """Resume pointers, transcripts and the one-shot replay suppression."""

    def __init__(self):
        self.sid: dict[str, str] = {}
        self.transcripts: dict[str, list[str]] = {}
        self.suppressed: set[str] = set()
        self.live: set[str] = set()
        self.unlinked: list[str] = []
        self.closed: list[str] = []
        self.api_calls: list[str] = []
        self._next = 0

    def mapped_sid(self, key):
        return self.sid.get(key, "")

    # -- SessionManager surface the app calls --
    async def remove(self, key):
        self.live.discard(key)
        self.suppressed.discard(key)

    def forget_conversation(self, key):
        return self.sid.pop(key, "")

    async def discard_conversation(self, key, *, replay=True):
        self.live.discard(key)
        self.sid.pop(key, None)
        if not replay:
            self.suppressed.add(key)

    # -- history store surface --
    def delete_session(self, key):
        return self.transcripts.pop(key, None) is not None

    # -- what a turn on a key is handed --
    def prior_history(self, key) -> list[str]:
        """The history a turn on ``key`` carries when its process is not live."""
        if key in self.live:
            return list(self.transcripts.get(key, []))
        if key in self.sid:  # native resume: the whole old conversation
            return list(self.transcripts.get(key, []))
        if key in self.suppressed:
            return []
        return list(self.transcripts.get(key, []))  # [CONVERSATION HISTORY] replay

    def run_turn(self, key, prompt) -> int:
        carried = self.prior_history(key)
        self.suppressed.discard(key)
        self.live.add(key)
        self._next += 1
        self.sid.setdefault(key, f"sid-{self._next}")
        self.transcripts.setdefault(key, []).append(prompt)
        return len(carried)


class Slot:
    def __init__(self, key):
        self.key = key
        self._app = APP_NAME
        self.memory_mode = MEMORY_MODE
        self.project = ""


class State:
    def __init__(self, core: Core):
        self.core = core
        self.slots: dict[str, Slot] = {}
        self._slots = self.slots
        self.sessions = core
        self.conversation_log = core
        self.created: list[str] = []
        self.turns: list[tuple[str, int]] = []  # (slot key, prior history carried)

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, app="", memory_mode=None, **_kw):
        if name not in self.slots:
            slot = Slot(name)
            slot._app = app
            slot.memory_mode = memory_mode or "persistent"
            self.slots[name] = slot
            self.created.append(name)
        return self.slots[name]


@pytest.fixture()
def core(monkeypatch):
    core = Core()
    utils = types.ModuleType("kiro_crew.dashboard.chat_utils")
    utils._history_key_for = _hkey
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.chat_utils", utils)
    transfer = types.ModuleType("kiro_crew.dashboard.session_transfer")
    transfer._unlink_layer_b_files = core.unlinked.append
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.session_transfer", transfer)
    teardown = types.ModuleType("kiro_crew.apps.teardown")
    teardown.hooks = {}
    teardown.register_slot_close_hook = lambda app, hook: teardown.hooks.__setitem__(app, hook)
    monkeypatch.setitem(sys.modules, "kiro_crew.apps.teardown", teardown)
    core.teardown = teardown

    class Gateway:
        """The public routes, behaving as core's handlers do for an app token."""

        def __init__(self, state):
            self.state = state

        async def delete(self, path):
            from urllib.parse import unquote

            core.api_calls.append(path)
            if path.startswith("/api/chat/slots/"):
                name = unquote(path[len("/api/chat/slots/") :])
                slot = self.state.slots.get(name)
                if slot is None or slot._app != APP_NAME:
                    return 404
                # close_slot: tell the owning app, pop, stop the session. The
                # resume pointer is KEPT (core preserves it for a reopen).
                hook = teardown.hooks.get(slot._app)
                if hook is not None:
                    await hook(name)
                self.state.slots.pop(name, None)
                await core.remove(_hkey(name))
                core.closed.append(name)
                return 200
            if path.startswith("/api/sessions/"):
                key = unquote(path[len("/api/sessions/") :])
                core.delete_session(key)
                return 200
            return 404

    monkeypatch.setattr(narrator, "_gateway_api", Gateway)
    monkeypatch.setattr(narrator, "app_install_generation", lambda: "g1")
    return core


@pytest.fixture()
def store(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    return RunStore(AppStorage(APP_NAME, data), data)


@pytest.fixture()
def run(store):
    return store.create_run({"turn": 0, "worldId": "w"}, {"worldId": "w", "title": "a life"})


def _ask(state, store, run, **kw):
    def dispatch(st, slot, prompt, **_kw):
        st.turns.append((slot.key, st.core.run_turn(_hkey(slot.key), prompt)))
        return True

    return asyncio.run(
        advance_turn(
            state_obj=state,
            store=store,
            run_id=run,
            dispatch=dispatch,
            inline_wait_secs=0.01,
            **kw,
        )
    )


def _commit(store, run):
    turn = int(store.read_state(run).get("turn") or 0) + 1
    store.commit_state(run, {**store.read_state(run), "turn": turn})
    store.append_turn(run, {"turn": turn, "prose": f"month {turn}"})
    store.clear_pending(run)


def _played(core, store, run, turns=2):
    """A life with a conversation that has history, at its current key."""
    state = State(core)
    for _ in range(turns):
        _ask(state, store, run)
        _commit(store, run)
    old = state.turns[-1][0]
    # The conversation has been handed the rulebook by a full read.
    store.mark_recall_sent(run, ["brief"], reset=True)
    assert store.recall_sent(run) == {"brief"}
    assert core.transcripts[_hkey(old)], "the premise: the old conversation has history"
    return state, old


def _assert_fresh_after(state, core, store, run, old):
    key, carried = state.turns[-1]
    assert key != old, "the new conversation must run on a new slot key"
    assert key == narrator_slot_key(run, store.conversation_number(run))
    assert carried == 0, "the new conversation was handed prior history"
    assert store.recall_sent(run) == set(), (
        "a new conversation holds nothing, so its first read must send the rulebook"
    )
    assert old not in state.slots, "the old slot must be closed"
    assert _hkey(old) not in core.sid, "the old resume pointer must be forgotten"
    assert _hkey(old) not in core.transcripts, "the old transcript must be deleted"
    assert store.stale_conversations(run) == []


# ── the bug, on the old scheme's own terms ─────────────────────────────────


def test_a_reused_key_hands_the_old_conversation_back(core, store, run):
    """The premise. A slot dropped and recreated under the SAME key resumes, which
    is why every path below has to move to a new key instead."""
    state, old = _played(core, store, run)
    state.slots.pop(old)
    assert core.prior_history(_hkey(old)), "recreating the same key resumes the old one"


# ── every rotation reason opens a new, empty conversation ──────────────────


def test_a_chapter_rotation(core, store, run):
    state, old = _played(core, store, run)
    _ask(state, store, run, chapter_crossed=True)
    _assert_fresh_after(state, core, store, run, old)


def test_a_budget_rotation(core, store, run):
    state, old = _played(core, store, run, turns=ROTATION_MAX_TURNS)
    _ask(state, store, run)
    _assert_fresh_after(state, core, store, run, old)


def test_an_idle_rotation(core, store, run, monkeypatch):
    import time

    state, old = _played(core, store, run)
    # The last month was committed an hour ago (these commits bypass the tool
    # that stamps the real time).
    monkeypatch.setattr(store, "committed_at", lambda _run, _turn: time.time() - 3600)
    _ask(state, store, run)
    _assert_fresh_after(state, core, store, run, old)


def test_an_install_change(core, store, run, monkeypatch):
    state, old = _played(core, store, run)
    monkeypatch.setattr(narrator, "app_install_generation", lambda: "g2")
    _ask(state, store, run)
    _assert_fresh_after(state, core, store, run, old)
    assert store.narrator_generation(run) == "g2"


def test_the_reset_control(core, store, run):
    state, old = _played(core, store, run)
    assert asyncio.run(narrator.reset_narrator_conversation(state, store, run))
    _ask(state, store, run)
    _assert_fresh_after(state, core, store, run, old)


def test_a_dismissed_tab(core, store, run):
    state, old = _played(core, store, run)
    # Core's own close of the CURRENT tab: hook first, then the pop.
    asyncio.run(core.teardown.hooks[APP_NAME](old))
    state.slots.pop(old)
    asyncio.run(core.remove(_hkey(old)))
    _ask(state, store, run)
    _assert_fresh_after(state, core, store, run, old)


def test_a_slot_heal(core, store, run):
    """A turn that expired without one tool call is answered with a new
    conversation; the same key rebuilt would resume the poisoned session."""
    import time

    state, old = _played(core, store, run)

    def silent(st, slot, prompt, **_kw):
        st.turns.append((slot.key, st.core.run_turn(_hkey(slot.key), prompt)))
        return True

    asyncio.run(
        advance_turn(
            state_obj=state,
            store=store,
            run_id=run,
            dispatch=silent,
            inline_wait_secs=0.01,
            budget_secs=0.01,
        )
    )
    time.sleep(0.05)
    _ask(state, store, run, budget_secs=0.01)
    _assert_fresh_after(state, core, store, run, old)


def test_an_existing_life_moves_on_its_next_rotation(core, store, run):
    """Migration: a life from before numbered keys sits on the bare key until it
    rotates, then moves like any other."""
    state, old = _played(core, store, run)
    assert old == narrator_slot_key(run), "an existing life keeps its key until it rotates"
    _ask(state, store, run, chapter_crossed=True)
    assert state.turns[-1][0] == narrator_slot_key(run, 1)


# ── one boundary, one new slot ─────────────────────────────────────────────


def test_a_retried_rotation_opens_one_new_slot(core, store, run):
    state, old = _played(core, store, run)
    _ask(state, store, run, chapter_crossed=True)
    _ask(state, store, run, chapter_crossed=True)  # the same month asked again
    new = [k for k in state.created if k != old and k != narrator_slot_key(run)]
    assert new == [narrator_slot_key(run, 1)], new
    assert store.conversation_number(run) == 1


def test_two_concurrent_requests_open_one_new_slot(core, store, run):
    state, old = _played(core, store, run)

    def dispatch(st, slot, prompt, **_kw):
        st.turns.append((slot.key, st.core.run_turn(_hkey(slot.key), prompt)))
        return True

    async def both():
        args = dict(
            state_obj=state,
            store=store,
            run_id=run,
            dispatch=dispatch,
            inline_wait_secs=0.01,
            chapter_crossed=True,
        )
        await asyncio.gather(advance_turn(**args), advance_turn(**args))

    asyncio.run(both())
    assert store.conversation_number(run) == 1
    assert {k for k, _ in state.turns[2:]} == {narrator_slot_key(run, 1)}


def test_two_concurrent_requests_after_an_update_open_one_new_slot(core, store, run, monkeypatch):
    state, _old = _played(core, store, run)
    monkeypatch.setattr(narrator, "app_install_generation", lambda: "g2")

    def dispatch(st, slot, prompt, **_kw):
        st.turns.append((slot.key, st.core.run_turn(_hkey(slot.key), prompt)))
        return True

    async def both():
        args = dict(
            state_obj=state,
            store=store,
            run_id=run,
            dispatch=dispatch,
            inline_wait_secs=0.01,
        )
        await asyncio.gather(advance_turn(**args), advance_turn(**args))

    asyncio.run(both())
    assert store.conversation_number(run) == 1
    assert {k for k, _ in state.turns[2:]} == {narrator_slot_key(run, 1)}


def test_the_dismissal_hook_ignores_an_old_key(core, store, run):
    """Retiring an old slot goes through core's close, which calls the hook."""
    state, old = _played(core, store, run)
    _ask(state, store, run, chapter_crossed=True)
    assert old in core.closed, "the old slot is closed through core's own close"
    assert store.conversation_number(run) == 1, "closing the OLD key must not move again"


# ── the current slot is still found ────────────────────────────────────────


def test_generating_finds_the_live_slot_on_the_new_key(core, store, run):
    state, _old = _played(core, store, run)
    _ask(state, store, run, chapter_crossed=True)  # left in flight (no commit)
    pending = store.read_pending(run)
    assert pending["slot"] == narrator_slot_key(run, 1)
    live = generating(store, run, state_obj=state)
    assert live is not None, "a live slot on the new key reads as in flight"
    assert live["slot"] == narrator_slot_key(run, 1)
    # And the liveness check really is reading that key: without the slot the
    # record's writer cannot exist.
    state.slots.pop(narrator_slot_key(run, 1))
    assert generating(store, run, state_obj=state) is None


# ── deleting a life removes every conversation it had ──────────────────────


class _Request(FakeRequest):
    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.app = {"state": state}


def test_deleting_a_life_removes_all_its_conversations(core, store, run, tmp_path):
    state, first = _played(core, store, run)
    _ask(state, store, run, chapter_crossed=True)
    _commit(store, run)
    # A stale conversation whose removal failed earlier, still on record.
    store.begin_conversation(run)
    _ask(state, store, run)
    _commit(store, run)
    keys = narrator.life_slot_keys(store, run)
    assert len(keys) == 3
    stuck = keys[1]
    core.transcripts[_hkey(stuck)] = ["left behind"]
    turn = int(store.read_state(run)["turn"])

    ctx = FakeCtx(store.data_dir, store._kv)
    res = asyncio.run(
        routes_mod.delete_life(
            _Request(state, match={"run_id": run}, body={"confirm": run, "turn": turn}), ctx
        )
    )
    assert res.status == 200, body_of(res)
    for key in keys:
        assert key not in state.slots, f"{key} still open"
        assert _hkey(key) not in core.sid, f"{key} resume pointer left"
        assert _hkey(key) not in core.transcripts, f"{key} transcript left"


# ── the public API client, against a real HTTP server ──────────────────────


def test_the_gateway_client_uses_the_app_secret_and_token_cookie(tmp_path, monkeypatch):
    """Token exchange with ``X-App-Secret``, then the port-scoped cookie, the same
    protocol as the shipped ``kirocrew_client``. Run against a real aiohttp server
    on loopback, so the requests on the wire are what is checked."""
    from aiohttp import web

    secret_dir = tmp_path / "apps" / APP_NAME
    secret_dir.mkdir(parents=True)
    (secret_dir / ".app_secret").write_text("s3cret\n", encoding="utf-8")
    monkeypatch.setenv("KIROCREW_HOME", str(tmp_path))
    seen: list[tuple[str, str]] = []

    async def scenario():
        async def token(request):
            if request.headers.get("X-App-Secret") != "s3cret":
                return web.json_response({"error": "invalid secret"}, status=403)
            return web.json_response({"token": "app-token"})

        async def delete(request):
            port = request.url.port
            seen.append((request.path, request.cookies.get(f"mc_token_{port}", "")))
            return web.json_response({"ok": True})

        app = web.Application()
        app.router.add_post(f"/api/apps/{APP_NAME}/token", token)
        app.router.add_delete("/api/chat/slots/{slot}", delete)
        app.router.add_delete("/api/sessions/{key}", delete)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        monkeypatch.setenv("KIROCREW_BOUND_PORT", str(port))
        try:
            api = narrator.GatewayApi(
                narrator._gateway_base_url(),
                narrator._app_secret_path().read_text(encoding="utf-8").strip(),
            )
            a = await api.delete("/api/chat/slots/endless-run-r-c1")
            b = await api.delete("/api/sessions/dashboard%3Aendless-run-r-c1")
        finally:
            await runner.cleanup()
        return a, b

    assert asyncio.run(scenario()) == (200, 200)
    assert seen == [
        ("/api/chat/slots/endless-run-r-c1", "app-token"),
        ("/api/sessions/dashboard:endless-run-r-c1", "app-token"),
    ]


def test_no_app_secret_means_no_removal_and_a_retry(store, run, tmp_path, monkeypatch):
    """Without credentials nothing is removed and the conversation stays on record."""
    monkeypatch.setattr(narrator, "_gateway_api", _REAL_GATEWAY_API)
    monkeypatch.setenv("KIROCREW_HOME", str(tmp_path))  # no .app_secret here
    store.begin_conversation(run)
    assert narrator._gateway_api(object()) is None
    assert asyncio.run(narrator.retire_stale_conversations(object(), store, run)) == []
    assert store.stale_conversations(run) == [0]


def test_a_refused_delete_is_retried_next_turn(core, store, run, monkeypatch):
    """A 403 (the grant not approved yet) or a 500 is not a removal."""
    state, old = _played(core, store, run)

    class Refusing:
        def __init__(self, _state):
            pass

        async def delete(self, path):
            return 403

    monkeypatch.setattr(narrator, "_gateway_api", Refusing)
    _ask(state, store, run, chapter_crossed=True)
    assert store.stale_conversations(run) == [0], "kept on record for a retry"
    assert _hkey(old) in core.sid, "nothing private ran ahead of the public delete"
