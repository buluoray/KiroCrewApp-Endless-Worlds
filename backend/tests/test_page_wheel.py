"""The page wheel: the sideways iOS-style picker that is the play page's one page
control, on a phone and on a wide screen. There is no fore-edge slider and no pager
buttons.

The app has no JS test runner, so these are source contracts (see ``uisrc.py``) plus
a Python mirror of the wheel's pure arithmetic. The real swipe and drag — follow the
pointer, coast, snap, one read on rest — runs against a pod in
``devtools/scrub.test.mjs`` at 375px (a finger) and 1280px (a mouse); the frame cost
is measured by ``devtools/switcher-perf.mjs``.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from srcguard import code_only  # noqa: E402
from uisrc import WEB_SRC, module, styles  # noqa: E402


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
    assert "const [first, last] = visiblePages(p, widthRef.current, latest)" in w
    assert "new ResizeObserver(measure)" in w
    # A fixed set of slots, enough for any window visiblePages can ask for.
    slots = _src()[_src().index("export function wheelSlots(") : _src().index("export function slotOf(")]
    assert "return 2 * (Math.ceil(widthPx / 2 / WHEEL_ITEM_PX) + 1) + 1" in slots
    assert "const count = wheelSlots(width)" in w
    assert "for (let i = 0; i < count; i++)" in w


def test_a_swipe_redraws_without_react_and_mounts_nothing():
    """Every frame of a swipe or a glide is written straight onto fixed slots; React
    renders only when the centred page changes. A per-frame state update re-rendered
    every number, and a number mounted or unmounted per page re-ran the app's
    `:has()` rules over the whole page."""
    w = _wheel()
    assert "useState(shown)" not in w and "setPosState" not in w, "no per-frame state"
    assert "const posRef = useRef(shown)" in w
    place = w[w.index("const place = useCallback(") : w.index("const finish = useCallback(")]
    assert "draw(p)" in place
    draw = w[w.index("const draw = useCallback(") : w.index("// At rest the drum")]
    assert "el.style.transform = `translateX(${d * WHEEL_ITEM_PX}px) rotateY(" in draw
    assert "el.style.opacity = String(look.opacity)" in draw
    assert "n = first + slotOf(i - first, count)" in draw, "a ring: one slot re-labelled per page"
    # The text node is rewritten in place, never replaced.
    assert "face.firstChild.nodeValue = String(n)" in draw
    assert ".textContent =" not in draw
    # The slots are keyed by position, not by page, and carry no React style or text.
    assert "key={i}" in w and "key={n}" not in w
    assert '<span className="ew-wheel-face" />' in w
    # The move handler reads no layout.
    move = w[w.index("const onPointerMove =") : w.index("const onPointerEnd =")]
    assert "getBoundingClientRect" not in move and "offsetWidth" not in move
    css = styles()
    n = re.search(r"\.ew-wheel-n \{([^}]*)\}", css).group(1)
    assert "will-change: transform, opacity;" in n
    contain = re.search(r"(?:^|[;\s])contain: ([^;]+);", n).group(1)
    assert contain == "layout size style", "a re-labelled number lays out only its own box"
    # No paint containment: it would clip the reading halo (text-shadow) to a square.


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
    for cls in ("ew-wheel-drum",):
        at = w.index(f'className="{cls}"')
        assert 'aria-hidden="true"' in w[at : at + 60], cls


def _play() -> str:
    return code_only(module("play.tsx"))


def _wheel_bar() -> str:
    p = _play()
    return p[p.index("const wheelBar = (") : p.index("const main = (")]


def test_every_screen_gets_the_wheel_and_dragging_it_does_not_scroll_the_page():
    play = _play()
    assert "usePhoneLayout" not in play and "PHONE_QUERY" not in _src(), "one layout"
    assert "'ew-topbar ew-topbar-wheel' +" in play
    css = styles()
    assert re.search(r"\.ew-wheel-track \{[^}]*touch-action: none;", css)
    # The wheel shares the back link's 44px row, so the fixed bar's slot does not grow.
    assert '<div className="ew-topbar-slot" />' in play
    assert "ew-topbar-slot-wheel" not in css and "ew-topbar-slot-scrub" not in css
    for sel in (r"\.ew-wheel-bar", r"\.ew-wheel", r"\.ew-wheel-track"):
        body = re.search(sel + r" \{([^}]*)\}", css).group(1)
        assert "height: 44px;" in body, sel
    # On a wide screen a bounded stretch at the row's end, not thirty numbers.
    wide = re.search(r"@media \(min-width: 601px\) \{([^}]*\})", css).group(1)
    assert ".ew-topbar.ew-topbar-wheel .ew-wheel-bar { flex: 0 1 520px; margin-left: auto; }" in wide


def test_the_slider_and_the_pager_buttons_are_gone():
    assert not (WEB_SRC / "page-scrubber.tsx").exists()
    play = module("play.tsx")
    for gone in ("PageScrubber", "HoldArrow", "const pager =", "const scrubber =", "{pager}"):
        assert gone not in play, gone
    css = styles()
    for gone in (".ew-scrub", ".ew-pager-arw", ".ew-pager-hold", ".ew-topbar-scrub", ".ew-pager {"):
        assert gone not in css, gone


def test_the_wheel_flips_one_page_per_notch_and_loads_on_settle():
    src = _src()
    steps = src[src.index("export function wheelSteps(") : src.index("/** One page number")]
    assert "if (acc >= WHEEL_STEP_PX) return { steps: 1, rest: 0 }" in steps
    assert "if (acc <= -WHEEL_STEP_PX) return { steps: -1, rest: 0 }" in steps
    assert "return { steps: 0, rest: acc }" in steps, "small deltas accumulate"
    w = _wheel()
    assert "el.addEventListener('wheel', onWheel, { passive: false })" in w
    wheel = w[w.index("const onWheel = (e: WheelEvent) =>") : w.index("el.addEventListener('wheel'")]
    assert "e.preventDefault()" in wheel, "the page must not scroll under the wheel"
    assert "wheelSteps(wheelAcc.current + d)" in wheel
    assert "settleSoon()" in wheel and "onCommit" not in wheel


def test_the_wheels_keys_are_the_slider_keys():
    src = _src()
    keys = src[src.index("export function scrubKey(") : src.index("export function wheelSteps(")]
    for k, d in (("ArrowLeft", "-1"), ("ArrowRight", "1"), ("PageDown", "-10"), ("PageUp", "10")):
        assert f"{k}: {d}," in keys, k
    assert "if (key === 'Home') return 1" in keys and "if (key === 'End') return latest" in keys
    w = _wheel()
    onkey = w[w.index("const onKeyDown =") : w.index("// A mouse wheel")]
    assert "e.preventDefault()" in onkey, "the play page's own paging keys stay out"
    assert "settleSoon()" in onkey and "onCommit" not in onkey
    page = code_only(module("story-page.tsx"))
    assert "!active?.closest('[role=\"slider\"]')" in page


def test_a_step_does_not_re_render_the_story():
    """The flipping number lives in a small external store; only the wheel, the `>|`
    mark and the picker's button subscribe."""
    store = code_only(module("scrub-store.ts"))
    assert "useSyncExternalStore(" in store
    play = code_only(module("play.tsx"))
    assert "const [scrub] = useState(createScrubStore)" in play
    assert "useScrubPreview" not in play, "the play page must not subscribe"
    assert "preview={scrub}" in _wheel_bar()


