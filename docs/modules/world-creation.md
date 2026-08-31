# World creation

A player turns a pasted rulebook — or a one-line idea — into a playable world. The
pipeline is: raw text or thin idea → clean → compile and validate at a gate → review
→ install. A compiling agent (the worldsmith) does the meaning work: it reads the
draft, strips what this framework cannot play, and emits a structured header. The
backend never trusts that output on faith — `compile.py` holds a gate that runs the
agent's header through the exact validation a hand-written world faces, and `drafts.py`
holds the small, crash-safe state machine that tracks a draft from creation to
install. The two processes (the HTTP route and the worldsmith MCP tool) share files
but never import each other; `drafts.py` is stdlib-only.

## Layout

| Path | What it is |
|---|---|
| `backend/compile.py` | the compile gate — `COMPILER_BRIEF` and `CLEANING_CONTRACT` (instructions to the worldsmith), `accept_compiled_header` (the validation gate), `_normalize_ids`/`_rewrite_when` (id repair), `_suspicious_paths` (near-miss warnings), and `preview` (the player-facing review) |
| `backend/drafts.py` | `DraftStore` — the `new → generating → ready\|failed → installed` lifecycle, id/size validation, atomic record writes, stale self-heal, and the tiny `worldsmith_prompt` |
| `backend/world.py` | `read_world` (the hand-written validation path the gate reuses) and install/provenance stamping |
| `backend/mcp_server.py` | the worldsmith tools (`endless_read_draft`, `endless_submit_world_draft`) that pull a draft and submit a compiled header |
| `backend/tests/test_compile.py` | the gate, brief, id-normalization, and preview contracts |
| `backend/tests/test_pending.py` | the stale-record self-heal bound |
| `backend/tests/test_world.py`, `backend/tests/test_library.py` | provenance stamping and install/staleness contracts the gate depends on |

## Load-bearing contracts

### The brief (`COMPILER_BRIEF`, `CLEANING_CONTRACT`)

- **The brief is a first-class artifact, and its allowed vocabulary is interpolated
  from code.** The worldsmith is an agent making meaning judgements, not a parser, so
  the brief names every allowed field primitive and opening kind by interpolating
  `FIELD_PRIMITIVES` and the kind constants — it cannot drift from what the backend
  accepts. `test_the_brief_names_every_allowed_primitive_and_kind` pins that.

- **JSON, not YAML, and `version` is a quoted string.** The brief mandates JSON
  because unquoted YAML silently corrupts values (`1.10` → `1.1`, `yes`/`off` → bool,
  `1:30` → `90`), and it states the load-bearing prohibitions: exactly one always-on
  panel, and *do not enumerate ending names* (detect the terminal state and let the
  narrator name it). `test_the_brief_states_the_load_bearing_prohibitions` pins the
  presence of those rules. The `when` grammar the brief describes is deliberately tiny
  — dotted paths, comparisons, and `and`/`or`/`not`, no calls — and the gate enforces
  that separately (`test_a_when_expression_with_a_function_call_is_refused`).

- **A lore entry is asked for its reader-facing fields, because the lore list is also
  the player's encyclopedia.** `view.world_detail` falls back to an entry's `id` for
  its heading and buckets a category-less entry under "other", and an `id` is a latin
  slug by contract — so a brief that documented only `id`/`keys`/`text` produced a
  Chinese world whose setting page read `holy-reveal`, `official-orgs`. The brief now
  asks for `name` and `category` (and optionally `summary`) in the world's own
  language and states that consequence, and
  `test_the_brief_asks_for_the_reader_facing_lore_fields` pins their presence.

- **The cleaning contract treats a thin idea as a commission and always reports what
  it dropped.** `CLEANING_CONTRACT` orders the agent to strip or rewrite unplayable
  content (ASCII maps, dice math, real-time or multiplayer rules, external links),
  report every removal in `dropped`, and never refuse a sparse prompt.

### The gate (`accept_compiled_header`)

- **The gate returns a readable result and never raises.** It produces a
  `CompileResult` carrying the problem and the offending field, because the review
  surface needs a reason a player can act on, not a traceback. Non-object output is
  refused with a readable reason (`test_non_object_output_is_refused_with_a_readable_reason`),
  and a fenced code block is unwrapped first (`test_a_fenced_code_block_is_unwrapped`).

- **Provenance is stamped by the backend, never supplied by the agent.** The gate
  overwrites any `compiledFrom` in the submitted body with a provenance computed from
  the actual prose. A compiler that reported a digest of something else could make a
  stale world look fresh. `test_provenance_is_stamped_by_the_backend_not_the_agent`
  feeds a lying digest and asserts it is overwritten.

