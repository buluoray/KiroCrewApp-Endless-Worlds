"""Echo story cards — a keepsake turned into something shareable (design §8.4).

A card is a DRAFT over an allowlist, and the allowlist is fixed at creation:
the keepsake's cited events, and the entities those events directly involve.
Every edit thereafter can only NARROW or RELABEL — drop an event, hide an
entity, rename a person, reorder — never add. That single rule is what makes
the §11 completion bar checkable: the export equals the preview because both
are pure functions of the same draft, and nothing outside the allowlist has a
path into either.

What can never appear in an export, by construction:

* a ``hidden``/``foreshadowed``/``rumoured`` event — the allowlist is built
  from ``known`` events only, the same rule as the star map (§5.4);
* another life's data — the index the allowlist is built from is per-run;
* a network request, a runtime token, or a run id — the export templates
  contain no script, no external reference, and never interpolate the run id;
* an ending, when spoilers are off — events on the life's final turn are
  spoiler content and are filtered wherever they would show (§12.3).

Anonymisation is a display-name map applied at RENDER time to every surface a
name reaches — title line, event summaries, excerpt, graph labels, alt text —
so a replaced name cannot survive in some corner the editor forgot (§12.3).
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from memory_graph import PLAYER

MAX_TITLE = 120
MAX_COVER = 200
MAX_THOUGHT = 1000
#: A card tells one arc, not a whole life (§8.4: 2–5 key events).
MAX_EVENTS = 5


class StoryCardError(ValueError):
    def __init__(self, field: str, expected: str) -> None:
        super().__init__(f"{field}: {expected}")
        self.field = field
        self.expected = expected


# ── the draft ────────────────────────────────────────────────────────────


def build_draft(
    index: dict[str, Any],
    keepsake: dict[str, Any],
    *,
    ended_turn: int = 0,
    language: str = "en",
) -> dict[str, Any]:
    """A card draft from a keepsake — automatic arrangement, then the player edits.

    The allowlist is decided HERE and never widens: the keepsake's cited
    ``known`` events (time-ordered, capped at :data:`MAX_EVENTS`), plus the
    entities those events directly involve. ``ended_turn`` marks which turn is
    ending content for the spoiler filter — 0 means the life continues.
    """
    events = []
    for cid in keepsake.get("cites") or []:
        ev = index["events"].get(str(cid))
        if ev is None or ev["disclosure"] != "known":
            continue
        events.append(ev)
    events.sort(key=lambda e: (e["turn"], e["id"]))
    events = events[:MAX_EVENTS]
    if not events:
        raise StoryCardError("keepsake", "cites at least one known event")

    involved: set[str] = set()
    for ev in events:
        involved.update(ev["participants"])
        if ev["place"]:
            involved.add(ev["place"])
        involved.update(th["id"] for th in ev["threads"])
    involved.discard(PLAYER)

    excerpt = str(keepsake.get("excerpt") or "")
    card: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "keepsakeId": str(keepsake.get("id") or ""),
        "title": str(keepsake.get("title") or ""),
        "coverLine": "",
        "thought": str(keepsake.get("thought") or ""),
        "language": language if language in ("zh", "en") else "en",
        "showSpoilers": False,
        "endedTurn": int(ended_turn),
        "events": [
            {
                "id": ev["id"],
                "turn": ev["turn"],
                "title": ev["title"],
                "summary": ev["summary"],
                "action": ev["action"],
                # The player's own selected prose rides on the event of its
                # turn, replacing the one-line summary in the render (§8.4).
                "excerpt": excerpt
                if excerpt and ev["turn"] == int(keepsake.get("turn") or 0)
                else "",
                "included": True,
            }
            for ev in events
        ],
        "entities": [
            {
                "id": eid,
                "kind": index["entities"][eid]["kind"],
                "name": index["entities"][eid]["name"],
                # What the export prints. Editing THIS is anonymisation; the
                # real name never leaves the draft file.
                "display": index["entities"][eid]["name"],
                "included": True,
            }
            for eid in sorted(involved)
            if eid in index["entities"]
        ],
        # Edges among allowlist nodes only, captured at build time so a later
        # graph change cannot grow the card (the preview IS the contract).
        "edges": _edges_within(index, {ev["id"] for ev in events}, involved),
        "createdAt": time.time(),
        "updatedAt": time.time(),
    }
    return card


def _edges_within(
    index: dict[str, Any], event_ids: set[str], entity_ids: set[str]
) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for cid in sorted(event_ids, key=lambda c: (index["events"][c]["turn"], c)):
        ev = index["events"][cid]
        for p in ev["participants"]:
            if p in entity_ids:
                edges.append({"from": p, "type": "participated_in", "to": cid})
        if ev["place"] and ev["place"] in entity_ids:
            edges.append({"from": cid, "type": "occurred_at", "to": ev["place"]})
        for th in ev["threads"]:
            if th["id"] in entity_ids:
                edges.append({"from": cid, "type": th["effect"], "to": th["id"]})
        for target in ev["echoes"]:
            if target in event_ids:
                edges.append({"from": cid, "type": "echoes", "to": target})
    return edges


def apply_edits(card: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Narrow, relabel, reorder — never add (§8.4).

    The refusal cases are the point: an event or entity id not already on the
    card is rejected, and turn numbers have no edit path at all (the client
    sends an ORDER of existing ids, never turn values).
    """
    if "title" in changes:
        title = str(changes["title"]).strip()
        if not title or len(title) > MAX_TITLE:
            raise StoryCardError("title", f"1–{MAX_TITLE} characters")
        card["title"] = title
    if "coverLine" in changes:
        cover = str(changes["coverLine"]).strip()
        if len(cover) > MAX_COVER:
            raise StoryCardError("coverLine", f"at most {MAX_COVER} characters")
        card["coverLine"] = cover
    if "thought" in changes:
        thought = str(changes["thought"])
        if len(thought) > MAX_THOUGHT:
            raise StoryCardError("thought", f"at most {MAX_THOUGHT} characters")
        card["thought"] = thought.strip()
    if "showSpoilers" in changes:
        card["showSpoilers"] = bool(changes["showSpoilers"])
    if "language" in changes:
        lang = str(changes["language"])
        if lang not in ("zh", "en"):
            raise StoryCardError("language", "zh or en")
        card["language"] = lang

    if "order" in changes:
        order = [str(x) for x in changes["order"] or []]
        known = {ev["id"] for ev in card["events"]}
        if set(order) != known:
            raise StoryCardError("order", "exactly the ids already on this card, reordered")
        by_id = {ev["id"]: ev for ev in card["events"]}
        card["events"] = [by_id[i] for i in order]

    if "events" in changes:
        # {id: included} — inclusion flags only.
        flags = changes["events"]
        if not isinstance(flags, dict):
            raise StoryCardError("events", "an object of {eventId: included}")
        known = {ev["id"] for ev in card["events"]}
        for eid in flags:
            if str(eid) not in known:
                raise StoryCardError("events", f"an event already on this card, got {eid!r}")
        for ev in card["events"]:
            if ev["id"] in flags:
                ev["included"] = bool(flags[ev["id"]])

    if "entities" in changes:
        # {id: {included?, display?}} — hide or rename, never add.
        rows = changes["entities"]
        if not isinstance(rows, dict):
            raise StoryCardError("entities", "an object of {entityId: {included, display}}")
        known_e = {e["id"]: e for e in card["entities"]}
        for eid, patch in rows.items():
            ent = known_e.get(str(eid))
            if ent is None:
                raise StoryCardError("entities", f"an entity already on this card, got {eid!r}")
            if isinstance(patch, dict):
                if "included" in patch:
                    ent["included"] = bool(patch["included"])
                if "display" in patch:
                    display = str(patch["display"]).strip()
                    if not display or len(display) > 120:
                        raise StoryCardError("entities", f"{eid}: display must be 1–120 characters")
                    ent["display"] = display

    card["updatedAt"] = time.time()
    return card


