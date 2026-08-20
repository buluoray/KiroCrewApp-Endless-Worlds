# Surface (manifest, routes, MCP server)

Endless Worlds is an external KiroCrew app whose backend is **hooks-only**: it
runs inside the gateway process and exposes two distinct surfaces over the same
on-disk data dir. The **HTTP route surface** (`backend/routes.py`) is
player-facing and called by the SPA; the **MCP server** (`backend/mcp_server.py`)
is agent-facing and reached over stdio. Two app-owned agents drive the MCP
surface — a **narrator** that lives one run turn by turn, and a **worldsmith**
that compiles pasted text into a playable world. Because a hooks-only backend
has no long-lived port, stdio is the only viable MCP transport, and both
processes self-locate the same data dir so routes and tools see one set of files.

## Layout

| Path | What it is |
|---|---|
| `app.json` | manifest: `ui.pages`, `backend.hooks.routes`, `mcpServers.endless-mcp`, `agents[]`, `permissions` |
| `agents/narrator.json` | the narrator agent (`name: endless-narrator`) — lives one run |
| `agents/worldsmith.json` | the worldsmith agent (`name: endless-worldsmith`) — compiles pasted text into a world |
| `backend/routes.py` | the player-facing HTTP surface — `register_routes(ctx)`, every handler auth-gated and validated |
| `backend/memory_routes.py` | the star-map / keepsakes / story-card / legacy routes, spliced into the surface via `memory_routes()` |
| `backend/mcp_server.py` | the stdio MCP server: the `_TOOLS` list, derived `_INPUT_SCHEMAS`, `STATE_WRITERS`, `call_tool` validate-then-dispatch, and the narrow capability handles |
| `backend/narrator.py` | narrator slot ownership, the namespaced tool ref, memory isolation, and the packaged agent's approval-free `allowedTools` |
| `backend/drafts.py` | the world-draft store behind the draft-then-compile pipeline |
| `backend/turn.py` | `advance_turn(...)` + `make_dispatcher(...)`, the one orchestrator both `/turn` and `/open` call |

## Load-bearing contracts

### Manifest

- **A backend is hooks-only.** `app.json` declares `backend.hooks.routes:
  "backend.routes:register_routes"` and nothing else — no long-lived server, no
  port. `register_routes(ctx)` runs in the gateway process. The MCP server is a
  *separate* stdio process, which is why it must self-locate the data dir rather
  than share the hook's `ctx`.

- **Both agents must be listed in `agents[]` AND carry a matching `name`.** The
  manifest lists `agents/narrator.json` and `agents/worldsmith.json`; each file's
  `name` field (`endless-narrator`, `endless-worldsmith`) is what actually
  materializes and dispatches — a file present on disk but absent from `agents[]`,
  or present in `agents[]` with no `name`, is not registered. The narrator's
  registration is pinned by `test_narrator.py::test_the_agent_is_registered_in_the_manifest`.

- **The app's own MCP server is referenced by its NAMESPACED key.** Agents
  reference `@endless-worlds:endless-mcp`, not the bare `@endless-mcp`; the bridge
  registers the server under `f"{app}:{server}"`, and the bare form resolves to
  zero tools with no error. The narrator holds this as `OWN_SERVER_REF` in
  `backend/narrator.py`. Pinned by
  `test_narrator.py::test_the_tool_ref_uses_the_namespaced_key_registration_actually_writes`
  and end-to-end launchability by `test_the_apps_own_server_is_launchable_as_an_external_app`.

- **`mcpServers.endless-mcp` uses absolute paths only.** The command is `python3`
  with an absolute script path and an absolute `PYTHONPATH`. An external app gets
  no `${APP_DIR}` or `~` expansion — args and env are passed verbatim — so a
  relative path or a tilde would fail to launch. That the agent declares no MCP
  server of its own (the manifest owns the launch spec) is pinned by
  `test_narrator.py::test_the_agent_declares_no_mcp_servers_of_its_own`, and the
  absence of an unresolvable placeholder token by
  `test_no_unresolvable_placeholder_token_in_the_agent_file`.

