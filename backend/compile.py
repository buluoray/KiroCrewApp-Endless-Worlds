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
import re
from dataclasses import dataclass, field as dc_field
from typing import Any

from chapters import bodies, brief
from template import (
    FIELD_PRIMITIVES,
    OPENING_KINDS,
    TemplateError,
    _tokenize,
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
- EVERY `id` anywhere in the header — the world `id` AND every nested id (each
  entry of styles, opening, panels, a panel's fields, endings, chapters, lore,
  systems, roles) —
  MUST be a lowercase slug: only the characters a-z, 0-9 and hyphen. NEVER
  camelCase, snake_case, spaces, or capitals. Write "birth-city", never
  "birthCity" or "birth_city". This is the single most common first-try mistake.
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
  panels      the state surfaces. Each panel needs a stable "id" for state and a
              localized "label" for display. EXACTLY ONE must have "always": true —
              that is the status bar shown at all times. Every other panel needs a
              "when" expression instead. Each field is
              {{ "id", "label", "primitive" }}.
  endings     conditions that finish a life. Each {{ "id", "when" }}.
  milestones  OPTIONAL named achievements — a long-play hook. Each
              {{ "id", "label", "when" }} (the same `when` language as endings and
              panels). Unlike an ending it does NOT finish the life: the first turn
              its `when` becomes true it is "reached", shown to the player, and stays
              reached forever after. Use them for memorable turning points a life can
              hit — came of age, took a title, survived a war, had an heir, mastered
              an art. `label` is player-facing, in the world's language.
  digest      {{ "categories": [...], "rumours": bool }} — the categories the world
              reports each turn about itself, if the prose has a turn-resolution
              section.
  save        the categories a save must carry, if the prose lists them.
  chapters    which parts of the rulebook the narrator is told up front, and which
              the world discloses later. See CHAPTERS below. Optional — a header
              without it means "the whole rulebook, always", which is correct for a
              short world and wasteful for a long one.
  lore        OPTIONAL keyword-triggered setting entries — the lighter companion to
              chapters (a chapter gates on STATE; a lore entry gates on KEYWORDS).
              A list of {{ "id", "keys": [...], "text": ..., "always"?: bool }}. Each
              surfaces to the narrator only when one of its `keys` (a name, place,
              faction, force) appears in the recent months or in the player's action
              — so put a recurring NAMED thing here (a character met once and seen
              again, a city, an order, an artefact, a law) rather than in the
              every-turn brief. `text` is the background to surface, inline, in the
              world's language — it need NOT be in the rulebook prose. `always: true`
              surfaces an entry every turn; use it for a couple of ever-relevant
              facts only. An entry needs at least one key unless it is `always`.
  systems     OPTIONAL mechanics the APP runs for you, so the narrator never does
              arithmetic. Each {{ "id", "kind", "into" }} where kind is one of
              {{accrual, resource, decay, unlock}} and `into` is the `state.…` path the
              system owns. The narrator declares `gains` (a field + an amount) and the
              app applies them:
                accrual  a life earns into `into`; optional
                         "tiers": [{{"at": n, "name": …}}] with "tierInto": state.…
                         derives a named rank (experience -> level).
                resource signed gains into `into`, clamped to "floor"/"cap", with an
                         optional per-turn "perTurn" drift (money, food, troops).
                decay    a per-turn "perTurn" drift toward "floor"/"cap", no gains.
                unlock   sets `into` true, and keeps it true, the turn "when" holds.
              A gain matches a system by the LAST segment of its `into`
              (into: state.hero.xp gets a gain whose field is "xp"). Put every NUMBER
              the world tracks here: the narrator declares what happened, never the
              total, so a duel is deadly in the fiction and the numbers are the app's.
              A declared system is INERT until the narrator feeds it: whenever you
              declare one, ALSO add a short PROSE rule that tells the narrator, in the
              world's own terms, to declare the matching gain (its `field` = the LAST
              segment of `into`) when the fiction earns it, and to NEVER write the
              total or the `tierInto` rank itself — the app derives those.
  roles       OPTIONAL starting archetypes the world offers. Each
              {{ "id", "name", "summary", "grants": {{…}} }}; `grants` is the opening
              state a life of that role begins with. Free-form — any concept the world
              likes; only the id must be a slug.
  handToAgent OPTIONAL references the world hands the narrator at the OPENING turn —
              a list of "lore.<id>", "systems.<id>", "roles.<id>", or "<kind>.*".
              Turn 1 has no prior prose for lore keywords to match against, so name
              here the setting, systems, and roles the narrator needs to open well.

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