# ── what the export actually contains ────────────────────────────────────


def resolve(card: dict[str, Any]) -> dict[str, Any]:
    """The renderable view: included nodes only, names mapped, spoilers gated.

    Every exporter renders from THIS and nothing else — one resolution point
    is what makes "export equals preview" a property instead of a hope. The
    §12.3 rules all land here: excluded entities take their edges with them,
    an anonymised name is substituted inside summaries and the excerpt too,
    and with spoilers off the ending turn's events vanish entirely.
    """
    # Real-name → display-name substitution, applied to EVERY surface a name
    # can reach. That includes other entities' own names: a thread called
    # 「艾琳欠下的人情」 embeds the very name the player anonymised, and a cast
    # chip or SVG label printing it verbatim would undo the rename (§12.3).
    renames = [
        (e["name"], e["display"])
        for e in card["entities"]
        if e["included"] and e["display"] != e["name"] and e["name"]
    ]
    hidden_names = [e["name"] for e in card["entities"] if not e["included"] and e["name"]]

    def scrub(text: str) -> str:
        for old, new in renames:
            text = text.replace(old, new)
        for old in hidden_names:
            text = text.replace(old, "□□")
        return text

    names: dict[str, str] = {}
    entities = []
    for ent in card["entities"]:
        if not ent["included"]:
            continue
        # Scrub OTHER names out of this entity's display — never its own pair:
        # a player who renames 艾琳 to 「艾琳姐」 chose a display containing the
        # real name, and self-application would mangle it (艾琳姐姐).
        display = ent["display"]
        for old, new in renames:
            if old != ent["name"]:
                display = display.replace(old, new)
        for old in hidden_names:
            display = display.replace(old, "□□")
        entities.append({**ent, "display": display})
        names[ent["id"]] = display

    spoilers = bool(card["showSpoilers"])
    ended = int(card.get("endedTurn") or 0)
    events = []
    for ev in card["events"]:
        if not ev["included"]:
            continue
        if not spoilers and ended and ev["turn"] >= ended:
            continue  # ending content stays out when spoilers are off (§12.3)
        events.append(
            {
                **ev,
                "title": scrub(ev["title"]),
                "summary": scrub(ev["summary"]),
                "excerpt": scrub(ev["excerpt"]),
                "action": scrub(ev["action"]),
            }
        )

    kept_events = {ev["id"] for ev in events}
    kept_entities = set(names)
    edges = [
        e
        for e in card["edges"]
        if (e["from"] in kept_events or e["from"] in kept_entities)
        and (e["to"] in kept_events or e["to"] in kept_entities)
    ]

    return {
        "title": scrub(card["title"]),
        "coverLine": scrub(card["coverLine"]),
        "thought": scrub(card["thought"]),
        "language": card["language"],
        "events": events,
        "entities": entities,
        "edges": edges,
        "names": names,
    }


