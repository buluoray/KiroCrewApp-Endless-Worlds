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
| `backend/backdrop.py` | `compile_backdrop` (the one SVG validation funnel) + `BackdropStore` (per-turn desktop/mobile backgrounds and button motif) |
| `backend/mcp_server.py` | the narrator-facing tools (`_mount_scene`, backdrop set/clear) that feed specs into the compiler and ledger |
| `web/src/scene.tsx` | the single root-level iframe that renders the mounted scene (pinned by `backend/tests/test_scene_slot.py`) |
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
  `test_grid_lays_cells_into_columns_and_escapes_labels`). A cell's `mark` carries
  two separable intentions: a STRING is that cell's own symbol and renders as an
  escaped badge, while `true` tints the whole cell. A symbol deliberately does not
  also tint — a narrator marks every cell of a map with its own symbol, and tinting
  on any mark rendered all of them identically while dropping the symbols entirely.
  A string past `MAX_MARK` is dropped whole rather than cut, because truncating an
  emoji's codepoint sequence renders a lone joiner or variation selector.
  `test_a_cells_symbol_mark_is_rendered_and_does_not_tint_every_cell`,
  `test_a_true_mark_still_tints_the_cell_and_draws_no_badge`,
  `test_a_mark_that_is_not_a_symbol_draws_nothing_rather_than_a_cut_one`, and
  `test_a_symbol_mark_is_escaped_like_any_other_narrator_text` pin it. A grid's rows
  are sized by their content and never by the room around them: `align-content`
  otherwise defaults to stretch and shares any surplus out among the auto rows, so a
  grid box taller than its rows turned six short map labels into 236px boxes holding
  57px of text — the shape a real phone showed. Both `align-content: start` and
  `grid-auto-rows: min-content` are declared, deliberately redundantly, because what
  gives that box its height on a phone is not reproducible off-device.
  `test_a_grid_row_is_sized_by_its_content_not_by_the_room_around_it` pins both.
  Node, edge,
  and depth ceilings are legibility bounds pinned by the same tests, not restated
  here.

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
  and is never re-keyed (`test_the_frame_is_never_re_keyed`). Moving or re-keying
  an iframe reloads it and throws away what the player is viewing. The frame has no
  fullscreen affordance (`test_the_scene_has_no_fullscreen_affordance`): keeping it
  inline avoids covering dashboard chrome on desktop and colliding with the
  portalled tab bar on mobile.

- **The frame is as tall as its picture, and the picture paints its own canvas.**
  One fixed height for every spec was wrong in both directions: a three-row ledger
  sat in a dead band, and a map taller than the frame lost its last row to
  `overflow: hidden` with nothing to scroll. The frame has an opaque origin, so the
  host cannot measure inside it — `SCENE_SCRIPT` reports the CONTENT's own extent
  (the furthest child's bottom plus that child's bottom margin, plus the body's
  bottom padding) on load and through a `ResizeObserver`, and `SceneSlot`
  applies it clamped between `MIN_SCENE_H` and `MAX_SCENE_H`; the stylesheet's
  `.ew-slot-on` height stands in until the first report. It measures the content and
  never `body`'s or `documentElement`'s own box: both track the frame's viewport when
  the document is shorter, so a frame sized from either can never shrink, and a phone
  showed a body inflated well past its content. A height message is not an
  answer: it is handled before the answer guards, so it neither fires a turn nor
  trips the first-result latch. `_STYLE` colours `html` as well as `body`, because
  the part of a frame a short document does not cover is painted by the canvas —
  left transparent, it showed the host page through. Pinned by
  `test_widget.py::test_the_frame_reports_its_own_content_height`,
  `test_the_documents_canvas_is_painted_not_just_its_body`,
  `test_scene_slot.py::test_the_frame_is_sized_from_the_documents_own_report`,
  `test_a_height_report_is_not_an_answer`, and
  `test_the_slot_surface_does_not_follow_the_dashboard_theme`.

