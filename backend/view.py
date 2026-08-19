"""The play view — what the player sees this turn, resolved on the server.

Panel visibility and field lookup live here rather than in the UI for one reason
worth stating: the ``when`` interpreter is a parser over untrusted template text
(``template.py``), and there must be exactly one of it. A second evaluator in
JavaScript would be a second grammar to keep identical, and the failure mode of
drift is a panel that appears in one place and not the other.

The convention the narrator maintains, derived from the flagship's own conditions
(``state.magic.awakened``, ``state.academy.enrolled``):

* a panel's data lives at ``state[<panelId>]``
* a field's value at ``state[<panelId>][<fieldId>]``
* anything else under a panel is a flag the narrator keeps for its ``when``

A missing value is not an error. It renders as a gap and the panel stays (R5.8) —
a life where the narrator has not yet mentioned your reputation is normal, and
hiding the whole panel over it would make the player think something broke.
"""

from __future__ import annotations

import re
from typing import Any

from halo import gate_digest
from template import Template

#: Box-drawing, block and geometric characters — the ones a template uses to
#: DRAW a panel in a terminal. Markdown uses none of them, which is what makes
#: this list safe to strip anywhere on a line.
#:
#: Deliberately NOT here: ``|``, ``-``, ``=``, ``*``, ``_``. Those are markdown's
#: own structure (tables, thematic breaks, emphasis) and the narrator writes
#: markdown, which the play page now renders. Stripping them turned
#: ``***他死了***`` into plain text and cut the pipes out of a table, leaving its
#: rows as loose words. R18 asks for framing to be removed and structure rendered
#: AS structure — a markdown table is structure, a drawn box is not.
_FRAMING = re.compile(r"[\u2500-\u257f\u2580-\u259f\u25a0-\u25ff\u2b1b\u2b1c\ufe0f]")

#: A line made only of drawn framing carries no content at all.
_FRAMING_ONLY_LINE = re.compile(r"^[\u2500-\u259f\u25a0-\u25ff\s]+$")


def strip_terminal_framing(prose: str) -> str:
    """Remove drawn frames from narration, keeping the words inside them.

    Deliberately not a general sanitiser: it removes framing, never content. A
    line that is nothing but frame is dropped; a line with words inside a frame
    keeps its words. Getting this backwards would eat narration, which is the
    product — and the danger is real enough that a test asserts the inside of a
    frame survives.
    """
    if not prose:
        return ""
    out: list[str] = []
    for line in prose.splitlines():
        if line.strip() and _FRAMING_ONLY_LINE.match(line):
            continue
        out.append(_FRAMING.sub("", line).rstrip())
    text = "\n".join(out)
    # Collapse the blank runs the stripped frames leave behind, but keep ONE
    # blank line: it is a markdown paragraph break.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _shape(primitive: str, raw: Any, options: Any = None) -> dict[str, Any]:
    """Normalise a declared value into what a primitive component can render.

    Shaped by PRIMITIVE, never by field id — the whole point of the primitives is
    that a world gets its panels by declaring them, with no code written per
    world. A branch on a field name here would be the first world-specific line
    in the app.
    """
    if raw is None:
        return {"kind": "gap"}

    if primitive in ("stat", "resource"):
        # Accept both a bare number and {value, max, note}: a narrator that
        # declares 「魔力: 40」 and one that declares 「魔力: {value: 40, max: 100}」
        # both mean the same thing, and refusing one of them would be the app
        # telling the narrator how to write.
        if isinstance(raw, dict):
            value, cap = raw.get("value"), raw.get("max")
            note = raw.get("note") or ""
        else:
            value, cap, note = raw, None, ""
        pct = None
        if isinstance(value, (int, float)) and isinstance(cap, (int, float)) and cap > 0:
            pct = max(0.0, min(1.0, float(value) / float(cap)))
        return {"kind": primitive, "value": value, "max": cap, "pct": pct, "note": note}

    if primitive == "trend":
        if isinstance(raw, dict):
            return {
                "kind": "trend",
                "value": raw.get("value"),
                "direction": raw.get("direction") or "",
                "note": raw.get("note") or "",
            }
        return {"kind": "trend", "value": raw, "direction": "", "note": ""}

    if primitive == "rank":
        # `tier`, and emphatically NOT `label`.
        #
        # This shaped dict is splatted over the field's own `{"id", "label",
        # "primitive", ...}`, so a key called `label` here does not add a label —
        # it DESTROYS the one the world declared. Measured on the live flagship:
        # the world declares `standing` with the label 社会地位 and nine tiers, the
        # narrator wrote the free phrase "边地平民，普通一户" into it, and the play
        # page showed that phrase where the label belongs with the field's real
        # name gone entirely. The UI then rendered an EMPTY accent chip, because it
        # was reading `label_`/`value` and this branch sends neither — which is the
        # small meaningless dot that made the panel look broken.
        #
        # One key collision, two symptoms, and a name that reads as harmless.
        if isinstance(raw, dict):
            return {
                "kind": "rank",
                "tier": str(raw.get("label") or raw.get("tier") or ""),
                "note": raw.get("note") or "",
            }
        return {"kind": "rank", "tier": "" if raw is None else str(raw), "note": ""}

    if primitive == "people":
        return {
            "kind": "people",
            "columns": _columns(options),
            "entries": _people(raw, _columns(options)),
        }

    if primitive == "threads":
        return {"kind": "threads", "entries": _entries(raw, ("text", "status"))}

    if primitive == "inventory":
        return {"kind": "inventory", "items": _inventory(raw)}

    return {"kind": "field", "value": raw if isinstance(raw, str) else str(raw)}


