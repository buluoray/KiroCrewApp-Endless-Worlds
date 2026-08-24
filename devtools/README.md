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

`fits_x=True` is the one assertion a screenshot cannot substitute for: it compares an
element's `scrollWidth` against the width it actually shows, so content that runs off
the side is a violation rather than a frame that merely looks fine. That defect is
invisible in a picture — a block does not look broken when it silently stops, and the
columns past the fold are simply gone. Measured on the performance page before it was
adapted: 553px of table in a 358px viewport, 195px of it unreachable.

Put it on the block that OWNS its width, and never on a table wrapped in a deliberate
scroll region — WCAG Reflow (1.4.10) exempts a data table's own two-axis scroll and
exempts nothing around it, so the assertion belongs on the page while the table's
overflow stays contained in its `role="region"` scroller.

## Reviewing a run without reading forty files

`review` writes one contact sheet per (width, theme) plus `report.json`:

```
26 shots, 1 needing attention
  starmap 1440/dark
      BROKE: .ew-slot-on: is visible (1156x175) but must have stepped aside
report: …/review/report.json
sheet:  …/review/sheet-1440-dark-1.png  1600x1807px
```

**One predicate decides both the count and the explanation** (`_attention`), because
those were written separately once and drifted: a shot whose only problem was a failed
request got counted in "N needing attention" while the printer explained only violations
and unreached shots. The run went red and named nothing, which costs an artifact download
to read one line. `backend/tests/test_devtools_review_explains.py` pins it — every signal
that can turn a run red must also be able to explain itself.

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

**An aborted request is judged by whose it is** (`failures.mjs`, unit-tested). The
dashboard fires its own boot calls — agents, theme, approvals, its project icon — while
the driver is still navigating to the app, and the browser cancels whatever is in flight
when it navigates. Those aborts are a race against the host's cold start, not a defect,
and they are nondeterministic: one commit passed a run and failed the next on nothing but
runner speed, which is the kind of red that teaches people to hit rerun. So a non-app
abort is dropped. **An abort of the app's own request is still a failure**, and that
distinction is the point — a scene frame whose second document request was cancelled is
exactly the defect class this harness was built for, so a blanket ignore-all-aborts rule
would have hidden it.

## What a screenshot cannot decide: whether text is legible

The tempting next step is to make a shot prove the captured frame is *readable*, so the
white-on-white class of regression cannot ship. **Two pixel statistics were tried and
both failed; they are recorded here so the next person does not re-derive them.**

- **Luminance spread** (the p2/p98 gap of the frame) — the idea being that a frame whose
  text vanished collapses toward one tone.
- **Edge density** (the share of pixels on a detected edge) — the idea being that
  glyphs are edges.

Neither separated a legible frame from one whose text had been deliberately forced
invisible. The reason is structural rather than a bad threshold: the world's backdrop art
showing through the frosted surface carries **more** variance and **more** edges than the
text does. A frame with invisible text measured 0.054 edge density where a healthy frame
measured 0.024 — the broken one scored higher, so no threshold can order them.

A second trap sits under any attempt to fix that by cropping to the element:
**an element screenshot of a `backdrop-filter` surface does not composite against the
page behind it.** Captured alone, the frame renders over a blank base, and a frame that
is dark on screen measured 98% white. A pixel gate there is grading a surface that does
not exist.

**What replaced it is static and deterministic** — `backend/tests/test_widget_contrast.py`
computes the WCAG contrast of the widget's own declared text colours against its own
scrim, composited over the brightest and darkest ground the art can supply (white and
black), and holds 4.5:1 for body text and 3.0:1 for labels. No browser, no flake, and it
fails on the exact bug the pixel metrics let through.

It also earned its place during design rather than after: at a scrim alpha of `.58` the
body text came to 4.20:1 and the labels to 2.50:1 over white art — both under AA. The
shipped values (`.66` scrim, `.66` label alpha) were solved to satisfy it, giving 5.63:1
and 3.47:1.

The rule that generalises: a legibility question with a numeric answer belongs in a
static test over the declared colours. A screenshot's job is to prove the surface exists,
is positioned, and carries the content it should — not to grade its contrast.

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

