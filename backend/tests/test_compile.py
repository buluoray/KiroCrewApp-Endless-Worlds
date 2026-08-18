"""Compiler gate tests.

The compiler itself is an agent, so what is tested here is the backend's side:
does a good header get through, does every shape of bad header get refused with
something a user can read, and is a compiled header held to exactly the same
standard as a hand-written one.

The end-to-end check — feed the flagship's own prose to a real agent with the
hand-written header withheld, and see whether it recovers the same structure —
needs the MCP tool surface from Task 7 and is marked below.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from compile import (  # noqa: E402
    COMPILER_BRIEF,
    accept_compiled_header,
    preview,
)
from template import FIELD_PRIMITIVES, OPENING_KINDS  # noqa: E402
from world import HAND_COMPILED, read_world  # noqa: E402

FLAGSHIP = _BACKEND.parent / "templates" / "jianhuo-jiyuan.md"

PROSE = "第一章\n\n世界不围绕玩家存在。\n【时间】XXX年·XXX月\n"

GOOD = {
    "id": "test-world",
    "title": "Test World",
    "version": "1.0",
    "language": "zh",
    "clock": {"unit": "month", "label": "{year}年·{month}月"},
    "styles": [{"id": "standard", "label": "标准", "default": True}],
    "opening": [
        {"id": "name", "label": "姓名", "kind": "text"},
        {"id": "race", "label": "种族", "kind": "pick",
         "options": ["人类", "精灵"], "custom": True},
    ],
    "panels": [
        {"id": "status", "always": True, "fields": [
            {"id": "age", "label": "年龄", "primitive": "field"},
            {"id": "renown", "label": "声望", "primitive": "stat", "min": 0, "max": 100},
        ]},
        {"id": "magic", "when": "state.magic.awakened == true", "fields": [
            {"id": "mana", "label": "魔力", "primitive": "stat"},
        ]},
    ],
    "endings": [
        {"id": "line-ended",
         "when": "state.alive == false and state.lineage.hasHeir == false"},
    ],
    "digest": {"categories": ["国家", "战争"], "rumours": True},
    "save": ["角色", "世界变量"],
}


# -- the happy path -------------------------------------------------------


def test_a_good_header_is_accepted_and_becomes_a_world() -> None:
    res = accept_compiled_header(PROSE, GOOD)
    assert res.ok, res.problem
    assert res.pack is not None
    assert res.pack.id == "test-world"
    assert res.pack.prose == PROSE
    assert res.world_text and res.world_text.endswith(PROSE)


def test_provenance_is_stamped_by_the_backend_not_the_agent() -> None:
    """The digest must be of the prose the backend holds, so a compiler that
    reports a digest of something else cannot make a stale world look fresh."""
    lying = {**GOOD, "compiledFrom": {
        "proseSha256": "0" * 64, "compiler": "hand", "contract": 1}}
    res = accept_compiled_header(PROSE, lying)
    assert res.ok
    assert res.pack.provenance.prose_sha256 != "0" * 64
    assert res.pack.is_stale() is False
    assert res.pack.provenance.compiler != HAND_COMPILED


def test_json_text_is_accepted_as_well_as_a_mapping() -> None:
    res = accept_compiled_header(PROSE, json.dumps(GOOD, ensure_ascii=False))
    assert res.ok, res.problem


def test_a_fenced_code_block_is_unwrapped() -> None:
    """Wrapping JSON in ``` is a formatting habit, not a different answer."""
    fenced = "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```"
    res = accept_compiled_header(PROSE, fenced)
    assert res.ok, res.problem


def test_the_result_round_trips_through_the_world_reader() -> None:
    res = accept_compiled_header(PROSE, GOOD)
    reread = read_world(res.world_text)
    assert reread.id == "test-world"
    assert reread.prose == PROSE
    assert reread.is_stale() is False


# -- refusals, each with something readable -------------------------------


@pytest.mark.parametrize(
    "mutate,expect_field",
    [
        (lambda h: {**h, "id": "Test_World"}, "template.id"),
        (lambda h: {k: v for k, v in h.items() if k != "clock"}, "clock"),
        (lambda h: {k: v for k, v in h.items() if k != "language"}, "language"),
        (lambda h: {**h, "version": 1.10}, "version"),
        (lambda h: {**h, "styles": []}, "styles"),
        (lambda h: {**h, "endings": []}, "endings"),
    ],
)
def test_a_broken_header_is_refused_naming_the_field(mutate, expect_field) -> None:
    res = accept_compiled_header(PROSE, mutate(GOOD))
    assert res.ok is False
    assert res.field == expect_field, res.problem
    assert res.problem and expect_field in res.problem


def test_an_invented_primitive_is_refused_rather_than_making_a_dead_panel() -> None:
    """A compile that invents `renown-meter` must fail loudly.

    Accepting it would ship a world with one panel that renders nothing, which
    the player would experience as a permanently blank box.
    """
    bad = json.loads(json.dumps(GOOD))
    bad["panels"][0]["fields"][1]["primitive"] = "renown-meter"
    res = accept_compiled_header(PROSE, bad)
    assert res.ok is False
    assert "primitive" in res.field
    assert "renown-meter" in res.problem


