# Character creation and the anti-halo instruments

Two modules govern how a life begins and how it stays honest. `opening.py` turns
a player's answers to a world's opening groups into the initial state, validating
everything before it builds anything and refusing to let the player claim a value
the world reserved for itself. `halo.py` is the app's counter-weight to the
protagonist halo: it *measures* a turn — how far events reach, whether gains are
sourced, how dense the drama is — and reports those readings to the narrator, but
it never rewrites narration. The shared decision across both: the app owns the
mechanics that keep a world from bending around the player (world-decided fields,
reach gating, attribution), and the narrator owns the prose; neither reaches into
the other's territory.

## Layout

| Path | What it is |
|---|---|
| `opening.py` | `build_initial_state`, `roll`, `_resolve_style`, `world_rolled_groups`, `compose_opening_prompt` — answers → initial state, and the opening turn's prompt |
| `halo.py` | `gate_digest`, `attribution`, `event_density`, `compose_restraint` — per-turn measurements and the restraint reading handed to the narrator |
| `mcp_server.py` | dispatches the opening turn and applies the halo readings on commit |

## Opening: building the initial state (`opening.py`)

`build_initial_state` validates every answer before constructing state; a
half-validated opening would start a run whose first turn contradicts the
player's own choices.

## Load-bearing contracts

- **A world-decided field is refused from the client, and the UI shows it
  label-only.** A group declared `random:true` is the world's call. If the client
  supplies any non-empty value for it, `build_initial_state` refuses with
  `OpeningError(field="answers.<id>")` rather than accepting it — accepting would
  hand the player the one thing the world reserved (the anti-halo mechanic itself).
  The UI contract is to render such a group with no selector, labelled as decided
  by the world. Load-bearing because a silently accepted value defeats the reserve.
  Enforced by `opening.build_initial_state` + `opening.world_rolled_groups`; pinned
  by `test_opening.test_a_player_supplied_value_for_a_world_rolled_group_is_refused`
  and `test_opening.test_the_flagship_reserves_magic_aptitude_for_the_world`.

- **An unanswered group means "let the world decide", stored, not omitted.** A
  group the player leaves blank is written as `WORLD_DECIDES` (`None`), so the
  narrator can tell "left to me" apart from "this world never asks it". Every group
  the world asks appears in the state. Load-bearing because omission and deferral
  are different instructions to the narrator, and collapsing them loses the
  player's intent. Enforced by `opening.build_initial_state`; pinned by
  `test_opening.test_an_unanswered_group_is_left_to_the_world_not_rejected` and
  `test_opening.test_every_group_the_world_asks_appears_in_the_state`.

- **A pick must be an offered option unless the group allows custom text, and a
  number must be a number.** A `pick` outside the offered options is refused when
  `custom` is off; a custom answer is kept verbatim where allowed; a `number` is
  coerced and `True` is rejected as a number (a bool is an int in Python); answers
  cap at length; an unknown group is named, not ignored. Load-bearing because the
  initial state is the narrator's ground truth, and a smuggled or malformed answer
  corrupts it at turn zero. Enforced by `opening.build_initial_state`; pinned by
  `test_opening.test_a_pick_outside_the_offered_options_is_refused_when_custom_is_off`,
  `test_opening.test_a_custom_answer_is_kept_verbatim_where_the_world_allows_it`,
  `test_opening.test_true_is_not_a_number`, and
  `test_opening.test_an_unknown_group_is_named_not_ignored`.

- **Rolling is not choosing, and a text group is never fabricated.** `roll` rolls
  only groups that have options; a `text` group rolls to `WORLD_DECIDES` — the app
  never invents a name, which is the narrator's job. Load-bearing because a
  fabricated free-text value would be the app writing story. Enforced by
  `opening.roll`; pinned by
  `test_opening.test_a_text_group_cannot_be_rolled_into_a_fabricated_value` and
  `test_opening.test_rolling_is_not_the_same_as_choosing`.