def _columns(options: Any) -> list[str]:
    """The column names a ``people`` field declared via ``attributes: [...]``.

    The world names the columns its prose lists (attitude, closeness, standing);
    without them this is empty and people fall back to name + note, exactly as
    before. Read from the field's own ``options``, never from a field id.
    """
    if isinstance(options, dict):
        cols = options.get("attributes")
        if isinstance(cols, list):
            return [str(c) for c in cols if isinstance(c, str) and c]
    return []


def _people(raw: Any, columns: list[str]) -> list[dict[str, Any]]:
    """People as name + note, plus any declared attribute columns per person.

    With no declared columns this is exactly the old name/note shape, so a world
    that named none is untouched. With them, each person also carries the values
    the prose lists under those columns — previously shaped away and lost.
    """
    if isinstance(raw, str):
        return [{"name": raw, "note": ""}]
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name") or item.get("text") or ""
            if not name:
                continue
            entry: dict[str, Any] = {"name": str(name), "note": str(item.get("note") or "")}
            cols = {c: str(item[c]) for c in columns if item.get(c) not in (None, "")}
            if cols:
                entry["cols"] = cols
            out.append(entry)
        elif item:
            out.append({"name": str(item), "note": ""})
    return out


def _inventory(raw: Any) -> list[dict[str, str]]:
    """Inventory items as name + optional count + note.

    A dict item keeps the count and note the narrator wrote, so "three healing
    potions" is no longer the same chip as "one". A bare string is just a name.
    Empty items (no name) are dropped, as they always were.
    """
    items = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, str]] = []
    for x in items:
        if isinstance(x, dict):
            name = str(x.get("name") or "")
            if not name:
                continue
            entry = {"name": name}
            if x.get("count") not in (None, ""):
                entry["count"] = str(x.get("count"))
            if x.get("note") not in (None, ""):
                entry["note"] = str(x.get("note"))
            out.append(entry)
        elif x:
            out.append({"name": str(x)})
    return out


def _entries(raw: Any, keys: tuple[str, str]) -> list[dict[str, str]]:
    primary, secondary = keys
    if isinstance(raw, str):
        return [{primary: raw, secondary: ""}]
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            first = item.get(primary) or item.get("name") or item.get("text") or ""
            second = item.get(secondary) or item.get("note") or item.get("status") or ""
            if first:
                out.append({primary: str(first), secondary: str(second)})
        elif item:
            out.append({primary: str(item), secondary: ""})
    return out


def world_detail(pack: Any, *, include_prose: bool = False) -> dict[str, Any]:
    """The body ``GET /worlds/{id}`` returns.

    A plain function rather than inline in the handler so the UI's contract with
    it is testable. It is not a hypothetical: renaming ``openingLabels`` to
    ``opening`` here once blanked the whole app with
    ``Cannot read properties of undefined (reading 'map')`` — the UI kept reading
    a key the backend had stopped sending, and nothing tied the two together.
    ``styleRows`` rather than overwriting ``styles``: ``summarize`` already sends
    ``styles`` as the world's style LABELS, and shadowing it with objects put two
    different shapes behind one field name. That works in untyped code by accident
    and is the exact drift the contract tests exist to catch — the detail view read
    ``.length`` on it while the shelf read the labels, and neither knew the other
    existed.
    """
    from world import summarize

    t = pack.template
    body: dict[str, Any] = {
        **summarize(pack),
        "opening": [
            {
                "id": g.id,
                "label": g.label,
                "kind": g.kind,
                "options": list(g.options),
                "custom": g.custom,
                # ``random`` is a rule of the world, not a convenience: a group
                # marked so is decided by the world and must not be offered as a
                # choice. The UI shows the result, never a picker.
                "worldDecides": g.random,
            }
            for g in t.opening
        ],
        "styleRows": [
            {"id": s.id, "label": s.label, "default": s.default} for s in t.styles
        ],
        "panels": [
            {
                "id": p.id,
                "always": p.always,
                "when": p.when.source if p.when else None,
                "fields": [
                    {"id": f.id, "label": f.label, "primitive": f.primitive}
                    for f in p.fields
                ],
            }
            for p in t.panels
        ],
        "digest": list(t.digest_categories),
        "endings": [e.id for e in t.endings],
        "save": list(t.save_schema),
    }
    if include_prose:
        body["prose"] = pack.prose
    return body


