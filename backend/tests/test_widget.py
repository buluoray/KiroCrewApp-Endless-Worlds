"""Scene compiler tests — the app's trust boundary.

The properties held here are the ones that make "model bytes never reach the DOM
as markup" true. Each is tested as a property of the OUTPUT, not of the code
shape, because the output is what the browser sees.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import widget as w  # noqa: E402
from widget import (  # noqa: E402
    CSP,
    ELEMENT_KINDS,
    MAX_COLUMNS,
    MAX_ELEMENTS,
    MAX_ROWS,
    MAX_SPEC_BYTES,
    MAX_TEXT,
    SCENE_SCRIPT,
    SceneSpecError,
    compile_cached,
    compile_scene,
    resolve_bind,
    scene_warnings,
    spec_digest,
    widget_path,
)

STATE = {"turn": 3, "magic": {"mana": 40, "cap": 100}, "status": {"age": "十五岁"}}
SIMPLE = {"title": "北境", "elements": [{"kind": "text", "text": "雪停了。"}]}


# -- the policy comes first ----------------------------------------------


def test_the_csp_precedes_every_generated_byte():
    """A policy that arrives after the content it governs has already lost."""
    out = compile_scene("map", SIMPLE, STATE)
    csp_at = out.index("Content-Security-Policy")
    for generated in ("北境", "雪停了。"):
        assert csp_at < out.index(generated), f"{generated!r} precedes the policy"
    assert out.index("<style") > csp_at
    assert out.index("<script") > csp_at


def test_the_policy_closes_every_route_out():
    for clause in (
        "default-src 'none'",
        "connect-src 'none'",
        "form-action 'none'",
        "base-uri 'none'",
        "img-src data:",
    ):
        assert clause in CSP
    assert "http" not in CSP, "no host is ever allowed"
    assert "*" not in CSP


def test_nothing_is_loaded_from_anywhere():
    """Inline everything, load nothing — so there is no request to intercept and
    no third party to trust."""
    out = compile_scene("map", SIMPLE, STATE)
    assert "src=" not in out.replace("data-scene=", "")
    assert "href=" not in out
    assert "//" not in out.replace("<!DOCTYPE", "")


# -- the script is a constant --------------------------------------------


def test_the_only_script_is_the_apps_own_constant():
    """This is what makes ``script-src 'unsafe-inline'`` defensible. The moment
    narrator text could reach script context, escaping stops being the boundary
    it claims to be."""
    out = compile_scene("map", SIMPLE, STATE)
    assert out.count("<script") == 1
    assert SCENE_SCRIPT in out


def test_the_frame_reports_its_own_content_height():
    """The host cannot measure inside the frame — it has an opaque origin — so a
    scene that is not exactly the stylesheet's fallback height can only be sized
    from the document's own report. Without it every scene is one fixed height: a
    short ledger sits in a dead band, and a map's last row is clipped off with no
    way to scroll to it.

    Measured as the CONTENT's extent — the furthest child's bottom plus its own
    bottom margin, plus the body's bottom padding — and never as the body's or the
    documentElement's own box. Both of those track the frame's viewport when the
    document is shorter than the frame, so a frame sized from either can never
    shrink; a phone showed a body inflated well past its content.
    """
    out = compile_scene("map", SIMPLE, STATE)
    assert "height:" in SCENE_SCRIPT and "ResizeObserver" in SCENE_SCRIPT
    assert "b.children" in SCENE_SCRIPT, "the report does not measure the content"
    assert "marginBottom" in SCENE_SCRIPT, "a child's own bottom margin is content too"
    assert "paddingBottom" in SCENE_SCRIPT
    for box in (
        "body.getBoundingClientRect().height",
        "documentElement.getBoundingClientRect",
        "body.scrollHeight",
        "documentElement.scrollHeight",
    ):
        assert box not in SCENE_SCRIPT, f"{box} tracks the frame, not the content"
    assert SCENE_SCRIPT in out


def test_a_grid_row_is_sized_by_its_content_not_by_the_room_around_it():
    """`align-content` defaults to stretch, so a grid box taller than its rows hands
    the surplus out among them: six short map labels became 236px boxes holding 57px
    of text. Two independent latches, because what gives the box that height on a
    phone is not reproducible off-device — and one of them silently doing nothing
    must not be the difference between a map and a column of empty panes.
    """
    style = compile_scene("map", SIMPLE, STATE).split("<style>", 1)[1].split("</style>", 1)[0]
    grid = style.split(".grid {", 1)[1].split("}", 1)[0]
    assert "align-content: start" in grid
    assert "grid-auto-rows: min-content" in grid
    # Third latch: iOS WebKit still stretched cells to a mis-sized track with only
    # the first two, so cells must not stretch — each takes its own content height.
    assert "align-items: start" in grid


def test_the_documents_canvas_is_painted_not_just_its_body():
    """A document shorter than its frame leaves the remainder painted by the CANVAS.
    With only ``body`` coloured, that remainder is transparent and the host page
    shows through — which under a light dashboard theme put the scene on a pale
    slab. The canvas has to carry the colour too."""
    out = compile_scene("map", SIMPLE, STATE)
    style = out.split("<style>", 1)[1].split("</style>", 1)[0]
    assert re.search(r"html\s*\{[^}]*background:\s*#0b0c10", style), (
        "the scene's canvas has no background of its own"
    )


def test_narrator_text_never_reaches_script_context():
    spec = {
        "title": "</script><script>alert(1)</script>",
        "elements": [
            {"kind": "text", "text": "</script><script>fetch('http://evil')</script>"},
            {"kind": "choice", "id": "go", "label": "'); alert(1); //"},
        ],
    }
    out = compile_scene("map", spec, STATE)
    assert out.count("<script") == 1, "a second script element appeared"
    # The one script present is byte-identical to the constant.
    scripts = re.findall(r"<script>.*?</script>", out, re.S)
    assert scripts == [SCENE_SCRIPT], "the emitted script is not the app's constant"


# -- narrator strings are content, never markup -------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "<img src=x onerror=alert(1)>",
        '"><svg onload=alert(1)>',
        "<iframe src=http://evil></iframe>",
        "</td></table><script>x</script>",
        "javascript:alert(1)",
        "<style>body{display:none}</style>",
    ],
)
def test_hostile_text_is_escaped_not_rendered(hostile):
    spec = {"elements": [{"kind": "text", "text": hostile}]}
    out = compile_scene("map", spec, STATE)
    body = out.split("<body>", 1)[1]
    assert "<img" not in body
    assert "<svg" not in body
    assert "<iframe" not in body
    assert "onerror" not in body or "&" in body
    assert body.count("<script") == 1  # only the constant


def test_a_quote_cannot_break_out_of_an_attribute():
    """The word "onclick" appearing as visible TEXT is harmless; what must not
    exist is a live attribute. Asserted that way round, because an earlier version
    of this test un-escaped the output first and then failed on its own content."""
    spec = {"elements": [{"kind": "choice", "id": "go", "label": 'x" onclick="alert(1)'}]}
    out = compile_scene("map", spec, STATE)
    assert 'onclick="' not in out, "a live event attribute was emitted"
    assert "&quot;" in out, "the quote was not escaped at all"


def test_a_spec_carrying_markup_fields_is_refused_outright():
    for banned in ("html", "innerHTML", "script", "srcdoc", "style"):
        with pytest.raises(SceneSpecError) as exc:
            compile_scene("map", {banned: "<b>x</b>", "elements": [{"kind": "divider"}]}, STATE)
        assert banned in exc.value.field


# -- the closed set ------------------------------------------------------


def test_an_unknown_kind_is_dropped_and_the_rest_of_the_scene_renders():
    """Fail-soft: an unknown kind emits no markup (the closed set still holds) but
    the element is dropped and recorded, rather than blanking the whole scene."""
    spec = {
        "elements": [
            {"kind": "text", "text": "留下来的"},
            {"kind": "iframe", "src": "http://evil"},
        ]
    }
    out = compile_scene("map", spec, STATE)
    assert "留下来的" in out  # the good element survived
    assert "<iframe" not in out  # the unknown kind produced no tag
    warnings = scene_warnings("map", spec, STATE)
    assert warnings == [{"index": 1, "field": "elements[1].kind", "reason": warnings[0]["reason"]}]
    assert "iframe" in warnings[0]["reason"]


def test_every_declared_kind_actually_compiles():
    """A kind in the set that the compiler cannot emit would be a scene that
    fails only when a narrator finally tries it."""
    samples = {
        "heading": {"kind": "heading", "text": "标题"},
        "text": {"kind": "text", "text": "一句话"},
        "note": {"kind": "note", "text": "一句小字"},
        "stat": {"kind": "stat", "label": "魔力", "value": 40, "max": 100},
        "bar": {"kind": "bar", "label": "体力", "value": 3, "max": 10},
        "keyvalue": {"kind": "keyvalue", "label": "年龄", "value": "十五岁"},
        "list": {"kind": "list", "items": ["剑", "护符"]},
        "table": {"kind": "table", "columns": ["名字"], "rows": [["母亲"]]},
        "choice": {"kind": "choice", "id": "go", "label": "走"},
        "divider": {"kind": "divider"},
        "grid": {"kind": "grid", "columns": 2, "cells": [{"label": "王庭"}, {"label": "矿脉"}]},
        "links": {
            "kind": "links",
            "nodes": [{"id": "a", "label": "王"}, {"id": "b", "label": "臣"}],
            "edges": [{"from": "a", "to": "b"}],
        },
        "tree": {
            "kind": "tree",
            "nodes": [{"id": "r", "label": "祖"}, {"id": "c", "label": "子", "parent": "r"}],
        },
    }
    assert set(samples) == set(ELEMENT_KINDS), "a kind has no sample here"
    for kind, el in samples.items():
        out = compile_scene("map", {"elements": [el]}, STATE)
        assert "<body>" in out, kind


# -- binds -------------------------------------------------------------


def test_a_bind_reads_the_same_state_the_panels_read():
    spec = {"elements": [{"kind": "stat", "label": "魔力", "bind": "magic.mana", "max": 100}]}
    out = compile_scene("map", spec, STATE)
    assert "40" in out
    assert "width:40%" in out


def test_a_keyvalue_renders_a_pairs_block_as_rows():
    """A keyvalue may carry a `pairs` array (a labelled ledger of key/value rows),
    not only a single label/value. Before this, `pairs` was ignored and the element
    rendered ONE empty row, so a whole 食物/饮水/药品 ledger looked blank."""
    spec = {
        "elements": [
            {
                "kind": "keyvalue",
                "pairs": [
                    {"key": "存货", "value": "整车囤货，约178天"},
                    {"key": "两人消耗", "value": "实际约90天"},
                ],
            },
        ]
    }
    out = compile_scene("map", spec, STATE)
    assert "存货" in out and "整车囤货，约178天" in out
    assert "两人消耗" in out and "实际约90天" in out
    assert out.count('<div class="r">') == 2, "one row per pair, not one empty row"
    # A single label/value still works (backward compatible).
    single = compile_scene(
        "map", {"elements": [{"kind": "keyvalue", "label": "年龄", "value": "十五岁"}]}, STATE
    )
    assert "年龄" in single and "十五岁" in single


def test_an_unresolvable_bind_falls_back_to_the_literal():
    """A typo'd bind is no longer fatal: it falls back to the element's own literal
    value/text so the scene still shows something truthful the narrator wrote."""
    spec = {
        "elements": [
            {"kind": "stat", "label": "x", "bind": "magic.nope", "value": "40"},
        ]
    }
    out = compile_scene("map", spec, STATE)
    assert "40" in out


def test_an_unresolvable_bind_with_no_literal_drops_only_that_element():
    """No bind and no literal means nothing to show — that one element is dropped
    (and recorded), the rest of the scene survives."""
    spec = {
        "elements": [
            {"kind": "text", "text": "还在"},
            {"kind": "stat", "label": "x", "bind": "magic.nope"},
        ]
    }
    out = compile_scene("map", spec, STATE)
    assert "还在" in out
    warnings = scene_warnings("map", spec, STATE)
    assert [w["index"] for w in warnings] == [1]
    assert warnings[0]["field"] == "elements[1].bind"


@pytest.mark.parametrize("bad", ["../secret", "magic..mana", "magic.mana()", "", "__class__.x"])
def test_a_malformed_bind_path_is_refused(bad):
    with pytest.raises(SceneSpecError):
        resolve_bind(bad, STATE)


def test_a_bind_cannot_walk_into_python_internals():
    with pytest.raises(SceneSpecError):
        resolve_bind("__class__", STATE)


# -- size -------------------------------------------------------------


def test_an_oversized_spec_is_refused():
    spec = {"elements": [{"kind": "text", "text": "字" * 300} for _ in range(MAX_ELEMENTS)]}
    size = len(json.dumps(spec, ensure_ascii=False).encode("utf-8"))
    assert size > MAX_SPEC_BYTES
    with pytest.raises(SceneSpecError) as exc:
        compile_scene("map", spec, STATE)
    assert exc.value.field == "spec"


def test_too_many_elements_is_truncated_not_refused():
    """A legibility cap, not a trust boundary: render the first MAX_ELEMENTS and
    drop the tail rather than blanking the whole scene."""
    spec = {"elements": [{"kind": "divider"} for _ in range(MAX_ELEMENTS + 5)]}
    out = compile_scene("map", spec, STATE)
    assert out.count("<hr>") == MAX_ELEMENTS


def test_an_empty_spec_is_refused():
    with pytest.raises(SceneSpecError):
        compile_scene("map", {"elements": []}, STATE)


def test_a_ragged_table_row_is_padded_and_truncated_to_the_columns():
    """A short row is padded, a long row is truncated — the table still renders
    rather than 422-ing the whole scene."""
    spec = {
        "elements": [{"kind": "table", "columns": ["a", "b"], "rows": [["1"], ["2", "3", "4"]]}]
    }
    out = compile_scene("map", spec, STATE)
    # Two body rows, each with exactly two cells (2 columns).
    rows = re.findall(r"<tr>(.*?)</tr>", out.split("<tbody>", 1)[1], re.S)
    assert len(rows) == 2
    for row in rows:
        assert row.count("<td>") == 2
    assert "4" not in out.split("<tbody>", 1)[1]  # the overflowing cell was cut


def test_one_bad_element_is_dropped_and_the_good_ones_render():
    """A legible partial beats a blank frame: a bad element is dropped and the
    surrounding elements still render, unlike the old whole-scene refusal."""
    spec = {
        "elements": [
            {"kind": "text", "text": "好的"},
            {"kind": "nope"},
            {"kind": "text", "text": "也好"},
        ]
    }
    out = compile_scene("map", spec, STATE)
    assert "好的" in out and "也好" in out
    assert [w["index"] for w in scene_warnings("map", spec, STATE)] == [1]


# -- bars ---------------------------------------------------------------


def test_a_bar_over_its_cap_does_not_overflow():
    spec = {"elements": [{"kind": "bar", "label": "x", "value": 500, "max": 100}]}
    assert "width:100%" in compile_scene("map", spec, STATE)


def test_a_zero_cap_draws_no_bar_rather_than_dividing_by_zero():
    spec = {"elements": [{"kind": "bar", "label": "x", "value": 5, "max": 0}]}
    assert 'class="t"' not in compile_scene("map", spec, STATE)


# -- caching, under the run --------------------------------------------


def test_compiled_bytes_live_under_the_run_not_the_world(tmp_path):
    """Specs travel between players; compiled bytes do not. This is what keeps
    "widget bytes are always locally produced" true for a pack from elsewhere."""
    p = widget_path(tmp_path, "run-1", "map")
    assert p == tmp_path / "runs" / "run-1" / "widgets" / "map.html"
    assert "worlds" not in str(p)


def test_an_unchanged_spec_is_reused(tmp_path):
    html1, cached1 = compile_cached(tmp_path, "run-1", "map", SIMPLE, STATE)
    html2, cached2 = compile_cached(tmp_path, "run-1", "map", SIMPLE, STATE)
    assert cached1 is False and cached2 is True
    assert html1 == html2


def test_a_changed_spec_is_recompiled(tmp_path):
    compile_cached(tmp_path, "run-1", "map", SIMPLE, STATE)
    other = {"title": "南境", "elements": [{"kind": "text", "text": "雪停了。"}]}
    _html, cached = compile_cached(tmp_path, "run-1", "map", other, STATE)
    assert cached is False


def test_a_moved_bound_value_busts_the_cache(tmp_path):
    """A cache hit must mean "the same picture", not "the same description" — a
    bound scene showing last month's numbers is the drift this module prevents."""
    spec = {"elements": [{"kind": "stat", "label": "魔力", "bind": "magic.mana", "max": 100}]}
    compile_cached(tmp_path, "run-1", "map", spec, STATE, bound_slice={"magic.mana": 40})
    _html, cached = compile_cached(
        tmp_path, "run-1", "map", spec, {"magic": {"mana": 90}}, bound_slice={"magic.mana": 90}
    )
    assert cached is False


