# World as data: lore · systems · roles · opening hand-off

> Status: P1–P4 implemented (structured lore and setting view, backend systems, roles and opening `handToAgent`, worldsmith extraction, and both bundled worlds populated).
> Date: 2026-08-20
> Scope: move a world's setting, characters, and mechanics out of prose and into the world pack's data structure; have the backend manage those elements; give the user a structured view of the world's setting.
> Not in scope: visual mockups, arbitrary history branching, validating the world's own concept vocabulary.

## 1. Summary

The cleaning work reached one conclusion: **anything that can live in the data structure should not live in the prose** — panel fields, character-creation options, and styles are already declared structure the narrator receives, so restating them as prose is noise. This design pushes that principle all the way and flips it from "remove duplication" into a positive architecture:

**The world is a body of open-vocabulary data (entities / roles / setting / systems). The narrator only writes prose and declares what happened. The backend runs the systems the world pack declares — computing state, rendering panels, and handing the narrator whichever structures the world pack names, at the moments it names them. The user browses the world's setting as structure.** Validation covers **structure and playability only**, never the world's own concept vocabulary.

Four additions / upgrades — and, deliberately, **no new concepts**: everything below reuses names the schema already has (`lore`, `panels`, `opening`), it only gives them more shape.

1. **`lore` gains structure**: today a lore entry is a flat keyword-triggered prose blob only the narrator sees. It gains optional fields (`name` / `summary` / `category` / `relations` / `reveal`) and serves three consumers — keyword injection to the narrator, opening hand-off, and a user-facing structured view of the setting. Same key, richer shape; the user-facing browser is just "the world's setting", not a new concept.
2. **systems (the "manage" half `packs` lacked)**: the world pack declares mechanics (experience, resources, decay, unlocks) as data; at commit the backend consumes the `gains`/`events` the narrator already declares, computes derived state, and writes it back. The narrator never does arithmetic.
3. **roles + opening.handToAgent**: the world pack declares starting archetypes (any concept) and declares which structures are handed to the narrator at the opening — controlling what the agent receives and when, not just turn 1.
4. **worldsmith emits these on the first cleaning**: extending the CLEANING_CONTRACT, cleaning shifts from "drop the unplayable" to "extract mechanics into a system, setting into lore, and leave only the core narrative rules in prose."

## 2. Confirmed product / architecture decisions

- **One system, not a new one.** `lore` does the setting job — enriched, not renamed. We do not add a parallel "codex" concept; the only question was what to call it, and the answer is: it stays `lore`.
- **Open vocabulary, no concept validation.** A lore entry carries no fixed `category` enum, roles are not typed, and fields beyond a system's own are free. The backend validates only: ids are slugs, `when`/`reveal` parse, a field primitive is in the supported set, and `system.kind` is one the backend runs. A world may declare whatever concepts it likes.
- **The narrator does not compute.** All numeric mechanics belong to backend systems. The narrator declares events and gains (reusing the existing `gains:[{field,amount,source}]` and `events`); the backend accrues / thresholds / decays / unlocks.
- **This relaxes, not tightens, the cleaning contract.** Real mechanics are no longer "fake formulas to strip from prose" — they are "a system the backend runs."
- **Prose is itself a structure.** At compile time the core is extracted from prose into named data blocks (lore / systems / roles + core narrative rules); `opening.handToAgent` decides what is handed over at the opening.
- **Greenfield, no back-compat.** This is a new project; outdated designs are torn out rather than bridged. The `lore` shape is changed in place (new optional fields), tests updated, and the builtin worlds populated with the richer shape — no migration shim.

## 3. Data model (world pack header)

### 3.1 `lore` gains structure
```yaml
lore:
  - id: greywing-keep
    category: place            # free string, not validated; only groups the setting view
    name: Greywing Keep        # display title (defaults to id)
    summary: the last lit fortress on the northern march   # one-line, shown first
    text: <the body / longer setting>                      # required, as today
    relations: [{to: house-ashwood, label: sworn to}]      # optional graph edges
    keys: [Greywing, nightwatch]   # keyword triggers for injection (as today)
    always: false              # injected every turn
    reveal: state.… == true    # optional: hidden from the player until unlocked (spoiler gate)
```
- **What is required stays required**: `id`, `text`, and (unless `always`) at least one key. Everything else is optional enrichment; an entry with only the old fields is still valid.
- **Three consumers**: (1) the narrator receives `name`+`summary`+`text` by keys/always; (2) the opening `handToAgent` names entries to hand over; (3) the setting view (`world_detail` exposes non-`reveal` entries, grouped by `category`, relations drawn with the scene `links` renderer; inside a life, entries reveal as unlocked).

