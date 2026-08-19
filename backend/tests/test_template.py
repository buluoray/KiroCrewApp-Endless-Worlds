"""Template loader + ``when`` interpreter tests.

No gateway import needed — this module is pure stdlib + PyYAML, so these run
anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from template import (  # noqa: E402
    Condition,
    TemplateError,
    parse_template,
    split_front_matter,
)

# A minimal but complete template. Every test that needs a valid one starts here
# and mutates one thing, so a failure names exactly one cause.
HEADER = """---
id: test-world
title: Test World
version: "1.0"
language: en
clock: { unit: month, label: "Year {year}, month {month}" }
lineage: true
styles:
  - { id: gentle, label: Gentle }
  - { id: standard, label: Standard, default: true }
opening:
  - { id: era, label: Era, kind: pick, options: [Golden, Waning], custom: true }
  - { id: name, label: Name, kind: text }
panels:
  - id: status
    label: Character Status
    always: true
    fields:
      - { id: age, label: Age, primitive: field }
      - { id: renown, label: Renown, primitive: stat, min: 0, max: 100 }
  - id: magic
    label: Magic
    when: state.magic.awakened == true
    fields:
      - { id: mana, label: Mana, primitive: stat }
endings:
  - { id: died, when: state.alive == false }
digest:
  categories: [nations, wars]
  rumours: true
