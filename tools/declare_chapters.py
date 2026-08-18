"""Declare the flagship's chapters, in its own headings.

Authoring a pack's header is the compiler agent's job; doing it here by hand is the
same work with the same output, and it is a change to ONE pack — no code in the app
knows any of these headings.

Only the group BOUNDARIES are declared, not all 174 chapters. Undeclared headings
belong to the declared chapter above them, so 27 declarations partition the whole book
and nothing becomes unreachable.

Gates reuse the flag vocabulary the pack's own panels already use
(``magic.awakened``, ``academy.enrolled``, ``office.high`` …) rather than inventing a
parallel one. Where a gate needs a flag the panels do not have, the condition still
reaches the narrator: the table of contents carries the ``when`` text verbatim, so it
can see what would open a chapter instead of only that one is closed.
"""

import pathlib
import sys

sys.path.insert(0, "backend")

SEED = pathlib.Path("seeds/jianhuo-jiyuan.md")

# (id, heading, always, when)
#
# `always` is the world's law and the parts of ordinary life every character lives
# inside. Gated chapters are institutions a life either enters or never touches.
# Ungated-and-not-always is reference the narrator may reach for when a month needs
# it — dragons exist whether or not this life ever meets one.
CHAPTERS: list[tuple[str, str, bool, str]] = [
    ("principles", "第二章 · 世界第一原则", True, ""),
    ("races", "第七章 · 种族系统", False, ""),
    ("nobility", "第十一章 · 四大主流政体", False, "state.office.high == true"),
    ("commoners", "第十八章 · 平民社会", False, ""),
    ("economy", "第二十章 · 经济系统", False, ""),
    ("guilds", "第二十六章 · 协会体系", False, "state.guild.member == true"),
    ("magic", "第三十章 · 魔法体系", False, "state.magic.awakened == true"),
    ("academy", "第四十章 · 魔法学校/学院", False, "state.academy.enrolled == true"),
    ("church", "第四十四章 · 教会体系", False, "state.faith.sworn == true"),
    ("beasts", "第五十一章 · 魔兽生态", False, ""),
    ("dungeons", "第五十六章 · 地下城系统", False, ""),
    ("demons", "第六十章 · 魔族系统", False, ""),
    ("travel", "第六十七章 · 旅行系统", False, ""),
    ("law", "第七十一章 · 奴役制度", False, ""),
    ("daily", "第七十七章 · 平民生活", False, ""),
    ("war", "第八十五章 · 战争系统", False, ""),
    ("crafting", "第九十一章 · 工匠系统", False, ""),
    ("legends", "第九十七章 · 传奇人物系统", False, ""),
    ("npcs", "第九十九章 · NPC自主系统", False, ""),
    ("climate", "第一百一十章 · 魔法气候", False, ""),
    ("classes", "第一百一十六章 · 社会阶层", False, ""),
    ("goals", "第一百二十一章 · 玩家人生目标", True, ""),
    ("failure", "第一百二十五章 · 失败系统", True, ""),
    # The reality protocols and the anti-halo rules. Always, and not negotiable: they
    # are the reason this world does not revolve around the player, and a narrator
    # that has to ask for them is a narrator that can forget to.
    ("protections", "第一百三十二章 · 现实性保护协议", True, ""),
    ("causality", "第一百三十九章 · 世界因果系统", True, ""),
    ("panels", "第一百四十七章 · 玩家状态栏", True, ""),
    ("domain", "第一百五十三章 · 领地系统", False, "state.domain.held == true"),
    ("endings", "第一百五十九章 · 末日不是唯一结局", True, ""),
    ("restraint", "第一百六十四章 · 防止世界过度热闹", True, ""),
    ("versioning", "第一百六十八章 · 世界规则更新", False, ""),
    ("identity", "第一百七十二章 · AI运行身份", True, ""),
]


def main() -> int:
    import yaml

    from template import split_front_matter

    raw = SEED.read_text(encoding="utf-8")
    header, prose = split_front_matter(raw)

    missing = [h for _i, h, _a, _w in CHAPTERS if h not in prose]
    if missing:
        print("headings not present in the prose:")
        for h in missing:
            print("   ", h)
        return 1
    if "chapters" in header:
        print("this pack already declares chapters; refusing to overwrite")
        return 1

    block = yaml.safe_dump(
        {
            "chapters": [
                {"id": cid, "heading": heading}
                | ({"always": True} if always else {})
                | ({"when": when} if when else {})
                for cid, heading, always, when in CHAPTERS
            ]
        },
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )

    # APPENDED to the existing YAML, not written over it. The front matter carries
    # the pack author's own comments — "every declaration below is traceable to a
    # chapter of the prose" — and re-serialising the parsed mapping would silently
    # delete all of them. A generator that destroys documentation to add a field is
    # not a generator anyone should run twice.
    close = raw.index("\n---\n", raw.index("\n") )
    head, tail = raw[:close], raw[close:]
    SEED.write_text(
        head + "\n\n# Which chapters the narrator is briefed with, and which the\n"
        "# world discloses later. Ids are this pack's own; headings are copied\n"
        "# verbatim from the prose below.\n" + block.rstrip() + tail,
        encoding="utf-8",
    )
    print(f"declared {len(CHAPTERS)} chapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