### 3.2 systems
```yaml
systems:
  - id: xp
    kind: accrual              # accrual | resource | decay | unlock
    from: gains                # consumes the narrator's declared gains (matched by field vs into's last segment)
    into: state.hero.xp
    tiers: [{at: 0, name: apprentice}, {at: 100, name: veteran}, {at: 300, name: master}]
    tierInto: state.hero.rank  # backend derives the tier and writes it back
  - id: rations
    kind: resource
    into: state.base.food
    floor: 0                   # lower bound (optional cap = upper bound)
    perTurn: -1                # per-turn drift (sugar for decay)
```
**kind semantics (backend applies at commit, after milestones):**
- `accrual`: add matched `gains.amount` into `into`; with `tiers`, derive the current tier from `into` and write `tierInto` (monotonic, never reverts).
- `resource`: add matched `gains` (signed) into `into`, clamped to `[floor, cap]`.
- `decay`: apply `perTurn` to `into` each turn (clamped to floor/cap).
- `unlock`: when `when` holds, set `into` true (milestones fold into this kind as a special case).
Every state key a system writes is backend-owned (like `state.milestones`): the narrator may read it but not overwrite it; panels and lore `reveal` reference these derived keys directly.

### 3.3 roles (starting archetypes)
```yaml
roles:
  - id: nightwatch
    name: Nightwatch
    summary: keeping a gate that will not open
    grants: {occupation: nightwatch, location: greywing-keep}   # seeds initial state
```
Open vocabulary; when an `opening.groups` entry names roles as its option source, the app renders it structurally and the narrator seeds the initial state from `grants`.

### 3.4 handToAgent (opening hand-off)
`opening` stays a list of character-creation groups; the hand-off is a sibling
top-level key rather than nesting `opening` into a dict (less churn, same intent):
```yaml
handToAgent: [lore.the-cold-omen, lore.greywing-keep, systems.xp, roles.*]
```
At the opening turn (`endless_read_runtime` with baseline=None), alongside the existing brief / shape / opening, the named lore entries (name+summary+text), system overviews, and roles (with their `grants`) are handed over as `out.handToAgent` — **fixing today's gap where turn 1 has no prior prose for keyword injection to match against**. `<kind>.*` takes all of a kind. Absent = nothing extra handed over, preserving current behaviour. A ref that resolves to nothing simply contributes nothing.

## 4. Validation boundary (structure, not concept)

`accept_compiled_header` / `parse_template` validate:
- every id is a lowercase-hyphen slug; `when`/`reveal` use the existing Condition grammar; `system.kind ∈ {accrual,resource,decay,unlock}`; `into`/`tierInto` are `state.…` paths; `from ∈ {gains}` (first version).
- **Not validated**: category values, role concepts, cross-entry semantics, tier names — the vocabulary is entirely the world's.
What cannot be structurally repaired (unknown kind, malformed path) goes to warnings (visible in review), never blocking the load (provenance-style, same as id normalisation).

## 5. Phases

| Phase | Contents | Main files |
|---|---|---|
| **P1** | `lore` gains structure (open vocabulary, no concept validation); `world_detail` exposes lore; a frontend setting view (grouped by category + relations via the scene `links` renderer); narrator injection carries name+summary+text at the opening hand-off, and name+text per turn (summary dropped and the set capped, so the per-turn context stays small) | `template.py` `view.py` `mcp_server.py`(read) + a frontend setting view |
| **P2** | `systems` engine (accrual/resource/decay/unlock), applied at commit to write derived state (milestones fold into unlock); panels show the derived keys automatically | new `systems.py`, `template.py`, `mcp_server.py`(_advance_turn), `compile.py` |
| **P3** | `roles` + `opening.handToAgent`; read_runtime hands over per handToAgent at the opening; the cleaning contract becomes "extract mechanics into a system, setting into lore" | `template.py` `view.py` `mcp_server.py` `compile.py` |
| **P4** | teach the worldsmith to emit lore/systems/roles on the first cleaning; populate both builtin worlds (flagship magic/combat → systems; Last Echoes XP/resources → systems; both worlds' setting → lore) | `agents/worldsmith.json` `compile.py` seeds |

## 6. The loop this closes

The cleaning rule turns from "remove duplication" into "structure first": setting, characters, and mechanics are all keys — the narrator receives structure, the backend computes, the user browses the setting, and the prose keeps only the genuine core of the narrative rules. Shipped behaviour lands in the owning module spec (`world-schema.md` / `view-and-packs.md` / `turn-loop.md` / `frontend.md`); this file is where it was argued, not where its contract lives.
