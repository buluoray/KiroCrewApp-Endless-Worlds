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
    MAX_ELEMENTS,
    MAX_SPEC_BYTES,
    SCENE_SCRIPT,
    SceneSpecError,
    compile_cached,
    compile_scene,
    resolve_bind,
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
        "default-src 'none'", "connect-src 'none'",
        "form-action 'none'", "base-uri 'none'", "img-src data:",
    ):
        assert clause in CSP
    assert "http" not in CSP, "no host is ever allowed"
    assert "*" not in CSP


def test_nothing_is_loaded_from_anywhere():
    """Inline everything, load nothing — so there is no request to intercept and
    no third party to trust."""
    out = compile_scene("map", SIMPLE, STATE)
    assert "src=" not in out.replace('data-scene=', '')
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


def test_an_unknown_kind_is_refused_before_anything_mounts():
    """Refused, not skipped: a compiler that ignored what it did not understand
    would let a spec fail open."""
    with pytest.raises(SceneSpecError) as exc:
        compile_scene("map", {"elements": [{"kind": "iframe", "src": "http://evil"}]}, STATE)
    assert exc.value.field == "elements[0].kind"


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


def test_an_unresolvable_bind_is_rejected_rather_than_left_blank():
    """Unlike a panel gap. A panel gap is a fact not yet mentioned; a scene bind
    is the narrator asserting a number exists — a silent blank would ship a widget
    that quietly disagrees with the panels."""
    with pytest.raises(SceneSpecError) as exc:
        compile_scene("map", {"elements": [{"kind": "stat", "label": "x", "bind": "magic.nope"}]}, STATE)
    assert exc.value.field == "elements[0].bind"


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


def test_too_many_elements_is_refused():
    spec = {"elements": [{"kind": "divider"} for _ in range(MAX_ELEMENTS + 1)]}
    with pytest.raises(SceneSpecError) as exc:
        compile_scene("map", spec, STATE)
    assert exc.value.field == "spec.elements"


def test_an_empty_spec_is_refused():
    with pytest.raises(SceneSpecError):
        compile_scene("map", {"elements": []}, STATE)


def test_a_ragged_table_row_is_refused_by_position():
    spec = {"elements": [{"kind": "table", "columns": ["a", "b"], "rows": [["1"]]}]}
    with pytest.raises(SceneSpecError) as exc:
        compile_scene("map", spec, STATE)
    assert exc.value.field == "elements[0].rows[0]"


def test_nothing_is_emitted_when_one_element_is_bad():
    """Validated whole: a scene missing its second half looks to the player like
    the world forgetting what it was saying."""
    spec = {"elements": [{"kind": "text", "text": "好的"}, {"kind": "nope"}]}
    with pytest.raises(SceneSpecError):
        compile_scene("map", spec, STATE)


# -- bars ---------------------------------------------------------------


def test_a_bar_over_its_cap_does_not_overflow():
    spec = {"elements": [{"kind": "bar", "label": "x", "value": 500, "max": 100}]}
    assert "width:100%" in compile_scene("map", spec, STATE)


def test_a_zero_cap_draws_no_bar_rather_than_dividing_by_zero():
    spec = {"elements": [{"kind": "bar", "label": "x", "value": 5, "max": 0}]}
    assert "class=\"t\"" not in compile_scene("map", spec, STATE)


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