#: The playability contract, handed to the worldsmith alongside COMPILER_BRIEF (via
#: the endless_read_draft tool) so the authoritative spec lives here, not in the
#: agent JSON where it would drift. COMPILER_BRIEF works out STRUCTURE from clean
#: prose; this adds the cleaning half — what a pasted rulebook must be reduced to
#: before it can be played in this framework at all.
CLEANING_CONTRACT = """
BEFORE you work out structure, CLEAN the pasted text. It may be a messy paste, and
parts of it may describe things this framework cannot play. Submit the CLEANED prose
(not the raw paste) as `prose`: that cleaned text is kept verbatim and handed to the
narrator, so anything you leave in it is something the narrator will try to honour.

HOW A WORLD IS PLAYED HERE — the ONLY capabilities you may rely on:
- The narrator writes PLAIN PROSE, one span of the clock's unit per turn.
- The app renders the STATE you declare through panels/fields, using ONLY these
  primitives: field, stat, rank, people, trend, resource, inventory, threads.
- The player acts through CHOICES (written in first person) or free text.
- Endings and panel visibility are STATE CONDITIONS in a tiny language: dotted
  `state.…` paths, == != > >= < <=, and/or/not, parens, literals. NO arithmetic,
  NO function calls, NO dice, NO probability expressed as a formula.
- Mood is a background image; the APP draws every piece of UI.

STRIP or REWRITE anything the framework cannot play — never pass it through:
- Any instruction to DRAW or SHOW an interface: ASCII maps, tables, boxes, banners,
  frames, ruled lines, a stat block redrawn as text. The narrator writes prose only
  and the app draws the UI from declared state — remove these demands entirely.
- Exact dice math, formulas, probability tables, hit-point/XP arithmetic: keep the
  FICTION (a duel is deadly) and drop the MATH the framework cannot run.- Real-time or twitch mechanics, second-by-second timers, multiplayer, or anything
  needing input the app does not collect.
- Out-of-world matter: author's notes, licences, changelogs, meta commentary, "as an
  AI" text, or instructions addressed to a game master or a model.
- External references, links, or files.
- Prose that merely RE-STATES what the header already carries as STRUCTURE: a status
  bar or panel drawn as a `【field】` list, the character-creation menu (era/race/
  origin/… as ①②③ options), or the list of styles. Those belong in the declared
  panels, opening groups, and styles — the app renders them and the narrator already
  receives them as its declaration shape, so repeating them as prose is dead weight
  it must wade through every turn. Keep the FICTION about those things (what magic is,
  how a race lives, what an era felt like); drop the bare field/option enumerations.
- The app's own plumbing described as world rules: save/load, version or patch
  mechanisms, a "launch screen", exploit-detection, or "you are an AI / you are not a
  GM" framing. The app owns these; the narrator does not run them.

EXTRACT, don't just strip — mechanics become `systems`, setting becomes `lore`:
- The NUMBERS a world genuinely tracks (experience and levels, gold, reputation,
  food or fuel that drains, a flag that flips once and stays flipped) are not
  something to delete with the dice math. Declare them as `systems` so the app keeps
  the totals and the narrator only declares what happened as `gains`. A world with a
  levelling table becomes an `accrual` system with tiers; rations that dwindle become
  a `resource` or `decay`; "once you awaken magic you always have it" becomes an
  `unlock`. Then the narrator never adds a number and can never inflate one.
- The recurring NAMED people, places, factions, orders, and forces the prose keeps
  returning to become `lore` entries (keyed on the name), and the archetypes a life
  can start as become `roles`. What is left in the prose is the world's principles,
  tone, and the fiction the narrator must honour — not its data tables or its cast
  list restated every turn.
What the narrator sees should be the CORE of the world — its principles, tone,
consequences, and the fiction it must honour — not the data structure restated or the
framework's plumbing.

THE CLEANED PROSE IS THE NARRATOR'S RULEBOOK ALONE — it is NEVER shown to the player.
The player's view of the world is the structured `lore` (a browsable encyclopedia the
app renders on the world page). So descriptive world exposition — history, factions,
how magic or infection works, what a place or era is like — belongs in `lore` entries,
NOT left in the prose as a player-readable "setting" section. Do NOT produce a
player-facing raw-prose settings dump: if a paragraph reads like something a reader
would browse to learn ABOUT the world, move it into `lore`; what stays in the prose is
only what the narrator must HOLD to run the world — first principles, tone,
consequences, the anti-halo / anti-exploit restraints, and the fiction it must honour.
Keep the prose lean: after extraction it should be a short set of core narrative
rules, not an encyclopedia. Keep the world's fiction, tone and consequences intact;
only drop what cannot be PLAYED as prose + declared state + choices + endings. Every
chapter heading you name in the header MUST appear character-for-character in your
cleaned prose.

If, after cleaning, there is no playable world left (the paste was not a world at
all), do NOT invent one: submit an empty header {} with a `dropped` note saying so.

Always pass `dropped`: a short list naming what you removed as unplayable, so the
player sees in the review what was changed.

FROM A THIN IDEA, NOT ONLY A CLEANUP
The pasted text may not be a rulebook at all — it may be a single line: a premise, a
genre, or the name of a novel, film, or game. Treat that as a COMMISSION, not an
error: build a full, playable world from it. Draw on what you know of a named work —
its setting, factions, timeline, and the shape of a life actually lived inside it —
and, if you have web tools (web_search / web_fetch), RESEARCH it so the names, places
and facts are right rather than invented. Do not assert canon you are unsure of as
fact: where you extend or interpret beyond the source, make it a plausible part of
the world rather than a false claim about the real work. Then turn all of it into the
same playable shape — a rulebook prose plus the structured header — and use `lore`
for the recurring named people, places and forces the source is full of. If the idea
is too thin to pin down, choose concrete, coherent specifics yourself and note in
`dropped` what you decided on the player's behalf. What you must never do is refuse a
thin idea, or hand back an empty world when the idea was real but merely brief.
"""


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


