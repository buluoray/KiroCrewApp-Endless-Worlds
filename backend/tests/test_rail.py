"""Guards on the desktop shelf drawer.

The drawer exists because navigation and reading were sharing one axis: the shelf, a
world, the opening screen and the live turn were all the same 900px column, so
switching between two lives meant going back to a list. Splitting the axes is the
kind of change that is easy to get right once and then lose, in three specific ways
these tests are aimed at.

The first is regressing the phone. The narrow layout was not a compromise to be
undone -- it is the baseline the desktop is added on top of -- so a rail that
renders at phone widths would be a strict loss, and it would be invisible to anyone
developing on a desktop.

The second is letting the reading measure grow on its own. A life is read, not
scanned; prose set to the full width of a 2560px monitor is unreadable, and the
failure looks like "the app uses the space well" in a screenshot. A reader may lift
the cap deliberately -- that is a stored preference, and the guard is that nothing
else can.

The third is the corner. The top-left slot carries the phone's "back to the shelf"
or the desktop's "shelf" opener, never both and never neither.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from uisrc import WEB_SRC, module, styles

#: Where the rail turns on. Duplicated from the stylesheet on purpose: a test that
#: reads the number out of the file it is checking cannot catch the number changing.
BREAKPOINT = 1100


def test_the_rail_is_absent_at_phone_widths():
    """The bare rule -- the one a phone applies -- must hide the rail.

    Asserted on the DEFAULT declaration rather than on the presence of a media
    query, because a rail that is shown by default and hidden inside a
    ``max-width`` query would still flash on a phone during load.
    """
    css = styles()
    bare = re.search(r"^\.ew-rail\s*\{([^}]*)\}", css, re.MULTILINE)
    assert bare, "the rail needs a default rule, not only a desktop one"
    assert "display: none" in bare.group(1), (
        "the phone baseline must not render the rail; found: " + bare.group(1).strip()
    )


def test_the_rail_only_appears_above_the_desktop_breakpoint():
    """``display: block`` for the rail must live inside a ``min-width`` block, and
    that width must be wide enough for a rail AND a readable measure."""
    css = styles()
    blocks = re.findall(r"@media \(min-width: (\d+)px\)\s*\{(.*?)\n\}", css, re.S)
    showing = [int(w) for w, body in blocks if re.search(r"\.ew-rail\s*\{[^}]*display:\s*block", body)]
    assert showing, "the rail is never shown at any width"
    assert min(showing) >= BREAKPOINT, (
        f"the rail turns on at {min(showing)}px; below {BREAKPOINT}px a rail plus a "
        "readable column gives a cramped rail AND cramped prose"
    )


def test_the_reading_column_does_not_grow_with_the_window_on_its_own():
    """The measure is capped by default, and capped in ``ch`` -- a character-relative
    unit, so it tracks the font rather than a pixel guess that breaks when the
    theme's type size changes.

    "On its own" is the whole content of this guard now. A reader may lift the cap
    (see the fluid-width tests below) and that is a choice they made; what must never
    happen is the layout widening the prose because a monitor happened to be wide.
    """
    css = styles()
    main = re.search(r"\.ew-main\s*\{([^}]*)\}", css)
    assert main, "the reading column needs its own rule"
    cap = re.search(r"max-width:\s*([\d.]+)(ch|rem|em)\b", main.group(1))
    assert cap, (
        "the reading column must be capped in a character-relative unit; found: "
        + main.group(1).strip()
    )
    if cap.group(2) == "ch":
        assert 55 <= float(cap.group(1)) <= 90, (
            f"{cap.group(1)}ch is outside the range prose stays readable in"
        )


def test_the_cap_is_lifted_only_by_the_readers_own_choice():
    """``max-width: none`` on the reading column must be qualified by the preference
    class. An unqualified one anywhere would restore exactly the failure the cap
    exists for -- prose set to the full width of a 2560px monitor -- and it would look
    like "the app uses the space well" in a screenshot."""
    css = styles()
    # Comments first, then the media-query wrappers. Both defeat a rule-level scan
    # and both did: a comment is swallowed into the following selector, so a rule
    # whose comment merely MENTIONS the preference class read as though the selector
    # carried it — and a media query's own `{` desyncs the brace pairing, which hid
    # every rule inside one. This test passed a real regression on both counts.
    flat = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    flat = re.sub(r"@media[^{]*\{", "", flat)
    seen = 0
    for rule in re.finditer(r"([^{}\n][^{}]*)\{([^}]*)\}", flat):
        selector, body = rule.group(1).strip(), rule.group(2)
        if not re.search(r"\.ew-main\b", selector):
            continue
        seen += 1
        if re.search(r"max-width:\s*none", body):
            assert "ew-w-fluid" in selector, (
                "the measure is uncapped by " + selector + ", which no reader asked for"
            )
    assert seen >= 2, (
        f"the scan found {seen} rules for the reading column; it should see both the "
        "default cap and the reader's override, so it is not actually checking them"
    )


def test_non_reading_desktop_pages_fill_the_canvas_from_the_top_left():
    """A reading measure is not a generic page measure.

    Short workflows once inherited the prose cap and the closed-shell auto margins,
    which made life opening and world creation float as centred columns. Every
    non-reading page owns the full main track and starts at its top-left instead.
    """
    src = module("main.tsx")
    # The invariant is that the root publishes BOTH the view and the read measure as
    # classes, not that they are adjacent in one literal: other state (the phone's
    # flush-top reading page) legitimately contributes a class between them, and an
    # adjacency check fails on that while the stylesheet still works perfectly.
    assert "'ew-root ew-view-' + view" in src, (
        "the stylesheet cannot tell which view it is styling"
    )
    assert "' ew-w-' + readWidth" in src, (
        "the stylesheet cannot distinguish live prose from non-reading pages"
    )

    css = styles()
    assert re.search(
        r"@media \(min-width: 768px\).*?\.ew-root\s*\{[^}]*"
        r"max-width:\s*none;[^}]*margin:\s*0;",
        css,
        re.S,
    ), "tablet and desktop pages still fall back to a centred 900px root"
    assert re.search(r"\.ew-view-live\s+\.ew-main\s*\{[^}]*max-width:\s*74ch", css), (
        "the readable measure must be scoped to the live view"
    )
    assert re.search(
        r"\.ew-view-live\s+\.ew-shell:not\(\.ew-shell-open\)\s+\.ew-main"
        r"\s*\{[^}]*margin-inline:\s*auto",
        css,
    ), "closed-shell centring must be scoped to live reading only"
    assert ".ew-create { max-width: none; }" in css, (
        "the create-world workflow still carries a page-level width cap"
    )


def test_the_two_width_modes_are_the_only_two_and_one_of_them_is_stored():
    """The choice is a standing preference, not a per-visit toggle: a reader who set
    a measure and came back to the app's own default would have to set it again every
    session, which reads as the setting not working."""
    src = module("main.tsx")
    assert "endless-worlds:width" in src, "the width choice is not persisted anywhere"
    assert re.search(r"localStorage\.setItem\(WIDTH_KEY", src), (
        "the width choice is read but never written"
    )
    assert re.search(r"ew-w-' \+ readWidth", src), (
        "the chosen width never reaches the stylesheet"
    )
    rail = module("rail.tsx")
    assert re.search(r"ReadWidth = 'fluid' \| 'fixed'", rail), (
        "the width type must name exactly the two modes the stylesheet implements"
    )
    css = styles()
    assert ".ew-w-fluid" in css, "the fluid mode has no rule at all"


def test_the_shelf_drawer_rests_closed_and_unmounts_when_it_is():
    """The shelf is a collapsible drawer: open by DEFAULT so the landing shows it,
    with the open/closed choice PERSISTED across loads (the reader closes it for
    reading room and it stays closed until they reopen it). Two invariants remain
    from the old closed-by-default drawer and still matter: it must UNMOUNT when
    closed (one merely hidden with CSS while mounted is stranded over the story by
    a resize down to phone width, where its opener no longer renders), and it must
    be dismissible from the keyboard."""
    src = module("main.tsx")
    assert "railOpen" in src and "RAIL_KEY" in src, "the drawer state is not tracked"
    # Open by default, reading its remembered state; closed only when so stored.
    assert re.search(r"RAIL_KEY\)\s*!==\s*'closed'", src), (
        "the drawer must default open and read its remembered state"
    )
    assert re.search(r"setItem\(RAIL_KEY", src), "the open/closed choice is not persisted"
    rail = module("rail.tsx")
    assert re.search(r"if \(!open\) return null", rail), (
        "the drawer stays mounted while closed, so a resize can strand it"
    )
    assert "'Escape'" in rail, (
        "a drawer covering the story must be dismissible from the keyboard"
    )


def test_the_desktop_opener_exists_only_where_the_inline_back_button_is_hidden():
    """The top-left corner carries exactly one control at every width: the phone's
    "back to the shelf", or the desktop's "shelf". Both showing is the two-back-
    buttons bug in a new costume; neither showing strands the reader."""
    css = styles()
    bare = re.search(r"^\.ew-shelfbtn\s*\{([^}]*)\}", css, re.MULTILINE)
    assert bare and "display: none" in bare.group(1), (
        "the opener renders at phone widths, where it would sit beside the inline "
        "back button"
    )
    wide = re.search(
        rf"@media \(min-width: {BREAKPOINT}px\)\s*\{{(.*?)\n\}}", css, re.S
    )
    assert wide, "no rule block at the desktop breakpoint"
    assert re.search(r"\.ew-shelfbtn\s*\{[^}]*display:\s*inline-flex", wide.group(1)), (
        "with the inline back button hidden at this width, nothing opens the shelf"
    )


def test_the_drawer_pushes_the_story_instead_of_covering_it():
    """The drawer must open IN FLOW -- a grid column that moves the story right --
    and never as a viewport-fixed overlay.

    This is not taste. The app is mounted inside the dashboard's own content region,
    which is itself offset right by the dashboard's sidebar, so `position: fixed;
    left: 0` resolves against the VIEWPORT and paints the panel outside the area the
    app can be seen in. It rendered, it was in the DOM, and the reader could not look
    at it -- which is exactly how this shipped once.
    """
    css = styles()
    flat = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    flat = re.sub(r"@media[^{]*\{", "", flat)
    for rule in re.finditer(r"([^{}\n][^{}]*)\{([^}]*)\}", flat):
        selector, body = rule.group(1).strip(), rule.group(2)
        if not re.search(r"\.ew-rail\b", selector):
            continue
        assert not re.search(r"position:\s*fixed", body), (
            selector + " pins the shelf to the viewport, which is not where this app "
            "lives"
        )
    # And the push itself: the open state has to give the story its own track.
    wide = re.search(
        rf"@media \(min-width: {BREAKPOINT}px\)\s*\{{(.*?)\n\}}", css, re.S
    )
    assert wide, "no rule block at the desktop breakpoint"
    grid = re.search(
        r"\.ew-shell-open\s*\{[^}]*grid-template-columns:\s*([^;]+);", wide.group(1)
    )
    assert grid, "the open drawer does not create a column for itself"
    assert "minmax(0" in grid.group(1), (
        "the story's track must be minmax(0, …) or a long unbroken world title "
        "widens it and pushes the prose off the page"
    )


def test_the_cap_moved_off_the_root_so_the_measure_owns_the_page():
    """A 900px root cap would leave a desktop reading in a phone's column. The
    desktop block therefore has to release the root's own cap and let the reading
    column set the measure -- either by widening it or by dropping it entirely, which
    is what the full-bleed backdrop needs."""
    css = styles()
    wide = re.search(
        rf"@media \(min-width: {BREAKPOINT}px\)\s*\{{(.*?)\n\}}", css, re.S
    )
    assert wide, "no rule block at the desktop breakpoint"
    root = re.search(
        r"\.ew-root\s*\{[^}]*max-width:\s*(none|\d+px)", wide.group(1)
    )
    assert root, "the desktop block must release .ew-root's phone/tablet cap"
    if root.group(1) != "none":
        assert int(root.group(1).removesuffix("px")) > 900, (
            "the root cap must exceed the phone/tablet 900px, or a desktop reads the "
            "story in a column sized for a phone"
        )


def test_the_star_map_has_a_way_in_at_every_width():
    """A way into the star map at every width. The desktop opens it from the right
    aside's tab strip; a phone opens it from the bottom bar's 星图 tab. The old bug
    was the opener borrowing `.ew-drawer` (hidden above 900px, so the desktop had no
    entrance at all) -- so neither entrance may sit on a class a width query hides."""
    src = module("play.tsx")
    star = re.search(r"setStarOpen\(true\)", src)
    assert star, "nothing opens the star map on the desktop aside"
    # The opener may be a multi-line handler, so look back a generous window.
    button = src[max(0, star.start() - 600):star.start()]
    assert 'className="ew-aside-tab"' in button, (
        "the desktop star opener lives on the right-aside tab strip"
    )
    # The phone entrance is the bottom bar's built-in 星图 tab.
    bar = module("tabbar.tsx")
    assert "'starmap'" in bar and "tab.starmap" in bar, (
        "the phone bottom bar must carry a 星图 tab"
    )
    # Neither entrance's own class may be hidden by a width query.
    css = styles()
    for cls in (".ew-aside-tab", ".ew-tab"):
        for rule in re.finditer(r"([^{}\n][^{}]*)\{([^}]*)\}", css):
            if cls in rule.group(1) and "focus" not in rule.group(1):
                assert "display: none" not in rule.group(2), (
                    "a star map entrance is hidden by " + rule.group(1).strip()
                )


def test_the_star_map_is_a_backdrop_adaptive_observatory():
    """The backdrop is the room, not wallpaper hidden behind an opaque app shell.

    The readable surfaces therefore need local blur and borders, while the map body
    keeps a transparent stage. On a phone the same hierarchy must reserve the foot
    of the viewport for the portalled tab bar, and a star tap must raise its detail
    into view instead of silently adding content below the current scroll position.
    """
    src = module("memory.tsx")
    assert ".ews-overlay:has(> .ew-backdrop) { background: transparent; }" in src
    assert "backdrop-filter: blur(18px) saturate(1.08)" in src
    assert ".ews-body { gap: 14px; padding: 14px 16px 16px; }" in src
    tabbed = re.search(r"@media \(max-width: 1100px\) \{(.*?)\n\}", src, re.S)
    assert tabbed, "the detail sheet does not cover the full bottom-tab range"
    assert "--ews-tab-clearance: calc(74px + env(safe-area-inset-bottom, 0px))" in tabbed.group(1), (
        "the phone map must clear both the portalled tab bar and the device safe area"
    )
    assert "position: absolute; inset-inline: 10px; bottom: var(--ews-tab-clearance)" in tabbed.group(1), (
        "a selected star's detail must rise into view above the phone tab bar"
    )
    assert "animation: ews-detail-rise .18s ease-out" in tabbed.group(1), (
        "a phone tap needs visible feedback that the detail sheet appeared"
    )
    assert "max-height: 38dvh" in tabbed.group(1), (
        "the detail sheet must leave a visible field of stars above it"
    )
    narrow = re.search(r"@media \(max-width: 860px\) \{(.*?)\n\}", src, re.S)
    assert narrow, "the observatory has no compact narrow-screen composition"
    assert "padding: 8px 10px var(--ews-tab-clearance)" in narrow.group(1), (
        "the compact phone layout must retain the bottom-tab clearance"
    )
    assert 'role="complementary" aria-live="polite"' in src, (
        "selection changes must also be announced without moving keyboard focus"
    )
    assert "window.matchMedia('(max-width: 860px)').matches" in src, (
        "a phone must default to the readable relation list, not a tiny scaled canvas"
    )
    relations = module("memory-layouts/relations.tsx")
    assert "relationReading(lang, r)" in relations
    assert "unrelatedCharacters.map((character)" in relations, (
        "list mode must still show visible people before a formal relation is recorded"
    )
    assert "star.rel.unrecorded" in relations
    assert "r.type}{r.value" not in relations, (
        "the relation list must not expose a raw type plus an unexplained signed level"
    )
    state = module("memory-state.ts")
    assert state.count("'star.rel.unrecorded':") == 2, (
        "the unrecorded-relation label must exist in both star-map languages"
    )


def test_the_rail_marks_exactly_one_row_as_current():
    """Two rows reading as current is the failure the split axes introduce: the
    world stays selected while a life is opened. The rail's own condition has to
    exclude one when the other holds."""
    src = module("rail.tsx")
    assert "activeWorldId === " not in src  # not a plain equality on the world alone
    # The world row's "on" test must be qualified by there being no active life.
    world_on = re.search(r"w\.worldId === activeWorldId([^\n]*)", src)
    assert world_on, "the rail does not mark the selected world at all"
    assert "!activeRunId" in world_on.group(1), (
        "a selected world must stop reading as current once a life is open"
    )


def test_opening_a_world_from_the_rail_clears_the_open_life():
    """The other half of the same rule, on the state side: the component that owns
    both facts must not leave them both set."""
    src = module("main.tsx")
    fn = re.search(r"const openWorld = \(worldId: string\) => \{(.*?)\n  \}", src, re.S)
    assert fn, "the rail's world handler is gone"
    assert "setLive(null)" in fn.group(1), (
        "opening a world must clear the live run, or the rail marks two rows"
    )


def test_the_rail_reuses_the_shelfs_words_for_a_lifes_state():
    """One phrasing per fact. Two vocabularies for the same life state is how a UI
    starts reading as two different apps."""
    src = module("rail.tsx")
    for key in ("life.turn", "life.ended", "life.unborn", "life.unreadable"):
        assert f"'{key}'" in src, f"the rail invented its own wording instead of {key}"


def test_every_string_the_rail_asks_for_exists_in_both_tables():
    """A key present in one table renders as the key itself for the other language
    -- visible, but only to whoever plays in it."""
    src = module("rail.tsx")
    keys = set(re.findall(r"t\('([\w.]+)'", src))
    assert keys, "the rail hardcodes its text instead of looking it up"
    root = WEB_SRC / "strings"
    zh = json.loads((root / "zh.json").read_text(encoding="utf-8"))
    en = json.loads((root / "en.json").read_text(encoding="utf-8"))
    assert not (keys - set(zh)), f"missing from zh.json: {sorted(keys - set(zh))}"
    assert not (keys - set(en)), f"missing from en.json: {sorted(keys - set(en))}"


def test_the_play_view_reads_the_language_without_a_type_assertion():
    """The bug this closes was not a crash: ``(v as unknown as {language?: string})``
    compiled cleanly while the route sent no such field, so the read was dead and
    the type system had been told not to notice."""
    src = module("play.tsx")
    assert "as unknown as" not in src, (
        "an assertion here can hide a field the backend never sends"
    )
    api = module("api.ts")
    play = re.search(r"export interface PlayView \{(.*?)\n\}", api, re.S)
    assert play and re.search(r"^\s*language:", play.group(1), re.MULTILINE), (
        "PlayView must declare the language it is read for"
    )


def test_a_world_title_cannot_widen_the_rail():
    """A world name is user content and can be one unbroken run. Without a wrap rule
    it widens the grid column, which pushes the reading measure sideways -- on a
    desktop, where nobody is looking for a mobile bug."""
    css = styles()
    rule = re.search(r"\.ew-rail-name\s*\{([^}]*)\}", css)
    assert rule, "the rail's title element has no rule"
    assert "overflow-wrap: anywhere" in rule.group(1)


# ── what the screenshot showed ──────────────────────────────────────────────
#
# Three defects visible in one desktop screenshot, each of which had no test.


def test_the_desktop_has_one_way_back_not_two():
    """Two identical "back to the shelf" links stacked in the top-left corner: the
    rail's permanent one, and the view's own inline one three lines below it.

    The rail's is the one that survives, because it is always in the same place. The
    inline button is the phone's only affordance, so it must NOT be hidden globally —
    only inside the block where the rail exists.
    """
    css = styles()
    bare = re.search(r"^\.ew-back\s*\{([^}]*)\}", css, re.MULTILINE)
    assert bare and "display: none" not in bare.group(1), (
        "hiding the inline back button by default would leave a phone with no way "
        "back at all — the rail does not render there"
    )
    wide = re.search(
        rf"@media \(min-width: {BREAKPOINT}px\)\s*\{{(.*?)\n\}}", css, re.S
    )
    assert wide, "no rule block at the desktop breakpoint"
    assert re.search(r"\.ew-back\s*\{[^}]*display:\s*none", wide.group(1)), (
        "with the rail showing, the view's own back button is a second control doing "
        "the same thing"
    )


def test_a_label_that_is_really_a_sentence_stops_columnising():
    """A narrator may put its own wording in a label slot, and on the live flagship it
    put a whole clause there. Squeezed into the fixed 5.5em label column that wrapped
    to ten lines beside a single dot of value.

    Checked in both places, because either half alone does nothing: the component has
    to mark the row, and the stylesheet has to lay it out.
    """
    src = module("ui.tsx")
    assert "ew-prow-stack" in src, "no row is ever marked as carrying a long label"
    assert re.search(r"f\.label\.length >", src), (
        "the decision must be made on the label's own length — CSS cannot measure "
        "text, so there is no container query that can do this"
    )

    css = styles()
    rule = re.search(r"\.ew-prow-stack\s*\{([^}]*)\}", css)
    assert rule, "the stacked row has no layout"
    assert "display: block" in rule.group(1), (
        f"a stacked row must leave the flex row, found: {rule.group(1).strip()}"
    )
    assert re.search(r"\.ew-prow-stack \.ew-plabel\s*\{[^}]*flex:\s*none", css), (
        "the label must give up its fixed column, or stacking changes nothing"
    )


def test_a_life_is_named_by_the_life_not_only_by_the_world():
    """Four rows reading the world's title, three of them also reading "turn 1".
    Choosing between them was guesswork."""
    for where in ("library.tsx", "rail.tsx"):
        src = module(where)
        assert "subtitle" in src, f"{where} still names a life only by its world"


# ── the waiting phrase ──────────────────────────────────────────────────────


def test_the_waiting_phrase_is_chosen_once_not_per_render():
    """A month takes tens of seconds and the page re-reads every few of them. A
    phrase derived during render would cycle through the whole set while the player
    watched — which reads as a glitch, not as flavour.
    """
    src = module("play.tsx")
    assert "pick('play.waiting')" in src, "the variants are never used"
    # Held in state, so a re-paint shows the same words.
    assert "setPhrase(pick(" in src, "the phrase is not stored anywhere"
    assert not re.search(r"label=\{pick\(", src), (
        "picking inside the render re-rolls the phrase on every poll"
    )


def test_both_languages_offer_the_same_number_of_variants():
    """A world played in one language would otherwise have fewer ways to say it — and
    with English as the fallback, a missing zh variant silently shows English mid-run.
    """
    import json

    root = WEB_SRC / "strings"
    zh = json.loads((root / "zh.json").read_text(encoding="utf-8"))
    en = json.loads((root / "en.json").read_text(encoding="utf-8"))
    for prefix in ("play.waiting", "opening.waiting"):
        z = sorted(k for k in zh if k.startswith(prefix + "."))
        e = sorted(k for k in en if k.startswith(prefix + "."))
        assert z == e, f"{prefix} differs: {set(z) ^ set(e)}"
        assert len(z) >= 3, f"{prefix} has {len(z)} variants; too few to feel random"


def test_the_variants_are_contiguous_from_zero():
    """The picker discovers how many exist by walking `.0`, `.1`, … until one is
    missing, so a gap silently truncates the set — add `.7` after deleting `.5` and
    two variants stop being reachable."""
    import json

    zh = json.loads((WEB_SRC / "strings" / "zh.json").read_text(encoding="utf-8"))
    for prefix in ("play.waiting", "opening.waiting"):
        found = sorted(
            int(k.rsplit(".", 1)[1]) for k in zh if k.startswith(prefix + ".")
        )
        assert found == list(range(len(found))), (
            f"{prefix} indices are {found}; the picker stops at the first gap"
        )


def test_a_birth_does_not_borrow_the_phrase_for_a_passing_month():
    """"The years slip by" is the wrong image for a life that has not begun. The
    opening has its own set."""
    src = module("play.tsx")
    assert "pick('opening.waiting')" in src, (
        "the opening screen reuses the month-passing phrases"
    )


def _z(css: str, selector: str) -> int:
    """The z-index a rule declares, so a test can compare layers instead of pinning a
    literal nobody can reason about."""
    m = re.search(re.escape(selector) + r"\s*\{[^}]*z-index:\s*(\d+)", css)
    assert m, f"{selector} declares no z-index"
    return int(m.group(1))


def test_the_reading_row_sits_below_the_host_and_above_the_story():
    """The row is fixed, which puts it at BODY level where it competes with the
    dashboard's own surfaces rather than with the app's.

    So it takes the lowest layer that does its job: above the story it floats over
    (whose lift is 1) and below everything the app itself puts on top — the phone's
    bottom bar, its overflow sheet, the row menus. A high value was copied from the
    bottom bar and had no reason behind it; this row is the first one the app places
    where the host's furniture lives, which is why it was the first to be noticed
    covering it.
    """
    css = styles()
    row = _z(css, ".ew-topbar-fixed")
    assert row > 1, "the row would sit under the story it floats over"
    assert row < _z(css, ".ew-tabbar"), (
        "the row outranks the app's own bottom bar, and at body level a layer that high "
        "also outranks the dashboard's surfaces"
    )
    assert row < _z(css, ".ew-menu"), "a row menu must open OVER the reading row"


def test_the_chrome_offset_is_declared_not_measured():
    """A measured offset returns 0 when read before the host's chrome lays out, and the
    row then sits ON that chrome until something remounts the effect — which in practice
    meant switching a bottom tab. A constant cannot be 0 at the wrong moment.

    The trade is explicit: a number this app does not own lives in exactly one place, so
    a host that changes its chrome is one edit rather than a hunt.
    """
    css = styles()
    assert re.search(r"--ew-chrome-h:\s*\d+px", css), "the offset has no single owner"
    assert re.search(r"\.ew-topbar-fixed\s*\{[^}]*top:\s*var\(--ew-chrome-h\)", css), (
        "the row does not use the declared offset, so it sits at the viewport top"
    )
    assert re.search(r"\.ew-topbar-slot\s*\{[^}]*height:\s*\d+px", css), (
        "nothing holds the row's place, so the world's name slides under it"
    )

    play = module("play.tsx")
    assert "createPortal" in play, (
        "a fixed row must be portalled: inside the shell it resolves against a "
        "transformed ancestor rather than the viewport"
    )
    assert "getBoundingClientRect" not in play, (
        "the offset is measured again, which is the reading that returns 0 too early"
    )
    assert "ResizeObserver" not in play, "an observer is back to keep a number honest"


def test_the_reading_bar_is_pinned_at_both_ends_of_the_page():
    """A 40px threshold let the bar slide away before the reader had passed the text
    it sits over, and a swipe back down slid it in again, so a small gesture near the
    top made it flicker in place. The pin zone is the bar's own footprint.

    The END of the page needs the same pin, and for a sharper reason: hiding there
    uncovers no story, and it is exactly where paging on matters. It used to reappear
    only as a side effect of the rubber band springing back — so the controls became
    unreachable the moment a pane did not bounce.
    """
    bar = module("tabbar.tsx")
    assert "READER_BAR_PIN_PX" in bar, "the pin zone has no named owner"
    assert "pinUntil = 40" in bar, "the default pin zone is gone"
    assert "y < pinUntil" in bar, "the hook no longer pins the bar near the top"
    assert "end < pinUntil" in bar, (
        "the bar is not pinned at the END of the page, so it stays hidden there"
    )
    assert "scrollHeight - el.clientHeight - y" in bar, (
        "distance-to-end is never computed, so the end-of-page pin cannot fire"
    )

    root = module("main.tsx")
    assert "useScrollHide(narrowLive, READER_BAR_PIN_PX)" in root, (
        "the reading bar still rides the bare 40px default"
    )


