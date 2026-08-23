"""The legibility floor for a scene widget, checked where it is actually decidable.

A scene frame is translucent by design: its document paints no ground, and what shows
through is the world's own backdrop art under a dark scrim the APP owns. That makes the
obvious check impossible and the tempting one worthless:

* impossible — the frame is sandboxed without ``allow-same-origin``, so nothing outside
  it may read its computed text colour;
* worthless — two pixel statistics were tried on the rendered frame (luminance spread,
  then edge density) and NEITHER separated a legible frame from one whose text had been
  made invisible: the art showing through carries more variance and more edges than the
  text does. A gate that passes the very bug it names is worse than no gate.

What IS decidable is the pair the app itself chose: its text colours against its own
scrim over the worst ground the art can supply. Blend the scrim over white (the brightest
backdrop possible) and over black (the darkest), compute WCAG contrast for each text
colour against both, and require the floors below. That is deterministic, needs no
browser, and it is exactly the invariant the original defect broke — text that fell back
to near-white on a near-white ground scores 1.0 here.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WIDGET = _ROOT / "backend" / "widget.py"
_STYLES = _ROOT / "web" / "src" / "styles.css"

#: WCAG AA: 4.5 for body text, 3.0 for large or secondary text. The muted colour is
#: deliberately allowed the lower floor — it is labelling, never the only carrier of a
#: fact — but it is not allowed to vanish.
BODY_FLOOR = 4.5
MUTED_FLOOR = 3.0


def _srgb(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_srgb(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _over(
    fg: tuple[float, float, float], alpha: float, bg: tuple[float, float, float]
) -> tuple[float, float, float]:
    """``fg`` at ``alpha`` composited over ``bg``."""
    return tuple(fg[i] * alpha + bg[i] * (1 - alpha) for i in range(3))  # type: ignore[return-value]


def _parse_colour(text: str) -> tuple[tuple[float, float, float], float]:
    """A `#rrggbb` or `rgba(r, g, b, a)` literal as (rgb, alpha)."""
    hexed = re.fullmatch(r"#([0-9a-fA-F]{6})", text.strip())
    if hexed:
        raw = hexed.group(1)
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)), 1.0
    rgba = re.fullmatch(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", text.strip()
    )
    if not rgba:
        raise AssertionError(f"unparseable colour literal: {text!r}")
    r, g, b, a = rgba.groups()
    return (int(r), int(g), int(b)), float(a) if a is not None else 1.0


def _scrim_rule() -> str:
    """The body of the ``.ew-slot`` rule with CSS COMMENTS STRIPPED.

    Stripped because the rule's own comment explains why `backdrop-filter` lives there,
    and a bare substring test is then satisfied by the prose rather than by the
    declaration — the assertion passes with the blur deleted, which is how this test
    first lied to me.
    """
    css = _STYLES.read_text(encoding="utf-8")
    rule = re.search(r"\.ew-slot\s*\{(.*?)\}", css, re.S)
    assert rule, ".ew-slot has no rule; the scene frame's scrim moved or was removed"
    return re.sub(r"/\*.*?\*/", "", rule.group(1), flags=re.S)


def _scrim() -> tuple[tuple[float, float, float], float]:
    """The `.ew-slot` background: the app-owned scrim every scene is read through."""
    found = re.search(r"background:\s*([^;]+);", _scrim_rule())
    assert found, ".ew-slot declares no background, so scenes are read through nothing"
    return _parse_colour(found.group(1))


def _widget_colour(pattern: str) -> tuple[tuple[float, float, float], float]:
    src = _WIDGET.read_text(encoding="utf-8")
    found = re.search(pattern, src)
    assert found, f"no colour matched {pattern!r} in widget.py's stylesheet"
    return _parse_colour(found.group(1))


def _worst_contrast(colour: tuple[tuple[float, float, float], float]) -> float:
    """The lower of this colour's contrast over the scrim on white and on black art."""
    rgb, alpha = colour
    scrim_rgb, scrim_alpha = _scrim()
    ratios = []
    for art in ((255, 255, 255), (0, 0, 0)):
        ground = _over(scrim_rgb, scrim_alpha, art)
        # A translucent text colour is itself composited over that ground.
        ink = _over(rgb, alpha, ground)
        ratios.append(_contrast(ink, ground))
    return min(ratios)


def test_scene_body_text_stays_legible_over_any_backdrop() -> None:
    got = _worst_contrast(_widget_colour(r"body \{[^}]*?color:\s*([^;]+);"))
    assert got >= BODY_FLOOR, (
        f"a scene's body text contrasts {got:.2f}:1 against its own scrim over the "
        f"worst-case backdrop, under the {BODY_FLOOR}:1 floor — on a bright world "
        "illustration this is the text that disappears"
    )


def test_scene_muted_text_stays_visible_over_any_backdrop() -> None:
    got = _worst_contrast(_widget_colour(r"\.k \{ color:\s*([^;]+);"))
    assert got >= MUTED_FLOOR, (
        f"a scene's labels contrast {got:.2f}:1 against its own scrim over the "
        f"worst-case backdrop, under the {MUTED_FLOOR}:1 floor — a ledger whose keys "
        "vanish reads as blank rows, which this app has shipped once already"
    )


def test_the_scene_frame_is_read_through_an_app_owned_scrim() -> None:
    """The frost is what makes the transparency safe; without it a light dashboard or a
    bright illustration decides the contrast, which is how the white-on-white bug got
    in. Pinned so removing the scrim cannot pass as 'simplifying'."""
    _rgb, alpha = _scrim()
    assert 0.3 <= alpha < 1.0, (
        f".ew-slot's scrim alpha is {alpha}; below ~0.3 the art decides legibility and "
        "at 1.0 the frame is an opaque slab again, which is what the frost replaced"
    )
    css = _scrim_rule()
    assert re.search(r"(?:^|\s)backdrop-filter:\s*[^;]*blur", css), (
        ".ew-slot declares no backdrop-filter blur: the blur is what keeps sharp art "
        "from competing with the text sitting on it"
    )
