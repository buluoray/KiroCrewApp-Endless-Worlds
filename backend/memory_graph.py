"""The world's memory — an event-centred fact graph under the story.

Design: ``MEMORY_GRAPH_DESIGN.md``. This module is the pure core of Phase 0 and
Phase 1: schema, semantic validation, index rebuild, relation projection, recall
candidates and the player-facing echo markers. It holds no I/O and no store — a
caller hands it chronicle entries and gets data back, which is what makes every
guarantee here testable without a gateway.

The load-bearing decisions, stated once:

* **The chronicle is the canonical source.** A turn's ``memory`` delta rides in
  the same chronicle line as its prose, so the two commit or fail together.
  Everything else this module computes — the entity index, the relation
  projection, the echo record — is derived from those lines and can be thrown
  away and rebuilt at any time. There is no second log to drift.
* **Only structured declarations become facts.** Nothing is ever extracted from
  prose. A turn without a ``memory`` block simply contributed no facts.
* **Events are append-only.** A wrong event is answered by a new event carrying
  ``corrects``, never by rewriting history.
* **An echo exists only when declared.** A new event that answers an old one
  names it in ``echoes``; prose that merely reminisces creates no edge and no
  player marker. That is what makes every marker traceable to a real turn.
"""

from __future__ import annotations

from typing import Any

# ── vocabulary (design §4.1, §4.2, §5.4) ────────────────────────────────

#: The five generic entity kinds. Deliberately closed: a world's own vocabulary
#: goes in names and aliases, never in new kinds the recall rules cannot reason
#: about.
KINDS = ("character", "place", "group", "object", "thread")

#: Who may see an event. ``hidden`` exists for world continuity only and must
#: never reach a player API, the star map, or a story card.
DISCLOSURES = ("known", "rumoured", "foreshadowed", "hidden")

IMPORTANCE = ("minor", "notable", "major")
DEFAULT_IMPORTANCE = "notable"

#: What an event may do to a thread.
THREAD_EFFECTS = ("opened", "advanced", "resolved")

#: How an event changes a relation. The relation *type* (trust, debt, fealty…)
#: is the world's own word and is a free string; the change verb is closed so
#: the projection stays computable.
RELATION_CHANGES = ("increase", "decrease", "set", "cleared")

#: The player is an entity every life has without declaring it.
PLAYER = "player"

#: A just-echoed event must rest before it can be recalled again (design §7.2).
ECHO_COOLDOWN_TURNS = 3

#: Candidates are memories, not news: an event this recent is still in the
#: narrator's recent-turns window and does not need recalling.
MIN_CANDIDATE_AGE_TURNS = 2

#: How many recall candidates one read returns, at most (design §7.1).
MAX_CANDIDATES = 6

#: An important event untouched for this many turns counts as dormant.
DORMANT_AFTER_TURNS = 8


class MemoryRejected(ValueError):
    """A ``memory`` block that must not be committed, naming the exact field.

    Carries a precise path (``memory.events[0].echoes[1]``) so the narrator can
    fix the one thing that was wrong and retry, per design §5.3.
    """

    def __init__(self, field: str, expected: str) -> None:
        super().__init__(f"{field}: {expected}")
        self.field = field
        self.expected = expected


def event_id(turn: int, key: str) -> str:
    """The canonical, run-scoped name of an event: ``event:12:saved-elin``.

    Minted by the server from ``(turn, key)`` — never taken from the narrator —
    which is why a key only needs to be unique within its own turn.
    """
    return f"event:{int(turn)}:{key}"


# ── the index — derived, disposable, rebuildable (design §6.1) ──────────


