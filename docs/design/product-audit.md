# Endless Worlds Product Experience Audit and Roadmap

> Audit date: 2026-08-18
> Audit baseline: Endless Worlds v0.3.0
> Audit scope: player flow, narrative interaction, saves and long-term play, mobile and accessibility, product completeness

## Goal

This audit reviews the existing Endless Worlds source and tests, looking for convenience features that would let players play more smoothly and more easily over the long term but that are not yet provided. The focus is not on stacking on more new systems, but on filling out the life cycle, failure recovery, and player entry points to capabilities that already exist underneath.

## Existing foundation

The following capabilities already exist and should not be rebuilt:

- Multi-world, multi-life shelf and desktop navigation bar.
- Paginated character creation, free-form input, per-item random and all-random.
- Character-creation drafts auto-save and can be recovered after leaving.
- Preset selection and free-form action go through the same turn-submission path, with a confirmation step.
- Turn idempotency, a server-side "generating" marker, and generation that continues after leaving the page and converges automatically.
- The Narrator runs in isolation, can only call this App's MCP tools, and cannot access player memory, the file system, or the network.
- Status panel, world summary, rumor markers, and dynamic-scene infrastructure.
- Paginated life history that also stores the action the player took at the time.
- World-deletion pre-check, name-confirmation, concurrent-player validation, and seed-world recovery.
- Narrow-screen layout, desktop rail, reduced-motion, and Chinese/English string tables.

The product's main gaps today fall into three categories:

1. The life cycle has no closed loop.
2. Existing underlying capabilities have no player entry point.
3. Failure recovery and long-run review experience are lacking.

## P0: Correctness and the core loop

### 1. Execute the ending conditions a world declares

