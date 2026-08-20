# Rules for AI assistants — Endless Worlds

**This file is a ROUTER, not a manual.** It maps the subsystem you are about to
change to the spec you must read first. The specs under [`docs/modules/`](docs/modules/README.md)
are the change-control contracts; this file only points at them.

## What this is

Endless Worlds is an external Kiro Crew app: a text life-simulation
where a player lives one life at a time inside a world and an LLM **narrator**
writes each turn. A single Python backend serves a player-facing HTTP surface and
a separate agent-facing MCP server; two app-owned agents (a narrator and a
worldsmith) drive it. The whole map is in [`docs/architecture.md`](docs/architecture.md).

- **Backend:** `backend/` (Python). Tests in `backend/tests/`.
- **Frontend:** `web/` (React + TS + Vite), built to `ui/index.mjs` and mounted
  directly onto the dashboard document (not an iframe).
- **Agents:** `agents/narrator.json`, `agents/worldsmith.json`.
- **Manifest:** `app.json`. **Worlds:** `seeds/*.md` (bundled) and the installed
  packs in the app data dir.

## Read before you touch

Load the spec for the row you are working in **before** you change code, and
update it in the **same commit** when you change what it documents.

| If you are touching… | Read first |
|---|---|
| `store.py` — persistence, run/world state, chronicle, index, delete | [data-model.md](docs/modules/data-model.md) |
| `world.py`, `template.py`, `chapters.py` — pack format, schema, the `when` language | [world-schema.md](docs/modules/world-schema.md) |
| `compile.py`, `drafts.py` — the world-creation pipeline and the compiler brief | [world-creation.md](docs/modules/world-creation.md) |
| `library.py`, `legacy.py` — the world shelf and the lineage bridge | [library-and-lineage.md](docs/modules/library-and-lineage.md) |
| `opening.py`, `halo.py` — character creation and the anti-halo instruments | [character-creation.md](docs/modules/character-creation.md) |
| `turn.py` — the turn loop and the pull-only protocol | [turn-loop.md](docs/modules/turn-loop.md) |
| `narrator.py`, `content.py`, `settings.py`, `agents/narrator.json` | [narrator-and-i18n.md](docs/modules/narrator-and-i18n.md) |
| `view.py`, `packs.py` — play-view assembly, shaping, capability packs | [view-and-packs.md](docs/modules/view-and-packs.md) |
| `scenes.py`, `widget.py`, `backdrop.py` — mounted scenes and backdrops | [scenes-and-backdrop.md](docs/modules/scenes-and-backdrop.md) |
| `memory_graph.py` — the world-memory fact layer | [memory-graph.md](docs/modules/memory-graph.md) |
| `keepsakes.py`, `story_cards.py`, `memory_routes.py` — the meaning layer | [meaning-layer.md](docs/modules/meaning-layer.md) |
| `routes.py`, `mcp_server.py`, `app.json`, `agents/worldsmith.json` | [surface.md](docs/modules/surface.md) |
| anything under `web/src/` | [frontend.md](docs/modules/frontend.md) |
| cross-cutting rules (English code, content-in-data, no-execute, persistence) | [conventions.md](docs/conventions.md) |

Design reasoning and the roadmap (planning artifacts, **not** contracts) live in
[`docs/design/`](docs/design/README.md).

## Invariants you must not weaken

Each is stated fully, with its enforcing function and pinning test, in the module
that owns it (see [`docs/architecture.md`](docs/architecture.md) § App-wide invariants):

- **One MCP state writer** — `endless_advance_turn` alone writes life state; read
  handlers get capability objects with no path to a writer.
- **The narrator reaches only this app's tools**, and its slot is sealed to
  `memory_mode="temporary"`.
- **Reserved state keys are app-owned and carried forward** across the full-state
  replacement each turn performs.
- **The narrator gives structure and meaning, never markup, geometry, or
  app-owned identifiers** (scene layout, event ids, milestones, lineage).
- **Untrusted content never executes** — the `when` language has no call node;
  scene/backdrop SVG cannot run script; player free-text enters prompts last,
  quoted, as reported speech.
- **The player is never shown the machinery** — no implementation vocabulary in
  prompts/previews; a malformed artifact degrades, it does not error.

## Conventions

- **Code is English; player/model-facing text is content** in `content/*.json` or
  the world pack, selected by the world's language. No hardcoded CJK — including
  punctuation. See [conventions.md](docs/conventions.md).
- A spec cites the **enforcing function AND the pinning test** for every
  load-bearing claim, and names a test rather than copying a number it pins.
- Describe **current** behavior in present tense in the specs. Roadmap and design
  reasoning go in `docs/design/`, not in a module spec.

## The gate before you commit

```bash
python -m pytest backend/tests        # backend
cd web && npm run build               # tsc --noEmit && vite build -> ui/index.mjs
```

The frontend build also runs the cross-file guard tests' companions: `view.py`'s
contract test scans `web/src` (`backend/tests/uisrc.py`) and the backend
source-scan guards live in `backend/tests/srcguard.py`. Keep both green — they are
what catch a UI/backend key drift or a hardcoded string before it ships.

## Git

- Do NOT `git commit` or `git push` unless explicitly asked. Being asked to commit
  is not permission to push.
- One logical change per commit; Conventional Commits (`feat`/`fix`/`refactor`/
  `docs`/`test`/`chore`), imperative, lowercase, ≤72 chars.