def test_two_always_panels_are_refused() -> None:
    bad = json.loads(json.dumps(GOOD))
    bad["panels"][1] = {"id": "magic", "always": True,
                        "fields": [{"id": "mana", "label": "魔力", "primitive": "stat"}]}
    res = accept_compiled_header(PROSE, bad)
    assert res.ok is False
    assert res.field == "panels"


def test_no_always_panel_is_refused() -> None:
    bad = json.loads(json.dumps(GOOD))
    bad["panels"][0] = {"id": "status", "when": "state.x == 1",
                        "fields": [{"id": "age", "label": "年龄", "primitive": "field"}]}
    res = accept_compiled_header(PROSE, bad)
    assert res.ok is False
    assert res.field == "panels"


def test_a_when_expression_with_a_function_call_is_refused() -> None:
    """The brief forbids calls; the gate enforces it rather than trusting."""
    bad = json.loads(json.dumps(GOOD))
    bad["endings"][0]["when"] = "len(state.heirs) > 0"
    res = accept_compiled_header(PROSE, bad)
    assert res.ok is False
    assert res.field == "when"


@pytest.mark.parametrize("garbage", ["not json at all", "[1, 2, 3]", "", "42"])
def test_non_object_output_is_refused_with_a_readable_reason(garbage: str) -> None:
    res = accept_compiled_header(PROSE, garbage)
    assert res.ok is False
    assert res.problem
    assert "json" in res.problem.lower() or "object" in res.problem.lower()


def test_compiling_with_no_prose_is_refused() -> None:
    res = accept_compiled_header("   ", GOOD)
    assert res.ok is False
    assert res.field == "prose"


# -- diagnostics ----------------------------------------------------------


def test_referenced_paths_are_reported() -> None:
    res = accept_compiled_header(PROSE, GOOD)
    assert res.referenced_paths == [
        "state.alive", "state.lineage.hasHeir", "state.magic.awakened",
    ]


def test_a_near_miss_path_is_warned_about_not_rejected() -> None:
    """`state.magik.awake` beside `state.magic.awakened` hides a panel forever.

    It cannot be an error — the backend cannot know which spelling the narrator
    will maintain — so it is surfaced as a warning the compiler can act on.
    """
    bad = json.loads(json.dumps(GOOD))
    bad["endings"].append({"id": "awoken", "when": "state.magik.awakened == true"})
    res = accept_compiled_header(PROSE, bad)
    assert res.ok is True
    assert res.warnings
    assert any("magic" in w and "magik" in w for w in res.warnings)


def test_ordinary_sibling_paths_do_not_warn() -> None:
    """`state.a.x` and `state.a.y` are normal and must stay quiet."""
    fine = json.loads(json.dumps(GOOD))
    fine["endings"].append({"id": "other", "when": "state.magic.exhausted == true"})
    res = accept_compiled_header(PROSE, fine)
    assert res.ok is True
    assert res.warnings == []


# -- the brief itself -----------------------------------------------------


def test_the_brief_names_every_allowed_primitive_and_kind() -> None:
    """The brief is the main lever on compile quality, so it must not drift from
    the code it describes."""
    for primitive in FIELD_PRIMITIVES:
        assert primitive in COMPILER_BRIEF, f"brief omits primitive {primitive}"
    for kind in OPENING_KINDS:
        assert kind in COMPILER_BRIEF, f"brief omits opening kind {kind}"


def test_the_brief_states_the_load_bearing_prohibitions() -> None:
    for rule in ("JSON", "quoted string", "EXACTLY ONE", "DO NOT ENUMERATE"):
        assert rule in COMPILER_BRIEF, f"brief no longer states: {rule}"


# -- preview --------------------------------------------------------------


def test_preview_speaks_the_worlds_words_not_the_apps() -> None:
    """R25.2 — no implementation vocabulary reaches the user."""
    res = accept_compiled_header(PROSE, GOOD)
    view = preview(res.pack)
    assert view["title"] == "Test World"
    assert view["opening"] == ["姓名", "种族"]
    assert view["panels"][0]["fields"] == ["年龄", "声望"]
    blob = json.dumps(view, ensure_ascii=False).lower()
    for forbidden in ("primitive", "schema", "validation", "contract", "widget"):
        assert forbidden not in blob, f"preview leaks the word {forbidden!r}"


# -- the real thing, pending the tool surface ----------------------------


@pytest.mark.skip(reason="needs the MCP tool surface + narrator slot from Task 7")
def test_the_compiler_recovers_the_flagship_structure_from_its_prose_alone() -> None:
    """The control experiment for Task 5c.

    Feed 剑火纪元's own prose to the compiling agent with the hand-written header
    withheld, and assert it recovers the structure a human found in the same text:
    a 17-field always-visible panel, at least 4 conditional panels, a month clock,
    6 styles, and 12 or more opening groups. The hand-written header is the gold
    reference precisely because it was made without reference to the compiler.
    """
    prose = read_world(FLAGSHIP.read_text(encoding="utf-8")).prose
    # header = call the narrator with COMPILER_BRIEF + prose
    # res = accept_compiled_header(prose, header)
    # assert res.ok
    # status = next(p for p in res.pack.template.panels if p.always)
    # assert len(status.fields) == 17
    # assert len([p for p in res.pack.template.panels if not p.always]) >= 4
    # assert res.pack.template.clock_unit == "month"
    # assert len(res.pack.template.styles) == 6
    # assert len(res.pack.template.opening) >= 12
    assert prose