- **The sandbox never gains `allow-same-origin`, and content loads through `src`.**
  The frame is `sandbox="allow-scripts allow-forms"`
  (`test_same_origin_is_never_granted`), so the scene document has an opaque origin
  even though `get_scene` serves the compiler-owned bytes as `text/html`. `get_scene`
  repeats that sandbox in the HTTP CSP response header and limits `frame-ancestors`
  to `'self'`; therefore opening the authenticated URL as a top-level document does
  not restore its origin privileges, and another site cannot embed it. `SceneSlot`
  first fetches the bytes to distinguish loading from failure, then points `src` at
  the authenticated scene URL with a version token derived from those bytes; the
  token changes only when the scene content changes. This replaces `srcdoc`, which
  blank-rendered in WebKit/iOS WKWebView, without granting the document access to
  the dashboard. The CSP-first compiler output and escaped narrator text remain the
  document-level defenses. Enforced by `routes.get_scene`; pinned by
  `test_scene_document_is_response_sandboxed_even_when_navigated_directly` and
  `test_the_scene_is_loaded_as_a_sandboxed_src_document`.

- **A requested backdrop publishes atomically with its page — never mid-read and
  never prose-first.** The narrator records a short brief for the pending turn and
  commits the turn without authoring SVG. The committed state remains internal
  while that durable brief exists: `get_run` serves the previous state and
  turn-truncated chronicle with the ordinary generation progress, and a second turn
  is refused. `BackdropStore.exact(turn)` distinguishes art created for this page
  from an older backdrop that merely remains effective through `at(turn)`. Only the
  exact commit clears the brief; the next poll then reveals prose, state, choices,
  button motif, and the coordinated desktop/mobile backdrop set together. Both SVGs
  are validated before the single history entry is written, so one invalid variant
  publishes neither. The live page pins its selected image URL to `?turn=` and
  double-buffers image decoding, so publication and viewport changes never flash a
  blank background.

- **The lane is the storyteller's decision, executed — never re-routed — by the
  illustrator.** The narrator's brief opens with `LANE: motif` (the default: an
  abstract force, perception, emotion, atmosphere, or change made visible) or
  `LANE: scene` (a concrete environment whose real spatial structure must remain
  recognizable). The routing test is semantic: “what does this place physically
  look like?” selects SCENE; “how does this force, feeling, perception, or
  transformation appear?” selects MOTIF. A motif brief carries one `THESIS:` naming
  the invisible dramatic fact or emotional logic to make felt, never a proposed
  geometry or visual solution, and optionally one intrinsic `MOTION:` verb. A scene
  brief carries `REFERENCE:` keywords. Either may carry a `PALETTE:` ramp. The
  illustrator never re-routes and
  treats a missing lane line as MOTIF. Pinned by the lane pins in
  `test_backdrop_guidance_is_an_art_brief_not_a_rendering_recipe`.

- **The SCENE lane's underlay never enters the model's context.** For pages that
  need a concrete place, `endless_trace_reference` searches attribution-free
  archives by lane. The default `photo` lane queries **Openverse** — a
  Creative-Commons aggregator spanning Wikimedia Commons, Flickr and museum feeds,
  filtered server-side to CC0 + Public Domain Mark, a far larger usable pool than
  Commons alone — and falls back to **Wikimedia Commons**. The `art` lane queries
  the **Met** (public-domain artworks) and then the **Smithsonian** (only when an
  `SI_API_KEY` is set; inert otherwise). Every candidate is kept only when its
  license reads as CC0 or public domain; CC BY, BY-SA, NC, and ND sources are
  excluded, so publication cannot silently lose attribution or share-alike
  obligations. Fetches require HTTPS and an exact host from a fixed allowlist
  (`_ALLOWED_FETCH_HOSTS`: Commons plus `api.openverse.org`,
  `collectionapi.metmuseum.org` / `images.metmuseum.org`, and `api.si.edu` /
  `ids.si.edu`); credentials in URLs, off-host redirects, and an off-host final
  response URL are refused. Image bytes are pulled only through vetted proxy/host
  endpoints — Openverse hands back a thumbnail on its OWN host even when the
  original lives on a third-party CDN — so the SSRF surface stays the allowlist.
  The selected source's title, page URL, and license are copied into the same
  durable `BackdropStore` history entry as the final SVG before the private trace
  is cleared, preserving provenance without requiring player-facing attribution UI.

