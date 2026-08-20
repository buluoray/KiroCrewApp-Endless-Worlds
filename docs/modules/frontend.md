# Frontend (`web/src`)

The player-facing SPA, built to `index.mjs` and mounted directly onto the
dashboard document (not an iframe). It renders the shelf of worlds, the
opening/creation forms, and the live reading view of a run, and it drives the
narrator through the app's HTTP surface (`api.ts`). Its structural decisions all
serve one goal: the server is the source of truth for a life, and the UI
survives a page reload, a language switch, or a scene mid-turn without losing —
or fabricating — state. Several backend tests scan the built frontend source to
pin these contracts, because nothing else binds the JS behavior to a Python-side
guarantee.

## Layout

| Path | What it is |
|---|---|
| `main.tsx` | app root — holds `view`, and independently holds selected-world and active-run; language state + persistence; routes a scene answer into a turn |
| `api.ts` | typed HTTP helpers over `/api/apps/endless-worlds`; `ApiError` with a machine code; preconditions as body fields; `models()` field-drift tolerance |
| `play.tsx` | the live reading view — server-driven generating state + poll, tool-call turn progress, retry, turn-number pager |
| `scene.tsx` | `SceneSlot` — the single scene iframe, created once and never moved |
| `opening.tsx` | the opening form — sealed world-decided groups, 30-day draft TTL |
| `create-world.tsx` | the world-creation surfaces, mirroring life creation |
| `rail.tsx` | `WorldRail` — the desktop navigation drawer (> 1100px) |
| `tabbar.tsx` | `WorldTabBar` — the phone tab bar, portaled to `document.body` |
| `library.tsx` | the shelf of worlds and lives |
| `memory.tsx`, `legacy.tsx`, `story-card.tsx`, `memory-state.ts` | the star-map / keepsake / legacy surfaces |
| `strings.ts`, `strings/` | the two language tables |

## Load-bearing contracts

- **Selected-world and active-run are independent state, not one view machine.**
  `main.tsx` keeps `view` alongside separate `selected` (which world is chosen),
  `world` (its detail), and `live` (the open run) — "which world is selected" and
  "what is being read" are different facts, and collapsing them into one
  single-value view state produced rows that both read as current. Opening a world
  clears the open life so two rows never both look active. Pinned by
  `test_rail.py::test_the_rail_marks_exactly_one_row_as_current` and
  `test_opening_a_world_from_the_rail_clears_the_open_life`.

- **Language is root React state, set synchronously, with a dropdown lock that
  beats world-follow.** `lang` lives at the root and is set synchronously (not in
  an effect) so a differently-languaged world re-renders the whole tree already
  speaking it; `t()` reads a module value so no call site needs a hook. An
  explicit dropdown pick sets `langLocked` and persists, and that lock overrides
  the otherwise-automatic follow of a world's own language. The play view reading
  the language without a dead type assertion is pinned by
  `test_rail.py::test_the_play_view_reads_the_language_without_a_type_assertion`,
  and both tables offering the same strings by
  `test_every_string_the_rail_asks_for_exists_in_both_tables`.

- **Navigation is region-driven: desktop rail vs mobile tab bar.** Below 1100px
  the `WorldRail` renders nothing and the phone gets `WorldTabBar`; above it, the
  reverse. Tabs are built from the `region` tag on either a mounted scene or an
  app panel, so a scene and a panel can feed one tab. Pinned by
  `test_rail.py::test_the_rail_is_absent_at_phone_widths` and
  `test_the_rail_only_appears_above_the_desktop_breakpoint`.

- **The tab bar is portaled to `document.body`; the rail opens in flow.**
  `WorldTabBar` is portaled onto `document.body` so it escapes transformed
  ancestors — an iOS WKWebView pins a plain `fixed` bar to the content box rather
  than the viewport. The `WorldRail` drawer opens *in flow*, pushing the story
  aside; it is never viewport-fixed, because the app is offset right by the
  dashboard sidebar and a `left:0` overlay would land off-canvas. Pinned by
  `test_rail.py::test_the_drawer_pushes_the_story_instead_of_covering_it` and
  `test_the_shelf_drawer_rests_closed_and_unmounts_when_it_is`; the desktop having
  exactly one way back by `test_the_desktop_has_one_way_back_not_two`.

- **The reading column has a fixed cap lifted only by the reader.** The reading
  measure does not grow with the window on its own; the width cap moved off the
  root onto the measure, and only the reader's own fluid/fixed choice lifts it. A
  long world title cannot widen the rail, and a label that is really a sentence
  stops columnising. Pinned by
  `test_rail.py::test_the_reading_column_does_not_grow_with_the_window_on_its_own`,
  `test_the_cap_is_lifted_only_by_the_readers_own_choice`,
  `test_a_world_title_cannot_widen_the_rail`, and
  `test_a_label_that_is_really_a_sentence_stops_columnising`.

