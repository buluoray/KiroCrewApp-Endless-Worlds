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
| `page-picker.tsx` | the pager's page indicator and its jump-to-month picker (number field + windowed list of every month with a hint) |
| `page-scrubber.tsx` | the press-and-drag page scrubber, hold-to-repeat Prev/Next, wheel and slider keys |
| `page-wheel.tsx` | the phone's sideways page wheel: replaces the pager buttons and the scrubber under 600px, beside the back link |
| `scrub-store.ts` | the page being flipped to, outside React state so a step re-renders only what shows it |
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
  the otherwise-automatic follow of a world's own language. The first-run default
  (no remembered pick) follows the Crew's UI language via
  `document.documentElement.lang` — the dashboard language KiroCrew's own provider
  sets on the shared document — falling back to `navigator.language` and then
  English, since the app ships only zh + en. The play view reading
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

- **Full-screen backdrops switch composition at the same 1100px boundary.** Live
  and chronicle payloads carry only whether a portrait variant exists; `Backdrop`
  owns one `matchMedia('(max-width: 1100px)')` subscription and appends
  `variant=mobile` only when both the flag and narrow environment are true. A resize
  therefore changes the requested SVG while the existing preload/double-buffer path
  holds the painted frame until its replacement decodes. `main.tsx`, `play.tsx`, and
  the full-screen memory overlays propagate the flag; shelf/history thumbnails remain
  desktop so their established landscape cards do not change. The server's metadata
  and fallback halves are pinned by
  `test_live_and_chronicle_metadata_report_mobile_availability` and
  `test_backdrop_route_selects_variants_and_preserves_legacy_fallback`.

- **The tab bar is portaled to `document.body`; the rail opens in flow.**
  `WorldTabBar` is portaled onto `document.body` so it escapes transformed
  ancestors — an iOS WKWebView pins a plain `fixed` bar to the content box rather
  than the viewport. The `WorldRail` drawer opens *in flow*, pushing the story
  aside; it is never viewport-fixed, because the app is offset right by the
  dashboard sidebar and a `left:0` overlay would land off-canvas. Pinned by
  `test_rail.py::test_the_drawer_pushes_the_story_instead_of_covering_it` and
  `test_the_shelf_drawer_rests_closed_and_unmounts_when_it_is`; the desktop having
  exactly one way back by `test_the_desktop_has_one_way_back_not_two`.

- **Only bottom-of-screen furniture is portaled; the top of the screen renders in
  place.** The app mounts onto the dashboard document, and that shell is a stacking
  context — so a portaled element competes with the shell as a whole, never with
  anything inside it. Since the app's own content and the host's chrome both live in
  that shell, a top-of-screen row portaled to `document.body` has no workable layer:
  measured on device, `z-index: 30` covered the host's top bar and menus while
  `z-index: 2` disappeared behind the app's backdrop. The phone's reading row is
  therefore `position: fixed` **in place**, below the chrome by the declared
  `--ew-chrome-h`, where it cannot outrank the host at all. The tab bar stays
  portaled because nothing of the host's lives at the bottom of the screen. The
  layer ladder, the offset's rationale, who owns the scrolling, and the traps are in
  [float-ui-in-the-dashboard-shell](../../skills/float-ui-in-the-dashboard-shell/SKILL.md);
  pinned by `test_rail.py::test_the_reading_row_sits_below_the_host_and_above_the_story`
  and `test_the_chrome_offset_is_declared_not_measured`.

- **The reading column has a fixed cap lifted only by the reader; pages do not.**
  The reading measure does not grow with the window on its own, and only the
  reader's fluid/fixed choice lifts it. That cap and the closed-shell centring are
  scoped to the live view: the shelf, world detail, opening, creation, and review
  pages fill the available main track and begin at its top-left even when their
  content is short. A long world title cannot widen the rail, and a label that is
  really a sentence stops columnising. Pinned by
  `test_rail.py::test_the_reading_column_does_not_grow_with_the_window_on_its_own`,
  `test_the_cap_is_lifted_only_by_the_readers_own_choice`,
  `test_non_reading_desktop_pages_fill_the_canvas_from_the_top_left`,
  `test_a_world_title_cannot_widen_the_rail`, and
  `test_a_label_that_is_really_a_sentence_stops_columnising`.

