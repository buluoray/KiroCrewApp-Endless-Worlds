# devtools — seed a life, run the app for real, screenshot it

Two things live here, and the first is useful on its own:

1. **`fixtures.py` — legal data from the backend's own writers.** A life story you can
   load in seconds without asking an LLM to write one: five seeded lives with turns,
   prose, mounted scenes, a backdrop, a memory graph and keepsakes. Every write goes
   through the app's real writers (`endless_advance_turn`, `SceneLedger`,
   `BackdropStore`, `KeepsakeStore`), so the result is legal by construction and a
   schema change breaks seeding loudly instead of leaving a stale JSON blob behind.
   **Exercising the narrator's generation is a separate exercise** — this path
   deliberately never calls an agent, which is what makes it fast and repeatable.

2. **`uishot.py` — the same app, running for real, screenshotted.** A throwaway
   Kiro Crew instance (its own data home, its own port, nothing near yours), this app
   installed into it, the fixtures seeded, and named shots captured at both widths and
   both themes.

## Use it

```bash
python3 devtools/uishot.py up            # throwaway instance + seeded lives (~5s)
python3 devtools/uishot.py list          # what is seeded, and what can be shot
python3 devtools/uishot.py shot          # every shot, both widths, both themes
python3 devtools/uishot.py shot starmap --theme light --width 390
python3 devtools/uishot.py compare origin/main play starmap   # before / after
python3 devtools/uishot.py down
```

Seeding alone, into any app data dir — your own install included:

```bash
python3 devtools/uishot.py seed --data-dir ~/.kiro/crew/apps/endless-worlds/data
```

Shots land in `$KIROCREW_SCRATCH/uishot/shots` (or the system temp dir), never in the
repo. `UISHOT_OUT` overrides it.

## Why a real instance and not a mock host

The defects that reached a player on this surface were not CSS:

- a scene frame rendered blank because the iframe re-requested its document as a
  navigation, and that second, separately-authenticated request failed where nothing
  could observe it;
- a supply ledger rendered empty rows because compiled bytes came from a cache keyed on
  a compiler version that never moved.

A harness that stubs the app's own API produces neither, so it would have reported both
surfaces as fine. This one drives the real backend, the real routes, the real bundle.

## Every shot carries evidence, not just pixels

A PNG cannot tell you a frame is stuck at its fallback height, or that the box you are
looking at is a 403 body. So each shot also reports:

- the measured geometry of the elements the recipe names;
- every call the app made, with status and duration — a cold `/worlds` parse takes
  seconds, and a slow first call is indistinguishable from a hung one in an image;
- calls still **pending** when the shot was taken (the driver waits for the app's own
  requests to settle first, so anything left is genuinely stuck);
- console errors, and every non-2xx request except a short ignore list of dashboard
  probes that cannot succeed on a headless instance.

A shot with a pending or failed request is printed `WARN`, and the command exits
non-zero.

## Adding a shot

Recipes are data in `shots.py`, so a reviewer can see what a shot claims to show:

```python
Shot(
    "starmap",
    "the life star map as an in-panel sheet",
    steps=[*_open("第三天 · 井边"), {"click": "人生星图"}, {"wait": ".ews-overlay"}],
    measure=(".ews-overlay", ".ews-lens-pane", ".ew-root"),
)
```

Steps are `click` / `clickNth` / `wait` / `scrollTo` / `press` / `seconds`. Address a
life by its **label**, not its title: every life in one world shares the world's title
(and the world's own card carries that text too), so a title click lands on whichever
the shelf renders first. The labels are in `fixtures.py`.

## Things worth knowing before you debug this

- **The app's dashboard URL is `/apps/<name>`**, not the `ui.pages[].route` in
  `app.json`. And a hard navigation there re-boots the SPA onto its default page, so
  the driver reaches the app by clicking its rail entry, the way a person does.
- **Third-party app code does not execute unless the operator trusts it.** The
  throwaway home is created with `agent.apps_trusted: ["endless-worlds"]` — trusting
  this app by name, never the allow-every-third-party-app switch.
- **The instance's ready line is how it is reached.** `--test-mode` prints port and a
  dashboard credential on stdout; there is no other supported way into a fresh
  instance's dashboard without a browser session.
- **Seeding runs under the gateway's interpreter**, discovered from the installed
  console script, because the app's store is built on the host's `AppStorage`. Override
  with `UISHOT_GATEWAY_PYTHON`.
- **Playwright** is discovered from `devtools/node_modules`, then from a global install
  (the browser automation Kiro Crew installs ships one). `UISHOT_PLAYWRIGHT` overrides.
  `npm install` here is only needed when neither exists.
- Shots are captured with `locale: zh-CN` and a fixed timezone, and animations settle
  before capture, so two runs of one shot differ only when the UI did.

## Not covered

- The narrator's generation path (an agent writing a turn). Out of scope on purpose.
- The lineage sheet (传承回顾) needs an heir life; the fixtures do not build one yet.
- Pixel diffing. `compare` puts before/after PNGs side by side for a person to judge;
  nothing here asserts on pixels, because a threshold that fails on antialiasing
  teaches people to ignore it.
