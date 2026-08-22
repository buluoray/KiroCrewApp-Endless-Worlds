"""Reach gating and the anti-halo instruments.

The shape of everything here: **the app measures, the narrator adjusts.** None of
it rewrites narration. A backend that quietly deleted a lucky break or capped a
number would be writing the story badly, and the player would feel the seams
without being able to name them. What it does instead is hand the narrator a
reading of its own recent behaviour — how eventful the life has been, which
sources it keeps crediting, which gains it never explained — and the narrator's own
rules (R7) tell it what to do about them.

Two things ARE enforced rather than reported, because they are not judgement calls:

* A distant event cannot arrive as established fact. It arrives marked as rumour.
  That is a property of where the character is standing, not a stylistic choice.
* A gain with no source is marked. Not refused — a narrator who forgot to say
  where five gold came from has still narrated a real turn — but the omission is
  visible to the next turn instead of settling into the ledger unnoticed.
"""

from __future__ import annotations

from typing import Any

from content import Content

#: How far from the character something happened, nearest first. These names are
#: the app's, not a world's: a template declares digest CATEGORIES in its own
#: words, while distance is a property of the character's position that every world
#: shares.
REACH_TIERS: tuple[str, ...] = ("here", "local", "regional", "realm", "world")

#: What a character can hear about when the narrator has not said otherwise.
#: "local" and not "world": a life starts in one place, and a newborn farmer who is
#: briefed on continental diplomacy has already been handed a protagonist's vantage
#: point before drawing breath.
DEFAULT_REACH = "local"

#: Turns looked at when reading how eventful a life has been.
DENSITY_WINDOW = 6

#: Turns looked at when counting how often the narrator credits the same source.
ATTRIBUTION_WINDOW = 12

#: Above this many notable events per turn, a life is being handed more than a
#: world would give it. Not a cap — a reading the narrator is shown.
BUSY_PER_TURN = 2.0

#: A source credited this many times inside the window has stopped being a reason
#: and become a habit.
REPEAT_PRESSURE = 3


def reach_rank(tier: Any) -> int:
    """Index of *tier*, or the default's index when it is not a tier we know.

    An unknown value degrades to the default rather than raising: the narrator
    writes these, and a turn should not fail because it said "far" instead of
    "distant".
    """
    if isinstance(tier, str) and tier in REACH_TIERS:
        return REACH_TIERS.index(tier)
    return REACH_TIERS.index(DEFAULT_REACH)


def gate_digest(categories: list[str], state: dict[str, Any]) -> list[dict[str, Any]]:
    """The world's report, marked by how it could have reached this character (R6).

    Two outcomes per entry, decided by distance alone:

    * within reach → reported
    * beyond reach → **rumour**, and marked so even if the narrator declared it as
      established fact

    Nothing is ever dropped. An earlier revision withheld anything more than one
    tier away, which meant a village character could never hear about the empire at
    all — wrong twice over: rumour is precisely the thing that travels further than
    a person does, and silently deleting something the narrator thought mattered is
    the one behaviour this module exists to avoid. The gate decides HOW news
    arrives, never WHETHER the narrator's words survive.

    Order follows the world's own category order, then rumours, so a world that
    thinks war matters more than trade reads that way.
    """
    raw = _find_digest(categories, state)
    reach = reach_rank(state.get("reach"))

    reported: list[dict[str, Any]] = []
    rumoured: list[dict[str, Any]] = []

    for category in categories:
        entry = raw.get(category)
        if entry is None:
            continue
        text, at, declared_rumour = _unpack(entry)
        if not text:
            continue
        distance = reach_rank(at) if at is not None else reach
        if distance <= reach and not declared_rumour:
            reported.append({"category": category, "text": text, "rumour": False})
        else:
            rumoured.append({"category": category, "text": text, "rumour": True})

    # A world's own rumour list is rumour by construction, whatever its distance.
    loose = raw.get("rumours")
    if isinstance(loose, list):
        for item in loose:
            text, _at, _ = _unpack(item)
            if text:
                rumoured.append({"category": "rumour", "text": text, "rumour": True})

    return reported + rumoured


def _find_digest(categories: list[str], state: dict[str, Any]) -> dict[str, Any]:
    """The world's report, wherever the narrator put it.

    ``state["digest"]`` is canonical. Failing that, ANY top-level dict holding at
    least one of this world's own category names is taken as the digest: the
    flagship's first real turn nested it under a name of the narrator's own
    choosing, which was a better name than "digest" in that world's language, and
    refusing to look would have thrown away every world event it wrote.
    """
    direct = state.get("digest")
    if isinstance(direct, dict):
        return direct
    known = set(categories) | {"rumours"}
    for value in state.values():
        if isinstance(value, dict) and known.intersection(value):
            return value
    return {}