def test_a_compiler_bump_busts_every_cache():
    a = spec_digest(SIMPLE)
    w.COMPILER += 1
    try:
        assert spec_digest(SIMPLE) != a
    finally:
        w.COMPILER -= 1


def test_an_unreadable_cache_is_a_miss_not_a_failure(tmp_path):
    compile_cached(tmp_path, "run-1", "map", SIMPLE, STATE)
    widget_path(tmp_path, "run-1", "map").with_suffix(".sha256").write_text("garbage")
    _html, cached = compile_cached(tmp_path, "run-1", "map", SIMPLE, STATE)
    assert cached is False


@pytest.mark.parametrize("bad", ["../escape", "A", "", "a/b"])
def test_a_malformed_id_never_becomes_a_path(tmp_path, bad):
    with pytest.raises(SceneSpecError):
        widget_path(tmp_path, bad, "map")
    with pytest.raises(SceneSpecError):
        compile_scene(bad, SIMPLE, STATE)


# -- no drawn framing reaches the DOM ----------------------------------


def test_no_box_drawing_character_survives_into_a_scene():
    """R18 — the app renders structure as structure; a drawn box is not
    structure."""
    spec = {"elements": [{"kind": "text", "text": "╔════╗ 魔力 ████░░ ╚════╝"}]}
    out = compile_scene("map", spec, STATE)
    for ch in "╔═╗╚╝█░│─":
        assert ch not in out, f"{ch!r} reached the DOM"


