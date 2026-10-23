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


def _veil_grounds(veil: str) -> list[tuple[float, float, float]]:
    rgb, alpha = _parse_colour(veil)
    return [_over(rgb, alpha, art) for art in (WHITE, BLACK)]


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
    veil = _rule(r"\.ew-root:has\(> \.ew-backdrop\) \.ew-main,[^{]*")
    grounds = _veil_grounds(_decl(veil, "background"))
    assert _decl(veil, "box-shadow").endswith(_decl(veil, "background")), (
        "the veil's spread must be the same glass as its body, or its edge reads as a seam"
    )
    for name, ink in _inks().items():
        got = _worst(ink, grounds)
        assert got >= BODY_FLOOR, (
            f"{name} ink on the reading veil is {got:.2f}:1 over the worst drawing, "
            f"under {BODY_FLOOR}:1"
        )


def test_the_phone_reading_row_is_as_dark_as_the_veil() -> None:
    grounds = _veil_grounds(_decl(_rule(r"\.ew-topbar-fixed"), "background"))
    for name, ink in _inks().items():
        got = _worst(ink, grounds)
        assert got >= BODY_FLOOR, f"{name} on the phone reading row is {got:.2f}:1"


def test_a_choice_on_the_veil_stays_legible() -> None:
    """A choice is a translucent card ON the veil, in either dashboard polarity."""
    veil = _veil_grounds(
        _decl(_rule(r"\.ew-root:has\(> \.ew-backdrop\) \.ew-main,[^{]*"), "background")
    )
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
