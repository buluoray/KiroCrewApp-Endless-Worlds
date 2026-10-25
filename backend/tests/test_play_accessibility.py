"""Player-facing contracts, using the repository's UI source-test style."""

import json
import re
from pathlib import Path

from uisrc import module, styles


def test_free_action_has_a_visible_label_and_keyboard_help():
    src = module("play.tsx")
    assert '<label htmlFor="ew-free-action"' in src
    assert 'id="ew-free-action"' in src
    assert 'aria-describedby="ew-action-help"' in src
    assert 'id="ew-action-help"' in src
    assert "e.nativeEvent.isComposing" in src


def test_cancel_returns_to_the_control_that_armed_the_action():
    src = module("play.tsx")
    assert "e.key === 'Escape' && arm" in src
    assert "onClick={cancelAction}" in src
    assert ".ew-choice-armed" in src and "?.focus()" in src


def test_a_landed_page_is_named_announced_and_focused_without_stealing_focus():
    src = module("story-page.tsx")
    assert 'role="region"' in src and "tabIndex={-1}" in src
    assert 'role="status" aria-live="polite" aria-atomic="true"' in src
    assert "t('play.pageReady'" in src
    assert "active === document.body" in src
    assert "closest('.ew-play-root')" in src
    assert "getClientRects().length" in src
    assert "visibility !== 'hidden'" in src
    assert "focus({ preventScroll: true })" in src
    assert "if (loading) return" in src
    assert module("play.tsx").count("<StoryPage") == 2


def test_phone_navigation_does_not_hide_the_keyboard_focus():
    css = styles()
    assert re.search(
        r"\.ew-topbar-hidden:focus-within\s*\{[^}]*transform: none;[^}]*opacity: 1;", css
    )
    assert re.search(r"\.ew-tabbar-hidden:focus-within\s*\{[^}]*transform: none;", css)
    assert re.search(r"\.ew-pager-arw\s*\{[^}]*width: 44px; height: 44px;", css)
    assert re.search(r"\.ew-pager-turn\s*\{[^}]*min-width: 0;", css)
    assert ".ew-act { flex-direction: column; }" in css


def test_first_life_help_is_visible_on_both_widths():
    src = module("main.tsx")
    assert "runs.length === 0 && worlds.some((w) => w.usable)" in src
    assert "t('shelf.firstLife')" in src
    assert "t('shelf.firstLifeHint')" in src
    src = module("play.tsx")
    assert "isLive && v.turn === 1 && !busy" in src
    assert "t('play.firstTurnHint')" in src


def test_first_run_and_keyboard_copy_exists_in_both_languages():
    base = Path(__file__).resolve().parents[2] / "web/src/strings"
    keys = [
        "play.actionLabel",
        "play.actionHelp",
        "play.pageReady",
        "play.firstTurnHint",
        "shelf.firstLife",
        "shelf.firstLifeHint",
    ]
    for lang in ("en", "zh"):
        catalog = json.loads((base / f"{lang}.json").read_text())
        assert all(catalog.get(key) for key in keys)
        assert (
            catalog["library.empty"]
            != {
                "en": "The shelf is empty. Your first world is waiting to be opened.",
                "zh": "书架还是空的。第一个世界，正等你推门。",
            }[lang]
        )


def test_closing_a_life_takes_a_confirm_step_and_sends_only_the_close_flag():
    src = module("play.tsx")
    # The visible control only ARMS; the send lives in the confirm step.
    assert "onClick={() => setArm(arm === CLOSE ? '' : CLOSE)}" in src
    assert src.count("close: true") == 1
    send = src.index("close: true")
    assert src.rfind("arm === CLOSE && !busy", 0, send) != -1
    assert "'.ew-close-life button'" in src  # cancel returns focus here
    # Growth rows come from the view, never computed in the page.
    assert "(v.growth ?? [])" in src
    base = Path(__file__).resolve().parents[2] / "web/src/strings"
    keys = [
        "play.closeLife",
        "play.closeLifeConfirm",
        "play.closeLifeYes",
        "play.closeLifeNo",
        "play.growth",
        "play.growthTier",
    ]
    for lang in ("en", "zh"):
        catalog = json.loads((base / f"{lang}.json").read_text())
        assert all(catalog.get(key) for key in keys)
