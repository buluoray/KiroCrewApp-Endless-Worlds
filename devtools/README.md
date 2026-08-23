# devtools — seed a life, run the app for real, screenshot it

Two things live here, and the first is useful on its own:

1. **`fixtures.py` — legal data from the backend's own writers.** A life story you can
   load in seconds without asking an LLM to write one: seven seeded lives with turns,
   prose, mounted scenes, a backdrop, a memory graph and keepsakes — including the two
   states nobody reaches by playing, a **closed life** and the **next generation** that
   inherits a person and an heirloom from it.

   Every write goes through the app's real writers (`endless_advance_turn`,
   `SceneLedger`, `BackdropStore`, `KeepsakeStore`, and `legacy.build_bridge_record` for
   the inheritance). That is the load-bearing decision: the data is legal by
   construction, and a schema change breaks seeding **at the call that changed** rather
   than leaving a hand-written JSON blob that renders a state the app can no longer
   produce. It never calls an agent — exercising the narrator's generation is a
   different exercise, and keeping it out is what makes this fast and repeatable.

   Usable on its own, against any app data dir including one you are playing:

   ```bash
   python3 devtools/uishot.py seed --data-dir ~/.kiro/crew/apps/endless-worlds/data
   ```

2. **`uishot.py` — the same app, running for real, screenshotted AND asserted.** A
   throwaway Kiro Crew instance (its own data home, its own port, nothing near yours),
   this app installed into it, the fixtures seeded, and named shots captured at both
   widths and both themes — each one checked against what must be true about where
   things landed.

## Use it

```bash
python3 devtools/uishot.py up            # throwaway instance + seeded lives (~5s)
python3 devtools/uishot.py list          # what is seeded, and what can be shot
python3 devtools/uishot.py shot          # every shot, both widths, both themes
python3 devtools/uishot.py shot starmap --theme light --width 390
python3 devtools/uishot.py review        # the same, reduced to contact sheets + a report
python3 devtools/uishot.py compare origin/main play starmap   # before / after
python3 devtools/uishot.py down
```

`shot` and `review` **sync this worktree's app code into the instance first**, so a
frontend edit is in the bundle the shot renders. Without that step the instance keeps
serving the bytes it was installed with, and a shot reports the old geometry — the most
expensive failure this harness can have, because it says a change is inert when it was
never loaded. The UI takes effect immediately (the app is installed in dev mode, which
serves it no-store); a backend edit is copied too and reported as needing `up`.

## What must be true, not what it looked like

Shots are not only pictures. Each recipe can carry `Expect(...)` entries, and a
violated one makes the command exit non-zero:

```python
Expect(
    ".ews-overlay",
    min_w=280,
    min_h=300,
    covers_x=".ew-play-root",
    why="the sheet must span the column it covers",
)
Expect(
    ".ew-slot-on",
    presence="absent",
    why="the scene frames render outside that column, so they must step aside",
)
```

They are deliberately **relationships and floors, never pinned pixel values**: "the
sheet covers the play column" is a property the layout must keep, while its exact height
changes for legitimate reasons every time content does. A pinned number fails on every
innocent edit and teaches everyone to ignore the gate.

`presence="absent"` means *not visible*, not *not in the DOM* — a `display:none` element
is still queryable, and "it stepped aside" has to mean it stopped rendering.

## Reviewing a run without reading forty files

`review` writes one contact sheet per (width, theme) plus `report.json`:

```
26 shots, 1 needing attention
  BROKE starmap 1440/dark: .ew-slot-on: is visible (1156x175) but must have stepped aside
report: …/review/report.json
sheet:  …/review/sheet-1440-dark-1.png  1600x1807px
```

Sheets are sized to stay under 2000px on every side, because a reviewing agent's image
API refuses anything larger — a sheet nobody can open is worse than no sheet. They
paginate by rows to get there rather than shrinking until the tiles are mush.

**A sheet's legibility differs by lane, and both numbers are measured rather than
assumed.** The phone lane packs four 390px captures per row, which lands near 1:1 — the
app's own Chinese body text is readable straight off the sheet. The desktop lane packs
three 1440px captures, which lands at ~0.35x: enough to see that a pane is empty, that a
surface went white-on-white, or that a widget is still showing under a sheet, and NOT
enough to read 13px body text. So on the desktop lane a sheet is a triage index: find
the tile that looks wrong, then open that single PNG — at 1440x900 it is inside the cap
and fully legible. `--cols 1` trades sheet count for legibility when you need the text.

Base64 is not a way around any of this: the image is already base64 on the wire, and the
2000px limit is on pixel dimensions, not bytes.

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

## In CI

The `ui-shots` job installs the app into a throwaway gateway, seeds the fixtures, runs
`review`, and uploads the sheets and `report.json` as an artifact. `kiro-cli` is absent
there and is not needed: the gateway reaches ready and serves the dashboard without it
(verified by probe), and no shot starts an agent session.

## Not covered

- The narrator's generation path (an agent writing a turn). Out of scope on purpose.
- Pixel diffing. `compare` puts before/after PNGs side by side for a person to judge;
  nothing here asserts on pixels, because a threshold that fails on antialiasing
  teaches people to ignore it.
