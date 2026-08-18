"""Guards on the desktop rail.

The rail exists because navigation and reading were sharing one axis: the shelf, a
world, the opening screen and the live turn were all the same 900px column, so
switching between two lives meant going back to a list. Splitting the axes is the
kind of change that is easy to get right once and then lose, in two specific ways
these tests are aimed at.

The first is regressing the phone. The narrow layout was not a compromise to be
undone -- it is the baseline the desktop is added on top of -- so a rail that
renders at phone widths would be a strict loss, and it would be invisible to anyone
developing on a desktop.

The second is letting the reading measure grow with the window. A life is read, not
scanned; prose set to the full width of a 2560px monitor is unreadable, and the
failure looks like "the app uses the space well" in a screenshot.
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


def test_the_reading_column_does_not_grow_with_the_window():
    """The measure is capped, and capped in ``ch`` -- a character-relative unit, so
    it tracks the font rather than a pixel guess that breaks when the theme's type
    size changes."""
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


def test_the_cap_moved_off_the_root_so_the_rail_sits_outside_the_measure():
    """A rail inside a 900px cap would eat the prose column rather than sit beside
    it. The desktop block therefore has to raise the root's own cap."""
    css = styles()
    wide = re.search(
        rf"@media \(min-width: {BREAKPOINT}px\)\s*\{{(.*?)\n\}}", css, re.S
    )
    assert wide, "no rule block at the desktop breakpoint"
    root = re.search(r"\.ew-root\s*\{[^}]*max-width:\s*(\d+)px", wide.group(1))
    assert root, "the desktop block must widen .ew-root"
    assert int(root.group(1)) > 900, (
        "the root cap must exceed the phone/tablet 900px, or the rail is taken out "
        "of the reading column instead of added beside it"
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
