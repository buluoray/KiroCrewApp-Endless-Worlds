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

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

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

#: An event the narrator wrote into the memory block without a recognizable
#: secrecy label is part of the story it just told. Secrecy is the thing that
#: must be legible — ``_DISCLOSURE_WORDS`` below catches every way a narrator
#: spells it — so an unreadable label falls back here rather than silently
#: hiding a memory the player lived through.
DEFAULT_DISCLOSURE = "known"

IMPORTANCE = ("minor", "notable", "major")
DEFAULT_IMPORTANCE = "notable"

#: What an event may do to a thread.
THREAD_EFFECTS = ("opened", "advanced", "resolved")

#: An unreadable effect still touched the thread; it just cannot claim to have
#: opened or closed it.
DEFAULT_THREAD_EFFECT = "advanced"

#: How an event changes a relation. The relation *type* (trust, debt, fealty…)
#: is the world's own word and is a free string; the change verb is closed so
#: the projection stays computable.
RELATION_CHANGES = ("increase", "decrease", "set", "cleared")

#: An unreadable change verb states the relation rather than moving it, which is
#: the one reading that cannot invent a direction the narrator did not write.
DEFAULT_RELATION_CHANGE = "set"

#: Every way a narrator spells a member of a closed vocabulary, mapped to the
#: canonical word. Substring-matched (design §5.3 repair), so "rumored",
#: "Rumours" and "widely rumoured" all land on ``rumoured``. This is what keeps
#: the vocabularies closed for every consumer WITHOUT costing the narrator a
#: memory over a synonym: repair first, fall back to the DEFAULT_* above.
_DISCLOSURE_WORDS: tuple[tuple[str, str], ...] = (
    ("foreshadow", "foreshadowed"), ("portent", "foreshadowed"),
    ("omen", "foreshadowed"), ("hint", "foreshadowed"), ("presage", "foreshadowed"),
    ("rumour", "rumoured"), ("rumor", "rumoured"), ("hearsay", "rumoured"),
    ("gossip", "rumoured"), ("whisper", "rumoured"),
    ("hidden", "hidden"), ("secret", "hidden"), ("conceal", "hidden"),
    ("private", "hidden"), ("unseen", "hidden"), ("unknown", "hidden"),
    ("undisclosed", "hidden"), ("covert", "hidden"),
    ("known", "known"), ("public", "known"), ("open", "known"),
    ("witness", "known"), ("seen", "known"), ("told", "known"),
)
_IMPORTANCE_WORDS: tuple[tuple[str, str], ...] = (
    ("major", "major"), ("critical", "major"), ("pivotal", "major"),
    ("huge", "major"), ("大", "major"),
    ("minor", "minor"), ("small", "minor"), ("trivial", "minor"),
    ("slight", "minor"), ("小", "minor"),
    ("notable", "notable"), ("normal", "notable"), ("medium", "notable"),
    ("moderate", "notable"), ("中", "notable"),
)
_THREAD_EFFECT_WORDS: tuple[tuple[str, str], ...] = (
    ("open", "opened"), ("start", "opened"), ("begin", "opened"),
    ("create", "opened"), ("new", "opened"),
    ("resolv", "resolved"), ("close", "resolved"), ("finish", "resolved"),
    ("complete", "resolved"), ("settle", "resolved"), ("ended", "resolved"),
    ("advance", "advanced"), ("progress", "advanced"), ("continue", "advanced"),
    ("deepen", "advanced"), ("touch", "advanced"),
)
_RELATION_CHANGE_WORDS: tuple[tuple[str, str], ...] = (
    ("increas", "increase"), ("rais", "increase"), ("rise", "increase"),
    ("grow", "increase"), ("gain", "increase"), ("improve", "increase"),
    ("strengthen", "increase"), ("deepen", "increase"), ("warm", "increase"),
    ("decreas", "decrease"), ("lower", "decrease"), ("fall", "decrease"),
    ("drop", "decrease"), ("lose", "decrease"), ("loss", "decrease"),
    ("weaken", "decrease"), ("worsen", "decrease"), ("cool", "decrease"),
    ("clear", "cleared"), ("sever", "cleared"), ("break", "cleared"),
    ("broke", "cleared"), ("remove", "cleared"), ("cut", "cleared"),
    ("set", "set"), ("establish", "set"), ("becom", "set"),
)

