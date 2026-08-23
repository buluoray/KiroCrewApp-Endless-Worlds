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
    "no height reported" into the failure note the player already has a string for.
    """
    src = module("scene.tsx")
    assert "SCENE_RENDER_DEADLINE_MS" in src, (
        "no render deadline: a frame whose document never ran leaves a silent blank "
        "slot, which is the failure mode that cost two rounds of guessing"
    )
    deadline = re.search(r"SCENE_RENDER_DEADLINE_MS\s*=\s*(\d+)", src)
    assert deadline, "the render deadline is not a declared constant"
    ms = int(deadline.group(1))
    assert 2000 <= ms <= 15000, (
        f"the render deadline is {ms}ms; too short flashes a false failure on a cold "
        "instance, too long restores the silent blank frame it exists to prevent"
    )
    # The timer must actually be able to mark the scene failed, and must be cleared
    # once a height arrives — a latched failure would stick after a slow first paint.
    watchdog = re.search(r"setTimeout\(\(\) => setFailed\(true\), SCENE_RENDER_DEADLINE_MS\)", src)
    assert watchdog, "the deadline does not lead to setFailed(true)"
    assert "clearTimeout" in src, "the watchdog is never cleared, so it cannot be cancelled"


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
