"""Text on the app's own canvas stays legible in a light AND a dark dashboard.

Two views paint a ground the app chose, not the dashboard: the shelf's night sky and
the live view, where the narrator's backdrop art fills the room. Their text once
followed the dashboard's tokens, so a light dashboard put its dark ink on that dark
ground. `styles.css` now gives those grounds the app's own ink and, where text sits
on art, a reading veil.

Same method as `test_widget_contrast.py`, for the same reason: no browser can read a
composited contrast reliably, but the pair the app itself declares is decidable.
Each text colour is composited through the app's own surfaces over the worst ground
the art can supply (white and black) and held to WCAG AA: 4.5:1, including the muted
ink, because that ink carries small body text (the date, the pager, panel labels).

Host values below are copied from the dashboard's theme palettes (kiro-light,
kiro-dark, light, dark, amber-light). They are the inputs the app does NOT own, so
the test pins the app's answer against a representative spread of them.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_widget_contrast import _contrast, _over, _parse_colour

_ROOT = Path(__file__).resolve().parents[2]
_STYLES = _ROOT / "web" / "src" / "styles.css"

BODY_FLOOR = 4.5
#: The bare glass, read without its halo: WCAG's floor for large text and UI.
GLASS_FLOOR = 3.0
WHITE = (255.0, 255.0, 255.0)
BLACK = (0.0, 0.0, 0.0)

#: Host accents a canvas view can be handed: kiro (both modes), light, amber-light, dark.
HOST_ACCENTS = ("#8e48ff", "#047558", "#bb4d00", "#00d492")
#: Host card surfaces in DARK dashboards (kiro-dark, dark); light mode uses the app's.
HOST_DARK_CARDS = ("#211d25", "#181b22")
#: (theme, --card, --text) for the pages that keep the dashboard's own tokens.
HOST_THEMES = (
    ("kiro-light", "#ffffff", "#4a464f"),
    ("light", "#ffffff", "#3f3f46"),
    ("kiro-dark", "#211d25", "#dcdadf"),
    ("dark", "#181b22", "#e4e4e7"),
)


def _css() -> str:
    return re.sub(r"/\*.*?\*/", "", _STYLES.read_text(encoding="utf-8"), flags=re.S)


def _rule(selector_pattern: str) -> str:
    found = re.search(selector_pattern + r"\s*\{(.*?)\}", _css(), re.S)
    assert found, f"no rule matched {selector_pattern!r} in styles.css"
    return found.group(1)


def _decl(body: str, prop: str) -> str:
    found = re.search(r"(?:^|[;\s])" + re.escape(prop) + r":\s*([^;]+);", body)
    assert found, f"{prop} is not declared in {body.strip()[:120]!r}"
    return found.group(1).strip()


def _rgb(text: str) -> tuple[float, float, float]:
    return _parse_colour(text)[0]


def _canvas_ink() -> str:
    return _rule(r"\.ew-root\.ew-home,\s*\.ew-root\.ew-view-live,\s*\.ew-tabbar,\s*\.ew-tabmore")


def _light_surfaces() -> str:
    return _rule(
        r'html\[data-mode="light"\] \.ew-root\.ew-home,\s*'
        r'html\[data-mode="light"\] \.ew-root\.ew-view-live,\s*'
        r'html\[data-mode="light"\] \.ew-tabbar,\s*'
        r'html\[data-mode="light"\] \.ew-tabmore'
    )


def _accent_ink(accent: str) -> tuple[float, float, float]:
    """`color-mix(in srgb, <accent> P%, #fff)` — an sRGB mix is a channel-wise lerp."""
    mix = _decl(_canvas_ink(), "--ew-accent-ink")
    found = re.fullmatch(
        r"color-mix\(in srgb, var\(--accent, #[0-9a-fA-F]{6}\) (\d+)%, #fff\)", mix
    )
    assert found, f"--ew-accent-ink is no longer the measured mix: {mix!r}"
    share = int(found.group(1)) / 100
    return _over(_rgb(accent), share, WHITE)


def _inks() -> dict[str, tuple[float, float, float]]:
    body = _canvas_ink()
    inks = {"text": _rgb(_decl(body, "--text")), "muted": _rgb(_decl(body, "--muted"))}
    for accent in HOST_ACCENTS:
        inks[f"accent {accent}"] = _accent_ink(accent)
    return inks


def _worst(ink: tuple[float, float, float], grounds: list[tuple[float, float, float]]) -> float:
    return min(_contrast(ink, g) for g in grounds)


def _veil_rule() -> str:
    return _rule(r"\.ew-root:has\(> \.ew-backdrop\) \.ew-main,[^{]*")


def _page_scrim_top() -> tuple[tuple[float, float, float], float]:
    """The page scrim's LIGHTEST stop: the art is never seen without at least this."""
    found = re.search(
        r"color-mix\(in srgb, var\(--ew-bg, (#[0-9a-fA-F]{6})\) (\d+)%, transparent\)",
        _decl(_rule(r"\.ew-backdrop-scrim"), "background"),
    )
    assert found, ".ew-backdrop-scrim is no longer a --ew-bg gradient"
    return _rgb(found.group(1)), int(found.group(2)) / 100


