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

#: The five generic entity kinds. A world's own vocabulary goes in names and
#: aliases, not in new kinds the recall rules cannot reason about — so an entity
#: whose declared kind is outside this set is not rejected but bucketed as the
#: generic ``object`` (see ``sanitize_memory``), keeping the memory while every
#: consumer still only ever sees this closed set. ``thread`` is never a coercion
#: target: it is a separate namespace with its own effects.
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
                # Provenance from a legacy bridge (design §9). Only the app's
                # turn-0 bridge record can carry it — the narrator's tool
                # schema closes the entity property list — so its presence in
                # a rebuilt index is itself evidence of a real bridge.
                if isinstance(ent.get("inheritsFrom"), dict):
                    entities[eid]["inheritsFrom"] = dict(ent["inheritsFrom"])
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


def sanitize_memory(
    memory: dict[str, Any], index: dict[str, Any], *, turn: int
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Salvage a ``memory`` block instead of rejecting it whole (design §5.3).

    The block is enrichment, not the story, so a single bad reference must never
    cost the real memory around it. Returns a CLEAN block carrying only the parts
    that pass, plus ``dropped`` — one entry per thing removed, each naming the
    exact field path and a narrator-facing ``detail`` — so the caller commits
    what survived and warns about the rest. Granularity, in check order:

    * an entity with a malformed id, a duplicate in-block id, or a kind that
      conflicts with a known one is dropped; an unrecognized kind is KEPT and
      bucketed as the generic ``object`` (never ``thread``); the survivors
      become resolvable references;
    * a structurally broken event (malformed/duplicate/replayed key, missing
      title or summary, unknown disclosure) is dropped whole — nothing anchors
      it — while an otherwise-good event is KEPT and loses only the individual
      references that do not resolve (an unknown participant, a non-place
      ``place``, an unknown importance, a dangling echo/corrects);
    * a THREAD is its own namespace, not an entity: ``opened`` DECLARES the
      thread (opening one is what creates it, so it never needs a prior entity),
      and only ``advanced``/``resolved`` on a thread never opened is dropped;
    * a relation is a single edge, so a bad endpoint/type/change/reasonEvent
      drops that one relation and never the events.

    Nothing is auto-invented (an unknown participant is dropped, not created) and
    nothing is back-filled from prose; a block whose parts all fail returns an
    empty clean block, which the caller records as no memory.
    """
    dropped: list[dict[str, str]] = []

    def drop(field: str, expected: str, detail: str) -> None:
        dropped.append({"field": field, "expected": expected, "detail": detail})

    # -- entities: keep the well-formed, non-conflicting ones -----------------
    declared: dict[str, str] = {}  # id -> kind, from the KEPT entities of this block
    kept_entities: list[dict[str, Any]] = []
    for i, ent in enumerate(memory.get("entities") or []):
        path = f"memory.entities[{i}]"
        eid = str(ent.get("id") or "")
        kind = str(ent.get("kind") or "")
        if not _id_ok(eid):
            drop(f"{path}.id", "a non-empty id without ':' or spaces",
                 f"Dropped a malformed entity id at {path}.")
            continue
        if kind not in KINDS:
            # Fail-soft: a narrator-invented kind (e.g. "concept") must not cost
            # the whole entity. Adopt the established kind when this id is already
            # known (a re-mention with a stray label just refreshes it); otherwise
            # bucket it as the neutral generic "object" — never "thread", which is
            # a separate namespace with its own effects. Downstream code and the
            # recall rules therefore still only ever see the closed KINDS set.
            prior = index["entities"].get(eid)
            coerced = prior["kind"] if prior is not None else "object"
            drop(f"{path}.kind", f"one of {', '.join(KINDS)}",
                 f"Kept entity {eid!r} but treated unknown kind {kind!r} as {coerced!r}.")
            kind = coerced
        if eid in declared:
            drop(f"{path}.id", f"declared twice this turn: {eid}",
                 f"Dropped the duplicate declaration of {eid!r}; the first was kept.")
            continue
        known = index["entities"].get(eid)
        if known is not None and known["kind"] != kind:
            drop(f"{path}.kind",
                 f"{eid} is already a {known['kind']}; a kind never changes without a merge",
                 f"Dropped entity {eid!r}: it is already a {known['kind']}, and a kind never "
                 "changes without an explicit merge.")
            continue
        declared[eid] = kind
        kept_entities.append({**ent, "kind": kind})

    def resolve(ref: str) -> str:
        """The kind of a resolvable entity reference, or '' if unknown."""
        if ref == PLAYER:
            return "character"
        if ref in declared:
            return declared[ref]
        known = index["entities"].get(ref)
        return known["kind"] if known is not None else ""

    known_threads = index.get("threads") or {}
    opened_threads: set[str] = set()  # threads opened earlier in THIS block

    # -- events: drop the unusable whole; salvage every event that can stand ---
    kept_keys: set[str] = set()
    kept_events: list[dict[str, Any]] = []
    for i, ev in enumerate(memory.get("events") or []):
        path = f"memory.events[{i}]"
        key = str(ev.get("key") or "")
        if not _id_ok(key):
            drop(f"{path}.key", "a non-empty key without ':' or spaces",
                 f"Dropped the event at {path}: its key is malformed, so nothing can anchor it.")
            continue
        if key in kept_keys:
            drop(f"{path}.key", f"used twice this turn: {key}",
                 f"Dropped the event at {path}: key {key!r} was already used this turn.")
            continue
        if event_id(turn, key) in index["events"]:
            # A replayed key for a turn that already recorded it — events are
            # append-only, the one collision idempotence does not absorb upstream.
            drop(f"{path}.key", f"already recorded for turn {turn}",
                 f"Dropped the event at {path}: {key!r} is already recorded for this turn.")
            continue
        if not str(ev.get("title") or "").strip():
            drop(f"{path}.title", "a short title",
                 f"Dropped the event at {path}: an event needs a title.")
            continue
        if not str(ev.get("summary") or "").strip():
            drop(f"{path}.summary", "a one-line summary",
                 f"Dropped the event at {path}: an event needs a one-line summary.")
            continue
        if str(ev.get("disclosure") or "") not in DISCLOSURES:
            drop(f"{path}.disclosure", f"one of {', '.join(DISCLOSURES)}",
                 f"Dropped the event at {path}: "
                 f"{ev.get('disclosure')!r} is not a known disclosure.")
            continue

        clean_ev = dict(ev)

        importance = ev.get("importance")
        if importance is not None and importance not in IMPORTANCE:
            clean_ev.pop("importance", None)
            drop(f"{path}.importance", f"one of {', '.join(IMPORTANCE)}",
                 f"Kept the event at {path} but dropped its unknown importance {importance!r}.")

        good_parts: list[Any] = []
        for j, part in enumerate(ev.get("participants") or []):
            if resolve(str(part)):
                good_parts.append(part)
            else:
                drop(f"{path}.participants[{j}]",
                     f"a known entity or one declared this turn, got {part!r}",
                     f"Kept the event at {path} but dropped its unknown participant "
                     f"{str(part)!r}; re-declare that entity to record it.")
        if "participants" in clean_ev:
            clean_ev["participants"] = good_parts

        place = str(ev.get("place") or "")
        if place:
            pkind = resolve(place)
            if pkind != "place":
                clean_ev.pop("place", None)
                reason = (f"{place} is a {pkind}, not a place" if pkind
                          else f"a known place, got {place!r}")
                drop(f"{path}.place", reason,
                     f"Kept the event at {path} but dropped its place ({reason}).")

        good_threads: list[Any] = []
        for j, th in enumerate(ev.get("threads") or []):
            tid = str(th.get("id") or "")
            effect = str(th.get("effect") or "")
            tpath = f"{path}.threads[{j}]"
            if not _id_ok(tid):
                drop(f"{tpath}.id", "a non-empty id without ':' or spaces",
                     f"Kept the event at {path} but dropped a malformed thread id.")
                continue
            if effect not in THREAD_EFFECTS:
                drop(f"{tpath}.effect", f"one of {', '.join(THREAD_EFFECTS)}",
                     f"Kept the event at {path} but dropped thread {tid!r}: unknown effect "
                     f"{effect!r}.")
                continue
            if effect == "opened":
                # Opening a thread is what creates it; it needs no prior existence.
                opened_threads.add(tid)
                good_threads.append(th)
            elif tid in known_threads or tid in opened_threads:
                good_threads.append(th)
            else:
                drop(f"{tpath}.id", f"a thread opened before or this turn, got {tid!r}",
                     f"Kept the event at {path} but dropped thread {tid!r}: it was never "
                     "opened. Open it with effect 'opened' before advancing or resolving it.")
        if "threads" in clean_ev:
            clean_ev["threads"] = good_threads

        good_echoes: list[Any] = []
        for j, target in enumerate(ev.get("echoes") or []):
            if str(target) in index["events"]:
                good_echoes.append(target)
            else:
                drop(f"{path}.echoes[{j}]",
                     "the canonical id of an event that exists in this life "
                     f"(like event:3:some-key), got {target!r}",
                     f"Kept the event at {path} but dropped an echo to {str(target)!r}, which "
                     "names no event in this life.")
        if "echoes" in clean_ev:
            clean_ev["echoes"] = good_echoes

        corrects = str(ev.get("corrects") or "")
        if corrects and corrects not in index["events"]:
            clean_ev.pop("corrects", None)
            drop(f"{path}.corrects",
                 f"the canonical id of an event that exists in this life, got {corrects!r}",
                 f"Kept the event at {path} but dropped a correction of {corrects!r}, which "
                 "names no event in this life.")

        kept_keys.add(key)
        kept_events.append(clean_ev)

    # -- relations: a single bad edge drops only itself -----------------------
    kept_relations: list[dict[str, Any]] = []
    for i, rel in enumerate(memory.get("relations") or []):
        path = f"memory.relations[{i}]"
        bad_end = next(
            (end for end in ("from", "to") if not resolve(str(rel.get(end) or ""))), None
        )
        if bad_end is not None:
            ref = str(rel.get(bad_end) or "")
            drop(f"{path}.{bad_end}",
                 f"a known entity or one declared this turn, got {ref!r}",
                 f"Dropped the relation at {path}: its {bad_end} {ref!r} does not resolve.")
            continue
        if not str(rel.get("type") or "").strip():
            drop(f"{path}.type", "the relation's name, in the world's own word",
                 f"Dropped the relation at {path}: it has no type.")
            continue
        if str(rel.get("change") or "") not in RELATION_CHANGES:
            drop(f"{path}.change", f"one of {', '.join(RELATION_CHANGES)}",
                 f"Dropped the relation at {path}: {rel.get('change')!r} is not a known change.")
            continue
        reason = str(rel.get("reasonEvent") or "")
        if reason and reason not in kept_keys and reason not in index["events"]:
            drop(f"{path}.reasonEvent",
                 "an event key declared this turn, or the canonical id of an existing event, "
                 f"got {reason!r}",
                 f"Dropped the relation at {path}: its reasonEvent {reason!r} names no event "
                 "kept this turn or in this life.")
            continue
        kept_relations.append(rel)

    clean: dict[str, Any] = {}
    if kept_entities:
        clean["entities"] = kept_entities
    if kept_events:
        clean["events"] = kept_events
    if kept_relations:
        clean["relations"] = kept_relations
    return clean, dropped


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


# ── the life star map — one sparse payload, three lenses (design §8.3) ───


def star_payload(
    index: dict[str, Any],
    keepsakes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The sparse, layout-agnostic subgraph all three views render.

    One payload, three lenses: 时间星座 / 关系轨道 / 纪念地图 are LAYOUTS over
    this data, never three queries — switching views must not refetch or change
    what is visible (§8.3.1, §12.4).

    Selection (dense storage, sparse presentation, §8.3): major events, events
    that echo or were echoed, events a keepsake cites, events touching an open
    thread — plus the entities directly involved in any included event. Nothing
    else ships.

    Disclosure is enforced HERE, server-side (§12.3): only ``known`` events may
    enter the star map (§5.4). A hidden or foreshadowed event is absent from the
    payload, so no client filter can leak it.
    """
    keepsakes = keepsakes or []
    events = index["events"]

    cited: set[str] = set()
    for kp in keepsakes:
        cited.update(str(c) for c in kp.get("cites") or [])

    echo_sources: set[str] = set(index["echoedAt"])
    open_threads = {
        tid for tid, rec in index["threads"].items()
        if rec["opened"] and not rec["resolved"]
    }

    picked_events: dict[str, dict[str, Any]] = {}
    for cid, ev in events.items():
        if ev["disclosure"] != "known":
            continue
        keep = (
            ev["importance"] == "major"
            or ev["echoes"]
            or cid in echo_sources
            or cid in cited
            or any(th["id"] in open_threads for th in ev["threads"])
        )
        if keep:
            picked_events[cid] = ev

    # Entities ride only on the events that carried them in.
    picked_entities: set[str] = set()
    for ev in picked_events.values():
        picked_entities.update(ev["participants"])
        if ev["place"]:
            picked_entities.add(ev["place"])
        picked_entities.update(th["id"] for th in ev["threads"])
    for kp in keepsakes:
        picked_entities.update(str(e) for e in kp.get("entities") or [])

    nodes: list[dict[str, Any]] = []
    for cid in sorted(picked_events, key=lambda c: (picked_events[c]["turn"], c)):
        ev = picked_events[cid]
        nodes.append({
            "id": cid, "kind": "event", "turn": ev["turn"],
            "title": ev["title"], "summary": ev["summary"],
            "importance": ev["importance"], "action": ev["action"],
        })
    for eid in sorted(picked_entities - {PLAYER}):
        ent = index["entities"].get(eid)
        if ent is None:
            continue
        nodes.append({
            "id": eid, "kind": ent["kind"], "name": ent["name"],
            "aliases": ent["aliases"], "summary": ent["summary"],
            "open": eid in open_threads if ent["kind"] == "thread" else None,
        })

    edges: list[dict[str, Any]] = []
    for cid, ev in sorted(picked_events.items(), key=lambda kv: (kv[1]["turn"], kv[0])):
        for p in ev["participants"]:
            if p in picked_entities and p != PLAYER:
                edges.append({"from": p, "type": "participated_in", "to": cid})
        if ev["place"] and ev["place"] in picked_entities:
            edges.append({"from": cid, "type": "occurred_at", "to": ev["place"]})
        for th in ev["threads"]:
            if th["id"] in picked_entities:
                edges.append({"from": cid, "type": th["effect"], "to": th["id"]})
        for target in ev["echoes"]:
            if target in picked_events:
                edges.append({"from": cid, "type": "echoes", "to": target})

    projection = project_relations(index)
    relations = [
        {"from": slot["from"], "type": slot["type"], "to": slot["to"],
         "level": slot["level"], "value": slot["value"],
         # The evidence trail (§4.3): the current reading must be able to open
         # into the events that produced it. Only sources the player may see.
         "sources": [c["reasonEvent"] for c in slot["changes"]
                     if c["reasonEvent"] in picked_events]}
        for slot in projection.values()
        if slot["active"]
        and slot["from"] in (picked_entities | {PLAYER})
        and slot["to"] in (picked_entities | {PLAYER})
    ]

    return {"nodes": nodes, "edges": edges, "relations": relations}



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
    turn = int(last.get("turn") or 0)
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
                # The answering event's own canonical id, so "collect this echo"
                # can cite the WHOLE path (§8.2) rather than only its source.
                "currentId": event_id(turn, str(ev.get("key") or "")),
                "title": str(ev.get("title") or ""),
                "summary": str(ev.get("summary") or ""),
            })
    return out
