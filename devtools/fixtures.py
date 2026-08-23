"""Fixture data for the UI screenshot harness.

The load-bearing decision here: a scenario is a SCRIPT OF TURNS driven through the
app's own write path (``endless_advance_turn``, ``SceneLedger``, ``BackdropStore``,
``KeepsakeStore``), never a hand-written JSON blob dropped into the data dir. A blob
freezes today's schema and then rots silently — the harness would keep producing
screenshots of a state the app can no longer produce. Driven through the real writer,
a schema change breaks seeding loudly, at the call that changed.

Every scenario is a separate life so one screenshot run can visit them all: the shelf
shows them side by side and each shot names the life it wants.

Content here is Chinese on purpose — it is fixture DATA, not code, and the app's
Chinese worlds are the ones whose text metrics matter (CJK wraps differently, and a
CJK label is wider per character than the English the tests use).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent / "backend"
SEEDS = Path(__file__).resolve().parent.parent / "seeds"


def _import_backend() -> Any:
    """Make the app's backend importable and hand back the MCP entry module.

    The MCP server is the app's single state writer, so it is the only door a
    fixture is allowed through for turn state.
    """
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    import mcp_server  # noqa: PLC0415

    return mcp_server


#: The world every fixture life is lived in — a real shipped pack, not a toy.
WORLD_ID = "last-echoes-zombie-sim"
#: The other shipped pack, and the only one that declares `lineage` — so the
#: cross-generation fixtures have to live here rather than in the one above.
LINEAGE_WORLD_ID = "age-of-sword-and-flame"


@dataclass
class Scenario:
    """One seeded life, plus what a shot recipe needs to reach it."""

    key: str
    #: The player-set LABEL for this life. A life's `title` is its world's name, and
    #: every life in one world therefore reads identically on the shelf — which is
    #: realistic and useless to click. A label is what a player renames a life to, it
    #: shows as the card's heading with the world name beneath it, and it gives each
    #: fixture life one unambiguous piece of text a recipe can address.
    label: str
    #: What this scenario exists to exercise, in one line (printed by `uishot list`).
    exercises: str
    #: ``(srv, data_dir, already_built)`` -> runId. The third argument carries the
    #: runIds of the scenarios built before this one, which is how the heir reaches
    #: the ended life it inherits from — a lineage fixture cannot be built in
    #: isolation, and faking one would mean hand-writing the bridge record the app
    #: builds itself.
    build: Callable[[Any, Path, dict[str, str]], str]
    #: Filled in at seed time with the runId the build produced.
    run_id: str = field(default="", compare=False)


# ── the turn scripts ────────────────────────────────────────────────────────


_PROSE_LONG = (
    "井台的水终于清了。你把第二桶灌满，铁皮桶沿磕在石头上，声音在空院子里传得很远——比你想的远。\n\n"
    "小云站在三步外，没有再往前。她的脚踝肿着，重心全压在另一条腿上，手里还攥着那把从楼梯口捡的"
    "螺丝刀，刀尖朝下，不是要用，是不敢放。\n\n"
    "“据点里还有个人，”你说，“叫阿美。腿伤了，在看家。不会只有我们两个。”\n\n"
    "她抬眼看了你一下，又低下去。风把帆布掀起一角，远处城西的黑烟还在往这边压。她没有说好，也没有"
    "说不好。\n\n"
    "你没有催。催一个刚从两天独处里走出来的人，只会让她把那把螺丝刀攥得更紧。你把桶盖扣好，蹲下去"
    "检查绳结——这是你能给她的全部时间。"
)

_PROSE_SHORT = "水压出来了，前两下是浑的，第三下开始变清。你把桶挪到出水口下面。"

#: A scene with a spatial kind (grid) — the map. Structure only, no geometry.
_SCENE_MAP: dict[str, Any] = {
    "title": "周边地图",
    "elements": [
        {
            "kind": "grid",
            "columns": 3,
            "cells": [
                {"label": "江城市区", "note": "大部分街道被异样人占据", "mark": "⚠"},
                {"label": "陈屿的据点", "note": "老城区旧楼顶层，楼梯口封死", "mark": True},
                {"label": "阿美所在邻楼", "note": "四楼躲藏，独自撑了两天"},
                {"label": "红星大超市", "note": "三街区外，已失控", "mark": "⚠"},
                {"label": "体育中心安置点", "note": "蓝白警告：早已沦陷，勿前往", "mark": "☠"},
                {"label": "城西方向", "note": "蓝白指引的方向；远处黑烟正往此蔓延"},
            ],
        }
    ],
}

#: A ledger built from `pairs` — the shape whose empty rendering was the bug that
#: made the cached-compiler defect visible. Worth keeping in the fixture set forever.
_SCENE_LEDGER: dict[str, Any] = {
    "title": "据点物资核算 · 两人份",
    "elements": [
        {"kind": "heading", "text": "食物"},
        {
            "kind": "keyvalue",
            "pairs": [
                {"key": "存货", "value": "整车囤货，原按一人省吃可撑约178天"},
                {"key": "两人消耗", "value": "每日消耗接近翻倍，实际约可撑90天"},
                {"key": "结论", "value": "食物压力可控，但不能再指望像之前那样宽裕"},
            ],
        },
        {"kind": "divider"},
        {"kind": "heading", "text": "饮水"},
        {
            "kind": "keyvalue",
            "pairs": [
                {"key": "存货", "value": "桶装+瓶装若干，原按一人可撑2-3周"},
                {"key": "两人消耗", "value": "饮用+清创用水叠加，实际约1-1.5周"},
                {"key": "集雨系统", "value": "已搭好，但这几天无雨，暂时指望不上"},
                {"key": "结论", "value": "水是眼下最紧的一项，撑不到下一次真正下雨"},
            ],
        },
        {"kind": "divider"},
        {"kind": "heading", "text": "药品"},
        {
            "kind": "keyvalue",
            "pairs": [
                {"key": "存货", "value": "碘伏、纱布、止痛药、抗生素等，部分已用于阿美"},
                {"key": "结论", "value": "消耗速度会比一人时快，需要开始省着用"},
            ],
        },
    ],
}

#: An asking scene — the play page renders its choices, so the harness can shoot the
#: interactive shape as well as the read-only one.
_SCENE_ASK: dict[str, Any] = {
    "title": "取水顺序",
    "elements": [
        {"kind": "text", "text": "两个桶，一趟只能拎一个走。"},
        {"kind": "choice", "label": "先把满的搬回去", "id": "full-first"},
        {"kind": "choice", "label": "两个都灌满再一起搬", "id": "both"},
    ],
}

#: A minimal valid backdrop: the store validates it, so this proves the real path.
_BACKDROP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900">'
    '<rect width="1200" height="900" fill="#0b0f14"/>'
    '<circle cx="900" cy="220" r="120" fill="#16222c"/>'
    '<rect y="620" width="1200" height="280" fill="#101922"/></svg>'
)
_BACKDROP_MOBILE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 1400">'
    '<rect width="780" height="1400" fill="#0b0f14"/>'
    '<circle cx="600" cy="300" r="140" fill="#16222c"/>'
    '<rect y="1040" width="780" height="360" fill="#101922"/></svg>'
)


def _advance(
    srv: Any, run: str, turn: int, prose: str, state: dict[str, Any], **extra: Any
) -> None:
    args: dict[str, Any] = {
        "runId": run,
        "turn": turn,
        "prose": prose,
        "state": state,
        "choices": [
            {"id": "wait", "label": "等她自己开口"},
            {"id": "carry", "label": "先把水搬回去"},
        ],
        **extra,
    }
    out = json.loads(srv.call_tool("endless_advance_turn", args))
    if out.get("committed") is not True:
        raise RuntimeError(f"turn {turn} refused: {out}")


def _new_run(srv: Any, title: str, *, language: str = "zh", world: str = WORLD_ID) -> str:
    store = srv._store()
    return store.create_run(
        {"turn": 0, "worldId": world, "language": language, "alive": True},
        {"runId": "", "worldId": world, "title": title, "turn": 0},
    )


def _label(srv: Any, run: str, label: str) -> None:
    """Set the life's player-facing label (the shelf card's heading)."""
    if not srv._store().patch_index(run, {"label": label}):
        raise RuntimeError(f"no index row to label for {run}")


#: Every life lives in the same shipped world, so their `title` is identical — the
#: label is what tells them apart on the shelf and in a shot recipe.
WORLD_TITLE = "末世残响"


def _build_rich(srv: Any, data: Path, built: dict[str, str]) -> str:
    """The workhorse: a life deep enough to have every surface populated."""
    from backdrop import BackdropStore  # noqa: PLC0415
    from keepsakes import KeepsakeStore  # noqa: PLC0415
    from scenes import SceneLedger  # noqa: PLC0415

    run = _new_run(srv, WORLD_TITLE)
    base = {"alive": True, "worldId": WORLD_ID, "language": "zh"}
    memory = {
        "entities": [
            {"id": "c1", "kind": "character", "name": "陈屿", "summary": "本人"},
            {"id": "c2", "kind": "character", "name": "阿美", "summary": "据点同伴，腿伤未愈"},
            {"id": "c3", "kind": "character", "name": "小云", "summary": "井边遇到的幸存者"},
            {"id": "p1", "kind": "place", "name": "老城区据点", "summary": "旧楼顶层"},
            {"id": "p2", "kind": "place", "name": "住宅区水井", "summary": "手压式，铰链锈响"},
            {"id": "o1", "kind": "object", "name": "手摇收音机", "summary": "电池将尽"},
            {"id": "g1", "kind": "group", "name": "体育中心残余", "summary": "广播里那批人"},
        ],
        # A thread is declared BY an event, with the effect that event had on it —
        # there is no thread list at the memory root, and one put there is dropped in
        # silence. Same for who was present: the field is `participants`.
        "events": [
            {
                "id": "e-well",
                "title": "试压水井",
                "summary": "压出浑水，第三下开始变清",
                "participants": ["player", "c2"],
                "place": "p2",
                "importance": "major",
                "threads": [{"id": "t-water", "effect": "opened"}],
            }
        ],
    }
    _advance(srv, run, 1, _PROSE_SHORT, {**base, "turn": 1}, memory=memory)
    # Memory on EVERY turn, not just the first: the star map's timeline lens draws one
    # row per known event, so a single-event graph makes a populated map look empty and
    # hides exactly the spacing defects the shot is taken to inspect.
    _advance(
        srv,
        run,
        2,
        _PROSE_LONG,
        {**base, "turn": 2},
        memory={
            "events": [
                {
                    "id": "e-door",
                    "title": "隔门对话",
                    "summary": "对方是个人，不是异样人",
                    "participants": ["player", "c3"],
                    "place": "p2",
                    "importance": "major",
                    "threads": [{"id": "t-join", "effect": "opened"}],
                }
            ],
        },
    )
    _advance(
        srv,
        run,
        3,
        _PROSE_LONG,
        {**base, "turn": 3},
        memory={
            "events": [
                {
                    "id": "e-invite",
                    "title": "发出邀请",
                    "summary": "她犹豫，没有答应",
                    "participants": ["player", "c2", "c3"],
                    "importance": "major",
                    "threads": [{"id": "t-join", "effect": "advanced"}],
                }
            ],
            # Relations hang off the PROTAGONIST entity the app itself creates
            # (`player`). The relations lens orbits the life's centre, which is that
            # entity — edges between two side characters leave it reading "no
            # relationships recorded yet" no matter how many were stored.
            "relations": [
                {"from": "player", "to": "c2", "type": "同伴", "value": "互相托付：她看家，我出门"},
                {"from": "player", "to": "c3", "type": "陌生", "value": "刚建立的谨慎信任"},
            ],
        },
    )

    ledger = SceneLedger(data, run)
    ledger.mount("local-map", _SCENE_MAP, region="world", label="地图")
    ledger.mount("supply-ledger", _SCENE_LEDGER, region="pack", label="物资")
    ledger.mount("water-order", _SCENE_ASK, asks=True, region="tasks", label="取水")

    BackdropStore(data, run).set(_BACKDROP, turn=3, mobile=_BACKDROP_MOBILE)

    keeps = KeepsakeStore(data, run)
    # A keepsake must cite a real event, and event ids are DERIVED by the graph
    # (``event-<turn>-<slug>``) rather than taken from what the narrator sent — so read
    # them back instead of guessing. Guessing here is exactly the drift this harness
    # exists to avoid.
    events = _event_ids(srv, run)
    if not events:
        raise RuntimeError("no events in the seeded graph; the memory payload was dropped")
    keeps.create(
        kind="event",
        title="第三下水才变清",
        thought="那一刻才真的相信这口井能用",
        cites=events[:1],
        turn=1,
    )
    keeps.create(
        kind="excerpt",
        title="隔着一道门问出的名字",
        thought="两天没跟活人说话，声音是抖的",
        excerpt="她抬眼看了你一下，又低下去。",
        turn=2,
    )
    return run


def _event_ids(srv: Any, run: str) -> list[str]:
    """The event ids the memory graph actually derived for this life."""
    from memory_graph import build_index  # noqa: PLC0415

    index = build_index(srv._store().read_chronicle(run))
    return sorted(index.get("events") or {})


def _build_short_turn(srv: Any, data: Path, built: dict[str, str]) -> str:
    """A page barely taller than the viewport — the geometry that exposes a sheet or
    a scene frame sized from the story rather than from itself."""
    run = _new_run(srv, WORLD_TITLE)
    _advance(srv, run, 1, _PROSE_SHORT, {"alive": True, "turn": 1, "language": "zh"})
    return run


def _build_ended(srv: Any, data: Path, built: dict[str, str]) -> str:
    """A closed life: the shelf marks it, and the ending recap is reachable."""
    run = _new_run(srv, WORLD_TITLE)
    _advance(srv, run, 1, _PROSE_SHORT, {"alive": True, "turn": 1, "language": "zh"})
    _advance(
        srv,
        run,
        2,
        "水没能撑到下一场雨。",
        {"alive": False, "turn": 2, "language": "zh", "ended": "died"},
    )
    return run


def _build_long_title(srv: Any, data: Path, built: dict[str, str]) -> str:
    """A title no shelf card was designed for — the cheapest way to find a clamp that
    was never applied."""
    run = _new_run(srv, WORLD_TITLE)
    _advance(srv, run, 1, _PROSE_SHORT, {"alive": True, "turn": 1, "language": "zh"})
    return run


def _build_english(srv: Any, data: Path, built: dict[str, str]) -> str:
    """The same app in English: label widths differ enough to break a row that fits
    in Chinese, and this app ships both."""
    run = _new_run(srv, "Last Echoes", language="en")
    _advance(
        srv,
        run,
        1,
        "The pump gave muddy water twice, then ran clear.",
        {"alive": True, "turn": 1, "language": "en"},
    )
    return run


def _build_lineage_ended(srv: Any, data: Path, built: dict[str, str]) -> str:
    """A finished life in the world that declares lineage — the source an heir needs.

    Kept separate from the plain `ended` life because inheritance has real
    preconditions: only the lineage world offers it, and only entities the finished
    life VISIBLY held are inheritable, so this life has to have actually lived with
    the people it passes on.
    """
    run = _new_run(srv, LINEAGE_WORLD_ID, world=LINEAGE_WORLD_ID)
    base = {"alive": True, "worldId": LINEAGE_WORLD_ID, "language": "zh"}
    _advance(
        srv,
        run,
        1,
        "洪水冲垮石桥的那晚，你把艾琳从水里拉上岸。她的手一直没有松开。",
        {**base, "turn": 1},
        memory={
            "entities": [
                {"id": "elin", "kind": "character", "name": "艾琳", "summary": "洪水那夜救下的人"},
                {"id": "bridge", "kind": "place", "name": "石桥渡口", "summary": "旧桥垮塌处"},
                {"id": "ring", "kind": "object", "name": "母亲的银环", "summary": "家中仅剩的旧物"},
            ],
            "events": [
                {
                    "id": "e-flood",
                    "title": "洪水与石桥",
                    "summary": "把艾琳从水里拉上岸",
                    "participants": ["player", "elin"],
                    "place": "bridge",
                    "importance": "major",
                    "threads": [{"id": "t-debt", "effect": "opened"}],
                }
            ],
            "relations": [
                {"from": "player", "to": "elin", "type": "恩义", "value": "她认下这条命的分量"}
            ],
        },
    )
    _advance(
        srv,
        run,
        2,
        "许多年后，你把银环留在她手里，说了最后一句话。",
        {**base, "turn": 2, "alive": False, "ended": "died"},
        memory={
            "events": [
                {
                    "id": "e-last",
                    "title": "银环易主",
                    "summary": "把母亲的银环交给艾琳",
                    # The ring is listed as a participant, not merely declared as an
                    # entity: `legacy.candidates` only offers what a known event
                    # actually touched, so a declared-but-untouched heirloom is
                    # refused by the bridge — correctly.
                    "participants": ["player", "elin", "ring"],
                    "importance": "major",
                    "threads": [{"id": "t-debt", "effect": "resolved"}],
                }
            ],
        },
    )
    return run


def _build_heir(srv: Any, data: Path, built: dict[str, str]) -> str:
    """The next generation: a life whose FIRST chronicle record is a legacy bridge.

    Built the way the app builds it — ``legacy.build_bridge_record`` over the source
    life's own graph index, appended as turn 0 — so the inherited entities and the
    relation they arrive with are exactly what a player's heir would carry, and the
    ending page's own gates (lineage world, source life over, same world) hold.
    """
    from legacy import build_bridge_record  # noqa: PLC0415
    from memory_graph import build_index  # noqa: PLC0415

    source = built.get("lineage-ended")
    if not source:
        raise RuntimeError("the heir needs the finished lineage life built first")
    store = srv._store()
    index = build_index(store.read_chronicle(source))

    run = _new_run(srv, LINEAGE_WORLD_ID, world=LINEAGE_WORLD_ID)
    bridge = build_bridge_record(
        index,
        source_run_id=source,
        selected=["elin", "ring"],
        language="zh",
    )
    store.append_turn(run, bridge)
    _advance(
        srv,
        run,
        1,
        "你在祖母的名字下长大。银环挂在门后，艾琳还记得那条命是谁给的。",
        {"alive": True, "worldId": LINEAGE_WORLD_ID, "language": "zh", "turn": 1},
    )
    return run


SCENARIOS: list[Scenario] = [
    Scenario(
        "rich",
        "第三天 · 井边",
        "the workhorse: 3 turns, 3 mounted scenes (grid map / keyvalue ledger / asking), "
        "a committed backdrop, a memory graph and two keepsakes",
        _build_rich,
    ),
    Scenario("short", "一回合", "a one-turn page, for height-coupled layout", _build_short_turn),
    Scenario(
        "ended", "撑不到雨季", "a closed life: shelf marking and the ending recap", _build_ended
    ),
    Scenario(
        "longtitle",
        "江城地下水位与集雨系统长期可持续性观测记录（第二年修订版·附录三）",
        "a label no shelf card was designed for: clamping and wrapping",
        _build_long_title,
    ),
    Scenario(
        "english",
        "Day Three",
        "the English pack: wider labels than the Chinese one",
        _build_english,
    ),
    # Order matters from here down: the heir is built FROM the finished life above it.
    Scenario(
        "lineage-ended",
        "石桥那一夜",
        "a finished life in the lineage world — the source of an inheritance, with "
        "entities a player visibly lived with",
        _build_lineage_ended,
    ),
    Scenario(
        "heir",
        "银环的下一代",
        "the next generation: a life whose first record is a legacy bridge carrying a "
        "person and an object across from the life above",
        _build_heir,
    ),
]


def seed_all(data_dir: Path) -> dict[str, str]:
    """Seed every scenario into ``data_dir``; return ``{scenario key: runId}``.

    ``data_dir`` is the app's own data directory — for a throwaway instance that is
    ``<home>/apps/endless-worlds/data``.

    Must run under an interpreter that can import the host gateway package: the app's
    store is built on the host's ``AppStorage``, and seeding through anything else
    would be seeding a different thing than the app reads. ``uishot`` therefore runs
    this module as a script under that interpreter (see ``__main__`` below).
    """
    srv = _import_backend()
    srv._DATA = data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    from library import WorldLibrary  # noqa: PLC0415

    # Install the bundled packs the way the app does on first run, so the shelf has
    # real worlds rather than fixtures pretending to be worlds.
    WorldLibrary(data_dir, SEEDS).ensure_seeds_installed()

    out: dict[str, str] = {}
    for sc in SCENARIOS:
        sc.run_id = sc.build(srv, data_dir, out)
        _label(srv, sc.run_id, sc.label)
        out[sc.key] = sc.run_id
    return out


if __name__ == "__main__":
    # `python fixtures.py <data-dir>` — prints {scenario: runId} as JSON.
    print(json.dumps(seed_all(Path(sys.argv[1]))))