def build_index(chronicle: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything the graph knows, rebuilt from the canonical turn records.

    Deterministic by construction: entries are walked in chronicle order and
    every collection preserves that order, so two rebuilds of the same chronicle
    are equal — the Phase 0 completion bar ("禁用所有索引后仍可从回合记录重建相同图").

    Shape:
      ``entities``  id → {kind, name, aliases, summary, firstTurn}
      ``events``    canonical id → the declared event + {id, turn, action}
      ``threads``   thread id → {opened, resolved, lastTouched} (turn numbers)
      ``relations`` ordered change records, each with its source event
      ``echoedAt``  source event id → [turns that echoed it]
    """
    entities: dict[str, dict[str, Any]] = {
        PLAYER: {"kind": "character", "name": PLAYER, "aliases": [], "summary": "",
                 "firstTurn": 0},
    }
    events: dict[str, dict[str, Any]] = {}
    threads: dict[str, dict[str, Any]] = {}
    relations: list[dict[str, Any]] = []
    echoed_at: dict[str, list[int]] = {}

    for entry in chronicle:
        memory = entry.get("memory")
        if not isinstance(memory, dict):
            continue
        turn = int(entry.get("turn") or 0)
        action = str(entry.get("action") or "")

        for ent in memory.get("entities") or []:
            eid = str(ent.get("id") or "")
            known = entities.get(eid)
            if known is None:
                entities[eid] = {
                    "kind": str(ent.get("kind") or ""),
                    "name": str(ent.get("name") or eid),
                    "aliases": [str(a) for a in ent.get("aliases") or []],
                    "summary": str(ent.get("summary") or ""),
                    "firstTurn": turn,
                }
            else:
                # Enrichment only: aliases accumulate, name and summary may be
                # refreshed. The kind never changes here — validation refused
                # any redeclaration that tried (design §5.3).
                for alias in ent.get("aliases") or []:
                    if str(alias) not in known["aliases"]:
                        known["aliases"].append(str(alias))
                if ent.get("name"):
                    known["name"] = str(ent["name"])
                if ent.get("summary"):
                    known["summary"] = str(ent["summary"])

        for ev in memory.get("events") or []:
            cid = event_id(turn, str(ev.get("key") or ""))
            events[cid] = {
                "id": cid,
                "turn": turn,
                "key": str(ev.get("key") or ""),
                "title": str(ev.get("title") or ""),
                "summary": str(ev.get("summary") or ""),
                "importance": str(ev.get("importance") or DEFAULT_IMPORTANCE),
                "participants": [str(p) for p in ev.get("participants") or []],
                "place": str(ev.get("place") or ""),
                "threads": [
                    {"id": str(th.get("id") or ""), "effect": str(th.get("effect") or "")}
                    for th in ev.get("threads") or []
                ],
                "echoes": [str(e) for e in ev.get("echoes") or []],
                "corrects": str(ev.get("corrects") or ""),
                "disclosure": str(ev.get("disclosure") or ""),
                "action": action,
            }
            for th in ev.get("threads") or []:
                tid = str(th.get("id") or "")
                rec = threads.setdefault(
                    tid, {"opened": 0, "resolved": 0, "lastTouched": 0}
                )
                effect = str(th.get("effect") or "")
                if effect == "opened" and not rec["opened"]:
                    rec["opened"] = turn
                if effect == "resolved":
                    rec["resolved"] = turn
                rec["lastTouched"] = turn
            for target in ev.get("echoes") or []:
                echoed_at.setdefault(str(target), []).append(turn)

        for rel in memory.get("relations") or []:
            reason = str(rel.get("reasonEvent") or "")
            # A this-turn key resolves to its canonical id; a canonical id is
            # kept as-is. Validation guaranteed one of the two holds.
            if reason and not reason.startswith("event:"):
                reason = event_id(turn, reason)
            relations.append({
                "turn": turn,
                "from": str(rel.get("from") or ""),
                "type": str(rel.get("type") or ""),
                "to": str(rel.get("to") or ""),
                "change": str(rel.get("change") or ""),
                "value": str(rel.get("value") or ""),
                "reasonEvent": reason,
            })

    return {
        "entities": entities,
        "events": events,
        "threads": threads,
        "relations": relations,
        "echoedAt": echoed_at,
    }


def project_relations(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The current relation state, computed from every change in order.

    History is never overwritten (design §4.3): each ``(from, type, to)`` keeps
    its full change list with source events, and the current reading is folded
    from them. ``set`` establishes a value, ``increase``/``decrease`` move a
    level, ``cleared`` ends the relation. Re-running this over the same index
    must produce the same result — a test pins that.
    """
    out: dict[str, dict[str, Any]] = {}
    for rec in index["relations"]:
        key = f"{rec['from']}\u241f{rec['type']}\u241f{rec['to']}"
        slot = out.setdefault(
            key,
            {"from": rec["from"], "type": rec["type"], "to": rec["to"],
             "level": 0, "value": "", "active": True, "changes": []},
        )
        slot["changes"].append(
            {"turn": rec["turn"], "change": rec["change"],
             "value": rec["value"], "reasonEvent": rec["reasonEvent"]}
        )
        change = rec["change"]
        if change == "increase":
            slot["level"] += 1
            slot["active"] = True
        elif change == "decrease":
            slot["level"] -= 1
            slot["active"] = True
        elif change == "set":
            slot["value"] = rec["value"]
            slot["active"] = True
        elif change == "cleared":
            slot["level"] = 0
            slot["value"] = ""
            slot["active"] = False
    return out


# ── validation (design §5.3) ────────────────────────────────────────────


def _id_ok(value: str) -> bool:
    """An entity id or event key: non-empty, no colon (the canonical-id
    separator), no whitespace. Unicode is welcome — a Chinese world may well
    name its people in Chinese."""
    return bool(value) and ":" not in value and not any(c.isspace() for c in value)


def validate_memory(memory: dict[str, Any], index: dict[str, Any], *, turn: int) -> None:
    """Refuse a ``memory`` block that must not become facts, or return quietly.

    Validates the WHOLE block before anything is committed: a memory that fails
    here fails the entire tool call, so there is never a half-written turn
    (design §5.3 "先通过校验，再提交任何内容"). Every refusal names the exact
    field path so the narrator can correct one thing and retry.

    Semantic rules, in the order they are checked:
    * an entity id must be well-formed and not redeclare a known id with a
      different kind (no evidence-free type changes);
    * every reference (participants, place, thread ids, relation endpoints)
      must resolve to the implicit ``player``, a previously known entity, or an
      entity declared in this very block — unknown references are refused, not
      auto-created;
    * event keys are unique within the turn and must not collide with an
      already-recorded event of this turn;
    * an echo target must be the canonical id of an event that exists in THIS
      life — which is also what makes a cross-life reference impossible, since
      another run's ids simply do not resolve here;
    * a correction target must exist, like an echo;
    * a relation's ``reasonEvent`` is either a key declared in this block or a
      canonical id of an existing event.
    """
    declared: dict[str, str] = {}  # id -> kind, from this block
    entities = memory.get("entities") or []
    for i, ent in enumerate(entities):
        path = f"memory.entities[{i}]"
        eid = str(ent.get("id") or "")
        if not _id_ok(eid):
            raise MemoryRejected(f"{path}.id", "a non-empty id without ':' or spaces")
        kind = str(ent.get("kind") or "")
        if kind not in KINDS:
            raise MemoryRejected(f"{path}.kind", f"one of {', '.join(KINDS)}")
        if eid in declared:
            raise MemoryRejected(f"{path}.id", f"declared twice this turn: {eid}")
        known = index["entities"].get(eid)
        if known is not None and known["kind"] != kind:
            raise MemoryRejected(
                f"{path}.kind",
                f"{eid} is already a {known['kind']}; a kind never changes "
                "without an explicit merge",
            )
        declared[eid] = kind

    def resolve(ref: str) -> str:
        """The kind of a resolvable entity reference, or '' if unknown."""
        if ref == PLAYER:
            return "character"
        if ref in declared:
            return declared[ref]
        known = index["entities"].get(ref)
        return known["kind"] if known is not None else ""

    keys_this_turn: set[str] = set()
    events = memory.get("events") or []
    for i, ev in enumerate(events):
        path = f"memory.events[{i}]"
        key = str(ev.get("key") or "")
        if not _id_ok(key):
            raise MemoryRejected(f"{path}.key", "a non-empty key without ':' or spaces")
        if key in keys_this_turn:
            raise MemoryRejected(f"{path}.key", f"used twice this turn: {key}")
        keys_this_turn.add(key)
        if event_id(turn, key) in index["events"]:
            # A replayed key for a turn that already recorded it — events are
            # append-only, and this is the one collision idempotence does not
            # already absorb upstream.
            raise MemoryRejected(f"{path}.key", f"already recorded for turn {turn}")
        if not str(ev.get("title") or "").strip():
            raise MemoryRejected(f"{path}.title", "a short title")
        if not str(ev.get("summary") or "").strip():
            raise MemoryRejected(f"{path}.summary", "a one-line summary")
        disclosure = str(ev.get("disclosure") or "")
        if disclosure not in DISCLOSURES:
            raise MemoryRejected(
                f"{path}.disclosure", f"one of {', '.join(DISCLOSURES)}"
            )
        importance = ev.get("importance")
        if importance is not None and importance not in IMPORTANCE:
            raise MemoryRejected(
                f"{path}.importance", f"one of {', '.join(IMPORTANCE)}"
            )
        for j, part in enumerate(ev.get("participants") or []):
            if not resolve(str(part)):
                raise MemoryRejected(
                    f"{path}.participants[{j}]",
                    f"a known entity or one declared this turn, got {part!r}",
                )
        place = str(ev.get("place") or "")
        if place:
            kind = resolve(place)
            if not kind:
                raise MemoryRejected(
                    f"{path}.place",
                    f"a known entity or one declared this turn, got {place!r}",
                )
            if kind != "place":
                raise MemoryRejected(f"{path}.place", f"{place} is a {kind}, not a place")
        for j, th in enumerate(ev.get("threads") or []):
            tid = str(th.get("id") or "")
            kind = resolve(tid)
            if not kind:
                raise MemoryRejected(
                    f"{path}.threads[{j}].id",
                    f"a known entity or one declared this turn, got {tid!r}",
                )
            if kind != "thread":
                raise MemoryRejected(
                    f"{path}.threads[{j}].id", f"{tid} is a {kind}, not a thread"
                )
            if str(th.get("effect") or "") not in THREAD_EFFECTS:
                raise MemoryRejected(
                    f"{path}.threads[{j}].effect",
                    f"one of {', '.join(THREAD_EFFECTS)}",
                )
        for j, target in enumerate(ev.get("echoes") or []):
            if str(target) not in index["events"]:
                raise MemoryRejected(
                    f"{path}.echoes[{j}]",
                    "the canonical id of an event that exists in this life "
                    f"(like event:3:some-key), got {target!r}",
                )
        corrects = str(ev.get("corrects") or "")
        if corrects and corrects not in index["events"]:
            raise MemoryRejected(
                f"{path}.corrects",
                f"the canonical id of an event that exists in this life, got {corrects!r}",
            )

    for i, rel in enumerate(memory.get("relations") or []):
        path = f"memory.relations[{i}]"
        for end in ("from", "to"):
            ref = str(rel.get(end) or "")
            if not resolve(ref):
                raise MemoryRejected(
                    f"{path}.{end}",
                    f"a known entity or one declared this turn, got {ref!r}",
                )
        if not str(rel.get("type") or "").strip():
            raise MemoryRejected(f"{path}.type", "the relation's name, in the world's own word")
        if str(rel.get("change") or "") not in RELATION_CHANGES:
            raise MemoryRejected(
                f"{path}.change", f"one of {', '.join(RELATION_CHANGES)}"
            )
        reason = str(rel.get("reasonEvent") or "")
        if reason:
            in_block = reason in keys_this_turn
            in_history = reason in index["events"]
            if not in_block and not in_history:
                raise MemoryRejected(
                    f"{path}.reasonEvent",
                    "an event key declared this turn, or the canonical id of an "
                    f"existing event, got {reason!r}",
                )


# ── recall (design §7) ──────────────────────────────────────────────────


def recall_candidates(
    index: dict[str, Any],
    *,
    turn: int,
    action: str = "",
    limit: int = MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Up to ``limit`` old events worth the narrator's attention this turn.

    The system recalls; the narrator decides (design §7.1). Scoring is entirely
    deterministic — shared entities with the recent turns, mention in the
    player's own action text, open threads, dormant importance — and a cooldown
    keeps a just-echoed event from monopolising the story. Candidates go to the
    NARRATOR, so ``hidden`` events are eligible: continuity is exactly what
    hidden exists for. The player-facing filter lives in :func:`echo_markers`.
    """
    events = index["events"]
    if not events:
        return []

    # What "recent" means: entities touched by the last two turns' events.
    recent_entities: set[str] = set()
    for ev in events.values():
        if ev["turn"] >= turn - 2:
            recent_entities.update(ev["participants"])
            if ev["place"]:
                recent_entities.add(ev["place"])
            recent_entities.update(th["id"] for th in ev["threads"])

    open_threads = {
        tid for tid, rec in index["threads"].items()
        if rec["opened"] and not rec["resolved"]
    }
    action_lower = action.lower()

    def last_echo(cid: str) -> int:
        turns = index["echoedAt"].get(cid) or []
        return max(turns) if turns else 0

    scored: list[tuple[int, int, str, dict[str, Any], list[str]]] = []
    for cid, ev in events.items():
        age = turn - ev["turn"]
        if age < MIN_CANDIDATE_AGE_TURNS:
            continue  # still in the recent-turns window; not a memory yet
        if last_echo(cid) >= turn - ECHO_COOLDOWN_TURNS:
            continue  # cooling down — just-echoed events must rest (§7.2)

        reasons: list[str] = []
        score = 0
        touched = set(ev["participants"]) | {th["id"] for th in ev["threads"]}
        if ev["place"]:
            touched.add(ev["place"])

        shared = (touched & recent_entities) - {PLAYER}
        if shared:
            score += 3
            reasons.append("same-entity")
        if action_lower:
            names: list[str] = []
            for ref in touched:
                ent = index["entities"].get(ref)
                if ent:
                    names.append(ent["name"])
                    names.extend(ent["aliases"])
            if any(n and n.lower() in action_lower for n in names):
                score += 3
                reasons.append("action-mention")
        if touched & open_threads:
            score += 4
            reasons.append("open-thread")
        if age >= DORMANT_AFTER_TURNS and not last_echo(cid):
            if ev["importance"] == "major":
                score += 3
                reasons.append("dormant-important")
            elif ev["importance"] == "notable":
                score += 1
                reasons.append("dormant")

        if score > 0:
            # Older first among equals: the long-buried memory is the one the
            # narrator cannot supply from its own context.
            scored.append((score, ev["turn"], cid, ev, reasons))

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    picked = scored[:limit]

    # One two-hop surprise (§7.2 rule 6): an event that shares an entity with a
    # PICKED candidate but not with the recent turns — explainable, but not
    # obvious. Deterministic: the oldest qualifying event fills the last slot.
    if picked and len(picked) < limit:
        picked_ids = {cid for _, _, cid, _, _ in picked}
        picked_entities: set[str] = set()
        for _, _, _, ev, _ in picked:
            picked_entities.update(ev["participants"])
            if ev["place"]:
                picked_entities.add(ev["place"])
        picked_entities.discard(PLAYER)
        for cid, ev in sorted(events.items(), key=lambda kv: (kv[1]["turn"], kv[0])):
            if cid in picked_ids or turn - ev["turn"] < MIN_CANDIDATE_AGE_TURNS:
                continue
            if last_echo(cid) >= turn - ECHO_COOLDOWN_TURNS:
                continue
            touched = set(ev["participants"]) | {th["id"] for th in ev["threads"]}
            if ev["place"]:
                touched.add(ev["place"])
            touched.discard(PLAYER)
            if touched & picked_entities and not (touched & recent_entities):
                picked.append((1, ev["turn"], cid, ev, ["two-hop"]))
                break

    out: list[dict[str, Any]] = []
    for _, _, cid, ev, reasons in picked:
        out.append({
            "id": cid,
            "turn": ev["turn"],
            "title": ev["title"],
            "summary": ev["summary"],
            "entities": sorted(
                (set(ev["participants"]) | ({ev["place"]} if ev["place"] else set()))
                - {PLAYER}
            ),
            "threads": [th["id"] for th in ev["threads"]],
            "action": ev["action"],
            "reasons": reasons,
            "lastEchoedTurn": last_echo(cid),
        })
    return out


def event_neighbourhood(index: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    """The named events in full, with their directly involved entities resolved.

    The narrator's limited follow-up read (design §7.1): by id, a bounded
    neighbourhood, never the whole graph. Unknown ids are silently absent — the
    narrator asked about something this life does not remember.
    """
    out: list[dict[str, Any]] = []
    for cid in ids:
        ev = index["events"].get(str(cid))
        if ev is None:
            continue
        refs = set(ev["participants"]) | {th["id"] for th in ev["threads"]}
        if ev["place"]:
            refs.add(ev["place"])
        out.append({
            **ev,
            "involved": [
                {"id": r, **{k: v for k, v in index["entities"][r].items()
                             if k in ("kind", "name", "aliases")}}
                for r in sorted(refs) if r in index["entities"]
            ],
        })
    return out


# ── the player-facing echo markers (design §7.3, §8.1) ──────────────────


def echo_markers(chronicle: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The traceable "an old thing came back" markers for the LAST turn.

    An echo exists only where the last turn's structured declaration names an
    older event — prose alone never produces one (§7.3). Both ends must be
    ``known`` to the player: an echo of something only foreshadowed or hidden
    would be the UI explaining what the world has not yet revealed (§5.4).
    """
    if not chronicle:
        return []
    last = chronicle[-1]
    memory = last.get("memory")
    if not isinstance(memory, dict):
        return []
    index = build_index(chronicle[:-1])
    out: list[dict[str, Any]] = []
    for ev in memory.get("events") or []:
        if str(ev.get("disclosure") or "") != "known":
            continue
        for target in ev.get("echoes") or []:
            src = index["events"].get(str(target))
            if src is None or src["disclosure"] != "known":
                continue
            out.append({
                "sourceId": src["id"],
                "sourceTurn": src["turn"],
                "sourceTitle": src["title"],
                "sourceSummary": src["summary"],
                "sourceAction": src["action"],
                "title": str(ev.get("title") or ""),
                "summary": str(ev.get("summary") or ""),
            })
    return out
