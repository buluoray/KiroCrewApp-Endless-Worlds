# Scenes and backdrop

The narrator mounts purpose-built visual surfaces (maps, relationship webs, family
and skill trees, ledgers, non-list choices) and sets the background art behind a
life. It never emits markup. `widget.py` compiles a structured scene *spec* into a
self-contained HTML document; `scenes.py` (`SceneLedger`) is the mount/answer ledger
that decides what is on screen and how a player's answer comes back; `backdrop.py`
validates and stores the background image. The split is the security posture:
narrator output is data that the backend turns into bytes, and every byte the player
sees is produced locally from a closed, code-owned vocabulary.

## Layout

| Path | What it is |
|---|---|
| `backend/widget.py` | the scene compiler — `compile_scene` turns a spec into HTML; `ELEMENT_KINDS`, the geometry renderers (`_render_links`, grid/tree branches in `_element`), the CSP + constant `SCENE_SCRIPT`, `_esc`, `resolve_bind`, and the `compile_cached`/`spec_digest` cache under the run |
| `backend/scenes.py` | `SceneLedger` — per-run mount table (`mount`/`update`/`dismiss`/`mounted`), the answer channel (`answer`, `record_answer`), and `_reject_markup` |
| `backend/backdrop.py` | `compile_backdrop` (the one SVG validation funnel) + `BackdropStore` (per-turn, per-page background and its button motif) |
| `backend/mcp_server.py` | the narrator-facing tools (`_mount_scene`, backdrop set/clear) that feed specs into the compiler and ledger |
| `website/…/SceneSlot` | the single root-level iframe that renders the mounted scene (pinned by `tests/test_scene_slot.py`) |
| `backend/tests/test_widget.py` | compiler contracts — kinds, geometry, escaping, CSP, bounds, cache |
| `backend/tests/test_scene_slot.py` | the mount-stability and sandbox contracts for the iframe host |
| `backend/tests/test_result_channel.py` | the answer-channel contracts (nonce, first-result, no-write-on-reject) |
| `backend/tests/test_backdrop.py` | backdrop validation, repair, and storage contracts |

## Load-bearing contracts

### The compiler (`widget.py`)

- **The kind set is closed, and an unknown kind is refused, not skipped.**
  `ELEMENT_KINDS` is the sole allow-list; `_element` dispatches only on a member of
  it. A compiler that ignored an unknown kind would fail open, letting a spec smuggle
  intent past the boundary. `test_an_unknown_kind_is_refused_before_anything_mounts`
  pins the refusal, and `test_every_declared_kind_actually_compiles` pins the set and
  the compiler to each other so a kind cannot be added to one without the other.

- **The narrator supplies structure; the backend computes all geometry.** No
  coordinate, CSS class, or tag ever originates from narrator text. `_render_links`
  computes ring coordinates from `nodes` and `edges`
  (`test_links_draws_svg_from_nodes_and_edges_with_no_author_coordinates`) and
  rejects an edge to an undeclared node
  (`test_links_rejects_an_edge_to_an_unknown_node`). The `tree` branch builds the
  hierarchy from `parent` references and rejects a cycle
  (`test_tree_rejects_a_cycle`) while escaping every label
  (`test_tree_nests_children_under_parents_and_escapes`). The `grid` branch places
  cells from a validated integer column count and rejects one out of range
  (`test_grid_rejects_out_of_range_columns`,
  `test_grid_lays_cells_into_columns_and_escapes_labels`). Node, edge, and depth
  ceilings are legibility bounds pinned by the same tests, not restated here.

- **A scene is validated whole before any byte is emitted.** `compile_scene` builds
  the entire body or raises `SceneSpecError`; a scene never mounts half-drawn, and
  size bounds are checked first. `test_nothing_is_emitted_when_one_element_is_bad`
  and `test_an_oversized_spec_is_refused` pin it.