save: [character, wealth]
---"""

PROSE = "Chapter One\n\nThe world does not revolve around you.\n"


def build(header: str = HEADER, prose: str = PROSE) -> str:
    return f"{header}\n{prose}"


# -- front matter ---------------------------------------------------------


def test_prose_survives_byte_for_byte() -> None:
    """R14.1: the rulebook reaches the narrator exactly as authored."""
    _, prose = split_front_matter(build())
    assert prose == PROSE


def test_prose_with_yaml_lookalike_content_is_not_parsed() -> None:
    """A prose body containing --- and key: value must stay prose."""
    tricky = "---\nnot: front matter\n---\n\nStill prose.\n"
    _, prose = split_front_matter(build(prose=tricky))
    assert prose == tricky


def test_cjk_and_box_drawing_prose_survives() -> None:
    tricky = "╔══════╗\n《无限世界·人生状态》\n【时间】\n"
    _, prose = split_front_matter(build(prose=tricky))
    assert prose == tricky


@pytest.mark.parametrize(
    "text",
    [
        "no front matter at all",
        "\n---\nid: x\n---\nleading blank line before ---",
        "---\nid: x\nnever closed\n",
    ],
)
def test_missing_or_unclosed_front_matter_is_refused(text: str) -> None:
    with pytest.raises(TemplateError) as exc:
        split_front_matter(text)
    assert exc.value.field == "front matter"


def test_invalid_yaml_names_front_matter_not_a_crash() -> None:
    with pytest.raises(TemplateError) as exc:
        split_front_matter("---\nid: [unclosed\n---\nprose\n")
    assert exc.value.field == "front matter"


# -- happy path -----------------------------------------------------------


def test_flagship_shaped_template_parses() -> None:
    t = parse_template(build())
    assert t.id == "test-world"
    assert t.version == "1.0"
    assert t.lineage is True
    assert t.clock_unit == "month"
    assert [s.id for s in t.styles] == ["gentle", "standard"]
    assert t.default_style.id == "standard"
    assert [g.id for g in t.opening] == ["era", "name"]
    assert t.opening[0].custom is True
    assert [p.id for p in t.panels] == ["status", "magic"]
    assert [p.label for p in t.panels] == ["Character Status", "Magic"]
    assert t.digest_categories == ["nations", "wars"]
    assert t.digest_rumours is True
    assert t.save_schema == ["character", "wealth"]
    assert t.prose == PROSE


def test_version_given_as_a_yaml_float_becomes_a_string() -> None:
    """`version: 1.0` is a float to YAML; comparisons need a stable string."""
    t = parse_template(build())
    assert isinstance(t.version, str)


def test_default_style_falls_back_to_the_first_when_none_declared() -> None:
    header = HEADER.replace(", default: true", "")
    assert parse_template(build(header)).default_style.id == "gentle"


def test_panel_label_falls_back_to_stable_id_for_older_worlds() -> None:
    header = HEADER.replace("    label: Character Status\n", "", 1)
    assert parse_template(build(header)).panels[0].label == "status"


def test_panel_extras_are_carried_through_for_the_primitive() -> None:
    t = parse_template(build())
    renown = next(f for f in t.panels[0].fields if f.id == "renown")
    assert renown.options == {"min": 0, "max": 100}


# -- conditional panels ---------------------------------------------------


def test_always_panel_is_visible_with_empty_state() -> None:
    t = parse_template(build())
    assert t.panels[0].visible({})


def test_conditional_panel_hidden_until_its_trigger_is_met() -> None:
    t = parse_template(build())
    magic = t.panels[1]
    assert magic.visible({}) is False
    assert magic.visible({"magic": {"awakened": False}}) is False
    assert magic.visible({"magic": {"awakened": True}}) is True


def test_panels_for_yields_only_visible_panels() -> None:
    t = parse_template(build())
    assert [p.id for p in t.panels_for({})] == ["status"]
    assert [p.id for p in t.panels_for({"magic": {"awakened": True}})] == [
        "status",
        "magic",
    ]


# -- when: evaluation semantics ------------------------------------------


@pytest.mark.parametrize(
    "expr,state,expected",
    [
        ("state.a == 1", {"a": 1}, True),
        ("state.a != 1", {"a": 2}, True),
        ("state.a > 5", {"a": 6}, True),
        ("state.a >= 5", {"a": 5}, True),
        ("state.a < 5", {"a": 4}, True),
        ("state.a <= 5", {"a": 5}, True),
        ("state.s == 'gold'", {"s": "gold"}, True),
        ("state.b == true", {"b": True}, True),
        ("state.b == false", {"b": False}, True),
        ("state.b == null", {}, True),
        ("state.deep.nested.flag == true", {"deep": {"nested": {"flag": True}}}, True),
        ("not state.b", {"b": False}, True),
        ("state.a == 1 and state.b == 2", {"a": 1, "b": 2}, True),
        ("state.a == 1 and state.b == 2", {"a": 1, "b": 9}, False),
        ("state.a == 1 or state.b == 2", {"a": 0, "b": 2}, True),
        ("(state.a == 1 or state.b == 2) and state.c == 3", {"a": 1, "c": 3}, True),
        ("state.a == 1 or state.b == 2 and state.c == 3", {"a": 1}, True),
        ("state.n > 1.5", {"n": 2}, True),
        ("state.n > -1", {"n": 0}, True),
    ],
)
def test_evaluation(expr: str, state: dict, expected: bool) -> None:
    assert Condition.parse(expr).evaluate(state) is expected


@pytest.mark.parametrize(
    "expr",
    [
        "state.missing > 5",
        "state.missing < 5",
        "state.missing >= 5",
        "state.missing <= 5",
        "state.a.b.c.d == 1",
    ],
)
def test_a_missing_path_never_raises_and_is_not_satisfied(expr: str) -> None:
    """A trigger naming state the run has not reached yet hides its panel.

    Raising here would break the turn for a template that merely looks ahead,
    so the interpreter treats absence as 'not satisfied'.
    """
    assert Condition.parse(expr).evaluate({}) is False


def test_ordering_across_incomparable_types_is_false_not_a_crash() -> None:
    assert Condition.parse("state.s > 5").evaluate({"s": "text"}) is False


def test_walking_into_a_non_mapping_yields_none_rather_than_raising() -> None:
    assert Condition.parse("state.a.b == 1").evaluate({"a": 7}) is False


# -- when: nothing executes ---------------------------------------------

INJECTION_SHAPED = [
    "__import__('os').system('echo pwned')",
    "state.a == __import__('os')",
    "open('/etc/passwd').read() == 'x'",
    "eval('1+1') == 2",
    "state.a == 1; import os",
    "state.a == 1 && state.b == 2",
    "state.a == 1 || true",
    "state.a.__class__ == 1 and (lambda: 1)()",
    "[x for x in ()] == []",
    "{'a': 1} == state.a",
    "state.a == `whoami`",
    "state.a == $(whoami)",
    "state.a =! 1",
    "state.a ===  1",
    "== 1",
    "state.a ==",
    "(state.a == 1",
    "state.a == 1)",
    "and state.a",
    "state.a == 1 not",
    "",
    "   ",
]


@pytest.mark.parametrize("expr", INJECTION_SHAPED)
def test_injection_shaped_and_malformed_input_is_refused(expr: str) -> None:
    """Every one of these must fail to PARSE, so nothing can run.

    The interpreter has no call node, no subscript node, and no attribute
    node — only paths, literals, comparisons and boolean operators — so a
    function call cannot be represented, let alone evaluated. These cases pin
    that the failure is a clean TemplateError rather than an arbitrary
    exception escaping into the turn loop.
    """
    with pytest.raises(TemplateError):
        Condition.parse(expr)


def test_a_path_that_merely_looks_dangerous_is_inert() -> None:
    """`os.system` with no call parens parses as a path and reads as missing.

    Worth pinning: the danger is calling, and calling is unrepresentable.
    """
    assert Condition.parse("os.system == 1").evaluate({}) is False


def test_deeply_nested_parens_are_refused_not_a_recursion_crash() -> None:
    expr = "(" * 200 + "state.a == 1" + ")" * 200
    with pytest.raises(TemplateError):
        Condition.parse(expr)


def test_a_long_but_flat_expression_still_works() -> None:
    expr = " and ".join(f"state.k{i} == {i}" for i in range(50))
    state = {f"k{i}": i for i in range(50)}
    assert Condition.parse(expr).evaluate(state) is True


@pytest.mark.parametrize(
    "raw",
    ["version: 1.0", "version: 1.10", "version: 2", "version: yes"],
)
def test_an_unquoted_version_is_refused_rather_than_laundered(raw: str) -> None:
    """YAML 1.1 turns 1.10 into the float 1.1 — a different version, silently.

    R14.7's migration check compares versions exactly, so accepting a number and
    str()-ing it would hide data loss behind a plausible string. Falsification:
    restoring `str(_require(...))` in parse_template makes every case here pass
    silently, which is the bug.
    """
    bad = HEADER.replace('version: "1.0"', raw)
    with pytest.raises(TemplateError) as exc:
        parse_template(build(bad))
    assert exc.value.field == "version"


def test_a_quoted_version_keeps_its_exact_text() -> None:
    for text in ("1.0", "1.10", "2", "0.1.0-beta"):
        header = HEADER.replace('version: "1.0"', f'version: "{text}"')
        assert parse_template(build(header)).version == text


def test_a_json_front_matter_header_parses_identically() -> None:
    """JSON is a YAML 1.2 subset, so an agent-compiled header needs no new
    parser — and JSON avoids the implicit-typing traps entirely (no unquoted
    1.10, no `yes` becoming True, no `1:30` becoming 90)."""
    import json

    yaml_version = parse_template(build())
    header_obj = {
        "id": "test-world",
        "title": "Test World",
        "version": "1.0",
        "language": "en",
        "clock": {"unit": "month", "label": "Year {year}, month {month}"},
        "lineage": True,
        "styles": [
            {"id": "gentle", "label": "Gentle"},
            {"id": "standard", "label": "Standard", "default": True},
        ],
        "opening": [
            {"id": "era", "label": "Era", "kind": "pick",
             "options": ["Golden", "Waning"], "custom": True},
            {"id": "name", "label": "Name", "kind": "text"},
        ],
        "panels": [
            {"id": "status", "always": True, "fields": [
                {"id": "age", "label": "Age", "primitive": "field"},
                {"id": "renown", "label": "Renown", "primitive": "stat",
                 "min": 0, "max": 100},
            ]},
            {"id": "magic", "when": "state.magic.awakened == true", "fields": [
                {"id": "mana", "label": "Mana", "primitive": "stat"},
            ]},
        ],
        "endings": [{"id": "died", "when": "state.alive == false"}],
        "digest": {"categories": ["nations", "wars"], "rumours": True},
        "save": ["character", "wealth"],
    }
    json_doc = f"---\n{json.dumps(header_obj, ensure_ascii=False)}\n---\n{PROSE}"
    from_json = parse_template(json_doc)

    assert from_json.id == yaml_version.id
    assert from_json.version == yaml_version.version
    assert [p.id for p in from_json.panels] == [p.id for p in yaml_version.panels]
    assert len(from_json.opening) == len(yaml_version.opening)
    assert from_json.prose == yaml_version.prose
    assert from_json.panels[1].when.evaluate({"magic": {"awakened": True}}) is True


# -- header validation --------------------------------------------------


@pytest.mark.parametrize(
    "bad_header,field",
    [
        (HEADER.replace("id: test-world", "id: Test_World"), "template.id"),
        (HEADER.replace("title: Test World", "title: 7"), "title"),
        (HEADER.replace("language: en", "langauge: en"), "language"),
        (HEADER.replace("clock: { unit: month", "clock: { units: month"), "unit"),
        (
            HEADER.replace(
                "styles:\n  - { id: gentle, label: Gentle }\n"
                "  - { id: standard, label: Standard, default: true }\n",
                "styles: []\n",
            ),
            "styles",
        ),
        (HEADER.replace("kind: pick, options: [Golden, Waning]", "kind: pick"), "opening[0].options"),
        (HEADER.replace("kind: pick", "kind: slider"), "opening[0].kind"),
        (HEADER.replace("primitive: field", "primitive: magic-bar"), "panels[0].fields[0].primitive"),
        (HEADER.replace("    always: true\n", ""), "panels[0]"),
        (HEADER.replace("when: state.magic.awakened == true", "always: true"), "panels"),
        (HEADER.replace("  - { id: died, when: state.alive == false }\n", ""), "endings"),
    ],
)
def test_header_errors_name_the_field(bad_header: str, field: str) -> None:
    """R14.3: the Library shows WHICH field was wrong, so the message is UI."""
    with pytest.raises(TemplateError) as exc:
        parse_template(build(bad_header))
    assert exc.value.field == field, f"expected field {field}, got {exc.value.field}"
    assert exc.value.expected, "an error must say what was expected"


def test_a_panel_declaring_both_always_and_when_is_refused() -> None:
    bad = HEADER.replace(
        "    always: true\n", "    always: true\n    when: state.x == 1\n"
    )
    with pytest.raises(TemplateError) as exc:
        parse_template(build(bad))
    assert exc.value.field == "panels[0]"


def test_an_unparseable_when_in_a_panel_surfaces_as_a_template_error() -> None:
    bad = HEADER.replace("when: state.magic.awakened == true", "when: \"state.a ==\"")
    with pytest.raises(TemplateError):
        parse_template(build(bad))


def test_one_broken_template_does_not_affect_a_good_one() -> None:
    """R14.3: every template that did load still appears."""
    good = parse_template(build())
    with pytest.raises(TemplateError):
        parse_template(build(HEADER.replace("primitive: field", "primitive: nope")))
    assert parse_template(build()).id == good.id
