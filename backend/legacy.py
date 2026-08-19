"""The legacy bridge — carrying chosen inheritance into a next life (design §9).

Lives are isolated by construction: every fact graph is derived from its own
run's chronicle, and no tool or route reads across runs. The bridge does not
weaken that — it COPIES a selected subgraph into the new life's own canonical
record, stamped with provenance, at the moment the life is created. After
that, the two lives share nothing: the heir's story cannot reach back, and the
ancestor's later state never leaks forward. 传承不是共享可变图。

How the copy lands matters more than what it contains. It is written as a
**turn-0 chronicle entry** in the NEW run — the same canonical form every
narrated turn uses — so the Phase 0 invariants hold untouched: the index is
still rebuildable from the chronicle alone, and deleting the life still erases
everything with the run directory. There is no second store to keep honest.

Provenance (``inheritsFrom``) is stamped HERE, server-side. The narrator has
no path to forge it: ``endless_advance_turn``'s entity schema closes its
property list, so a declared memory block carrying ``inheritsFrom`` is refused
at the published-schema gate before any handler runs.

What the next narrator sees is the SUMMARY, never the source graph (§9): the
copied entities with one line each, and a bridge event that anchors them. The
ancestor's run id lives only in the provenance on disk — it is never served to
the narrator, which is what "不能读取上一世全部私有图" means structurally.
"""

from __future__ import annotations

import time
from typing import Any

from memory_graph import PLAYER

#: The bridge event's in-turn key. Turn 0 belongs to the app, so this cannot
#: collide with a narrator-declared key (those live on turns >= 1).
BRIDGE_KEY = "legacy-bridge"

#: How many things one heir can carry. A cap keeps the next life a story with
#: an inheritance, not a save-file import.
MAX_INHERITED = 12

_STRINGS = {
    "zh": {"bridge": "传承", "summary": "上一代留给这一世的东西。",
           "from": "来自上一世"},
    "en": {"bridge": "Inheritance", "summary": "What the last life left to this one.",
           "from": "from a life before"},
}


def _s(lang: str, key: str) -> str:
    return _STRINGS.get(lang, _STRINGS["en"])[key]


class LegacyError(ValueError):
    def __init__(self, field: str, expected: str) -> None:
        super().__init__(f"{field}: {expected}")
        self.field = field
        self.expected = expected


# ── what the ending screen offers (§9 step 1) ────────────────────────────