# ── exporters (self-contained: no scripts, no network, no ids) ──────────

_STRINGS = {
    "zh": {
        "page": "第 {n} 页",
        "then": "你当时的选择",
        "cast": "这段往事里的他们",
        "thought": "写在最后",
        "graph": "这几件事如何相连",
    },
    "en": {
        "page": "Page {n}",
        "then": "What was chosen then",
        "cast": "Who was there",
        "thought": "A closing thought",
        "graph": "How these moments connect",
    },
}


def _s(lang: str, key: str, **vars: Any) -> str:
    raw = _STRINGS.get(lang, _STRINGS["en"])[key]
    for k, v in vars.items():
        raw = raw.replace("{" + k + "}", str(v))
    return raw


def to_markdown(card: dict[str, Any]) -> str:
    view = resolve(card)
    lang = view["language"]
    out = [f"# {view['title']}"]
    if view["coverLine"]:
        out += ["", f"> {view['coverLine']}"]
    for ev in view["events"]:
        out += ["", f"## {_s(lang, 'page', n=ev['turn'])} · {ev['title']}"]
        body = ev["excerpt"] or ev["summary"]
        if body:
            out.append(body)
        if ev["action"]:
            out.append(f"*{_s(lang, 'then')}: {ev['action']}*")
    if view["entities"]:
        out += [
            "",
            f"### {_s(lang, 'cast')}",
            "、".join(e["display"] for e in view["entities"])
            if lang == "zh"
            else ", ".join(e["display"] for e in view["entities"]),
        ]
    if view["thought"]:
        out += ["", f"### {_s(lang, 'thought')}", view["thought"]]
    return "\n".join(out) + "\n"


