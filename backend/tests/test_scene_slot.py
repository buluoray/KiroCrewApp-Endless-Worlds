"""SceneSlot tests — the frame's identity, its sandbox, and what it accepts.

Regex guards over the TypeScript source (see ``uisrc``): the app has no JS test
runner, so these pin properties that would be silently wrong rather than loudly
broken — an iframe that reloads on every view change still *works*, it just throws
away whatever the player was looking at.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uisrc  # noqa: E402


@pytest.fixture(scope="module")
def slot() -> str:
    if not (uisrc.WEB_SRC / "scene.tsx").is_file():
        pytest.skip("web/src/scene.tsx not present")
    return uisrc.module("scene.tsx")


@pytest.fixture(scope="module")
def ui() -> str:
    if not uisrc.WEB_SRC.is_dir():
        pytest.skip("web/src not present")
    return uisrc.source()


# -- one element, never moved -------------------------------------------


def test_the_slot_is_rendered_at_the_root_outside_every_view_branch(ui: str) -> None:
    """Moving an iframe in the DOM reloads it, so the element must outlive the view
    switch — not just hide/show. Inside PlayPage it would unmount whenever the
    player walked back to the shelf, and a scene would restart on return."""
    root = uisrc.module("main.tsx")
    assert "<SceneSlot" in root, "the slot is not rendered by the root"
    # And nowhere else: a second instance would be a second element.
    assert uisrc.source().count("<SceneSlot") == 1


def test_the_slot_is_hidden_with_display_and_never_destroyed_once_created(
    slot: str, ui: str,
) -> None:
    """The invariant is "never destroyed or moved ONCE IT EXISTS", not "exists from
    the first paint".

    An earlier revision mounted the frame unconditionally, which put a live
    browsing context with allow-scripts into the dashboard's own document for every
    player — including the majority who never see a scene — and the whole dashboard
    went sluggish.

    So the gate has to be a MONOTONIC latch: gating on ``sceneId`` directly would
    destroy the element the moment a scene was dismissed, which is the reload this
    design exists to prevent.
    """
    assert re.search(r"everNeeded \? \(\s*<iframe", slot)
    assert "sceneId ? (" not in slot

    assert "setEverNeeded(true)" in slot
    assert "setEverNeeded(false)" not in slot

    assert ".ew-slot {" in uisrc.styles()
    assert "display: none" in uisrc.styles()
    assert ".ew-slot-on" in uisrc.styles()


def test_the_frame_is_never_re_keyed(slot: str) -> None:
    """A changed ``key`` destroys and recreates the element, which is the same thing
    as moving it."""
    iframe = slot.split("<iframe", 1)[1].split("/>", 1)[0]
    assert "key=" not in iframe


def test_fullscreen_is_the_same_element_promoted_to_a_fixed_overlay() -> None:
    """"Promoted in place": fullscreen toggles the frame's CLASS, never re-parents
    it (a re-parent reloads the scene). Geometry-wise it becomes a FIXED viewport
    overlay at the modal layer (z-index 70), so it sits ABOVE the mobile tab bar —
    which is portaled to <body> as a fixed high-z overlay — instead of behind it.
    An absolute-in-panel scene left its bottom hidden under the tab bar."""
    css = uisrc.styles()
    assert ".ew-slot-full" in css
    full = css.split(".ew-slot-full", 1)[1].split("}", 1)[0]
    assert "position: fixed" in full
    assert "z-index: 70" in full


def test_the_slot_never_becomes_the_scrolling_element() -> None:
    slot_css = uisrc.styles().split(".ew-slot {", 1)[1].split("}", 1)[0]
    assert "overflow: hidden" in slot_css


# -- the sandbox ---------------------------------------------------------


def test_the_sandbox_is_the_dashboards_own_host_values(slot: str) -> None:
    """McpAppFrame's values — the dashboard's existing host for server-compiled
    content — rather than a set invented here."""
    assert 'sandbox="allow-scripts allow-forms"' in slot


def test_same_origin_is_never_granted(ui: str) -> None:
    """With ``allow-same-origin``, srcdoc content shares the dashboard's origin and
    the sandbox stops being one.

    Asserted on the extracted ATTRIBUTE VALUE rather than by scanning the file: the
    comment that explains this rule necessarily contains the forbidden string, so a
    whole-file substring check fails on its own prose.
    """
    values = re.findall(r'sandbox="([^"]*)"', ui)
    assert values, "no sandbox attribute found"
    for value in values:
        assert "allow-same-origin" not in value
        assert "allow-top-navigation" not in value
        assert "allow-modals" not in value


def test_the_scene_is_handed_over_as_srcdoc_not_navigated_to(slot: str) -> None:
    """Nothing here should ever be able to become a top-level page."""
    assert "srcDoc={" in slot
    assert not re.search(r"\bsrc=\{", slot)


# -- what the slot accepts back -----------------------------------------


def test_a_message_must_name_this_app_this_scene_and_a_choice(slot: str) -> None:
    """The frame is null-origin (no ``allow-same-origin``), so ``event.origin`` is
    the string "null". The marker plus the scene identity is what there is, so all
    of these have to be present."""
    assert "e.origin !== 'null'" in slot
    assert "d.source !== 'endless-scene'" in slot
    assert "d.sceneId !== sceneId" in slot
    assert "typeof d.nonce !== 'string'" in slot
    assert "typeof d.choice !== 'string'" in slot


def test_the_message_listener_is_removed_when_the_scene_changes(slot: str) -> None:
    """A listener left behind would answer for a scene that is no longer there."""
    assert "removeEventListener('message'" in slot


def test_the_page_refuses_a_second_result_locally(slot: str) -> None:
    """A double-tap must not become two turns while the server's own refusal is
    still in flight."""
    assert "answered.current" in slot
    assert re.search(r"answered\.current = false", slot)


def test_a_scene_that_will_not_compile_does_not_break_the_page(slot: str) -> None:
    """The turn's words are still there; the narrator gets told which field to fix
    on its next turn."""
    assert ".catch(" in slot
    assert "setFailed(true)" in slot


# -- the built artifact --------------------------------------------------


def test_the_build_keeps_react_external() -> None:
    """The one thing worth asserting about the ARTIFACT rather than the source.

    Bundling React would give this app a SECOND copy of it, and hooks would then
    throw "invalid hook call" from inside a component that looks perfectly
    ordinary — among the least diagnosable failures in the ecosystem.
    """
    if not uisrc.BUILT.is_file():
        pytest.skip("ui/index.mjs not built")
    built = uisrc.BUILT.read_text(encoding="utf-8")
    assert 'from "react"' in built, "react was bundled instead of imported"
    assert "export { EndlessWorlds as default }" in built or "as default }" in built