- **A compiled header is held to the hand-written standard.** The gate assembles a
  real frontmatter-plus-prose document and validates it through `read_world` — the
  same path a human-authored world takes — so a compiled world is never held to a
  lower bar. `test_the_result_round_trips_through_the_world_reader` pins the reuse,
  `test_a_broken_header_is_refused_naming_the_field` pins that a bad field is named,
  and `test_an_invented_primitive_is_refused_rather_than_making_a_dead_panel` pins that
  an unknown primitive is refused rather than becoming a dead panel. The gate also
  reconstructs the real flagship world from its prose alone
  (`test_the_compiler_recovers_the_flagship_structure_from_its_prose_alone`).

- **A near-miss path is warned about, not rejected.** `_suspicious_paths` flags a
  referenced path whose middle segment differs slightly from a declared one
  (`state.magik.awakened` beside `state.magic.awakened`) — the shape a typo takes —
  as a diagnostic, while leaving ordinary siblings alone.
  `test_a_near_miss_path_is_warned_about_not_rejected` and
  `test_ordinary_sibling_paths_do_not_warn` pin both directions.

- **An unnamed lore entry is warned about rather than repaired.** `_flag_unnamed_lore`
  runs on every accepted header and lists the ids of lore entries with no `name`,
  because that is what a reader will see in place of a title. It deliberately invents
  nothing: a slug cannot be turned back into the world's language, so the only honest
  move is to surface the gap in the review where the brief's instruction can be
  repeated. `test_a_lore_entry_with_no_display_name_is_warned_about` and
  `test_a_named_lore_entry_stays_quiet` pin both directions.

- **Ids are auto-normalized, and their `when` references follow.** `_normalize_ids`
  slugifies only *declared* ids (camelCase → hyphen via `_slugify`), then
  `_rewrite_when` rewrites both the dotted path segments and the matching string
  literals inside every `when` so conditions still resolve after the rename; runtime
  keys the narrator invents are left untouched. This makes a camelCase id a first-try
  success instead of a reject-and-retry.
  `test_camelcase_ids_are_normalized_and_when_references_follow` pins that the
  rewritten condition still evaluates and an undeclared reference is left as-is;
  `test_a_header_of_clean_slugs_is_left_untouched` pins that clean input is not churned.

- **The preview speaks the world's own words, not the app's.** `preview` renders the
  review screen in the world's declared labels and leaks no implementation vocabulary.
  `test_preview_speaks_the_worlds_words_not_the_apps` serializes the view and asserts
  none of `primitive`, `schema`, `validation`, `contract`, or `widget` appears.

### The draft lifecycle (`DraftStore`)

- **A draft moves `new → generating → ready | failed → installed`, and the record is
  written before dispatch.** `mark_pending` persists the `generating` state *before*
  the worldsmith is dispatched, so the draft reads as generating instantly rather than
  looking `new` while work is already in flight. `create` validates the id
  (`_DRAFT_ID_RE`) and caps the raw text (`MAX_RAW_BYTES`), and records are written
  atomically.

- **A stale record self-heals to `failed`, whichever way it got stuck.** `_resolve`
  treats a `generating` record older than `STALE_SECS` as `failed`, so a dead gateway
  leaves a retryable draft rather than an eternal spinner; a record stranded at `new`
  past the same bound is judged the same way, because a lost compile dispatch (the
  client navigated away mid-fire, or the chat runtime refused the slot before
  `mark_pending` ran) otherwise leaves the review polling a frozen progress bar
  forever. The judgement is read-side only — the raw record is never rewritten, so a
  retry can still move it to `generating`
  (`test_resolution_never_writes_back`). The bound is set to exceed the
  request deadline; `test_the_staleness_bound_exceeds_the_request_deadline` pins that
  relationship, `test_a_stale_record_does_not_wedge_the_life_forever` pins the
  self-heal for the turn-generation store that shares this pattern, and
  `test_a_draft_stranded_at_new_reads_as_failed_after_the_stale_bound` pins the
  `new`-side clause.

- **The review screen recovers a lost dispatch itself.** On loading a draft still
  `new`, `WorldDraftReview` re-fires the compile once per mount (safe: the route
  short-circuits `generating`/`installed`), and the failed screen carries a
  "try again" button re-dispatching through the same path — so no failure mode
  ends at a screen with nothing to press but "discard".

- **A failed draft carries exactly the two fields the gate emits.** `store_failed`
  records the `problem` and the offending `field` from the `CompileResult`, so the
  retry surface tells the player what to fix. Install goes through `world.py`, which
  stamps provenance server-side (`test_install_stamps_provenance_and_emits_json`) and
  preserves an existing world's provenance and edits on a re-install
  (`test_install_preserves_existing_provenance`,
  `test_an_edited_installed_world_survives_a_newer_seed`).

- **The worldsmith prompt is pull-only.** `worldsmith_prompt` is deliberately tiny: it
  names the draft id and tells the agent to pull the draft itself via
  `endless_read_draft`, rather than pushing the raw text into the prompt.