# -- spatial / relational kinds: structure in, geometry computed here ------


def _scene(el: dict) -> str:
    return compile_scene("map", {"elements": [el]}, STATE)


def _body(out: str) -> str:
    """The rendered half only. A negative assertion about a CLASS has to be made
    here: the stylesheet names every class it styles, so `"gmk" not in out` fails on
    the rule that draws it rather than on any element."""
    return out.split("<body>", 1)[1]


def test_grid_lays_cells_into_columns_and_escapes_labels():
    out = _scene(
        {
            "kind": "grid",
            "columns": 3,
            "cells": [
                {"label": "王庭", "mark": True},
                {"label": "<b>矿脉</b>", "note": "危险"},
            ],
        }
    )
    assert "grid-template-columns:repeat(3,1fr)" in out
    assert "gc gm" in out  # the marked cell
    assert "<b>矿脉</b>" not in out  # label escaped
    assert "&lt;b&gt;矿脉&lt;/b&gt;" in out
    assert "危险" in out


def test_a_cells_symbol_mark_is_rendered_and_does_not_tint_every_cell():
    """A map's cells are told apart by their own symbols. Treating any mark as a
    whole-cell tint dropped those symbols on the floor AND, because a narrator marks
    every cell of a map, tinted all of them identically — a highlight that highlights
    everything says nothing.
    """
    out = _scene(
        {
            "kind": "grid",
            "columns": 3,
            "cells": [
                {"label": "市区", "mark": "⚠"},
                {"label": "据点", "mark": "🏠", "note": "楼梯已封"},
                {"label": "安置点", "mark": "🔥"},
            ],
        }
    )
    for glyph in ("⚠", "🏠", "🔥"):
        assert f'<span class="gmk">{glyph}</span>' in out
    assert "gc gm" not in _body(out), "a symbol must not also tint the cell"