def _veil_grounds(veil: str) -> list[tuple[float, float, float]]:
    rgb, alpha = _parse_colour(veil)
    scrim, share = _page_scrim_top()
    return [_over(rgb, alpha, _over(scrim, share, art)) for art in (WHITE, BLACK)]


def _halo_grounds(grounds: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """The glyph's own surround: the halo's working layer laid over the glass."""
    rgb, alpha = _parse_colour(_decl(_veil_rule(), "--ew-halo"))
    return [_over(rgb, alpha, g) for g in grounds]


def test_the_canvas_ink_does_not_follow_the_dashboard() -> None:
    """The defect itself: a light dashboard's dark --text on the app's dark ground."""
    body = _canvas_ink()
    for prop in ("--text", "--muted"):
        value = _decl(body, prop)
        assert value.startswith("#"), (
            f"{prop} on the canvas must be the app's own ink, not {value!r}"
        )
    assert "--card" in _light_surfaces(), "a light dashboard would hand the canvas white cards"


def test_text_on_the_reading_veil_holds_over_any_drawing() -> None:
    veil = _veil_rule()
    glass = _decl(veil, "--ew-veil")
    assert _decl(veil, "background") == "var(--ew-veil)"
    assert _decl(veil, "box-shadow").endswith("var(--ew-veil)"), (
        "the veil's feather must be the same glass as its body, or its edge reads as a seam"
    )
    assert "var(--ew-halo)" in _decl(veil, "text-shadow"), "the column's text lost its halo"
    grounds = _veil_grounds(glass)
    for name, ink in _inks().items():
        got = _worst(ink, _halo_grounds(grounds))
        assert got >= BODY_FLOOR, (
            f"{name} ink on its halo is {got:.2f}:1 over the worst drawing, under {BODY_FLOOR}:1"
        )


def test_the_veil_alone_keeps_body_text_readable() -> None:
    """Without the halo (a glyph's interior, a shadow a browser drops), body text holds 3:1."""
    got = _worst(_inks()["text"], _veil_grounds(_decl(_veil_rule(), "--ew-veil")))
    assert got >= GLASS_FLOOR, f"body text on the bare glass is {got:.2f}:1, under {GLASS_FLOOR}:1"


def test_the_veil_lets_the_art_through() -> None:
    """The owner's report: a glass dark enough to carry text alone hid the art."""
    _, alpha = _parse_colour(_decl(_veil_rule(), "--ew-veil"))
    assert alpha <= 0.5, f"the reading glass is {alpha:.2f} opaque; the art goes dark under it"


def test_the_phone_reading_row_is_as_light_as_the_veil() -> None:
    row = _decl(_rule(r"\.ew-topbar-fixed"), "background")
    grounds = _veil_grounds(row)
    assert _parse_colour(row)[1] <= _parse_colour(_decl(_veil_rule(), "--ew-veil"))[1]
    for name, ink in _inks().items():
        got = _worst(ink, _halo_grounds(grounds))
        assert got >= BODY_FLOOR, f"{name} on the phone reading row is {got:.2f}:1"


def test_a_choice_on_the_veil_stays_legible() -> None:
    """A choice is a translucent card ON the veil, in either dashboard polarity."""
    veil = _veil_grounds(_decl(_veil_rule(), "--ew-veil"))
    share = re.search(
        r"var\(--card, #[0-9a-f]+\) (\d+)%", _decl(_rule(r"\.ew-choice"), "background")
    )
    assert share, ".ew-choice is no longer a card mix"
    cards = (_decl(_light_surfaces(), "--card"),) + HOST_DARK_CARDS
    text = _inks()["text"]
    for card in cards:
        grounds = [_over(_rgb(card), int(share.group(1)) / 100, g) for g in veil]
        got = _worst(text, grounds)
        assert got >= BODY_FLOOR, f"a choice on card {card} is {got:.2f}:1"


def test_a_life_card_over_its_own_backdrop_stays_legible() -> None:
    """Shelf rows show the life's art at half opacity under a card-coloured scrim."""
    image_alpha = float(_decl(_rule(r"\.ew-card-bg"), "opacity"))
    top = re.search(
        r"var\(--card, #[0-9a-f]+\) (\d+)%", _decl(_rule(r"\.ew-card-bg-scrim"), "background")
    )
    assert top, ".ew-card-bg-scrim is no longer a card gradient"
    cards = (_decl(_light_surfaces(), "--card"),) + HOST_DARK_CARDS
    for card in cards:
        c = _rgb(card)
        grounds = [
            _over(c, int(top.group(1)) / 100, _over(art, image_alpha, c)) for art in (WHITE, BLACK)
        ]
        for name in ("text", "muted"):
            got = _worst(_inks()[name], grounds)
            assert got >= BODY_FLOOR, f"{name} on a life card ({card}) is {got:.2f}:1"


def test_the_shelf_night_sky_and_the_bare_live_page_carry_the_ink() -> None:
    # The sky's own stops; a var() fallback is the accent glow's hue, not ground.
    sky_css = re.sub(r"var\([^)]*\)", "", _decl(_rule(r"\.ew-home::before"), "background"))
    sky = re.findall(r"#[0-9a-fA-F]{6}", sky_css)
    assert sky, ".ew-home::before no longer paints its night sky"
    bare = _decl(_rule(r'html\[data-mode="light"\] \.ew-root\.ew-view-live::before'), "background")
    grounds = [_rgb(c) for c in sky] + [_rgb(bare)]
    for name, ink in _inks().items():
        got = _worst(ink, grounds)
        assert got >= BODY_FLOOR, f"{name} on the app's own dark ground is {got:.2f}:1"


def test_the_tab_bar_labels_hold_where_they_sit() -> None:
    """Labels sit in the bar's lower half, at or past the gradient's 46% stop."""
    stops = re.findall(r"rgba\([^)]*\)\s+(\d+)%", _decl(_rule(r"\.ew-tabbar"), "background"))
    alphas = re.findall(r"rgba\(\s*\d+,\s*\d+,\s*\d+,\s*([\d.]+)\)\s+46%", _rule(r"\.ew-tabbar"))
    assert stops and alphas, ".ew-tabbar's gradient changed shape; re-derive where labels sit"
    grounds = [_over((6, 7, 14), float(alphas[0]), art) for art in (WHITE, BLACK)]
    got = _worst(_inks()["muted"], grounds)
    assert got >= BODY_FLOOR, f"a tab label is {got:.2f}:1 on the bar"


def test_the_world_title_field_takes_its_ink_from_its_own_theme() -> None:
    """The field's ground is theme-derived, so a fixed cream ink was 1.2:1 in light."""
    rule = _rule(r"\.ew-title-edit")
    assert _decl(rule, "color").startswith("var(--text"), "the title field's ink is fixed again"
    for theme, card, text in HOST_THEMES:
        field = _over(_rgb(card), 0.85, BLACK)
        got = _contrast(_rgb(text), field)
        assert got >= BODY_FLOOR, f"the world title field in {theme} is {got:.2f}:1"


def test_the_scrubber_folio_reads_on_its_own_paper_in_every_theme() -> None:
    """The drag label is an opaque paper slip with fixed ink, so neither the dashboard
    theme nor the page art behind it can take its contrast away."""
    tip = _rule(r"\.ew-scrub-tip")
    paper = _decl(tip, "background")
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", paper), f"the folio paper must be opaque, not {paper!r}"
    ground = _rgb(paper)
    for sel in (r"\.ew-scrub-tip", r"\.ew-scrub-tip-n", r"\.ew-scrub-tip-hint"):
        ink = _decl(_rule(sel), "color")
        assert ink.startswith("#"), f"{sel} ink must be the folio's own, not {ink!r}"
        got = _contrast(_rgb(ink), ground)
        assert got >= BODY_FLOOR, f"{sel} on the folio is {got:.2f}:1"


def _canvas_var(value: str) -> tuple[float, float, float]:
    """`var(--text, …)` / `var(--muted, …)` resolved to the canvas ink it names."""
    found = re.fullmatch(r"var\((--text|--muted), #[0-9a-fA-F]{6}\)", value)
    assert found, f"the wheel's ink must be the canvas ink, not {value!r}"
    return _inks()[found.group(1)[2:]]


def test_the_phone_page_wheel_has_no_card_and_reads_on_the_reading_row() -> None:
    """The wheel's numbers sit straight on the phone's reading row: no paper of their
    own, the canvas ink the row is measured for, in a light and a dark dashboard. The
    centre number is held to AA over the worst art; its fading neighbours may fall."""
    for sel in (r"\.ew-wheel", r"\.ew-wheel-track", r"\.ew-wheel-n", r"\.ew-wheel-c"):
        body = _rule(sel)
        assert not re.search(r"(?:^|[;\s])background(?:-color)?:", body), f"{sel} has a background"
        assert "box-shadow:" not in body and "border:" not in body, f"{sel} is drawn as a card"
    # The row sits inside .ew-main, so its numbers carry the column's inherited halo.
    grounds = _halo_grounds(_veil_grounds(_decl(_rule(r"\.ew-topbar-fixed"), "background")))
    centre = _canvas_var(_decl(_rule(r"\.ew-wheel-c"), "color"))
    got = _worst(centre, grounds)
    assert got >= BODY_FLOOR, f"the wheel's centre number is {got:.2f}:1 on the reading row"
    # The neighbours start from the muted ink, which is itself AA there.
    assert _worst(_canvas_var(_decl(_rule(r"\.ew-wheel-n"), "color")), grounds) >= BODY_FLOOR
