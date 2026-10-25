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
| `backend/turn.py` | the turn loop: `advance_turn()` (dispatch + poll), `compose_prompt()`, `_addressing()`, `turn_notes()`, `declaration_shape()`, `already_committed()`, and the wait / budget / stale constants |
| `backend/opening.py` | `compose_opening_prompt()` — the opening turn's prompt, passed to the same `advance_turn()` via `prompt_override` so the wait and idempotence are not forked |
| `backend/store.py` | the commit + pending record + delta baseline: `mark_pending` / `read_pending` / `clear_pending`, `note_runtime_read`, and `fingerprint()` / `diff()` / `baseline_for()` |
| `backend/mcp_server.py` | `_advance_turn` — the commit gate the narrator calls; enforces read-runtime-first, requires `choices` on a living turn, stamps the turn number itself, and recovers/drops a malformed `memory` rather than failing the call |
| `backend/memory_graph.py` | repairs the structured `memory` block — a mis-spelled id/vocabulary/key is fixed, only an unrepairable piece is dropped and warned, never blocking the commit |
| `content/{en,zh}.json` | every line the prompt and the read's notes are built from (`addressing`, `turn.read`, `turn.action.*`, `opening.new`, `turn.style`/`turn.length.*`/`turn.noart`/`turn.close`, `shape.*`) — see [narrator-and-i18n](narrator-and-i18n.md) |

## Load-bearing contracts

- **Turn start never reuses a slot from another app installation.** Before prompt
  composition, `advance_turn()` compares the generation persisted in `RunStore`
  with the currently loaded app. A missing legacy marker or mismatch validates and
  releases only the app-owned, memory-sealed slot, purges its persisted conversation,
  and creates a replacement; the existing fresh-slot path clears a stale pending
  writer, and the new conversation's first full read hands it the rulebook. The generation marker is written only after the
  replacement exists, so a failed replacement is retried safely. The life remains
  at the same turn with the same state, rollback, chronicle, worlds, and shelf row.
  This is deterministic update/reinstall invalidation, separate from the behavioural
  timeout self-heal below.


- **A narrator that never touched the world is not ours — the slot self-heals.**
  A slot created while agent registration was broken binds a fallback agent, and
  slot reuse never re-resolves the binding, so the poisoning persists across
  every turn and retry. The signature is a dispatched turn whose full BUDGET
  expired with the pending record's `steps` counter still at zero (the MCP
  server stamps every `endless_*` call via `note_tool_call`, and a healthy
  narrator opens every turn with `endless_read_runtime`). `advance_turn` then
  drops the conversation (`release_narrator_slot`), clears the pending record,
  and rebuilds the slot in the same call — the fresh conversation reads the
  rulebook back on its first full read. Capped at one heal per turn
  (`_MAX_SLOT_HEALS_PER_TURN`, per-turn counter in the store) so a fresh slot
  that also fails surfaces as a failure instead of churning a new conversation
  every budget. One endless_* call is proof of the right narrator: slow is
  never healed. Pinned by
  `test_a_zero_contact_expired_turn_drops_the_slot_and_asks_again`,
  `test_a_turn_with_tool_activity_is_never_healed`, and
  `test_the_heal_is_capped_so_a_broken_fresh_slot_cannot_loop`.

