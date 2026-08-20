# Architecture

Endless Worlds is an external Kiro Crew app. A single Python backend does two
jobs at once: it serves a **player-facing HTTP surface** to the SPA, and it runs
a **separate stdio MCP server** that the app's own agents call. Two app-owned
agents drive the story — a **narrator** that advances one life turn by turn, and
a **worldsmith** that compiles pasted text into a world. Both processes locate
the same on-disk data directory, so a route and an MCP tool operate on the same
files without sharing a process.

```
                 player                             narrator / worldsmith
                   │                                        │
          HTTP (routes.py)                        stdio MCP (mcp_server.py)
                   │                                        │
                   └──────────────┬─────────────────────────┘
                                  │
                        the on-disk data dir
        (worlds/*.md · kv/*.json · runs/<id>/chronicle.jsonl · settings.json)
```

## The two agents

| Agent | Spec | Job |
|---|---|---|
| `endless-narrator` (`agents/narrator.json`) | [modules/narrator-and-i18n.md](modules/narrator-and-i18n.md) | Runs one life. Each turn it pulls the runtime, writes prose + the new world state + choices, and commits through the app's MCP server. One app-owned chat slot per life. |
| `endless-worldsmith` (`agents/worldsmith.json`) | [modules/world-creation.md](modules/world-creation.md), [modules/surface.md](modules/surface.md) | Turns a pasted rulebook — or a one-line idea — into an installable world, researching a named work with `web_search`/`web_fetch` when needed. |

Both agents reach nothing but this app's own MCP server (`web_*` on the
worldsmith aside). Their only tool ref is the **namespaced** `@endless-worlds:endless-mcp`;
the bare form resolves to zero tools silently. See
[modules/narrator-and-i18n.md](modules/narrator-and-i18n.md).

## The backend split

- **HTTP surface** (`backend/routes.py`, `backend/memory_routes.py`) — everything
  the SPA calls: worlds, lives, the turn endpoint, drafts, scenes, backdrop
  image, memory/star map, keepsakes, story cards. Every handler gates on an
  injected `user` and 401s without one. See [modules/surface.md](modules/surface.md).
- **MCP server** (`backend/mcp_server.py`) — everything the agents call. Exactly
  **one** tool writes state (`endless_advance_turn`); every other handler is
  handed a narrow capability object that cannot reach a writer at all. See
  [modules/surface.md](modules/surface.md).

## The data flow of one turn (the pull-only model)

1. The player submits an action; `routes.py` records the turn **in flight before
   the narrator is spoken to**, then dispatches the narrator.
2. The narrator's prompt carries **only** the run id, the turn number, and the
   player's quoted action. It does not carry world state or history.
3. The narrator calls `endless_read_runtime` first — pulling the rulebook (once),
   the current state, recent turns, restraint readings, and memory candidates —
   then calls `endless_advance_turn` with the whole new state + prose and an
   optional structured memory block. The memory block is validated as one unit:
   if it is invalid, the app drops that block and warns the narrator while the
   prose, choices, and state still commit; a valid block shares the turn's same
   chronicle record and cannot drift into a second log.
4. The commit lands as a filesystem write; the SPA polls and converges.

Why pull, not push: the narrator's session is one continuous conversation per
life, so it still holds the rulebook and its own prior turns. Re-pushing them
every turn made the prompt grow without bound while the player-visible transcript
filled with setup. The full protocol, the self-certifying delta fingerprint, and
the idempotence guarantees are in [modules/turn-loop.md](modules/turn-loop.md).

## The two halves of memory

- **Fact layer** — "what happened." Append-only, per-life, rebuildable from the
  chronicle. [modules/memory-graph.md](modules/memory-graph.md).
- **Meaning layer** — "what matters to me." Keepsakes and shareable story cards
  that *cite* facts and never mutate them. [modules/meaning-layer.md](modules/meaning-layer.md).

That split is itself the top invariant of the memory system: facts are
authoritative; meaning references facts by id and can only ever narrow what it
shows.

## App-wide invariants

These hold across modules; each is stated fully, with its enforcing function and
pinning test, in the module that owns it.

- **One MCP state writer.** `endless_advance_turn` alone writes life state; read,
  scene, and backdrop handlers get capability objects with no path to a writer.
  ([modules/surface.md](modules/surface.md))
- **The narrator can only reach this app's tools**, and its slot is sealed to
  `memory_mode="temporary"` — it never reads or writes player memory.
  ([modules/narrator-and-i18n.md](modules/narrator-and-i18n.md))
- **Reserved state keys are app-owned and carried forward** across the
  full-state replacement each turn performs; losing one (e.g. `worldId`) makes a
  life unreadable. ([modules/data-model.md](modules/data-model.md))
- **The narrator supplies structure and meaning, never markup, geometry, or
  identifiers the app owns** — scene layout, event ids, milestones, and lineage
  provenance are all computed or stamped server-side.
  ([modules/scenes-and-backdrop.md](modules/scenes-and-backdrop.md),
  [modules/memory-graph.md](modules/memory-graph.md),
  [modules/library-and-lineage.md](modules/library-and-lineage.md))
- **Untrusted content never executes.** The `when` condition language has no call
  node; scene/backdrop SVG is validated and delivered so it cannot run script;
  player free-text enters prompts last, quoted, as reported speech.
  ([modules/world-schema.md](modules/world-schema.md),
  [modules/scenes-and-backdrop.md](modules/scenes-and-backdrop.md),
  [modules/turn-loop.md](modules/turn-loop.md))
- **The player is never shown the machinery.** Prompts, previews, and degraded
  renders carry no implementation vocabulary; a malformed artifact degrades to a
  simpler rendering rather than surfacing an error.
  ([modules/character-creation.md](modules/character-creation.md),
  [modules/view-and-packs.md](modules/view-and-packs.md))
- **A single UI-vs-backend key contract.** One server-side interpreter decides
  what renders, and a cross-file test diffs every property the UI reads against
  the keys the backend sends — a field rename once blanked the whole page.
  ([modules/view-and-packs.md](modules/view-and-packs.md))
