# Endless Worlds

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

Requires a running [Kiro Crew](https://github.com/kirodotdev/KiroCrew) gateway
(Python 3.10+, Node.js 22+ to build the UI).

Install a local checkout (this repository does not currently declare a public
remote URL):

```bash
kirocrew app install /absolute/path/to/endless-worlds
kirocrew app enable endless-worlds
```

Open the dashboard and pick **无限世界 / Endless Worlds** from the sidebar. The
app self-heals its MCP server path to wherever it was installed, so no manual
editing of `app.json` is needed.

Backdrop publication additionally needs **one local SVG rasterizer** on the
gateway host — the illustrator visually reviews server-rendered PNG previews
before publishing. Any one of these satisfies it, checked in this order:

- the `cairosvg` Python package (`pip install cairosvg`),
- the `rsvg-convert` binary (`librsvg2-bin` on Debian/Ubuntu),
- the librsvg shared library itself (`librsvg2-2` on Debian/Ubuntu,
  `dnf install librsvg2` on Fedora/AL2023, `brew install librsvg` on macOS),
  reached directly through `ctypes` with no Python package.

The SCENE lane additionally needs the `vtracer` and `pillow` Python packages
(`pip install vtracer pillow`) to trace reference photos into underlays; the
motif lane works without them. Photo decoding and tracing run per variant in a
killable child process with a wall-clock timeout, input/output byte ceilings, and
format/dimension/pixel guards. References are fetched only over HTTPS from
Wikimedia Commons hosts, redirects cannot leave that allowlist, and only CC0 or
public-domain photos are accepted. If search, fetch, validation, or tracing fails,
the scene gets a quiet procedural tonal base instead of exposing a broken or
partially trusted trace.

Without a renderer, illustrator draft submission fails and page art falls back
to the narrator's emergency path; the story itself is unaffected.

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

Contributor guide and the "read the spec before you touch the code" routing
table are in [`AGENTS.md`](AGENTS.md).

## Creating a world

Worlds are self-contained Markdown files. Start from a shipped one in
[`seeds/`](seeds/), or use the in-app **Create a world** flow to hand the
worldsmith a premise. The pack format — the header schema, the field primitives,
the `when` expression language, and the systems engine — is specified in
[`docs/modules/world-schema.md`](docs/modules/world-schema.md) and
[`docs/modules/world-creation.md`](docs/modules/world-creation.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