def test_a_symbol_mark_passes_the_same_stripper_as_any_narrator_text():
    """`_esc` runs the shared framing stripper, which removes a variation selector —
    so an emoji written as ``☠️`` (U+2620 U+FE0F) renders as its base codepoint. The
    badge still appears; this pins that it is not silently lost, and that a mark takes
    the same road every other narrator string takes rather than a private one.
    """
    out = _scene({"kind": "grid", "columns": 1, "cells": [{"label": "安置点", "mark": "☠️"}]})
    assert '<span class="gmk">☠</span>' in out


def test_a_true_mark_still_tints_the_cell_and_draws_no_badge():
    """The other intention `mark` carries, kept separable: one cell called out of
    several, with no symbol to show."""
    out = _scene(
        {
            "kind": "grid",
            "columns": 2,
            "cells": [{"label": "据点", "mark": True}, {"label": "巷子"}],
        }
    )
    assert "gc gm" in _body(out)
    assert "gmk" not in _body(out)


@pytest.mark.parametrize("mark", ["", "   ", "这里很危险千万不要过去", "DANGEROUS-ROAD"])
def test_a_mark_that_is_not_a_symbol_draws_nothing_rather_than_a_cut_one(mark):
    """A mark past the cap is dropped WHOLE, never truncated: an emoji is a
    codepoint sequence, so cutting one renders a lone joiner or variation selector.
    The cell still renders — a misused field costs its badge, not the map."""
    out = _scene({"kind": "grid", "columns": 1, "cells": [{"label": "巷子", "mark": mark}]})
    assert "巷子" in out
    assert "gmk" not in _body(out) and "gc gm" not in _body(out)