- **`SceneSlot` is created once and never moved.** The scene iframe is created on
  first need and rendered at the root, outside every view branch; switching away
  hides it with `display:none` and never unmounts or re-keys it — moving or
  re-keying an iframe reloads it, discarding a mounted scene. Its sandbox is the
  dashboard's own host values with same-origin never granted, and the scene is
  handed over as `srcdoc`, not navigated to. Pinned by
  `test_scene_slot.py::test_the_slot_is_hidden_with_display_and_never_destroyed_once_created`,
  `test_the_frame_is_never_re_keyed`,
  `test_the_slot_is_rendered_at_the_root_outside_every_view_branch`,
  `test_same_origin_is_never_granted`, and
  `test_the_scene_is_handed_over_as_srcdoc_not_navigated_to`.

- **A scene answer takes the same road as any turn.** A scene posts its answer
  back via `postMessage` carrying a nonce that names this app, this scene, and a
  choice; `main.tsx` routes it through `api.answerScene` (which validates the
  nonce server-side) and then `api.takeTurn`. A scene is a way of *asking*, not a
  side channel — an accepted answer becomes the turn's action, and a refused one
  still reloads so the player is not stranded. Pinned by
  `test_result_channel.py::test_an_accepted_answer_becomes_the_turns_action` and
  `test_a_refused_answer_still_reloads_so_the_player_is_not_stranded`; the message
  naming all three parts by
  `test_scene_slot.py::test_a_message_must_name_this_app_this_scene_and_a_choice`.

- **The star map treats the backdrop as the room, not as wallpaper behind an
  opaque shell.** `memory.tsx` keeps the ordinary no-art fallback solid, but when
  `StarMap` contains a `Backdrop` the overlay itself becomes transparent and adds
  only a directional contrast shade. The header, filters, map field, detail card,
  and hint are separate translucent instruments, so each owns its readability
  without flattening the narrator's image. Through 1100px, while the portalled
  bottom bar exists, selecting a star raises a bounded detail sheet over the field
  and clears both the bar and the device safe area. Below 860px the filters also
  scroll on one line and the lenses fill their row. The sheet uses a brief entrance
  cue; selection changes are also announced as a polite live region. The people
  lens defaults to its readable list on phone-sized screens; that list includes
  visible people even before a formal relationship is recorded, labels that state
  plainly, translates common relationship kinds, humanises unknown identifiers,
  and explains signed strength as closer or more distant instead of exposing an
  enum and an unlabelled number. Pinned by
  `test_rail.py::test_the_star_map_is_a_backdrop_adaptive_observatory`.

- **The server is the source of truth for "generating," backed by a poll.**
  `play.tsx` drives its generating/awaiting-opening state from what the server
  reports (`v.generating`) and polls while it holds — a local React boolean died
  with the page, so leaving during generation once showed a life nobody asked for.
  Because the backend records the asking *before* speaking to the narrator, a
  returning player converges without doing anything. Pinned by
  `test_pending.py::test_the_page_converges_without_the_player_doing_anything`,
  `test_waiting_is_not_only_a_local_boolean`, and
  `test_a_life_being_written_is_not_shown_as_one_that_stalled`.

- **Turn progress is a tool-call count; retry preserves the input; paging is by
  turn number.** The progress bar advances by the narrator's tool-call count
  (capped short of completion until the commit lands) rather than a timer; a
  failed turn preserves the player's input for retry; and the top-of-story pager
  addresses months by turn *number*, not an offset — an offset shifts under a turn
  committed mid-paging. `api.chronicle(before)` therefore takes a turn number.

- **Opening groups the world decided are sealed, not offered; drafts expire in 30
  days.** `opening.tsx` renders a `worldDecides` group as a sealed note rather than
  a picker — offering a choice the world already made would lie about who decided.
  Half-finished openings persist to `localStorage` with a 30-day TTL, and a
  `CUSTOM` sentinel lets the player type their own value.

- **`create-world.tsx` mirrors life creation.** The world-creation flow runs
  server-side and the player may leave and return, polling for the coarse stage
  (`reading` / `writing`) plus a step count — the same leave-and-return,
  create-before-dispatch shape the run flow uses, so a slow compile is never lost.

- **`api.ts` helpers are typed, code-bearing, and drift-tolerant.** `API =
  '/api/apps/endless-worlds'`; the `json`/`post`/`send` helpers surface the
  server's machine-readable code through `ApiError` so the UI branches on the code
  rather than a message string. Preconditions ride as body fields
  (`deleteWorld(id, lives)`, `deleteLife(runId, turn)`). `models()` reads the
  dashboard's `/api/models` and tolerates both a bare array and `{models:[]}`, and
  both `model_id`/`model_name` and `id`/`name` — a field drift once emptied the
  picker down to only `auto`.
