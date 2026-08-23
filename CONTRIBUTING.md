# Contributing to Endless Worlds

Endless Worlds is an external [Kiro Crew](https://github.com/kirodotdev/KiroCrew)
app: a Python backend (an HTTP surface for the SPA plus an agent-facing MCP
server) and a React + TypeScript + Vite frontend built to a single committed
`ui/index.mjs` bundle. This guide is the practical how-to for changing it.
[`AGENTS.md`](AGENTS.md) is the authoritative engineering guide (the "read the
spec before you touch the code" routing table); this file is the workflow around
it. For runtime problems, see [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## Prerequisites

- **Python 3.10+** — the backend and its test suite.
- **Node.js 22+** — to build the UI bundle.
- A running **Kiro Crew gateway** to install and exercise the app.
- Optional, only for backdrop art: one SVG rasterizer (`cairosvg`,
  `rsvg-convert`, or `librsvg2-2`) plus `vtracer` + `pillow` for the SCENE lane.
  The story works without them (see the README).

## Repository layout

| Path | What it is |
|---|---|
| `backend/` | The Python package: `routes.py` (HTTP surface), `mcp_server.py` (agent-facing MCP tools), the domain modules, and `backend/tests/`. |
| `web/` | The React + TS + Vite SPA. Built to `../ui/index.mjs`. |
| `ui/index.mjs` | The **committed** build artifact (see "The bundle is committed" below). |
| `agents/` | The app's own agent definitions (narrator, illustrator, worldsmith). |
| `content/` | Language-keyed UI strings (`en.json` / `zh.json`). |
| `seeds/` | Shipped worlds as self-contained Markdown packs. |
| `docs/` | Change-control specs: `architecture.md`, `conventions.md`, one spec per subsystem under `modules/`, and design notes under `design/`. |
| `app.json` | The app manifest and its `version`. |

## Dev setup

```bash
# Build the UI bundle (required after any web/ change)
cd web && npm ci && npm run build      # tsc --noEmit && vite build -> ../ui/index.mjs

# Run the backend test suite
cd backend && python3 -m pytest

# Enable the pre-commit hook once per clone (git does not do this for you).
# It rebuilds ui/index.mjs whenever a staged change would make it stale.
git config core.hooksPath .githooks
```

Install your checkout into a gateway to exercise it end to end:

```bash
kirocrew app install /absolute/path/to/endless-worlds
kirocrew app enable endless-worlds
```

Or let [`devtools/`](devtools/README.md) do it in a throwaway instance, with a seeded
life story you did not have to write, and screenshot the result:

```bash
python3 devtools/uishot.py up                    # own data home, own port, 5 seeded lives
python3 devtools/uishot.py shot starmap --theme light --width 390
```

The same seeding works on its own, so you can load a playable life in seconds without
asking an LLM to write one:

```bash
python3 devtools/uishot.py seed --data-dir ~/.kiro/crew/apps/endless-worlds/data
```

## Quality gates (what CI enforces)

Every PR into `main` runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

1. **Backend tests** — `cd backend && python -m pytest`.
2. **Backend lint + types** (the `backend-lint` job) — `ruff check backend`,
   `ruff format --check backend`, and `mypy` (config in `backend/pyproject.toml`), plus
   the same three over `devtools/` (config in `devtools/pyproject.toml`).
3. **Frontend lint** — `cd web && npm run lint`. ESLint (`web/eslint.config.js`)
   with `typescript-eslint` recommended plus `react-hooks/rules-of-hooks` as an
   **error**, so a hook after an early return (React #310) fails CI instead of
   shipping.
4. **Frontend format** — `cd web && npm run format:check` (Prettier).
5. **Frontend typecheck + build** — `cd web && npm run build`.
6. **The committed bundle must match a fresh build** — CI fails if
   `ui/index.mjs` differs from what `npm run build` produces.

Run all of them locally before you push:

```bash
cd backend && ruff check . && ruff format --check . && mypy . && python3 -m pytest
cd ../web && npm run lint && npm run format:check && npm run build
git diff --quiet -- ui/index.mjs || echo "bundle is stale — commit the rebuild"
```

## The bundle is committed

`ui/index.mjs` is checked in because a registry install copies the repository
**as-is** — nothing builds the app after checkout, so a stale artifact means the
installed app silently runs older code than the commit claims. Two things follow:

- Rebuild and commit `ui/index.mjs` in the **same commit** as any change under
  `web/`, or any `app.json` version bump (Vite bakes the version into the bundle
  at build time). The pre-commit hook does this automatically once enabled.
- The build must be reproducible: `npm ci` pins every dependency from
  `web/package-lock.json`, so commit lockfile changes alongside dependency
  changes.

## Versioning

There is **no per-PR version gate**, on purpose. `app.json`'s `version` is a
judgement that a body of work is worth reinstalling — not a side effect of
touching a file. Day to day, reinstall the app instead of bumping. Bump the
version **deliberately** when you want a release to be installable, and rebuild
the bundle in the same commit.

Because a bump edits one shared line, two concurrent PRs that both bump collide.
Resolve it by rebasing the later PR onto `main`, setting the version to the next
number, and rebuilding the bundle — do not merge two PRs claiming the same
version.

## Making a change

1. **Read the spec first.** Before changing a subsystem, read its spec under
   [`docs/modules/`](docs/modules/README.md) (the routing table in
   [`AGENTS.md`](AGENTS.md) maps code areas to specs), and **update that spec in
   the same commit** when you change what it documents. A spec that disagrees
   with the code is worse than no spec.
2. **Follow the conventions** in [`docs/conventions.md`](docs/conventions.md):
   code and comments are English-only; user-facing strings live in the
   language-keyed `content/` files, never inline; player-supplied text is
   untrusted and never interpolated into a prompt or markup.
3. **Pin load-bearing claims to a test.** New behavior gets a test; a test that
   asserts a guard should be mutation-verified (break the code, confirm the test
   goes red, restore) so a green result is trustworthy.
4. **Keep comments about behavior, not history** — present tense, no
   "previously / we now", no PR/commit markers. Git holds the history.

## Pull requests

- Branch off `main`; keep one logical change per PR.
- Open the PR against `main` (CI only runs for PRs targeting `main`).
- CI must be green — backend tests, lint, typecheck+build, and the bundle
  freshness check.
- Prefer a squash merge so `main` keeps one commit per change.
- If your branch falls behind and a version/bundle conflict appears, rebase onto
  `main`, take the newer version, bump if you are shipping, and rebuild the
  bundle before merging.

## Linters and formatters

These gates run in CI (see Quality gates above); run them locally before pushing.

- **Backend — [Ruff](https://docs.astral.sh/ruff/) + mypy.** Ruff lints
  (`ruff check`, rule set `E,F,I,UP,B` at 100 cols) and enforces formatting
  (`ruff format`); config in `backend/pyproject.toml`. `ruff format .` fixes
  formatting. mypy runs **lenient/incremental** (`ignore_missing_imports`, no
  strict flags, `tests/` excluded) — green over the reachable app modules and
  meant to widen over time.
- **Frontend — ESLint + Prettier.** ESLint (`web/eslint.config.js`) runs
  `typescript-eslint` recommended plus `react-hooks/rules-of-hooks` as an error;
  Prettier formats (`npm run format` to fix, `npm run format:check` in CI).
  `src/styles.css` is excluded from Prettier because Vite inlines it verbatim into
  the committed bundle.

When adding or widening a rule, scope it narrowly first (like the original
hooks-only gate), keep the gate green, and adopt it behind its own PR so it never
floods existing code with findings.
