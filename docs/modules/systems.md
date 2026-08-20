# Game-system plugins

The systems engine is the world-as-data mechanics surface. A world pack declares
`systems` in its header; the narrator reports what happened as `gains`, and the
backend computes the resulting values from the prior committed state. These are
"plugins" in the architectural sense, not dynamically imported Python: the set of
kinds is closed in `template.SYSTEM_KINDS`, and every kind is validated, executed,
tested, taught to the world compiler, and documented as one change.

## Layout

| Path | What it is |
|---|---|
| `backend/template.py` | `System`, `SYSTEM_KINDS`, and `_parse_systems`: the declaration schema and per-kind structural validation |
| `backend/systems.py` | `apply_systems` and its numeric/path helpers: the in-place mechanics pass |
| `backend/mcp_server.py` | `_advance_turn` / `_apply_systems`: commit ordering, world lookup, and the prior-state boundary |
| `backend/compile.py` | `COMPILER_BRIEF` and `accept_compiled_header`: teaches the worldsmith the kinds and salvages generated declarations |
| `backend/tests/test_systems.py` | per-kind behavior, gain matching, monotonicity, and backend-ownership tests |
| `backend/tests/test_template.py` | declaration parsing and refusal tests |
| `seeds/*.md` | bundled examples of world-owned `systems` declarations and the prose rules that feed their gains |

## Declaration contract

Every entry has a unique lowercase-hyphen `id`, a `kind`, and an `into` path rooted
at `state.`. `source` currently accepts only `gains`. The optional knobs are
`floor`, `cap`, `perTurn`, `tiers`, `tierInto`, and `when`; `_parse_systems`
validates their structure while leaving the world's concepts and tier names open.
An `unlock` requires `when`, and `tierInto` is another backend-owned `state.` path.
Malformed generated entries are dropped with a compiler warning rather than
poisoning valid siblings.

A gain feeds a system when its `field` equals the final segment of `into`. For
example, `into: state.hero.xp` consumes gains whose field is `xp`. Gain amounts are
strings at the MCP boundary; `_num` accepts a leading signed number so values such
as `"5"`, `"-2"`, and `"5 gold"` have the same numeric meaning. The world prose
must tell the narrator when fiction earns the matching gain, but must not ask it to
maintain the total or derived tier.

The schema boundary is enforced by `template._parse_systems`; it is pinned by
`test_template.test_systems_parse_and_validate_structure`,
`test_template.test_an_unknown_system_kind_is_refused`,
`test_template.test_an_unlock_without_a_condition_is_refused`, and
`test_template.test_absent_systems_is_not_an_error`.

## Current kinds

| Kind | Commit-time transition | Kind-specific fields | Pinning test |
|---|---|---|---|
| `accrual` | prior value + matching gains, then clamp; optionally derive the highest reached tier | `floor`, `cap`, `tiers`, `tierInto` | `test_systems.test_accrual_adds_matched_gains_and_derives_the_tier` |
| `resource` | prior value + matching gains + `perTurn`, then clamp | `floor`, `cap`, `perTurn` | `test_systems.test_resource_consumes_signed_gains_and_clamps_to_floor` |
| `decay` | prior value + `perTurn`, then clamp; gains are ignored | `floor`, `cap`, `perTurn` | `test_systems.test_decay_drifts_each_turn_within_bounds` |
| `unlock` | set true when `when` holds; once true in prior state, remain true | `when` | `test_systems.test_unlock_is_monotonic` |

`systems._tidy` stores integral results as integers and rounds fractional results.
`systems._tier_name` selects the highest threshold not greater than the current
value. Gain isolation is pinned by
`test_systems.test_accrual_ignores_gains_for_other_fields`.

## Commit lifecycle

`mcp_server._advance_turn` validates and salvages the narrator payload, performs
reserved-key carry-forward and merge-forward, stamps the turn, applies milestones,
and then calls `_apply_systems` before the state is committed. `_apply_systems`
loads the run's world variant and delegates to `systems.apply_systems` with both the
new declaration and the prior committed state. The persistence ordering and
full-state replacement are specified in [data-model.md](data-model.md).

Derived paths use the same state that panels and capability packs render. The
rendering half is specified in [view-and-packs.md](view-and-packs.md); it does not
know or branch on system kinds.

## Load-bearing contracts

- **The backend owns every system value.** `apply_systems` reads its base from the
  prior committed state and overwrites the narrator's value in the state about to
  commit. A model cannot inflate experience, resources, tiers, or an unlock by
  echoing a total. Enforced by `mcp_server._advance_turn` +
  `systems.apply_systems`; pinned by
  `test_systems.test_backend_owns_the_value_over_the_narrator_declaration`.

- **Gain matching is structural and local.** `_matched_sum` compares `gain.field`
  with the final segment of `into`; unrelated gains do not bleed across systems.
  Enforced by `systems._matched_sum`; pinned by
  `test_systems.test_accrual_ignores_gains_for_other_fields`.

- **One malformed system never blocks a turn or a valid sibling.**
  `apply_systems` isolates every entry, and `_apply_systems` is an enrichment pass
  inside the commit path. This is fail-soft by design: mechanics may degrade, but
  committed story content remains playable. Enforced by `systems.apply_systems` +
  `mcp_server._apply_systems`; the per-kind behavior is pinned by
  `backend/tests/test_systems.py`.

- **World declarations never execute.** `unlock.when` uses the same eval-free,
  depth-capped `template.Condition` interpreter as panels and endings. A new kind
  must not add callbacks, imports, expressions evaluated by Python, or another
  condition language. Enforced by `template.Condition`; pinned by
  `test_template.test_injection_shaped_and_malformed_input_is_refused` and
  `test_template.test_deeply_nested_parens_are_refused_not_a_recursion_crash`.

- **The registry, runtime, compiler brief, tests, and this spec move together.** A
  kind added only to `SYSTEM_KINDS` parses but is inert if `apply_systems` has no
  branch; a kind omitted from `COMPILER_BRIEF` exists but the worldsmith cannot
  author it. This synchronization is a contributor contract because there is no
  dynamic plugin registry or generated dispatch table.

## Extension workflows

There are two different changes; do not mix them:

1. **Declare a mechanic using an existing kind.** Change the world pack and its
   tests, align the gain field with the target path, expose the derived path through
   existing panels when needed, and leave engine code unchanged. Follow
   [declare-world-system](../../.kiro/skills/declare-world-system/SKILL.md).
2. **Add a new engine kind.** Use this only when none of the current transitions can
   represent the mechanic. Update the registry/schema, runtime branch, compiler
   brief and salvage behavior, behavior/parser tests, bundled examples if any, and
   this spec in the same commit. Follow
   [add-game-system-kind](../../.kiro/skills/add-game-system-kind/SKILL.md).
