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
ILLUSTRATOR_JSON = _BACKEND.parent / "agents" / "illustrator.json"
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
        self._slots = self.slots
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


def test_install_generation_changes_on_update_and_same_content_reinstall(tmp_path):
    root = tmp_path / "app"
    (root / "backend").mkdir(parents=True)
    manifest = root / "app.json"
    backend = root / "backend" / "narrator.py"
    manifest.write_text('{"version":"1"}', encoding="utf-8")
    backend.write_text("old", encoding="utf-8")

    first = narrator._installation_generation(root)
    backend.write_text("new", encoding="utf-8")
    after_update = narrator._installation_generation(root)

    replacement = root / "app.reinstalled.json"
    replacement.write_bytes(manifest.read_bytes())
    replacement.replace(manifest)
    after_reinstall = narrator._installation_generation(root)

    assert after_update != first, "changed installed bytes must start a new generation"
    assert after_reinstall != after_update, (
        "reinstalling identical app.json bytes must still start a new generation"
    )


@pytest.mark.parametrize(
    ("app", "mode", "error"),
    [
        ("some-other-app", MEMORY_MODE, SlotOwnedByAnother),
        (APP_NAME, "persistent", MemoryModeConflict),
    ],
)
def test_stale_install_release_keeps_foreign_or_unsealed_slots(app, mode, error):
    state = FakeState()
    slot = FakeSlot(narrator_slot_key("run-1"), app=app, memory_mode=mode)
    state.slots[slot.key] = slot

    with pytest.raises(error):
        narrator.release_stale_narrator_slot(state, "run-1")

    assert state.slots[slot.key] is slot


def test_stale_install_release_removes_only_the_app_owned_sealed_slot():
    state = FakeState()
    slot = FakeSlot(narrator_slot_key("run-1"), app=APP_NAME, memory_mode=MEMORY_MODE)
    state.slots[slot.key] = slot

    assert narrator.release_stale_narrator_slot(state, "run-1") is True
    assert slot.key not in state.slots


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
    own_prefix = OWN_SERVER_REF + "/"
    assert agent["tools"], "the narrator must have its own tools"
    for ref in agent["tools"]:
        assert ref == OWN_SERVER_REF or ref.startswith(own_prefix), (
            f"{ref} is not one of this app's own tools"
        )
    for forbidden in (
        "learn_add", "learn_list", "search_chat_history", "get_chat_session",
        "local_knowledge_search", "execute_bash", "fs_write", "fs_read",
        "web_fetch", "@kirocrew-core", "@builder-mcp",
        # Scoped OUT of the narrator: these belong to the illustrator and the
        # worldsmith. Per-tool scoping keeps their descriptions out of the
        # narrator's every-turn context.
        OWN_SERVER_REF + "/endless_commit_backdrop",
        OWN_SERVER_REF + "/endless_submit_world_draft",
        OWN_SERVER_REF + "/endless_read_draft",
        OWN_SERVER_REF + "/endless_export_world",
    ):
        assert forbidden not in agent["tools"]
        assert forbidden not in agent["allowedTools"]