#: A ready-made slug: lowercase alnum, hyphen-separated, no leading/trailing hyphen.
_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _slugify(value: str) -> str:
    """Coerce an id-ish string to a lowercase-hyphen slug. `birthCity` → `birth-city`,
    `birth_city` → `birth-city`, `HP Bar` → `hp-bar`. Idempotent on a real slug."""
    s = str(value).strip()
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", s)  # camelCase boundary
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).lower()   # any other run → one hyphen
    return s.strip("-")[:64]


def _declared_ids(header: dict[str, Any]) -> set[str]:
    """Every id the header declares — the world id and each nested one. These are
    the ONLY strings a rename may touch, so a free runtime key a `when` invents is
    never rewritten out from under the narrator."""
    ids: set[str] = set()

    def add(v: Any) -> None:
        if isinstance(v, str) and v.strip():
            ids.add(v.strip())

    add(header.get("id"))
    for key in ("styles", "opening", "endings", "chapters", "lore", "systems", "roles"):
        for item in header.get(key) or []:
            if isinstance(item, dict):
                add(item.get("id"))
    for panel in header.get("panels") or []:
        if isinstance(panel, dict):
            add(panel.get("id"))
            for field in panel.get("fields") or []:
                if isinstance(field, dict):
                    add(field.get("id"))
    return ids