def test_a_symbol_mark_is_escaped_like_any_other_narrator_text():
    out = _scene({"kind": "grid", "columns": 1, "cells": [{"label": "巷子", "mark": "<b>!"}]})
    assert "<b>!" not in _body(out)
    assert "&lt;b&gt;!" in out


def test_grid_clamps_out_of_range_columns_into_range():
    out = _scene({"kind": "grid", "columns": 9, "cells": [{"label": "x"}]})
    assert "grid-template-columns:repeat(8,1fr)" in out  # 9 clamped down to 8
    out0 = _scene({"kind": "grid", "columns": 0, "cells": [{"label": "x"}]})
    assert "grid-template-columns:repeat(1,1fr)" in out0  # 0 clamped up to 1


def test_grid_drops_a_bad_cell_and_keeps_the_rest():
    out = _scene(
        {
            "kind": "grid",
            "columns": 2,
            "cells": [{"label": "王庭"}, "not-an-object", {"label": "矿脉"}],
        }
    )
    assert "王庭" in out and "矿脉" in out
    assert "not-an-object" not in out


def test_links_draws_svg_from_nodes_and_edges_with_no_author_coordinates():
    out = _scene(
        {
            "kind": "links",
            "nodes": [{"id": "a", "label": "国王"}, {"id": "b", "label": "叛军"}],
            "edges": [{"from": "a", "to": "b", "label": "敌对"}],
        }
    )
    assert "<svg" in out and 'class="lk"' in out
    assert "<line" in out and "<circle" in out
    assert "国王" in out and "敌对" in out
    # geometry is the app's: the spec carried no x/y, and coordinates appear anyway
    assert re.search(r'cx="[0-9.]+"', out)