Steps are `click` / `label` / `clickSel` / `clickNth` / `wait` / `scrollTo` / `press` /
`seconds`. Address a
life by its **label**, not its title: every life in one world shares the world's title
(and the world's own card carries that text too), so a title click lands on whichever
the shelf renders first. The labels are in `fixtures.py`.

`label` clicks by accessible name, which is how to reach a control the app renders
TWICE and hides one of by width — the shelf's row actions are inline buttons on a
desktop and fold into a kebab on a phone, and the name carries the life's label so it
is unique on a shelf of five. `clickSel` clicks a CSS selector, for a control whose
only name is a number (`.ew-perf-row:last-of-type .ew-perf-open`) — addressing the last
row by position survives a scenario growing another turn. Both match `:visible` only,
because the hidden twin is the common case at 390px.

Adding `"optional": True` to a click makes a missing target a *skipped* step instead of
a failed shot, and it is for exactly one situation: a control whose presence depends on
REMEMBERED ui state, so whether it is there depends on what ran before. The rail's
open/closed state is the real case — past 1100px an open rail hides the shelf's own life
rows, so the desktop route to the performance page runs through closing it, and the
previous shot may have left it closed already. It is not for papering over a flake: the
skip is reported and the expectations still decide the verdict.

## Things worth knowing before you debug this

- **The app's dashboard URL is `/apps/<name>`**, not the `ui.pages[].route` in
  `app.json`. And a hard navigation there re-boots the SPA onto its default page, so
  the driver reaches the app by clicking its rail entry, the way a person does.
- **Third-party app code does not execute unless the operator trusts it.** The
  throwaway home is created with `agent.apps_trusted: ["endless-worlds"]` — trusting
  this app by name, never the allow-every-third-party-app switch.
- **The instance is isolated by TWO variables, and the guard checks OWNERSHIP.**
  `KIROCREW_HOME` alone is not isolation: enabling an app registers its agents into
  kiro-cli's own `~/.kiro/agents`, which no data-home override moves, so an instance
  once repointed the operator's live specs at its scratch install — and because the
  app's MCP server resolves its data dir from its own file location, the operator's next
  session read fixture data and reported their own save as missing. `KIRO_HOME` plus
  `KIROCREW_POD=1` redirects that write, and `_assert_untouched` refuses to start if any
  shared spec now *points into this instance*. It asks that question rather than "did
  these files change", because this harness shares a machine with the gateway driving
  it: the host rewrites every spec at once when it re-registers agents, and a
  change-keyed guard called that broken isolation and refused to start on a working
  machine. An ambient change that leads nowhere near the instance is reported, not
  fatal. `backend/tests/test_devtools_isolation_guard.py` pins both halves.
- **The instance's ready line is how it is reached.** `--test-mode` prints port and a
  dashboard credential on stdout; there is no other supported way into a fresh
  instance's dashboard without a browser session.
- **Seeding runs under an interpreter that can import the host gateway package**,
  because the app's store is built on the host's `AppStorage`. Search order: the
  `UISHOT_GATEWAY_PYTHON` override, the current interpreter if it already has the
  package, then the interpreter behind the installed console script. A pipx install
  satisfies only the third of those, which is why CI installs the wheel into its own
  interpreter instead.
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

**Installing the host gateway is the part that has cost the most, and it has two
requirements that are easy to satisfy one at a time.**

1. **It must be a released wheel, not a git source install.** The host's dashboard
   bundle is produced by that repo's own build step and is not in its source tree, so
   `pip install git+…` yields the Python package with no SPA: the gateway comes up and
   serves a "Dashboard HTML not found" page, and every shot photographs an error page.
   A wheel carries the built bundle — measured, not assumed: a wheel-installed package
   holds `static/dist/index.html` and its 479 asset files, where a source checkout
   holds none.
2. **It must land where the job's own interpreter can import it.** The official
   installer prefers pipx, which puts the package in its own managed venv. That is
   correct for a person and useless here: `gateway_interpreter()` then finds nothing
   that can import the host package, and `up` cannot start an instance at all.

So the job resolves the release channel's own signed feed for the version and its
sha256, then installs that exact wheel with the hash in the URL fragment. The feed is
the same pointer the installer reads, so this tracks the channel instead of pinning a
version that rots silently, and a wheel swapped underneath us fails the install rather
than the assertions.

**`instance.py` refuses to start against a gateway serving the no-dashboard marker**,
naming the remedy. That check is not a nicety, because the failure it catches is not
naturally fast: with no dashboard, each shot waits out its own locator timeout, so a
wrong install spent **33 minutes** producing 52 identical "element missing" lines and no
cause. The same 52 shots against a real dashboard capture and assert in about **4
minutes**, which is what makes this affordable as a PR gate — the 33 minutes measured
the failure mode, not the gate.

For the same reason `review` prints `UNREACHED <shot>: <failure>` plus the failing step,
console output and requests, not only the violated expectations. The first CI failure
here was diagnosable only by downloading the artifact and looking at a PNG, which is a
diagnosis nobody makes at 2am.

## Not covered

- The narrator's generation path (an agent writing a turn). Out of scope on purpose.
- Pixel diffing. `compare` puts before/after PNGs side by side for a person to judge;
  nothing here asserts on pixels, because a threshold that fails on antialiasing
  teaches people to ignore it.
