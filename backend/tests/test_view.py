"""Play-view tests — primitives driven by config, gaps, and framing removal."""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import view as view_mod  # noqa: E402
from template import FIELD_PRIMITIVES  # noqa: E402
from view import build_play_view, strip_terminal_framing  # noqa: E402
from world import read_world  # noqa: E402

FLAGSHIP = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"


@pytest.fixture(scope="module")
def tpl():
    if not FLAGSHIP.is_file():
        pytest.skip("flagship seed not present")
    return read_world(FLAGSHIP.read_text(encoding="utf-8")).template


# -- panel visibility is decided once, on the server ---------------------


def test_only_the_always_panel_shows_before_the_narrator_says_otherwise(tpl):
    v = build_play_view(tpl, {"turn": 1})
    assert [p["id"] for p in v["panels"]] == ["status"]
    assert [p["label"] for p in v["panels"]] == ["角色状态"]


def test_a_conditional_panel_appears_when_its_flag_flips(tpl):
    v = build_play_view(tpl, {"turn": 1, "magic": {"awakened": True}})
    assert "magic" in [p["id"] for p in v["panels"]]


def test_every_conditional_panel_can_be_reached(tpl):
    """If a world declares a panel nobody can ever see, that is worth knowing —
    a condition typo would otherwise hide a whole panel forever."""
    state = {
        "turn": 1,
        "magic": {"awakened": True},
        "relations": {"known": True},
        "office": {"high": True},
        "academy": {"enrolled": True},
        "family": {"held": True},
    }
    shown = {p["id"] for p in build_play_view(tpl, state)["panels"]}
    assert shown == {p.id for p in tpl.panels}


def test_the_ui_is_never_asked_to_evaluate_a_condition(tpl):
    """One ``when`` interpreter, in Python, over untrusted template text. A second
    one in JavaScript would be a second grammar to keep identical."""
    v = build_play_view(tpl, {"turn": 1})
    for panel in v["panels"]:
        assert "when" not in panel


# -- endings are judged in one place --------------------------------------


def test_a_life_continues_until_an_ending_holds(tpl):
    v = build_play_view(tpl, {"turn": 1})
    assert v["ended"] is False
    assert v["endingId"] == ""


def test_a_declared_ending_condition_closes_the_life(tpl):
    """The world's own law: the first ending whose ``when`` holds names it."""
    v = build_play_view(tpl, {"turn": 9, "alive": False, "lineage": {"hasHeir": False}})
    assert v["ended"] is True
    assert v["endingId"] == "line-ended"


def test_the_narrator_can_close_a_life_by_flag(tpl):
    """A bare truthy flag means over without a declared id; a string names one."""
    assert build_play_view(tpl, {"turn": 3, "ended": True})["endingId"] == "ended"
    assert build_play_view(tpl, {"turn": 3, "ended": "retired"})["endingId"] == "retired"


def test_unlocked_chapters_pass_through_and_default_empty(tpl):
    assert build_play_view(tpl, {"turn": 1})["unlocked"] == []
    v = build_play_view(tpl, {"turn": 2}, unlocked=["第七章 · 魔法的觉醒"])
    assert v["unlocked"] == ["第七章 · 魔法的觉醒"]


def test_world_decided_opening_values_are_revealed_at_birth(tpl) -> None:
    view = build_play_view(
        tpl,
        {"turn": 1, "opening": {"aptitude": "特殊", "race": "龙裔"}},
    )

    assert view["reveals"] == [{"label": "魔法资质", "value": "特殊"}]


def test_return_recap_uses_recent_unique_facts_without_generating_copy(tpl) -> None:
    chronicle = [
        {
            "turn": 1,
            "prose": "First",
            "action": "Keep the oath",
            "events": ["Swore an oath", "Met the knight"],
            "choices": [],
        },
        {
            "turn": 2,
            "prose": "Second",
            "action": "Open the letter",
            "events": ["Met the knight", "Learned the family secret", "Left home"],
            "choices": [
                {"id": "stay", "label": "Stay"},
                {"id": "go", "label": "Go"},
            ],
        },
    ]

    recap = build_play_view(tpl, {"turn": 2}, chronicle=chronicle)["recap"]

    assert recap == {
        "lastAction": "Open the letter",
        "events": ["Met the knight", "Learned the family secret", "Left home"],
        "choices": ["Stay", "Go"],
    }

