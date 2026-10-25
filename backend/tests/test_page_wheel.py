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
    for cls in ("ew-wheel-drum", "ew-wheel-ribbon"):
        at = w.index(f'className="{cls}"')
        assert 'aria-hidden="true"' in w[at : at + 60], cls


def _play() -> str:
    return code_only(module("play.tsx"))


def _phone_bar() -> str:
    p = _play()
    return p[p.index("const phoneBar = phone ? (") : p.index("const pager =")]


def test_the_phone_gets_the_wheel_and_a_finger_does_not_scroll_the_page():
    assert "export const PHONE_QUERY = '(max-width: 600px)'" in _src()
    play = _play()
    assert "const phone = usePhoneLayout()" in play
    assert "(phoneBar ? ' ew-topbar-wheel' : '')" in play
    css = styles()
    assert re.search(r"\.ew-wheel-track \{[^}]*touch-action: none;", css)
    # The wheel shares the back link's 44px row, so the fixed bar's slot does not grow.
    assert "ew-topbar-slot-wheel" not in play and "ew-topbar-slot-wheel" not in css
    assert "(scrubber ? ' ew-topbar-slot-scrub' : '')" in play
    for sel in (r"\.ew-wheel-bar", r"\.ew-wheel", r"\.ew-wheel-track"):
        body = re.search(sel + r" \{([^}]*)\}", css).group(1)
        assert "height: 44px;" in body, sel


def test_a_phone_has_no_pager_buttons_only_the_wheel_beside_the_back_link():
    play = _play()
    pager = play[play.index("const pager =") : play.index("const main = (")]
    assert pager.startswith("const pager =\n    latest >= 1 && !phone ? ("), "no pager on a phone"
    scrubber = play[play.index("const scrubber =") : play.index("const phoneBar =")]
    assert "latest >= 2 && !phone ? (" in scrubber, "no fore-edge on a phone"
    bar = _phone_bar()
    assert "<PageWheel" in bar
    for gone in ("<HoldArrow", "t('play.firstTurn')", "t('play.prevTurn')", "t('play.nextTurn')"):
        assert gone not in bar, gone
    # One row: the back link, then the wheel bar, in the same top bar.
    top = play[play.index("'ew-topbar' +") :]
    assert top.index("className=\"ew-back\"") < top.index("{phoneBar}")
    css = styles()
    row = re.search(r"\.ew-topbar\.ew-topbar-wheel \{([^}]*)\}", css).group(1)
    assert "flex-wrap: nowrap;" in row


def test_the_back_link_stays_on_one_line_and_the_wheel_shrinks_instead():
    css = styles()
    back = re.search(r"\.ew-topbar\.ew-topbar-wheel \.ew-back \{([^}]*)\}", css).group(1)
    assert "white-space: nowrap;" in back
    assert "flex: none;" in back, "the link never shrinks"
    assert "min-width: max-content;" in back
    # It outranks the narrow-screen rule that let the old link wrap (0,2,0).
    assert ".ew-topbar .ew-back { min-width: 0; flex: 1; white-space: normal; }" in css
    for sel in (r"\.ew-wheel-bar", r"\.ew-wheel"):
        body = re.search(sel + r" \{([^}]*)\}", css).group(1)
        assert "flex: 1 1 auto;" in body and "min-width: 0;" in body, f"{sel} shrinks"


def test_the_wheel_has_no_action_line():
    assert "ew-wheel-hint" not in module("page-wheel.tsx")
    assert "ew-wheel-hint" not in styles()
    assert "loadPageIndex" not in _src(), "the wheel no longer reads the page index"


def test_the_wheel_has_no_background_panel():
    css = styles()
    for sel in (r"\.ew-wheel", r"\.ew-wheel-track", r"\.ew-wheel-bar"):
        body = re.search(sel + r" \{([^}]*)\}", css).group(1)
        assert not re.search(r"(?:^|[;\s])background(?:-color)?:", body), sel
        assert "box-shadow:" not in body and "border:" not in body, sel
    assert re.search(r"\.ew-wheel-c \{[^}]*color: var\(--text,", css), "the centre in canvas ink"
    assert re.search(r"\.ew-wheel-n \{[^}]*color: var\(--muted,", css)
    # The ribbon still marks the centre.
    w = _wheel()
    assert '<span className="ew-wheel-ribbon" aria-hidden="true" />' in w


def test_the_mark_at_the_wheels_end_goes_back_to_the_live_page():
    bar = _phone_bar()
    at = bar.index('className="ew-wheel-latest"')
    btn = bar[at : bar.index("</button>", at)]
    assert "aria-label={t('play.latestTurn')}" in btn, "named for a screen reader"
    assert "disabled={isLive}" in btn
    assert "onClick={() => setViewTurn(null)}" in btn, "Latest is the LIVE page"
    assert bar.index("</PageWheel>") < at, "at the wheel's end"


def test_a_tap_on_the_centre_number_opens_the_type_a_number_picker():
    w = _wheel()
    end = w[w.index("const onPointerEnd =") : w.index("const onKeyDown =")]
    assert "if (Math.abs(off) < 0.5 && e.type === 'pointerup')" in end
    assert "live.current.onCentreTap?.()" in end
    key = w[w.index("const onKeyDown =") : w.index("// A mouse wheel")]
    assert "e.key === 'Enter' && onCentreTap" in key
    assert "data-ew-pick-toggle" in w, "the wheel's own tap toggles, not closes, the picker"
    bar = _phone_bar()
    assert "onCentreTap={() => setPickOpen((o) => !o)}" in bar
    pick = bar[bar.index("<PagePicker") : bar.index("</PageWheel>")]
    for attr in ("open={pickOpen}", "onOpenChange={setPickOpen}", "overWheel"):
        assert attr in pick, attr
    picker = code_only(module("page-picker.tsx"))
    assert "at?.closest?.('[data-ew-pick-toggle]')" in picker
    # The picker button stays a real, named button for a keyboard and a screen reader.
    assert "aria-label={t('play.jumpOpen', { n: label, total: latest })}" in picker
    css = styles()
    assert re.search(r"\.ew-pager-pick\.ew-pager-pick-wheel \{[^}]*pointer-events: none;", css)


def test_the_wheel_ticks_only_with_motion_allowed():
    css = styles()
    assert re.search(r"\.ew-wheel-n \{[^}]*oldstyle-nums", css)
    assert ".ew-wheel-on .ew-wheel-c .ew-wheel-face { animation: ew-wheel-tick" in css
    reduced = [
        m.group(1)
        for m in re.finditer(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
    ]
    assert any(".ew-wheel-on .ew-wheel-c .ew-wheel-face { animation: none; }" in r for r in reduced)
    assert "reducedMotion() ||" in _wheel(), "reduced motion jumps instead of gliding"
