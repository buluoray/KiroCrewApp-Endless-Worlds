"""Guards on how the story is set: paragraphs, and the reader's type settings.

The page read as one wall of text for a reason no screenshot of the code shows: the
host's markdown renderer wraps every block in a wrapper of its own and sets its own
paragraph margins and line height, so a `.ew-prose p` gap rule matched every
paragraph as the LAST child of its wrapper and the gap was zero. The fix is that the
app owns the paragraph blocks (``paragraphs.ts``). The behaviour of the split is
tested in ``web/test/paragraphs.test.ts``; these guard the wiring a split alone does
not prove: that the page renders through it, and that the stylesheet spaces OUR
blocks rather than the host's.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from uisrc import WEB_SRC, module, styles

UI_DIR = Path(__file__).resolve().parents[2] / "ui"


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_the_story_is_rendered_one_block_per_paragraph():
    src = module("ui.tsx")
    assert "splitParagraphs(cleaned)" in src, "the prose no longer goes through the split"
    assert "ew-para ew-para-${para.kind}" in src, "a paragraph has no block of its own"
    # The older-host fallback splits too: one <p> per paragraph, not a pre-wrap blob.
    assert "ew-para-plain" in src


def test_the_gap_is_between_the_apps_blocks_not_the_hosts_paragraphs():
    css = styles()
    assert "var(--ew-para-gap)" in _rule(css, ".ew-para + .ew-para")
    # The host sets its paragraphs at line-height 1.5 with margins of its own; inside
    # one of our blocks they must take the block's own type instead.
    assert re.search(r"margin:\s*0", _rule(css, ".ew-para p"))
    assert "line-height: inherit" in _rule(css, ".ew-para :is(p, li, blockquote)")
    assert "p:last-child" not in css.split("/* ── prose ── */")[1].split("/* ── play page")[0], (
        "a last-child margin rule is back: every host paragraph is a last child"
    )


def test_chinese_is_indented_and_set_looser_than_latin():
    css = styles()
    zh = _rule(css, ".ew-prose:lang(zh)")
    assert "--ew-para-indent: 2em" in zh, "Chinese paragraphs lost the two-character indent"
    assert "var(--ew-read-lh-cjk)" in zh
    # The first declaration of each is the default; the leading steps follow it.
    latin = float(re.search(r"--ew-read-lh-latin:\s*([\d.]+)", css).group(1))
    cjk = float(re.search(r"--ew-read-lh-cjk:\s*([\d.]+)", css).group(1))
    assert 1.6 <= latin <= 1.8 and 1.8 <= cjk <= 2.0 and cjk > latin


def test_the_prose_is_told_the_lifes_language():
    """The paragraph style and the CJK face follow the language of the TEXT; the root
    carries the interface's, which a reader can pin to the other one."""
    play = module("play.tsx")
    assert play.count("lang={v.language} />") >= 2, "a story page renders without its language"


def test_every_reading_setting_has_a_label_in_both_tables():
    reading = module("reading.ts")
    tables = {
        lang: json.loads((WEB_SRC / "strings" / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in ("en", "zh")
    }
    for setting, const in (
        ("font", "FONTS"),
        ("size", "SIZES"),
        ("leading", "LEADINGS"),
        ("paragraph", "PARAGRAPHS"),
        ("width", "WIDTHS"),
    ):
        values = re.search(rf"export const {const}: [^=]+= \[([^\]]*)\]", reading)
        assert values, f"{const} is not a literal list"
        keys = [f"read.{setting}.{v}" for v in re.findall(r"'([\w-]+)'", values.group(1))]
        keys.append(f"read.{setting}")
        for lang, table in tables.items():
            missing = [k for k in keys if k not in table]
            assert not missing, f"missing from {lang}.json: {missing}"
    for lang, table in tables.items():
        assert "read.open" in table and "read.glyph" in table, lang


def test_the_panel_is_reachable_from_the_reading_page_at_every_width():
    """The width control used to live in the desktop drawer, which a phone never
    renders. The panel sits in the reading row, which every width has."""
    play = module("play.tsx")
    row = play.split("'ew-topbar ew-topbar-wheel'")[1].split("</div>")[0]
    assert "<ReadingSettings />" in row
    assert "onWidth" not in module("rail.tsx"), "a second width control is back in the drawer"


def test_the_bundled_faces_are_local_licensed_and_small():
    """Same-origin files only: the dashboard's CSP allows `font-src 'self'`, and a font
    CDN would also tell a third party when someone opens a story."""
    reading = module("reading.ts")
    files = re.findall(r"file: '([\w-]+\.woff2)'", reading)
    assert files, "no bundled faces"
    total = 0
    for name in files:
        path = UI_DIR / "fonts" / name
        assert path.is_file(), f"{name} is referenced but not shipped"
        total += path.stat().st_size
    assert total < 250_000, f"bundled faces are {total} bytes"
    for family in {f.split("-")[0] for f in files}:
        licence = [p for p in (UI_DIR / "fonts").glob("OFL-*.txt") if family in p.name.lower()]
        assert licence, f"no licence file ships with {family}"
    for src in (reading, styles()):
        assert not re.search(r"https?://[^\s'\"]*fonts", src), "a remote font URL"