- **The CSP is the first byte, and it closes every route out.** `compile_scene`
  writes a `default-src 'none' … connect-src 'none'` policy at the head of the
  document. A policy that arrives after the content it governs has already lost.
  `test_the_csp_precedes_every_generated_byte` pins the ordering;
  `test_the_policy_closes_every_route_out` and `test_nothing_is_loaded_from_anywhere`
  pin that no network route survives.

- **The only script is the app's own constant, with nothing interpolated.**
  `SCENE_SCRIPT` is emitted byte-identically; it only posts `{source, sceneId,
  nonce, choice}` to the parent. This is what makes `script-src 'unsafe-inline'`
  defensible. `test_the_only_script_is_the_apps_own_constant` and
  `test_narrator_text_never_reaches_script_context` pin it.

- **Every narrator string is escaped, and markup fields are refused outright.** All
  text passes through `_esc` (`html.escape` composed with the prose frame-stripper so
  the two cannot drift); `test_hostile_text_is_escaped_not_rendered` and
  `test_a_quote_cannot_break_out_of_an_attribute` pin it. Fields carrying markup
  (`html`, `innerHTML`, `script`, `srcdoc`, `style`) are rejected by the compiler
  (`test_a_spec_carrying_markup_fields_is_refused_outright`), and the markup carriers
  (`html`, `innerHTML`, `script`, `srcdoc`) are refused again at mount by
  `SceneLedger._reject_markup` (`test_a_spec_carrying_markup_is_refused_not_stripped`)
  — so the narrator learns rather than silently loses content.

- **A bind reads state or is rejected, never left blank.** `resolve_bind` walks a
  dotted path over dict-only state and raises on a miss, because a bind is the
  narrator asserting a number exists; `test_an_unresolvable_bind_is_rejected_rather_than_left_blank`
  pins it. `_PATH_RE` plus the dict-only walk block traversal into Python internals
  (`test_a_bind_cannot_walk_into_python_internals`,
  `test_a_malformed_bind_path_is_refused`).

- **Compiled bytes live under the run, not the world.** `spec_digest` keys the cache
  on the compiler version, the state slice, and the mount nonce; the HTML is written
  under `runs/<id>/`. Specs travel between players, but bytes are always produced
  locally. `test_compiled_bytes_live_under_the_run_not_the_world` and
  `test_an_unreadable_cache_is_a_miss_not_a_failure` pin it.

### The iframe host (`SceneSlot`)

- **The scene frame is created once and never re-keyed, re-parented, or destroyed.**
  It renders at the app root outside every view branch
  (`test_the_slot_is_rendered_at_the_root_outside_every_view_branch`), is created
  lazily then kept (`test_the_slot_is_hidden_with_display_and_never_destroyed_once_created`),
  is never re-keyed (`test_the_frame_is_never_re_keyed`), and its fullscreen state is
  the same element with different geometry
  (`test_fullscreen_is_the_same_element_with_different_geometry`). Moving or re-keying
  an iframe reloads it and throws away what the player is viewing.

- **The sandbox never gains `allow-same-origin`, and content arrives as `srcdoc`.**
  The frame is `sandbox="allow-scripts allow-forms"`
  (`test_same_origin_is_never_granted`) and the HTML is handed over as `srcDoc`, never
  navigated to (`test_the_scene_is_handed_over_as_srcdoc_not_navigated_to`).

- **One turn in flight, across every surface.** A scene answer dispatches from
  `main.tsx` (`onSceneChoice`), not from the play page, so the page's own `busy`
  cannot see it — a hoisted `turnPending` lock (ref-gated against same-frame
  double taps) covers the window before the next poll reports `generating`. It is
  fed to every `SceneSlot` as `locked` (two mounted asking scenes cannot fire two
  concurrent turns) and to `PlayPage` where it folds into `busy` (choice buttons
  and the act box).

- **A slot's "sending…" state always has a way back.** `SceneSlot`'s internal
  reset watches `[sceneId, html, resetSignal]`: a refused answer or a dropped
  request leaves the html unchanged, so `onSceneChoice` bumps a `sceneEpoch`
  (passed as `resetSignal`) in its `finally` — without it the tapped slot shows
  "sending…" forever with no way to act again. A stale re-tap after a completed
  turn is refused server-side (its nonce is spent), so the reset is safe on the
  success path too.