- **Recall: a specific brief used to match nothing, so the lane missed on every
  good-faith attempt.** Both backends match CONJUNCTIVELY, and the Illustrator is
  asked to write a `REFERENCE` line of concrete keywords — so the better the brief,
  the more certainly it returned zero. Measured live: an 18-word river-mill brief
  returns **0** hits on Commons *and* **0** on Openverse, while its first two words
  return several. `search_candidates` therefore walks a bounded ladder — the full
  query, then `_LADDER_RUNGS` truncations, front words first because a brief leads
  with its subject and trails into atmosphere — and stops at the first rung that
  matches, reporting which rung won.

  The ladder **floors at four words**, and that floor is the judgement: two words
  stop being about the subject (the river-mill brief's two-word rung matched an
  amphora and a manuscript page), and an unrelated photograph traced *as the place*
  is worse than the honest procedural base — confidently wrong rather than merely
  plain. Below the floor the lane declines.

  Two more gates were measured into place. Commons adds `filetype:bitmap` and
  samples `_RAW_SEARCH_ROWS` rather than twice the wanted count, because its
  attribution-free material skews to scanned BOOKS: a four-word village query
  returned ten pages whose every public-domain hit was a PDF or DjVu scan and whose
  every photograph was CC BY-SA, so nothing survived the gates on a query that HAD
  matched — widening the same single request took a night-castle query from zero
  usable rows to ten. And `_looks_like_document` drops a *rephotographed* document,
  which no MIME gate can catch: a live castle query returned two handwritten letters
  ABOVE the one real castle, as ordinary JPEGs, and the caller traces the FIRST
  candidate that fetches. Neither letter carried a document category — what named
  them was the description, which opened "Manuscript letter" — so the judgement
  reads categories, object name, and only the description's LEAD
  (`_DESCRIPTION_LEAD`), since an incidental "carved letters above the arch" further
  down must not drop a real scene. Openverse and the Met expose only a title, so
  that is what they pass.

  **Openverse's own `category=photograph` filter is deliberately NOT used.** It
  exists (`{digitized_artwork, photograph, illustration}`) and looks like the
  structural version of the same gate, but the field is sparsely populated: measured
  live, `gothic cathedral nave vaulted` returns 15 results plain and **0** with the
  filter. It converts hits into misses, so the client-side gate stays.

- **The brief names its SUBJECT separately, because the words that would match are
  usually already in it.** This is the upstream half of the recall fix above, and it
  came from measuring what the ladder could not reach. On the only two real briefs
  recorded, the front held the era and the photographable subject sat in the MIDDLE:

  | queried alone | usable candidates |
  |---|---|
  | `thatched roofs` / `thatched cottage` / `harvest wagon` | 5 / 5 / 5 |
  | `stone keep` / `stone bridge` / `walled town` | 5 / 5 / 5 |
  | `river valley` / `watermill` / `village lane` | 5 / 5 / 5 |
  | the whole 18-word brief containing all of them | **0** |

  Every one of those subjects was already inside a brief that returned nothing, so
  the ladder's front-truncation never reached them (both briefs open with `medieval
  European …`). Quoting the leading phrase was tested and does NOT help here —
  `"medieval European farming"` returns 0 exactly as the bare form does — so the
  remedy is not a smarter query shape but naming the subject:

  `REFERENCE: subject="thatched cottage"; context="medieval northern Europe, autumn
  dusk, muddy lane after rain"`

  Only `subject` is searched, and it is searched as EVERY word at once; `context` is
  the illustrator's to draw with and never reaches an archive. The tool's own `query`
  description carries the same rule, since that schema is the only machine-readable
  instruction the Illustrator gets — and its previous example (`'stone bridge river
  mist'`) invited exactly the query shape that returns nothing.