- **`SceneSlot` is created once and never moved.** The scene iframe is created on
  first need and rendered at the root, outside every view branch; switching away
  hides it with `display:none` and never unmounts or re-keys it — moving or
  re-keying an iframe reloads it, discarding a mounted scene. The compiled bytes
  load through the authenticated scene URL as the iframe's `src`, because a
  sandboxed `srcdoc` blank-renders in WebKit/iOS WKWebView; a content-version token
  changes only when the compiled HTML changes. The frame remains
  `sandbox="allow-scripts allow-forms"` with same-origin never granted, so the
  document has an opaque origin and cannot reach the dashboard. There is no
  fullscreen affordance: the scene remains an inline panel instead of covering
  host chrome or colliding with the mobile tab bar. Pinned by
  `test_scene_slot.py::test_the_slot_is_hidden_with_display_and_never_destroyed_once_created`,
  `test_the_frame_is_never_re_keyed`,
  `test_the_slot_is_rendered_at_the_root_outside_every_view_branch`,
  `test_same_origin_is_never_granted`,
  `test_the_scene_is_loaded_as_a_sandboxed_src_document`, and
  `test_the_scene_has_no_fullscreen_affordance`.

- **A scene frame is sized by its own document, and clears the phone's tab bar.**
  The frame's origin is opaque, so the document reports its content height and
  `SceneSlot` applies it clamped; the stylesheet height is only the pre-report
  fallback. Its surface uses fixed dark values rather than `var(--card)`/
  `var(--border)`, which a light dashboard theme resolves to white behind a scene
  sitting on the world's own dark canvas. Because the frames render after the shell
  and outside it, the shell's bottom padding cannot reach them: the tab-bar
  clearance goes to whatever the page ends with — `.ew-scenes-clear` when frames are
  on screen, and the region pane's own padding otherwise, so the gap never lands
  between the panels and the map instead of under it. Pinned by
  `test_scene_slot.py::test_the_frame_is_sized_from_the_documents_own_report`,
  `test_a_height_report_is_not_an_answer`,
  `test_the_slot_surface_does_not_follow_the_dashboard_theme`, and
  `test_the_scene_frames_clear_the_phones_tab_bar`.

- **The app's own canvas carries the app's own ink.** The shelf's night sky and the
  live view's backdrop are grounds the app chose, dark in every dashboard theme, so
  `.ew-root.ew-home` and `.ew-root.ew-view-live` (and the portaled tab bar) declare
  their own `--text`, `--muted` and an `--ew-accent-ink` for accent text, and under
  `html[data-mode="light"]` re-declare the dark surface set (`--card`, `--bg`,
  `--border`, …) a light dashboard would otherwise hand them. Where a backdrop is
  painted, the reading column and the shelf drawer sit on a reading veil whose alpha
  is solved, not picked. Every pair is held to WCAG AA over white and black art by
  `test_theme_contrast.py` (`test_text_on_the_reading_veil_holds_over_any_drawing`,
  `test_a_life_card_over_its_own_backdrop_stays_legible`,
  `test_the_canvas_ink_does_not_follow_the_dashboard`).

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

- **No ask is judged by its own request.** A turn's HTTP request is an
  acknowledgement, not a verdict: the ask is on disk before the narrator is spoken
  to, so a request that never answers proves nothing about whether the month is
  being written. `play.tsx` therefore holds no "it failed" flag — the outstanding
  ask names the month it wants and the stall verdict is DERIVED each poll from
  whether the life has reached that month or has a narrator in flight — and the
  reload after an ask sits at the top level of `take`, so it runs whether the
  request answered, refused, or threw. A birth is fired and handed off rather than
  awaited, in every caller, for the same reason. Latching the verdict instead left a
  permanent "this page did not come through" over a month that had committed, which
  only remounting the view could clear. Pinned by
  `test_pending.py::test_a_request_that_never_answered_does_not_freeze_the_page` and
  `test_a_birth_is_fired_and_handed_off_never_waited_on`. When the server reports
  the birth's narrator run ended with nothing written (`unanswered`, see
  [turn-loop](turn-loop.md)), the awaiting poll stops and `opening.silent` shows at
  once beside "continue birth", instead of after `AWAITING_POLL_CAP`; the view
  field is pinned by `test_the_play_view_carries_every_field_the_ui_reads`. The two
  un-advanced reasons it branches on are specified in [turn-loop](turn-loop.md).

- **The play page is one page per life.** `main.tsx` keys `PlayPage` by the
  open run id, so entering another life (rail, shelf, legacy heir) remounts it.
  Without the key the page kept the previous life's typed words, armed choice and
  outstanding ask, and a read of the old life still in flight landed on the new
  one and stayed. The scene frames render at the root, so the remount reloads
  none of them. Pinned by `test_ui_state.py::test_the_play_page_is_one_page_per_life`.

