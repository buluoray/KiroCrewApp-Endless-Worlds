"""Fast page navigation on the play page: First/Latest, the month picker, keys.

Paging a long life one click at a time is too slow — month 3 of 84 is 81 clicks.
The pager gains First and Latest, its page indicator opens a picker (type a month
or pick a row that says what happened in it), and Left/Right/Home/End page while
focus is on the page. The guards below each fail if their behaviour is removed.

The app has no JS test runner, so the UI rules are source contracts (see
``uisrc.py``); the index route is exercised for real.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from srcguard import code_only  # noqa: E402
from uisrc import WEB_SRC, module, styles  # noqa: E402

import routes as routes_mod  # noqa: E402
from narrator import APP_NAME  # noqa: E402
from store import RunStore  # noqa: E402


def _pager() -> str:
    src = module("play.tsx")
    return src[src.index("const pager =") : src.index("const main = (")]


# ── First and Latest ─────────────────────────────────────────────────────────


def test_first_and_latest_sit_beside_prev_and_next_with_labels():
    pager = _pager()
    assert "t('play.firstTurn')" in pager and "t('play.latestTurn')" in pager
    order = [
        pager.index("t('play.firstTurn')"),
        pager.index("t('play.prevTurn')"),
        pager.index("<PagePicker"),
        pager.index("t('play.nextTurn')"),
        pager.index("t('play.latestTurn')"),
    ]
    assert order == sorted(order), "the pager reads First ‹ page › Latest"
    # First lands on month 1 — or on the live page when the life has one month.
    assert "setViewTurn(latest <= 1 ? null : 1)" in pager


def test_latest_returns_to_the_live_page_not_a_past_copy_of_it():
    """The live page is `viewTurn === null`: only there do the turn in flight, the
    painting stage and the recap render. Latest setting the newest NUMBER would show
    the newest month as a re-read page with none of them."""
    pager = _pager()
    latest_btn = pager[
        pager.index("t('play.latestTurn')") - 400 : pager.index('<Chevron dir="last"')
    ]
    assert "disabled={isLive}" in latest_btn
    assert "onClick={() => setViewTurn(null)}" in latest_btn
    # The picker routes its newest row the same way.
    picker = module("page-picker.tsx")
    assert "onJump(n >= latest ? null : n)" in picker
    # And so do the keys.
    play = module("play.tsx")
    assert "setViewTurn(next >= liveTurn ? null : next)" in play


# ── the picker ───────────────────────────────────────────────────────────────


def test_the_page_indicator_opens_a_keyboard_reachable_picker():
    picker = module("page-picker.tsx")
    trigger = picker[picker.index("<button\n        ref={trigger}") : picker.index("{open ? (")]
    assert 'aria-haspopup="dialog"' in trigger and "aria-expanded={open}" in trigger
    assert "t('play.jumpOpen'" in trigger, "the indicator must say it opens a picker"
    assert "onClick={() => setOpen(!open)}" in trigger
    # The phone wheel can hold the open state; the button still toggles it.
    assert "const open = openProp ?? ownOpen" in picker
    assert 'role="dialog"' in picker and "t('play.jumpTitle')" in picker
    # Type a month and press Enter: a real form, a labelled numeric field.
    assert "<form" in picker and "onSubmit" in picker and "if (valid) onJump(typed)" in picker
    assert re.search(r'<label className="ew-pick-label" htmlFor=\{inputId\}', picker)
    assert 'type="number"' in picker and 'inputMode="numeric"' in picker
    assert "min={1}" in picker and "max={latest}" in picker and "autoFocus" in picker
    # Escape closes and hands focus back to the indicator, not to <body>.
    assert "e.key === 'Escape'" in picker and "onClose()" in picker
    assert "trigger.current?.focus({ preventScroll: true })" in picker
    # A click outside closes it.
    assert "addEventListener('pointerdown', away)" in picker
    assert "play.tsx" and "import { PagePicker } from './page-picker'" in module("play.tsx")


def test_each_row_names_the_month_and_a_few_words_from_it():
    picker = module("page-picker.tsx")
    assert '<span className="ew-pick-n">{n}</span>' in picker
    assert "hints?.get(n)" in picker and '<span className="ew-pick-hint">' in picker
    assert "aria-current={n === shown ? 'page' : undefined}" in picker
    assert "t('play.jumpNow')" in picker, "the live month is marked as now"


def test_the_list_draws_only_the_rows_on_screen():
    """A hundred-month life must not mount a hundred buttons on every open."""
    picker = code_only(module("page-picker.tsx"))
    assert "export function visibleRows(" in picker
    assert "const [first, last] = visibleRows(scrollTop, latest)" in picker
    assert "for (let i = first; i < last; i++)" in picker
    assert "Array.from({ length: latest" not in picker
    assert "style={{ top: i * PICKER_ROW_PX }}" in picker
    assert "style={{ height: latest * PICKER_ROW_PX }}" in picker
    m = re.search(r"const PICKER_VIEW_ROWS = (\d+)", picker)
    o = re.search(r"const PICKER_OVERSCAN = (\d+)", picker)
    assert m and o and int(m.group(1)) + 2 * int(o.group(1)) <= 20
    css = styles()
    assert re.search(r"\.ew-pick-row \{[^}]*position: absolute;[^}]*height: 44px;", css)
    assert re.search(r"\.ew-pick-list \{[^}]*overflow-y: auto;", css)
    assert "export const PICKER_ROW_PX = 44" in picker


def test_the_hints_are_one_read_and_a_jump_fetches_only_its_page():
    picker = code_only(module("page-picker.tsx"))
    assert len(re.findall(r"api\s*\.chronicleIndex\(", picker)) == 1
    assert not re.search(r"api\s*\.chronicle\(", picker), (
        "the picker must not page the chronicle itself"
    )
    assert "if (!open || index?.key === indexKey) return" in picker
    api = module("api.ts")
    assert "/chronicle/index" in api
    play = code_only(module("play.tsx"))
    # One page read at a time, and a read is not thrown away for a page change.
    fetch = play[play.index("const pageFetchRef = useRef(0)") : play.index("const prevTurnRef")]
    assert "if (pageFetchRef.current) return" in fetch
    assert re.search(r"api\s*\.chronicle\(runId, want \+ 1\)", fetch)
    assert "if (!alive) return" not in fetch
    assert "if (runRef.current !== forRun) return" in fetch
    assert "setPageRead((n) => n + 1)" in fetch and "pageRead]" in fetch
    assert "if (pageFailRef.current === viewTurn) return" in fetch, "a failed read loops"


# ── the keyboard ─────────────────────────────────────────────────────────────


def test_arrow_home_end_page_without_stealing_keys_from_fields():
    play = module("play.tsx")
    assert "const PAGER_KEYS = new Set(['ArrowLeft', 'ArrowRight', 'Home', 'End'])" in play
    owned = play[play.index("function keyIsOwned(") : play.index("function Chevron(")]
    for sel in (
        "input",
        "textarea",
        "select",
        "[contenteditable]",
        '[role="tablist"]',
        '[role="dialog"]',
    ):
        assert sel in owned, f"{sel} must keep its own keys"
    handler = play[
        play.index("const onKey = (e: KeyboardEvent) =>") : play.index(
            "window.addEventListener('keydown', onKey)"
        )
    ]
    assert "e.altKey || e.ctrlKey || e.metaKey || e.shiftKey" in handler
    assert "if (sheetOpen || keyIsOwned(e.target)) return" in handler
    assert "bar.getClientRects().length" in handler, "a hidden pager must not page"
    assert "e.key === 'Home'" in handler and "? 1" in handler
    assert "Math.max(1, cur - 1)" in handler
    assert "e.preventDefault()" in handler
    assert "window.removeEventListener('keydown', onKey)" in play
    assert (
        'id="ew-free-action"' in play
        and "<textarea" in play[play.index('id="ew-free-action"') - 200 :]
    )


# ── layout, copy and docs ────────────────────────────────────────────────────


def test_every_pager_target_stays_44px_and_fits_375():
    css = styles()
    assert re.search(r"button\.ew-pager-turn \{[^}]*min-height: 44px;", css)
    assert re.search(r"\.ew-pick-input \{[^}]*min-height: 44px;", css)
    assert re.search(r"\.ew-pick \{[^}]*width: min\(320px, calc\(100vw - 24px\)\);", css)
    narrow = css[css.index("@media (max-width: 480px)") :]
    assert ".ew-pager-long { display: none; }" in narrow
    assert ".ew-pager-short { display: inline; }" in narrow
    # At 375px the indicator is mid-row; anchored to it the picker ran off the left
    # edge (measured on a pod). It anchors to the whole bar instead.
    assert ".ew-pager-pick { position: static; }" in narrow
    assert ".ew-pick { left: 8px; right: 8px; width: auto; }" in narrow
    assert ".ew-topbar:not(.ew-topbar-fixed) { position: relative; }" in narrow


def test_picker_copy_exists_in_both_languages():
    keys = [
        "play.firstTurn",
        "play.latestTurn",
        "play.pageOf",
        "play.pageShort",
        "play.jumpOpen",
        "play.jumpTitle",
        "play.jumpLabel",
        "play.jumpGo",
        "play.jumpList",
        "play.jumpNow",
    ]
    for lang in ("en", "zh"):
        cat = json.loads((WEB_SRC / "strings" / f"{lang}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert cat.get(k), f"{lang}: {k} missing"
        assert "{total}" in cat["play.pageOf"] and "{n}" in cat["play.pageOf"]


def test_the_frontend_doc_describes_fast_page_navigation():
    doc = (_BACKEND.parent / "docs" / "modules" / "frontend.md").read_text(encoding="utf-8")
    assert "page-picker.tsx" in doc
    assert "test_page_jump.py" in doc


# ── the index route ──────────────────────────────────────────────────────────


def test_the_index_route_lists_every_lived_month_with_a_short_hint(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage
    from test_delete_world import FakeCtx, FakeRequest, body_of

    data = tmp_path / "data"
    data.mkdir()
    storage = AppStorage(APP_NAME, data)
    st = RunStore(storage, data)
    run = st.create_run({"turn": 130, "worldId": "w"}, {"worldId": "w", "title": "t"})
    st.append_turn(run, {"turn": 0, "prose": "", "legacy": {"from": "x"}})
    st.append_turn(run, {"turn": 1, "prose": "## The Well\n\nYou wake by the **well**."})
    st.append_turn(run, {"turn": 2, "prose": "p", "action": "Ask the smith about his daughter"})
    for i in range(3, 131):
        st.append_turn(run, {"turn": i, "prose": "x" * 4000, "action": "a" * 200})

    ctx = FakeCtx(data, storage)
    res = asyncio.run(routes_mod.get_chronicle_index(FakeRequest(match={"run_id": run}), ctx))
    rows = body_of(res)["rows"]
    assert [r["turn"] for r in rows] == list(range(1, 131)), "turn 0 is not a page"
    assert rows[0]["hint"] == "The Well"
    assert rows[1]["hint"] == "Ask the smith about his daughter"
    assert all(len(r["hint"]) <= routes_mod.INDEX_HINT_CHARS for r in rows)
    assert set(rows[2]) == {"turn", "hint"}, "the index must carry no prose"
    assert len(res.body) < 130 * 80, "a long life's index stays a small read"


def test_the_index_and_the_chronicle_agree_on_which_months_exist():
    src = (_BACKEND / "routes.py").read_text(encoding="utf-8")
    assert 'path="/runs/{run_id}/chronicle/index"' in src
    chron = code_only(src[src.index("async def get_chronicle(") : src.index("CHRONICLE_PAGE = ")])
    idx = code_only(src[src.index("async def get_chronicle_index(") : src.index("def _int_param(")])
    assert "_lived_entries(ctx, store, run_id)" in chron
    assert "_lived_entries(ctx, store, run_id)" in idx
    assert 'request.get("user") is None' in idx