def to_html(card: dict[str, Any]) -> str:
    """One self-contained document: inline CSS, zero scripts, zero URLs."""
    view = resolve(card)
    lang = view["language"]
    esc = html.escape
    rows = []
    for ev in view["events"]:
        body = esc(ev["excerpt"] or ev["summary"])
        action = (
            f"<div class='act'>{esc(_s(lang, 'then'))}: {esc(ev['action'])}</div>"
            if ev["action"]
            else ""
        )
        rows.append(
            f"<section><h2><span class='turn'>{esc(_s(lang, 'page', n=ev['turn']))}"
            f"</span> {esc(ev['title'])}</h2><p>{body}</p>{action}</section>"
        )
    cast = ""
    if view["entities"]:
        chips = "".join(f"<span class='chip'>{esc(e['display'])}</span>" for e in view["entities"])
        cast = f"<h3>{esc(_s(lang, 'cast'))}</h3><div class='cast'>{chips}</div>"
    thought = (
        f"<h3>{esc(_s(lang, 'thought'))}</h3><p class='thought'>{esc(view['thought'])}</p>"
        if view["thought"]
        else ""
    )
    cover = f"<p class='cover'>{esc(view['coverLine'])}</p>" if view["coverLine"] else ""
    graph = to_svg(card, standalone=False)
    return f"""<!doctype html>
<html lang="{esc(lang)}"><head><meta charset="utf-8">
<title>{esc(view["title"])}</title>
<style>
body {{ margin: 0 auto; max-width: 640px; padding: 32px 20px; background: #14151f;
       color: #e5e7eb; font: 16px/1.8 system-ui, sans-serif; }}
h1 {{ font-size: 26px; }} h2 {{ font-size: 17px; margin: 26px 0 6px; }}
h3 {{ font-size: 14px; color: #9ca3af; margin: 28px 0 8px; }}
.cover {{ font-style: italic; color: #a5a8b6; border-inline-start: 3px solid #7c3aed;
          padding-inline-start: 12px; }}
.turn {{ font-size: 12px; color: #9ca3af; font-weight: 400; margin-inline-end: 6px; }}
.act {{ font-size: 13px; font-style: italic; color: #a78bfa; }}
.chip {{ display: inline-block; border: 1px solid #2d2f3d; border-radius: 999px;
         padding: 2px 12px; margin: 0 6px 6px 0; font-size: 13px; }}
.thought {{ font-style: italic; }}
svg {{ width: 100%; height: auto; margin-top: 10px; }}
</style></head><body>
<h1>{esc(view["title"])}</h1>
{cover}
{"".join(rows)}
{cast}
<h3>{esc(_s(lang, "graph"))}</h3>
{graph}
{thought}
</body></html>
"""


def to_svg(card: dict[str, Any], *, standalone: bool = True) -> str:
    """The small relation graph, only ever the card's own nodes (§8.4).

    Events sit on a left column in time order, entities on a right column;
    edges are straight lines. Labels and the ``<title>`` accessibility text
    both use DISPLAY names, so anonymisation covers alt text too (§12.3).
    """
    view = resolve(card)
    esc = html.escape
    events = view["events"]
    entities = view["entities"]
    rows = max(len(events), len(entities), 1)
    width, row_h, pad = 640, 56, 30
    height = pad * 2 + rows * row_h

    pos: dict[str, tuple[int, int]] = {}
    for i, ev in enumerate(events):
        pos[ev["id"]] = (170, pad + i * row_h + row_h // 2)
    for i, ent in enumerate(entities):
        pos[ent["id"]] = (470, pad + i * row_h + row_h // 2)

    parts: list[str] = []
    for edge in view["edges"]:
        a, b = pos.get(edge["from"]), pos.get(edge["to"])
        if a and b:
            dash = ' stroke-dasharray="4 4"' if edge["type"] == "echoes" else ""
            parts.append(
                f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" '
                f'stroke="#5b5f75" stroke-width="1.2"{dash}/>'
            )
    for ev in events:
        x, y = pos[ev["id"]]
        label = esc(ev["title"][:18])
        parts.append(
            f"<g><title>{esc(ev['title'])}</title>"
            f'<circle cx="{x}" cy="{y}" r="8" fill="#7c3aed"/>'
            f'<text x="{x - 16}" y="{y + 4}" text-anchor="end" fill="#e5e7eb" '
            f'font-size="12">{label}</text></g>'
        )
    for ent in entities:
        x, y = pos[ent["id"]]
        label = esc(ent["display"][:14])
        parts.append(
            f"<g><title>{esc(ent['display'])}</title>"
            f'<circle cx="{x}" cy="{y}" r="6" fill="#1f2030" stroke="#9ca3af"/>'
            f'<text x="{x + 14}" y="{y + 4}" fill="#e5e7eb" font-size="12">{label}</text></g>'
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{esc(view["title"])}">'
        f'<rect width="{width}" height="{height}" fill="#14151f"/>' + "".join(parts) + "</svg>"
    )
    return svg


EXPORT_FORMATS = {
    "md": ("text/markdown; charset=utf-8", to_markdown),
    "html": ("text/html; charset=utf-8", to_html),
    "svg": ("image/svg+xml", to_svg),
}


# ── storage — drafts live inside the run directory (§6.1, §6.3) ─────────


class StoryCardStore:
    def __init__(self, data_dir: Path, run_id: str) -> None:
        self._dir = data_dir / "runs" / run_id / "story-cards"

    def get(self, card_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{12}", card_id):
            return None
        path = self._dir / f"{card_id}.json"
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) else None

    def put(self, card: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{card['id']}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(card, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp, path)