- **A total miss offers a way back, and a different one per reason.** A base underlay
  used to be reported as a finished outcome ("here is a tonal base, compose over
  it"), which left no route out of a miss the Illustrator could have fixed in one
  call. `_base_underlay_next` now branches on the audit: `no-candidates` asks for one
  retry with the bare subject and shows what a subject looks like (the miss cache
  makes that retry nearly free); `search-failed` asks for a retry with the SAME words,
  because the archive not answering says nothing about the query and rewording it
  would be superstition; `fetch-failed` and a page that asked for no photograph get
  no retry at all. Pinned by
  `test_a_total_miss_offers_a_way_back_and_names_the_subject_rule` and
  `test_the_query_contract_asks_for_a_subject_not_a_scene`; the illustrator prompt's
  half by `test_backdrop_guidance_is_an_art_brief_not_a_rendering_recipe`.

- **A brief that declared SCENE cannot be published as a hand-drawn motif.** The
  request record now stores the `lane` parsed from the brief's first line
  (`store.brief_lane`, parsed once at request time), and `_require_scene_underlay`
  refuses a draft or a commit for a `scene` brief when no trace record exists.

  Nothing checked this before, and the hole was invisible by construction:
  `_apply_underlay` requires the `etr-underlay` placeholder only when a trace record
  EXISTS, so an Illustrator that skipped `endless_trace_reference` entirely and
  hand-drew the page committed cleanly and was stored as an ordinary motif — no
  underlay, no receipt, nothing recording the intent. A real page did exactly that,
  and afterwards nothing could tell whether the narrator had asked for a motif or the
  scene lane had been quietly abandoned, because the brief is cleared the moment art
  commits. The receipt could not help either: a motif page correctly has none.

  Three deliberate edges. A **base** underlay satisfies the gate — it asks whether
  the lane RAN, not whether a photograph was found, so a search that legitimately
  found nothing still publishes. `brief_lane` is **lenient**: an odd or absent header
  yields `""` and is not enforced, because losing a page's art over a header is worse
  than not enforcing the lane on that page. And `endless_commit_fallback_backdrop` is
  **not** gated: it is the repair path for a page whose illustrators already failed,
  and refusing it would leave the page with no art at all. The gate runs at draft
  submit (so the Illustrator learns before rendering previews) and again at commit,
  because the draft store survives a restart and a draft accepted before the gate
  existed must not walk through it. Pinned by
  `test_a_scene_brief_cannot_be_published_as_a_hand_drawn_motif`,
  `test_a_motif_brief_is_still_free_to_be_hand_drawn`,
  `test_a_base_underlay_satisfies_the_scene_gate`, and
  `test_an_undeclared_lane_is_not_enforced`.

- **The MOTIF second pass is earned, not owed.** It was unconditional — "the first
  rendered draft is diagnosis, never the final" — which made MOTIF the most expensive
  lane in the app: two complete SVG sets (desktop 800×600 + mobile 450×900, four
  documents) and two rounds of preview `read`s on every page, whether or not the
  first draft had anything wrong with it. Measured against a real page, the
  illustrator took ~3 minutes where the narrator's text turn took ~60 seconds, and
  SCENE was already the cheaper lane because it permits a first-draft final.

  The review itself is unchanged: name the single weakest or most generic decision.
  What changed is that a revision now requires that weakness to be **real** — when
  the first draft already carries a specific authored idea and the review finds
  nothing structural to fix, it commits. A revision made because the process expects
  one adds elaboration rather than authorship. Still never a third draft. This is a
  deliberate trade of a quality guarantee for latency; the guarantee it replaces was
  a process rule, not a measurement. Pinned by
  `test_backdrop_guidance_is_an_art_brief_not_a_rendering_recipe`.

- **Cost: a source is asked once per subject, and only when it might answer.**
  Wikimedia rate-limits a burst — an unbounded probe earned a 429 inside about
  twenty calls — and every request also costs the player latency, so three
  mechanisms bound them. The source loop STOPS once `limit` candidates are in hand
  instead of always querying every source (it previously spent a Commons request
  even when Openverse had already returned enough, buying candidates nobody would
  reach). The ladder stops at the first rung that matches. And `MissCache` records
  which `(source, query)` pairs answered with nothing usable, so a subject with no
  attribution-free photograph is discovered once rather than once per page.

  The cache is only safe because of three deliberate constraints:

  1. **A `SearchUnavailable` is never recorded.** Every source used to collapse a
     failed REQUEST and a genuine miss into `[]`; they are now different facts,
     because one rate-limited minute would otherwise mark a subject imageless for a
     fortnight.
  2. **The key carries a `_search_fingerprint()`** over the license gate, format
     gate, document gate, sample width and rungs. Changing any of them retires every
     stale negative — without it, fixing a filter would keep answering "no image"
     from a cache built under the old rules, and the fix would look like it had not
     worked. This is the nastiest shape the feature could take.
  3. **Entries expire (`_MISS_TTL_SECS`) and the file is capped
     (`_MISS_CACHE_CAP`, oldest evicted).** The corpora grow, so "this subject has no
     photograph" is true of a moment, not forever.

  The key is a query's lowercased word SET, not its string: a conjunctive match does
  not depend on word order, so the same words in another order are the same negative
  fact. Per SOURCE rather than per query, because Openverse missing while Commons
  hits is the normal case and a composite negative would throw that away.

  Pinned by `test_the_ladder_widens_a_specific_brief_and_stops_at_the_first_rung`,
  `test_the_commons_search_excludes_book_scans_and_samples_wide`,
  `test_a_rephotographed_document_is_not_a_reference_photograph`,
  `test_the_search_itself_drops_a_document_that_outranks_the_subject`,
  `test_a_satisfied_lane_does_not_pay_for_the_next_source`,
  `test_a_source_that_answered_with_nothing_is_not_asked_again`,
  `test_a_rate_limited_search_is_never_cached_as_a_world_without_photographs`,
  `test_a_recorded_miss_expires_and_does_not_outlive_a_filter_change`, and
  `test_the_miss_cache_is_bounded_and_evicts_the_oldest`.

  The same photo is cover-cropped separately for desktop and mobile. The first
  attempt uses `(0.5, 0.5)` for both; if a preview clips decisive structure, the
  illustrator may spend its single retry on independent `desktopFocalX/Y` and
  `mobileFocalX/Y` controls (`0` is left/top, `1` is right/bottom). Pillow checks
  the actual decoded format, per-axis dimensions, and total pixels before full
  conversion. Pillow/vtracer work runs in a killable child process bounded by
  `TRACE_TIMEOUT_SECS`; the parent also caps input/output bytes and validates the
  returned fragment through `compile_backdrop` before trusting it. A fetch/trace
  pass that fails EVERY candidate is retried a bounded `_FETCH_RETRY_ATTEMPTS` times
  with a short `_FETCH_RETRY_BACKOFF_SECS` pause before the lane records
  `fetch-failed` — the search is not repeated, only the fetch. A backdrop is never
  re-fetched on a later turn, so without this a one-second network blip or a 429 on
  the image host would cost that page its photo permanently; the happy path breaks on
  the first success and never sleeps. Pinned by
  `test_a_transient_fetch_failure_is_retried_before_settling_for_base`.

  The resulting fragments are the Illustrator's to choose among. Up to
  `TRACE_CANDIDATE_COUNT` (3) references are traced and stashed in `CandidateStore`
  (keyed to run + turn); `endless_trace_reference` returns one raster preview set
  per candidate and sets NO active underlay. The Illustrator reads every
  candidate's previews and calls `endless_select_reference` with the chosen
  `index`, which promotes that candidate into the active `TraceStore` underlay and
  clears the rest — so the curation of which reference best fits the brief is the
  drawing agent's, not a blind "first that traced". When a MULTI-WORD query matches
  nothing, the tool does NOT settle immediately: it returns `underlay: none` with a
  directive to call `endless_trace_reference` once more with the single most-relevant
  noun (only the narrow CC0/PD slice is searched, so a compound subject misses while
  its head noun hits), and creates no base — the scene gate then refuses a commit
  until a trace exists, so the retry is enforced, not merely advised. A single-word
  miss, a transient error, or a second miss (bounded by `_TRACE_RETRY_CAP`) settles a
  single procedural tonal base active directly. The active fragments live in
  `TraceStore` keyed to the run and turn;
  the Illustrator places one
  `<g id="etr-underlay"/>` per SVG (single or double XML quotes are accepted),
  which the server splices at draft AND commit time (`compose_with_underlay`). Once
  a trace exists, each variant must contain exactly one recognized placeholder;
  omission, duplication, a missing fragment, or any unresolved `etr-underlay`
  marker is refused rather than silently publishing hand-drawn-only scene art. If
  the underlay already carries the composition, the overlay may contain zero marks;
  sparse architecture/light marks are added only when they materially clarify the
  scene. Motif documents remain untouched when no trace exists, while a
  placeholder without a stored trace is refused.

  Publication copies a sanitized trace receipt into the same durable
  `BackdropStore` history entry before private fragments are cleared:
  `pipeline: trace`, `underlay: reference|base`, the opaque `fragmentId`, final
  query, and `used: true`. `GET /runs/{runId}` exposes the current receipt in
  backdrop metadata, and chronicle rows expose the receipt effective on each page.
  This makes a completed SCENE pipeline auditable after security logs and preview
  files rotate; photo-backed entries additionally retain their source provenance.
  When no usable reference exists the tool degrades to a
  procedural tonal base, and that `underlay: base` result is still composed and
  recorded rather than becoming indistinguishable from a motif. The
  composed-document ceiling is `MAX_BACKDROP_BYTES` (1MB); hand-drawn tool inputs
  stay schema-capped at 24KB. Pinned by `backend/tests/test_phototrace.py` and
  `backend/tests/test_backdrop.py`.

- **Backdrop-agent failure stays behind the curtain, and a timed-out scene never
  falls through to the narrator hand-drawing one.** The brief is cleared on successful commit, not on dispatch, so
  a dropped request or gateway restart can resume recovery. The backend gives the
  model a whole-recovery budget of `_BACKDROP_FALLBACK_SECS` (120s) across its
  illustrator attempts. When that budget elapses without an exact commit, the server
  publishes the traced underlay ALONE as the page's backdrop — `commit_underlay_only`
  composes the stored desktop/mobile fragment (a traced photo, or the procedural
  base) into a bare `etr-underlay` placeholder shell and writes it through the normal
  `BackdropStore.set`, with a `serverFallback: true` receipt. The overlay was always
  optional, so this is a complete, real image produced with NO model call — it
  replaces the old path where a timed-out scene fell through to the narrator
  hand-drawing one. Only a page with no traced underlay at all (a motif page, or an
  illustrator that never reached the trace tool) still queues the internal repair
  message in the same narrator slot, which may send a simpler brief or draw directly
  through the separate `endless_commit_fallback_backdrop` capability. That handler
  requires a persisted same-run/same-turn fallback gate, so merely possessing the
  tool cannot bypass the illustrator during an ordinary turn. The player sees only
  the existing generation state, never an implementation failure or retry control.
  Pinned by `test_the_server_publishes_the_base_underlay_when_the_model_never_commits`,
  `test_the_server_fallback_is_a_noop_when_nothing_was_traced`,
  `test_two_failed_illustrators_notify_the_same_narrator_behind_the_gate`,
  `test_successful_illustrator_commit_clears_the_waiting_request`, and
  `test_narrator_fallback_commit_is_refused_until_recovery_opens_its_gate`.

- **A base's degradation depends on WHY the photo search missed.** When the trace
  returns `underlay: base` the illustrator follows the result's `next`. A *transient*
  miss (`search-failed` / `fetch-failed`) leaves a finished tonal backdrop to commit
  as-is (one placeholder, no other marks). But a `no-candidates` miss is terminal —
  the forced single-keyword retry already ran and still found nothing, so no
  free-license photograph exists for this page — and the base is then only a tonal
  GROUND: the illustrator authors a hand-drawn scene over it (photographic realism is
  not required — an abstract, artful evocation of the place is welcome), with the full
  review pass, rather than committing bare tonal bars that read as flat. Committing
  the base ALONE is reserved for the timeout safety net (`commit_underlay_only`),
  never the intended output of a no-candidates page. The instructions live in
  `agents/illustrator.json` and `_base_underlay_next`.

- **The backdrop pipeline is timed for audit.** `backdrop_timing.py`'s
  `BackdropTimeline` appends one event per pipeline step to
  `runs/<id>/backdrop-timeline.jsonl` — `requested`, each backdrop tool call (with its
  server-side `serverMs`), the recovery attempts, and the server fallback. `call_tool`
  records the tool events centrally, so the GAP between two events is the model's own
  thinking/generation time, told apart from measured server work. `GET
  /runs/{runId}/backdrop-timeline?turn=N` returns the ordered events plus a summary
  naming the single longest gap and the slowest server step, so "which step stuck the
  longest" is answerable after the fact. Diagnostic only — nothing reads it to make a
  decision. Pinned by `backend/tests/test_backdrop_timing.py`.

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

- **A corrupt optional ledger degrades to no mounted scenes.** Malformed JSON in
  `scenes.json` is logged and read as an empty ledger without rewriting the damaged
  bytes; the next explicit mount can recover through the normal atomic write path.
  Real filesystem errors still raise rather than masquerading as empty content.
  Enforced by `SceneLedger._read`; pinned by
  `test_a_corrupt_scene_ledger_degrades_to_no_mounted_scenes`.

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
  `BackdropError` on anything unsafe, and `BackdropStore.set` validates desktop,
  optional mobile, and optional button SVGs before it writes a byte
  (`test_store_rejects_bad_markup_at_set_time_and_stores_nothing`,
  `test_store_rejects_bad_mobile_atomically`). The
  gate refuses scripts, event handlers (`_HANDLER_RE`), `<foreignObject>`, external
  references (`_EXTERNAL_REF_RE`, including protocol-relative), and non-SVG input, and
  it is told, not silently stripped
  (`test_compile_refuses_script_handlers_foreignobject_external_and_non_svg`,
  `test_ordinary_attributes_are_not_mistaken_for_handlers`). A self-contained SVG with
  gradients, patterns, filters, and animation — both SMIL and inline CSS (a `<style>`
  block with `@keyframes`, or `style=` transitions) — is accepted; only SCRIPTS are
  inert in the image context, so declarative CSS animation plays, and the gate blocks
  only `@import` and external `url()`
  (`test_compile_accepts_a_self_contained_svg`, `test_compile_accepts_inline_css_animation`).

- **Repair runs before the well-formedness check.** The gate injects a missing
  `xmlns`, and injects `xmlns:xlink` when an `xlink:` attribute is used but its prefix
  is undeclared, *before* parsing with `ElementTree`. Ordering the parse last means a
  merely-missing namespace is repaired rather than rejected, and a genuinely malformed
  SVG is refused so it never ships as a broken-image glyph.
  `test_compile_injects_the_namespace_when_missing`,
  `test_an_xlink_attr_without_its_namespace_is_repaired_not_broken`, and
  `test_a_malformed_svg_is_refused_so_it_never_ships_as_a_broken_image` pin the order.

- **The coordinated variants and button motif travel as one entry.** `BackdropStore`
  keeps required desktop `markup`, optional portrait `mobile`, and optional button
  motif under one turn/version. Replacing an entry without either optional SVG drops
  the old one; no variant can drift to a different turn
  (`test_store_keeps_a_mobile_variant_with_the_desktop_backdrop`,
  `test_store_keeps_a_common_buttons_motif_with_the_backdrop`). The HTTP route serves
  desktop by default, selects mobile with `?variant=mobile`, and falls back to desktop
  for legacy entries; `part=buttons` remains orientation-independent and takes
  precedence (`test_backdrop_route_selects_variants_and_preserves_legacy_fallback`).
  The set is bound to the turn and restored per page
  (`test_backdrop_is_bound_to_the_turn_and_restores_per_page`); a corrupt store file
  reads as no background, never an error
  (`test_store_treats_a_corrupt_file_as_no_background`).

- **Backdrop guidance is an art brief, not a rendering recipe.** The packaged
  illustrator receives only the page inputs and commits one coordinated set: desktop
  `markup` at 800×600 and portrait `mobile` at 450×900. Both share a palette, visual
  thesis, motif grammar, and optional motion verb, but each frame is composed
  independently; mobile is never a crop or scaled desktop copy. MOTIF is the default
  lane. The brief supplies meaning, emotional temperature, world character, and the
  desired difference from recent backdrops, but never a visual recipe. Before
  drawing, the illustrator silently develops multiple substantially different
  concepts, rejects literal summaries, obvious symbols, generic screensaver
  treatments, and repeated composition families, then chooses the most
  world-specific metaphor with the strongest compositional tension and emotional
  afterimage. No shape family or SVG technique is mandatory; formal choices must be
  earned by the selected concept. SCENE is reserved for recognizable environmental
  structure and enters the trace pipeline. Calm reading fields come from
  low luminance, scale, and contrast; portrait art avoids full borders, left/right
  pair dependence, and bright central motifs. For visual review, the illustrator
  first submits the complete desktop/mobile set as an unpublished draft. The server
  validates every SVG, rejects off-box file/data/network references before
  rendering, and creates bounded PNG previews outside the public
  `BackdropStore`. The whole renderer chain runs in a separate killable process
  bounded by `RENDER_TIMEOUT_SECS`, so a pathological draft (deep filter stacks
  can make cairo rasterization spin) times out instead of wedging the MCP server;
  the parent trusts only its own PNG signature and dimension check, never the
  child's exit status. The illustrator reads every first-draft preview together as
  images and judges the coordinated set. MOTIF always treats that first render as
  diagnosis: it identifies the weakest or most generic artistic decision, makes one
  structural revision, submits a replacement draft, reads the replacement previews
  together, and commits only that reviewed second `draftId`. SCENE may keep a strong
  first draft, but any revision must likewise be resubmitted and visually reviewed;
  unrendered final markup is never published. Draft submission neither clears the
  waiting request nor makes art visible to live play, history, or shelf surfaces;
  only the final atomic write does. Enforced by
  the `prompt` and path-restricted `read` capability in
  `agents/illustrator.json`, the draft/final handlers in `backend/mcp_server.py`,
  and `BackdropDraftStore`; pinned by
  `test_backdrop_guidance_is_an_art_brief_not_a_rendering_recipe` and the backdrop
  draft-store/MCP tests.
