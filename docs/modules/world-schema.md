# World schema

A world is a single file. `world.py` owns the on-disk *pack* (a JSON header the
machine manages plus prose the human writes, appended byte-for-byte); `template.py`
owns the *schema* that header parses into (panels, opening groups, endings,
milestones, lore, systems, roles, clock); and `chapters.py` owns how that prose is cut into the
slices a single life is allowed to read. The unifying decision across all three:
a world declares only what the app must render or enforce, the prose is never
parsed for meaning, and every gate the world writes is evaluated by an eval-free
interpreter that cannot execute code from a pack. Shipping a world is copying its
file, so the format has to round-trip losslessly and refuse a pack it is too old
to run before that pack fails mid-play.

## Layout

| Path | What it is |
|---|---|
| `world.py` | pack file format — `read_world`/`serialize_world` round-trip, CONTRACT gate, `is_stale` provenance, widget-spec upsert, `install_seed`, `summarize` |
| `template.py` | header schema — `Template`, `_parse_panels`/`_parse_opening`/`_parse_endings`/`_parse_milestones`/`_parse_lore`/`_parse_systems`/`_parse_roles`/`_parse_handoff`, `_require_version`/`_require_id`, and the `Condition` interpreter |
| `chapters.py` | prose partition — `bodies`, `brief`, `read_chapter`, `contents`, `opened_since` |
| `data/worlds/<worldId>.md` | an installed pack; `<worldId>.<lang>.md` is an optional language variant |
| `seeds/<name>.md` | hand-authored seed packs, normalized into `data/worlds` on install |

## The pack file (`world.py`)

The header is JSON (machine-managed); the prose is everything after it and is
stored verbatim. `serialize_world` round-trips to a fixed point and preserves
unknown header keys (`raw_header` minus `_GENERATED_KEYS`). `summarize` projects
one Library-shelf row (`worldId`, `title`, `version`, `language`, `lineage`,
`clockUnit`, `styles`, `panelCount`, `openingGroups`, card copy, `stale`,
`improvable`).

## Load-bearing contracts

- **Prose survives read/write byte-for-byte, and unknown header keys survive
  too.** The prose is a distribution artifact the author wrote; the app must
  hand it back unchanged, including a leading dashed line that could be mistaken
  for front-matter. Unknown header keys are round-tripped so an older build does
  not silently strip declarations it does not yet understand. Load-bearing
  because any lossy round-trip corrupts the shipping unit itself. Enforced by
  `world.serialize_world`; pinned by
  `test_world.test_prose_survives_read_write_byte_for_byte`,
  `test_world.test_round_trip_is_stable_after_two_passes`,
  `test_world.test_a_prose_starting_with_a_dashed_line_still_round_trips`, and
  `test_world.test_unknown_header_keys_are_preserved_not_dropped`.

- **The CONTRACT gate refuses a too-new pack up front.** A pack declaring
  `compiledFrom.contract` greater than `world.CONTRACT` is refused with
  `ContractTooNew` carrying both numbers, at parse time. Load-bearing because the
  alternative is a pack that loads and then fails deep inside a turn. Enforced by
  `world.read_world`; pinned by
  `test_world.test_a_pack_needing_a_newer_core_is_refused_with_both_versions`.

- **Staleness is provenance-only and never a lockout.** `is_stale()` compares a
  stored `prose_sha256` against the current prose digest; a pack with no
  provenance is not stale (the field can be absent), and the digest is over the
  prose alone, so retitling a world is not "the rulebook moved". A stale world
  still loads fully. Load-bearing because a typo fix in a 200-turn world must not
  lock the player out of it, and because provenance is a hint to the author, not
  a gate on play. Enforced by `world.is_stale`; pinned by
  `test_world.test_editing_the_prose_flips_staleness_but_the_world_still_loads`,
  `test_world.test_a_pack_with_no_provenance_is_not_reported_stale`, and
  `test_world.test_provenance_digest_is_over_the_prose_only`.

- **Widget specs travel; compiled HTML does not.** `upsert_widget_spec` refuses a
  spec that carries `html` — the receiving machine compiles the spec locally.
  Load-bearing because it is the trust boundary between a portable declaration and
  executable markup crossing machines. Enforced by `world.upsert_widget_spec`;
  pinned by `test_world.test_a_widget_spec_carrying_compiled_html_is_refused`.
  Malformed `card` hints degrade to absent rather than removing the world from the
  shelf (`test_world.test_summary_carries_only_clean_emotional_card_copy`).

## The template schema (`template.py`)

One file, front matter (`split_front_matter`) plus verbatim prose. `Template`
carries `id, title, version, clock_unit/label, lineage, styles, opening, panels,
endings, digest_categories/rumours, save_schema, prose, chapters, lore,
systems, roles, hand_to_agent, milestones`.

