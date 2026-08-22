# Troubleshooting

Common runtime problems running Endless Worlds on a Kiro Crew gateway, and how to
resolve them. For development workflow and CI, see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## The narrator can't reach its tools — restart the gateway

**Symptom.** A turn cannot advance. The narrator (or illustrator) session no
longer has the app's MCP tools — `endless_read_runtime`, `endless_advance_turn`,
`endless_paint_backdrop`, `endless_trace_reference`, etc. are missing, and the
session may report only unrelated tools (e.g. a default/credential agent) with no
`endless_*` tools available. The turn stalls or the agent says it cannot read the
run.

**Cause.** The app's MCP server did not attach to that agent session — a
transient wiring issue between the gateway, the session, and the app's MCP
server (the documented narrator tool-loss / default-agent substitution). It is
not corruption of your life or the world; the on-disk data is intact.

**Fix — restart the Kiro Crew gateway, then reopen the app.** Restarting
re-attaches the app's MCP server to fresh sessions. Use whichever matches how you
run the gateway:

- **Desktop app:** quit and reopen it (it restarts its bundled gateway), then
  reopen Endless Worlds.
- **Service install (Linux/macOS):** restart the Kiro Crew service, e.g.
  `systemctl --user restart kirocrew` on Linux, then reload the dashboard.
- **Foreground gateway:** stop the running `kirocrew gateway` process and start
  it again.

Then verify and resume:

```bash
kirocrew doctor                 # confirm the gateway is healthy
kirocrew app list               # confirm endless-worlds is installed + enabled
```

Reopen the life and advance the turn again — turns are idempotent per
`(runId, turn)`, so re-triggering a stalled turn does not double-apply it.

**If it persists after a restart:** confirm the app is enabled
(`kirocrew app enable endless-worlds`) and that its MCP server path is healed
(the app self-heals `app.json` to its install location on enable). Check
`kirocrew logs` for MCP startup errors around the time the session opened.

## Page art is plain bands / no photo backdrop

**Symptom.** A scene page shows flat tonal bands instead of a traced photo.

**Causes and fixes.**

- **Missing rasterizer or tracer.** Backdrop publishing needs one SVG rasterizer
  (`cairosvg`, `rsvg-convert`, or `librsvg2-2`) on the gateway host, and the
  SCENE lane additionally needs `vtracer` + `pillow`. Install them (see the
  README's Install section). Without them, art falls back to a procedural base;
  the story is unaffected.
- **No free-licensed photo for the subject.** SCENE only uses CC0 / public-domain
  references. Some subjects (and most anime/stylized worlds) have none, so the
  page legitimately degrades to a motif or a tonal base.
- **A transient fetch blip.** A momentary network error or rate-limit can miss;
  the backend now retries the fetch a bounded number of times before settling, so
  a one-off blip should self-recover on the page.

## The Life Star Map (人生星图) shows a blank/white overlay

If the star map white-screens with a React error, reload the app after updating
to the latest build — the known hook-ordering crash (React #310) is fixed. If it
recurs on the latest build, capture the console error and file it (see below).

## CI: "ui/index.mjs is stale"

The committed bundle must match a fresh build. Rebuild and commit it:

```bash
cd web && npm run build
git add ../ui/index.mjs && git commit --amend   # or a new commit
```

Enable the pre-commit hook so this happens automatically:
`git config core.hooksPath .githooks`.

## The app runs old code after an update

A registry install copies the repository as-is; nothing rebuilds after checkout.
After pulling new code, re-sync the app in the gateway (App Store Sync / reinstall
the checkout) so the new `ui/index.mjs` and backend are picked up, then
hard-refresh the dashboard tab to clear a cached bundle.

## The app is missing from the sidebar

Confirm it is installed and enabled:

```bash
kirocrew app list
kirocrew app enable endless-worlds
```

## Filing an issue

Include: what you did, the world/life involved, the exact on-screen or console
error, your gateway platform, and whether a gateway restart changed anything.
Development and PR workflow is in [`CONTRIBUTING.md`](CONTRIBUTING.md).
