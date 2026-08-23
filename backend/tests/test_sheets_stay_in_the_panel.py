"""Guards on WHERE the app's full-screen sheets are allowed to reach.

The app is mounted inside the dashboard's own document, so ``position: fixed``
resolves against the WINDOW, not against the app's panel: a sheet pinned that way
paints over the dashboard's own chrome, its left menu included. Anchored to
``.ew-root`` — the app's positioning box — the same sheet covers the app and nothing
outside it.

The trap is that ``absolute`` alone regressed something real once: a reader scrolled
down opened a sheet that stayed behind at the top of the panel, and the story showed
past its edges. That is what viewport pinning was standing in for, and it is why each
sheet scrolls itself to the top of the viewport as it opens. Both halves are needed,
so both are pinned here — for the star map and for the two sheets that copied its
positioning.

The second test covers a different failure with the same symptom: ``var(--fg)`` is not
a Kiro Crew variable (the host's is ``--text``), so every use fell back to a hardcoded
near-white and disappeared on a light dashboard — a white sheet with no content on it.
"""

from __future__ import annotations

import re

from uisrc import WEB_SRC, module

#: (module, overlay class) for every sheet that covers the app.
SHEETS = [
    ("memory.tsx", "ews-overlay"),
    ("legacy.tsx", "ewl-overlay"),
    ("story-card.tsx", "ewc-overlay"),
]


def _rule(css: str, cls: str) -> str:
    """The body of the ``.<cls>`` rule, comments stripped."""
    flat = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = re.search(rf"\.{cls}\s*\{{([^}}]*)\}}", flat)
    assert found, f".{cls} has no rule at all"
    return found.group(1)


def test_no_sheet_reaches_outside_the_app_panel() -> None:
    for name, cls in SHEETS:
        src = module(name)
        body = _rule(src, cls)
        assert "position: absolute" in body, (
            f".{cls} must anchor to the app's own positioning box; "
            "in-flow or static positioning is not what these sheets are"
        )
        # Checked across the whole subtree, not just the overlay rule: the pin can be
        # moved to any ancestor in it and have exactly the same effect.
        for selector, decls in re.findall(
            r"([^{}\n][^{}]*)\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        ):
            if cls.split("-")[0] + "-" not in selector:
                continue
            assert not re.search(r"position:\s*fixed", decls), (
                selector.strip() + " pins a sheet to the window, which is not where this "
                "app lives — it covers the dashboard's own chrome, its left menu included"
            )


def test_every_sheet_brings_itself_into_view_when_it_opens() -> None:
    """Without this, `absolute` is a regression rather than a fix: a sheet opened from
    a scrolled-down page stays behind at the top of the panel and the content it is
    supposed to cover shows past it."""
    for name, _cls in SHEETS:
        src = module(name)
        assert re.search(r"scrollIntoView\(\{\s*block:\s*'start'\s*\}\)", src), (
            f"{name} does not scroll its sheet into view on open"
        )
        # The ref has to be on EVERY branch that renders the sheet — the loading
        # branch is the one mounted first, so a ref only on the settled branch never
        # fires.
        renders = src.count('className="ews-overlay"') + src.count('className="ewl-overlay"')
        renders += src.count('className="ewc-overlay"')
        refs = src.count("ref={sheet}")
        assert refs >= renders, (
            f"{name} renders its sheet {renders}x but only {refs} carry the ref, so the "
            "first-mounted branch cannot scroll into view"
        )


def test_no_ui_surface_paints_with_the_undefined_fg_variable() -> None:
    """``--fg`` is not a Kiro Crew variable; ``--text`` is.

    A fallback literal is not a safety net here, it is the bug: it silently pins one
    hardcoded near-white on a background that follows the host theme, so the text
    disappears the moment the dashboard is light. Checked across the whole UI source,
    not just the star map, because the same line was copied into three sheets.
    """
    offenders = [
        f"{p.name}:{n}"
        for p in sorted(WEB_SRC.rglob("*"))
        if p.suffix in (".ts", ".tsx", ".css")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "var(--fg" in line
    ]
    assert not offenders, (
        "these lines paint with var(--fg), which no theme defines, so they always "
        "fall back to a near-white literal and vanish on a light dashboard: " + ", ".join(offenders)
    )