- **`version` must be a quoted string.** `_require_version` refuses an unquoted
  version. YAML 1.1 turns `1.10` into the float `1.1` — a different version — and
  migration compares the text exactly, so accepting a number would launder data
  loss. This is why compiled headers are emitted as JSON (`yes`→bool, `1:30`→90,
  `language: no`→False are the same trap family). Load-bearing because version
  identity is the key migration keys off. Enforced by `template._require_version`;
  pinned by `test_template.test_an_unquoted_version_is_refused_rather_than_laundered`,
  `test_template.test_a_quoted_version_keeps_its_exact_text`, and
  `test_template.test_a_json_front_matter_header_parses_identically`.

- **Exactly one always-visible panel; a panel is `always` xor `when`.**
  `_parse_panels` requires one panel with `always:true` (the ever-present main
  bar) and forbids a panel that sets both `always` and `when` or neither. Field
  primitives are restricted to `FIELD_PRIMITIVES`; unknown per-field keys are kept
  as primitive `options` rather than dropped. Load-bearing because a UI with zero
  or two "always" bars has no stable anchor, and a silently dropped field key
  loses a world's declaration. Enforced by `template._parse_panels`; pinned by
  `test_template.test_a_panel_declaring_both_always_and_when_is_refused`,
  `test_template.test_panel_extras_are_carried_through_for_the_primitive`, and the
  flagship shape tests
  `test_flagship_template.test_status_panel_is_the_seventeen_field_bar` /
  `test_flagship_template.test_the_five_conditional_panels_match_chapters_148_to_152`.

- **Endings and milestones detect terminal/threshold state without enumerating
  outcomes.** `_parse_endings` takes `id` + `when` and must not name specific
  outcomes (those are narrator-written); a death with a lineage heir is not an
  ending, and a world-level ending needs no death. `_parse_milestones` takes `id`
  + player-facing `label` + `when` (+ optional `spoiler`); a milestone is reached
  the first turn its `when` holds, is permanent and app-owned in `state.milestones`
  (a reserved key), and is rebuilt from prior committed state by
  `mcp_server._apply_milestones` — never from the narrator's declaration, so the
  narrator can neither grant nor revoke one. Load-bearing because ending/milestone
  logic is the app's, not the story's, and must not be forgeable per turn.
  Enforced by `template._parse_endings`/`_parse_milestones` +
  `mcp_server._apply_milestones`; pinned by
  `test_flagship_template.test_endings_detect_terminal_state_without_enumerating_outcomes`,
  `test_flagship_template.test_death_with_an_heir_is_not_an_ending`,
  `test_flagship_template.test_a_world_level_ending_needs_no_death`, and
  `test_template.test_milestones_parse_with_id_label_and_when` (with the
  label/when-required refusals).

- **Lore is inline and keyed; an entry that can never surface is refused.**
  `_parse_lore` takes `id` + inline `text` + case-insensitive `keys` OR
  `always:true`; an entry with neither is refused. Lore gates on keywords, whereas
  chapters gate on state — the two complement rather than overlap. Load-bearing
  because a keyless, non-always lore entry is dead weight that could never appear.
  Enforced by `template._parse_lore`; pinned by
  `test_template.test_lore_parses_keyword_and_always_entries` and
  `test_template.test_a_lore_entry_with_no_keys_and_not_always_is_refused`.

- **A lore entry carries optional structure, and `reveal` is what gates the
  setting view.** Beyond `id`/`text`/`keys`, an entry may declare
  `name`/`summary`/`category`/`relations`/`reveal` — all free-form (the world's own
  vocabulary, never validated against a concept list). `view.world_detail` exposes
  only entries whose `reveal is None` as the player-browsable "world setting", so a
  spoiler entry (one with a `reveal` condition) is injected to the narrator by
  keyword but never listed in the public setting view. Load-bearing because it is
  the single field separating background a player may read up front from a reveal
  the story must earn. Enforced by `template._parse_lore` + `view.world_detail`;
  pinned by `test_template.test_lore_carries_optional_structure_and_reveal`.

- **Systems are the mechanics the backend runs; the narrator declares events, not
  numbers.** `_parse_systems` takes `id` + `kind` (one of `SYSTEM_KINDS` =
  accrual/resource/decay/unlock) + `into` (a dotted `state.…` path the system owns),
  plus per-kind knobs (`tiers`/`tierInto`, `floor`/`cap`/`perTurn`, `when`). An
  unknown kind is refused and an `unlock` without a `when` is refused; two systems
  writing the same `into`, or two gain-fed systems (`GAIN_FED_SYSTEM_KINDS`) whose
  paths end in the same segment, are refused as well — see the gain-identity
  invariant in [systems.md](systems.md) for why a shared segment silently
  double-credits. The world's own concepts (tier names, what a system models) are not
  validated. Load-bearing because it is the boundary that keeps every world number
  the app's rather than the model's. Enforced by `template._parse_systems`; pinned by
  `test_template.test_systems_parse_and_validate_structure`,
  `test_template.test_an_unknown_system_kind_is_refused`,
  `test_template.test_an_unlock_without_a_condition_is_refused`,
  `test_template.test_two_gain_fed_systems_may_not_share_the_last_path_segment`,
  `test_template.test_two_systems_may_not_write_the_same_path`, and
  `test_template.test_absent_systems_is_not_an_error`. Runtime transitions,
  ownership, and extension workflows live in [systems.md](systems.md).

