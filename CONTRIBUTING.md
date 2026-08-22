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

## Quality gates (what CI enforces)

Every PR into `main` runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

1. **Backend tests** — `cd backend && python -m pytest`.
2. **Frontend lint** — `cd web && npm run lint`. A narrow ESLint gate
   (`web/eslint.config.js`): `react-hooks/rules-of-hooks` is an **error** and
   nothing else is enabled, so a hook after an early return (React #310) fails
   CI instead of shipping. Run it locally with `npm run lint`.
3. **Frontend typecheck + build** — `cd web && npm run build`.
4. **The committed bundle must match a fresh build** — CI fails if
   `ui/index.mjs` differs from what `npm run build` produces.

Run all of them locally before you push:

```bash
cd backend && python3 -m pytest
cd ../web && npm run lint && npm run build
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

## Linters (current and recommended)

Current: the frontend `react-hooks/rules-of-hooks` gate above, plus `tsc`
strict typechecking through the build.

The backend currently has **no linter or formatter** — only pytest. If you want
to raise the floor, the recommended additions (see the discussion this file was
introduced with) are, in priority order:

- **Ruff** (`ruff check` + `ruff format`) — one fast tool that replaces
  flake8 + isort + black; start with a small rule set and widen deliberately.
- **mypy** — type checking for the backend, ideally gated per-module rather than
  repo-wide so it can be adopted incrementally.
- Frontend, later: widen ESLint from hooks-only toward `typescript-eslint`
  recommended rules, and add **Prettier** for formatting.

Adopt each behind its own PR and CI step, scoped narrowly at first (like the
hooks gate) so it never floods existing code with findings.