def _rewrite_when(src: str, rename: dict[str, str]) -> str:
    """Rewrite a `when` expression so references to renamed ids follow the rename —
    both as path segments (`state.birthCity` → `state.birth-city`) and as string
    literals (`state.style == "Gentle"` → `... "gentle"`). Only DECLARED ids in the
    rename map are touched; a path segment that is a free runtime key is left as-is.
    Returns the source unchanged if it does not tokenise, so the real error is still
    reported by the validator rather than swallowed here."""
    try:
        toks = _tokenize(src)
    except Exception:  # noqa: BLE001
        return src
    parts: list[str] = []
    for tok in toks:
        if tok.kind == "word":
            segs = [rename.get(s, s) for s in tok.text.split(".")]
            parts.append(".".join(segs))
        elif tok.kind == "str":
            inner = tok.text[1:-1]
            parts.append(f'"{rename[inner]}"' if inner in rename else tok.text)
        else:
            parts.append(tok.text)
    return " ".join(parts)


def _normalize_ids(header: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Slugify every declared id that is not already a slug, and follow the rename
    into every `when`. Returns a normalized deep copy and the {old: new} map (empty
    when nothing needed changing). This is what makes a camelCase id a first-try
    success instead of a reject-and-retry: the gate still validates, but the common
    mistake is fixed before it reaches the gate."""
    rename: dict[str, str] = {}
    for old in _declared_ids(header):
        new = _slugify(old)
        if new and new != old and _SLUG_OK.match(new):
            rename[old] = new
    if not rename:
        return header, {}

    body = json.loads(json.dumps(header))  # deep copy; a header is JSON by contract

    def fix(d: Any) -> None:
        if isinstance(d, dict) and isinstance(d.get("id"), str) and d["id"].strip() in rename:
            d["id"] = rename[d["id"].strip()]

    if isinstance(body.get("id"), str) and body["id"].strip() in rename:
        body["id"] = rename[body["id"].strip()]
    for key in ("styles", "opening", "endings", "chapters", "lore", "systems", "roles"):
        for item in body.get(key) or []:
            fix(item)
    for panel in body.get("panels") or []:
        fix(panel)
        if isinstance(panel, dict):
            for field in panel.get("fields") or []:
                fix(field)
    for group in ("panels", "endings", "chapters"):
        for item in body.get(group) or []:
            if isinstance(item, dict) and isinstance(item.get("when"), str):
                item["when"] = _rewrite_when(item["when"], rename)
    return body, rename


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

    # Fix the most common first-try mistake — a camelCase / snake_case / spaced id —
    # BEFORE the gate, following the rename into every `when` so a reference never
    # dangles. The gate below still validates; this just spares a reject-and-retry.
    mapping, rename = _normalize_ids(mapping)

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

    normalized = [f"normalized id {old!r} → {new!r}" for old, new in sorted(rename.items())]
    return CompileResult(
        ok=True,
        world_text=serialize_world(pack),
        pack=pack,
        referenced_paths=paths,
        warnings=normalized + _suspicious_paths(paths) + _chapter_warnings(pack, panel_paths),
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
    card = pack.raw_header.get("card") if isinstance(pack.raw_header, dict) else None
    promise = ""
    possibilities: list[str] = []
    if isinstance(card, dict):
        if isinstance(card.get("promise"), str):
            promise = card["promise"]
        poss = card.get("possibilities")
        if isinstance(poss, list):
            possibilities = [p for p in poss if isinstance(p, str)][:3]
    return {
        "title": t.title,
        "promise": promise,
        "possibilities": possibilities,
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
                "label": p.label,
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
    "CLEANING_CONTRACT",
    "CompileResult",
    "accept_compiled_header",
    "preview",
]
