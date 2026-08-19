"""Narrator slot tests.

The fakes here mimic core's ``get_slot`` / ``get_or_create_slot`` semantics. A
fake that drifts from core proves nothing, so ``TestAgainstRealCore`` pins the
two behaviours the fakes assume against the REAL classes when the source tree is
importable, and skips otherwise.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import narrator  # noqa: E402
from narrator import (  # noqa: E402
    APP_NAME,
    MEMORY_MODE,
    NARRATOR_AGENT,
    OWN_SERVER_REF,
    BadRunId,
    MemoryModeConflict,
    SlotOwnedByAnother,
    ensure_narrator_slot,
    is_narrator_slot,
    narrator_slot_key,
    release_narrator_slot,
)

AGENT_JSON = _BACKEND.parent / "agents" / "narrator.json"
APP_JSON = _BACKEND.parent / "app.json"


class FakeSlot:
    def __init__(self, key, agent="", app="", memory_mode="persistent"):
        self.key = key
        self.agent = agent
        self._app = app
        self.memory_mode = memory_mode
        self.project = ""


class FakeState:
    """Mirrors state.py:4501-4520 — including the raise on a mode conflict."""

    def __init__(self):
        self.slots: dict[str, FakeSlot] = {}
        self.create_calls: list[dict] = []

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, agent="", app="", memory_mode=None, **kw):
        self.create_calls.append(
            {"name": name, "agent": agent, "app": app, "memory_mode": memory_mode, **kw}
        )
        if name in self.slots:
            existing = self.slots[name]
            if memory_mode is not None and memory_mode != existing.memory_mode:
                raise ValueError(
                    f"Slot {name!r} already exists with memory_mode={existing.memory_mode!r}"
                )
            return existing
        slot = FakeSlot(name, agent=agent, app=app, memory_mode=memory_mode or "persistent")
        self.slots[name] = slot
        return slot


# -- creation -------------------------------------------------------------


def test_a_new_run_gets_a_sealed_slot_owned_by_this_app():
    state = FakeState()
    slot = ensure_narrator_slot(state, "run-1", project="/tmp/run-1")

    assert slot.memory_mode == MEMORY_MODE == "temporary"
    assert slot._app == APP_NAME
    assert slot.agent == NARRATOR_AGENT
    assert slot.project == "/tmp/run-1"


def test_the_seal_is_requested_at_creation_not_assigned_after():
    """memory_mode cannot be fixed later: core validates it in ``Slot.__init__``
    and refuses to change it on an existing slot, so passing it to the create
    call is the only moment it can be set."""
    state = FakeState()
    ensure_narrator_slot(state, "run-1")
    assert state.create_calls[0]["memory_mode"] == "temporary"


def test_a_second_call_returns_the_same_slot_without_recreating():
    state = FakeState()
    first = ensure_narrator_slot(state, "run-1")
    before = len(state.create_calls)
    second = ensure_narrator_slot(state, "run-1")

    assert second is first
    assert len(state.create_calls) == before, "must not re-enter creation"


# -- refusals -------------------------------------------------------------


def test_a_slot_another_app_owns_is_refused_not_adopted():
    state = FakeState()
    state.slots["endless-run-run-1"] = FakeSlot(
        "endless-run-run-1", app="some-other-app", memory_mode="temporary"
    )
    with pytest.raises(SlotOwnedByAnother) as exc:
        ensure_narrator_slot(state, "run-1")
    assert "some-other-app" in str(exc.value)


def test_an_unowned_slot_under_our_key_is_refused_too():
    """An unscoped slot with our key is somebody's own chat session that happens
    to be named this. Adopting it would pull their transcript into the game."""
    state = FakeState()
    state.slots["endless-run-run-1"] = FakeSlot("endless-run-run-1", app="", memory_mode="temporary")
    with pytest.raises(SlotOwnedByAnother):
        ensure_narrator_slot(state, "run-1")


@pytest.mark.parametrize("mode", ["persistent", "incognito"])
def test_an_unsealed_slot_is_refused_rather_than_narrated_into(mode):
    """``incognito`` is refused as firmly as ``persistent``: it still READS the
    player's memory (state.py:2039 — only ``temporary`` blocks reads), so it
    would leak their real life into the story while looking private."""
    state = FakeState()
    state.slots["endless-run-run-1"] = FakeSlot(
        "endless-run-run-1", app=APP_NAME, memory_mode=mode
    )
    with pytest.raises(MemoryModeConflict) as exc:
        ensure_narrator_slot(state, "run-1")
    assert mode in str(exc.value)


def test_there_is_no_fallback_to_an_unsealed_slot():
    """The whole point: a conflict must not degrade into playing anyway."""
    src = inspect.getsource(narrator)
    for banned in ('memory_mode="persistent"', "memory_mode='persistent'", '"incognito"'):
        assert banned not in src.replace(
            '#: player\'s real life, and ``incognito`` still READS memory', ""
        ) or banned == '"incognito"', f"{banned} suggests a fallback path"
    # MEMORY_MODE is the only mode ever passed to a create call.
    assert src.count("MEMORY_MODE") >= 3


def test_core_guard_is_a_second_independent_enforcement_point():
    """If our own check were bypassed, core still refuses (state.py:4501)."""
    state = FakeState()
    state.slots["endless-run-run-1"] = FakeSlot(
        "endless-run-run-1", app=APP_NAME, memory_mode="persistent"
    )
    with pytest.raises(ValueError):
        state.get_or_create_slot(
            name="endless-run-run-1", agent=NARRATOR_AGENT, app=APP_NAME,
            memory_mode=MEMORY_MODE,
        )


# -- run ids --------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["", "../escape", "a/b", "Upper", "-lead", "x" * 49, "run 1", "dashboard:x"]
)
def test_a_malformed_run_id_never_becomes_a_slot_key(bad):
    state = FakeState()
    with pytest.raises(BadRunId):
        narrator_slot_key(bad)
    with pytest.raises(BadRunId):
        ensure_narrator_slot(state, bad)
    assert state.slots == {}, "nothing may be created for a rejected id"


def test_narrator_slots_are_recognisable():
    assert is_narrator_slot(narrator_slot_key("run-1"))
    assert not is_narrator_slot("dashboard-chat-7")
    assert not is_narrator_slot("")


# -- no runtime trust grant ----------------------------------------------


def test_this_app_never_grants_itself_tool_approval():
    """Mirrors spec_builder's test_app_never_grants_worker_trust.

    A backend grant cannot be bounded honestly, so approval-free play is a
    DECLARED allowlist in the packaged agent (which the governance ceiling can
    veto) rather than a runtime stamp.
    """
    src = inspect.getsource(narrator)
    assert "_trust = True" not in src
    assert "_trusted_patterns" not in src.replace(
        "``_trust``, no\n   ``_trusted_patterns``", ""
    ).replace("slot._trust / slot._trusted_patterns", "")


# -- the declared surface -------------------------------------------------


def test_the_narrator_can_reach_nothing_but_this_apps_own_tools():
    """The load-bearing control for R26.

    ``temporary`` blocks memory context injection and consolidation, but a direct
    memory TOOL call is a third path that only this allowlist closes — and the
    prefix that tells the model not to make one is advisory
    (chat_utils.py:1139).
    """
    agent = json.loads(AGENT_JSON.read_text(encoding="utf-8"))
    assert agent["tools"] == [OWN_SERVER_REF]
    for forbidden in (
        "learn_add", "learn_list", "search_chat_history", "get_chat_session",
        "local_knowledge_search", "execute_bash", "fs_write", "fs_read",
        "web_fetch", "@kirocrew-core", "@builder-mcp",
    ):
        assert forbidden not in agent["tools"]
        assert forbidden not in agent["allowedTools"]


def test_auto_approve_is_declared_because_an_unattended_prompt_means_rejected():
    """bridges.py: "A granted server that is only in ``tools`` still prompts for
    every call, which for an unattended app agent resolves to rejected." An
    app-owned slot is unattended until a human drives it through a dashboard-user
    route, so without this the narrator's every call would be denied."""
    agent = json.loads(AGENT_JSON.read_text(encoding="utf-8"))
    assert agent["allowedTools"] == [OWN_SERVER_REF]


