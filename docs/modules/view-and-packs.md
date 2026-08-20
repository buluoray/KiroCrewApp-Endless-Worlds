# View and capability packs

`view.py` resolves *what the player sees*: `build_play_view` assembles the entire
play-page body from a run's world and state, and every other function in the file
feeds it. `packs.py` is the render half of capability packs — declarative JSON a
world carries that composes existing field primitives into an extra panel. Both
share one hard rule: the app draws every world with the same code paths, so there
is exactly one `when` interpreter and exactly one shaping function, both
server-side, and neither branches on a field id. The reader-facing risk they guard
against is specific: the dashboard renders any thrown app as a single full-page
error card, so a value the UI reads but the backend never sends does not misrender
one panel — it blanks the whole page.

## Layout

| Path | What it is |
|---|---|
| `backend/view.py` | The play-page assembler. `build_play_view` returns the whole body (turn, clock, prose, choices, digest, panels, scenes, style, ended/endingId, reveals, echoes, recap). Owns the primitive shapers and the world-detail/life-row shapes the UI reads |
| `backend/view.py::build_play_view` | Composes the body; decides panel visibility via `panel.visible(state)`; calls `render_pack_panels` to append pack panels after primitive ones |
| `backend/view.py::_shape` | The single primitive shaper — the one function that turns a raw state value into a renderable field, dispatching on `primitive` alone |
| `backend/view.py::_lookup`, `_panel_data` | State readers that accept state keyed by id *or* label and nested *or* flat |
| `backend/view.py::resolve_ending` | The single ending judge; both the play view and the turn route ask it the same question |
| `backend/view.py::strip_terminal_framing` | Strips drawn box frames from narrator prose while preserving markdown structure |
| `backend/view.py::world_detail` | The world-detail response shape (opening, styleRows, endings…) the library/detail UI reads |
| `backend/packs.py` | The capability-pack renderer: turns the packs a world carries plus a run's state into panels, degradation included |
| `backend/packs.py::render_pack_panels` | One guarded panel per pack, in declaration order, shaped by the injected `Shaper` |
| `backend/packs.py::_render_one`, `_degrade`, `_readable` | Compose a pack's fields; fall back to a labelled value list; join only textual leaves |
| `backend/packs.py::resolve_path`, `_walk` | The explicit, `eval`-free dotted/`a[].b` path walker packs use to read state |
| `backend/tests/test_view.py`, `test_view_contract.py`, `test_shape_merge.py`, `test_result_channel.py`, `test_packs.py` | The pinning tests named below |

## Load-bearing contracts

- **One `when` interpreter, server-side.** Panel visibility is decided in the
  backend by `panel.visible(state)`; no `when` key ever reaches the UI. A second
  interpreter (a JS reimplementation in the client) would drift, showing a panel in
  one place and hiding it in the other. `build_play_view` emits resolved
  visibility, not conditions; `test_the_ui_is_never_asked_to_evaluate_a_condition`
  asserts no raw `when` leaks into the response, and `test_every_conditional_panel_can_be_reached`
  exercises the interpreter itself.

- **`resolve_ending` is the single place a life is judged over.** The play view and
  the turn route must never disagree about whether a life has ended, so both call
  `resolve_ending`; a declared `when` beats a bare narrator flag. Pinned by
  `test_a_life_continues_until_an_ending_holds`, `test_a_declared_ending_condition_closes_the_life`,
  and `test_a_declared_ending_wins_over_the_bare_flag`.

- **`_shape` branches on `primitive` and nothing else.** A branch on a field id
  would be the app's first world-specific line and the start of per-world rendering
  code. `test_no_shaping_branches_on_a_field_id` parses `_shape`'s AST, walks every
  comparison, and asserts the set of names compared against string literals is
  exactly `{"primitive"}`, with a non-empty guard so the check cannot silently go
  inert. `test_every_declared_primitive_has_a_shape` pins that every primitive the
  template can declare has a branch.

- **`rank` emits a tier, never a label.** The `rank` shaper deliberately returns the
  computed `tier` and never re-emits a `label` key, because splatting a `label` would
  overwrite the label the world declared. `test_a_rank_keeps_the_label_the_world_gave_it`
  and `test_a_rank_the_narrator_said_nothing_about_shows_no_tier` (in
  `test_shape_merge.py`) pin both directions; `test_no_shaper_can_overwrite_what_the_world_declared`
  generalizes it across primitives.

- **State is read by id *or* label, nested *or* flat.** `_lookup` accepts state
  keyed by a field's id or its label, and `_panel_data` accepts nested or flat
  state, because the narrator is an LLM shown the world's labels and will sometimes
  key by label or flatten a panel — losing a whole panel over a spelling choice is
  worse than tolerating both shapes. `test_a_field_the_narrator_has_not_mentioned_is_a_gap_not_an_error`
  and `test_a_panel_survives_a_missing_value` pin the degradation, not an exception.

