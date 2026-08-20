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

FLAGSHIP = _BACKEND.parent / "templates" / "age-of-sword-and-flame.md"

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
        # A present-but-wrong-typed version (the YAML 1.10 -> 1.1 corruption) is
        # still refused — salvage only DEFAULTS a missing scalar, it never launders
        # a data-loss bug into a plausible string.
        (lambda h: {**h, "version": 1.10}, "version"),
        # An empty endings list is not something salvage invents its way out of.
        (lambda h: {**h, "endings": []}, "endings"),
    ],
)
def test_a_broken_header_is_refused_naming_the_field(mutate, expect_field) -> None:
    res = accept_compiled_header(PROSE, mutate(GOOD))
    assert res.ok is False
    assert res.field == expect_field, res.problem
    assert res.problem and expect_field in res.problem


def test_an_invented_primitive_is_coerced_to_field_not_left_dead() -> None:
    """A compile that invents `renown-meter` used to ship a permanently blank box.

    Salvage now coerces any unknown primitive to a plain `field` and warns, so the
    world is playable and the change is visible in the review.
    """
    bad = json.loads(json.dumps(GOOD))
    bad["panels"][0]["fields"][1]["primitive"] = "renown-meter"
    res = accept_compiled_header(PROSE, bad)
    assert res.ok is True, res.problem
    status = next(p for p in res.pack.template.panels if p.always)
    assert status.fields[1].primitive == "field"
    assert any("renown-meter" in w and "field" in w for w in res.warnings)


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


def test_a_when_expression_with_a_function_call_is_dropped_not_fatal() -> None:
    """The brief forbids calls. A single ending that uses one is dropped and warned
    about; the world's other, valid ending survives rather than the whole compile
    dying on one bad condition."""
    bad = json.loads(json.dumps(GOOD))
    bad["endings"].append({"id": "counted", "when": "len(state.heirs) > 0"})
    res = accept_compiled_header(PROSE, bad)
    assert res.ok is True, res.problem
    assert [e.id for e in res.pack.template.endings] == ["line-ended"]
    assert any("dropped ending" in w for w in res.warnings)


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


# -- id auto-normalization (camelCase -> slug), references follow -----------


def test_camelcase_ids_are_normalized_and_when_references_follow() -> None:
    """A camelCase id is the most common first-try compiler mistake. It is fixed
    before the gate, and every `when` that references it follows the rename — as a
    path segment AND (for a matching literal) as a string — so nothing dangles."""
    header = json.loads(json.dumps(GOOD))
    header["opening"].append({"id": "birthCity", "label": "出生城", "kind": "text"})
    header["panels"].append({
        "id": "cityPanel",
        "when": 'state.birthCity == "riverport"',
        "fields": [{"id": "cityMood", "label": "民心", "primitive": "stat"}],
    })
    result = accept_compiled_header(PROSE, header)
    assert result.ok, result.problem
    t = result.pack.template

    ids = {o.id for o in t.opening} | {p.id for p in t.panels}
    assert "birth-city" in ids and "birthCity" not in ids
    assert "city-panel" in {p.id for p in t.panels}
    assert "city-mood" in {f.id for p in t.panels for f in p.fields}

    # The panel that gated on the camelCase id now gates on the slug — and the
    # rewritten `when` (with a hyphen in the path) still tokenises and evaluates
    # against state stored under that slug.
    city = next(p for p in t.panels if p.id == "city-panel")
    assert city.when is not None
    assert city.when.evaluate({"birth-city": "riverport"}) is True
    assert city.when.evaluate({"birth-city": "elsewhere"}) is False

    # A free runtime key in a `when` (magic.awakened is not a declared id) is left
    # exactly as written even while other ids are being renamed.
    magic = next(p for p in t.panels if p.id == "magic")
    assert magic.when is not None
    assert "state.magic.awakened" in magic.when.referenced_paths()

    # The normalization is surfaced, not silent.
    assert any("normalized id" in w for w in result.warnings)


def test_a_header_of_clean_slugs_is_left_untouched() -> None:
    result = accept_compiled_header(PROSE, json.loads(json.dumps(GOOD)))
    assert result.ok, result.problem
    assert not any("normalized id" in w for w in result.warnings)


# -- salvage: repairing an otherwise-playable header ----------------------


