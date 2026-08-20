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
| `backend/mcp_server.py` | `_advance_turn` — the commit gate the narrator calls; enforces read-runtime-first and stamps the turn number itself |
| `backend/memory_graph.py` | validates the structured `memory` block whole, against the same commit |
| `content/{en,zh}.json` | every line the prompt is built from (`turn.pull`, `turn.ask`, `turn.action.*`, `shape.*`, `opening.*`) — see [narrator-and-i18n](narrator-and-i18n.md) |

## Load-bearing contracts

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

- **The structured `memory` block is validated whole, or nothing commits.** A turn
  may declare entities (stable ids reused every appearance), events (each with a
  closed `disclosure`), relations, and `echoes` naming a prior event's canonical
  id — and it is the *declaration*, not the prose, that makes the world's memory of
  an event real. The whole block is validated against the same commit that writes
  the prose: a malformed block commits nothing, a declared echo becomes a
  traceable marker, and prose alone never fabricates one. Enforced by
  `memory_graph`; pinned by `test_malformed_memory_commits_nothing`,
  `test_the_design_example_validates_whole`,
  `test_a_declared_echo_becomes_a_traceable_marker`,
  `test_prose_alone_never_fabricates_a_marker`, and
  `test_a_retried_turn_never_duplicates_nodes_or_edges`; a whole malformed turn
  applies nothing (`test_a_malformed_turn_applies_nothing`).

- **The opening turn reuses the same loop.** `compose_opening_prompt()` builds a
  different prompt but hands it to the same `advance_turn()` via `prompt_override`,
  so the deadline and the idempotence live in one place and cannot drift apart. The
  opening prompt takes its language from the world it is quoting, not from a caller
  argument — `compose_opening_prompt()` has no `language` parameter — pinned by
  `test_the_opening_prompt_takes_its_language_from_the_world_not_the_caller`. The
  briefing state machine sends the rulebook and declaration shape only when the
  slot is fresh or a different slot was last briefed, so turn 2 never re-pushes the
  rulebook.
