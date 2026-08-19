"""Compiling a world header from bare prose.

The compiler is an **agent**, not a parser. Deciding that 【魔力】 is a bounded stat
while 【主修学派】 is a plain field is a judgement about meaning, and no schema can
make it. What lives here is the deterministic half:

* ``COMPILER_BRIEF`` — what the agent is told to produce. This is the single
  biggest lever on compile quality, so it is a first-class artifact, not an
  afterthought buried in a prompt string.
* ``accept_compiled_header`` — the gate. It hashes the prose, validates the
  emitted header through the **same code path** as a hand-written one, and refuses
  anything that would produce a broken world.

The gate returns a result rather than raising, because R14.6 requires telling the
user what could not be worked out — an exception traceback is not that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Any

from chapters import bodies, brief
from template import (
    FIELD_PRIMITIVES,
    OPENING_KINDS,
    TemplateError,
)
from world import (
    COMPILER_VERSION,
    CONTRACT,
    Provenance,
    WorldError,
    WorldPack,
    read_world,
    serialize_world,
)

#: What the compiling agent must produce. Written as instructions to that agent.
COMPILER_BRIEF = f"""
You are compiling a world-simulation rulebook into a machine-readable header.

You will be given the FULL PROSE of a rulebook — often 100+ chapters. Read it and
emit ONE JSON object describing what an app must render to play that world. You are
not summarising the rulebook and not rewriting it: the prose is kept verbatim and
handed to the narrator separately. You are only working out its structure.

OUTPUT FORMAT
- Emit JSON. Not YAML. Unquoted YAML silently corrupts values: 1.10 becomes the
  number 1.1, `yes`/`off` become booleans, 1:30 becomes 90, `no` becomes false.
- `version` MUST be a quoted string, e.g. "1.0".
- Emit nothing but the JSON object.

REQUIRED FIELDS
  id          lowercase slug (a-z, 0-9, hyphen), derived from the title
  title       the world's own title, as the prose gives it
  card        an emotional shelf entrance, not a feature summary:
              {{ "promise": one concise sentence about what living here feels like,
                "possibilities": 2–3 concrete lives, dilemmas, or long consequences
                the player might experience }}. Use the prose's own tone and never
              promise a guaranteed outcome, protagonist privilege, or a genre the
              rulebook does not support.
  version     quoted string; use "1.0" when the prose does not say
  language    the language the prose is written in ("zh", "en", …)
  clock       {{ "unit": …, "label": … }} — the unit the world advances in
              (month / day / season / year / mission-week), and a label template
              using {{year}} / {{month}} etc. Look for the status bar's time line.
  styles      the rulebook's own difficulty / tone / realism levels, if it has
              them. Each {{ "id", "label" }}, at most one with "default": true.
              If the prose offers none, emit a single sensible level.
  opening     the questions asked before play begins, in the prose's order. Each
              {{ "id", "label", "kind" }} where kind is one of {sorted(OPENING_KINDS)}.
              A "pick" needs "options": [...]. Add "custom": true when the prose's
              list ends with a self-defined choice. Add "random": true when the
              prose offers a randomise option — that is an action, NOT an option
              the character can end up literally holding.
  panels      the state surfaces. EXACTLY ONE must have "always": true — that is
              the status bar shown at all times. Every other panel needs a "when"
              expression instead. Each field is
              {{ "id", "label", "primitive" }}.
  endings     conditions that finish a life. Each {{ "id", "when" }}.
  digest      {{ "categories": [...], "rumours": bool }} — the categories the world
              reports each turn about itself, if the prose has a turn-resolution
              section.
  save        the categories a save must carry, if the prose lists them.
  chapters    which parts of the rulebook the narrator is told up front, and which
              the world discloses later. See CHAPTERS below. Optional — a header
              without it means "the whole rulebook, always", which is correct for a
              short world and wasteful for a long one.

CHAPTERS — cutting a long rulebook into the parts a life actually needs
A 100-chapter rulebook is not uniformly relevant. Most of it describes institutions
a given life never enters: the academy's grading rules matter to a student and to
nobody else. Briefing all of it every life buys context that life will never use,
and hands the narrator material it may start reaching for merely because it is
there.

Each entry is {{ "id", "heading" }} plus at most one of "always" / "when":
  heading   copied VERBATIM from the prose — the exact text of the line that opens
            that section. The app finds it by searching; it does not know how your
            rulebook marks a section, and it will refuse the whole pack if a heading
            you name is not present character-for-character.
  always    true for the parts the narrator cannot write a single honest turn
            without. These are sent unasked, every life.
  when      a condition (same tiny language as panels). The chapter is readable
            only while it holds. Asking earlier is REFUSED, not merely discouraged.
  neither   readable whenever the narrator asks, never volunteered.

Declare BOUNDARIES, not every chapter. Undeclared sections belong to the declared
chapter above them, so ten declarations can partition a hundred-chapter book. Text
before your first declared heading is always briefed automatically — do not declare
a chapter for the top of the file.