- **Roles are open-vocabulary archetypes; only the slug id is validated.**
  `_parse_roles` takes `id` (a slug) + free-form `name`/`summary`/`grants`; `grants`
  is the opening state a life of that role begins with, and the backend never
  validates what a role *is*. `handToAgent` (`_parse_handoff`) is a list of
  `lore.<id>` / `systems.<id>` / `roles.<id>` / `<kind>.*` references whose *shape*
  is validated while a dangling id is tolerated (a world may name an entry it later
  adds). Load-bearing because open vocabulary is the whole premise — the app
  enforces structure and playability, never the world's concept set. Enforced by
  `template._parse_roles`/`_parse_handoff`; pinned by
  `test_template.test_roles_parse_with_open_vocabulary` and
  `test_template.test_handoff_refs_parse_and_reject_a_bad_shape`.

- **The `when` interpreter cannot execute code and is depth-capped.**
  `Condition.parse` is a recursive-descent parser over a tiny grammar — paths,
  literals, comparisons, `and`/`or`/`not`, parens. There is no call node, no
  subscript node, no attribute node, so a function call from a pack is
  unrepresentable, not merely rejected. Depth is capped at `_MAX_DEPTH` and raises
  `TemplateError`, never a `RecursionError` into the turn loop. Evaluation is
  total: a missing path is `None`, ordering against a missing or incomparable
  value is `False` rather than an exception, so a lookahead trigger merely hides
  its panel. `referenced_paths()` surfaces every dotted path for typo diagnostics.
  Load-bearing because pack content is untrusted input evaluated every turn.
  Enforced by `template.Condition`; pinned by
  `test_template.test_injection_shaped_and_malformed_input_is_refused`,
  `test_template.test_a_path_that_merely_looks_dangerous_is_inert`,
  `test_template.test_deeply_nested_parens_are_refused_not_a_recursion_crash`,
  `test_template.test_a_missing_path_never_raises_and_is_not_satisfied`, and
  `test_template.test_ordering_across_incomparable_types_is_false_not_a_crash`.

## Chapters: cutting the rulebook (`chapters.py`)

A world names its own headings verbatim and the app finds them; a single life is
sent only the slices its state unlocks.

- **The split is declared, never detected.** A chapter carries the exact heading
  text; `chapters` locates it with `str.find`, with no regex and no world-specific
  heading pattern anywhere in the module. A heading not present in the prose is
  refused at read time, not turns later. Load-bearing because a built-in pattern
  would silently work for one world's heading style and fail for another's.
  Enforced by `template._parse_chapters`/`chapters.bodies`; pinned by
  `test_chapters.test_the_app_carries_no_pattern_for_any_worlds_headings` (a
  source scan) and
  `test_chapters.test_a_heading_that_is_not_in_the_prose_is_refused_at_read_time`.

- **No prose is unreachable.** `bodies()` partitions the entire prose in prose
  order — each chapter runs from its heading to the next declared heading, and any
  text above the first heading becomes a synthetic `PREAMBLE`. Declaring a subset
  of a book's headings must not create holes. Load-bearing because unpartitioned
  prose is content the author wrote that no life could ever read. Enforced by
  `chapters.bodies`; pinned by
  `test_chapters.test_every_character_of_the_prose_lands_in_exactly_one_chapter`,
  `test_chapters.test_the_text_above_the_first_declared_heading_is_not_lost`, and
  `test_chapters.test_a_chapter_keeps_its_own_heading`.

- **A closed chapter is refused, not emptied.** A `when`-gated chapter is readable
  only while its condition holds; `read_chapter` refuses it (naming the condition
  that would open it) rather than returning an empty body. An empty body reads as
  "the world has nothing to say here", which makes gated disclosure advisory
  instead of real. Load-bearing because the refusal is what makes the gate an
  actual boundary. Enforced by `chapters.read_chapter`; pinned by
  `test_chapters.test_a_closed_chapter_is_refused_not_emptied`,
  `test_chapters.test_a_refusal_says_what_would_open_it`, and
  `test_chapters.test_a_chapter_opens_when_its_condition_holds`. An ungated
  chapter is readable without being briefed
  (`test_chapters.test_an_ungated_chapter_is_readable_without_being_briefed`).

- **The table of contents is sent once, not every turn.** `contents()` (id,
  heading, brief, available, when) accompanies the brief/full snapshot; delta
  turns receive only `opened_since(before, after)` — chapters newly available —
  and nothing is ever reported as *closing* (that would be the app deciding what
  the narrator remembers). Load-bearing because the TOC is a large fraction of a
  full book, so re-sending it each turn would cost more than the book by a handful
  of turns in. Enforced by `chapters.contents`/`chapters.opened_since` +
  `mcp_server._read_runtime`; pinned by
  `test_chapters.test_the_contents_is_not_sent_every_turn`,
  `test_chapters.test_a_chapter_the_world_just_opened_is_announced`, and
  `test_chapters.test_a_chapter_that_closed_again_is_not_announced`.