def test_a_declared_ending_wins_over_the_bare_flag(tpl):
    v = build_play_view(
        tpl, {"turn": 9, "ended": True, "world": {"epochClosed": True}}
    )
    assert v["endingId"] == "world-epoch-closed"


def test_a_structured_value_in_a_scalar_field_renders_readable_lines():
    """The narrator wrote the whole family object into the one-line field. It must
    render its text, not a Python repr like {'held': True, ...}."""
    shaped = view_mod._shape(
        "field",
        {"held": True, "title": "维尔卡斯子爵", "wealth": "小贵族之家", "heirs": None},
    )
    assert shaped["kind"] == "lines"
    assert shaped["lines"] == ["维尔卡斯子爵", "小贵族之家"]
    # The gating boolean and the empty value are dropped, not shown as True/None.
    assert all("True" not in ln and "held" not in ln for ln in shaped["lines"])


def test_a_structured_value_with_no_text_is_a_gap():
    assert view_mod._shape("field", {"held": True})["kind"] == "gap"


# -- gaps -----------------------------------------------------------------


def test_a_field_the_narrator_has_not_mentioned_is_a_gap_not_an_error(tpl):
    v = build_play_view(tpl, {"turn": 1})
    status = v["panels"][0]
    assert all(f["kind"] == "gap" for f in status["fields"])
    assert status["empty"] is True


def test_a_panel_survives_a_missing_value(tpl):
    """R5.8 — hiding a panel because one number is absent would read to the
    player as something breaking."""
    v = build_play_view(tpl, {"turn": 1, "status": {"age": "十五岁"}})
    status = v["panels"][0]
    filled = [f for f in status["fields"] if f["kind"] != "gap"]
    assert len(filled) == 1
    assert len(status["fields"]) == 17
    assert status["empty"] is False


# -- primitives are shaped by config, never by field name ----------------