# (1) primitive synonyms / default -----------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("text", "field"), ("string", "field"), ("name", "field"),
        ("date", "field"), ("bool", "field"),
        ("number", "stat"), ("int", "stat"), ("counter", "stat"),
        ("float", "stat"),
        ("list", "inventory"), ("items", "inventory"),
        ("ladder", "rank"), ("roster", "people"),
        ("totally-unknown", "field"),
    ],
)
def test_primitive_synonyms_are_coerced(given: str, expected: str) -> None:
    h = json.loads(json.dumps(GOOD))
    h["panels"][0]["fields"][1]["primitive"] = given
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    status = next(p for p in res.pack.template.panels if p.always)
    assert status.fields[1].primitive == expected
    assert any("coerced primitive" in w for w in res.warnings)


# (2) unparseable when: drop the one, keep the world -----------------------


def test_a_conditional_panel_with_a_bad_when_is_dropped_never_the_always() -> None:
    h = json.loads(json.dumps(GOOD))
    h["panels"][1]["when"] = "len(state.x) > 0"  # a call — will not parse
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    ids = {p.id for p in res.pack.template.panels}
    assert "status" in ids and "magic" not in ids
    assert any("dropped conditional panel" in w for w in res.warnings)


# (3) chapters are an optional optimization: drop the bad ones --------------


def test_a_chapter_heading_absent_from_prose_is_dropped_not_fatal() -> None:
    h = json.loads(json.dumps(GOOD))
    h["chapters"] = [
        {"id": "intro", "heading": "第一章", "always": True},        # present in PROSE
        {"id": "ghost", "heading": "no such heading", "always": True},  # not present
    ]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    assert [c.id for c in res.pack.template.chapters] == ["intro"]
    assert any("dropped chapters" in w for w in res.warnings)


def test_a_duplicate_chapter_id_is_dropped() -> None:
    h = json.loads(json.dumps(GOOD))
    h["chapters"] = [
        {"id": "intro", "heading": "第一章", "always": True},
        {"id": "intro", "heading": "第一章", "always": True},
    ]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    assert len(res.pack.template.chapters) == 1
    assert any("duplicate chapters id" in w for w in res.warnings)


# (4) optional enrichment lists: drop bad entries, keep good ones -----------


def test_a_bad_lore_entry_is_dropped_and_the_good_one_survives() -> None:
    h = json.loads(json.dumps(GOOD))
    h["lore"] = [
        {"id": "riverport", "keys": ["Riverport"], "text": "A trade city."},
        {"id": "broken", "text": ""},  # no keys, no text, not always
    ]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    assert [entry.id for entry in res.pack.template.lore] == ["riverport"]
    assert any("dropped lore" in w for w in res.warnings)


def test_a_bad_system_entry_is_dropped_and_the_good_one_survives() -> None:
    h = json.loads(json.dumps(GOOD))
    h["systems"] = [
        {"id": "xp", "kind": "accrual", "into": "state.hero.xp"},
        {"id": "junk", "kind": "not-a-kind", "into": "state.hero.y"},
    ]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    assert [s.id for s in res.pack.template.systems] == ["xp"]
    assert any("dropped systems" in w for w in res.warnings)


def test_a_non_list_optional_field_is_dropped_whole() -> None:
    h = json.loads(json.dumps(GOOD))
    h["lore"] = "this should have been a list"
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    assert res.pack.template.lore == []
    assert any("dropped lore" in w for w in res.warnings)


# (5) CJK / empty-slug id fallback -----------------------------------------


def test_an_all_non_ascii_id_falls_back_to_a_digest_slug() -> None:
    h = json.loads(json.dumps(GOOD))
    h["id"] = "剑火纪元"
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    assert res.pack.id.startswith("world-")
    assert len(res.pack.id) == len("world-") + 8
    assert any("world id" in w for w in res.warnings)


def test_a_missing_id_is_derived_from_the_title() -> None:
    h = json.loads(json.dumps(GOOD))
    del h["id"]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    assert res.pack.id == "test-world"  # from title "Test World"
    assert any("derived world id" in w for w in res.warnings)


def test_a_digest_slug_is_deterministic_for_the_same_title_and_prose() -> None:
    h = json.loads(json.dumps(GOOD))
    h["id"] = "剑火纪元"
    first = accept_compiled_header(PROSE, json.loads(json.dumps(h)))
    second = accept_compiled_header(PROSE, json.loads(json.dumps(h)))
    assert first.pack.id == second.pack.id


