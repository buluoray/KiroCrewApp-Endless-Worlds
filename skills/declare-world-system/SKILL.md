---
name: declare-world-system
description: Add a backend-managed mechanic to an Endless Worlds pack using an existing system kind, without changing engine code.
version: 1.0.0
tags: [skill, endless-worlds, game-system, world-pack, systems]
---

# Declare a world system

## When to use

Use this skill when a world needs a tracked mechanic such as experience,
reputation, money, supplies, pressure, or a permanent unlock and one of the existing
system kinds already represents its transition. Do not use it to add a new engine
kind; use `add-game-system-kind` for that.

## Read first

| Contract | Why |
|---|---|
| [`docs/modules/systems.md`](../../docs/modules/systems.md) | current kinds, declaration fields, gain matching, and ownership |
| [`docs/modules/world-schema.md`](../../docs/modules/world-schema.md) | pack schema and the eval-free `when` language |
| [`docs/modules/view-and-packs.md`](../../docs/modules/view-and-packs.md) | how a derived state path becomes a player-facing panel |

## Workflow

1. **Classify the transition before editing the pack.**
   - `accrual`: matching gains accumulate; optional thresholds derive a tier.
   - `resource`: matching signed gains and an optional per-turn drift, clamped.
   - `decay`: per-turn drift only; gains do not affect it.
   - `unlock`: a `when` condition flips a boolean once and never reverts.
   If none fits without distorting the mechanic, stop and use
   `add-game-system-kind`; do not simulate a fifth kind in narrator prose.

2. **Choose one backend-owned target path.** Set `into` to a dotted path rooted at
   `state.`. The matching gain field MUST equal the final path segment: a system
   targeting `state.hero.reputation` consumes gains with `field: reputation`.
   Choose a unique final segment when two mechanics must not share gains.

3. **Declare the system in the world header.** Use a lowercase-hyphen `id`, one
   existing `kind`, and only that kind's fields. For example:

   ```yaml
   systems:
     - id: guild-reputation
       kind: accrual
       into: state.guild.reputation
       floor: 0
       tiers:
         - { at: 0, name: unknown }
         - { at: 25, name: trusted }
       tierInto: state.guild.standing
   ```

4. **Write the fiction-to-gain rule in the world prose.** In the world's own
   language, tell the narrator when an event earns or spends the matching field.
   Tell it to declare the gain, never the running total or `tierInto` value. Keep
   exact arithmetic and state serialization out of prose.

5. **Surface only what the player needs.** Point an existing panel field at the
   derived path, or add a declarative panel/capability pack. Do not add a frontend
   branch for this system id. Add `systems.<id>` or `systems.*` to `handToAgent`
   only when the narrator needs the declaration at the opening turn.

6. **Pin the pack behavior.** Add or update a seed/template test that parses the
   declaration and proves the panel path is reachable. If the engine behavior
   itself needs a new expectation, add a focused case to
   `backend/tests/test_systems.py` without weakening existing ownership tests.

7. **Run the gate from the repository root.** Run
   `python -m pytest backend/tests` and `cd web && npm run build`. Inspect
   `git diff --check` and confirm no engine files changed for an existing-kind
   declaration.

## Guardrails

- The narrator reports events and gains; the backend owns every total and tier.
- A system reads its base from prior committed state. Do not seed future totals in
  narrator instructions to work around that boundary.
- `unlock.when` uses the existing `Condition` grammar. Never add executable
  expressions, calls, indexing, or arithmetic to a pack.
- World-specific labels and rules stay in the world pack, not Python/TypeScript.
- Do not invent a new kind name in content. Unknown kinds are refused by schema.