### The answer channel (`SceneLedger`)

- **A rejected answer writes no state.** Every rejection path in `record_answer` is
  pinned to assert both the response and that nothing was persisted
  (`test_a_failure_record_does_not_touch_the_answer`).

- **The nonce is a per-mount identity: stale is refused, first-result wins.** `mount`
  issues a fresh nonce; an answer aimed at a replaced scene is refused with no write
  (`test_an_answer_aimed_at_a_replaced_scene_is_refused`), and a second answer never
  overwrites the first (`test_a_second_answer_never_overwrites_the_first`).

- **The nonce is never handed to the narrator.** The `_mount_scene` tool result
  carries only the scene id. A narrator holding a mount identity could forge an
  answer to the question it just asked — the one thing the channel exists to prevent.
  `test_the_nonce_is_never_handed_to_the_narrator` inspects the tool source and pins
  it. The page's own defenses (origin `'null'`, protocol marker, scene-and-mount
  match, local first-result latch) are pinned by the `slot_src` tests in the same
  file.

### The backdrop (`backdrop.py`)

- **The background is an inert `<img>` of validated pure SVG, not a sandboxed
  iframe.** A sandboxed `srcdoc` iframe blank-rendered inside iOS WKWebView and
  in-app webviews; an `<img>` of `image/svg+xml` sizes reliably everywhere and is the
  stronger boundary, because image-context SVG runs no script and fetches nothing
  with or without a sandbox. The real invariant is *we never run it at all*, not *we
  sanitize it well enough to run* — so the CSP/iframe surface is deliberately absent.
  The `<img>` sits behind the prose with `pointer-events:none` so a painted button
  cannot be clicked.

  > This module validates the markup but cannot enforce the delivery context. If the
  > serving layer ever inlines a backdrop as a live document instead of an `<img>`
  > source, every denylist gap below becomes reachable.

- **All storage funnels through one validation gate.** `compile_backdrop(svg)` raises
  `BackdropError` on anything unsafe, and `BackdropStore.set` validates before it
  writes a byte (`test_store_rejects_bad_markup_at_set_time_and_stores_nothing`). The
  gate refuses scripts, event handlers (`_HANDLER_RE`), `<foreignObject>`, external
  references (`_EXTERNAL_REF_RE`, including protocol-relative), and non-SVG input, and
  it is told, not silently stripped
  (`test_compile_refuses_script_handlers_foreignobject_external_and_non_svg`,
  `test_ordinary_attributes_are_not_mistaken_for_handlers`). A self-contained SVG with
  gradients, patterns, filters, and SMIL animation is accepted
  (`test_compile_accepts_a_self_contained_svg`).

- **Repair runs before the well-formedness check.** The gate injects a missing
  `xmlns`, and injects `xmlns:xlink` when an `xlink:` attribute is used but its prefix
  is undeclared, *before* parsing with `ElementTree`. Ordering the parse last means a
  merely-missing namespace is repaired rather than rejected, and a genuinely malformed
  SVG is refused so it never ships as a broken-image glyph.
  `test_compile_injects_the_namespace_when_missing`,
  `test_an_xlink_attr_without_its_namespace_is_repaired_not_broken`, and
  `test_a_malformed_svg_is_refused_so_it_never_ships_as_a_broken_image` pin the order.

- **The button motif travels with the backdrop.** `BackdropStore` keeps a companion
  button-motif SVG alongside the background, validated the same way, so a page's
  buttons always match its scene; replacing the backdrop without a new motif drops the
  old one (`test_store_keeps_a_common_buttons_motif_with_the_backdrop`,
  `test_store_rejects_bad_buttons_motif`). The backdrop is bound to the turn and
  restored per page (`test_backdrop_is_bound_to_the_turn_and_restores_per_page`); a
  corrupt store file reads as no background, never an error
  (`test_store_treats_a_corrupt_file_as_no_background`).