def test_the_tool_ref_uses_the_namespaced_key_registration_actually_writes():
    """CORRECTED. An earlier revision of this test asserted the BARE key
    (``@endless-mcp``) and was pinning the wrong rule.

    Registration namespaces every app server: ``namespaced =
    f"{app_name}:{server_name}"`` then ``servers[namespaced] = cfg``
    (bridges.py:2064, :2094). ``_own_mcp_servers`` filters that map by
    ``f"{app_name}:"`` and returns the entries **unrenamed** (bridges.py:549),
    and ``_register_agents`` merges them into the materialized agent's own
    ``mcpServers`` (bridges.py:945-948). kiro-cli resolves ``@x`` against those
    keys, so the namespaced form is the ONLY one that resolves — the bare form is
    dropped SILENTLY at mount time, "no exception and no log line anywhere"
    (bridges.py:_unresolvable_tool_refs).

    ``ref = f"@{name}"`` at bridges.py:426 is a different key space (the per-app
    MCP policy file), not a competing convention.
    """
    agent = json.loads(AGENT_JSON.read_text(encoding="utf-8"))
    manifest = json.loads(APP_JSON.read_text(encoding="utf-8"))

    declared = set(manifest.get("mcpServers") or {})
    assert declared, "app.json must declare the server the agent references"

    for ref in agent["tools"] + agent["allowedTools"]:
        assert ref.startswith("@")
        key = ref[1:]
        app_part, sep, server_part = key.partition(":")
        assert sep, f"{ref} uses the bare key; registration namespaces it"
        assert app_part == manifest["name"], f"{ref} namespaces the wrong app"
        assert server_part in declared, (
            f"{ref} resolves to nothing in app.json mcpServers"
        )


