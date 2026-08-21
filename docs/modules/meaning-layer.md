# Meaning layer (keepsakes, story cards, star lenses)

The player-meaning half of the memory system: "what matters to me." It cites the
fact graph in [memory-graph.md](memory-graph.md) and never mutates it. Keepsakes
are immutable references to facts a player chose to keep; story cards are
shareable, anonymisable exports built from a keepsake's cited facts; and the star
map renders one sparse, disclosure-filtered payload through three lenses. Every
surface here is derived from facts and can only *narrow* what a fact already
authorised — meaning can forget, relabel, and reorder, but it can never invent a
fact or widen access to a hidden one. Keepsakes and cards live inside the run
directory, so deleting a life leaves no residue.

## Layout

| Path | What it is |
|---|---|
| `backend/keepsakes.py` | `KeepsakeStore` (per-run `runs/<id>/keepsakes.json`) and `KeepsakeError` — immutable cited-fact references |
| `backend/story_cards.py` | `build_draft`, `apply_edits`, `resolve`, the `to_markdown`/`to_html`/`to_svg` exporters, `StoryCardStore`, `StoryCardError` |
| `backend/memory_graph.py` | `star_payload` — the shared sparse subgraph the three lenses render (see [memory-graph.md](memory-graph.md)) |
| `backend/memory_routes.py` | HTTP surface: keepsake create/update/delete, story-card preview/edit/export, star payload, per-life memory-view preference |
| `backend/tests/test_keepsakes.py` | pinning tests for citation immutability, excerpt honesty, corrupt-file tolerance, deletion residue, and the layout-agnostic, disclosure-filtered star payload |
| `backend/tests/test_story_cards.py` | pinning tests for allowlist narrowing, preview==export purity, render-time anonymisation, spoiler gate, export safety |

## Load-bearing contracts — keepsakes

- **The cited path is immutable.** `KeepsakeStore.update()` accepts only
  `title`/`thought`/`spoiler` and never touches `cites`; a keepsake points at one
  fact node, one echo path, or one excerpt for its whole life. Editing the
  citation would turn a memento into a claim — to point at something else, you
  make a new keepsake. Pinned by `test_the_cited_path_is_immutable` (a `cites`
  passed to `update` is silently ignored).

- **An excerpt carries a content hash so it cannot silently drift.** An `excerpt`
  keepsake stores the player's selected prose, its turn, and a `sha256` of that
  text; the create route normalises markdown noise and refuses (422) an excerpt
  not found in that turn's raw prose, so a keepsake can never claim text the page
  can't back. Pinned by `test_an_excerpt_keeps_its_content_hash`.

- **A corrupt file loses meaning, never facts, and never takes the star map
  down.** `KeepsakeStore.list()` swallows read/parse errors and returns `[]`, so
  a damaged meaning file degrades to "no keepsakes" while the fact graph and star
  map keep working. Pinned by
  `test_a_corrupt_file_loses_the_meaning_layer_never_crashes`. Field-named
  refusals (`KeepsakeError` → 422) are pinned by `test_refusals_name_the_field`.

- **Keepsakes live in the run dir, so deletion leaves no residue.** They are
  written under `runs/<run_id>/`, so deleting a life erases them with it — the
  meaning is forgotten, the fact was already gone with the run. Pinned by
  `test_keepsakes_live_inside_the_run_dir_so_deletion_leaves_no_residue`.
  The route also requires every cited event to be a `known` event of this life,
  and nothing on this surface can reach the turn-commit path.

## Load-bearing contracts — story cards

- **The allowlist is fixed at build and only ever narrows.** `build_draft`
  captures the keepsake's cited *known* events (time-ordered, capped) plus the
  entities those events directly involve, and freezes the edges at build time via
  `_edges_within`, so a later graph change cannot grow the card. A hidden event
  cannot be cited in (`test_a_hidden_event_cannot_be_cited_into_a_card`), and the
  card holds exactly the cited events and their entities
  (`test_the_card_holds_exactly_the_cited_events_and_their_entities`).