#: The player is an entity every life has without declaring it.
PLAYER = "player"

#: A character must be present in MORE than this share of a life's events to be
#: read as the one whose life it is (see :func:`life_centre`). Strictly more than
#: half is the whole point: at most one character can clear it, so the reading is
#: unique or absent, never a pick between rivals.
CENTRE_EVENT_SHARE = 0.5

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
    """The canonical, run-scoped name of an event: ``event-12-saved-elin``.

    Minted by the server from ``(turn, key)`` — never taken from the narrator —
    which is why a key only needs to be unique within its own turn.

    The shape is a plain slug on purpose. This id is the one internal identifier
    the narrator is SHOWN (in ``memoryCandidates``, and back in a turn's own
    ``echoes``), and a narrator writes in the shapes it is shown: while this read
    ``event:12:saved-elin``, the narrator mirrored the colon into its own entity
    ids (``character:lin-shuang``) and every one of them failed the id rule. So
    nothing the narrator can see carries a separator it must not use.
    """
    return f"event-{int(turn)}-{key}"


#: An id minted by :func:`event_id`, told apart from an entity id by its shape.
#: Used where a reference may be either an event key from this turn or a canonical
#: id from an earlier one.
_EVENT_ID = re.compile(r"^event-\d+-")


def is_event_id(value: str) -> bool:
    """Whether ``value`` has the shape :func:`event_id` mints."""
    return bool(_EVENT_ID.match(value))


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
                # The FIRST record of a thread opens it, whatever the effect says.
                # A narrator that advances a thread it never explicitly opened has
                # still told us the thread exists; leaving `opened` at 0 would keep
                # it out of every open-threads reading (recall, legacy, story cards)
                # and lose it silently.
                if not rec["opened"]:
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
            if reason and not is_event_id(reason):
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


# ── repair, then validate (design §5.3) ─────────────────────────────────


_WHITESPACE = re.compile(r"\s+")


def _id_ok(value: str) -> bool:
    """An entity id or event key: non-empty, no colon (the canonical-id
    separator), no whitespace. Unicode is welcome — a Chinese world may well
    name its people in Chinese."""
    return bool(value) and ":" not in value and not any(c.isspace() for c in value)


def repair_id(value: Any) -> str:
    """The usable id inside whatever the narrator wrote, or ``''``.

    A narrator writes in the shapes it is shown, and it used to be shown
    colon-namespaced canonical event ids — so it wrote ``character:lin-shuang``
    and ``group: darkflame court`` and the old validator dropped every one of
    them. :func:`event_id` no longer mints a colon anywhere, but the habit
    outlives the prompt: a colon here is a namespace the narrator added, and the
    id it namespaces is the last segment; whitespace is a slug that was never
    slugified. Repair both instead of losing the memory:

    >>> repair_id("character:lin-shuang")
    'lin-shuang'
    >>> repair_id("event:6:slept-through-collapse")
    'slept-through-collapse'
    >>> repair_id("  darkflame court ")
    'darkflame-court'

    Case is left alone on purpose: an id is an identity, and lowercasing one
    would stop a re-mention from matching the entity it re-mentions.
    """
    raw = str(value or "").strip()
    if ":" in raw:
        segments = [seg.strip() for seg in raw.split(":") if seg.strip()]
        raw = segments[-1] if segments else ""
    return _WHITESPACE.sub("-", raw).strip("-")


#: A kind word a narrator prefixed onto an id (``character-lin-shuang``) — the
#: same namespacing instinct as the colon, in a shape that is a legal slug and so
#: cannot be spotted by the id rule. Stripped only when what remains is an id the
#: graph already knows, since ``place-of-bones`` may well be an id in its own right.
_KIND_PREFIX = re.compile(
    r"^(?:character|place|group|object|thread|event|person|people|npc|faction|"
    r"item|location|region|concept)[-_]"
)