- **Local verdicts wait for the server.** The draft review calls a draft gone
  only on a 404 (or a first read that never answered); a dropped poll of a
  compile keeps the progress screen and lets the next poll answer. The settings
  panel enables Save only after the player's settings were read, because Save
  writes every field and the pre-read fields are defaults; a failed read or save
  is shown, with a retry for the read. Pinned by
  `test_ui_state.py::test_one_dropped_poll_does_not_declare_a_draft_gone`,
  `test_save_waits_for_the_players_settings_to_be_read`, and
  `test_a_failed_read_or_save_is_said_out_loud`.

- **Turn progress follows tool calls and time, and names the real stage; retry
  preserves the input; paging is by turn number.** `TurnProgress` takes the larger
  of a notch per narrator tool call and a slow creep from `generating.askedAt`
  (`progressPct`, both capped at 92% until the commit lands), because a month is
  only two or three calls and the long one is the write, so a call-only bar stood
  still for about a minute. Beside the tuned waiting phrase it shows the server's
  own `generating.stage` (`play.stage.reading` / `writing` / `painting`), and beside
  that an elapsed clock (`formatElapsed`, `m:ss`) counted from `askedAt`, so a reload
  keeps the real wait. Only the label and stage are live regions; the clock sits
  outside them (a screen reader would otherwise read every second) and is a plain
  text change, so reduced motion needs nothing more. Pinned by
  `test_rail.py::test_turn_progress_names_the_server_stage_and_creeps_between_calls`
  and `test_play_flow.py::test_the_wait_shows_time_since_the_ask_without_reading_every_second_aloud`.

- **A hidden entry recap can come back; echo lines name their event.** Hiding
  "Where this life left off" lights a `play.recapReopen` button in the pager (live
  page only) that reopens it; keyboard focus moves between Hide and Recap rather
  than falling to the page. A newer month retires both the recap and the button.
  Each echo's folded line carries its own event title (`play.echoLineTitled`,
  the answering event, else its source), so two echoes of one page no longer read
  the same. Pinned by `test_play_flow.py::test_a_hidden_recap_can_be_reopened_from_the_pager`
  and `test_each_echo_line_names_its_own_event`.
  A failed turn preserves the player's input for retry; and the top-of-story pager
  addresses months by turn *number*, not an offset — an offset shifts under a turn
  committed mid-paging. `api.chronicle(before)` therefore takes a turn number.

- **Any month is two moves away.** The pager reads First ‹ page › Latest. Latest
  always sets the *live* page (`viewTurn = null`), never a past copy of the newest
  number, so a turn in flight, the painting stage and the Recap button return with
  it. The page indicator (`play.pageOf`, `play.pageShort` below 480px so five 44px
  targets fit at 375px) is the button of `page-picker.tsx`: a labelled dialog with a
  number field (type a month, Enter) over a list of every month, each row its number
  plus a hint — the player's action, else how the page began. Escape or a click
  outside closes it, Escape returning focus to the indicator; a jump hands focus to
  `StoryPage`, which announces the new page once. The rows are a fixed 44px and
  absolutely placed, so only those on screen plus a small overscan are drawn
  (`visibleRows`) whatever the life's length. The hints are ONE read of
  `GET /runs/{id}/chronicle/index` (number + ≤48-char hint per month, built from the
  same `_lived_entries` filter as the chronicle so the two agree on which months
  exist), made on first open and kept until a new month lands. The page picked is
  fetched on its own, and `play.tsx` keeps at most one page read in flight: a held
  arrow key or a second jump waits for it rather than starting a request per month,
  a read is kept even if the reader moved on, and a failed read is not retried in a
  loop. Left/Right/Home/End page while focus is on the page itself — never from a
  field (the free-action box above all), a tab strip, a dialog, or while a sheet
  covers the column or the pager is hidden. Pinned by `test_page_jump.py`.