- **`permissions.storage: true` is required, and `/health` proves it.** The App
  Kit context only populates `ctx.storage` for a service the manifest declares;
  with `storage` off, `ctx.storage` is `None`. `GET /health` is therefore a real
  storage probe — it round-trips storage rather than returning a static `ok`, so a
  misdeclared permission fails loudly at the health check instead of silently at
  the first write.

- **`permissions.network: false`; the worldsmith's web tools are agent scope, not
  app permission.** The app itself makes no outbound network calls. The
  worldsmith reaches `web_search` / `web_fetch` because those are declared in its
  *agent* `tools`/`allowedTools`, which is a different grant layer from the app's
  `permissions.network`. Turning `network` on would widen the app's own surface
  for no reason the agent tools do not already cover.

### Routes (`backend/routes.py`)

- **Every handler gates on the injected user.** Each `async (request, ctx)`
  handler begins by treating `request.get("user") is None` as `401`
  (`_unauthorized()`). The platform injects `user`; the app carries no other
  authz. This is uniform across all endpoint groups — health/settings, worlds,
  runs/lives, scenes, backdrop, world-drafts, and the spliced memory routes.

- **A gone or damaged life answers a status code, never a 500.**
  `store.read_state` never returns a falsy value — it raises — so a bare
  `if not state:` guard after it is dead code and the exception becomes a 500 on
  a surface the play page polls every 3 seconds. Every player-reachable handler
  that loads run state goes through `_load_run_state`, which maps `StoreError`
  to `404` ("no such life") and `CorruptRunState` to `422` ("this life is
  damaged"); `answer_scene` maps its `SceneLedgerError` on construction to `404`
  the same way. `advance_run_turn` loads state *before* its `already_committed`
  chronicle scan so a ghost life cannot 500 out of the scan either. Pinned by
  `test_route_errors.py` (ghost life polls as 404 everywhere, damaged life as
  422, malformed id as 4xx).

- **Create-then-open and draft-then-compile are split for retryability.**
  `create_run` writes the life to disk *before* asking the narrator for the
  opening turn, and `open_run` is a separate idempotent call (turn ≥ 1 returns the
  existing first turn) — so a narrator timeout leaves a retryable life, never
  nothing, and a slow success never narrates a second first turn. The world-draft
  pipeline mirrors this: `POST /world-drafts` stores pasted text before any agent
  runs, `POST …/compile` writes a pending marker before dispatch and refuses a
  double-dispatch, and `POST …/install` requires status `ready`. The dispatch
  record existing before the narrator is spoken to is pinned by
  `test_pending.py::test_the_record_exists_before_the_narrator_is_spoken_to`, and
  the no-double-dispatch guard by `test_asking_twice_while_in_flight_does_not_dispatch_twice`.

- **`list_runs` reads each life's own state, not the index cache.** The runs list
  derives turn and status from every life's own state file rather than a summary
  written at birth — otherwise a life that has since advanced would still show as
  unborn. The subtitle for a life comes from the *player's own opening answers*,
  not from narrated state, pinned by
  `test_routes.py::test_a_lifes_subtitle_comes_from_the_players_own_answers` and
  `test_a_life_with_nothing_distinguishing_it_gets_no_subtitle`.

- **Destructive routes require the dialog's shown facts as preconditions.**
  `GET …/deletion` returns the facts the confirm dialog shows (a world's live-life
  count, a life's current turn); the matching `POST …/delete` requires those facts
  back in the body and rejects a mismatch with `409`, so a delete can never affect
  more than what the player was shown. Preconditions travel as body fields
  (`deleteWorld(id, lives)`, `deleteLife(runId, turn)`).

- **Gateway internals are imported inside the handler.** `advance_run_turn` and
  `open_run` import `kiro_crew.dashboard.chat_runner._run_chat` *inside* the
  handler body, not at module top — exactly one code path touches gateway
  internals, matching the `issue_radar` / `spec_builder` precedent, and the app's
  module can load even where that internal is absent. The missing top-level import
  that once caused a 500 is guarded by
  `test_routes.py::test_the_missing_import_that_caused_the_500_is_present`, no
  handler leaking a stack trace by `test_no_handler_leaks_a_stack_trace_to_the_player`,
  and every declared route resolving to a real handler by
  `test_every_declared_route_points_at_a_real_handler`.

### MCP server (`backend/mcp_server.py`)

- **Exactly one tool is a state writer.** `STATE_WRITERS =
  frozenset({"endless_advance_turn"})` is held as data so the set cannot grow
  unnoticed. `endless_advance_turn` is the only tool that can commit a run's
  prose + state + choices. Pinned by
  `test_mcp_server.py::test_exactly_one_tool_is_declared_a_state_writer`.

- **Read handlers get narrow capability handles that cannot reach a writer.** The
  scene, backdrop, and read-only handlers are constructed with handles (e.g.
  `SceneLedger`, scoped to a run's `scenes.json`) that have no attribute path to a
  run-state writer at all — the isolation is structural, not review discipline. A
  scene call leaving state byte-identical is pinned by
  `test_a_scene_call_leaves_state_byte_identical`, the ledger's inability to reach
  run state by `test_the_scene_ledger_cannot_reach_run_state_at_all`, and the
  general property by `test_no_handler_but_advance_turn_can_even_reach_a_writer`.
  `SceneLedger.record_answer` exists but is referenced by no handler, so the
  narrator can never answer its own scene's question — pinned by
  `test_recording_an_answer_is_not_reachable_from_any_tool`; the nonce is never
  handed back (`test_the_nonce_is_never_handed_to_the_narrator`).

- **The enforced schema is the published schema.** `_INPUT_SCHEMAS` is derived
  from the same `_TOOLS` list that `tools/list` advertises, so a narrator is never
  refused for a rule it was not shown. Pinned by
  `test_the_enforced_schema_is_the_published_schema`; the surface being exactly the
  declared tools by `test_the_surface_is_exactly_the_declared_tools`.

- **`call_tool` validates the whole call, then dispatches, and returns errors as
  data.** An unknown tool, a bad field, or a malformed turn comes back as JSON
  (`{ok:false, field, expected, …}`), never a raised exception — a raise is a
  protocol error the narrator cannot act on, a named field is fixable. A malformed
  turn applies *nothing* (prose included) — pinned by
  `test_a_malformed_turn_applies_nothing`; an unknown tool refused by name by
  `test_an_unknown_tool_is_refused_by_name`; every bad field named by
  `test_every_bad_field_is_named`.

- **The turn number is stamped by the server.** `endless_advance_turn` stamps the
  turn from the server's own record, not from anything in the declared state, and
  is idempotent per `(runId, turn)` (a replay changes nothing). App-owned
  `RESERVED_STATE_KEYS` (`worldId`, `style`, `language`, `opening`, `status`,
  `milestones`) survive the full-state replacement even when the narrator omits
  them. Pinned by `test_the_turn_number_is_stamped_by_the_server_not_trusted_from_state`,
  `test_a_replayed_turn_changes_nothing`, and
  `test_a_commit_keeps_the_keys_the_narrator_never_declares`.

- **The tool surface (~11 tools), by facing.** One-line purpose each:

  | Tool | Facing | Purpose |
  |---|---|---|
  | `endless_advance_turn` | narrator | the one writer — commit prose + full state + choices (+ optional memory/events) |
  | `endless_read_runtime` | narrator | read-only pull of rulebook + state + recent turns, with a `since`-fingerprint delta |
  | `endless_mount_scene` | narrator | mount a structured scene (map/tree/links/ledger/choice) from a spec; the app draws it |
  | `endless_update_scene` | narrator | change a mounted scene without remounting (a remount reloads its iframe) |
  | `endless_await_scene` | narrator | return the player's scene answer if present; never blocks |
  | `endless_dismiss_scene` | narrator | remove a scene |
  | `endless_set_backdrop` | narrator | set an inert background SVG (+ optional button motif), script/handler-free |
  | `endless_clear_backdrop` | narrator | clear the backdrop (idempotent) |
  | `endless_export_world` | narrator | serialize a whole world to one portable file |
  | `endless_read_draft` | worldsmith | return the pasted `rawText` + the authoritative compiler `brief` |
  | `endless_submit_world_draft` | worldsmith | compile + store a draft through the same gate a hand-written world uses |

  A scene spec carrying markup is refused, not silently stripped
  (`test_a_spec_carrying_markup_is_refused_not_stripped`); updating an unmounted
  scene is an error, not a silent mount
  (`test_updating_an_unmounted_scene_is_an_error_not_a_silent_mount`); dismissing
  twice is harmless (`test_dismissing_twice_is_not_an_error`); `endless_await_scene`
  never blocks (`test_await_never_blocks_and_reports_the_players_answer`); a scene
  id can never become a path (`test_a_malformed_scene_id_never_becomes_a_path`);
  and `endless_export_world` refuses a path dressed as a world id
  (`test_export_world_refuses_a_path_dressed_as_a_world_id`).

- **No tool speaks implementation vocabulary, and stdout is protocol-only.** Tool
  descriptions are written for the narrator and leak no internal terms
  (`test_no_tool_description_leaks_implementation_vocabulary`); no handler can emit
  a prompt or approval (`test_no_handler_can_emit_a_prompt_or_approval`); nothing
  is written to stdout outside the JSON-RPC protocol
  (`test_stdout_is_never_written_to_outside_the_protocol`); and the server fails
  loudly when a dependency is missing rather than degrading silently
  (`test_the_server_fails_loudly_when_its_dependency_is_missing`).

### Agents

- **The narrator owns a sealed, app-stamped slot and can reach nothing but this
  app's own tools.** A new run gets a slot sealed and stamped `_app` at creation;
  a slot another app owns, or an unsealed slot, is refused rather than narrated
  into, with a second independent core guard behind it. The narrator's `tools`
  allowlist reaches only `@endless-worlds:endless-mcp`, and memory isolation is
  `memory_mode="temporary"` (blocking memory reads *and* the consolidator) — the
  temporary prompt prefix is advisory, only the mechanism is relied on. Pinned by
  `test_narrator.py::test_a_new_run_gets_a_sealed_slot_owned_by_this_app`,
  `test_a_slot_another_app_owns_is_refused_not_adopted`,
  `test_the_narrator_can_reach_nothing_but_this_apps_own_tools`,
  `test_only_temporary_blocks_memory_reads`, and
  `test_every_non_persistent_mode_blocks_memory_writes`.

- **Approval-free play comes from the packaged agent's declared `allowedTools`,
  not runtime trust-stamping.** The app never grants itself tool approval at
  runtime; the packaged agent declares `allowedTools` so an unattended tool call
  is not silently rejected, and governance can still veto it. Pinned by
  `test_this_app_never_grants_itself_tool_approval` and
  `test_auto_approve_is_declared_because_an_unattended_prompt_means_rejected`.

- **The worldsmith's whole non-web surface is this app's MCP server.**
  `agents/worldsmith.json` (`name: endless-worldsmith`, `model: auto`) declares
  `tools`/`allowedTools` of exactly `web_search`, `web_fetch`, and
  `@endless-worlds:endless-mcp` — no filesystem, shell, or player memory. It
  reads a draft (`endless_read_draft`, returning `rawText` + the authoritative
  `brief`), cleans or expands it, and submits (`endless_submit_world_draft`) through
  the same `accept_compiled_header` gate a hand-written world passes; a refusal is
  stored as the draft's `problem`, not raised. The web tools exist so it can
  research a named work rather than invent its canon.