def test_the_apps_own_server_is_launchable_as_an_external_app():
    """`kirocrew app mcp <name>` is BUILTIN-ONLY.

    ``_run_app_mcp_server`` resolves exactly one module name,
    ``f"kiro_crew.apps.builtins.{app}.mcp_server"`` (cli_commands.py:601), and
    exits 1 on ImportError with no external-app fallback. The trap is that
    ``_pin_host_cli_command`` (bridges.py:488) does not check builtin-vs-external
    — it happily rewrites ``command: "kirocrew"`` into a working spawn, so the
    shape LOOKS right and only the dispatch behind it fails, leaving the agent
    with no tools and nothing in any log.

    ``args`` and ``env`` are passed through VERBATIM (no ``${APP_DIR}``, no ``~``
    expansion, no app-root-relative resolution; ``cwd`` is not read at all), so
    an absolute path is a hard requirement. ``command`` is the one field
    rewritten, and only when bare — a bare ``python3`` becomes the app's venv
    interpreter if it has one, else the gateway's own.
    """
    manifest = json.loads(APP_JSON.read_text(encoding="utf-8"))
    spec = manifest["mcpServers"]["endless-mcp"]

    assert spec["command"] == "python3", "bare, so the venv-first rewrite applies"
    assert "url" not in spec, (
        "the url shape needs a live backend port; a backend.hooks-only app is "
        "never tracked in _processes, so registration would skip the entry"
    )
    assert spec["args"] and all(a.startswith("/") for a in spec["args"]), (
        "args are verbatim — a relative path is never resolved"
    )
    for value in (spec.get("env") or {}).values():
        assert value.startswith("/"), "env is verbatim except for PATH"


def test_no_unresolvable_placeholder_token_in_the_agent_file():
    """Placeholder rendering is hard-coded to one app (`pptx-maker`), and an
    unresolved ``{TOKEN}`` makes ``_render_shipped_agent`` return None — the agent
    is then not registered AT ALL, silently."""
    raw = AGENT_JSON.read_text(encoding="utf-8")
    assert not re.search(r"\{[A-Z_]{2,}\}", raw)


def test_the_agent_declares_no_mcp_servers_of_its_own():
    """``_register_agents`` merges ``{**own_servers, **agent_data["mcpServers"]}``
    — the agent's own map WINS, so a hand-written ``endless-mcp`` entry would shadow
    the framework-injected namespaced one and change which key resolves."""
    agent = json.loads(AGENT_JSON.read_text(encoding="utf-8"))
    assert not agent.get("mcpServers")


def test_the_agent_is_registered_in_the_manifest():
    manifest = json.loads(APP_JSON.read_text(encoding="utf-8"))
    agent = json.loads(AGENT_JSON.read_text(encoding="utf-8"))
    assert agent["name"] == NARRATOR_AGENT
    assert "agents" in manifest, "an agent JSON not listed in app.json is never registered"
    assert any(str(a).endswith("narrator.json") for a in manifest["agents"])


def test_the_narrators_prompt_leaks_no_implementation_vocabulary_to_the_player():
    """R25.2 — the prompt tells the narrator to avoid these words, so it may
    name them in a prohibition, but it must not instruct the narrator to SHOW
    them. Checked as: every occurrence sits inside the prohibition sentence."""
    agent = json.loads(AGENT_JSON.read_text(encoding="utf-8"))
    prompt = agent["prompt"]
    prohibition = next(
        (line for line in prompt.split("\n") if "never mention" in line), ""
    )
    assert prohibition, "the prompt must carry an explicit no-implementation-words rule"
    for word in ("schemas", "templates", "contracts", "panels"):
        assert prompt.count(word) == prohibition.count(word), (
            f"{word!r} appears outside the prohibition sentence"
        )


# -- fakes vs the real thing ---------------------------------------------