def _unpack(entry: Any) -> tuple[str, Any, bool]:
    """``(text, at, declared_rumour)`` from either a bare string or an object.

    Both shapes are accepted for the same reason the panel primitives accept both:
    refusing one would be the app telling the narrator how to write.
    """
    if isinstance(entry, str):
        return entry.strip(), None, False
    if isinstance(entry, dict):
        text = entry.get("text") or entry.get("summary") or ""
        return (
            str(text).strip(),
            entry.get("at") or entry.get("reach"),
            bool(entry.get("rumour")),
        )
    return "", None, False


def event_density(chronicle: list[dict[str, Any]], window: int = DENSITY_WINDOW) -> dict[str, Any]:
    """How eventful the recent past has been (R7.4).

    Counts what the narrator itself marked as notable rather than guessing from
    prose length — a long quiet month and a short catastrophic one are not
    distinguishable by character count, and inferring drama from verbosity would
    reward padding.
    """
    recent = chronicle[-window:] if window else []
    if not recent:
        return {"turns": 0, "events": 0, "perTurn": 0.0, "busy": False, "quiet": False}

    events = 0
    for entry in recent:
        marked = entry.get("events")
        if isinstance(marked, list):
            events += len(marked)
        elif isinstance(marked, int):
            events += max(0, marked)
    per_turn = events / len(recent)
    return {
        "turns": len(recent),
        "events": events,
        "perTurn": round(per_turn, 2),
        "busy": per_turn > BUSY_PER_TURN,
        # Quiet is reported too, and is NOT a fault. A life is allowed to be
        # uneventful; the reading exists so the narrator can tell the difference
        # between a calm stretch it chose and one it drifted into.
        "quiet": events == 0 and len(recent) >= 3,
    }


def attribution(
    chronicle: list[dict[str, Any]], window: int = ATTRIBUTION_WINDOW
) -> dict[str, Any]:
    """Which sources this life keeps being credited to, and what went unexplained.

    ``leaning`` is the anti-halo instrument (R7.3): a source credited over and over
    inside one window has stopped being a reason and become a habit, and the
    narrator's own diminishing-returns rule is what should apply to it.
    """
    recent = chronicle[-window:] if window else []
    counts: dict[str, int] = {}
    unsourced: list[dict[str, Any]] = []

    for entry in recent:
        for gain in _gains(entry):
            source = str(gain.get("source") or "").strip()
            if not source:
                unsourced.append(
                    {
                        "turn": entry.get("turn"),
                        "field": gain.get("field"),
                        "amount": gain.get("amount"),
                    }
                )
                continue
            counts[source] = counts.get(source, 0) + 1

    leaning = [
        {"source": s, "times": n}
        for s, n in sorted(
            ((s, n) for s, n in counts.items() if n >= REPEAT_PRESSURE),
            key=lambda t: (-t[1], t[0]),
        )
    ]
    return {
        "turns": len(recent),
        "sources": counts,
        "leaning": leaning,
        "unsourced": unsourced,
    }


def _gains(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw = entry.get("gains")
    return [g for g in raw if isinstance(g, dict)] if isinstance(raw, list) else []


def compose_restraint(chronicle: list[dict[str, Any]], language: Any = "en") -> str:
    """The reading handed to the narrator, in the world's own language.

    Phrased as observations, not orders. The rulebook already says what the world
    owes nobody; being told "you have handed this life three windfalls in six
    months" is what makes that rule actionable, whereas "be harsher" is a mood.

    Returns "" when there is nothing worth saying — a prompt that always carries a
    paragraph of self-criticism trains the narrator to skim it.
    """
    text = Content(language)
    density = event_density(chronicle)
    credit = attribution(chronicle)
    lines: list[str] = []

    if density["busy"]:
        lines.append(text("restraint.busy", turns=density["turns"], events=density["events"]))
    if density["quiet"]:
        lines.append(text("restraint.quiet", turns=density["turns"]))
    for lean in credit["leaning"]:
        lines.append(
            text(
                "restraint.leaning",
                source=lean["source"],
                turns=credit["turns"],
                times=lean["times"],
            )
        )
    if credit["unsourced"]:
        fields = text("list.join").join(str(u.get("field") or "?") for u in credit["unsourced"][:4])
        lines.append(text("restraint.unsourced", fields=fields))

    if not lines:
        return ""
    return text("restraint.intro") + "\n" + "\n".join(f"- {ln}" for ln in lines)