> **Status: implemented (2026-08-18).** `backend/view.py` adds `resolve_ending(template, state)`, which evaluates all `endings` conditions in a single place and returns the matched ending id (a world's declared condition takes priority over the narrator-written `state["ended"]` marker); `build_play_view` returns `ended` and `endingId` accordingly. `advance_run_turn` checks before dispatch, and a new turn on an already-ended life is rejected with a stable `reason:"ended"` + `endingId` instead of narrating. The frontend `play.tsx` adds a final-chapter branch: it shows a closing notice, the last narrative segment as an epilogue, the number of turns survived, and provides "live again in this world" and "back to shelf" entry points, with the chronicle still viewable. Tests are in `test_view.py`. **Still not done**: the next-generation inheritance flow for `lineage: true` worlds (see P2 §14).

**Current state**

A world template can declare `endings`, and the detail page shows the number of ending conditions, but at runtime nothing evaluates those conditions in one place. `ended` currently depends only on the narrator writing state itself; even if a life has ended, the play page and turn route may still allow further actions.

**Code entry points**

- `backend/template.py`: `Ending` and ending-condition parsing.
- `backend/view.py`: `build_play_view()` only reads `state.ended`.
- `backend/routes.py`: `advance_run_turn()` has no ended-state rejection yet.
- `web/src/play.tsx`: has no dedicated branch for `v.ended`.

**Recommended behavior**

- Evaluate all ending conditions in a single place on the backend and return the matched ending ID.
- Reject new turns for an ended life, and return a stable machine-readable reason for repeated requests.
- The play page replaces the action area with a final-chapter page.
- The final chapter shows time survived, key events, final state, and provides entry points to start a new life, export, and organize lives.
- A `lineage: true` world enters the next-generation inheritance flow when conditions are met, rather than only showing a badge.

### 2. Show all mounted dynamic scenes

> **Status: implemented (2026-08-18).** Scenes are no longer a single slot showing only "the latest question scene": `PlayPage` now reports all mounted scenes to the app root, and `main.tsx` renders one persistent `SceneSlot` per scene in **mount order** (keyed by sceneId, never reordered -- moving an iframe reloads it). Display-type scenes (maps/ledgers with `asks:false`) are therefore visible, and answered-but-not-dismissed scenes remain as well. The `scene: string` state becomes `scenes: SceneRow[]`.
> **Still not done (UX polish, non-blocking):** a scene bar / tabs plus "proactively expand a non-question scene" collapse interaction; and scene-driven turns still do not explicitly pass the next turn number (they currently rely on the server's `current+1` + nonce/answered guard, which is safe but not idempotency-optimal).

**Current state**

The Narrator can mount `asks: false` maps, ledgers, and other display-type scenes, but the frontend only selects the latest, not-yet-answered question scene. So the display capability of the live-generated UI already exists, but it never appears in front of the player.

**Code entry points**

- `backend/mcp_server.py`: `endless_mount_scene`.
- `backend/view.py`: the play view already returns mounted scenes.
- `web/src/play.tsx`: only filters `asks && !answered`.
- `web/src/main.tsx`, `web/src/scene.tsx`: currently only one SceneSlot.

**Recommended behavior**

- Add a scene bar or tabs showing all currently mounted scenes.
- Question scenes can still auto-surface, but non-question scenes let the player open them proactively.
- Answered-but-not-dismissed maps or ledgers remain viewable.
- A scene-driven turn must also submit an explicit next turn number, keeping the same idempotency semantics as a normal action.

### 3. Preserve player input after failure and support retry

> **Status: implemented (2026-08-18).** `take()` in `web/src/play.tsx` only clears input when the turn truly advanced (`advanced`), was already submitted (`already`), or the life ended (`ended`); when the narrator did not respond it keeps the text the player wrote, remembers the last action that did not land, and offers a "try again" button next to the stalled notice that re-sends the same action directly. `ended` is no longer misclassified as stalled (the final-chapter branch now takes over).

**Current state**

When a turn request returns normally but `advanced == false`, the frontend still clears the free-form input and then asks the player to say it again. The network-error path, on the other hand, preserves the input -- inconsistent behavior.

**Code entry points**

- `web/src/play.tsx`: `take()`.

**Recommended behavior**

- Clear input only on a successful advance or a confirmed already-submitted state.
- Preserve the last action and show "retry the last action with one tap".
- Distinguish offline, timeout, a request already generating, and narrator-did-not-respond.
- After a transient read failure, a successful load must clear the old error.

### 4. Fix recovery, language, and error states

> **Status: implemented (2026-08-18).**
> - **Language takes effect immediately (context refactor):** the render language becomes React state on the root component, and the root writes the module `current` in `strings.ts` **synchronously during render** (no longer inside an effect), so the moment the world's language changes the whole tree re-renders in the new language, no longer lagging a frame. `t()`/`pick()` still read the module `current`, so call sites change zero; the language setter is distributed via `LanguageContext` (`useSetLanguage`), and `play.tsx` and the root's world-loading site call it.
> - **Stale-location cleanup + detail recovery:** before recovering `live`/`detail`/`opening`, `api.run`/`api.world` verifies the target still exists; if deleted, the remembered location is cleared and the view returns to the shelf (no longer opening a 404 page); a recovery branch is added for the `detail` view.
> - **Per-page retry buttons:** the shelf, play page, world detail, and chronicle all offer a "retry / Retry" button when a read fails; the shelf and play-page buttons are inside `body`, so they are tappable on narrow screens (rail hidden) too.
> - **404:** `get_run` already returns 404 for a nonexistent life and 422 when there is no world (confirmed this pass, unchanged).

- A change in the world's language must trigger a React re-render, avoiding an English world showing a Chinese UI when first opened.
- Read failures on the shelf, world detail, life page, and history should all offer a retry button.
- Mobile must not depend on a desktop-only visible rail to reload.
- A nonexistent life uniformly returns 404, not an uncaught `StoreError`/500.
- When recovering to a deleted life, the invalid remembered location should be cleared and the view returned to the shelf.
- If the `detail` view writes a remembered location, it must also be recoverable.

## P1: High-value convenience features

### 5. Manage lives individually

**Target capabilities**

- Player-customized life names.
- Delete a single life without affecting the world or other lives in the same world.
- Archive and un-archive.
- Group into in-progress, ended, and archived.
- A life row shows the world, simulation style, current turn, and last-played time.
- Support pinning and filtering by status; add search once the count grows.

**Existing foundation**

`RunStore.delete_run()` already handles cleanup of state, rollback, pending, brief, chronicle, and index.

**Current state**

Single-life deletion has landed: `backend/routes.py` registers `POST /runs/{run_id}/delete` (`delete_life`, `routes.py:548/1172`), reusing `RunStore.delete_run()`; the frontend has `DeleteLifeDialog`, and there is `test_delete_life.py`.

> **Rename / archive / grouping implemented (2026-08-18).** Added `RunStore.patch_index()` (merges `label`/`archived` into the index row without touching `lastPlayed` or other fields) + `POST /runs/{run_id}/meta` (`set_life_meta`, an empty `label` string clears it, `archived` is a boolean). `list_runs` passes these two fields through as-is. Frontend: `LifeRow` prefers the player-customized `label`, with inline rename (Enter to save / Esc to cancel), archive/un-archive, and delete controls; the shelf groups by **in-progress / ended / archived (collapsible)**; the rail collapses archived lives and likewise prefers `label`. Test `test_store.py::test_patch_index_*`. **Still not done:** pinning (starred), filtering/search by status/world, and `lastPlayed` is currently the creation time (turn submission does not refresh the index, an existing limitation).

### 6. Recap and life chronicle

> **Status: the event timeline is implemented (2026-08-18).** `get_chronicle` now returns the `events` (strings) and `gains` (`{field,amount?,source?}`) that were already stored per turn; `history.tsx` renders these markers under each turn's body (a gain carries its source) and adds a "big events only" toggle -- listing only turns with events and hiding the body, i.e. an event timeline. The ending page reuses the same data: the `LifeSummary` component reads the chronicle (up to the most recent 100 turns, which for the vast majority of lives is the whole thing) and aggregates events from earliest to latest into "the great events of this life", with no extra model calls. **Still not done:** a "since you last left" recap banner when returning to a life.

**Current state**

Each turn already stores `events` and `gains`, but the player history API only returns the turn, body, and action.

**Recommended behavior**

- Show a no-extra-model-call "since you last left" when returning to a life.
- In history, show that turn's events, gains/losses, and their sources.
- Provide a "big events only" timeline.
- The ending page reuses the same data to generate a life summary.

**Code entry points**

- `backend/mcp_server.py`: writes `events`, `gains` when committing the chronicle.
- `backend/routes.py`: `get_chronicle()` currently does not return either.
- `web/src/history.tsx`: history display.

### 7. Improve the review experience for long lives

> **Status: jump-to, event filtering, and full-text search implemented (2026-08-18).** `history.tsx` adds a "jump to turn N" input (using the existing `?before=N+1` to position, replacing rather than appending the current page), a "big events only" event filter, and full-text search -- `get_chronicle` supports `?q=` (case-insensitive substring filter on body/action/events, applied before pagination, so paging pages through the hits), and the frontend has a search box / clear / no-match hint; the backend `?limit=` already supports fetching up to 100 turns at once. **Still not done:** per-turn collapse/expand.

Current history is fixed at 12 turns per page and can only click "further back" repeatedly. Recommend adding:

- Jump to a specific turn.
- Search body and player actions.
- Filter by key events.
- Per-turn collapse and expand.
- Load more at once, or fetch up to 100 turns on demand.
- Export an entire life as a continuous Markdown novel.

### 8. Character-creation summary, reset, and reuse

> **Status: the summary/reset/draft experience is implemented (2026-08-18).** `opening.tsx`: the last page adds a "what this life looks like" pre-birth summary, listing each choice item by item, with world-decided items clearly marked in italic as "left to the world to decide"; adds "reset all" (only appears when there is input); shows a one-time "restored your previous choices" notice when a draft is brought back; drafts get a 30-day TTL (ignored once expired), and `main.tsx` clears leftover drafts for deleted worlds once the world list is known. **Copy the previous life's character creation is implemented (2026-08-18):** `create_run` accepts `fromRunId` and uses the source life's character-creation choices as the starting point of a new life (bringing only the player's own choices; world-decided/random items stored as null are dropped and re-adjudicated by the world), and the ending page adds a "live again with the same start" entry point. **Still not done:** save as a character-creation preset (reuse one start across worlds).

- Summarize all choices before birth and clearly mark the items left to the world to decide.
- Add "reset all".
- Copy the previous life's character creation, or save it as a character-creation preset.
- When returning to an existing draft, clearly show "restored previous choices".
- Drafts need an expiry or cleanup policy to avoid lingering long-term in shared localStorage.

### 9. Improve action expressiveness

- Add an optional OOC / clarification channel so a player can correct the narrator's understanding of intent without wasting a world turn explaining in-fiction.
- The Choice schema can optionally carry risk, cost, time span, or preconditions.
- Add pacing controls, such as "narrate this night in detail" or "fast-forward three years".
- Allow switching narration style within a life; the backend already supports passing a style per turn.
- Person, item, and thread panel entries can be clicked to fill the action box.
- First-time play can show a free-form action example, not just "or do something else".

## P2: Long-term play capabilities

### 10. Redo the previous turn

`RunStore.rollback()` already stores the previous state, but there is no player entry point yet, and it only rolls back state -- it does not sync the chronicle, scenes, and pending.

**Recommended constraints**

- The first version only allows redoing the most recently submitted turn.
- Clear pending and explicitly invalidate the original chronicle record; do not silently delete audit history.
- Re-establish the narrator session's runtime baseline.
- Clearly distinguish "withdraw the action" from "re-narrate with the same action".

Do not directly implement arbitrary history branching. The current chronicle does not store a full per-turn state, so it cannot accurately restore turn 7 from turn 20. If branching is needed in the future, per-turn state snapshots should start being written first.

### 11. World and life import/export

World export is already implemented as `endless_export_world` (formerly `endless_make_pack`, renamed because it collided with capability-pack generation), but it is only written to a server directory by the narrator MCP -- players cannot download it directly, and there is no import capability. It exports the entire world file and is unrelated to Task 16's capability-pack generation (compile-time, the `compose` primitive).

Recommended order:

1. Player downloads a world pack.
2. Import a world pack and validate the contract, world ID, and content.
3. Export a complete life, including current state, chronicle, world reference, and necessary scene data.
4. When importing a life, regenerate the run ID and never overwrite an existing local life.
5. Can serve as a safe backup before deleting a life.

### 12. Background-completion notification and safe abandonment

- Show how long has been waited so far.
- After the player leaves the page, send a Dashboard notification when generation completes.
- Allow safe cleanup of stale pending after a request deadline.
- Do not allow premature cancellation, or two narrators might write the same turn simultaneously.
- Reduce polling frequency when the page is hidden or offline, and refetch immediately on reconnect or returning to the foreground.

### 13. World updates and creation

- The "a newer version exists" hint currently has no action entry point; it should allow installing the new version as a separate world, or clearly explain why an existing world cannot be overwritten.
- Add world-pack import.
- Later, the existing compiler brief can be connected to a "paste a rulebook and create a world" product flow.
- An existing world definition that hosts lives must not be overwritten directly.

### 14. Cross-life and world continuity

This is a larger product direction and not a near-term quick win:

- Each life and narrator session is currently isolated, which is the correct privacy boundary.
- To let a second life inherit the world history caused by a first life, an independent, App-specific world chronicle should be built, rather than reading the player's personal memory.
- Cross-life inheritance must be explicitly allowed by the world template and must not become the default for all worlds.

## Accessibility and interaction quick wins

> **Status: the main items are implemented (2026-08-18).** Done: character-creation inputs named with `aria-label`, character-creation option/style pills using `aria-pressed`, the history and status drawers using `aria-expanded`/`aria-controls`, stalled and scene loading using `role=status aria-live=polite`, scene fullscreen supporting Escape to exit, scene loading showing pending copy, `Cmd/Ctrl+Enter` to submit a free-form action directly, the root node setting `lang` per the world's language, and all custom controls getting a `:focus-visible` focus ring. **Still not done:** unifying 44px touch targets, full modal focus-trap / focus restore after close, and font-size/line-height/reading-width preferences (a settings-type feature, scheduled separately).

Recommend handling these together in P1:

- Character-creation inputs use a real `<label>` or an explicit accessible name.
- Option pills use `aria-pressed` or radiogroup semantics.
- The history and status drawers add `aria-expanded`, `aria-controls`.
- Loading, failure, and stalled states use appropriate live regions.
- Modals add a focus trap and focus restore after close, and forbid Escape/scrim close while working.
- Custom buttons get a unified focus ring.
- Primary touch targets reach 44px.
- Scene fullscreen supports Escape to exit.
- Scene loading shows a pending state.
- `Cmd/Ctrl+Enter` submits or confirms a free-form action.
- Add font-size, line-height, and reading-width preferences.
- The root node sets the correct `lang` per the world's language.

## Second-round parallel audit addendum (2026-08-18, net-new after dedup)

> The second round used 4 parallel agents to separately re-review save management, turn mechanics, frontend UI, and dynamic content plus the world system. Only items not already covered above are listed here; the ending loop, showing all dynamic scenes, failure retry, managing lives individually, recap/event timeline, long-history navigation, character-creation summary/reuse, the OOC channel, turn redo, import/export, accessibility, and so on are all covered earlier and not repeated.

### N1 (folded into P0): panel primitives are declared but discarded at runtime

> **Status: people and inventory are fixed (2026-08-18).** `_shape` in `backend/view.py` now takes a field `options`: `people` preserves each person's attribute values (attitude/closeness/identity) per the declared `attributes` columns, and stays name+note when nothing is declared; `inventory` preserves each item's `count`/`note` ("three potions" is no longer identical in shape to "one bottle"). The frontend `ui.tsx` renders the person columns and item counts, and the `ShapedField` type is updated accordingly. Tests are in `test_view.py` (`test_people_carry_declared_attribute_columns`, `test_an_inventory_keeps_count_and_note`).
> **Still not done (needs storage / a new route, not "fast and safe"):** the `delayed`-consequence ledger for `resource`, and the historical series (sparkline) for `trend` -- both require recording per-turn values or unsettled items on the store side, left for a dedicated version.

Fields promised by the template and compiler brief are flattened in `_shape()` in `backend/view.py`, which is the same class of "the world declared it but it is not honored" correctness problem as P0#1 -- the compiled world pack carries these declarations, yet nothing happens on the player side.

- `people`: `_shape` only outputs the `("name","note")` columns (`view.py:126`), discarding the `attributes` columns promised by `COMPILER_BRIEF` (`compile.py:134-135`). An NPC's attitude/closeness/identity has nowhere to be shown.
- `inventory`: dict items are flattened into plain strings (`view.py:131-135`), losing count, description, and category. "Three potions" and "one bottle" are indistinguishable in the UI.
- `resource` with `delayed: true`: the brief promises "will be spent, and changes have delayed consequences" (`compile.py:137-138`), but `_shape` does not read `delayed`, making it no different from `stat`, and there is no "unsettled consequence" record structure.
- `trend`: only returns the `value/direction/note` strings, with no historical series, even though the full per-turn state snapshot is already on disk (chronicle).

**Recommendation**: the people/inventory branches of `_shape` preserve the declared columns and counts; for `resource`, pick one -- either remove the promise from the brief, or add a pending-consequences ledger in the store and prompt the narrator in `advance_turn`; for `trend`, add a `GET /runs/{id}/series?path=` that extracts historical values from the chronicle.

### N2 (folded into P1): existing capabilities still lack a player entry point

> **Status: three items implemented (2026-08-18).** (1) Chapter-unlock hint: `get_run` uses `store.read_prev` to compare the previous state with the current one, computes the chapters newly opened this turn via `opened_since`, maps them to the world's own heading, and `build_play_view` adds an `unlocked` field to pass it through; the top of the play page quietly hints "a new chapter opened: <...>" (in the world's wording, without leaking implementation vocabulary; a first turn with an empty prev does not false-fire). (2) World-lore-text entry point: `api.world(id, true)` requests `?prose=1`, and `WorldDetailView` adds a "read this world's setting" collapsible section. (3) World-card footprint: `main.tsx` aggregates `runs` by `worldId` and passes them into `WorldCard`, showing "you have lived here n times". Tests `test_store.py::test_read_prev_*`, `test_view.py::test_unlocked_chapters_*`.

- **Chapter-unlock hint**: `opened_since()` in `backend/chapters.py` can already compute the chapters newly unlocked this turn, but neither `view.py` nor `routes.py` passes it through, so the player misses the sense of progress in "the world opened the magic-system chapter for you". Landing spot: `build_play_view` adds `unlocked`, and it **must use the world's own heading wording and must not leak implementation vocabulary like chapter/disclosure** (R25.2). Difficulty: low.
- **World-lore-text entry point**: the detail page never requests `?prose=1`, so the player cannot see the world's full lore text (the backend already supports it). Landing spot: `web/src/library.tsx`. Difficulty: low.
- **World-card footprint count**: the world card only talks about static config, not the player's own footprint. Aggregate the existing `runs` by `worldId` and pass them into `WorldCard`, showing "I have lived here n times". Landing spot: `web/src/main.tsx`. Difficulty: low.

### N3 (folded into P1/accessibility): reading and immersion experience

- **A continuous reading flow across the current turn and history**: the play page only shows the current turn's body, and the previous turn requires opening the drawer to History; splice the most recent 1-2 chronicle entries above the current body to restore narrative continuity (`api.chronicle` already exists). Landing spot: `web/src/play.tsx`. Difficulty: medium.
- **Reading / immersion mode**: a toggle that hides the rail and the right-side panel to focus on reading long narrative. Landing spot: `web/src/main.tsx` + `styles.css`. Difficulty: low.
- **Excerpt / bookmark a body paragraph**: narrative is this App's only product, yet there is no way to mark a favorite paragraph -- turn the page and it is lost. Difficulty: low to medium.
- **Skeleton loading states**: every loading state is a single line of text, and the layout jumps abruptly the instant data arrives; switch to skeleton screens. Difficulty: low.
- **A pinnable panel on mobile**: below 900px the panel is only in a drawer, so typing and checking status are mutually exclusive; switch to a sticky-able summary bar. Landing spot: `web/src/play.tsx`. Difficulty: medium.

### N4 (folded into P2): the world presentation layer

- **Scene widgets lack spatial/relational elements**: the existing 10 `ELEMENT_KINDS` are all linear layout (`widget.py:52-54`: heading/text/note/stat/bar/keyvalue/list/table/choice/divider); the tool description says "a map" yet no element can draw a map or a relationship graph. Recommend adding constrained, closed kinds: `grid` (a region map with fixed rows and columns), `links` (a relationship graph of nodes + edges), `tree` (a skill tree / family tree of parent-child hierarchy), with **all geometry generated by the backend in `widget.py` and the narrator providing only relationships, not coordinates**, holding the "model bytes do not go straight into the DOM" trust boundary. Difficulty: medium-high.
- **Achievement / milestone system**: zero implementation. The header adds `milestones: [{id, label, when}]`, **directly reusing the existing `Condition` interpreter** (near-zero mechanism cost), evaluated after each commit; achieved items are written to a reserved field in `RESERVED_STATE_KEYS` (which already has carry-forward), and the view returns the items newly achieved this turn. Difficulty: medium (the "fires only once" persistence needs care).

## Recommended implementation route

### Batch one: the correctness loop

1. Evaluate ending conditions, forbid further actions after ending, and add the final chapter.
2. Show all dynamic scenes.
3. Preserve failed input and retry.
4. Fix language, mobile retry, stale location, and 404/500.

### Batch two: everyday play convenience

1. Complete and verify single-life deletion.
2. Add life rename, archive, grouping, and metadata.
3. Add recap, event timeline, and long-history navigation.
4. Add character-creation summary, reset, and reuse.
5. Complete keyboard and accessibility improvements.

### Batch three: long-term value

1. World and life import/export.
2. Redo the previous turn.
3. Background-completion notification and safe abandonment.
4. Start saving per-turn state snapshots to pave the way for future history branching.
5. Design lineage next-generation and optional world-level continuity.

## Decision principles

- Fix product promises and data correctness first, then add new worlds or new panels.
- Prefer exposing capabilities that already exist underneath, rather than creating parallel mechanisms.
- Turn redo must maintain consistency across state, chronicle, scene, and narrator baseline.
- Full history branching must be built on top of per-turn state snapshots.
- Narrator isolation and player-memory isolation are product boundaries, and convenience features must not bypass them.

## Mobile frontend deep audit

> Deep-audit date: 2026-08-19
> Baseline: current `main` (`0b807f1`), phone design floor 320px, checked at 320 / 360 / 390 / 430 / 768 / 900 / 1100px.
> Method: after 4 independent parallel source audits, each item was re-checked against the current TSX/CSS. The current host has no Browser driver installed, and the installed app bundle differs from the source bundle, so this section marks deterministic DOM/CSS defects as "source-confirmed" and leaves items that require looking at real pixels in the verification matrix, rather than substituting screenshots from an old install package as evidence.

This round confirms the existing layout has a solid foundation: the CSS is narrow-first; 320-767px uses a 16px gutter; the rail only appears above 1100px; the panel sidebar only appears above 900px, with a drawer replacement on phones; the body stays at 16px / 1.85 / 66ch; key choices are 48px, and the primary button, back, input box, and drawer are 44px; `prefers-reduced-motion` already fully covers existing animations. The problems below are specific breakpoints on top of that foundation, not a suggestion to overturn the existing responsive structure.

### Critical mobile blockers

#### M0.1 Scene iframe height is 0 after zoom

**Status: source-confirmed; occurs at all widths.**

- `web/src/styles.css:559-566`: `.ew-slot-full` uses `position: absolute; inset: 0; height: auto`, but the nearest positioned ancestor is `.ew-slot-wrap { position: relative }`, not the `.ew-root` the comment refers to.
- `web/src/scene.tsx:100-126`: in the full state both the iframe and the button bar leave the document flow; the wrapper has no in-flow child, the content height collapses to 0, and the iframe's top/bottom can only resolve to 0 height.
- On phones a regular scene is fixed at 320px, and zooming is the only way out to view a complex scene, so this is not a cosmetic problem.

**Recommendation**: keep the full scene in-flow (for example, the wrapper owns the overlay geometry), or put the full class on the wrapper; also add Escape to exit and `aria-expanded`, and preserve the existing correct constraint that the same iframe DOM node does not move.

#### M0.2 The delete-confirmation dialog can appear outside the current viewport

**Status: source-confirmed; triggered after scrolling a long shelf / long detail page.**

- `web/src/styles.css:213-227`: `.ew-modal-wrap` is an absolute box relative to the entire `.ew-root`; the panel is fixed at `4vh` from the top of the root, not the top of the current viewport.
- `web/src/confirm.tsx:87,219`: both delete dialogs use the same structure and only focus the panel on open, with no `scrollIntoView`.
- When deleting from the bottom of a long list, the current viewport may only show the scrim, with the dialog several screens above. The input also `autoFocus`es, and the 15px font size triggers iOS focus zoom, with the keyboard further shrinking the usable area.

**Recommendation**: keep the overlay boundary from covering the host chrome, but scroll the panel into view on open; use `dvh` to constrain the dialog body, a sticky action bar, and a 16px input font; forbid scrim/Escape close while a delete is working.

#### M0.3 The phone system Back / edge-swipe back does not go to the app's previous layer

**Status: source-confirmed.**

The shelf/detail/opening/live in `web/src/main.tsx` are all React state; the source has no `pushState`, `popstate`, or hash routing. The Android system Back and the iOS back gesture exit the current dashboard page rather than going detail -> shelf, opening -> detail, or live -> shelf. The existing visible back button should still be kept, but the browser history must reflect the layer the user entered.

#### M0.4 A question scene sits at the very end of the page, with no waiting feedback when answering

**Status: source-confirmed; the actual "how many screens from the fold" needs re-testing with real data.**

- `web/src/main.tsx:347` mounts the single `SceneSlot` after `.ew-shell`; `web/src/play.tsx` only reports the scene id, with no notice, anchor, or `scrollIntoView`. On phones the scene appears after the body, choices, input area, and two drawers.
- `onSceneChoice` directly awaits `answerScene` + `takeTurn`, without hooking into PlayPage's tapped/phrase/busy state; it does not refresh until the whole turn completes. A scene tap that may take tens of seconds looks like it did not respond.

**Recommendation**: PlayPage shows a scene-arrival notice/entry point and scrolls the scene into view; scene answers reuse the waiting and idempotent-turn semantics of a normal action.

#### M0.5 A single polling read failure permanently masks later successful data

**Status: source-confirmed.**

`load()` in `web/src/play.tsx:50-56` sets `error` on failure and, on success, only calls `setV` without clearing the old error; the render checks `error` first. During generation, even if the 3-second polling later succeeds, the player stays on the error page. Impact is highest during mobile network switches, brief offline periods, and background recovery.

### Layout defects by viewport

#### 320-430px

- **A long chip can create full-page horizontal scroll (source-confirmed)**: `.ew-chip` uses `white-space: nowrap` and has no max-width; inventory, rank, world style, opening label, and digest category can all come from the world or the narrator, so the string cannot be assumed short. A single chip should be allowed to wrap when necessary, or truncate and provide the full value.
- **The digest flex row cannot shrink reliably (source-confirmed)**: `.ew-dcat` is `flex: 0 0 auto`, and the body sibling has no `min-width: 0` / `overflow-wrap`; a long category or an unbreakable token stretches the page wide.
- **Long body tokens have no containment (source-confirmed)**: `.ew-prose` lacks `overflow-wrap: anywhere`, and code/pre have no local horizontal-scroll strategy. The default wrapping of normal CJK body text is correct, and `break-all` should not be used globally.
- **Opening history pushes the panels drawer after the entire history section (source-confirmed)**: the order in `play.tsx` is history button -> the entire History -> panels button. The longer the history, the harder the entry point to check current status becomes. The two auxiliary panels should sit side by side as tabs/disclosure, or the entry points fixed rather than pushed apart.
- **The choice confirmation can render below the fold (design defect, needs pixel confirmation)**: after clicking the last choice, the confirm row is inserted below that choice, but with no `scrollIntoView`. The choice lights up, but the submit control may not be in the viewport.
- **The input area is a non-wrapping single-line flex (potential i18n defect)**: current short Chinese/English labels still fit, but the textarea can be squeezed into a very narrow sliver by a longer locale's button. Set a usable minimum width for the input and allow the row to wrap when the constraints are insufficient.
- **The scene's regular height is fixed at 320px (needs real-scene confirmation)**: on 320x568 it occupies about 56% of screen height; the only zoom-out currently is broken by M0.1. Decide the `min()`/`dvh` strategy after fixing M0.1, rather than arbitrarily shortening it first.

#### 768px transition

- The gutter changes from 16px to 24px, still single-column reading; no premature two-column squeeze was found.
- The opening action bar needs re-testing on both sides of 768px: `.ew-spacer` is just a leftover desktop right-alignment mechanism when it wraps on mobile, and may produce an unnatural isolated gap.

#### 900px transition

- **History is hidden by mistake (source-confirmed)**: `@media (min-width: 900px) { .ew-drawer { display: none } }` hides both the history and the panel drawer; only the panel has a `.ew-aside` replacement, history does not. Between 900-1099px there is no rail either, so history is entirely unreachable; above 1100px there is likewise no replacement entry point.
- **An ended life has no panels (source-confirmed)**: the ended branch only renders history, not `panels` or `.ew-aside`, so the final state cannot be viewed at any width.

#### 1100px transition

- The grid division of labor between the rail and the reading column is correct, and replacing inline back with the rail's permanent shelf entry point is also reasonable.
- `.ew-rail` uses `max-height: calc(100vh - 120px)`, a height that depends on a hard-coded guess about the host chrome; if the real dashboard container is not the viewport scroller, sticky/height may not behave as expected. This item must be tested for real inside the host and cannot be judged failed from source alone.

### Touch, keyboard and accessibility

This round rates the 44px platform convention separately from WCAG 2.2 AA's 24px target-size floor. No SC 2.5.8 failure of `<24x24` with insufficient spacing was confirmed; the following are important 44px-convention gaps:

- `.ew-opt`, `.ew-btn-sm`, `.ew-btn-quiet`, `.ew-slot-btn` are 36px. Prioritize raising the choice confirmation, opening option, delete, and scene zoom.
- `.ew-input` and the action textarea are 15px, and iOS auto-zooms on focus; change to at least 16px.
- Several buttons removed `-webkit-tap-highlight-color` without their own `:active` feedback, so a touch feels like it did not register.

Explicit semantic/keyboard gaps:

- The visual `.ew-glabel` in `web/src/opening.tsx` is not a `<label>`, and the text/number inputs have no accessible name.
- Opening options and style pills have no `aria-pressed` or radio semantics; color is the only selected state.
- The history/panel drawers have no `aria-expanded`, `aria-controls`, and the expanded content has no named region.
- The action textarea is named only by placeholder; the name disappears after input, and there is no associated description of the character limit.
- Loading, error, stalled, scene-arrival, and delete-failure mostly have no status/alert live region; `Waiting` already has the correct pattern and can be reused.
- Modals actively remove the focus outline, have no focus trap, and do not restore the opener after close; the world-deletion `.ew-doomed` is a scrollable but non-keyboard-focusable region.
- The modal Escape and scrim can still close during the working phase, so the backend delete completes but the UI does not run `onDeleted`, leaving a stale shelf.
- Scene fullscreen has no Escape to exit and no expanded state.
- The root node does not set `lang` per the world; the language-module mutation also does not guarantee an immediate React rerender.

### Loading, error and recovery behavior

- The shelf backend error has no retry on phones; the desktop rail is not a clear retry entry point either.
- PlayPage's initial `!v` loading is only a single line of text with no Back; a pending request has no timeout/AbortController, so phones can enter a waiting page that cannot be exited.
- A history first-load failure shows an error, but a next-page failure after some turns have loaded has no visible hint or retry.
- The scene fetch has no pending state; a failure hint exists, but a new scene arriving is not announced.
- There is no offline/online, visibility, or reconnect handling; the background still polls every 3 seconds, and returning to the foreground does not refetch immediately.
- `view:'detail'` is written to localStorage, but the restore effect only restores live/opening; the detail-page memory is a dead write.
- There is no scroll reset after a view switch or after deletion returns to the shelf; the result note is at the top of the root, so the user may stay in the middle of a long list and not see the feedback.

### Recommended mobile implementation order

1. **Fix unusable paths**: M0.1 scene full geometry; M0.2 modal visibility / working-close protection; 900px history; ended panels.
2. **Fix mobile navigation and feedback**: in-app history integration; scene arrival/waiting; PlayPage clears the old error on a successful read; all critical errors offer retry/back.
3. **Fix touch and input**: 36 -> 44px; input 16px; active/focus-visible; keep the confirm row automatically visible.
4. **Fix modal a11y**: focus trap/restore, a focusable doomed region, live regions, keyboard and visual-viewport behavior.
5. **Fix content reflow**: chip, digest, prose/code, and long locales; verify together with real CJK/Latin long data.
6. **Fill in semantics**: opening labels/selected state, drawers, textarea, root language.
7. **Then do experience enhancements**: mobile information architecture for history/panels, offline/visibility, long-history performance, and scroll restoration.

### Verification matrix

| Width | Required checks | Current evidence |
|---:|---|---|
| 320x568 | shelf/detail/opening/live have no full-page horizontal scroll; all critical targets >=44px; after the keyboard opens the dialog input + action are visible; scene/confirm are not swallowed by the fold | source defects confirmed; real pixels pending a Browser driver |
| 360x800 | CJK-populated world; long chip/digest; history and panels are mutually reachable | source defects confirmed; real pixels pending a Browser driver |
| 390x844 | iPhone primary checks: focus zoom, back gesture, delete dialog, scene full, safe visible height | source defects confirmed; real device pending testing |
| 430x932 | large-screen phone: opening 4-group page and action bar wrap; long title / life delete on the same row | source defects confirmed; real pixels pending a Browser driver |
| 768x900 | 16 -> 24px gutter boundary; still a single reading column; action bar has no abnormal gap | static structure correct; boundary screenshots pending testing |
| 900x900 | `.ew-aside` appears; the panel drawer disappears; history must still exist | **current source failure: history disappears along with it** |
| 1100x900 | the rail appears; inline back disappears but the shelf path is still reachable; rail sticky height; history reachable | rail structure statically correct; **history currently fails**; host sticky pending testing |

Once visual verification is restored, the minimum automation gate should include: `documentElement.scrollWidth <= clientWidth + 1` at 320/390px; listing each non-fixed element that crosses the viewport; measuring the main content column width directly rather than only measuring overflow; opening the keyboard/dialog/scene/history states; and looking at screenshots with real Chinese fill data. Overflow results must first distinguish tables that are allowed local scroll from controls/text that are not allowed to overflow, and CJK squeezed into one character per line can only be found by looking at the image.