- **Press and slide to flip fast.** `page-scrubber.tsx` adds a slim full-width track
  as the top bar's second row (a life of 2+ pages; the fixed bar's slot grows by that
  row). Drag it — mouse or finger, pointer capture, `touch-action: none` so the page
  never scrolls — and the thumb, the page indicator and a floating label (page number
  plus the same index hint the picker shows, from the one shared `loadPageIndex`
  read) follow live; release loads that ONE page. Holding Prev/Next (`HoldArrow`)
  keeps flipping after 300ms and speeds up the longer it is held (`holdInterval`);
  a plain click is still one page, and release loads only the last. The wheel over
  the track moves one page per notch (`wheelSteps` accumulates trackpad deltas) and
  the keys follow the ARIA slider pattern (arrows ±1, PageUp/PageDown ±10,
  Home/End); both load once the reader pauses (`SCRUB_SETTLE_MS`). While flipping,
  the number lives in `scrub-store.ts` (a `useSyncExternalStore` store) that only
  the thumb, label and indicator subscribe to, so the story does not re-render per
  step. The track is `role="slider"` with `aria-valuetext` "Page 12 of 120";
  `StoryPage` announces the landed page once and leaves focus on the slider. The
  newest page lands on the live page, like Latest. Pinned by `test_page_scrubber.py`;
  the pointer paths run for real in `devtools/scrub.test.mjs`.

- **The scrubber is drawn as a book.** On a wide screen the track is a book's
  fore-edge: fine page lines (`repeating-linear-gradient`, CSS only) whose pitch
  tightens for a longer life (`edgeGap`), the pages already read a warmer, thumbed
  paper. The thumb is a cloth ribbon bookmark with a notched tail
  (`.ew-scrub-ribbon`, `clip-path`), drawing only — the slider role, values and
  focus stay on the track. The drag label is a folio slip: opaque paper with its own
  ink in both dashboard themes, the page number in a serif reading face in small caps
  with old-style figures, the action in italic under a hairline. The page indicator
  uses the same face; the First/Prev/Next/Latest buttons are quiet hairline frames.
  A jump of more than one page by the scrubber, the wheel or a held arrow (`leafTo`)
  draws one short fold of shadow over the landed page (`.ew-leaf`), cleared on
  `animationend`; `prefers-reduced-motion` draws none. Chapter tabs and fateful marks
  are not drawn: the page index carries neither. Pinned by `test_page_scrubber.py`;
  the folio's contrast by `test_theme_contrast.py`.

- **On a phone the pager is a sideways page wheel beside the back link.** Under
  `PHONE_QUERY` (`max-width: 600px`) there are no pager buttons (First, Prev, the
  `N / M` indicator, Next, Latest) and no fore-edge slider: `play.tsx` renders
  `phoneBar` instead, and `page-wheel.tsx` puts a row of page numbers in the top row,
  one line with the back link (`.ew-topbar-wheel`, `flex-wrap: nowrap`). The link
  never wraps or shrinks (`white-space: nowrap`, `flex: none`); the wheel takes the
  width it leaves and draws fewer numbers. There is no card behind the numbers: they
  sit straight on the reading row in the canvas ink — the centre `--text`, held to
  AA over the worst art, its neighbours `--muted` fading out, turning away on a drum
  (inline `rotateY`/`scale`/`opacity` from `wheelLook`) under a mask. The centre
  number alone, larger and in full ink, marks the page: no ribbon, bookmark or
  underline is drawn over or under it (the desktop slider keeps its ribbon thumb,
  which is its drag handle). A swipe
  follows the finger; on release the drum coasts to where a decaying throw would stop
  (`flickVelocity`, `wheelTarget`, `WHEEL_TAU_MS`) and snaps to that page, ticking
  the centre number as each page crosses; a tap on a neighbour turns to it. Only the
  numbers on screen are drawn (`visiblePages`). The page number lives in the scrub
  store while it turns and the ONE page loads when it rests. Same `role="slider"`
  values, keys and settle rule as the desktop track; reduced motion snaps without the
  glide or the tick.

  A tap on the centre number (or Enter on the wheel) opens the #127 type-a-number
  picker: `PagePicker` with `overWheel`, its open state held by the play page. Its
  button is a transparent 44px square laid over the centre number with
  `pointer-events: none`, so a finger reaches the wheel while a keyboard or screen
  reader still finds the named picker button, its focus ring round the centre
  number. The wheel's track carries `data-ew-pick-toggle`, so its own tap toggles the
  picker instead of counting as an outside press. The way back to the live page is
  the small mark at the wheel's end (`WheelLatest` in `page-wheel.tsx`,
  `.ew-wheel-latest`, named `play.latestTurn`). On the latest page it has nowhere to
  go, so it is hidden: `disabled`, `aria-hidden`, `tabIndex={-1}` and
  `visibility: hidden`, which keeps its 44px slot so the wheel and the back link do
  not shift when it comes and goes. It reads the wheel's flip preview, so it shows
  again the moment a swipe leaves the latest page, before the page lands. The
  desktop pager's Latest button is unchanged. The hidden-recap button stays in the
  same row. The bar
  is one 44px row, so the fixed bar's slot does not grow. Each number's slot fills
  that row (`.ew-wheel-n`, `top: 0; height: 44px`), so the back link, the centre
  number and the `>|` mark share one vertical centre; `devtools/wheel-align.test.mjs`
  measures their ink centres within 2px at 320, 375 and 480px, both themes, on a
  1-, 2- and 3-digit page (same `EW_POD_URL` / `EW_POD_SESSION` contract). It also
  checks the mark is hidden and unfocusable on the latest page, back mid-flip, shown
  and focusable one page back, and that the link, the centre number and the mark's
  slot stay within 1px between the two. It never waits a fixed delay: each
  measurement waits for fonts, the wheel at rest on the page, and the row's boxes
  still for 5 frames. Pinned by
  `test_page_wheel.py` and `test_theme_contrast.py`; the swipe, coast, snap, one read,
  no pager buttons, the one-line back link, the picker and the way back run in
  `devtools/scrub.test.mjs` at 375px.

