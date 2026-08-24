"""Guards on where a scene frame's document comes from, and on what it is allowed.

Three forms have been tried, and the choice is decided by which surfaces render:

* ``srcdoc`` blank-renders in WebKit / iOS WKWebView (observed: an empty box where
  the local map belongs).
* ``blob:`` renders in Chromium, and in an iOS WKWebView shell fails the load with
  "invalid url or response" and takes the whole page down (observed on a real
  device). A blob URL is not a form every embedder resolves.
* The scene ROUTE renders on both, and is what these tests hold.

The route was withdrawn once on the theory that the frame's own document navigation
was answered with an auth refusal the app could not see. That theory was wrong: the
frame's request returns 200 (measured — each scene appears twice in a shot's request
log, once for the app's fetch and once for the frame's), and the empty ledger it was
blamed for came from a stale compiled-bytes cache, fixed by the compiler-version
bump that shipped alongside it.

What the route does cost is real, though: the frame owns that response, so a refusal
or a shell instead of our document would leave a blank frame and the app — holding
valid html — would believe the scene was fine. That hole is closed by a WATCHDOG, not
by avoiding the request: the document reports its own height when it runs, so no
report by the deadline means it did not render. These tests hold the route, the
watchdog, and the boundary neither may cost.
"""

from __future__ import annotations

import re

from uisrc import module


def test_the_frame_loads_the_scene_route_as_a_document() -> None:
    src = module("scene.tsx")
    assert "/scenes/" in src and "${API}" in src, (
        "the scene frame no longer addresses the scene route; srcdoc and blob: are "
        "both known to fail on a WebKit shell, so a plain document URL is the only "
        "form observed to render on every surface this app runs on"
    )
    frame = re.search(r"<iframe(.*?)/>", src, re.S)
    assert frame and "src={src}" in frame.group(1), (
        "the frame is not loading from the computed route src"
    )


def test_the_frame_does_not_go_back_to_a_blob_document() -> None:
    """The regression this file exists to prevent, named as itself.

    A blob: frame renders fine in Chromium, which is exactly why it can be
    reintroduced by someone testing only there — and it takes an iOS WKWebView shell
    down with the page, which no CI lane covers.
    """
    src = module("scene.tsx")
    assert "createObjectURL" not in src, (
        "the scene frame is a blob: document again — it renders in Chromium and "
        "crashes an iOS WKWebView shell, and no lane here would catch it"
    )
    assert "srcdoc" not in re.sub(r"(?s)/\*.*?\*/|//[^\n]*", "", src), (
        "the scene frame uses srcdoc, which blank-renders on WebKit"
    )


def test_a_frame_that_never_renders_reports_itself() -> None:
    """Without this the slot sits blank at the fallback height and says nothing.

    The watchdog is what makes the route's unobservable response observable: it turns
    "no height reported" into a fallback and, failing that, the note the player
    already has a string for.
    """
    src = module("scene.tsx")
    # The deadline is DERIVED, not declared: a constant cannot be right for both a
    # path where the route form never works (short is kind) and one where the
    # fallback blank-renders (short pre-empts a working navigation). It scales off
    # the app's own fetch of the same document, which is the one measurement of that
    # path the app already has.
    assert "renderDeadlineMs(fetchMs)" in src, (
        "the deadline must be derived from the measured fetch, not a fixed constant"
    )
    assert re.search(r"setFetchMs\(performance\.now\(\) - startedAt\)", src), (
        "nothing measures the fetch the deadline is derived from"
    )
    bounds = {
        name: int(m.group(1))
        for name in ("SCENE_RENDER_DEADLINE_MIN_MS", "SCENE_RENDER_DEADLINE_MAX_MS")
        if (m := re.search(rf"{name}\s*=\s*(\d+)", src))
    }
    assert len(bounds) == 2, "the derived deadline is not bounded at both ends"
    lo, hi = bounds["SCENE_RENDER_DEADLINE_MIN_MS"], bounds["SCENE_RENDER_DEADLINE_MAX_MS"]
    assert 300 <= lo < hi <= 6000, (
        f"the deadline band is {lo}..{hi}ms; too low a floor pre-empts a working "
        "navigation on the surface where the fallback blank-renders, and too high a "
        "ceiling restores the silent blank frame the watchdog exists to prevent"
    )
    # The timer must actually be able to mark the scene failed, and must be cleared
    # once a height arrives — a latched failure would stick after a slow first paint.
    assert "setFailed(true)" in src, "the deadline does not lead to setFailed(true)"
    assert "clearTimeout" in src, "the watchdog is never cleared, so it cannot be cancelled"


def test_the_frame_never_paints_a_document_it_has_not_vouched_for() -> None:
    """What a loading frame paints is not the app's choice, so it paints nothing.

    Behind an SSO proxy the refused navigation renders the proxy's own white sign-in
    page, mid-story, for as long as the probe runs — the report was "白" before the
    scene appeared. The frame is therefore transparent until its height report proves
    it ran OUR document, with a placeholder standing in its space.

    ``opacity``, never ``display``: the document has to load and lay out to report a
    height at all, and ``display:none`` would zero the very measurement being waited
    for — turning the wait into a permanent one.
    """
    src = module("scene.tsx")
    assert re.search(r"const waiting = on && !fitH && !failed", src), (
        "nothing defines the window in which the frame has not yet vouched for itself"
    )
    assert re.search(r"waiting\s*\n?\s*\?\s*\{ opacity: 0, pointerEvents: 'none' \}", src), (
        "the frame must be transparent, and inert, until it reports a height"
    )
    assert re.search(r"\{waiting \? <div className=\"ew-slot-wait\"", src), (
        "nothing stands in the frame's place while it is invisible"
    )
    # The guard above is only sound while the hidden frame still lays out.
    assert not re.search(r"waiting[^\n]*display: 'none'", src), (
        "hiding the waiting frame with display would zero the height report it is "
        "waiting for, and the wait would never end"
    )


def test_the_sandbox_and_the_origin_check_are_unchanged() -> None:
    """The document's LOAD form has changed twice; its trust level never may.

    Without allow-same-origin the document's origin is opaque, which is what makes
    ``e.origin !== 'null'`` a real check rather than a formality — a message carrying
    any real origin did not come from the sandbox. Both halves have to stay, and they
    only mean something together.
    """
    src = module("scene.tsx")
    sandbox = re.search(r'sandbox="([^"]*)"', src)
    assert sandbox, "the scene frame lost its sandbox attribute"
    flags = sandbox.group(1).split()
    assert set(flags) == {"allow-scripts", "allow-forms"}, (
        f"the scene frame's sandbox flags changed to {flags!r}; allow-same-origin in "
        "particular would give the document the dashboard's origin and its DOM"
    )
    assert "e.origin !== 'null'" in src, (
        "the message handler no longer requires an opaque origin, so any frame on the "
        "page could answer for a scene"
    )