class TestAgainstRealCore:
    """Pin the two semantics the fakes assume. Skips if core is not importable."""

    @staticmethod
    def _state_mod():
        try:
            from kiro_crew.dashboard import state as state_mod
        except Exception:  # pragma: no cover - environment-dependent
            pytest.skip("kiro_crew.dashboard.state not importable here")
        return state_mod

    def test_valid_memory_modes_still_contains_temporary(self):
        state_mod = self._state_mod()
        assert MEMORY_MODE in state_mod.VALID_MEMORY_MODES

    def test_get_or_create_slot_still_accepts_the_kwargs_we_pass(self):
        """A renamed kwarg would otherwise land as **kw and be silently ignored,
        leaving the slot persistent and unowned."""
        state_mod = self._state_mod()
        sig = inspect.signature(state_mod.DashboardState.get_or_create_slot)
        for param in ("name", "agent", "app", "memory_mode"):
            assert param in sig.parameters, f"core no longer takes {param!r}"

    def test_only_temporary_blocks_memory_reads(self):
        """The reason ``incognito`` is refused. If core ever made incognito block
        reads too, this fails and the refusal can be revisited."""
        state_mod = self._state_mod()
        slot_cls = getattr(state_mod, "_ChatSlot", None)
        if slot_cls is None:  # pragma: no cover
            pytest.skip("_ChatSlot not exposed")
        assert slot_cls("k", memory_mode="temporary").blocks_reads is True
        assert slot_cls("k", memory_mode="incognito").blocks_reads is False
        assert slot_cls("k", memory_mode="persistent").blocks_reads is False

    def test_every_non_persistent_mode_blocks_memory_writes(self):
        state_mod = self._state_mod()
        slot_cls = getattr(state_mod, "_ChatSlot", None)
        if slot_cls is None:  # pragma: no cover
            pytest.skip("_ChatSlot not exposed")
        assert slot_cls("k", memory_mode="temporary").is_restricted is True
        assert slot_cls("k", memory_mode="persistent").is_restricted is False


# -- release on delete ----------------------------------------------------


class FakeRuntime:
    """Mirrors the fields release_narrator_slot touches on core's state: the raw
    ``_slots`` dict, and the two best-effort hooks."""

    def __init__(self) -> None:
        self._slots: dict[str, FakeSlot] = {}
        self.cancelled: list[str] = []
        self.pushed = 0

    def cancel_questions_for_slot(self, key: str) -> None:
        self.cancelled.append(key)

    def _push_slots(self) -> None:
        self.pushed += 1


def test_release_drops_this_apps_slot_and_refreshes():
    rt = FakeRuntime()
    key = narrator_slot_key("run-1")
    rt._slots[key] = FakeSlot(key, app=APP_NAME, memory_mode=MEMORY_MODE)

    assert release_narrator_slot(rt, "run-1") is True
    assert key not in rt._slots, "the deleted life's slot is gone"
    assert rt.cancelled == [key], "its pending question cards are cancelled"
    assert rt.pushed == 1, "the slot list is refreshed"


def test_release_never_removes_a_slot_another_owner_holds():
    rt = FakeRuntime()
    key = narrator_slot_key("run-2")
    rt._slots[key] = FakeSlot(key, app="someone-else", memory_mode=MEMORY_MODE)

    assert release_narrator_slot(rt, "run-2") is False
    assert key in rt._slots, "a slot this app does not own is left alone"


def test_release_is_a_guarded_noop_on_bad_input():
    # No slot present, a runtime without _slots, and a bad run id all no-op rather
    # than raising — a cleanup failure must never fail the deletion.
    assert release_narrator_slot(FakeRuntime(), "run-3") is False
    assert release_narrator_slot(object(), "run-3") is False
    assert release_narrator_slot(FakeRuntime(), "not a run id!!") is False


def test_the_slot_is_created_under_this_app_so_its_origin_is_app():
    """The app passes ``app=APP_NAME`` to get_or_create_slot, which is exactly what
    makes core tag the slot's origin APP rather than USER
    (``slot._origin = origin or (SlotOrigin.APP if app else "")``). Pinning the
    app-side half here keeps that guarantee from silently regressing."""
    state = FakeState()
    ensure_narrator_slot(state, "run-1")
    assert state.create_calls[0]["app"] == APP_NAME


def test_purge_is_a_guarded_noop_without_a_session_store():
    import asyncio

    class NoSessions:
        pass

    assert asyncio.run(narrator.purge_narrator_session(NoSessions(), "run-1")) is False
    assert asyncio.run(narrator.purge_narrator_session(object(), "run-1")) is False


def test_purge_is_a_noop_on_a_bad_run_id():
    import asyncio

    class S:
        sessions = object()

    assert asyncio.run(narrator.purge_narrator_session(S(), "not a run id!!")) is False