WHAT BELONGS IN `always` — be strict. Ask: could the narrator write one honest turn
of an ordinary life without this? Usually only:
  - the world's first principles, especially any rule that the world does not
    revolve around the player
  - the protocols that restrain the narrator: anti-protagonist-halo, no free
    windfalls, realism guards
  - causality, and how the world advances on its own
  - what the state surfaces MEAN
  - how a life can fail, end, and be inherited
Ordinary life — how commoners live, what money is worth, the weather, social class —
is TEXTURE, not law. Leave it unmarked so the narrator fetches it when a turn
touches it. If more than about half the book is `always`, you have not chosen.

WHAT BELONGS BEHIND `when` — an institution a life either enters or never does:
magic once it awakens, the academy once enrolled, the church once sworn, nobility
once titled, a domain once held. Gate on the SAME flags your panels gate on. Two
spellings of one concept means one of them is never true, and the chapter behind it
is unreachable for the whole life.

CHOOSING A PRIMITIVE — the only allowed values are {sorted(FIELD_PRIMITIVES)}
  field      a plain labelled value: a name, a place, a date, a school of magic
  stat       a number that moves and has a meaningful floor/ceiling; add
             "min"/"max" when the prose gives them, "trend": true when the prose
             cares about its direction over time
  rank       a named ladder the character climbs; add "tiers": [...] in order
  people     a roster of named characters with attributes; add
             "attributes": [...] naming the columns the prose lists
  trend      a value whose history matters more than its current number
  resource   a quantity that is SPENT and whose changes have delayed consequences
             (money, grain, troops, population); add "delayed": true
  inventory  a list of held things: skills, spells, items, holdings
  threads    open commitments, unfinished business, goals, secrets — anything the
             prose expects to be resolved later

WHEN EXPRESSIONS — deliberately tiny. Available: dotted paths rooted at `state`,
the comparisons == != > >= < <=, `and` / `or` / `not`, parentheses, and literals
(quoted strings, numbers, true, false, null). There are NO function calls, no
indexing, no arithmetic. Nesting is capped at 32.
  good:  state.magic.awakened == true
  good:  state.alive == false and state.lineage.hasHeir == false
  bad:   len(state.heirs) > 0        (no calls)
  bad:   state.wealth - 100 > 0      (no arithmetic)
Because there is no way to measure a list, ask for a scalar the narrator maintains
(`state.lineage.hasHeir`) rather than trying to inspect one.

Use ONE spelling per concept. `state.magic.awakened` in a panel and
`state.magik.awake` in an ending are two different facts, and the second will
never be true.

ENDINGS — DO NOT ENUMERATE OUTCOME NAMES. If the prose says the ending is produced
by world state, or that there is no fixed ending, then emit conditions that DETECT
a terminal state and let the narrator name what it was. A rulebook offering nine
possible world fates does not want nine hardcoded endings; it wants one condition
that notices a fate was reached. Enumerating them turns an open world into a menu.

DEATH — when the rulebook has inheritance or multi-generation play, death alone is
not an ending: it advances a generation. The ending needs both facts, e.g.
`state.alive == false and state.lineage.hasHeir == false`.

WHAT TO DO WITH UNCERTAINTY
Do not invent structure the prose does not have. If it has no academy system, emit
no academy panel. If you genuinely cannot work out a required field, say so in
plain language instead of guessing — a header that misdescribes the world is worse
than a compile that admits what it could not find.
""".strip()


@dataclass
class CompileResult:
    """Outcome of accepting a compiled header.

    ``ok`` false carries a plain-language ``problem`` for the user (R14.6) and,
    when the failure was a specific field, its path.
    """

    ok: bool
    world_text: str | None = None
    pack: WorldPack | None = None
    problem: str | None = None
    field: str | None = None
    #: Every state path the header's `when` expressions read. Not an error — a
    #: diagnostic, so a typo'd path is visible rather than silently dead.
    referenced_paths: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)


def _as_mapping(header: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Coerce the agent's output to a mapping, insisting on JSON."""
    if isinstance(header, dict):
        return header, None
    if not isinstance(header, str):
        return None, f"expected a JSON object, got {type(header).__name__}"
    text = header.strip()
    # A model often wraps JSON in a fenced block; that is a formatting habit, not
    # a different answer, so it is unwrapped rather than rejected.
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"the compiled header is not valid JSON ({exc.msg} at line {exc.lineno})"
    if not isinstance(parsed, dict):
        return None, f"expected a JSON object, got {type(parsed).__name__}"
    return parsed, None


def _suspicious_paths(paths: list[str]) -> list[str]:
    """Flag paths that look like a near-miss of another path.

    Two paths differing only in their last segment are normal (`state.a.x` /
    `state.a.y`). Two differing only by a near-identical *middle* segment are the
    shape a typo takes, and the cost of missing one is a panel that never appears.
    """
    warnings: list[str] = []
    parts = [p.split(".") for p in paths]
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            if len(a) != len(b) or a == b:
                continue
            diffs = [k for k in range(len(a)) if a[k] != b[k]]
            if len(diffs) != 1:
                continue
            k = diffs[0]
            if k == len(a) - 1:
                continue  # differing leaf is ordinary
            x, y = a[k], b[k]
            if x[:3] == y[:3] or abs(len(x) - len(y)) <= 2:
                warnings.append(
                    f"'{'.'.join(a)}' and '{'.'.join(b)}' differ only at '{x}'/'{y}' "
                    f"— if that is a typo, one of them can never be true"
                )
    return warnings