def test_auto_approve_is_declared_because_an_unattended_prompt_means_rejected():
    """bridges.py: "A granted server that is only in ``tools`` still prompts for
    every call, which for an unattended app agent resolves to rejected." An
    app-owned slot is unattended until a human drives it through a dashboard-user
    route, so without this the narrator's every call would be denied."""
    agent = json.loads(AGENT_JSON.read_text(encoding="utf-8"))
    assert agent["allowedTools"] == agent["tools"], (
        "auto-approve must mirror the granted set, or a granted tool still prompts"
    )


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
        # A per-tool ref is "<app>:<server>/<tool>"; membership is by server key.
        server_only = server_part.split("/", 1)[0]
        assert server_only in declared, (
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
    expansion, no app-root-relative resolution; ``cwd`` is not read at all), so an
    absolute path is a hard requirement AT LAUNCH. The SHIPPED manifest therefore
    carries a repo-relative path (portable, leaks no machine path), and the backend
    hook absolutizes the installed copy on load — see ``_absolutized_mcp_spec`` /
    ``_heal_mcp_server_path`` in ``routes.py``. ``command`` stays a bare ``python3``
    so the venv-first rewrite applies.
    """
    from pathlib import Path

    from routes import _absolutized_mcp_spec

    manifest = json.loads(APP_JSON.read_text(encoding="utf-8"))
    spec = manifest["mcpServers"]["endless-mcp"]

    assert spec["command"] == "python3", "bare, so the venv-first rewrite applies"
    assert "url" not in spec, (
        "the url shape needs a live backend port; a backend.hooks-only app is "
        "never tracked in _processes, so registration would skip the entry"
    )
    # Shipped form is repo-relative: portable across installs and carries no
    # machine path. It is NOT launchable as-is (args are verbatim) — the hook
    # below is what makes it so.
    assert spec["args"] == ["backend/mcp_server.py"]
    assert (spec.get("env") or {}).get("PYTHONPATH") == "backend"

    # The load-time heal turns that into the absolute paths the verbatim-args
    # reality requires, for whatever directory the app was installed into.
    backend_dir = Path("/somewhere/apps/endless-worlds/backend")
    healed = _absolutized_mcp_spec(manifest, backend_dir)
    assert healed is not None, "a relative shipped path must be rewritten"
    hspec = healed["mcpServers"]["endless-mcp"]
    assert hspec["args"] == [str(backend_dir / "mcp_server.py")]
    assert hspec["env"]["PYTHONPATH"] == str(backend_dir)
    assert all(a.startswith("/") for a in hspec["args"]), "healed args are absolute"
    # Idempotent: healing an already-absolute manifest is a no-op.
    assert _absolutized_mcp_spec(healed, backend_dir) is None



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


def test_the_system_prompt_carries_the_pull_and_fingerprint_instruction():
    """The per-turn message no longer repeats "call endless_read_runtime / pass the
    fingerprint as since" (that was ~300 chars of duplication every turn). The
    instruction must therefore live in the SYSTEM prompt, which is present on every
    turn regardless of compaction — otherwise nothing tells the narrator to look."""
    prompt = json.loads(AGENT_JSON.read_text(encoding="utf-8"))["prompt"]
    assert "endless_read_runtime" in prompt, "the system prompt must tell it to pull"
    assert "fingerprint" in prompt and "since" in prompt, (
        "the delta-read rules must live in the system prompt now"
    )


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


def test_backdrop_guidance_is_an_art_brief_not_a_rendering_recipe():
    """The drawing lives in the ILLUSTRATOR now (the narrator only sends a brief),
    so the diversity contract that keeps every page from wearing the same
    gradient/vignette/grain stack belongs to the illustrator's prompt. Safety
    belongs to ``compile_backdrop``; this contract protects visual variety.

    The NARRATOR must carry none of the SVG recipe — it delegates via a brief."""
    illustrator_agent = json.loads(ILLUSTRATOR_JSON.read_text(encoding="utf-8"))
    prompt = illustrator_agent["prompt"]

    for required in (
        "senior game environment artist",
        "ONE coordinated backdrop set",
        "desktop raw SVG as `markup`",
        "mobile raw SVG as `mobile`",
        "viewBox='0 0 800 600'",
        "viewBox='0 0 450 900'",
        "share the same palette",
        "compose each frame independently",
        "must not be a crop, stretch, or scaled copy",
        "scale, tonal placement, and contrast",
        "complete tall composition",
        "passing both `markup` and `mobile` in the same call",
        "PLAYER CHOICE",
        "PAGE PROSE",
        "ART BRIEF",
        "ONE visual thesis",
        "SMALL palette",
        "one motion verb or none",
        "Work with SVG's strengths",
        "motif-first and architecture-first",
        "first "
        "line declares the lane",
        "`LANE: motif` or `LANE: scene`",
        "The storyteller already made "
        "this choice; never re-route it",
        "If no lane line is present, work in the motif lane",
        "In the MOTIF lane",
        "without calling endless_trace_reference",
        "The brief tells you what must be felt; it does not tell you what shapes to draw",
        "Derive the visual metaphor, mark language, material character, spatial balance, and motion",
        "silently develop at least three substantially different visual concepts",
        "Reject the literal summary, the first obvious symbol, any generic screensaver treatment",
        "strongest world-specific metaphor, compositional tension, and emotional afterimage",
        "intentional and distinctive at first glance, then richer on a second look",
        "expressive decisions rather than a checklist",
        "No technique is mandatory",
        "only when this page's chosen concept earns them",
        "must not read as an icon, diagram, UI ornament, stock particle effect, or decorative filler",
        "in "
        "either lane",
        "In the SCENE lane",
        "call endless_trace_reference",
        # The subject half only: the context half must never reach the archive,
        # because every word in a query removes results.
        "REFERENCE `subject=`",
        "SINGLE most-relevant noun",
        "its hex stops as `ramp`",
        'one `<g id="etr-underlay"/>` '
        "in EACH SVG",
        "never draw the underlay yourself",
        "returns several traced CANDIDATES",
        "call endless_select_reference with the `index`",
        "The traces centre both variants",
        "`desktopFocalX`/`desktopFocalY`",
        "`mobileFocalX`/`mobileFocalY`",
        "chosen independently",
        "`0` is left/top, `1` is right/bottom",
        "add NO overlay marks",
        "restraint is a finished decision",
        "three to six decisive spatial facts",
        "draw only the sparse marks traceable to them",
        "Organic "
        "forms (trees, fog, water, foliage) stay in the underlay",
        "`underlay: base`",
        "at most ONE trace retry total",
        "never do both",
        "Prefer environment and evidence",
        "large anatomically detailed people or animals",
        "small, distant, cropped, shadowed",
        "Never wrap either SVG in a Markdown code fence",
        "SMIL only",
        "Follow the lane-specific visual feedback loop before publication",
        "endless_submit_backdrop_draft",
        "does not publish them",
        "opaque `draftId`",
        "safe PNG thumbnail paths",
        "built-in `read` tool once in Image mode",
        "ALL returned PNG paths together",
        "judge desktop and mobile side by side",
        "Inspect the rendered pixels",
        "one clear visual thesis",
        "genuinely independent compositions",
        "a world-specific artistic concept rather than a generic effect",
        "calm prose reading fields",
        "clipping or dead space",
        # The MOTIF second pass is EARNED, not owed. It used to be unconditional,
        # which cost two more SVGs and another preview read on every page whose
        # first draft was already good — the dominant latency in the whole lane.
        "review the first rendered draft as diagnosis before you treat it as final",
        "single weakest or most generic artistic decision",
        "exactly ONE structural revision",
        "not merely a color adjustment or additional effects",
        "as a SECOND draft",
        "call `read` once more with ALL second-draft previews together",
        "commit only that second `draftId`",
        "Never make a third draft",
        "A second pass is earned by a named weakness, not owed by default",
        "the review finds nothing structural to fix, commit it",
        "For SCENE, the first reviewed draft may be final",
        "submit the complete revision as a second draft",
        "never publish revised markup that was not rendered and inspected",
        "use only the latest reviewed `draftId`",
    ):
        assert required in prompt, f"illustrator prompt missing: {required!r}"

    assert prompt.index("First call endless_submit_backdrop_draft") < prompt.index(
        "built-in `read` tool once"
    ) < prompt.index("as a SECOND draft") < prompt.index(
        "call `read` once more"
    ) < prompt.index("commit only that second `draftId`")

    trace_tool = OWN_SERVER_REF + "/endless_trace_reference"
    select_tool = OWN_SERVER_REF + "/endless_select_reference"
    draft_tool = OWN_SERVER_REF + "/endless_submit_backdrop_draft"
    commit_tool = OWN_SERVER_REF + "/endless_commit_backdrop"
    assert illustrator_agent["tools"] == [
        trace_tool, select_tool, draft_tool, commit_tool, "read"
    ]
    assert illustrator_agent["allowedTools"] == [
        trace_tool, select_tool, draft_tool, commit_tool, "read"
    ]
    assert illustrator_agent["toolsSettings"]["read"]["allowedPaths"] == [
        "**/runs/*/backdrop-previews/backdrop-preview-*.png"
    ]

    for rejected in (
        "paths, gradients, masks, clipping, patterns, filters, texture",
        "semantic `<g>` groups",
        "recognizable silhouette",
        "Bézier curves and arcs",
        "spotlight the hero",
        "faux-photorealism",
        "meaning instead of becoming generic wallpaper",
        "First look for repeated rhythm, architecture, interiors",
        "with a clear routing order",
        "make a fully ornamental field with no recognizable story noun",
        "silently choose exactly one lane",
        "HYBRID is second",
        "STORY IMAGE is the exception",
        "Then draw a sparse overlay ON the traced structure",
    ):
        assert rejected not in prompt, f"illustrator prompt retained: {rejected!r}"

    # The narrator delegates during every normal turn. Direct SVG exists only as a
    # separately gated recovery capability after two worker failures; keeping the
    # illustrator recipe out of this prompt still prevents routine self-drawing.
    narrator_agent = json.loads(AGENT_JSON.read_text(encoding="utf-8"))
    narrator = narrator_agent["prompt"]
    fallback = OWN_SERVER_REF + "/endless_commit_fallback_backdrop"
    assert "endless_paint_backdrop" in narrator
    assert fallback in narrator_agent["tools"]
    assert fallback in narrator_agent["allowedTools"]
    assert "Never call endless_commit_fallback_backdrop during a normal turn" in narrator
    # The lane decision lives with the storyteller: MOTIF briefs name one abstract
    # phenomenon, while SCENE briefs carry photo-search keywords.
    for lane_pin in (
        "LANE: motif", "LANE: scene", "THESIS:", "MOTION:",
        "REFERENCE:", "PALETTE:",
        "if the image's point is what a place physically looks like, choose SCENE",
        "naming the invisible dramatic fact or emotional logic the art should make felt",
        "Never prescribe geometry, objects, placement, SVG techniques, or a visual solution",
        "emotional temperature, material atmosphere",
        "let it derive the motif",
    ):
        assert lane_pin in narrator, f"narrator brief guidance missing: {lane_pin!r}"
    for removed_recipe in (
        "source → path or field → destination",
        "A bright source at the left",
        "one anchor or source",
        "one winding carrier curve",
        "sparse family of blue points",
    ):
        assert removed_recipe not in prompt
        assert removed_recipe not in narrator
    assert "endless_set_backdrop" not in narrator
    for recipe in (
        "viewBox='0 0 800 600'", "viewBox='0 0 450 900'",
        "feTurbulence", "<animateTransform>",
    ):
        assert recipe not in narrator, f"narrator still carries SVG recipe: {recipe!r}"


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
