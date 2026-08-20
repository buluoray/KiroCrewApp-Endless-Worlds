# Module specs

One spec per subsystem. **These are change-control contracts:** read the spec for
the subsystem you are touching before you change it, and update it in the same
commit when you change what it documents. This is also the on-demand load target —
open only the one you need.

Each spec follows the same shape: a one-paragraph overview, a Layout table
(path → what it is), and a **Load-bearing contracts** section where every entry
states the invariant, why it is load-bearing, and cites the enforcing function
plus the pinning test by name.

## Persistence

| Spec | Subsystem |
|---|---|
| [data-model.md](data-model.md) | `store.py` persistence: `runId`/`worldId` identity, on-disk layout, reserved-key carry-forward, prev-before-state crash ordering, corrupt-vs-absent, the fingerprint/diff delta protocol, the in-flight pending record, `delete_run`'s key sweep, and life rename/archive metadata. |

## World authoring and library

| Spec | Subsystem |
|---|---|
| [world-schema.md](world-schema.md) | `world.py` pack format (byte-verbatim prose, the CONTRACT gate, provenance staleness, specs-travel-not-HTML) + `template.py` schema (quoted-string version, panels, endings/milestones that detect rather than enumerate, lore, the eval-free depth-capped `when` interpreter) + `chapters.py` (declared-not-detected headings, closed chapters refused not emptied, no unreachable prose, TOC sent once). |
| [world-creation.md](world-creation.md) | The paste-or-idea → clean → compile-gate → review → install pipeline: `COMPILER_BRIEF` as a code-interpolated artifact with the JSON/quoted-version mandate, `accept_compiled_header` (never raises, reuses `read_world`, stamps provenance server-side), camelCase→slug id normalization with `when` rewrite, and the crash-safe `DraftStore` lifecycle. |
| [library-and-lineage.md](library-and-lineage.md) | `library.py` world shelf (directory-as-index, id validated before any path touch, seeds installed once then reported-not-applied, gravestone-before-unlink deletion, staleness as a flag) + `legacy.py` lineage bridge (only visibly-lived entities inheritable, copied into the heir's own turn-0 chronicle, `inheritsFrom` stamped server-side and refused from the narrator). |

## The play loop

| Spec | Subsystem |
|---|---|
| [character-creation.md](character-creation.md) | `opening.py` initial-state build (validate-all-first, world-decided `random:true` fields refused from the client with a label-only UI, unanswered = `WORLD_DECIDES`, pull-only prompt that names the run) + `halo.py` anti-halo instruments (the app measures and never rewrites narration, reach gating marks a far event as rumour rather than dropping it, unsourced gains are flagged not refused). |
| [turn-loop.md](turn-loop.md) | `turn.py` pull-only turn protocol: the prompt carries only run id + turn + the player's quoted action, prompt size is independent of life length, read-runtime-first is enforced on evidence not absence, the self-certifying delta baseline, idempotence per `(runId, turn)`, mark-pending-before-dispatch, and a timeout that neither rolls back nor clears the record. |
| [narrator-and-i18n.md](narrator-and-i18n.md) | The narrator seal and text layer: the namespaced-only tool ref, `tools == allowedTools` for the unattended slot, `memory_mode="temporary"` as the real isolation, `content.py`'s world-selects-language `Content` with the no-hardcoded-CJK (incl. punctuation) and route-call-site guards, and `settings.py` reasoning-effort coercion. |
| [view-and-packs.md](view-and-packs.md) | `view.py` assembles the whole play-page body through one server-side `when` interpreter and one `primitive`-only shaper, guarded by the cross-file UI-reads-⊆-backend-keys contract; `packs.py` composes primitives into declarative, per-pack-degrading panels. |
| [scenes-and-backdrop.md](scenes-and-backdrop.md) | The scene compiler/ledger split and the backdrop validation funnel: a closed element-kind set, backend-computed geometry, whole-spec validation, a CSP-first `srcdoc` sandbox, the answer nonce that is never narrator-facing, and the inert-`<img>` "never run it at all" backdrop model. |

## Memory

| Spec | Subsystem |
|---|---|
| [memory-graph.md](memory-graph.md) | The world-memory fact layer (`memory_graph.py`): chronicle as single source of truth, a byte-stable rebuildable index, structured-only facts, server-minted event ids, whole-block atomic validation, append-only `(runId, turn)` idempotency, relations as a projection, deterministic cooldown-guarded echoes, and cross-life isolation. |
| [meaning-layer.md](meaning-layer.md) | The player-meaning layer (`keepsakes.py` + `story_cards.py` + star lenses): immutable cited-fact keepsakes with content-hash honesty, story-card allowlists that only narrow, preview==export purity, render-time anonymisation and spoiler/export safety, and the shared server-disclosure-filtered `star_payload` behind three lenses. |

## Surface and UI

| Spec | Subsystem |
|---|---|
| [surface.md](surface.md) | The manifest (hooks-only backend, dual-listed agents, namespaced MCP ref, storage/network permissions), `routes.py` (auth gating, the create-then-open / draft-then-compile split, per-life state reads, delete preconditions), and `mcp_server.py` (the single state writer, capability-isolated read handlers, enforced==published schema, validate-then-dispatch). |
| [frontend.md](frontend.md) | `web/src`: independent selected-world/active-run state, synchronous language state with a dropdown lock, region-driven rail-vs-tabbar navigation, the never-moved `SceneSlot` iframe, server-authoritative "generating" with a poll and turn-number paging, sealed opening groups, and the drift-tolerant `api.ts` helpers. |