def accept_compiled_header(
    prose: str,
    header: Any,
    *,
    compiler: str = str(COMPILER_VERSION),
) -> CompileResult:
    """Validate an agent-compiled header and assemble a world file.

    The header is checked by building a real world file and reading it back, so a
    compiled header goes through exactly the same validation as one a person
    typed — it is never held to a lower standard.
    """
    mapping, problem = _as_mapping(header)
    if mapping is None:
        return CompileResult(ok=False, problem=problem)

    if not prose.strip():
        return CompileResult(
            ok=False, problem="there is no rulebook text to compile", field="prose"
        )

    body = dict(mapping)
    # Provenance is stamped here, never taken from the agent: the digest must be
    # of the prose the backend actually holds.
    body["compiledFrom"] = Provenance.for_prose(prose, compiler=compiler).to_dict()
    body["contract"] = body.get("contract", CONTRACT)

    text = f"---\n{json.dumps(body, ensure_ascii=False, indent=2)}\n---\n{prose}"

    try:
        pack = read_world(text)
    except TemplateError as exc:
        return CompileResult(
            ok=False,
            problem=f"the compiled header is unusable — {exc.field}: {exc.expected}",
            field=exc.field,
        )
    except WorldError as exc:
        return CompileResult(ok=False, problem=str(exc))

    paths: list[str] = []
    for panel in pack.template.panels:
        if panel.when is not None:
            paths.extend(panel.when.referenced_paths())
    for ending in pack.template.endings:
        paths.extend(ending.when.referenced_paths())
    panel_paths = set(paths)
    for chapter in pack.template.chapters:
        if chapter.when is not None:
            paths.extend(chapter.when.referenced_paths())
    paths = sorted(set(paths))

    return CompileResult(
        ok=True,
        world_text=serialize_world(pack),
        pack=pack,
        referenced_paths=paths,
        warnings=_suspicious_paths(paths) + _chapter_warnings(pack, panel_paths),
    )


def _chapter_warnings(pack: WorldPack, panel_paths: set[str]) -> list[str]:
    """Two things about a chapter split that only the app can measure.

    Reported rather than refused. A pack whose author briefs the whole book is
    wasteful, not broken, and refusing it would make chapters a hurdle instead of an
    improvement — a compiler that cannot get its split accepted will stop declaring
    one at all.
    """
    template = pack.template
    if not template.chapters:
        return []

    out: list[str] = []
    texts = bodies(template)
    whole = len(template.prose.strip()) or 1
    briefed = len(brief(template))
    share = briefed * 100 // whole
    if share > BRIEF_SHARE_WARN:
        out.append(
            f"the opening brief is {share}% of the rulebook ({briefed} of {whole} "
            "characters) — declaring chapters saves nothing until the parts an "
            "ordinary life never touches are left unmarked"
        )

    # A gate on a flag no panel and no ending ever mentions is a chapter nobody can
    # open. It is not a syntax error and the pack plays; the material is simply
    # unreachable for every life, which is invisible until someone goes looking.
    for chapter in template.chapters:
        if chapter.when is None:
            continue
        named = set(chapter.when.referenced_paths())
        if named and not (named & panel_paths):
            out.append(
                f"chapter {chapter.id!r} opens on {chapter.when.source!r}, and nothing "
                "else in this world ever sets those — gate chapters on the same flags "
                "the panels use, or the chapter can never be read"
            )

    empty = [c.id for c in template.chapters if not texts.get(c.id, "").strip()]
    if empty:
        out.append(
            "these chapters resolve to no text at all: " + ", ".join(sorted(empty))
        )
    return out


#: Above this share of the rulebook, an "opening brief" is not a brief. Warned about,
#: never refused: it is a judgement about the pack author's choices, and the app is
#: not the author.
BRIEF_SHARE_WARN = 55


def preview(pack: WorldPack) -> dict[str, Any]:
    """What the world will contain, for the skippable post-compile view (R14.6).

    Deliberately phrased in the world's own words — panel and field labels as the
    rulebook wrote them — not in the app's vocabulary (R25.2).
    """
    t = pack.template
    return {
        "title": t.title,
        "language": t.language,
        "clock": t.clock_label,
        "lineage": t.lineage,
        "styles": [s.label for s in t.styles],
        # Shown in the world's own headings: which parts the narrator starts with,
        # and which the world holds back until something is true.
        "chapters": [
            {
                "heading": c.heading,
                "brief": c.always,
                "when": c.when.source if c.when is not None else "",
            }
            for c in t.chapters
        ],
        "opening": [g.label for g in t.opening],
        "panels": [
            {
                "label": p.id,
                "always": p.always,
                "fields": [f.label for f in p.fields],
            }
            for p in t.panels
        ],
        "digest": t.digest_categories,
        "endings": len(t.endings),
    }


__all__ = [
    "COMPILER_BRIEF",
    "CompileResult",
    "accept_compiled_header",
    "preview",
]
