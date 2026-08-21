# Turn loop (`turn.py`)

Advancing one turn of a life: the player's action goes in, one committed month
of state and prose comes out. The narrator runs in its own app-owned chat slot
(see [narrator-and-i18n](narrator-and-i18n.md)) and commits through the app's own
MCP server — a *separate process* — so `advance_turn()` does not await a return
value; it dispatches a prompt and then polls the store for the commit. The prompt
is **pull-only**: it carries the run id, the turn number, and the player's quoted
action, and nothing else. Everything the narrator needs to write the turn — world
rules, current state, recent chronicle, the anti-halo restraint reading — it pulls
itself with `endless_read_runtime`. This is what keeps the prompt the same size at
turn 200 as at turn 1.

## Layout

| Path | What it is |
|---|---|
| `backend/turn.py` | the turn loop: `advance_turn()` (dispatch + poll), `compose_prompt()`, `_addressing()`, `declaration_shape()`, `already_committed()`, the briefing state machine, and the deadline / stale constants |
| `backend/opening.py` | `compose_opening_prompt()` — the opening turn's prompt, passed to the same `advance_turn()` via `prompt_override` so the wait and idempotence are not forked |
| `backend/store.py` | the commit + pending record + delta baseline: `mark_pending` / `read_pending` / `clear_pending`, `note_runtime_read`, and `fingerprint()` / `diff()` / `baseline_for()` |
| `backend/mcp_server.py` | `_advance_turn` — the commit gate the narrator calls; enforces read-runtime-first, requires `choices` on a living turn, stamps the turn number itself, and recovers/drops a malformed `memory` rather than failing the call |
| `backend/memory_graph.py` | salvages the structured `memory` block — a bad piece is dropped and warned, the rest recorded, never blocking the commit |
| `content/{en,zh}.json` | every line the prompt is built from (`turn.ask`, `turn.action.*`, `shape.*`, `opening.*`) — see [narrator-and-i18n](narrator-and-i18n.md) |

## Load-bearing contracts


- **A narrator that never touched the world is not ours — the slot self-heals.**
  A slot created while agent registration was broken binds a fallback agent, and
  slot reuse never re-resolves the binding, so the poisoning persists across
  every turn and retry. The signature is a dispatched turn whose full deadline
  expired with the pending record's `steps` counter still at zero (the MCP
  server stamps every `endless_*` call via `note_tool_call`, and a healthy
  narrator opens every turn with `endless_read_runtime`). `advance_turn` then
  drops the conversation (`release_narrator_slot`), clears the pending record,
  and rebuilds the slot in the same call — the fresh slot re-briefs the rulebook
  through the existing `fresh_slot` path. Capped at one heal per turn
  (`_MAX_SLOT_HEALS_PER_TURN`, per-turn counter in the store) so a fresh slot
  that also fails surfaces as a failure instead of churning a new conversation
  every deadline. One endless_* call is proof of the right narrator: slow is
  never healed. Pinned by
  `test_a_zero_contact_expired_turn_drops_the_slot_and_rebriefs`,
  `test_a_turn_with_tool_activity_is_never_healed`, and
  `test_the_heal_is_capped_so_a_broken_fresh_slot_cannot_loop`.

- **The prompt size is independent of life length.** A turn's prompt carries the
  run id, the turn number, the player's action, and — only on the turn that needs
  it — the rulebook; it never carries state or history, because the narrator's
  session is one continuous conversation per life and already holds what it wrote.
  Enforced by `compose_prompt()`; pinned by
  `test_no_amount_of_history_grows_the_prompt` (a 1-turn and a 200-turn life
  differ by a bounded margin the test fixes) and
  `test_the_prompt_carries_the_law_and_the_players_words_and_little_else`.
  Re-adding any state or chronicle renderer to the prompt silently breaks this.

- **The run id is named, and named first.** `_addressing(run_id, turn)` is the
  first line of the prompt, above the rulebook, phrased as a directive not to
  alter the identifier — because an exact identifier a tool call requires must be
  stated, never inferred, and the rulebook is 15,000 characters the narrator would
  otherwise read first. Enforced by `_addressing()` / `compose_prompt()`; pinned
  by `test_the_prompt_names_the_run_the_narrator_is_advancing` and
  `test_the_id_is_marked_as_not_to_be_altered`.

