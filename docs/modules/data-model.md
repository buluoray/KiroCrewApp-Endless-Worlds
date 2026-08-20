# Data model (persistence)

The store is the whole of a player's saved history: one *life* (a `runId`) is a
run of turns inside one *world* (a `worldId`), and every durable fact about it
lives on disk under the app's `data/` directory. State and its rollback point go
through `AppStorage` (atomic tmp-and-rename writes, path-traversal rejection);
the per-turn chronicle is a plain append file so a single turn can be appended
without rewriting the whole run. `store.py` is the only module that names these
paths; every other module asks the store rather than touching files. The shapes
below — identity fields, the reserved-key carry-forward, the commit ordering,
the corrupt-versus-absent distinction, and the fingerprint/diff delta protocol —
are the contract that keeps a life readable across a crash, a compaction, and a
deletion.

## Layout

| Path | What it is |
|---|---|
| `store.py` | the persistence surface — id minting/validation, `read_state`/`commit_state`/`rollback`, index rows, fingerprint/diff, pending-turn record, `delete_run`, chronicle append/read |
| `kv/run.<runId>.state.json` | current world state (whole-value `AppStorage` entry, atomic write) |
| `kv/run.<runId>.prev.json` | last-known-good state — the rollback target |
| `kv/index.json` | `{ "runs": [ …Lives-view rows… ] }`, the shelf |
| `kv/briefed-<runId>.json` | `{ slot, at }` rulebook-delivery marker |
| `kv/pending-<runId>.json` | in-flight-turn record (`turn`, `slot`, `askedAt`, `action`, `readAt?`, `readTurn?`, …) |
| `runs/<runId>/chronicle.jsonl` | append-only, one JSON line per committed turn |
| `mcp_server.py` (`_advance_turn`) | applies `RESERVED_STATE_KEYS` carry-forward, then the milestone rebuild and the systems engine, on each commit |

## Identity fields

- **`runId`** — a life. Shape `^[0-9a-f]{32}$` (`uuid4().hex`), minted by
  `store.new_run_id()` and never taken from a request. `store._check_run_id`
  refuses anything else; a malformed id is a caller bug, not user input to
  sanitize. Pinned by `test_store.test_malformed_run_ids_are_refused`.
- **`worldId`** — a world. Equals the template `id`, a lowercase slug
  constrained by `template._require_id` (`_ID_RE`). Pinned by
  `test_template.test_header_errors_name_the_field`.

## State shape

`opening.build_initial_state` produces `{ worldId, turn, style, language,
opening, status }`; a run begins `status:"awaiting-opening"`, `turn:0`. After
each turn the narrator's declaration **replaces** state wholesale, except the
app-owned keys in `RESERVED_STATE_KEYS = (worldId, style, language, opening,
status, milestones)`, which `mcp_server._advance_turn` carries forward.

## Load-bearing contracts

- **Reserved keys carry forward; everything else the narrator omits is gone.**
  A field the narrator stops declaring reads as a fact that stopped being true —
  that is the intended narrative semantics. The six reserved keys are not the
  narrator's to declare, so dropping one (notably `worldId`) would leave a life
  that `get_run` cannot resolve panels for. Load-bearing because the carry-forward
  set is the only thing standing between a terse turn and an unopenable life.
  Enforced by `mcp_server._advance_turn`; the pending record's exclusion from
  the set is pinned by `test_pending.test_the_record_lives_outside_the_state`.

- **Systems compute derived state at commit, and read their base from the PRIOR
  committed state — so the number is the app's, not the narrator's.** After the
  reserved-key carry-forward and the milestone rebuild, `_advance_turn` runs the
  world's declared `systems` (`systems.apply_systems`) against the narrator's
  `gains` for this turn, reading each system's base value from the prior committed
  state and overwriting its `into` path in the state about to be committed. Because
  the base is the last committed value (not the narrator's fresh declaration, which
  could echo or invent one), a system-owned field is the app's regardless of what
  the narrator wrote — the same ownership `state.milestones` has, extended to any
  `state.…` path a system declares. The pass is best-effort: a world with no systems
  is a no-op, and one bad system never blocks the turn. Load-bearing because it is
  what stops a narrator from inflating a level, a purse, or an unlock. Enforced by
  `mcp_server._advance_turn` + `systems.apply_systems`; pinned by
  `test_systems.test_accrual_adds_matched_gains_and_derives_the_tier`,
  `test_systems.test_resource_consumes_signed_gains_and_clamps_to_floor`,
  `test_systems.test_decay_drifts_each_turn_within_bounds`,
  `test_systems.test_unlock_is_monotonic`, and
  `test_systems.test_backend_owns_the_value_over_the_narrator_declaration`.

- **`commit_state` writes `prev` before `state`.** The outgoing state is copied
  to `prev` first, then the new state is written. A crash between the two leaves
  both holding the outgoing state — internally consistent, costing at most the
  in-flight turn. Reversing the order would destroy the rollback point on every
  commit. Load-bearing because it is the single ordering that makes a torn write
  recoverable. Enforced by `store.commit_state`; pinned by
  `test_store.test_crash_between_prev_and_state_leaves_both_consistent`, which
  asserts the `prev` write happens first. `read_prev` is empty before the first
  commit (`test_store.test_read_prev_is_empty_before_a_commit_then_holds_the_outgoing_state`),
  which is how a caller distinguishes a freshly opened life from one open since
  birth.