def test_a_long_jump_leafs_the_page_once_and_reduced_motion_draws_none():
    play = module("play.tsx")
    leaf = play[play.index("const leafTo =") : play.index("const wheelBar =")]
    assert "Math.abs(to - shownTurn) > 1" in leaf, "one step is a plain page turn"
    assert "goPage(n)" in leaf
    assert "const goPage = (n: number) => setViewTurn(n >= latest ? null : Math.max(1, n))" in play
    assert "leafTo(n)" in _wheel_bar()
    assert "{leaf?.turn === shownTurn ? (" in play
    assert "onAnimationEnd={() => setLeaf(null)}" in play, "it plays once, not on every revisit"
    css = styles()
    reduced = [
        m.group(1)
        for m in re.finditer(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
    ]
    assert any(re.search(r"\.ew-leaf \{[^}]*display: none;", r) for r in reduced)


def test_wheel_copy_exists_in_both_languages():
    for lang in ("en", "zh"):
        cat = json.loads((WEB_SRC / "strings" / f"{lang}.json").read_text(encoding="utf-8"))
        assert cat.get("play.scrubLabel"), lang
        assert "{n}" in cat["play.scrubValue"] and "{total}" in cat["play.scrubValue"], lang


def test_the_frontend_doc_describes_the_wheel():
    doc = (_BACKEND.parent / "docs" / "modules" / "frontend.md").read_text(encoding="utf-8")
    assert "page-wheel.tsx" in doc and "scrub-store.ts" in doc
    assert "test_page_wheel.py" in doc and "scrub.test.mjs" in doc
    assert "switcher-perf.mjs" in doc
    assert "page-scrubber.tsx" not in doc


def test_the_top_row_is_the_back_link_then_the_wheel():
    play = _play()
    bar = _wheel_bar()
    assert "<PageWheel" in bar
    for gone in ("<HoldArrow", "t('play.firstTurn')", "t('play.prevTurn')", "t('play.nextTurn')"):
        assert gone not in bar, gone
    top = play[play.index("'ew-topbar ew-topbar-wheel' +") :]
    assert top.index('className="ew-back"') < top.index("{wheelBar}")
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


def test_the_phone_wheel_draws_no_bookmark():
    """The centre number alone marks the page: no ribbon, bookmark or underline."""
    w = module("page-wheel.tsx")
    assert not re.search(r"ribbon|bookmark", w, re.I), "no bookmark element in the wheel"
    css = styles()
    assert ".ew-wheel-ribbon" not in css
    assert not re.search(r"\.ew-wheel-c \{[^}]*(?:border-bottom|text-decoration):", css)


def test_the_mark_at_the_wheels_end_goes_back_to_the_live_page():
    bar = _wheel_bar()
    at = bar.index("<WheelLatest")
    use = bar[at : bar.index("</WheelLatest>", at)]
    assert "onLatest={() => setViewTurn(null)}" in use, "Latest is the LIVE page"
    assert "store={scrub}" in use, "follows the swipe, not only the landed page"
    assert bar.index("</PageWheel>") < at, "at the wheel's end"
    w = _src()
    mark = w[w.index("export function WheelLatest(") :]
    btn = mark[mark.index('className="ew-wheel-latest"') : mark.index("</button>")]
    assert "const atLatest = (preview ?? shown) >= latest" in mark
    assert "aria-label={t('play.latestTurn')}" in btn, "named for a screen reader"
    assert "disabled={atLatest}" in btn
    assert "aria-hidden={atLatest ? true : undefined}" in btn, "hidden from a screen reader"
    assert "tabIndex={atLatest ? -1 : undefined}" in btn, "out of the tab order"


def test_the_spent_latest_mark_is_hidden_but_keeps_its_slot():
    """On the live page the mark hides without moving the wheel or the back link."""
    css = styles()
    rule = re.search(r"\.ew-wheel-latest:disabled \{([^}]*)\}", css)
    assert rule and "visibility: hidden" in rule.group(1)
    assert "display: none" not in rule.group(1)


def test_a_tap_on_the_centre_number_opens_the_type_a_number_picker():
    w = _wheel()
    end = w[w.index("const onPointerEnd =") : w.index("const onKeyDown =")]
    assert "if (Math.abs(off) < 0.5 && e.type === 'pointerup')" in end
    assert "live.current.onCentreTap?.()" in end
    key = w[w.index("const onKeyDown =") : w.index("// A mouse wheel")]
    assert "e.key === 'Enter' && onCentreTap" in key
    assert "data-ew-pick-toggle" in w, "the wheel's own tap toggles, not closes, the picker"
    bar = _wheel_bar()
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