- **The back link reads `← 书架` / `← Shelf`.** `play.back` is the short visible
  text everywhere; `play.backLabel` (`回到书架` / `Back to the shelf`) is its
  accessible name.

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

- **Reading a new page remains keyboard- and screen-reader accessible.**
  `StoryPage` names the prose region by page number, announces a ready page once
  through a persistent polite status, and focuses the prose after load/paging.
  Loading past pages do not take focus until their content arrives. Unchanged
  polls do not refocus; a hidden reading tab, sheet, or focus outside the play
  root prevents focus theft. Ending prose uses the same component.
  `PlayPage` visibly labels free actions and describes Ctrl/Cmd+Enter (direct
  submission); composition events never submit unfinished IME text. Escape and
  Think again restore focus to the armed choice, the free-action box, or the
  close-this-life button. Closing a life (`play.closeLife`) takes the same second
  step as an action and sends only `{close: true}` from the confirm button; the
  view's backend-computed `growth` rows render beside the milestone marker. Scroll-hidden
  navigation becomes visible on keyboard focus. Phone actions stack, pager labels
  can shrink, and pager/confirmation targets remain at least 44px.
  The shelf explains how to start a first life, the first page explains the
  choice/confirm loop, and an empty world shelf points to Create a world.
  Pinned by `test_free_action_has_a_visible_label_and_keyboard_help`,
  `test_cancel_returns_to_the_control_that_armed_the_action`,
  `test_a_landed_page_is_named_announced_and_focused_without_stealing_focus`,
  `test_phone_navigation_does_not_hide_the_keyboard_focus`,
  `test_first_life_help_is_visible_on_both_widths`,
  `test_closing_a_life_takes_a_confirm_step_and_sends_only_the_close_flag`, and
  `test_first_run_and_keyboard_copy_exists_in_both_languages` in
  `test_play_accessibility.py`. `devtools/play-ux.test.mjs` walks keyboard choice,
  Escape, free text, IME, turn arrival, history, and first-run screens in a seeded
  disposable pod. Set `EW_POD_URL` and `EW_POD_SESSION` (Playwright storage state)
  when running it with `node --test`; absent these, it skips rather than touching
  a live home. Turn writes and empty-shelf reads are intercepted fixtures; other
  reads reach the real app. Native screen-reader speech is not automated here.

- **A month written while the reader is on the page updates what surrounds it.**
  The rail's row for the open life reads the shelf's run list, which `load()`
  fetches once; `PlayPage` reports a signature of the row's own facts (turn,
  unborn, ended, being written) through `onRowState`, and `refreshRuns` re-reads
  only the run list when it moves, keeping the newest response. The "where this
  life left off" recap opens on entering a life and closes when a newer month
  lands while the reader is there (`recapTurn`), so it never summarises the page
  that just arrived. The first-page hint carries `ew-first-turn-hint`, which
  cancels the shared `.ew-hint` negative top margin that otherwise laid it over
  the last line of prose. Pinned by `test_play_flow.py` and, against a seeded
  disposable pod with turn writes intercepted, `devtools/play-flow.test.mjs`
  (same `EW_POD_URL` / `EW_POD_SESSION` contract as `play-ux.test.mjs`).