- **The cross-file view contract: the UI reads a subset of what the backend sends.**
  A field rename (`openingLabels` → `opening`) once blanked the entire app, because
  nothing tied the properties the TypeScript reads off `world`/`v`/`g`/`run`/`dg`/`f`
  to the keys the backend actually emits, and the dashboard turns the resulting
  `undefined.map` into one full-page error card. `test_view_contract.py` reads the
  TS *source* (not the bundle), regex-extracts every such property read including the
  guarded `(world.x ?? [])` and optional-chained `v?.x` forms, and diffs each read
  set against the real response keys of `world_detail` and `build_play_view` (plus
  the route-overlaid keys and the life-row shape). `test_the_world_bodies_carry_every_field_the_ui_reads`,
  `test_the_play_view_carries_every_field_the_ui_reads`, and
  `test_the_life_list_carries_every_field_the_ui_reads` name the drifted keys on
  failure. The contract runs both directions: `test_every_primitive_the_backend_can_emit_has_a_branch_in_the_ui`
  catches a primitive the UI cannot render, the quiet half of the same drift class.
  `test_the_stale_field_that_caused_the_outage_is_gone` mutation-pins that
  `openingLabels` appears in neither the UI source nor `world_detail`, so the exact
  outage cannot return.

- **`?? []` is the runtime belt to the contract test's suspenders.** Even with the
  contract test green, an unguarded `.map` on an absent server-sent array would cost
  the player everything on screen. `test_a_missing_array_degrades_instead_of_taking_the_page_down`
  scans the UI source for `.map(` on a server-sent array field without a preceding
  `?? []` and fails, so a missing array degrades one element instead of the page.

- **A capability pack is declarative JSON that composes existing primitives into one
  panel.** A pack has no renderer of its own; it names existing primitives and where
  to read them, and `render_pack_panels` shapes the composed values with the *same*
  `_shape` a primitive panel uses, so a pack renders identically to a hand-declared
  panel. `_shape` is injected as the `Shaper` argument rather than imported, so
  `packs.py` has no import cycle with `view.py`. `resolve_path` walks dotted keys and
  the `a[].b` list marker only — explicit and `eval`-free, the same stance the `when`
  interpreter takes toward untrusted template text. `test_a_well_formed_pack_renders_composed_fields_shaped_by_primitive`
  and the `resolve_*` tests pin it.

- **Pack panels are appended after primitive panels, in order.** Integration is a
  single line in `build_play_view`; the play page draws pack panels with no new
  component and no per-world code. `test_build_play_view_appends_pack_panels_after_the_primitive_ones`
  pins the position and `test_no_packs_leaves_the_view_unchanged` pins the no-op case.

- **A bad pack degrades that one panel and never breaks the turn.** Each pack renders
  inside its own `try/except` in `render_pack_panels`; a malformed pack, an unknown
  primitive, an unresolvable path, or a pack declaring a contract newer than this
  build routes to `_degrade` (a labelled list of raw values) and play continues —
  the player is told nothing (R5.9, no implementation leak). The isolation is
  per-pack: `test_one_bad_pack_does_not_take_down_a_good_sibling`. `_degrade` itself
  cannot raise (its inner `resolve_path` is guarded) and `_readable` joins only
  textual leaves so no Python repr leaks. Pinned by
  `test_an_unknown_primitive_degrades_to_a_labelled_value_list`,
  `test_a_pack_declaring_a_newer_contract_degrades`, and
  `test_a_malformed_pack_never_raises_and_degrades`.

- **Declarative-config-only is the pack trust boundary (R21.1).** A pack can only
  recombine existing renderers; there is no `eval`, and no HTML or script is ever
  executed from a pack. Packs are stored per world (round-tripped in the world
  header), while pack *state* is per run. The sibling rule enforcing the boundary
  lives in `world.py`: `WorldPack.upsert_widget_spec` raises if a spec carries
  `html`, because specs travel between players but executable bytes are always
  regenerated locally.

- **`strip_terminal_framing` drops frames, keeps markdown.** It removes drawn box
  framing from narrator prose but preserves markdown structural characters, and the
  scene compiler reuses it so the prose stripper and the scene escaper cannot drift.
  `test_a_line_of_frame_is_dropped` and `test_words_inside_a_frame_survive` pin it.

- **The result channel writes nothing on rejection, and the narrator never holds a
  mount identity.** Player answers arrive through the app-owned `SceneLedger`, not the
  narrator; every rejection (`StaleScene`, `AlreadyAnswered`) asserts both the
  response and that no state was written (R20). The per-mount nonce is never returned
  to the narrator — `test_the_nonce_is_never_handed_to_the_narrator` inspects
  `mcp_server._mount_scene`'s source and asserts the tool result carries only the id,
  because a narrator holding the mount identity could forge an answer to the question
  it just asked. `test_an_answer_aimed_at_a_replaced_scene_is_refused` and
  `test_a_second_answer_never_overwrites_the_first` pin the write-suppression.