def test_links_drops_an_edge_to_an_unknown_node_and_still_draws():
    out = _scene(
        {
            "kind": "links",
            "nodes": [{"id": "a", "label": "A"}],
            "edges": [{"from": "a", "to": "ghost"}],
        }
    )
    assert "<svg" in out and "<circle" in out  # the node still draws
    assert "<line" not in out  # the dangling edge was dropped


def test_links_de_dups_repeated_node_ids_keeping_the_first():
    out = _scene(
        {
            "kind": "links",
            "nodes": [
                {"id": "a", "label": "第一"},
                {"id": "a", "label": "第二"},
                {"id": "b", "label": "乙"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        }
    )
    assert "第一" in out and "第二" not in out
    assert out.count("<circle") == 2


def test_tree_nests_children_under_parents_and_escapes():
    out = _scene(
        {
            "kind": "tree",
            "nodes": [
                {"id": "root", "label": "始祖"},
                {"id": "kid", "label": "<i>长子</i>", "parent": "root", "note": "储君"},
            ],
        }
    )
    assert 'class="tree"' in out
    assert out.count("<ul") >= 2  # root list + one nested
    assert "<i>长子</i>" not in out
    assert "储君" in out


def test_tree_survives_a_cycle_by_promoting_a_root_and_dropping_the_back_edge():
    """A cycle no longer 422s the scene. A real root renders normally; a separate
    pair that only points at each other is stranded, so it is promoted as its own
    root and the back-edge that would loop back is dropped rather than raising."""
    out = _scene(
        {
            "kind": "tree",
            "nodes": [
                {"id": "root", "label": "始祖"},
                {"id": "kid", "label": "长子", "parent": "root"},
                {"id": "a", "label": "甲", "parent": "b"},
                {"id": "b", "label": "乙", "parent": "a"},
            ],
        }
    )
    assert 'class="tree"' in out
    for name in ("始祖", "长子", "甲", "乙"):
        assert name in out


def test_tree_treats_an_unknown_parent_as_a_root():
    out = _scene({"kind": "tree", "nodes": [{"id": "a", "label": "A", "parent": "ghost"}]})
    assert 'class="tree"' in out
    assert "A" in out  # rendered as a root rather than refused


def test_tree_drops_a_node_with_no_usable_id_but_keeps_the_rest():
    out = _scene(
        {
            "kind": "tree",
            "nodes": [
                {"id": "root", "label": "始祖"},
                {"id": "Bad Id", "label": "无效"},
                {"id": "kid", "label": "长子", "parent": "root"},
            ],
        }
    )
    assert "始祖" in out and "长子" in out
    assert "无效" not in out


def test_the_new_kinds_are_in_the_closed_set():
    assert {"grid", "links", "tree"} <= ELEMENT_KINDS


# -- fail-soft salvage: a legible partial beats a blank frame -------------


def test_over_long_text_is_truncated_with_an_ellipsis_not_refused():
    spec = {"elements": [{"kind": "text", "text": "字" * (MAX_TEXT + 50)}]}
    body = compile_scene("map", spec, STATE).split("<body>", 1)[1]
    assert "…" in body
    assert body.count("字") == MAX_TEXT - 1  # cap-1 chars, then the ellipsis


def test_an_unexpected_scalar_is_coerced_not_refused():
    """A bool is not text a narrator meant, but coercing it beats dropping the
    element that carries it."""
    out = compile_scene("map", {"elements": [{"kind": "text", "text": True}]}, STATE)
    assert "True" in out.split("<body>", 1)[1]


def test_a_list_longer_than_the_cap_is_truncated():
    spec = {"elements": [{"kind": "list", "items": [str(i) for i in range(MAX_ROWS + 10)]}]}
    assert compile_scene("map", spec, STATE).count("<li>") == MAX_ROWS


def test_a_table_drops_a_non_array_row_and_keeps_the_rest():
    spec = {"elements": [{"kind": "table", "columns": ["a"], "rows": [["1"], "bad", ["2"]]}]}
    body = compile_scene("map", spec, STATE).split("<tbody>", 1)[1]
    assert len(re.findall(r"<tr>", body)) == 2


def test_a_table_wider_than_the_column_cap_is_truncated():
    cols = [f"c{i}" for i in range(MAX_COLUMNS + 3)]
    spec = {"elements": [{"kind": "table", "columns": cols, "rows": [["x"]]}]}
    out = compile_scene("map", spec, STATE)
    assert out.count("<th>") == MAX_COLUMNS


def test_scene_warnings_reports_a_hard_gate_without_raising():
    """A whole-spec gate (empty elements) surfaces as one warning at index -1 so
    the mount tool can still succeed and tell the narrator."""
    warnings = scene_warnings("map", {"elements": []}, STATE)
    assert warnings and warnings[0]["index"] == -1


def test_the_markup_ban_stays_a_hard_gate_even_with_salvage():
    """MUST-BLOCK is untouched: a spec carrying markup is still refused outright,
    not salvaged element by element."""
    for banned in ("html", "script", "srcdoc"):
        with pytest.raises(SceneSpecError):
            compile_scene("map", {banned: "<b>x</b>", "elements": [{"kind": "divider"}]}, STATE)


# -- id coherence across the three readers -------------------------------


def test_a_mangled_choice_id_is_coherent_across_button_and_answer_channel(tmp_path):
    """The single most error-prone item: the stored spec, the compiled button's
    ``data-choice``, and the answer channel's offered set must all read the same id
    for a valid click to be accepted. Normalizing once at the mount boundary is
    what keeps them from disagreeing."""
    from scenes import SceneLedger

    ledger = SceneLedger(tmp_path, "run-1")
    spec = {
        "elements": [
            {"kind": "text", "text": "岔路"},
            {"kind": "choice", "id": "Go North!", "label": "往北"},
        ]
    }
    nonce = ledger.mount("fork", spec, asks=True)
    stored = ledger.spec("fork")  # (a) the stored spec

    out = compile_scene("fork", stored, {}, nonce=nonce)
    button_ids = re.findall(r'data-choice="([^"]+)"', out)  # (b) the button
    assert len(button_ids) == 1

    offered = {  # (c) the answer channel
        el.get("id")
        for el in stored["elements"]
        if isinstance(el, dict) and el.get("kind") == "choice"
    }
    assert button_ids[0] in offered, "button id and offered set disagree"

    # End-to-end: a click with the button's id is accepted, not refused.
    ledger.record_answer("fork", button_ids[0], nonce=nonce)
    assert ledger.answer("fork") == button_ids[0]


def test_two_choices_that_slugify_to_the_same_id_stay_distinct(tmp_path):
    from scenes import SceneLedger

    ledger = SceneLedger(tmp_path, "run-1")
    spec = {
        "elements": [
            {"kind": "choice", "id": "go!", "label": "一"},
            {"kind": "choice", "id": "go?", "label": "二"},
        ]
    }
    ledger.mount("fork", spec)
    ids = [el["id"] for el in ledger.spec("fork")["elements"]]
    assert len(set(ids)) == 2, "colliding slugs were not disambiguated"


def test_a_mangled_scene_id_is_slugified_consistently(tmp_path):
    from scenes import SceneLedger, slugify_scene_id

    ledger = SceneLedger(tmp_path, "run-1")
    ledger.mount("Battle Map!", {"elements": [{"kind": "text", "text": "x"}]})
    sid = slugify_scene_id("Battle Map!")
    assert sid == "battle-map"
    assert [r["sceneId"] for r in ledger.mounted()] == [sid]
    # Every later reader resolves the raw id to the same slug.
    assert ledger.spec("Battle Map!") == ledger.spec(sid)
    assert ledger.nonce(sid)
    # The compiled-bytes path uses the slug and never the raw id.
    assert widget_path(tmp_path, "run-1", sid).name == f"{sid}.html"


def test_update_of_an_unmounted_scene_upserts_with_a_fresh_nonce(tmp_path):
    from scenes import SceneLedger

    ledger = SceneLedger(tmp_path, "run-1")
    ledger.update("fresh", {"elements": [{"kind": "text", "text": "新"}]})
    assert [r["sceneId"] for r in ledger.mounted()] == ["fresh"]
    assert ledger.nonce("fresh"), "an upsert must produce a real mount identity"