def _repair_ref(value: Any, is_known: Any) -> str:
    """``repair_id``, but preferring a reading the graph already knows.

    Stripping the namespace is the right default, yet ``fire:court`` may well be
    an id that was always spelled ``fire-court``. Every reading is tried and the
    first the graph already knows wins, so a repair reconnects a reference to the
    entity it meant instead of minting a near-duplicate beside it. A reading that
    resolves nothing is never preferred over the id as written.
    """
    raw = str(value or "").strip()
    candidates: list[str] = []
    for candidate in (repair_id(raw), _WHITESPACE.sub("-", raw.replace(":", "-")).strip("-")):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in list(candidates):
        stripped = _KIND_PREFIX.sub("", candidate, count=1)
        if stripped and stripped != candidate and stripped not in candidates:
            candidates.append(stripped)  # never candidates[0]: known-only, never fallback
    for candidate in candidates:
        if is_known(candidate):
            return candidate
    return candidates[0] if candidates else ""


def _repair_word(value: Any, words: tuple[tuple[str, str], ...], default: str) -> str:
    """The canonical member of a closed vocabulary a narrator's word means.

    Longest-hint-first substring matching, so "widely rumoured" resolves and a
    hint that is a substring of another word cannot steal the match. Returns
    ``default`` for a word carrying no recognizable hint.
    """
    text = str(value or "").strip().lower()
    if not text:
        return default
    best = ""
    chosen = default
    for hint, canonical in words:
        if hint in text and len(hint) > len(best):
            best, chosen = hint, canonical
    return chosen if best else default


def _lead(text: str, limit: int = 48) -> str:
    """A title-length lead cut from a longer line, at a clause boundary if there
    is one inside the budget. Used to give a titleless event the title its own
    summary already contains, rather than dropping the event over a missing
    field the narrator wrote the content for."""
    line = _WHITESPACE.sub(" ", str(text or "").strip())
    if len(line) <= limit:
        return line
    head = line[:limit]
    for sep in ("。", "！", "？", "；", "，", "、", ". ", ", ", "; ", " — ", " "):
        cut = head.rfind(sep)
        if cut >= limit // 3:
            return head[:cut].rstrip(" ,;—、，。") + "…"
    return head.rstrip() + "…"


