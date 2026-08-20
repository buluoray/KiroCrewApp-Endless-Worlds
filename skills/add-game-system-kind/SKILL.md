---
name: add-game-system-kind
description: Extend Endless Worlds with a new backend game-system kind across schema, runtime, compiler guidance, tests, and docs.
version: 1.0.0
tags: [skill, endless-worlds, game-system, backend, systems]
---

# Add a game-system kind

## When to use

Use this skill only when `accrual`, `resource`, `decay`, and `unlock` cannot model
the mechanic without moving arithmetic or state ownership into narrator prose. A
new kind is a core engine change, not a world-pack convenience.

## Read first

| Contract | Why |
|---|---|
| [`docs/modules/systems.md`](../../docs/modules/systems.md) | runtime ownership, fail-soft behavior, existing kinds, synchronized touchpoints |
| [`docs/modules/world-schema.md`](../../docs/modules/world-schema.md) | `System` schema and safe `Condition` grammar |
| [`docs/modules/data-model.md`](../../docs/modules/data-model.md) | full-state replacement and commit ordering |
| [`docs/modules/world-creation.md`](../../docs/modules/world-creation.md) | worldsmith compiler brief and salvage boundary |

## Files that move together

| Path | Required change |
|---|---|
| `backend/template.py` | add the literal to `SYSTEM_KINDS`; add typed fields and per-kind validation only when required |
| `backend/systems.py` | add one `apply_systems` branch that reads its base from `prev` and writes through `_set` |
| `backend/compile.py` | teach `COMPILER_BRIEF` the new kind and keep generated-header salvage aligned |
| `backend/tests/test_template.py` | pin accepted shape and required-field refusals |
| `backend/tests/test_systems.py` | pin the transition, ownership, bounds, and failure behavior |
| `backend/tests/test_compile.py` | ensure the compiler brief names every `SYSTEM_KINDS` member and salvage keeps valid siblings |
| `docs/modules/systems.md` | update the current-kind table and any changed invariant in the same commit |
| `seeds/*.md` | add an example only when a bundled world actually needs the kind |

## Workflow

1. **Prove the existing kinds are insufficient.** Write the proposed transition as
   `next = f(prior, matching gains, current state)`. If it is accumulation,
   accumulation plus drift, drift alone, or monotonic condition-to-true, use an
   existing kind instead. Record non-obvious design reasoning under `docs/design/`;
   keep the current-behavior contract in `docs/modules/systems.md`.

2. **Extend the declaration schema first.** Add the kind to `SYSTEM_KINDS`. Add a
   `System` field only when the transition needs data no existing field expresses.
   In `_parse_systems`, validate structure and required fields, not world concepts.
   Reject booleans as numbers and keep state targets rooted at `state.`.

3. **Implement one fail-soft runtime branch.** In `systems.apply_systems`, compute
   from `prev`, not the narrator's fresh declaration. Reuse `_num`, `_get`, `_set`,
   `_clamp`, `_tidy`, `_matched_sum`, and the shared `Condition` interpreter rather
   than creating a second path language or evaluator. Preserve the per-system
   isolation loop so one malformed entry cannot block its siblings or the turn.

4. **Teach world creation the same contract.** Update every hardcoded kind list and
   per-kind explanation in `COMPILER_BRIEF`. Confirm `accept_compiled_header` either
   preserves a valid declaration or drops only the malformed entry with a warning.
   The worldsmith cannot author a kind it was never told about.

5. **Add mutation-resistant tests.** At minimum:
   - parser accepts the valid shape and refuses a missing required field;
   - a runtime test proves the exact transition from prior state;
   - a narrator-supplied total cannot override the backend result;
   - floor/cap, monotonicity, or gain isolation is pinned when applicable;
   - `test_the_brief_names_every_allowed_primitive_and_kind` iterates
     `SYSTEM_KINDS`, so the compiler brief cannot silently drift;
   - adding the registry literal without a runtime behavior test must fail review.

6. **Update the contract and routing in the same commit.** Add the kind to the table
   in `docs/modules/systems.md`, name its enforcing function and pinning test, and
   update any design document that enumerates the closed kind set. Do not copy
   numeric caps into prose; cite the test that pins them.

7. **Run focused validation, then the full gate.** From the repository root run:

   ```bash
   python -m pytest backend/tests/test_systems.py \
     backend/tests/test_template.py backend/tests/test_compile.py -q
   python -m pytest backend/tests
   (cd web && npm run build)
   git diff --check
   ```

   Inspect `git diff origin/main...HEAD` and confirm registry, runtime, compiler,
   tests, and docs are all present before committing.

## Guardrails

- Never let the narrator own a number, tier, unlock, or other app-owned value.
- Never evaluate pack content with `eval`, callbacks, dynamic imports, or code from
  a world file.
- Never branch frontend rendering on a system kind or id; render derived state
  through existing panel primitives.
- Never turn fail-soft enrichment into a turn-blocking exception.
- Never update only `SYSTEM_KINDS`: a parseable but inert kind is worse than a
  refused one.
- Do not commit or push unless the user explicitly asks.
