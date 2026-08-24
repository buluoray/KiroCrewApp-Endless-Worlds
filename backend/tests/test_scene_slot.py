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
    slot: str,
    ui: str,
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


def test_the_scene_has_no_fullscreen_affordance() -> None:
    """Fullscreen was removed. As a fixed overlay it covered the crew dashboard's own
    chrome on desktop; as an in-panel absolute box it sat under the mobile tab bar.
    Neither geometry worked, and a map/ledger reads fine inline — so the scene
    renders in the panel only, with no zoom control."""
    slot = uisrc.module("scene.tsx")
    css = uisrc.styles()
    assert "ew-slot-full" not in slot and "ew-slot-full" not in css
    assert "setFull" not in slot and "zoomIn" not in slot and "zoomOut" not in slot


def test_the_slot_never_becomes_the_scrolling_element() -> None:
    slot_css = uisrc.styles().split(".ew-slot {", 1)[1].split("}", 1)[0]
    assert "overflow: hidden" in slot_css


# -- the frame is as tall as its picture --------------------------------


def test_the_frame_is_sized_from_the_documents_own_report(slot: str) -> None:
    """One fixed height for every spec is wrong in both directions: a short ledger
    sits in a dead band, and a map taller than the frame has its last row clipped
    with no way to reach it (the slot never scrolls, by the rule above).

    The frame has an opaque origin, so the host cannot measure inside it — the
    document reports its own height and the host applies it, clamped.
    """
    assert re.search(r"typeof d\.height === 'number'", slot)
    assert "Number.isFinite(d.height)" in slot
    assert "setFitH(" in slot
    # Applied to the element, and clamped rather than trusted.
    assert re.search(r"height: `\$\{fitH\}px`", slot)
    assert "MIN_SCENE_H" in slot and "MAX_SCENE_H" in slot
    assert re.search(r"Math\.min\(MAX_SCENE_H, Math\.max\(MIN_SCENE_H,", slot)
    # The stylesheet keeps a fallback for the frame that has not reported yet.
    assert re.search(r"\.ew-slot-on \{[^}]*height: \d+px", uisrc.styles())


def test_a_height_report_is_not_an_answer(slot: str) -> None:
    """A height message carries no choice and must not travel the answer path: it
    arrives whenever the picture resizes, including while a turn is in flight, so
    treating it as an answer would either fire a turn or trip the local
    first-result latch and leave the slot stuck on "sending…"."""
    body = slot.split("const onMessage", 1)[1]
    height_at = body.index("d.height")
    choice_at = body.index("typeof d.choice")
    assert height_at < choice_at, "the height branch must precede the answer guards"
    latch_at = body.index("answered.current")
    assert height_at < latch_at, "a height report must not reach the answer latch"


def test_the_slot_surface_does_not_follow_the_dashboard_theme() -> None:
    """The frame is read on the world's own art, never on the host's palette.

    Resolved against a LIGHT dashboard theme, `var(--card)`/`var(--border)` are white,
    which painted a pale slab behind the scene. The frame is now FROSTED rather than
    opaque — a fixed dark scrim at partial alpha plus a blur, so the world's backdrop
    tints it — but the rule that matters is unchanged and stated the same way: no host
    theme variable decides this surface. The contrast that alpha has to keep is
    computed in ``tests/test_widget_contrast.py``.
    """
    slot_css = uisrc.styles().split(".ew-slot {", 1)[1].split("}", 1)[0]
    # Comments stripped first: the comment that explains this rule necessarily
    # names the forbidden variables, so a raw substring check fails on its own prose
    # (the same trap `test_same_origin_is_never_granted` documents).
    decls = re.sub(r"/\*.*?\*/", "", slot_css, flags=re.S)
    assert "var(--card" not in decls and "var(--border" not in decls
    found = re.search(r"background:\s*rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)", decls)
    assert found, "the slot's scrim is not a fixed rgba colour: " + decls
    red, green, blue, alpha = (float(v) for v in found.groups())
    assert max(red, green, blue) < 60, "the scrim is not dark, so bright art decides legibility"
    assert 0.3 <= alpha < 1.0, f"scrim alpha {alpha} is outside the frosted range"
    assert re.search(r"(?:^|\s)backdrop-filter:\s*[^;]*blur", decls), (
        "the slot has no backdrop blur, so sharp art competes with the text on it"
    )


def test_the_scene_frames_clear_the_phones_tab_bar() -> None:
    """The frames render after the shell, outside it, so the shell's own bottom
    padding does not reach them and the bar (fixed, portalled) covered the last
    frame. The clearance goes to whatever the page ENDS with: when frames follow the
    region pane the pane drops its own, or the gap merely opens between the panels
    and the map.
    """
    root = uisrc.module("main.tsx")
    css = uisrc.styles()
    assert re.search(r"\.ew-scenes-clear \{[^}]*padding-bottom: 72px", css)
    assert "scenesShown ? 'ew-scenes-clear'" in root
    assert "paddingBottom: scenesShown ? undefined : '72px'" in root


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


def test_the_scene_is_loaded_as_a_sandboxed_src_document(slot: str) -> None:
    """The scene ROUTE is the primary form: a real same-origin document, never a
    ``blob:`` URL (which fails the load in a WebKit-based in-app browser and takes
    the page down with it).

    ``srcdoc`` is present but only as the watchdog's fallback, and this pins that it
    stays subordinate: it is gated on the ``inline`` state, so a fresh document is
    always attempted over the route first. Security is unchanged in either form — the
    frame keeps its sandbox with no allow-same-origin (asserted separately), so the
    document is null-origin and cannot reach the dashboard.
    """
    assert re.search(r"\bsrc=\{src\}", slot), "scene must load via src"
    assert "createObjectURL" not in slot, "blob: crashes a WebKit in-app browser"
    # The fallback is conditional, never the unconditional source of the document.
    assert re.search(r"srcDoc=\{inline && on \? html : undefined\}", slot), (
        "srcdoc must be gated on the fallback state, not the primary form"
    )
    assert re.search(r"const src = inline \? undefined : routeSrc", slot), (
        "the route form must be what a fresh document is tried with first"
    )


def test_a_frame_that_never_ran_falls_back_before_it_reports_failure(slot: str) -> None:
    """The watchdog escalates; it does not dead-end.

    A frame that misses the deadline has not run — an SSO proxy's own sign-in page in
    place of our document, an auth refusal, a JSON body, an embedder that refused the
    URL. The app already holds the bytes (it fetched them itself, and that fetch is
    authenticated by the app rather than by the browser), so the first miss switches
    the frame to those bytes. Only a second miss is a real failure the player is told
    about. Reporting the first one was the bug this replaces: behind an SSO tunnel the
    route form NEVER runs, so the note was permanent while the document sat in hand.
    """
    assert "inline ? setFailed(true) : setInline(true)" in slot, (
        "the first missed deadline must fall back, not fail"
    )


def test_the_fallback_is_per_document_and_not_a_session_latch(slot: str) -> None:
    """Reset on new bytes, so one refused navigation cannot pin every later scene to
    ``srcdoc`` — including on the surfaces where only the route form renders."""
    assert re.search(r"setInline\(false\)\s*\n\s*\}, \[routeSrc\]\)", slot), (
        "the fallback must reset when the document changes"
    )


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