- **Corrupt and absent are different answers.** `AppStorage.get()` returns `None`
  for both a missing entry and unparseable JSON. `store.read_state` disambiguates
  on `is_file()` and raises `CorruptRunState` for damaged bytes (never rewriting
  the file) versus `StoreError` for a genuinely absent run. Load-bearing because
  conflating them lets a damaged save be mistaken for a new run and silently
  overwritten. Enforced by `store.read_state`; pinned by
  `test_store.test_corrupt_state_is_reported_and_never_rewritten` and
  `test_store.test_absent_run_is_a_plain_error_not_a_corruption_claim`.

- **Index rows separate playing from housekeeping.** `upsert_index` bumps
  `lastPlayed` and promotes the row to the front (recency); `patch_index` merges
  `label`/`archived` without touching `lastPlayed` or the ordering, and returns
  `False` on a missing life so the route answers 404. Load-bearing because a
  rename or archive that reordered the shelf would make the Lives view reshuffle
  on metadata edits. Enforced by `store.upsert_index`/`store.patch_index`; pinned
  by `test_store.test_index_upsert_replaces_and_promotes`,
  `test_store.test_patch_index_merges_metadata_without_reordering`, and
  `test_store.test_patch_index_reports_a_missing_life`.

- **Fingerprint/diff is a self-certifying delta protocol.** `fingerprint(state)`
  is a sha256 over sorted keys, truncated to 16 hex, computed on **state, not
  slot**. A narrator that lost the fingerprint (e.g. after compaction) asks with
  nothing and receives a full snapshot. `baseline_for` resolves a fingerprint
  only against the current and prev states — a narrator further behind than that
  gets `None` and a full snapshot. `diff` is **top-level only**: a per-leaf panel
  diff would hand the narrator a shape it never declared. Load-bearing because it
  lets the delta path fail safe into a full send with zero server-side
  bookkeeping. Enforced by `store.fingerprint`/`store.baseline_for`/`store.diff`.

- **The in-flight record is written before the narrator is dispatched.**
  `mark_pending` runs before `turn.advance_turn` speaks to the narrator, closing
  the window where a dropped request leaves nothing on disk saying a turn is
  being written, and preventing a second narrator from racing for the same
  commit. The record is advisory: it is judged by age
  (`PENDING_STALE_SECS > TURN_DEADLINE_SECS * 2`), by turn number, and is not
  believed without a timestamp. It lives in its own `pending-<runId>` key, so it
  neither spends the rollback point nor is subject to carry-forward. Load-bearing
  because idempotence only protects a *landed* turn; the pre-dispatch write is
  what protects an *in-flight* one. Enforced by `turn.advance_turn` +
  `store.mark_pending`; pinned by
  `test_pending.test_the_record_exists_before_the_narrator_is_spoken_to`,
  `test_pending.test_asking_twice_while_in_flight_does_not_dispatch_twice`,
  `test_pending.test_a_returning_request_attaches_to_the_first_narrators_turn`,
  `test_pending.test_the_staleness_bound_exceeds_the_request_deadline`,
  `test_pending.test_a_record_with_no_timestamp_is_not_believed`, and
  `test_pending.test_marking_a_turn_in_flight_does_not_spend_the_rollback_point`.

- **`delete_run` drops every key a life owns.** State, prev, `briefed-`,
  `pending-`, the index row, and the `runs/<id>/` tree all go. Load-bearing
  because a leaked `pending-` makes `turn.generating` report a turn in flight for
  a life that no longer exists, and a leaked `briefed-` misreports rulebook
  delivery for a reused id. Enforced by `store.delete_run`; pinned by
  `test_store.test_delete_removes_state_index_row_and_chronicle`, with the cascade
  key-sweep pinned by
  `test_delete_life.test_one_life_is_erased_and_its_world_is_untouched`.

- **A torn chronicle line costs only that line.** The chronicle is appended one
  JSON line per turn; `read_chronicle` skips an unparseable trailing line rather
  than failing the whole read. Load-bearing because it bounds the blast radius of
  a crash mid-append to the single turn being written. Enforced by
  `store.append_turn`/`store.read_chronicle`; pinned by
  `test_store.test_a_torn_trailing_line_costs_only_that_line` and
  `test_store.test_chronicle_appends_in_order`.

## Life metadata: rename and archive

Rename (`label`) and archive (`archived`) are metadata patches through
`store.patch_index(runId, {...})`. They do not bump `lastPlayed` or reorder the
shelf, and return `False` (→ 404) on a missing life. The Lives view groups off
the same `archived` flag and index rows. Pinned by
`test_store.test_patch_index_merges_metadata_without_reordering` and
`test_store.test_patch_index_reports_a_missing_life`.