- **A conversation is replaced after a pause or after eight turns, once per
  boundary.** Every model call re-sends the conversation so far, and the prompt
  cache that makes that cheap lives minutes while players pause longer (measured:
  55% of gaps over 5 min, 27% over 30). So `_should_rotate()` starts a fresh
  conversation when the gap since the last commit (`RunStore.committed_at`, read
  from that commit's provenance record and trusted only for the committed turn)
  exceeds `IDLE_ROTATION_SECS` (300, reason `idle`), at `ROTATION_MAX_TURNS` (8,
  reason `budget`), or on a chapter boundary (`chapter`); an install change
  (`install`) is checked first. Idle never fires while a live in-flight record
  exists for the next month, because a second ask five minutes after a first one
  that did not rotate would otherwise discard the narrator still writing it; an
  unknown commit time never rotates. Every reason goes through the same seam:
  `mark_rotation(turn=baseline)` before `reset_narrator_conversation` (which
  clears the legacy briefed marker and suppresses the transcript replay), so a retry or
  double tap sees the marker at `baseline` and never rotates twice, and the
  recall-sent record (lore, recall candidates, people cards, held blocks) is
  stamped with the old rotation and reads as empty. The perf ledger records the
  reason; `tools/perf_audit.py` groups turns by it. Pinned by
  `test_a_pause_past_the_threshold_rotates_and_a_short_one_does_not`,
  `test_an_idle_boundary_rotates_exactly_once`,
  `test_idle_never_discards_a_narrator_still_writing_the_month`,
  `test_an_unknown_commit_time_never_rotates_on_idleness`,
  `test_a_commit_time_for_another_month_is_not_trusted`,
  `test_the_budget_caps_a_conversation_at_eight_turns`, and
  `test_the_turn_after_a_pause_starts_fresh_and_forgets_what_was_sent`.

- **A fresh conversation commits a patch, not the whole state.** Its first read
  is full (it holds no `since`), and that read's `fingerprint` names exactly the
  state it sent, so `endless_advance_turn` accepts a `statePatch` with
  `basedOn` = that fingerprint. Measured narrators in that position re-declared
  the full state instead (20-24 KB of output, ~115 s against ~64 s for a
  continued turn), so every full read of a life past its opening carries
  `commitWith` (`read.patch`, naming the
  fingerprint). Pinned by
  `test_the_fresh_narrator_that_follows_the_read_commits_a_patch`,
  `test_a_delta_read_carries_no_commit_note`, and
  `test_an_opening_read_carries_no_commit_note`.

- **The user message is a few lines; MCP supplies everything else.** Three
  layers, each carried once. Stable how-to-narrate rules (what a turn is, the
  first page and its backdrop lane, the page-art recovery procedure, that the
  read's `thisTurn` notes are the app speaking) are in `agents/narrator.json`,
  the cached system prefix of every call. Per-world and per-life material (the
  `brief`, the `shape`, the opening groups, the voice, the state) comes from
  `endless_read_runtime`, once per conversation on the recall-sent record: a
  full read resets that record and always carries the brief and shape; a delta
  read names them in `held` when this conversation already has them, and still
  sends them when the record was emptied (a rotation stamp, or `advance_turn()`
  creating a fresh slot, which resets the record before dispatch). The per-turn message — `compose_prompt()`, and
  `compose_opening_prompt()` for a life's first turn — is the run id and turn
  (`addressing`), a pull (`turn.read` / `opening.new`), and the player's quoted
  action, last. The app's per-turn settings (style, page length, art off, a
  close) are built by `turn_notes()`, written into the in-flight record by
  `mark_pending(notes=)` before dispatch, and returned by the read as
  `thisTurn` (only for the record of the month being asked, once per
  conversation while unchanged). A fresh conversation holds no fingerprint, so
  its first read is full and carries the rulebook before it writes, and a commit
  with no read behind it is refused (`read-runtime-first`, below). Measured on
  the 28 live narrator sessions (232 user messages): a re-brief message was
  median 8.6 KB, max 21 KB (395 KB over 43 messages), and is now median 391 B;
  an opening was median 684 B and is now 247 B; a recovery prompt went from
  458 B to 125 B; an ordinary turn stays about 390 B. Pinned by
  `test_brief.test_no_turn_message_carries_the_rulebook_in_a_fresh_or_kept_conversation`,
  `test_brief.test_a_turn_message_has_no_channel_for_a_rulebook`,
  `test_context_dedupe.test_a_full_read_carries_the_brief_and_shape_and_a_delta_read_does_not`,
  `test_a_fresh_conversation_gets_them_again`,
  `test_a_delta_read_in_a_rotated_conversation_still_gets_them`,
  `test_a_rebuilt_slot_forgets_what_the_old_conversation_was_sent`,
  `test_a_kept_slot_keeps_the_record`,
  `test_a_fresh_slots_message_has_no_brief_and_its_first_read_does`,
  `test_the_turns_notes_reach_the_read_once_and_again_when_they_change`,
  `test_a_record_for_another_month_gives_no_notes`,
  `test_no_amount_of_history_grows_the_prompt`, and
  `test_the_prompt_carries_the_run_the_turn_and_the_players_words_and_nothing_else`.
  Re-adding a rulebook, state or chronicle renderer to the prompt breaks this.

- **The run id is named, and named first.** `_addressing(run_id, turn)` is the
  first line of the prompt, phrased as a directive not to alter the identifier —
  because an exact identifier a tool call requires must be stated, never inferred. Enforced by `_addressing()` / `compose_prompt()`; pinned
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
  read (`test_recent_turns_ride_only_on_a_full_read`). A re-read month is the
  story the narrator wrote (prose, action, choices, events, memory), never the
  page snapshots the chronicle keeps for the reader (`panels`, `digest`, both
  rendered from the state the same full read carries whole). Enforced by
  `mcp_server._narrator_month`; pinned by
  `test_a_full_read_re_reads_months_without_their_page_snapshots`.

- **A full read fits under the harness's 30,000-character tool-result limit.**
  Over that limit the harness spills the result to a file and the narrator sees
  only a preview. Of the 12-month window (`RECENT_TURNS`), only the newest
  `FULL_MONTHS` (4) come whole; each older month is a `short: true` row the app
  builds from the commit (`turn`, `action`, the month's `events`, the first `line`
  of its prose, and `eventIds` to ask `memoryEvents` with). A whole month also
  leaves out each choice's `art` and keeps only the ids and names in its
  `memory`, because the summaries there retell the prose beside them and the
  graph still holds them. If the read is still over `READ_CEILING` (26,000),
  `_fit_recent` drops the oldest short rows first, then shortens the oldest whole
  months to short rows (kept, never dropped), and names both in `recentTrimmed`.
  After that, and only for a life past its opening, the opening hand-off
  (`handToAgent` and its note) is dropped and named as
  `recentTrimmed.handToAgent: "dropped"`: its purpose is turn one, and past it
  its setting surfaces through `lore` and its grants are in the state. The
  newest month, the state, the scenes, the brief and the shape are never cut, so
  a read whose state alone is larger stays over the ceiling. Delta reads carry
  no months and are never trimmed. Measured on the four live lives the default
  full read went from 34.9K / 34.1K / 32.1K / 14.4K characters to 27.6K / 16.3K /
  23.9K / 13.0K. The brief and shape now ride in every full read (largest live
  world: 10.6K characters together); on the five live lives the largest full
  read is 25.1K, the two-month life that was 27.8K before its hand-off was
  dropped. Pinned by `test_a_begun_lifes_full_read_sheds_its_opening_hand_off_to_fit`,
  `test_the_opening_read_keeps_its_hand_off`,
  `test_a_read_under_the_ceiling_keeps_everything`, `test_a_long_lifes_full_read_stays_under_the_ceiling`,
  `test_the_newest_months_keep_their_whole_prose`,
  `test_a_re_read_month_leaves_out_the_choice_art`,
  `test_trimming_drops_the_oldest_summaries_first_and_says_so`,
  `test_once_no_summary_is_left_the_oldest_whole_months_are_shortened`,
  `test_state_and_scenes_are_never_trimmed`, and
  `test_a_delta_read_is_never_trimmed_or_summarised`.

- **A whole block the conversation already holds is named in `held`, not
  re-sent.** On a delta read the world summary and the mounted scenes are left
  out when this conversation was given that exact body (tagged by
  `RunStore.content_tag` in the recall-sent record, so a full read or a rotation
  makes them unsent again, and a changed body is a new tag). The `brief`, the
  `shape` and the `thisTurn` notes ride the same way; no user message carries
  the brief or the shape. Pinned by
  `test_the_world_summary_rides_once_per_conversation`,
  `test_a_rotation_makes_the_world_summary_unsent_again`,
  `test_unchanged_scenes_are_held_and_a_changed_ledger_is_sent`, and
  `test_the_turns_notes_reach_the_read_once_and_again_when_they_change`.

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

- **A narrator run that ends without a month, and without one tool call, ends
  the wait.** The slot survives an agent that was refused at spawn (a sandbox or
  credential failure), so neither slot absence nor the age bound notices it, and
  the birth screen used to cycle its flavour lines for the whole opening budget.
  `make_dispatcher`'s `dispatch(..., on_settled=)` calls back when the run is over,
  however it ended, and `advance_turn` hands it `settle_unanswered`, which stamps
  the pending record `endedAt` only when the month did not land, the record is
  still this ask (same `askedAt`), and `steps` is still zero. A run that reached
  this app's tools is left alone: a runtime that dies mid-prompt can leave its
  tool process writing, and a playtest saw exactly that commit 75s after the run
  ended. `_in_flight` then treats the record as nobody writing, and
  `turn.unanswered()` feeds the play view's `unanswered` field. Enforced by
  `turn.settle_unanswered` and `turn._in_flight`; pinned by
  `test_a_narrator_refused_at_spawn_ends_the_wait`,
  `test_a_run_that_reached_the_tools_is_not_called_unanswered`,
  `test_a_late_settle_never_closes_a_newer_ask` and
  `test_a_new_ask_clears_the_unanswered_mark` (the first two mutation-verified).

- **The pending record is written before the narrator is dispatched.** The
  ordering closes the window between speaking to the narrator and the commit: a
  request that dies in that gap would otherwise be indistinguishable from one
  nobody made, and would let a returning player dispatch a second narrator for the
  same turn. `advance_turn()` calls `mark_pending` before dispatch, checks for an
  in-flight turn, and attaches to it rather than re-dispatching. Pinned by
  `test_the_record_exists_before_the_narrator_is_spoken_to` and
  `test_asking_twice_while_in_flight_does_not_dispatch_twice`.

- **A request is never held for the length of a turn.** `advance_turn()` waits
  `TURN_INLINE_WAIT_SECS` for the commit, not the turn's budget, and a month that
  outruns that wait is handed back as `reason="writing"` with the pending record
  intact — the play view's poll finishes it. Holding the connection until the commit
  instead was correct on loopback and wrong everywhere else: any intermediary
  between the browser and the gateway (an SSO tunnel, a reverse proxy, a load
  balancer, a phone's NAT) drops a connection that has carried no bytes for a
  minute, and a waiting turn carries none — so the server finished the month,
  committed it, cleared the pending record, and answered into a socket nobody held.
  The page then reported that the page had not come through, over a month that was
  on disk, and only remounting the view found it. The two un-advanced reasons are
  NOT interchangeable: `writing` means this request recorded and dispatched the ask
  (the player's words are spent, and re-asking would be the double narration the
  pending record exists to prevent), while `generating` means nothing was taken
  because the app is still finishing the current page. Pinned by
  `test_an_ask_this_request_dispatched_reports_itself_as_taken`,
  `test_asking_twice_while_in_flight_does_not_dispatch_twice`, and
  `test_no_request_is_held_anywhere_near_an_intermediarys_idle_timeout`.

- **A handover neither rolls back nor clears the pending record.** The narrator is
  still writing after the caller stops waiting, so undoing anything would throw away
  a month of a life, and clearing the record would throw away the only evidence the
  month was ever asked for. Pinned by
  `test_a_month_that_outruns_the_wait_is_handed_over_not_rolled_back`; marking a turn
  in flight also does not spend the store's rollback point
  (`test_marking_a_turn_in_flight_does_not_spend_the_rollback_point`).

- **Three bounds, in this order: the request's wait, the turn's budget, the stale
  window.** `TURN_INLINE_WAIT_SECS` is how long ONE request waits before handing the
  turn to the poll. `TURN_DEADLINE_SECS` is the turn's BUDGET — how long a dispatched
  narration is believed to be legitimately running — and every judgement about a turn
  in flight is measured against it, never against the wait: the poisoned-slot
  signature handed the shorter bound reads every ordinary slow month as a narrator
  that never touched the world and drops a live conversation mid-turn.
  `PENDING_STALE_SECS` is the escape hatch that lets an abandoned pending record be
  re-dispatched, and it is deliberately larger than two full budgets so a turn that
  merely overran one request is never mistaken for abandoned — which would dispatch
  the exact duplicate the pending record exists to prevent. The turn and opening
  budgets are equal. Pinned by
  `test_the_deadline_is_the_one_the_player_was_promised`,
  `test_no_request_is_held_anywhere_near_an_intermediarys_idle_timeout`, and
  `test_an_ordinary_slow_month_does_not_lose_its_conversation`; do not copy the
  numbers into prose, the tests own them.

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
  layer (`call_tool` → `_check`), a `memory` sent as a JSON **string** — the
  double-encoding a narrator sometimes emits — is recovered to an object, an
  unrecoverable string is dropped, and a **`null` on an optional field is treated as
  absent** (`"place": null`) while a `null` ENTRY in a list is dropped as a hole —
  rather than the whole call being refused on a type mismatch. `null` on a REQUIRED
  field is still refused: committing a blank page is worse than refusing the call. At
  the semantic layer (`_advance_turn`), `sanitize_memory` REPAIRS the block — a
  namespaced id, a vocabulary synonym, a reused key, a title written only into the
  summary — and drops only what it would have to invent to keep, surfacing that as a
  non-blocking `panel: "memory"` warning while the rest of the block — and the prose,
  choices, and state — still commit, the same "enrichment never blocks a committed
  turn" contract milestones and systems already have. Facts are never back-filled
  from prose. Enforced by `mcp_server.call_tool` + `_check` + `_advance_turn` +
  `memory_graph`; pinned by
  `test_a_bad_reference_is_salvaged_and_the_turn_keeps_the_event`,
  `test_a_null_optional_field_is_absent_not_a_type_error`,
  `test_a_null_entry_in_a_list_is_a_hole_not_a_refusal`,
  `test_a_null_REQUIRED_field_is_still_refused`,
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
  The refusal also teaches the case the gate is hardest on: a character who cannot
  deliberately act (a newborn, an infant, someone asleep or bound) still gets
  choices — what the life leans into, in the player's own voice — because being
  unable to act is not an ending. Without that sentence a live narrator stalled on
  turn 1 reasoning about whether a newborn may be offered choices at all, instead of
  resending the call; the same rule is in the narrator's own prompt so the common
  case never reaches the gate. Pinned by the `"newborn"` detail assert in
  `test_a_living_turn_with_no_choices_is_refused`.

- **A terminal turn stamps `state.ended` at commit.** When the narrator passes
  `ending: true` or the committed state fires a declared world ending,
  `_advance_turn` writes `ended` into the committed state: the narrator's own
  ending id if it wrote one, else the id of the world ending that fired, else
  `true`. Before this, `ending: true` alone committed a choiceless page that
  `resolve_ending` still read as a living life — no ending page, no controls, and a
  turn route willing to narrate past the death — while a world-law ending was over
  for the play view but listed as being lived by every reader keyed on the flag.
  Pinned by `test_life_end.test_an_ending_marker_closes_the_life_for_every_reader`,
  `test_a_world_law_ending_names_itself_on_disk`, `test_a_narrator_ending_id_is_kept`
  and `test_a_living_turn_is_not_stamped`.

- **The player can close a life, and only the app's record carries that ask.**
  `POST /runs/{id}/turn` with `close: true` (a literal `true`; it drops any action
  words) is refused 409 on a life that has had no month yet; otherwise it runs
  the normal `advance_turn` with `close=True`. `store.mark_pending` writes
  `close: true` into the in-flight record before dispatch, together with the
  app's own `turn.close` note asking for an epilogue (from `turn_notes`, never
  the quoted player-words block), which the read returns in `thisTurn`. At commit, `_advance_turn` reads the pending record for
  THIS turn: when it carries `close`, the turn is terminal whatever the narrator
  sent — `retiredByPlayer` is set, choices are dropped, and the ended stamp above
  writes the narrator's ending id, else the fired world ending (the flagship's
  `retired`), else `retired`. Nothing the narrator sends can close a life this way:
  its tool has no such argument, and a close recorded for another turn is ignored.
  Pinned by `test_close_life.test_a_close_asked_by_the_player_ends_the_life_at_commit`,
  `test_without_the_players_close_a_living_turn_stays_alive`,
  `test_the_close_rides_only_in_the_apps_pending_record`,
  `test_a_narrator_ending_id_is_kept_on_a_closing_turn`,
  `test_the_close_note_is_the_apps_line_not_quoted_player_words`,
  `test_advance_turn_records_the_close_before_the_narrator_is_asked`, and
  `test_a_life_that_has_not_begun_cannot_be_closed`.
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
  so the wait and the idempotence live in one place and cannot drift apart. The
  opening prompt takes its language from the world it is quoting, not from a caller
  argument — `compose_opening_prompt()` has no `language` parameter — pinned by
  `test_the_opening_prompt_takes_its_language_from_the_world_not_the_caller`. No
  prompt carries the rulebook or the declaration shape; the opening's first read
  is full and carries both.

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
  The `painting` record carries the committed turn's chronicle `action`, so the
  page keeps quoting what the player asked for through the art wait, the longest
  part of a rich month; pinned (mutation-verified) by
  `test_painting_keeps_quoting_what_the_player_asked_for`.
  Both readers release the page once its exact art exists, even if a request is
  still on disk, and `endless_paint_backdrop` refuses to queue a brief for a page
  that already has its exact art, so a replacement brief racing a late
  illustrator commit cannot re-open a finished page. Enforced by
  `turn.generating` and `mcp_server._paint_backdrop`; pinned by
  `test_a_page_that_already_has_its_art_is_not_reported_painting` and
  `test_paint_backdrop_declines_a_page_that_already_has_its_art`. The sparse
  cadence's replacement exemption does not reopen such a page either; pinned by
  `test_sparse_replacement_brief_is_declined_once_the_page_has_its_art`.

- **The illustrator starts when the brief lands, not when the prose commits.**
  The narrator briefs before `endless_advance_turn`, so the brief exists while the
  turn is still in flight. `turn.brief_in_flight` recognises it (bound to the live
  attempt by `pendingAt`), and the play view's generating poll and the request's
  own inline wait (`advance_turn(on_poll=...)`) both start recovery for it. A new
  narrator attempt for a turn first drops any brief, art, traced underlay,
  reference candidates or unpublished draft an abandoned attempt left for it
  (`turn.forget_unpublished_art`, called just before `mark_pending`).
  The details and their tests live in
  [scenes-and-backdrop.md](scenes-and-backdrop.md); this loop's half is pinned by
  `test_a_new_attempt_drops_the_art_and_brief_its_abandoned_attempt_left` and
  `test_the_inline_wait_runs_its_poll_hook_and_survives_one_that_fails`.

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
