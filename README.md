# Endless Worlds

**English** | [简体中文](README.zh-CN.md)

Live a whole life inside an AI-simulated world. Endless Worlds is a
[Kiro Crew](https://github.com/kirodotdev/KiroCrew) app: a text life-simulation
where you are born into a world, live it one turn at a time, and an LLM
**narrator** writes each turn — reacting to your choices, remembering what you
did fifty turns ago, and letting the world move on its own whether or not you
act. It ships **剑火纪元** (a western-fantasy sandbox) as its flagship world and
**末世残响** (a zombie-apocalypse survival world) alongside it, and it can turn a
pasted premise into a brand-new world with its built-in worldsmith.

- One life at a time, in the world's own language (中文 / English).
- A narrator that never breaks character and never treats you as the chosen hero.
- Per-turn generated backdrops, fateful-choice art, a life star map, keepsakes,
  world memory that echoes past facts back into the story, and multi-generation
  lineage.
- Bring your own world: paste a setting or a one-line idea and the worldsmith
  cleans and compiles it into a playable pack.

## How it works

Endless Worlds runs entirely on your own Kiro Crew gateway. It has two backend
surfaces served by one Python package:

- an **HTTP surface** (`backend/routes.py`) the web UI talks to, and
- an agent-facing **MCP server** (`backend/mcp_server.py`) the narrator and
  worldsmith agents call to read runtime state and commit turns.

The frontend (`web/`, React + TypeScript + Vite) is built to a single
`ui/index.mjs` bundle that mounts directly onto the dashboard. Worlds are
Markdown packs (`seeds/*.md`): a machine-readable header the app renders and
enforces, plus prose that is the narrator's rulebook, passed through verbatim.

The whole architecture is documented in [`docs/architecture.md`](docs/architecture.md);
per-module contracts live under [`docs/modules/`](docs/modules/README.md).

## Install

Requires a running [Kiro Crew](https://github.com/kirodotdev/KiroCrew) gateway,
with Python 3.10+ and Node.js 22+ on the host (used to build the UI during a
registry install).

**Install from a registry (recommended).** A registry install clones and builds
the app and runs its `setup.sh`, which best-effort-installs the optional art
dependencies described below. Add this repository as an app registry and install
Endless Worlds from the dashboard's **App Store**:

- Registry URL: `https://github.com/buluoray/KiroCrewApp-Endless-Worlds`
  (its `app-registry.json` lists the app).
- In the dashboard, open the **App Store**, add that registry, then install
  **无限世界 / Endless Worlds** and enable it.

Pick it from the sidebar. The app self-heals its MCP server path to wherever it
was installed, so no manual `app.json` editing is needed.

On that registry install (and every update) the app runs `setup.sh` — a
**best-effort, non-blocking** setup of its OPTIONAL art dependencies: an SVG
rasterizer (so the illustrator can preview draft backdrops) and `vtracer` +
`pillow` (so SCENE pages can trace reference photos). The install never fails on
them — if any are missing the app still runs: backdrop publication falls back to
the narrator's hand-drawn path, and photo scenes degrade to a quiet procedural
tonal base. Reference photos are fetched only over HTTPS from a fixed
CC0/public-domain allowlist.

**Local install — for development only.** A local-path install copies the app but
does **not** run `setup.sh`; use it when iterating on the code, not for regular
use:

```bash
kirocrew app install /absolute/path/to/endless-worlds
kirocrew app enable endless-worlds
bash setup.sh   # the local install skips this, so run it yourself if you want the optional deps
```

## Build and develop

The shipped `ui/index.mjs` is a build artifact; rebuild it after changing
anything under `web/`:

```bash
cd web
npm ci
npm run build        # tsc --noEmit && vite build -> ../ui/index.mjs
```

Run the backend test suite:

```bash
cd backend
python3 -m pytest
```

Contributor workflow (setup, quality gates, PR process, linters) is in
[`CONTRIBUTING.md`](CONTRIBUTING.md); the "read the spec before you touch the
code" routing table and engineering rules are in [`AGENTS.md`](AGENTS.md). Hitting
a runtime problem (e.g. the narrator loses its tools — restart the gateway)? See
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## Creating a world

Worlds are self-contained Markdown files. Start from a shipped one in
[`seeds/`](seeds/), or use the in-app **Create a world** flow to hand the
worldsmith a premise. The pack format — the header schema, the field primitives,
the `when` expression language, and the systems engine — is specified in
[`docs/modules/world-schema.md`](docs/modules/world-schema.md) and
[`docs/modules/world-creation.md`](docs/modules/world-creation.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
