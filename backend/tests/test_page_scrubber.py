"""The page scrubber: press, hold and slide to flip through a life's pages fast.

A slim track under the pager has one position per page. Dragging it, holding Prev or
Next, or spinning the wheel over it moves the page indicator and a small label live,
and only release (or a pause, for the wheel and keys) loads the one page landed on.
The guards below each fail if their behaviour is removed; the pointer behaviour runs
for real in ``devtools/scrub.test.mjs`` against a pod.

The app has no JS test runner, so these are source contracts (see ``uisrc.py``).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from srcguard import code_only  # noqa: E402
from uisrc import WEB_SRC, module, styles  # noqa: E402


def _scrubber() -> str:
    src = code_only(module("page-scrubber.tsx"))
    return src[src.index("export function PageScrubber(") : src.index("export function HoldArrow(")]


def _hold() -> str:
    src = code_only(module("page-scrubber.tsx"))
    return src[src.index("export function HoldArrow(") :]


def _pager() -> str:
    src = module("play.tsx")
    return src[src.index("const goPage =") : src.index("const main = (")]


# ── dragging the track ───────────────────────────────────────────────────────


def test_the_scrubber_sits_in_the_top_bar_for_a_life_with_pages():
    play = module("play.tsx")
    assert "import { HoldArrow, PageScrubber } from './page-scrubber'" in play
    pager = _pager()
    assert "latest >= 2 ? (\n      phone ? (\n        <PageWheel" in pager
    assert pager.index("<PageWheel") < pager.index("<PageScrubber"), "the wheel on a phone"
    assert pager.count("onCommit={leafTo}") == 4, "both scrubbers and both held arrows"
    assert "onCommit={leafTo}" in pager
    assert "goPage(n)" in pager[pager.index("const leafTo =") :]
    # The newest page is the LIVE page, like Latest.
    assert "const goPage = (n: number) => setViewTurn(n >= latest ? null : Math.max(1, n))" in pager
    start = play.index("'ew-topbar' +")
    bar = play[start : play.index("{t('play.back')}", start) + 400]
    assert "{pager}\n        {scrubber}" in bar
    assert "(scrubber ? ' ew-topbar-scrub' : '')" in bar


def test_dragging_moves_only_the_preview_and_release_loads_one_page():
    s = _scrubber()
    down = s[s.index("const onPointerDown =") : s.index("const onPointerMove =")]
    assert "e.currentTarget.setPointerCapture(e.pointerId)" in down
    assert "e.preventDefault()" in down, "a drag must not select text or scroll"
    assert "store.set(pointPage(e.clientX))" in down
    move = s[s.index("const onPointerMove =") : s.index("const onPointerEnd =")]
    assert "store.set(pointPage(e.clientX))" in move
    assert "onCommit" not in move and "finish" not in move, "no page load while dragging"
    end = s[s.index("const onPointerEnd =") : s.index("const onKeyDown =")]
    assert "finish()" in end
    for ev in ("onPointerUp={onPointerEnd}", "onPointerCancel={onPointerEnd}"):
        assert ev in s
    # finish loads the one page landed on, and nothing when it is the same page.
    fin = s[s.index("const finish = useCallback(") : s.index("const settleSoon =")]
    assert "if (n !== null && n !== live.current.shown) live.current.onCommit(n)" in fin
    assert "store.set(null)" in fin
    # The scrubber never reads a page itself.
    assert not re.search(r"api\s*\.", code_only(module("page-scrubber.tsx")))


def test_the_pointer_maps_to_a_page_on_the_rail():
    src = code_only(module("page-scrubber.tsx"))
    assert "return clampPage(1 + ((x - left) / width) * (latest - 1), latest)" in src
    assert "Math.min(latest, Math.max(1, Math.round(n)))" in src
    assert "r ? pageAt(x, r.left, r.width, live.current.latest)" in src


def test_the_label_follows_with_the_page_and_its_hint_from_one_shared_read():
    s = _scrubber()
    assert 'className="ew-scrub-tip"' in s and "{active ? (" in s
    assert "t('play.pageOf', { n: value, total: latest })" in s
    assert "hints.rows.get(value)" in s
    assert "loadPageIndex(runId, latest)" in s
    picker = code_only(module("page-picker.tsx"))
    loader = picker[
        picker.index("export function loadPageIndex(") : picker.index("export function PagePicker(")
    ]
    assert "if (indexCache?.key === key) return indexCache.rows" in loader
    assert "loadPageIndex(runId, latest)" in picker, "the picker shares the same read"


def test_a_step_does_not_re_render_the_story():
    """The flipping number lives in a small external store; only the thumb, the
    label and the indicator subscribe. In play-page state it would re-render the
    whole story on every page passed."""
    store = code_only(module("scrub-store.ts"))
    assert "useSyncExternalStore(" in store
    play = code_only(module("play.tsx"))
    assert "const [scrub] = useState(createScrubStore)" in play
    assert "useScrubPreview" not in play, "the play page must not subscribe"
    picker = code_only(module("page-picker.tsx"))
    assert "const flipping = useScrubPreview(preview)" in picker
    assert "t('play.pageOf', { n: label, total: latest })" in picker
    assert "preview={scrub}" in _pager()
    assert "const preview = useScrubPreview(store)" in _scrubber()


# ── holding Prev / Next ──────────────────────────────────────────────────────


def test_holding_an_arrow_repeats_faster_and_loads_once_on_release():
    pager = _pager()
    assert pager.count("<HoldArrow") == 2
    assert "dir={-1}" in pager and "dir={1}" in pager
    # The order First ‹ page › Latest still holds (test_page_jump pins it too).
    assert (
        pager.index("t('play.prevTurn')")
        < pager.index("<PagePicker")
        < pager.index("t('play.nextTurn')")
    )
    src = code_only(module("page-scrubber.tsx"))
    assert "export const HOLD_START_MS = 300" in src
    ramp = src[
        src.index("export function holdInterval(") : src.index("export const SCRUB_SETTLE_MS")
    ]
    waits = [int(n) for n in re.findall(r"return (\d+)", ramp)]
    assert waits == sorted(waits, reverse=True) and waits[0] == 300 and waits[-1] < 300
    h = _hold()
    assert "e.currentTarget.setPointerCapture(e.pointerId)" in h
    assert "window.setTimeout(tick, HOLD_START_MS)" in h
    assert "holdInterval(performance.now() - h.start)" in h
    at = h.index("const tick = () =>")
    tick = h[at : h.index("useEffect(", at)]
    assert "store.set(next)" in tick and "onCommit" not in tick, "no page load mid-hold"
    stop = h[h.index("const stop = () =>") : h.index("const tick = () =>")]
    assert "if (h.n !== live.current.shown) live.current.onCommit(h.n)" in stop
    assert "swallowClick.current = true" in stop, "the click after a hold is not a step"
    for ev in ("onPointerUp={stop}", "onPointerCancel={stop}", "onLostPointerCapture={stop}"):
        assert ev in h
    # A plain click (or Enter) is still exactly one page.
    assert "onCommit(clampPage(shown + dir, latest))" in h
    assert "onContextMenu={(e) => e.preventDefault()}" in h


# ── the wheel ────────────────────────────────────────────────────────────────


def test_the_wheel_flips_one_page_per_notch_and_loads_on_settle():
    src = code_only(module("page-scrubber.tsx"))
    steps = src[src.index("export function wheelSteps(") : src.index("function railFrac(")]
    assert "if (acc >= WHEEL_STEP_PX) return { steps: 1, rest: 0 }" in steps
    assert "if (acc <= -WHEEL_STEP_PX) return { steps: -1, rest: 0 }" in steps
    assert "return { steps: 0, rest: acc }" in steps, "small deltas accumulate"
    s = _scrubber()
    assert "el.addEventListener('wheel', onWheel, { passive: false })" in s
    wheel = s[
        s.index("const onWheel = (e: WheelEvent) =>") : s.index("el.addEventListener('wheel'")
    ]
    assert "e.preventDefault()" in wheel, "the page must not scroll under the scrubber"
    assert "wheelSteps(wheelAcc.current + d)" in wheel
    assert "settleSoon()" in wheel and "onCommit" not in wheel
    assert "window.setTimeout(finish, SCRUB_SETTLE_MS)" in s


# ── touch ────────────────────────────────────────────────────────────────────


def test_a_finger_scrubs_without_scrolling_the_page():
    css = styles()
    assert re.search(r"\.ew-scrub-track \{[^}]*touch-action: none;", css)
    assert re.search(r"\.ew-pager-hold \{[^}]*touch-action: none;", css)
    assert re.search(r"\.ew-pager-hold \{[^}]*-webkit-touch-callout: none;", css)
    assert re.search(r"\.ew-scrub \{[^}]*flex: 1 0 100%;", css), "a full-width row"
    assert ".ew-topbar.ew-topbar-scrub { flex-wrap: wrap; row-gap: 2px; }" in css
    # The fixed bar's slot grows by the scrubber row (24px) and its gap (2px).
    m = re.search(r"\.ew-topbar-slot \{ flex: none; height: (\d+)px; \}", css)
    g = re.search(r"\.ew-topbar-slot\.ew-topbar-slot-scrub \{ height: (\d+)px; \}", css)
    assert m and g and int(g.group(1)) == int(m.group(1)) + 24 + 2
    assert re.search(r"\.ew-scrub-track \{[^}]*height: 24px;", css)
    # The label stays inside the bar at both ends.
    assert "transform: `translateX(${-frac * 100}%)`" in _scrubber()


# ── accessibility ────────────────────────────────────────────────────────────


def test_the_track_is_a_labelled_slider_with_its_keys():
    s = _scrubber()
    for attr in (
        'role="slider"',
        "tabIndex={0}",
        "aria-label={t('play.scrubLabel')}",
        "aria-valuemin={1}",
        "aria-valuemax={latest}",
        "aria-valuenow={value}",
        "aria-valuetext={t('play.scrubValue', { n: value, total: latest })}",
    ):
        assert attr in s, attr
    src = code_only(module("page-scrubber.tsx"))
    keys = src[src.index("export function scrubKey(") : src.index("export function wheelSteps(")]
    for k, d in (("ArrowLeft", "-1"), ("ArrowRight", "1"), ("PageDown", "-10"), ("PageUp", "10")):
        assert f"{k}: {d}," in keys, k
    assert "if (key === 'Home') return 1" in keys and "if (key === 'End') return latest" in keys
    onkey = s[s.index("const onKeyDown =") : s.index("useEffect(", s.index("const onKeyDown ="))]
    assert "e.preventDefault()" in onkey, "the play page's own paging keys stay out"
    assert "settleSoon()" in onkey and "onCommit" not in onkey
    # The play page's key handler skips a slider, and checks defaultPrevented first.
    play = module("play.tsx")
    assert "'[role=\"slider\"]'" in play or '[role="slider"]' in play


def test_the_page_is_announced_once_on_settle_and_the_slider_keeps_focus():
    page = code_only(module("story-page.tsx"))
    assert "!active?.closest('[role=\"slider\"]')" in page
    # The one announcement is StoryPage's live region, which fires per landed page,
    # not per step: nothing in the scrubber writes a live region.
    s = module("page-scrubber.tsx")
    assert "aria-live" not in s
    assert 'aria-hidden="true"' in s[s.index('className="ew-scrub-tip"') - 200 :]


# ── the book: fore-edge, ribbon, folio, leafing ──────────────────────────────


def test_the_ribbon_thumb_is_drawing_only_and_the_track_keeps_the_slider():
    """The ribbon replaced the round knob, inside the track, never as the slider."""
    s = _scrubber()
    thumb = s[s.index('className="ew-scrub-thumb"') - 40 : s.index("</div>\n      </div>")]
    assert 'aria-hidden="true"' in thumb and "style={{ left: at }}" in thumb
    assert '<span className="ew-scrub-ribbon" />' in thumb
    assert "role=" not in thumb and "tabIndex" not in thumb, "the ribbon is not a second control"
    # The slider attributes sit on the track, which still wraps the ribbon.
    track = s[s.index("className={'ew-scrub-track'") : s.index('className="ew-scrub-thumb"')]
    assert 'role="slider"' in track and "aria-valuenow={value}" in track
    css = styles()
    assert re.search(r"\.ew-scrub-ribbon \{[^}]*clip-path: polygon\([^)]*50% 80%", css), (
        "the ribbon's notched tail"
    )
    assert re.search(r"\.ew-scrub-thumb \{[^}]*pointer-events: none;", css)
    # No round knob left.
    thumb_css = re.search(r"\.ew-scrub-thumb \{([^}]*)\}", css).group(1)
    assert "border-radius: 50%" not in thumb_css


def test_the_rail_is_a_fore_edge_denser_for_a_longer_life():
    src = code_only(module("page-scrubber.tsx"))
    gap = src[src.index("export function edgeGap(") : src.index("function railFrac(")]
    pitches = [int(n) for n in re.findall(r"return (\d+)", gap)]
    assert pitches == sorted(pitches, reverse=True) and pitches[-1] >= 2, pitches
    assert "'--ew-edge-gap': `${edgeGap(latest)}px`" in _scrubber()
    css = styles()
    for sel, line in (
        (r"\.ew-scrub-rail", "--ew-edge-line"),
        (r"\.ew-scrub-fill", "--ew-edge-read-line"),
    ):
        body = re.search(sel + r" \{([^}]*)\}", css).group(1)
        assert "repeating-linear-gradient(" in body and line in body, sel
        assert "var(--ew-edge-gap" in body, sel
    # Drawn with CSS only: no image asset behind the book.
    assert "url(" not in re.search(r"\.ew-scrub-rail \{([^}]*)\}", css).group(1)


def test_the_folio_is_set_in_a_reading_face_on_its_own_paper():
    css = styles()
    tip = re.search(r"\.ew-scrub-tip \{([^}]*)\}", css).group(1)
    assert "serif;" in tip and "font-family:" in tip
    n = re.search(r"\.ew-scrub-tip-n \{([^}]*)\}", css).group(1)
    assert "small-caps" in n and "oldstyle-nums" in n
    hint = re.search(r"\.ew-scrub-tip-hint \{([^}]*)\}", css).group(1)
    assert "font-style: italic;" in hint


def test_a_long_jump_leafs_the_page_once_and_reduced_motion_draws_none():
    pager = _pager()
    leaf = pager[pager.index("const leafTo =") : pager.index("const scrubber =")]
    assert "Math.abs(to - shownTurn) > 1" in leaf, "one click is a plain page turn"
    play = module("play.tsx")
    assert "{leaf?.turn === shownTurn ? (" in play
    assert "onAnimationEnd={() => setLeaf(null)}" in play, "it plays once, not on every revisit"
    body = play[play.index("{leaf?.turn === shownTurn ? (") :][:300]
    assert 'aria-hidden="true"' in body
    css = styles()
    assert re.search(r"\.ew-leaf \{[^}]*animation: ew-leaf [.\d]+s", css)
    reduced = [
        m.group(1)
        for m in re.finditer(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
    ]
    assert any(re.search(r"\.ew-leaf \{[^}]*display: none;", r) for r in reduced)
    assert any(re.search(r"\.ew-scrub-ribbon \{[^}]*transition: none;", r) for r in reduced) or (
        "@media (prefers-reduced-motion: reduce) { .ew-scrub-ribbon { transition: none; } }" in css
    )


# ── copy and docs ────────────────────────────────────────────────────────────


def test_scrubber_copy_exists_in_both_languages():
    for lang in ("en", "zh"):
        cat = json.loads((WEB_SRC / "strings" / f"{lang}.json").read_text(encoding="utf-8"))
        assert cat.get("play.scrubLabel"), lang
        assert "{n}" in cat["play.scrubValue"] and "{total}" in cat["play.scrubValue"], lang


def test_the_frontend_doc_describes_the_scrubber():
    doc = (_BACKEND.parent / "docs" / "modules" / "frontend.md").read_text(encoding="utf-8")
    assert "page-scrubber.tsx" in doc and "scrub-store.ts" in doc
    assert "test_page_scrubber.py" in doc and "scrub.test.mjs" in doc