- **`apply_edits` can narrow, relabel, and reorder — never add.** An event or
  entity id not already on the card is rejected; `order` must be exactly the
  existing ids permuted; turn numbers have no edit path at all (the client sends
  an order of ids, never turn values). Adding must be structurally impossible.
  Pinned by `test_edits_can_narrow_but_never_add` and
  `test_reorder_keeps_turn_numbers_untouched`. Excluding a node takes its edges
  with it (`test_excluding_an_entity_takes_its_edges_with_it`,
  `test_excluding_an_event_takes_its_edges_and_text`).

- **Preview equals export because both are a pure function of the draft.**
  `resolve(card)` is the single resolution point every exporter renders from, so
  the previewed card and the downloaded file are the same computation, not a hope.
  Pinned by `test_the_export_is_a_pure_function_of_the_draft` (same draft →
  identical bytes).

- **Anonymisation at render time reaches every surface, including SVG alt text.**
  `resolve` scrubs renamed and hidden names across titles, summaries, excerpts,
  graph labels, and the SVG `<title>` alt text — including *other* names embedded
  inside an entity's own display, while never self-applying a rename to its own
  display pair; hidden entities render as `□□`. Pinned by
  `test_a_renamed_entity_leaves_no_trace_of_the_real_name` (SVG alt text
  included) and
  `test_anonymisation_reaches_summaries_and_titles_written_by_the_narrator`.

- **Spoiler gate.** With spoilers off, events on or after the ending turn vanish
  from the render. Pinned by
  `test_ending_content_is_filtered_until_spoilers_are_shown`. An `excerpt`
  keepsake replaces that turn's summary in the render
  (`test_an_excerpt_keepsake_replaces_that_turns_summary`).

- **Exports carry no network, no script, no run id, no internal id, and are
  byte-deterministic.** The rendered artifacts contain no `<script>`, no `token`,
  no run id, and no `event-<turn>-` ids; the only permitted URL is the SVG `xmlns`.
  Pinned by `test_exports_carry_no_network_no_script_no_run_or_event_ids`. The
  export filename derives from the card id alone (never title, never run id), and
  `StoryCardStore` validates card ids as `[0-9a-f]{12}` so a traversal id
  resolves to nothing (`test_store_roundtrip_and_bad_ids`).

## Load-bearing contracts — the shared star payload and view preference

- **One sparse payload feeds three lenses; the payload does not know about
  lenses.** `star_payload` returns `{nodes, edges, relations}` — a layout-agnostic
  subgraph the time / relationship / keepsake lenses all render as *layouts*, not
  as separate queries, so switching a lens neither refetches nor changes what is
  visible. It carries no `view` key and two computations are identical. Pinned by
  `test_the_payload_is_layout_agnostic_and_stable`.

- **Disclosure filtering is server-side, so hidden never reaches any surface.**
  Only `known` events enter the payload; relations carry only the `reasonEvent`
  sources that are themselves visible. A hidden event is absent as node, edge,
  and relation — verified by a whole-blob leak scan in
  `test_hidden_events_never_enter_the_star_payload`,
  `test_relations_carry_their_visible_evidence_only`, and
  `test_a_minor_unechoed_event_stays_out_of_the_sparse_view`. A keepsake pulls
  its cited event into the sparse view
  (`test_a_keepsake_pulls_its_cited_event_into_the_view`).

- **The memory-view preference is per-life.** `GET .../memory/star` returns the
  payload plus keepsakes and the life's saved `view` in one request, and
  `set_memory_view` stores the chosen lens as per-life shelf metadata (beside
  `label`/`archived`); switching lives never inherits another life's lens, and
  the preference never touches the fact graph. Enforced by `set_memory_view` in
  `memory_routes.py` (the lens is stored as shelf metadata, never in the run's
  state or chronicle).

- **The legacy bridge is offered only at the ending.** `get_legacy_candidates`
  gates on `_life_over`, which uses the single ending evaluator so a
  world-declared ending still opens the bridge even without a narrator `ended`
  flag; a mid-life request is refused (409), so the bridge cannot become a
  duplication device. Pinned by the tests in `test_legacy.py`.
