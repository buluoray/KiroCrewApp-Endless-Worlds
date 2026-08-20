# Memory graph (world-memory fact layer)

The fact layer of a life: "what happened," authoritative, append-only, per-life.
A turn's structured `memory` delta rides in the *same* chronicle line as its
prose, so facts and story commit or fail together and there is no second log to
drift. `build_index(chronicle)` walks entries in order and derives the whole
graph — entities, events, threads, relations, echo timings — as a disposable,
reconstructable projection; the chronicle is the single source of truth.
Nothing is ever inferred from prose: a turn without a structured `memory` block
contributes zero facts. This module is the fact half of a deliberate split — the
meaning half (keepsakes, story cards, star lenses) is in
[meaning-layer.md](meaning-layer.md), which cites facts and never mutates them.

## Layout

| Path | What it is |
|---|---|
| `backend/memory_graph.py` | the fact graph itself — `build_index`, `event_id`, `validate_memory`, `project_relations`, `recall_candidates`, `echo_markers`, `event_neighbourhood`, `star_payload`, and `MemoryRejected` |
| `backend/memory_routes.py` | the HTTP surface that commits/serves the graph and gates disclosure per life (star payload, echo markers, legacy bridge) |
| `backend/tests/test_memory_graph.py` | the pinning tests for index rebuild, validation, relations, recall, echoes, and the tool surface (no partial write, `(runId,turn)` idempotency, per-life candidate isolation, bounded neighbourhood) |
| `backend/tests/test_full_chain.py` | the one birth-to-inheritance life test that exercises the whole memory-graph chain end to end |
| `MEMORY_GRAPH_DESIGN.md` | the design rationale (§1–§15) these contracts implement |

## Load-bearing contracts

- **The chronicle is the single source of truth; the index is rebuildable and
  byte-stable.** Everything `build_index` produces is derived by an ordered walk
  over order-preserving collections, so two rebuilds are identical and disabling
  every index still reconstructs the same graph. This is what lets the index be
  treated as a cache rather than data. Pinned by
  `test_rebuilding_the_index_is_byte_stable` and
  `test_relation_projection_is_stable_and_keeps_its_sources`.

- **Only structured declarations become facts — never prose.** `build_index`
  skips any entry whose `memory` is not a dict, so reminiscing in narration
  creates no node or edge. Continuity is a thing the world *declares*, not a
  thing a reader infers, which is what makes every fact traceable.

- **Canonical event ids are server-minted.** `event_id(turn, key)` mints
  `event:<turn>:<key>`; the narrator supplies only `key`, unique within its turn.
  Because the id encodes the turn, a `key` collision within one turn is the only
  uniqueness the caller must guarantee (`test_duplicate_event_key_in_one_turn_is_refused`),
  and ids from another run cannot be forged.

- **Whole-block atomic validation — never a half-written turn.**
  `validate_memory(memory, index, *, turn)` validates the *entire* `memory` block
  before anything commits; any failure raises `MemoryRejected(field, expected)`
  with an exact path (e.g. `memory.events[0].echoes[1]`) and the whole tool call
  fails. Unknown references are refused rather than auto-created
  (`test_unknown_participant_is_refused_by_path`); an entity kind never changes
  without an explicit merge (`test_an_entity_kind_never_changes_without_a_merge`),
  and same-name-different-id is never auto-merged
  (`test_same_name_different_id_is_never_merged`); `disclosure` is required and
  closed (`test_disclosure_is_required_and_closed`); a `place` reference must
  resolve to a `place` (`test_a_place_reference_must_actually_be_a_place`). The
  tool surface confirms nothing leaks on failure:
  `test_malformed_memory_commits_nothing` (state turn stays 0, chronicle empty).

- **Append-only and `(runId, turn)` idempotent — a retry never duplicates.**
  Replaying a key for a turn already recorded is refused (`already recorded for
  turn N`); at the tool surface a retried turn returns `committed:false` and the
  rebuilt index still holds exactly one event and one relation. Pinned by
  `test_a_retried_turn_never_duplicates_nodes_or_edges`.

- **Relations are a stable projection that never erases history.**
  `project_relations(index)` folds the ordered change list per `(from, type, to)`:
  `set` establishes, `increase`/`decrease` move a level, `cleared` ends but keeps
  every prior change with its `reasonEvent`. The UI must both show the current
  reading and explain the turns behind it, so the reading opens into its causes.
  Pinned by `test_relation_projection_is_stable_and_keeps_its_sources` and
  `test_cleared_ends_a_relation_but_never_erases_its_history`.

- **Echo recall is deterministic and cooldown-guarded; the system proposes, the
  narrator decides.** `recall_candidates(index, *, turn, action, limit=...)`
  scores old events entirely deterministically (shared entities, name mention in
  the action text, open threads, dormant importance) and caps the result; a
  just-echoed event rests before it can recall again (via `echoedAt`).
  Candidates go to the narrator, so `hidden` events are eligible here —
  continuity is exactly what `hidden` is for; the player-facing filter lives in
  `echo_markers`. Cap and cooldown pinned by
  `test_candidates_never_exceed_the_cap` and
  `test_cooldown_a_just_echoed_event_rests`; recall behavior by
  `test_an_open_thread_is_recalled_and_a_resolved_one_scores_lower`,
  `test_the_player_action_mentioning_a_name_recalls_the_event`,
  `test_too_recent_events_are_not_memories_yet`.

- **An echo references a prior event id, and a marker requires BOTH ends known.**
  An echo edge exists only when a new event names an older canonical id in
  `echoes`; prose alone fabricates nothing
  (`test_prose_alone_never_fabricates_a_marker`). `echo_markers(chronicle)`
  emits a player-facing marker only when *both* the source and the answering
  event are `known` — an echo of something merely `foreshadowed`/`hidden` would
  make the UI explain what the world has not revealed. Disclosure filtering
  pinned by `test_a_declared_echo_becomes_a_traceable_marker`,
  `test_a_source_the_player_has_not_lived_never_surfaces`, and
  `test_a_hidden_current_event_never_surfaces_either`.

- **Life isolation via non-resolving cross-life ids.** An echo target must be a
  canonical id of an event *in this life*, which makes referencing another run
  structurally impossible (another run's ids do not resolve): pinned by
  `test_echo_target_must_be_a_real_event_of_this_life`. Recall is per-run at the
  tool surface too — a second run sharing the store returns no `memoryCandidates`
  (`test_read_runtime_returns_candidates_from_this_life_only`). Follow-up reads
  are bounded: `event_neighbourhood(index, ids)` resolves only the named events
  and their directly involved entities, never the whole graph, and silently omits
  unknown ids (`test_read_runtime_serves_a_bounded_neighbourhood_by_id`).

## Disclosure is enforced server-side

`star_payload(index, keepsakes=None)` admits only `known` events, so a
hidden/foreshadowed event is *absent from the payload* and no client filter can
leak it — the whole-blob leak check in
`test_hidden_events_never_enter_the_star_payload` scans nodes, edges, and
relations. The payload is a sparse, layout-agnostic projection shared by every UI
lens; its selection and lens-free stability are documented with the meaning
layer, since the lenses are player-meaning surfaces. See
[meaning-layer.md](meaning-layer.md).
