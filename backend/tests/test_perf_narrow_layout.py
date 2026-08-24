"""A column a phone drops has to be readable SOMEWHERE, and only once.

The performance page is the app's one wide table: eight columns of numbers, which at
390px cannot lay out without pushing content off the side. It is not card-stacked —
reflowing a table with `display` costs its semantics, and cards suit lookup while this
page exists to compare turns — so the narrow layout drops the secondary columns from
their own cells and the row's expansion carries them instead.

That arrangement has two failure modes, and both are the same defect: the list of
dropped columns and the list of facts the expansion carries disagreeing.

* A column dropped with nowhere to read it is WCAG **F102**, a documented failure of
  1.4.10 rather than a judgment call — the number is simply gone on a phone.
* A column shown in the expansion *and* in its own cell is the same value twice on one
  screen, which is what makes a disclosure feel like it padded itself.

So there is one list, `NARROW_HIDDEN`, and this pins every consumer to it. The tests
read source because the app has no JS test runner; what they check is the invariant, not
the wording.
"""

from __future__ import annotations

import re

from uisrc import module, styles

_PERF = "perf.tsx"

#: `<th className="ew-perf-rest">{t('perf.x')}</th>` — the header cells the narrow
#: layout hides. Matched on the class and the catalog key together so a cell that
#: grows a second class, or a key that moves, shows up here rather than passing.
_HIDDEN_HEADER = re.compile(r"className=\"ew-perf-rest\">\{t\('([^']+)'\)\}")

#: The one list both sides read.
_DECLARED = re.compile(r"const NARROW_HIDDEN = \[(.*?)\] as const", re.DOTALL)


def _declared_keys() -> list[str]:
    body = _DECLARED.search(module(_PERF))
    assert body, "NARROW_HIDDEN is gone — the pairing has no single source any more"
    return re.findall(r"'([^']+)'", body.group(1))


def test_every_hidden_column_is_declared_in_the_one_list() -> None:
    """A cell hidden on a phone must be a member of the list, not an ad-hoc class.

    A `ew-perf-rest` added directly to a cell hides a column that the expansion was
    never told to carry — the F102 half, and the half that is invisible when the
    page is only ever looked at on a desktop.
    """
    declared = set(_declared_keys())
    hidden = set(_HIDDEN_HEADER.findall(module(_PERF)))
    assert hidden, "no columns are marked narrow-hidden; the narrow layout is gone"
    assert hidden <= declared, (
        "these columns are hidden on a phone but are not in NARROW_HIDDEN, so the "
        f"expansion does not carry them and they are unreadable there: {sorted(hidden - declared)}"
    )


def test_every_declared_key_is_actually_a_hidden_column() -> None:
    """And the reverse: a key in the list whose column is NOT hidden.

    That one is silent in the other direction — the fact is suppressed above 768px
    on the grounds that the column shows it, while the column was never hidden
    below it, so the value disappears from the expansion for no reason.
    """
    declared = set(_declared_keys())
    hidden = set(_HIDDEN_HEADER.findall(module(_PERF)))
    assert declared <= hidden, (
        "these keys claim to be columns a phone drops, but no header cell is marked "
        f"`ew-perf-rest` for them: {sorted(declared - hidden)}"
    )


def _media_blocks(css: str, query: str) -> str:
    """Every ``@media`` block with this query, joined.

    Two reasons this is not a regex and not a single lookup. A regex cannot stay
    inside one block — it holds nested rules, so any character class written to
    bound it stops at the first `}` of the first rule, which is how the first
    version of this test failed on correct CSS. And the stylesheet has SEVERAL
    blocks per breakpoint (each written next to the rules it is about), so taking
    the first one reads someone else's block and reports this page's rule missing.

    Comments are stripped first: a `{` inside one would throw off the matching.
    """
    plain = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    out: list[str] = []
    for match in re.finditer(re.escape(query) + r"\s*\{", plain):
        depth = 0
        start = match.end() - 1
        for i in range(start, len(plain)):
            if plain[i] == "{":
                depth += 1
            elif plain[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append(plain[start : i + 1])
                    break
        else:
            raise AssertionError(f"unbalanced braces after {query!r}")
    assert out, f"no {query!r} block in the stylesheet"
    return "\n".join(out)


def test_both_halves_of_the_arrangement_exist_in_the_stylesheet() -> None:
    """The classes are inert without their rules, and each has exactly one job.

    `ew-perf-rest` hides a cell BELOW the breakpoint; `ew-perf-fact-dup` hides its
    stand-in ABOVE it. Swapped or missing, the page either shows every value twice
    or loses half of them, and the source scan above cannot see that.
    """
    css = styles()
    narrow = _media_blocks(css, "@media (max-width: 767px)")
    wide = _media_blocks(css, "@media (min-width: 768px)")
    assert ".ew-perf-rest { display: none" in narrow, (
        "`.ew-perf-rest` must be hidden below 768px — that is what drops the "
        "secondary columns on a phone"
    )
    assert ".ew-perf-fact-dup { display: none" in wide, (
        "`.ew-perf-fact-dup` must be hidden at and above 768px — otherwise the "
        "expansion repeats columns the table is already showing"
    )
    assert ".ew-perf-fact-dup" not in narrow, (
        "hiding the stand-in on a phone too would leave the dropped columns "
        "unreadable at every width"
    )
    assert ".ew-perf-rest" not in wide, (
        "hiding the cells above the breakpoint as well would drop the columns at "
        "every width, with the expansion's stand-ins hidden there too"
    )


def test_the_table_scrolls_inside_a_reachable_region() -> None:
    """Reflow exempts a data table, not the page around it — and not by default.

    The exemption is only earned if the overflow is CONTAINED and the container is
    reachable: `tabindex` so a keyboard user can scroll it (axe's
    `scrollable-region-focusable`), and a role plus a name because anything
    focusable needs both. Putting any of it on the `<table>` instead stops it
    scrolling and destroys the table semantics this layout was chosen to keep.
    """
    src = module(_PERF)
    assert 'className="ew-perf-scroll"' in src
    assert 'role="region"' in src, "a focusable scroller needs a role"
    assert 'aria-labelledby="ew-perf-caption"' in src, "and a name, taken from the caption"
    assert "tabIndex={0}" in src, "and a tab stop, since the table holds nothing focusable"
    assert 'id="ew-perf-caption"' in src, "the caption it is named by has to exist"
    assert "overflow-x: auto" in styles().split(".ew-perf-scroll")[1][:120], (
        "the overflow belongs on the region, not on the table"
    )


def test_the_row_disclosure_is_a_real_button() -> None:
    """A `<tr>` takes no focus and announces no state.

    Hanging the expansion off a row click makes it mouse-only and silent to a
    screen reader, which is the easy version of this control and the wrong one.
    """
    src = module(_PERF)
    assert 'className="ew-perf-open"' in src
    assert "aria-expanded={open}" in src, "the control has to say whether it is open"
    assert "aria-controls={`ew-perf-stages-" in src, "and name what it opens"
    assert re.search(r"\.ew-perf-open \{[^}]*min-height: 44px", styles()), (
        "the one control on this page a finger has to hit needs a 44px target"
    )