def _lookup(data: dict[str, Any], field: Any) -> Any:
    """A field's value, by id first and by LABEL second.

    Two spellings on purpose, and the id is canonical. The label form exists
    because the narrator is a language model: the labels are the words it was
    shown, and it will sometimes key state by them. Losing a whole panel over a
    spelling is worse than accepting both — the flagship's first real turn came
    back keyed entirely by label, and every panel read as empty.
    """
    if field.id in data:
        return data[field.id]
    return data.get(field.label)


def _panel_data(panel: Any, state: dict[str, Any]) -> dict[str, Any]:
    """This panel's own dict, whichever way the narrator nested it.

    ``state[<panelId>]`` is canonical. A FLAT state — every field at the top level
    — is accepted too, because that is what a narrator declares when nobody told
    it otherwise, and it is a perfectly reasonable shape for a story to be in.
    """
    nested = state.get(panel.id)
    if isinstance(nested, dict):
        return nested
    by_label: dict[str, Any] = {}
    for field in panel.fields:
        if field.id in state:
            by_label[field.id] = state[field.id]
        elif field.label in state:
            by_label[field.label] = state[field.label]
    return by_label


def resolve_ending(template: Template, state: dict[str, Any]) -> str:
    """The single place a life is judged to be over, returning the ending id.

    A world declares its ``endings`` as ``when`` conditions; the first one that
    holds names how this life ended, and the world's own law wins. The narrator
    may also close a life directly by writing ``state["ended"]`` — a string names
    the ending, any other truthy value means "over" without a declared id. Empty
    string means the life continues.

    Kept here so both the play view and the turn route ask the same question: a
    life the view calls ended must be the same life the turn route refuses to
    advance, and a second evaluator would let those two drift.
    """
    for ending in template.endings:
        if ending.when.evaluate(state):
            return ending.id
    flag = state.get("ended")
    if isinstance(flag, str) and flag:
        return flag
    return "ended" if flag else ""


def build_play_view(
    template: Template,
    state: dict[str, Any],
    *,
    chronicle: list[dict[str, Any]] | None = None,
    scenes: list[dict[str, Any]] | None = None,
    unlocked: list[str] | None = None,
) -> dict[str, Any]:
    """Everything the play page renders, with nothing left for it to decide."""
    chronicle = chronicle or []
    last = chronicle[-1] if chronicle else {}
    turn = int(state.get("turn") or 0)

    panels: list[dict[str, Any]] = []
    for panel in template.panels:
        if not panel.visible(state):
            continue
        data = _panel_data(panel, state)
        fields = [
            {
                "id": f.id,
                "label": f.label,
                "primitive": f.primitive,
                "options": f.options,
                **_shape(f.primitive, _lookup(data, f), f.options),
            }
            for f in panel.fields
        ]
        panels.append({
            "id": panel.id,
            "always": panel.always,
            "fields": fields,
            # A panel where the narrator has said nothing yet is still shown, but
            # the UI can quiet it down rather than presenting a wall of dashes.
            "empty": all(f["kind"] == "gap" for f in fields),
        })

    ending_id = resolve_ending(template, state)
    return {
        "turn": turn,
        "clock": _clock(template, state),
        "prose": strip_terminal_framing(str(last.get("prose") or "")),
        "choices": list(last.get("choices") or []),
        "digest": gate_digest(template.digest_categories, state),
        "panels": panels,
        "scenes": scenes or [],
        "style": state.get("style") or "",
        "ended": bool(ending_id),
        "endingId": ending_id,
        # Chapter headings the world has just opened this month, in the world's own
        # words. Computed by the route (it needs the prior state); the play page
        # shows them as a quiet "a new chapter opens" marker.
        "unlocked": list(unlocked or []),
    }


def _clock(template: Template, state: dict[str, Any]) -> str:
    """The world's own way of naming when it is.

    Formatted from the template's label, so a world that counts in seasons or
    dynasties says so instead of being described in the app's words.
    """
    label = template.clock_label or ""
    if not label:
        return ""
    values = state.get("clock")
    values = values if isinstance(values, dict) else {}
    out = label
    for key, value in values.items():
        out = out.replace("{" + str(key) + "}", str(value))
    return out if "{" not in out else ""
