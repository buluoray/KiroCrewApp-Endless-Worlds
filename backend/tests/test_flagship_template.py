"""The flagship template must load, and must need zero capability packs.

These are the Task 5 acceptance checks (R1.5, R5.1, R5.2, R5.7, R14.1) run
against the real 剑火纪元 file that ships with the app — not a synthetic
stand-in. If the header and the prose ever drift apart, this is what catches it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from template import FIELD_PRIMITIVES, parse_template  # noqa: E402

TEMPLATE_PATH = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"


@pytest.fixture(scope="module")
def flagship():
    if not TEMPLATE_PATH.is_file():
        pytest.fail(f"flagship template missing at {TEMPLATE_PATH}")
    return parse_template(TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_it_loads(flagship) -> None:
    assert flagship.id == "age-of-sword-and-flame"
    assert flagship.language == "zh"
    assert flagship.version == "1.0"


def test_prose_carries_core_rules_while_facts_live_in_lore(flagship) -> None:
    """R14.1, data-first form — the raw rulebook's world FACTS were extracted into
    `lore` (browsable + keyword/hand-off), so the prose the narrator reads is now the
    PREAMBLE plus the core narrative rules, not the 170-odd raw reference chapters.
    """
    prose = flagship.prose
    # The framing the book opens with is kept as the preamble.
    assert "第一章 · 核心定位" in prose
    # The load-bearing narrative laws stay in prose, in the world's own words.
    assert "世界第一原则" in prose
    assert "世界不围绕玩家存在" in prose
    assert "终极原则" in prose
    # App plumbing the app itself performs was stripped, not carried, and the
    # heading-referenced reference chapters became data.
    assert "第一百七十四章 · 正式启动界面" not in prose
    assert "存档系统" not in prose
    # A truncation regression still shows here, but the floor now sits at the cleaned
    # size — the raw paste's reference chapters are lore now, not prose.
    assert len(prose) > 2_000, f"prose looks truncated: {len(prose)} chars"
    # The world's facts moved into structured lore entries (was ~8, now the full set).
    assert len(flagship.lore) >= 40, f"world facts not extracted to lore: {len(flagship.lore)}"
    assert any(e.id == "races-and-culture" for e in flagship.lore)


def test_clock_and_lineage_match_the_prose(flagship) -> None:
    # 第一百四十七章 — 【时间】XXX年·XXX月
    assert flagship.clock_unit == "month"
    assert "{year}" in flagship.clock_label and "{month}" in flagship.clock_label
    # 第一百二十八章 · 多世代模式
    assert flagship.lineage is True


def test_six_simulation_styles_with_one_default(flagship) -> None:
    """第一百七十四章 — 【模拟风格】① 极度现实 … ⑥ 混合模式"""
    assert [s.label for s in flagship.styles] == [
        "极度现实",
        "经典西幻冒险",
        "史诗魔幻",
        "黑暗奇幻",
        "日常人生",
        "混合模式",
    ]
    assert flagship.default_style.label == "经典西幻冒险"


def test_thirteen_declared_opening_groups_plus_the_style_chooser(flagship) -> None:
    """第一百七十四章 declares 14 questions; style is the 14th and lives in
    `styles` so it is not defined twice."""
    assert len(flagship.opening) == 13
    assert [g.id for g in flagship.opening] == [
        "era", "race", "birth", "name", "age", "sex", "birthplace",
        "family", "skills", "aptitude", "faith", "personality", "goal",
    ]


def test_the_three_list_groups_offer_the_prose_custom_tail(flagship) -> None:
    """Each of 时代/种族/出生身份 ends with 自定义 in the prose (R2.2)."""
    by_id = {g.id: g for g in flagship.opening}
    for gid in ("era", "race", "birth"):
        assert by_id[gid].custom is True, f"{gid} must offer a custom option"
        assert by_id[gid].options, f"{gid} must list its options"
    # 第三十三章 · 魔法资质 — ⑥随机 is a roll action, not a holdable value.
    assert by_id["aptitude"].random is True
    assert "随机" not in by_id["aptitude"].options


def test_status_panel_is_the_seventeen_field_bar(flagship) -> None:
    """第一百四十七章 · 玩家状态栏 — 17 fields, always visible (R5.1)."""
    status = flagship.panels[0]
    assert status.id == "status"
    assert status.always is True
    assert len(status.fields) == 17
    assert [f.label for f in status.fields] == [
        "时间", "年龄", "种族", "身份", "所在地", "职业", "财富", "家庭",
        "社会地位", "魔法能力", "战斗能力", "神术/信仰", "技能", "声望",
        "重要关系", "所属势力", "当前目标",
    ]


def test_all_panel_labels_are_localized(flagship) -> None:
    assert [(panel.id, panel.label) for panel in flagship.panels] == [
        ("status", "角色状态"),
        ("magic", "魔法能力"),
        ("relations", "社会关系"),
        ("nation", "国家"),
        ("academy", "学院"),
        ("family", "家族"),
    ]

def test_the_five_conditional_panels_match_chapters_148_to_152(flagship) -> None:
    """R5.2 — each appears only when its trigger is met."""
    conditional = {p.id: p for p in flagship.panels if not p.always}
    assert set(conditional) == {"magic", "relations", "nation", "academy", "family"}
    assert len(conditional["magic"].fields) == 8      # 第一百四十八章
    assert len(conditional["nation"].fields) == 12    # 第一百五十章
    assert len(conditional["academy"].fields) == 9    # 第一百五十一章
    assert len(conditional["family"].fields) == 10    # 第一百五十二章
    for panel in conditional.values():
        assert panel.when is not None


def test_a_fresh_character_sees_only_the_status_bar(flagship) -> None:
    """第一百二十二章 — 玩家可以不学魔法. That life shows no magic panel."""
    assert [p.id for p in flagship.panels_for({})] == ["status"]


def test_panels_appear_as_the_life_opens_up(flagship) -> None:
    state = {
        "magic": {"awakened": True},
        "relations": {"known": True},
        "academy": {"enrolled": True},
        "family": {"held": True},
        "office": {"high": False},
    }
    visible = [p.id for p in flagship.panels_for(state)]
    assert visible == ["status", "magic", "relations", "academy", "family"]
    assert "nation" not in visible, "not high office yet"

    state["office"]["high"] = True
    assert "nation" in [p.id for p in flagship.panels_for(state)]


def test_nine_digest_categories_with_rumour(flagship) -> None:
    """第一百四十六章 · 月度世界演化 (R6.1)."""
    assert flagship.digest_categories == [
        "国家", "战争", "教会", "学院", "经济", "魔兽", "魔族", "冒险者", "你所在地区",
    ]
    assert flagship.digest_rumours is True


def test_endings_detect_terminal_state_without_enumerating_outcomes(flagship) -> None:
    """第一百五十九/一百六十章 — 末日不是唯一结局, 无固定结局.

    The header must NOT name outcomes (魔法黄金时代 / 大魔灾毁灭世界 / …): those
    are produced by world state and written by the narrator. Enumerating them
    would turn an open world into a menu, so this test pins their absence.
    """
    ids = [e.id for e in flagship.endings]
    assert ids == ["line-ended", "world-epoch-closed", "retired"]
    for named_outcome in ("魔法黄金时代", "大魔灾毁灭世界", "魔族统治", "精灵复兴"):
        assert not any(named_outcome in e.when.source for e in flagship.endings)


def test_death_with_an_heir_is_not_an_ending(flagship) -> None:
    """R11.2 — death advances the generation while an heir exists."""
    by_id = {e.id: e for e in flagship.endings}
    dead_with_heir = {"alive": False, "lineage": {"hasHeir": True}}
    dead_no_heir = {"alive": False, "lineage": {"hasHeir": False}}
    assert by_id["line-ended"].when.evaluate(dead_with_heir) is False
    assert by_id["line-ended"].when.evaluate(dead_no_heir) is True


def test_a_world_level_ending_needs_no_death(flagship) -> None:
    """第一百五十九章 — the world can close an era with the player still alive."""
    by_id = {e.id: e for e in flagship.endings}
    alive_world_over = {"alive": True, "world": {"epochClosed": True}}
    assert by_id["world-epoch-closed"].when.evaluate(alive_world_over) is True


def test_retiring_early_is_available(flagship) -> None:
    by_id = {e.id: e for e in flagship.endings}
    assert by_id["retired"].when.evaluate({"retiredByPlayer": True}) is True
    assert by_id["retired"].when.evaluate({}) is False


def test_sixteen_save_categories(flagship) -> None:
    """第一百七十章 · 存档系统 (R9.2)."""
    assert len(flagship.save_schema) == 16
    for required in ("角色", "NPC", "世界变量", "未完成事件"):
        assert required in flagship.save_schema


def test_the_flagship_needs_zero_capability_packs(flagship) -> None:
    """R1.5 / R5.7 — the shipped world renders from core primitives alone.

    This is the load-bearing assertion of the whole core-first design: if the
    flagship needed a pack, packs would have become the mechanism rather than
    the escape hatch.
    """
    used = {f.primitive for p in flagship.panels for f in p.fields}
    assert used <= FIELD_PRIMITIVES, f"unknown primitives: {used - FIELD_PRIMITIVES}"


def test_every_field_id_is_unique_within_its_panel(flagship) -> None:
    for panel in flagship.panels:
        ids = [f.id for f in panel.fields]
        assert len(ids) == len(set(ids)), f"duplicate field id in panel {panel.id}"