# (6) default the scalars the brief already documents ----------------------


def test_missing_scalars_are_defaulted() -> None:
    h = json.loads(json.dumps(GOOD))
    for key in ("version", "language", "clock"):
        del h[key]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    t = res.pack.template
    assert t.version == "1.0"
    assert t.language == "en"
    assert t.clock_unit == "turn"


def test_a_missing_styles_list_gets_a_default_style() -> None:
    h = json.loads(json.dumps(GOOD))
    del h["styles"]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    assert len(res.pack.template.styles) == 1
    assert any("default style" in w for w in res.warnings)


# (7) opening kind synonyms ------------------------------------------------


@pytest.mark.parametrize("synonym", ["select", "choice", "dropdown", "options"])
def test_opening_kind_synonyms_become_pick_when_options_exist(synonym: str) -> None:
    h = json.loads(json.dumps(GOOD))
    h["opening"][1]["kind"] = synonym
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    race = next(g for g in res.pack.template.opening if g.id == "race")
    assert race.kind == "pick"
    assert any("mapped opening kind" in w for w in res.warnings)


def test_a_pick_with_no_options_is_downgraded_to_text() -> None:
    h = json.loads(json.dumps(GOOD))
    h["opening"].append({"id": "guild", "label": "公会", "kind": "pick", "options": []})
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    guild = next(g for g in res.pack.template.opening if g.id == "guild")
    assert guild.kind == "text"
    assert any("downgraded a pick" in w for w in res.warnings)


def test_non_string_options_are_cleaned() -> None:
    h = json.loads(json.dumps(GOOD))
    h["opening"][1]["options"] = ["人类", 42, {"bad": 1}, "精灵"]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    race = next(g for g in res.pack.template.opening if g.id == "race")
    assert race.options == ["人类", "42", "精灵"]
    assert any("cleaned non-string options" in w for w in res.warnings)


# (8) trivial scalar coercions ---------------------------------------------


def test_more_than_one_default_style_keeps_the_first_and_clears_the_rest() -> None:
    h = json.loads(json.dumps(GOOD))
    h["styles"] = [
        {"id": "gentle", "label": "温和", "default": True},
        {"id": "harsh", "label": "残酷", "default": True},
    ]
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    defaults = [s.id for s in res.pack.template.styles if s.default]
    assert defaults == ["gentle"]
    assert any("extra default flag" in w for w in res.warnings)


def test_an_empty_field_label_defaults_to_the_field_id() -> None:
    h = json.loads(json.dumps(GOOD))
    h["panels"][0]["fields"][0]["label"] = ""
    res = accept_compiled_header(PROSE, h)
    assert res.ok is True, res.problem
    status = next(p for p in res.pack.template.panels if p.always)
    assert status.fields[0].label == status.fields[0].id
    assert any("defaulted field label" in w for w in res.warnings)


# -- _as_mapping backslash repair ------------------------------------------


def test_a_lone_backslash_in_the_json_is_repaired() -> None:
    """A stray backslash (a path, an over-eager escape) is doubled and recovered
    rather than wasting the compile."""
    text = json.dumps(GOOD, ensure_ascii=False)
    broken = text.replace('"标准"', '"标准 C:\\Users"', 1)
    res = accept_compiled_header(PROSE, broken)
    assert res.ok is True, res.problem


# -- must-block: a near-empty header is a clean refusal --------------------


@pytest.mark.parametrize("empty", ["{}", {}, {"title": "Nothing"}])
def test_a_near_empty_header_is_refused_with_a_plain_sentence(empty) -> None:
    res = accept_compiled_header(PROSE, empty)
    assert res.ok is False
    assert res.problem == "no playable world could be found"


def test_zero_panels_is_still_a_hard_refusal() -> None:
    h = json.loads(json.dumps(GOOD))
    h["panels"] = []
    res = accept_compiled_header(PROSE, h)
    assert res.ok is False
    assert res.problem == "no playable world could be found"


# -- a clean header stays warning-free through salvage ---------------------


def test_a_clean_good_header_produces_no_salvage_warnings() -> None:
    res = accept_compiled_header(PROSE, json.loads(json.dumps(GOOD)))
    assert res.ok is True, res.problem
    assert res.warnings == []