- **The opening prompt names the run and carries a pull instruction only.**
  `compose_opening_prompt` pushes the run id plus an instruction to call
  `endless_read_runtime`; the world's rules and the player's own answers are pulled,
  not pushed, so the player-visible transcript is not a wall of setup, and the
  prompt tells the narrator not to name the settings back to the player. The run id
  must be stated explicitly — the narrator cannot infer the id its every tool call
  must match. Load-bearing because an opening turn whose id the narrator guesses is
  rejected at commit, and a setup dump breaks the narrative surface. Enforced by
  `opening.compose_opening_prompt`; pinned by
  `test_opening.test_the_opening_prompt_carries_no_setup_only_a_pull`,
  `test_opening.test_the_opening_prompt_names_the_run`, and
  `test_opening.test_the_opening_prompt_tells_the_narrator_not_to_name_the_settings`.

- **Style resolves to a real style and a new run always has a turn to retry.**
  `_resolve_style` falls back through the world default to the first style on an
  unknown or blank input; language defaults to the world's; a new run is
  `status:"awaiting-opening"`, `turn:0`, so a failed opening turn leaves something
  to retry. Enforced by `opening._resolve_style`/`build_initial_state`; pinned by
  `test_opening.test_an_unknown_style_falls_back_to_the_worlds_default` and
  `test_opening.test_a_new_run_starts_awaiting_its_opening_turn`.

## Anti-halo: measure, never rewrite (`halo.py`)

The load-bearing property of the whole module is that it never edits the story.
A backend that capped a number or deleted a lucky break would write the story
badly, and the player would feel the seams. What it enforces is only what is a
property of the world, not a judgement about the prose.

- **The module never rewrites narration.** `halo.py` contains no state commit, no
  prose reassignment, and no clamping of narrator values. Load-bearing because the
  moment the app edits prose it becomes a bad co-author the player cannot see.
  Pinned structurally by `test_halo.test_the_app_never_rewrites_narration`, a
  source scan asserting the writing/clamping constructs do not appear in the module.

- **Reach gating marks distant events as rumour and drops nothing.** `gate_digest`
  marks an event beyond the character's `reach` as `rumour:true` even when the
  narrator declared it as fact — reach is a property of where the character stands,
  over the tiers in `REACH_TIERS` (default `local`). Nothing is ever withheld:
  rumour is exactly what travels far, and as reach grows the same event becomes
  reportable. An unknown distance degrades to the default rather than raising.
  Load-bearing because withholding far events would blind the player to the world,
  while presenting them as fact would break the character's vantage point. Enforced
  by `halo.gate_digest`; pinned by
  `test_halo.test_a_distant_event_arrives_as_rumour_even_when_declared_as_fact`,
  `test_halo.test_nothing_the_narrator_wrote_is_ever_dropped`,
  `test_halo.test_reach_grows_and_the_same_event_becomes_reportable`, and
  `test_halo.test_an_unknown_distance_degrades_to_the_default_rather_than_failing`.

- **An unsourced gain is flagged, not refused.** `attribution` surfaces a gain
  with no `source` to the next turn as `unsourced` rather than blocking it — a
  forgotten attribution is still a real turn. It also reports `leaning`: a source
  credited past a repeat threshold within a window, i.e. a reason that has become a
  habit. Load-bearing because refusing an unsourced gain would drop legitimate
  story, while ignoring it would let the world quietly bend toward the player.
  Enforced by `halo.attribution`; pinned by
  `test_halo.test_a_gain_with_no_source_is_flagged_not_refused` and
  `test_halo.test_a_source_credited_over_and_over_becomes_leaning`.

- **Density counts marked events, not prose length.** `event_density` counts the
  events the narrator marked, not how much it wrote, and calls a turn `busy` above
  a per-turn threshold; a quiet turn is not a fault. Load-bearing because inferring
  drama from verbosity rewards padding. Enforced by `halo.event_density`; pinned by
  `test_halo.test_density_counts_what_the_narrator_marked_not_how_much_it_wrote`.

- **The restraint reading says nothing when there is nothing to say, and leaks no
  implementation vocabulary.** `compose_restraint` returns `""` when there is no
  observation, phrases what it does return as an observation rather than an order,
  and never puts words like `state`, `chronicle`, `digest`, `schema`, or `JSON`
  into the prompt. Load-bearing because a constant paragraph of self-criticism
  trains the narrator to skim it, and implementation vocabulary in the prompt leaks
  the machine into the story. Enforced by `halo.compose_restraint`; pinned by
  `test_halo.test_nothing_is_said_when_there_is_nothing_to_say`,
  `test_halo.test_the_reading_is_an_observation_not_an_order`, and
  `test_halo.test_the_reading_never_leaks_implementation_vocabulary`.