def test_no_shaping_branches_on_a_field_id():
    """The whole promise of the primitives: a world gets its panels by declaring
    them, with no code written per world. A branch on a field name here would be the
    first world-specific line in the app.

    Expressed as the real invariant — ``_shape`` may branch on its ``primitive``
    argument and on nothing else — rather than as a list of names not to mention.
    Two looser forms of this test have now been wrong in opposite directions: a
    substring search over the source went red on a comment containing "page"
    (which contains "age"), and a search over every string literal went red on
    ``x.get("name")``, where ``name`` is a structural key of the ``inventory`` entry
    shape and not anybody's field id. A branch is an ``if``, so test the ``if``.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(view_mod._shape)))

    compared: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # Only comparisons against a string literal can encode a world's vocabulary.
        against_text = any(
            isinstance(c, ast.Constant) and isinstance(c.value, str)
            for c in node.comparators
        )
        if against_text and isinstance(node.left, ast.Name):
            compared.add(node.left.id)

    assert compared, "the shaper branches on nothing at all; this test is inert"
    assert compared == {"primitive"}, (
        f"_shape branches on {sorted(compared - {'primitive'})} — a shaper may only "
        "look at the declared primitive, or the app has grown a world-specific line"
    )


def test_every_declared_primitive_has_a_shape():
    """A primitive the template validator accepts but the view cannot render
    would surface as a blank panel with no error anywhere."""
    for primitive in sorted(FIELD_PRIMITIVES):
        shaped = view_mod._shape(primitive, "x")
        assert shaped["kind"] != "gap", primitive


def test_a_stat_accepts_both_a_bare_number_and_a_capped_object():
    """A narrator that writes 40 and one that writes {value: 40, max: 100} mean
    the same thing; refusing one would be the app telling it how to write."""
    bare = view_mod._shape("stat", 40)
    capped = view_mod._shape("stat", {"value": 40, "max": 100})
    assert bare["value"] == capped["value"] == 40
    assert bare["pct"] is None
    assert capped["pct"] == pytest.approx(0.4)


def test_a_stat_over_its_cap_does_not_overflow_the_bar():
    assert view_mod._shape("stat", {"value": 300, "max": 100})["pct"] == 1.0
    assert view_mod._shape("stat", {"value": -5, "max": 100})["pct"] == 0.0


def test_a_zero_cap_does_not_divide_by_zero():
    assert view_mod._shape("resource", {"value": 3, "max": 0})["pct"] is None


def test_people_and_threads_accept_a_bare_string_or_a_list():
    one = view_mod._shape("people", "父亲")
    assert one["entries"] == [{"name": "父亲", "note": ""}]
    many = view_mod._shape("people", [{"name": "母亲", "note": "病重"}, "邻居"])
    assert many["entries"] == [
        {"name": "母亲", "note": "病重"}, {"name": "邻居", "note": ""}
    ]
    assert view_mod._shape("threads", ["父亲的债"])["entries"][0]["text"] == "父亲的债"


def test_an_inventory_drops_empty_entries():
    items = view_mod._shape("inventory", ["剑", "", {"name": "护符"}, {}])["items"]
    assert [i["name"] for i in items] == ["剑", "护符"]


def test_an_inventory_keeps_count_and_note():
    """"三瓶药水" must not shape down to the same chip as "一瓶"."""
    items = view_mod._shape(
        "inventory", [{"name": "药水", "count": 3, "note": "治疗"}, "剑"]
    )["items"]
    assert items[0] == {"name": "药水", "count": "3", "note": "治疗"}
    assert items[1] == {"name": "剑"}


def test_people_carry_declared_attribute_columns():
    """A people field that declares `attributes` keeps those columns per person;
    one that declares none is untouched."""
    plain = view_mod._shape("people", [{"name": "母亲", "note": "病重"}])
    assert plain["columns"] == [] and "cols" not in plain["entries"][0]

    shaped = view_mod._shape(
        "people",
        [{"name": "李衍", "attitude": "亲近", "closeness": "挚友"}],
        {"attributes": ["attitude", "closeness"]},
    )
    assert shaped["columns"] == ["attitude", "closeness"]
    assert shaped["entries"][0]["cols"] == {"attitude": "亲近", "closeness": "挚友"}


# -- the world's own clock -----------------------------------------------


def test_the_clock_is_formatted_from_the_worlds_own_label(tpl):
    v = build_play_view(tpl, {"turn": 3, "clock": {"year": 812, "month": 4}})
    assert v["clock"] == "812年·4月"


def test_an_unfilled_clock_says_nothing_rather_than_showing_a_placeholder(tpl):
    assert build_play_view(tpl, {"turn": 1})["clock"] == ""
    assert build_play_view(tpl, {"turn": 1, "clock": {"year": 812}})["clock"] == ""


# -- the world outside this life ----------------------------------------


def test_the_digest_only_carries_categories_the_world_names(tpl):
    """The categories are the world's OWN words (`国家`, `战争`, …), not slugs —
    so an app-invented key is simply not a category this world has."""
    state = {
        "turn": 1,
        "digest": {
            "国家": "王国在征税。",
            "invented-by-the-app": "这一条不该出现。",
            "rumours": ["有人说北边死了个骑士。", ""],
        },
    }
    v = build_play_view(tpl, state)
    cats = [d["category"] for d in v["digest"]]
    assert "国家" in cats
    assert "invented-by-the-app" not in cats
    assert cats.count("rumour") == 1
    assert cats.index("国家") < cats.index("rumour"), "world order, then rumours"


def test_an_empty_digest_is_empty_not_padded(tpl):
    assert build_play_view(tpl, {"turn": 1})["digest"] == []


# -- terminal framing is stripped, content is not -----------------------


def test_a_line_of_frame_is_dropped():
    assert strip_terminal_framing("╔════════╗\n他醒了。\n╚════════╝") == "他醒了。"


def test_words_inside_a_frame_survive():
    """The dangerous direction: a sanitiser that ate narration would be deleting
    the product."""
    out = strip_terminal_framing("│ 他醒了，天还没亮。 │")
    assert out == "他醒了，天还没亮。"


def test_markdown_structure_survives_because_it_is_structure():
    """The narrator writes markdown and the play page renders it, so markdown's
    own characters are content, not framing. An earlier revision stripped inline
    runs of ``*``/``-``/``=`` and pipes: it turned ``***他死了***`` into plain text
    and cut a table's pipes out, leaving its rows as loose words. R18 asks for a
    drawn box to go and structure to be RENDERED as structure — a table is
    structure."""
    assert strip_terminal_framing("***他死了***") == "***他死了***"
    table = "| 名字 | 关系 |\n|---|---|\n| 母亲 | 病重 |"
    assert strip_terminal_framing(table) == table
    assert strip_terminal_framing("# 第一章") == "# 第一章"
    assert strip_terminal_framing("- 一件事\n- 另一件事") == "- 一件事\n- 另一件事"


def test_a_paragraph_break_is_not_collapsed_away():
    """One blank line is a markdown paragraph break; runs of them are the debris
    a stripped frame leaves behind."""
    assert strip_terminal_framing("第一段。\n\n第二段。") == "第一段。\n\n第二段。"


def test_block_characters_and_bars_are_removed():
    assert "█" not in strip_terminal_framing("魔力 ████░░░░ 40/100")
    assert "40/100" in strip_terminal_framing("魔力 ████░░░░ 40/100")


def test_stripping_leaves_paragraphs_readable():
    out = strip_terminal_framing("第一段。\n\n\n\n第二段。")
    assert out == "第一段。\n\n第二段。"


def test_empty_prose_is_empty():
    assert strip_terminal_framing("") == ""
    assert strip_terminal_framing(None) == ""


def test_the_view_strips_framing_from_what_the_narrator_wrote(tpl):
    v = build_play_view(
        tpl, {"turn": 2}, chronicle=[{"turn": 2, "prose": "═══════\n下雪了。"}]
    )
    assert v["prose"] == "下雪了。"


# -- choices and scenes --------------------------------------------------


def test_choices_come_from_the_turn_that_was_committed(tpl):
    v = build_play_view(
        tpl, {"turn": 2},
        chronicle=[{"turn": 2, "prose": "p", "choices": [{"id": "a", "label": "走"}]}],
    )
    assert v["choices"] == [{"id": "a", "label": "走"}]


def test_a_turn_with_no_choices_offers_none_rather_than_a_default(tpl):
    """An app-invented "继续" would be the app putting words in the world's
    mouth. Free-text action is always available, so nothing is lost."""
    v = build_play_view(tpl, {"turn": 2}, chronicle=[{"turn": 2, "prose": "p"}])
    assert v["choices"] == []


def test_mounted_scenes_are_passed_through(tpl):
    scenes = [{"sceneId": "map", "asks": True, "answered": False}]
    assert build_play_view(tpl, {"turn": 1}, scenes=scenes)["scenes"] == scenes


# -- reading the shape a narrator actually wrote --------------------------


def test_a_flat_label_keyed_state_still_fills_the_panels(tpl):
    """A named regression, taken verbatim from the flagship's first real turn: the
    narrator declared every field at the TOP level, keyed by the Chinese labels it
    had been shown. Canonical is ``state[panelId][fieldId]``; losing a whole panel
    over a spelling is worse than accepting both."""
    state = {
        "turn": 1,
        "时间": "黄金王国312年·狼月",
        "年龄": "0岁（新生）",
        "种族": "兽人",
    }
    status = build_play_view(tpl, state)["panels"][0]
    filled = {f["label"]: f.get("value") for f in status["fields"] if f["kind"] != "gap"}
    assert filled["时间"] == "黄金王国312年·狼月"
    assert filled["年龄"] == "0岁（新生）"
    assert status["empty"] is False


def test_the_canonical_nested_shape_still_wins(tpl):
    state = {"turn": 1, "status": {"age": "十五岁"}, "年龄": "不该用这个"}
    status = build_play_view(tpl, state)["panels"][0]
    ages = [f for f in status["fields"] if f["id"] == "age"]
    assert ages[0]["value"] == "十五岁"


def test_a_digest_nested_under_the_worlds_own_name_is_found(tpl):
    """Verbatim from the same turn: it was nested under 「本月世界动态」, which is a
    better name than "digest" in that world's language. Refusing to look would have
    thrown away every world event the narrator wrote."""
    state = {
        "turn": 1,
        "本月世界动态": {
            "国家": "五大王国维持四十年边境稳定。",
            "魔兽": "草原深处有狼群南迁迹象。",
        },
    }
    cats = [d["category"] for d in build_play_view(tpl, state)["digest"]]
    assert "国家" in cats and "魔兽" in cats