- **The player's free text is placed last, quoted, and labelled as reported
  speech.** The action reaches a model as untrusted input — a prompt-injection
  surface — so `compose_prompt()` appends it last via `turn.action.preamble`
  (labelling it a character's stated intent, not an instruction) wrapped by
  `turn.action.quote`. A line like "ignore every rule above" then reads as
  something a character said. Pinned by
  `test_the_players_own_words_are_quoted_as_intent_not_instruction`, which asserts
  the preamble is present and the prompt ends with the quoted action.

- **Read-runtime-first is enforced on evidence, not on absence.** `_advance_turn`
  refuses a commit (machine reason `read-runtime-first`) unless the store holds a
  `note_runtime_read` for this turn, so the narrator cannot write a month it never
  looked at. A *missing* in-flight record proves nothing and never triggers the
  refusal — refusing on absence would wedge a live life over the app's own
  bookkeeping gap. Pinned by `test_a_commit_without_a_reading_is_refused`,
  `test_the_same_commit_succeeds_once_the_narrator_has_looked`,
  `test_a_missing_record_does_not_refuse`, and
  `test_a_record_for_another_turn_does_not_vouch_for_this_one`; the reason names
  `endless_read_runtime` but no file or module
  (`test_the_refusal_explains_itself_without_leaking_implementation`).

- **The delta baseline is self-certifying.** `endless_read_runtime` with a `since`
  fingerprint returns only what changed, but only while the store can still
  resolve that fingerprint to the state it named — "the rest is unchanged" is safe
  only when the narrator can still see what "the rest" refers to. A fingerprint the
  store no longer holds resolves to a full snapshot, not a promise. Enforced by
  `store.fingerprint()` / `diff()` / `baseline_for()`; pinned by
  `test_a_baseline_the_store_no_longer_holds_resolves_to_nothing`,
  `test_a_narrator_two_turns_behind_gets_no_delta`, and
  `test_the_previous_turns_state_is_resolvable`. The diff is per-panel, unchanged
  panels are named rather than sent, and disappearances are reported
  (`test_the_diff_is_per_panel_not_per_leaf`, `test_unchanged_keys_are_named_not_sent`,
  `test_a_key_that_disappeared_is_reported`); recent chronicle rides only on a full
  read (`test_recent_turns_ride_only_on_a_full_read`).

- **A turn is idempotent per `(runId, turn)`.** `advance_turn()` returns a landed
  turn without asking the narrator again, so a double-tap or a retry over a flaky
  connection cannot produce two versions of one month; the turn number is stamped
  by the server, never trusted from state. Pinned by
  `test_a_committed_turn_is_returned_without_asking_the_narrator`,
  `test_a_double_tap_cannot_produce_two_versions_of_one_month`,
  `test_a_replayed_turn_changes_nothing`, and
  `test_the_turn_number_is_stamped_by_the_server_not_trusted_from_state`.

- **The commit poll requires the wanted turn's own chronicle line, not just the
  counter.** A commit is two writes — `commit_state` bumps `state.turn`, then
  `append_turn` adds the chronicle line — and `_await_commit` can poll into the
  gap between them. The counter alone would hand back `chronicle[-1]`, the
  *previous* month's prose, as if it were this one; requiring the entry whose
  `turn == wanted` makes the poll wait out the gap instead. The writer order is
  deliberately NOT reversed: `already_committed` gates on the counter before
  scanning the chronicle, so a chronicle-first crash would leave a duplicate
  entry a rebuilt memory graph double-counts, while a counter-first crash leaves
  only a prose hole. Pinned (mutation-verified) by
  `test_a_poll_in_the_commit_gap_returns_the_wanted_prose_not_the_previous`.

- **A dead writer's record is recovered without waiting out the age bound.** The
  age test in `_in_flight` exists because slot *presence* proves nothing — a slot
  outlives the turn it was asked for. Slot *absence* is the opposite: an
  in-flight narrator keeps its session busy and the gateway's idle sweep never
  resets a busy session (`reset(skip_if_busy=True)`), so a slot that
  `ensure_narrator_slot_ex` had to re-create (`fresh_slot`) proves the recorded
  writer died between the mark and the commit. `advance_turn` then clears the
  record and re-dispatches instead of wedging the life for `PENDING_STALE_SECS`;
  `generating(store, run_id, state_obj)` applies the same judgement read-only
  (the record is left for the advance path), so the play view and the deletion
  guards stop reporting a corpse as "a month is being written". Both enforcement
  points are pinned and independently mutation-verified:
  `test_a_dead_writers_record_is_recovered_without_waiting_out_the_age_bound` and
  `test_generating_reports_nothing_when_the_recorded_slot_is_gone`
  (+ `test_generating_without_a_state_object_keeps_the_age_only_judgement` for
  callers with no gateway state).

- **The pending record is written before the narrator is dispatched.** The
  ordering closes the window between speaking to the narrator and the commit: a
  request that dies in that gap would otherwise be indistinguishable from one
  nobody made, and would let a returning player dispatch a second narrator for the
  same turn. `advance_turn()` calls `mark_pending` before dispatch, checks for an
  in-flight turn, and attaches to it rather than re-dispatching. Pinned by
  `test_the_record_exists_before_the_narrator_is_spoken_to` and
  `test_asking_twice_while_in_flight_does_not_dispatch_twice`.

- **A timeout neither rolls back nor clears the pending record.** The narrator may
  still commit validly after the caller stops waiting, so undoing anything would
  throw away a month of a life. `advance_turn()` returns a `generating` outcome and
  leaves the pending record in place. Pinned by
  `test_a_silent_narrator_times_out_without_rolling_anything_back`; marking a turn
  in flight also does not spend the store's rollback point
  (`test_marking_a_turn_in_flight_does_not_spend_the_rollback_point`).

- **The stale window is more than twice the turn deadline.** `PENDING_STALE_SECS`
  is the escape hatch that lets an abandoned pending record be re-dispatched, and
  it is deliberately larger than two full turn deadlines so a turn that merely
  overran one request is never mistaken for abandoned — which would dispatch the
  exact duplicate the pending record exists to prevent. The turn and opening
  deadlines are equal. The relationship is pinned by
  `test_the_deadline_is_the_one_the_player_was_promised`; do not copy the numbers
  into prose, the test owns them.

- **Dispatch goes through the background-turn cap, and queued is not failure.** A
  turn is charged against `run_background_turn` rather than awaiting the chat
  runner directly, so the app cannot outrun its own concurrency ceiling; when the
  underlying enqueue reports the slot busy, the turn is queued and still waited
  for, not dropped. Pinned by `test_a_turn_is_charged_against_the_background_turn_cap`,
  `test_the_dispatcher_never_awaits_the_chat_runner_directly`, and
  `test_a_queued_turn_is_still_waited_for`. The outcome carries a machine reason,
  never player-facing text (`test_the_outcome_carries_a_machine_reason_not_player_facing_text`);
  phrasing lives in the content tables.

- **The structured `memory` block is enrichment, and never blocks a turn.** A turn
  may declare entities (stable ids reused every appearance), events (each with a
  closed `disclosure`), relations, and `echoes` naming a prior event's canonical
  id — and it is the *declaration*, not the prose, that makes the world's memory of
  an event real. Memory is validated but NON-BLOCKING at BOTH layers. At the schema
  layer (`call_tool`), a `memory` sent as a JSON **string** — the double-encoding a
  narrator sometimes emits — is recovered to an object, and an unrecoverable string
  is dropped, rather than the whole call being refused on a type mismatch. At the
  semantic layer (`_advance_turn`), `sanitize_memory` SALVAGES the block: a bad piece
  is dropped and surfaced as a non-blocking `panel: "memory"` warning while the rest
  of the block — and the prose, choices, and state — still commit, the same
  "enrichment never blocks a committed turn" contract milestones and systems already
  have. Facts are never back-filled from prose. Enforced by `mcp_server.call_tool` +
  `_advance_turn` + `memory_graph`; pinned by
  `test_a_bad_reference_is_salvaged_and_the_turn_keeps_the_event`,
  `test_memory_sent_as_a_json_string_is_recovered`,
  `test_memory_sent_as_a_non_json_string_is_dropped_not_fatal`,
  `test_the_design_example_survives_whole`,
  `test_a_declared_echo_becomes_a_traceable_marker`,
  `test_prose_alone_never_fabricates_a_marker`, and
  `test_a_retried_turn_never_duplicates_nodes_or_edges`.

- **A living turn MUST offer `choices`; only a terminal turn may omit them.** A
  committed turn with no choices and no ending is a dead page the player cannot act
  on, so it is refused BEFORE anything commits (machine reason `choices-required`)
  unless the turn is terminal: the narrator passes `ending: true`, or the committed
  state fires a declared world ending (`endings[].when`). This is the one place the
  turn contract is strict where memory is lenient — choices are the interaction
  itself, not enrichment. The gate runs only when the world pack loads, so a
  synthetic turn with no world is left alone. Enforced by `_advance_turn`; pinned by
  `test_a_living_turn_with_no_choices_is_refused` and
  `test_a_declared_ending_lets_a_turn_omit_choices`.
 `_clean_choices` salvages before it judges: a caption under a
  plausible alias key (`text`, `title`, `caption`, `name`) is folded onto
  `label`, and a bare string entry IS a caption — the content decides, not the
  key spelling (a live narrator sent `text` captions and looped six identical
  retries on a refusal naming a field it had sent). When entries were sent but
  all cleaned away, the refusal says so and spells the accepted shape instead
  of claiming no choices arrived. Pinned by
  `test_choice_captions_are_salvaged_from_common_alias_keys` and the truthful
  detail assert in
  `test_a_living_turn_left_with_no_usable_choice_is_still_refused`.
- **The opening turn reuses the same loop.** `compose_opening_prompt()` builds a
  different prompt but hands it to the same `advance_turn()` via `prompt_override`,
  so the deadline and the idempotence live in one place and cannot drift apart. The
  opening prompt takes its language from the world it is quoting, not from a caller
  argument — `compose_opening_prompt()` has no `language` parameter — pinned by
  `test_the_opening_prompt_takes_its_language_from_the_world_not_the_caller`. The
  briefing state machine sends the rulebook and declaration shape only when the
  slot is fresh or a different slot was last briefed, so turn 2 never re-pushes the
  rulebook.

- **A requested backdrop is part of the turn's publication boundary.** The narrator
  may commit state, prose, and chronicle before the illustrator finishes, but
  `get_run` continues to build the prior page from `read_prev` and a turn-truncated
  chronicle while the durable backdrop request remains. `generating()` reports the
  ordinary `painting` stage, and `advance_run_turn` refuses another action, so no
  client can observe or advance past the hidden page. Only an exact-turn backdrop
  commit clears the request and publishes prose, panels, choices, and art together.
  Enforced by `routes._backdrop_is_pending` / `routes.get_run` and
  `turn.generating`; pinned by
  `test_requested_art_withholds_the_new_page_until_its_exact_commit` and
  `test_a_committed_page_stays_generating_while_its_requested_art_is_pending`.

- **Illustration failure is recovered behind the normal generation state.** A
  durable request survives the HTTP request and a gateway restart; `get_run`
  re-arms one recovery task per run. Two independent illustrator attempts are
  allowed. If neither commits the exact page, the same narrator slot receives an
  internal repair prompt and may issue a simpler brief or use
  `endless_commit_fallback_backdrop`. That direct tool is independently refused
  unless the persisted failure gate is open for the same run and turn. No agent
  failure or retry copy is exposed to the player. Enforced by
  `routes._recover_backdrop` and `mcp_server._commit_fallback_backdrop`; pinned by
  `test_two_failed_illustrators_notify_the_same_narrator_behind_the_gate` and
  `test_narrator_fallback_commit_is_refused_until_recovery_opens_its_gate`.