def candidates(index: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The inheritable things of a finished life, grouped the way §9 names them.

    Only entities the player has LIVED: an entity whose every appearance is
    hidden or foreshadowed never becomes a candidate — the ending screen must
    not reveal what the story didn't (§5.4). Characters carry their current
    relation readings so the choice is informed.
    """
    visible: set[str] = set()
    appearances: dict[str, int] = {}
    for ev in index["events"].values():
        if ev["disclosure"] != "known":
            continue
        touched = set(ev["participants"]) | {th["id"] for th in ev["threads"]}
        if ev["place"]:
            touched.add(ev["place"])
        for eid in touched:
            visible.add(eid)
            appearances[eid] = appearances.get(eid, 0) + 1
    visible.discard(PLAYER)

    from memory_graph import project_relations

    projection = project_relations(index)
    relations_of: dict[str, list[dict[str, Any]]] = {}
    for slot in projection.values():
        if not slot["active"]:
            continue
        for end in (slot["from"], slot["to"]):
            if end != PLAYER:
                relations_of.setdefault(end, []).append({
                    "type": slot["type"], "level": slot["level"],
                    "value": slot["value"],
                })

    groups: dict[str, list[dict[str, Any]]] = {
        "characters": [], "objects": [], "groups": [], "threads": [], "places": [],
    }
    kind_to_group = {"character": "characters", "object": "objects",
                     "group": "groups", "thread": "threads", "place": "places"}
    for eid in sorted(visible):
        ent = index["entities"].get(eid)
        if ent is None:
            continue
        row: dict[str, Any] = {
            "id": eid, "kind": ent["kind"], "name": ent["name"],
            "summary": ent["summary"], "appearances": appearances.get(eid, 0),
        }
        if ent["kind"] == "character" and eid in relations_of:
            row["relations"] = relations_of[eid]
        if ent["kind"] == "thread":
            rec = index["threads"].get(eid) or {}
            row["open"] = bool(rec.get("opened")) and not rec.get("resolved")
        groups[kind_to_group[ent["kind"]]].append(row)
    return groups


# ── the bridge record (§9 steps 3–4) ─────────────────────────────────────


def build_bridge_record(
    source_index: dict[str, Any],
    *,
    source_run_id: str,
    selected: list[str],
    language: str = "en",
) -> dict[str, Any]:
    """The turn-0 chronicle entry that carries the inheritance into a new life.

    Validation is whole-or-nothing, like a narrated memory block: every
    selected id must be an entity the finished life visibly held, or the whole
    bridge is refused with the offending field named.

    The record's shape IS a normal turn record with a normal ``memory`` block —
    entities plus one ``known`` bridge event they all participate in, plus a
    ``set`` relation change per carried relation whose ``reasonEvent`` is the
    bridge event. That gives §4.3 to inherited relations too: "she trusts you"
    opens into "because of what was carried across", not into nothing.
    """
    if not selected:
        raise LegacyError("selected", "at least one thing to carry over")
    if len(selected) > MAX_INHERITED:
        raise LegacyError("selected", f"at most {MAX_INHERITED} things")

    allowed = candidates(source_index)
    visible = {row["id"] for rows in allowed.values() for row in rows}
    picked: list[str] = []
    for i, raw in enumerate(selected):
        eid = str(raw)
        if eid not in visible:
            raise LegacyError(
                f"selected[{i}]",
                f"something this life visibly held, got {eid!r}",
            )
        if eid not in picked:
            picked.append(eid)

    entities: list[dict[str, Any]] = []
    for eid in picked:
        src = source_index["entities"][eid]
        entities.append({
            "id": eid,
            "kind": src["kind"],
            "name": src["name"],
            "aliases": list(src["aliases"]),
            "summary": src["summary"],
            # Stamped by the app, never by a narrator: the tool schema has no
            # such field, so this can only originate here (§9 step 4).
            "inheritsFrom": {
                "runId": source_run_id,
                "nodeId": eid,
                "turn": int(src.get("firstTurn") or 0),
            },
        })

    from memory_graph import project_relations

    relations: list[dict[str, Any]] = []
    projection = project_relations(source_index)
    for slot in projection.values():
        if not slot["active"]:
            continue
        ends = {slot["from"], slot["to"]}
        # A relation crosses the bridge only when everything it touches did:
        # the player, plus carried entities. A relation to someone left behind
        # would name a node the new graph does not hold.
        if not ends <= (set(picked) | {PLAYER}):
            continue
        level = slot["level"]
        relations.append({
            "from": slot["from"], "type": slot["type"], "to": slot["to"],
            "change": "set",
            "value": slot["value"] or (f"{level:+d}" if level else ""),
            "reasonEvent": BRIDGE_KEY,
        })

    lang = language if language in _STRINGS else "en"
    memory = {
        "entities": entities,
        "events": [{
            "key": BRIDGE_KEY,
            "title": _s(lang, "bridge"),
            "summary": _s(lang, "summary"),
            "importance": "major",
            "participants": [PLAYER] + picked,
            "disclosure": "known",
        }],
        "relations": relations,
    }
    return {
        "turn": 0,
        "prose": "",
        "action": "",
        "choices": [],
        "events": [],
        "gains": [],
        "legacy": {"fromRunId": source_run_id, "at": time.time()},
        "memory": memory,
    }


# ── what the next narrator is told (§9 step 5) ───────────────────────────


def narrator_summary(index: dict[str, Any], language: str = "en") -> dict[str, Any] | None:
    """The allowed source summary — names and one-liners, never the old graph.

    Returns ``None`` for a life with no inheritance, so the common case costs
    nothing. Deliberately absent: the ancestor's run id, its events, anything
    the player did not choose to carry.
    """
    inherited = [
        {"id": eid, "kind": ent["kind"], "name": ent["name"],
         "summary": ent["summary"]}
        for eid, ent in index["entities"].items()
        if isinstance(ent.get("inheritsFrom"), dict)
    ]
    if not inherited:
        return None
    lang = language if language in _STRINGS else "en"
    return {
        "note": _s(lang, "summary"),
        "from": _s(lang, "from"),
        "entities": sorted(inherited, key=lambda e: e["id"]),
    }
