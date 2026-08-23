"""Guards on where a scene frame's document comes from, and on what it is allowed.

A scene's picture is fetched once, by the app, over a request whose failure the app
can SEE (``api.scene`` throws on any non-2xx and the slot says "failed"). Pointing
the frame's ``src`` at the same route threw those bytes away and asked for them a
second time — as a document navigation, authenticated by whatever the browser chose
to attach to it, and answered to nobody: the frame owns that response, the app never
reads it. Whenever it came back as anything but our document, the result was a blank
frame at the stylesheet's fallback height and no error on any surface, because the
app had its html and believed the scene was fine.

So the frame is fed the bytes already in hand, as a blob: document. These tests hold
that shape, and hold the boundary it must not cost: the sandbox still withholds
allow-same-origin (so the document's origin stays opaque and its postMessage origin
is the string "null"), and the handler still checks exactly that.
"""

from __future__ import annotations

import re

from uisrc import module


def test_the_frame_renders_the_bytes_the_app_already_fetched() -> None:
    src = module("scene.tsx")
    assert "URL.createObjectURL" in src, (
        "the frame is not built from the fetched bytes; a second request for the same "
        "document is a failure the app cannot see"
    )
    assert "URL.revokeObjectURL" in src, "each blob document must be released"
    # The blob is built from the fetched html, not from anything else.
    made = re.search(r"URL\.createObjectURL\(new Blob\(\[(\w+)\]", src)
    assert made and made.group(1) == "html", (
        "the blob must carry the fetched html itself, not a re-derived value"
    )


def test_the_frame_never_points_at_the_scene_route() -> None:
    """The route still exists — ``api.scene`` uses it, and a directly navigated scene
    keeps its response headers. What must not come back is the FRAME depending on it."""
    src = module("scene.tsx")
    frame = re.search(r"<iframe(.*?)/>", src, re.S)
    assert frame, "no scene frame in scene.tsx"
    assert "${API}" not in src and "/scenes/" not in src, (
        "the frame is addressing the scene route again — that is the second, "
        "unobservable request this fix removed"
    )


def test_the_sandbox_and_the_origin_check_are_unchanged() -> None:
    """The blob document is a different LOAD, not a different trust level.

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