def sanitize_memory(
    memory: dict[str, Any], index: dict[str, Any], *, turn: int
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """REPAIR a ``memory`` block, and drop only what cannot be repaired (§5.3).

    The block is enrichment, not the story, so a slip in it must never cost the
    real memory around it — and the slips a narrator actually makes are almost
    all spelling, not meaning. So the order here is repair first, drop last:

    * a **malformed id or reference** (a colon namespace, an unslugified space)
      is repaired, preferring the reading the graph already knows, so the
      declaration lands on the entity it meant. Only an id with nothing usable
      left is dropped;
    * a **closed vocabulary** (kind, disclosure, importance, thread effect,
      relation change) accepts the narrator's synonym and maps it to the
      canonical member; an unrecognizable word falls back to that vocabulary's
      documented default. Every consumer still sees only the closed set;
    * a **missing title or summary** is taken from whichever of the two the
      narrator did write. An event is dropped only when it has neither, because
      then there is genuinely nothing to record;
    * a **colliding event key** (used twice this turn, or already recorded for
      this turn) is suffixed rather than dropped — a key only needs to be unique
      inside its own turn, and both events happened;
    * a **thread advanced or resolved without ever being opened** is kept and
      opens on that first touch: the narrator told us the thread exists, which
      is what opening one means;
    * a **relation whose reasonEvent names nothing** keeps the relation and
      loses only the reason, since the reason was always optional.

    What is still DROPPED, because repairing it would mean inventing a fact:
    a reference to an entity that was never declared (participant, place,
    relation endpoint), an echo or correction naming an event that does not
    exist, a relation with no type, and anything whose id repairs to nothing.
    Nothing is ever back-filled from prose.

    Returns the CLEAN block (repairs applied) plus ``dropped`` — one entry per
    thing genuinely removed, each naming the exact field path — which the caller
    surfaces as a non-blocking warning. Repairs are logged, not warned: they cost
    the narrator nothing to know about and the id shapes it is shown are what
    provoked most of them.
    """
    dropped: list[dict[str, str]] = []

    def drop(field: str, expected: str, detail: str) -> None:
        dropped.append({"field": field, "expected": expected, "detail": detail})

    def repaired(field: str, detail: str) -> None:
        logger.info("memory repaired at %s: %s", field, detail)

    # -- entities: repair the id, adopt the established kind, merge re-declarations
    declared: dict[str, str] = {}  # id -> kind, from the KEPT entities of this block
    kept_entities: list[dict[str, Any]] = []
    at_id: dict[str, int] = {}  # id -> its slot in kept_entities, for merging
    for i, ent in enumerate(memory.get("entities") or []):
        path = f"memory.entities[{i}]"
        raw_id = str(ent.get("id") or "")
        # Always through the repair: a well-formed id can still be a namespaced one
        # ("character-lin-shuang"), which only the graph's own knowledge can spot.
        eid = _repair_ref(raw_id, lambda c: c in declared or c in index["entities"])
        if not eid:
            drop(f"{path}.id", "a non-empty id without ':' or spaces",
                 f"Dropped an entity at {path}: its id has nothing usable in it.")
            continue
        if eid != raw_id:
            repaired(f"{path}.id", f"read {raw_id!r} as {eid!r}")

        kind = str(ent.get("kind") or "")
        known = index["entities"].get(eid)
        established = declared.get(eid) or (known["kind"] if known is not None else "")
        if kind not in KINDS or (established and kind != established):
            # Fail-soft: a narrator-invented kind ("concept") or a stray label on a
            # known entity must not cost the entity. An id that already has a kind
            # keeps it — a kind never changes without an explicit merge — and a new
            # id is bucketed as the neutral generic "object", never "thread", which
            # is a separate namespace with its own effects. Downstream code and the
            # recall rules therefore still only ever see the closed KINDS set.
            coerced = established or "object"
            if kind != coerced:
                repaired(f"{path}.kind", f"read kind {kind!r} as {coerced!r} for {eid!r}")
            kind = coerced

        slot = at_id.get(eid)
        if slot is not None:
            # Declared twice in one block: the second declaration is enrichment, not
            # a collision — merge it forward instead of throwing the writing away.
            prior = kept_entities[slot]
            aliases = list(prior.get("aliases") or [])
            for alias in ent.get("aliases") or []:
                if str(alias) not in aliases:
                    aliases.append(str(alias))
            merged = {**prior, **{k: v for k, v in ent.items() if v}, "id": eid,
                      "kind": prior["kind"]}
            if aliases:
                merged["aliases"] = aliases
            kept_entities[slot] = merged
            repaired(f"{path}.id", f"merged the second declaration of {eid!r}")
            continue

        declared[eid] = kind
        at_id[eid] = len(kept_entities)
        kept_entities.append({**ent, "id": eid, "kind": kind})

    def resolve(ref: str) -> str:
        """The kind of a resolvable entity reference, or '' if unknown."""
        if ref == PLAYER:
            return "character"
        if ref in declared:
            return declared[ref]
        known = index["entities"].get(ref)
        return known["kind"] if known is not None else ""

    def resolve_repaired(raw: Any, path: str, what: str) -> str:
        """A reference, repaired if it does not resolve as written."""
        ref = str(raw or "")
        if resolve(ref):
            return ref
        fixed = _repair_ref(ref, lambda c: bool(resolve(c)))
        if fixed and fixed != ref and resolve(fixed):
            repaired(path, f"read {what} {ref!r} as {fixed!r}")
            return fixed
        return ref

    known_threads = index.get("threads") or {}
    opened_threads: set[str] = set()  # threads this block declares or touches first

    #: A past event's own key → its canonical id, so a narrator that names an old
    #: event by bare key (the form it wrote) still reaches the event it means.
    by_key: dict[str, str] = {}
    for cid, rec in index["events"].items():
        by_key[str(rec.get("key") or "")] = cid

    def resolve_event(raw: Any) -> str:
        """The canonical id of an existing event, from a canonical id or a bare
        key, or '' if it names none."""
        ref = str(raw or "").strip()
        if not ref:
            return ""
        if ref in index["events"]:
            return ref
        return by_key.get(ref, "") or by_key.get(repair_id(ref), "")

    # -- events: repair what is fixable; drop only what has no content at all ---
    kept_keys: set[str] = set()
    renamed_keys: dict[str, str] = {}
    kept_events: list[dict[str, Any]] = []
    for i, ev in enumerate(memory.get("events") or []):
        path = f"memory.events[{i}]"

        # Title and summary hold each other up: either one can name the event.
        title = str(ev.get("title") or "").strip()
        summary = str(ev.get("summary") or "").strip()
        if not title and not summary:
            drop(f"{path}.title", "a short title",
                 f"Dropped the event at {path}: it has neither a title nor a summary, "
                 "so there is nothing to record.")
            continue
        if not title:
            title = _lead(summary)
            repaired(f"{path}.title", f"took the title {title!r} from the summary")
        if not summary:
            summary = title
            repaired(f"{path}.summary", "took the summary from the title")

        raw_key = str(ev.get("key") or "")
        key = raw_key if _id_ok(raw_key) else (repair_id(raw_key) or repair_id(title))
        if is_event_id(key):
            # The narrator wrote the CANONICAL id where a key belongs — mirroring
            # what it is shown again. The key is the tail; keeping the prefix would
            # mint `event-1-event-1-met-hui-ya`.
            key = _EVENT_ID.sub("", key, count=1)
        if not key:
            key = f"unnamed-{i + 1}"
        if key != raw_key:
            repaired(f"{path}.key", f"read {raw_key!r} as {key!r}")
        # A key only has to be unique inside its own turn, so a collision is
        # answered by a free neighbour rather than by losing the event.
        base, n = key, 2
        while key in kept_keys or event_id(turn, key) in index["events"]:
            key, n = f"{base}-{n}", n + 1
        if key != base:
            renamed_keys[base] = key
            repaired(f"{path}.key", f"{base!r} was taken this turn, recorded as {key!r}")

        clean_ev = dict(ev)
        clean_ev["key"] = key
        clean_ev["title"] = title
        clean_ev["summary"] = summary

        disclosure = str(ev.get("disclosure") or "")
        if disclosure not in DISCLOSURES:
            fixed = _repair_word(disclosure, _DISCLOSURE_WORDS, DEFAULT_DISCLOSURE)
            repaired(f"{path}.disclosure", f"read {disclosure!r} as {fixed!r}")
            disclosure = fixed
        clean_ev["disclosure"] = disclosure

        importance = ev.get("importance")
        if importance is not None and importance not in IMPORTANCE:
            fixed = _repair_word(importance, _IMPORTANCE_WORDS, DEFAULT_IMPORTANCE)
            repaired(f"{path}.importance", f"read {importance!r} as {fixed!r}")
            clean_ev["importance"] = fixed

        good_parts: list[Any] = []
        for j, part in enumerate(ev.get("participants") or []):
            ppath = f"{path}.participants[{j}]"
            ref = resolve_repaired(part, ppath, "participant")
            if resolve(ref):
                good_parts.append(ref)
            else:
                drop(ppath,
                     f"a known entity or one declared this turn, got {str(part)!r}",
                     f"Kept the event at {path} but dropped its unknown participant "
                     f"{str(part)!r}; re-declare that entity to record it.")
        if "participants" in clean_ev:
            clean_ev["participants"] = good_parts

        raw_place = str(ev.get("place") or "")
        if raw_place:
            place = resolve_repaired(raw_place, f"{path}.place", "place")
            pkind = resolve(place)
            if pkind == "place":
                clean_ev["place"] = place
            else:
                clean_ev.pop("place", None)
                reason = (f"{place} is a {pkind}, not a place" if pkind
                          else f"a known place, got {raw_place!r}")
                drop(f"{path}.place", reason,
                     f"Kept the event at {path} but dropped its place ({reason}).")

        good_threads: list[Any] = []
        for j, th in enumerate(ev.get("threads") or []):
            tpath = f"{path}.threads[{j}]"
            raw_tid = str(th.get("id") or "")
            tid = raw_tid
            if not _id_ok(tid):
                tid = _repair_ref(
                    raw_tid, lambda c: c in known_threads or c in opened_threads
                )
                if not tid:
                    drop(f"{tpath}.id", "a non-empty id without ':' or spaces",
                         f"Kept the event at {path} but dropped a thread whose id has "
                         "nothing usable in it.")
                    continue
                repaired(f"{tpath}.id", f"read {raw_tid!r} as {tid!r}")

            effect = str(th.get("effect") or "")
            if effect not in THREAD_EFFECTS:
                fixed = _repair_word(effect, _THREAD_EFFECT_WORDS, DEFAULT_THREAD_EFFECT)
                repaired(f"{tpath}.effect", f"read {effect!r} as {fixed!r}")
                effect = fixed
            if effect != "opened" and tid not in known_threads and tid not in opened_threads:
                # Naming a thread is what brings it into the graph; build_index opens
                # it on this first touch, so an "advanced" thread nobody opened is a
                # thread opening here, not an inconsistency to throw away.
                repaired(f"{tpath}.id", f"thread {tid!r} opens on this first mention")
            opened_threads.add(tid)
            good_threads.append({**th, "id": tid, "effect": effect})
        if "threads" in clean_ev:
            clean_ev["threads"] = good_threads

        good_echoes: list[Any] = []
        for j, target in enumerate(ev.get("echoes") or []):
            cid = resolve_event(target)
            if cid:
                if cid != str(target):
                    repaired(f"{path}.echoes[{j}]", f"read {str(target)!r} as {cid!r}")
                good_echoes.append(cid)
            else:
                drop(f"{path}.echoes[{j}]",
                     "the canonical id of an event that exists in this life "
                     f"(like event-3-some-key), got {target!r}",
                     f"Kept the event at {path} but dropped an echo to {str(target)!r}, which "
                     "names no event in this life.")
        if "echoes" in clean_ev:
            clean_ev["echoes"] = good_echoes

        raw_corrects = str(ev.get("corrects") or "")
        if raw_corrects:
            cid = resolve_event(raw_corrects)
            if cid:
                if cid != raw_corrects:
                    repaired(f"{path}.corrects", f"read {raw_corrects!r} as {cid!r}")
                clean_ev["corrects"] = cid
            else:
                clean_ev.pop("corrects", None)
                drop(f"{path}.corrects",
                     f"the canonical id of an event that exists in this life, got "
                     f"{raw_corrects!r}",
                     f"Kept the event at {path} but dropped a correction of "
                     f"{raw_corrects!r}, which names no event in this life.")

        kept_keys.add(key)
        kept_events.append(clean_ev)

    # -- relations: repair the verb and the reason; drop only an unnamed edge ---
    kept_relations: list[dict[str, Any]] = []
    for i, rel in enumerate(memory.get("relations") or []):
        path = f"memory.relations[{i}]"
        clean_rel = dict(rel)
        bad_end = None
        for end in ("from", "to"):
            ref = resolve_repaired(rel.get(end), f"{path}.{end}", end)
            if not resolve(ref):
                bad_end = end
                break
            clean_rel[end] = ref
        if bad_end is not None:
            ref = str(rel.get(bad_end) or "")
            drop(f"{path}.{bad_end}",
                 f"a known entity or one declared this turn, got {ref!r}",
                 f"Dropped the relation at {path}: its {bad_end} {ref!r} does not resolve.")
            continue
        if not str(rel.get("type") or "").strip():
            drop(f"{path}.type", "the relation's name, in the world's own word",
                 f"Dropped the relation at {path}: it has no type, so there is no edge "
                 "to record.")
            continue
        change = str(rel.get("change") or "")
        if change not in RELATION_CHANGES:
            fixed = _repair_word(change, _RELATION_CHANGE_WORDS, DEFAULT_RELATION_CHANGE)
            repaired(f"{path}.change", f"read {change!r} as {fixed!r}")
            clean_rel["change"] = fixed
        raw_reason = str(rel.get("reasonEvent") or "")
        if raw_reason:
            reason = renamed_keys.get(raw_reason, raw_reason)
            if reason not in kept_keys:
                # Not a key from this turn — then it must name an existing event, by
                # canonical id or by the bare key the narrator wrote it under.
                reason = resolve_event(reason)
            if reason:
                if reason != raw_reason:
                    repaired(f"{path}.reasonEvent", f"read {raw_reason!r} as {reason!r}")
                clean_rel["reasonEvent"] = reason
            else:
                # The reason was always optional, so a dangling one costs the reason,
                # never the relation the narrator actually declared.
                clean_rel.pop("reasonEvent", None)
                drop(f"{path}.reasonEvent",
                     "an event key declared this turn, or the canonical id of an existing "
                     f"event, got {raw_reason!r}",
                     f"Kept the relation at {path} but dropped its reasonEvent "
                     f"{raw_reason!r}, which names no event kept this turn or in this life.")
        kept_relations.append(clean_rel)

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


def life_centre(index: dict[str, Any]) -> dict[str, Any]:
    """Who this life is *about* — the single node the people lens orbits.

    ``PLAYER`` is the entity every life has without declaring it, and the design
    assumed a narrator would address the protagonist through it. Nothing ever told
    the narrator that id exists: ``shape.memory`` asks it to declare "a person a
    turn introduces", and the person a named life introduces first is the one
    living it. So a narrator declares that person as a character of its own and
    then addresses *everything* to that id. Measured on a live run: ``chen-yu``
    (陈屿) carried 26 of 26 event participations and all 5 relations while
    ``player`` carried none — two ids for one person, which the lens rendered as
    two selectable centres, and the one it defaulted to was the empty one.

    Both halves are fixed: ``shape.memory`` now names ``player`` so a new life
    declares one identity, and the centre is *resolved from the graph* rather than
    assumed, so a life already written the other way reads correctly too.

    ``player`` wins whenever the graph references it at all — a declared identity
    is never second-guessed. Only when it is entirely unreferenced does a
    substitute apply, and only for the character present in strictly more than
    :data:`CENTRE_EVENT_SHARE` of the life's events: a share at most one character
    can hold, and one a supporting character cannot. Below it there is no
    substitute and ``player`` stands, because a life with no evident centre must
    not be handed an invented one.

    Returns ``{"id", "name"}``; ``name`` is empty when the centre is an unnamed
    ``player``, which is the client's cue to use its own word for "me".
    """
    events = index["events"]
    entities = index["entities"]
    referenced = any(
        PLAYER in ev["participants"] for ev in events.values()
    ) or any(PLAYER in (rec["from"], rec["to"]) for rec in index["relations"])

    chosen = PLAYER
    if not referenced and events:
        present: dict[str, int] = {}
        for ev in events.values():
            for pid in set(ev["participants"]):
                if (entities.get(pid) or {}).get("kind") == "character":
                    present[pid] = present.get(pid, 0) + 1
        # Sorted, not just max(): two entities can never both clear a strict
        # majority, but ordering the scan anyway keeps a rebuild byte-identical
        # regardless of dict insertion order (the Phase 0 determinism bar).
        for count, eid in sorted(((n, i) for i, n in present.items()), reverse=True):
            if count > len(events) * CENTRE_EVENT_SHARE:
                chosen = eid
            break

    name = str((entities.get(chosen) or {}).get("name") or "")
    # build_index seeds the implicit player's name with its own id; that is a
    # placeholder, not a thing to show a player.
    return {"id": chosen, "name": "" if name == PLAYER else name}


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

    return {"nodes": nodes, "edges": edges, "relations": relations,
            "centre": life_centre(index)}



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
