"""The phone's page wheel: the sideways iOS-style picker that replaces the fore-edge
slider in the phone layout.

The app has no JS test runner, so these are source contracts (see ``uisrc.py``) plus
a Python mirror of the wheel's pure arithmetic. The real swipe — follow the finger,
coast, snap, one read on rest, only on-screen numbers drawn — runs against a pod in
``devtools/scrub.test.mjs`` at 375px.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from srcguard import code_only  # noqa: E402
from uisrc import module, styles  # noqa: E402


def _src() -> str:
    return code_only(module("page-wheel.tsx"))


def _wheel() -> str:
    s = _src()
    return s[s.index("export function PageWheel(") :]


def _const(name: str) -> float:
    m = re.search(rf"export const {name} = ([\d.]+)", _src())
    assert m, name
    return float(m.group(1))


# The wheel's arithmetic, mirrored from its source and pinned below to that source,
# so the snapping rule can be exercised on numbers here.
def _clamp(n: float, latest: int) -> int:
    # JS Math.round: halves go up.
    return min(latest, max(1, math.floor(n + 0.5)))


def _target(pos: float, velocity: float, latest: int) -> int:
    return _clamp(pos + velocity * _const("WHEEL_TAU_MS"), latest)


def _visible(pos: float, width: float, latest: int) -> tuple[int, int]:
    half = math.ceil(width / 2 / _const("WHEEL_ITEM_PX")) + 1
    c = math.floor(pos + 0.5)
    return max(1, c - half), min(latest, c + half)


def test_the_mirrored_arithmetic_is_the_source_arithmetic():
    s = _src()
    assert "return clampPage(pos + velocity * WHEEL_TAU_MS, latest)" in s
    assert "const half = Math.ceil(widthPx / 2 / WHEEL_ITEM_PX) + 1" in s
    assert "return [Math.max(1, c - half), Math.min(latest, c + half)]" in s
    assert _const("WHEEL_ITEM_PX") >= 44, "a number is a 44px touch target"


def test_a_released_wheel_snaps_to_the_nearest_page():
    # At rest between pages, it snaps to the nearer one, either way.
    assert _target(41.4, 0, 120) == 41
    assert _target(41.6, 0, 120) == 42
    # A flick carries it on in the flick's direction, then snaps.
    assert _target(40.0, 0.02, 120) > 45
    assert _target(40.0, -0.02, 120) < 35
    # Never off the book, however hard the flick.
    assert _target(118, 1.0, 120) == 120
    assert _target(3, -1.0, 120) == 1


def test_a_finger_that_stopped_before_lifting_throws_nothing():
    s = _src()
    vel = s[s.index("export function flickVelocity(") : s.index("export function visiblePages(")]
    assert "now - b.t > 80) return 0" in vel
    assert "Math.max(1, b.t - a.t)" in vel
    end = _wheel()[_wheel().index("const onPointerEnd =") : _wheel().index("const onKeyDown =")]
    assert "glideTo(wheelTarget(posRef.current, velocity, last))" in end
    assert "e.type === 'pointercancel' ? 0" in end


def test_only_the_numbers_on_screen_are_drawn():
    assert _visible(250, 375, 500) == (244, 256), "a 500-page life draws a dozen numbers"
    assert _visible(1, 375, 500) == (1, 7)
    assert _visible(2, 375, 2) == (1, 2)
    w = _wheel()
    assert "const [first, last] = visiblePages(pos, width, latest)" in w
    assert "for (let n = first; n <= last; n++)" in w
    assert "new ResizeObserver(measure)" in w


def test_the_wheel_loads_one_page_when_it_rests_never_while_it_turns():
    w = _wheel()
    move = w[w.index("const onPointerMove =") : w.index("const onPointerEnd =")]
    assert "place(rubber(" in move and "onCommit" not in move and "finish" not in move
    place = w[w.index("const place = useCallback(") : w.index("const finish = useCallback(")]
    assert "store.set(clampPage(p, live.current.latest))" in place and "onCommit" not in place
    glide = w[w.index("const glideTo =") : w.index("const onPointerDown =")]
    # The one load is at the end of the glide, after the last frame.
    assert glide.index("place(target)\n        finish()") > glide.index("if (k < 1)")
    assert "onCommit" not in glide
    fin = w[w.index("const finish = useCallback(") : w.index("const settleSoon =")]
    assert "if (n !== null && n !== live.current.shown) live.current.onCommit(n)" in fin
    assert "store.set(null)" in fin
    # Keys and the mouse wheel load on a pause, like the slider's.
    assert "window.setTimeout(finish, SCRUB_SETTLE_MS)" in w
    assert not re.search(r"\bapi\s*\.", _src()), "the wheel never reads a page itself"
    assert "const preview = useScrubPreview(store)" in w, "the story does not re-render"


def test_the_wheel_is_a_labelled_slider_with_the_slider_keys():
    w = _wheel()
    for attr in (
        'role="slider"',
        "tabIndex={0}",
        "aria-label={t('play.scrubLabel')}",
        'aria-orientation="horizontal"',
        "aria-valuemin={1}",
        "aria-valuemax={latest}",
        "aria-valuenow={value}",
        "aria-valuetext={t('play.scrubValue', { n: value, total: latest })}",
    ):
        assert attr in w, attr
    assert "scrubKey(e.key, store.get() ?? shown, latest)" in w
    assert "aria-live" not in module("page-wheel.tsx"), "StoryPage announces once, on landing"
    for cls in ("ew-wheel-drum", "ew-wheel-hint", "ew-wheel-ribbon"):
        at = w.index(f'className="{cls}"')
        assert 'aria-hidden="true"' in w[at : at + 60], cls


def test_the_phone_gets_the_wheel_and_a_finger_does_not_scroll_the_page():
    assert "export const PHONE_QUERY = '(max-width: 600px)'" in _src()
    play = code_only(module("play.tsx"))
    assert "const phone = usePhoneLayout()" in play
    assert "(phone ? ' ew-topbar-slot-wheel' : ' ew-topbar-slot-scrub')" in play
    css = styles()
    assert re.search(r"\.ew-wheel-track \{[^}]*touch-action: none;", css)
    # The fixed bar's slot grows by the wheel's own row (58px) and the row gap (2px).
    base = re.search(r"\.ew-topbar-slot \{ flex: none; height: (\d+)px; \}", css)
    slot = re.search(r"\.ew-topbar-slot\.ew-topbar-slot-wheel \{ height: (\d+)px; \}", css)
    row = re.search(r"\.ew-wheel \{[^}]*height: (\d+)px;", css)
    assert base and slot and row
    assert int(slot.group(1)) == int(base.group(1)) + int(row.group(1)) + 2


def test_the_wheel_shares_the_folio_and_ticks_only_with_motion_allowed():
    css = styles()
    wheel = re.search(r"\.ew-wheel \{([^}]*)\}", css).group(1)
    tip = re.search(r"\.ew-scrub-tip \{([^}]*)\}", css).group(1)
    for prop in ("background", "font-family"):
        got = re.search(rf"{prop}: ([^;]+);", wheel).group(1)
        assert got == re.search(rf"{prop}: ([^;]+);", tip).group(1), f"same folio {prop}"
    assert "font-style: italic;" in re.search(r"\.ew-wheel-hint \{([^}]*)\}", css).group(1)
    assert re.search(r"\.ew-wheel-n \{[^}]*oldstyle-nums", css)
    assert ".ew-wheel-on .ew-wheel-c .ew-wheel-face { animation: ew-wheel-tick" in css
    reduced = [
        m.group(1)
        for m in re.finditer(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
    ]
    assert any(".ew-wheel-on .ew-wheel-c .ew-wheel-face { animation: none; }" in r for r in reduced)
    assert "reducedMotion() ||" in _wheel(), "reduced motion jumps instead of gliding"
