#!/usr/bin/env python3
"""uishot — bring up a real, seeded instance of this app and screenshot it.

    python3 devtools/uishot.py up                 # throwaway instance + fixture data
    python3 devtools/uishot.py list               # what can be shot, and what it shows
    python3 devtools/uishot.py shot play starmap  # named shots (all of them if none named)
    python3 devtools/uishot.py shot play --theme light --width 390
    python3 devtools/uishot.py compare origin/main play   # before/after, side by side
    python3 devtools/uishot.py down

Why this exists in this shape: the app renders inside the dashboard, and the defects
that reach a player are usually NOT css — a scene frame blank because a second
authenticated request failed unseen, a ledger empty because compiled bytes came from
a cache whose version never moved. Both are invisible to a harness that stubs the
app's own API, so this drives the real backend, the real routes and the real bundle.

Every shot prints the measured geometry, the console errors and every non-2xx request
next to the PNG, because a screenshot on its own cannot tell you a frame is 320px tall
or that it is showing a 403 body.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
import instance as inst  # noqa: E402
import shots as shotdefs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
#: Where the instance, its log and the shots live. A session-scoped scratch dir when
#: the host provides one (it is reclaimed with the session); the system temp dir
#: otherwise. Never inside the repo: none of this is source.
WORK = Path(
    os.environ.get("UISHOT_WORK")
    or (Path(os.environ.get("KIROCREW_SCRATCH") or tempfile.gettempdir()) / "uishot")
)
STATE = WORK / "instance.json"
LOG = WORK / "gateway.log"
SESSION = WORK / "browser-session.json"
OUT = Path(os.environ.get("UISHOT_OUT") or (WORK / "shots"))


def _node_playwright() -> str:
    """Where the driver should find Playwright.

    Search order, cheapest first: an explicit override; this directory's own
    ``node_modules``; then a Playwright already installed globally — the browser
    automation Kiro Crew itself installs ships one, and reusing it avoids a second
    ~150MB browser download for a dev-only tool. Falls back to the bare specifier so
    the failure, if there is one, is Node's own clear "cannot find package".
    """
    explicit = os.environ.get("UISHOT_PLAYWRIGHT")
    if explicit:
        return explicit
    here = Path(__file__).resolve().parent
    candidates = [here / "node_modules" / "playwright"]
    got = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True)
    if got.returncode == 0 and got.stdout.strip():
        groot = Path(got.stdout.strip())
        candidates += [
            groot / "playwright",
            groot / "@playwright" / "cli" / "node_modules" / "playwright",
            groot / "@playwright" / "mcp" / "node_modules" / "playwright",
        ]
    for cand in candidates:
        if cand.is_dir():
            return str(cand)
    return "playwright"


def cmd_seed(args: argparse.Namespace) -> int:
    """Seed fixture lives into ANY app data dir — no screenshot harness involved.

    Useful on its own: it is how you get a playable life in seconds without asking an
    LLM to write one. The data is legal by construction because it goes in through the
    backend's own writers; testing the narrator's GENERATION is a different exercise
    and deliberately not what this does.
    """
    if args.data_dir:
        target = args.data_dir
    else:
        if not STATE.exists():
            print("no instance running — pass --data-dir, or `uishot up` first", file=sys.stderr)
            return 2
        target = inst.Instance.from_json(STATE.read_text(encoding="utf-8")).data_dir
    runs = _seed_into(target)
    print(f"seeded {len(runs)} lives into {target}")
    for key, run in runs.items():
        print(f"  {key:<10} {run}")
    return 0


def _seed_into(data_dir: Path, home: Path | None = None) -> dict[str, str]:
    """Run the fixture builder in a child process under the gateway's interpreter.

    The app's store is built on the host's ``AppStorage``, so seeding has to happen
    under an interpreter that can import the host package — which is not necessarily
    the one running this CLI.
    """
    env = {**os.environ}
    if home is not None:
        env["KIROCREW_HOME"] = str(home)
    proc = subprocess.run(
        [
            str(inst.gateway_interpreter()),
            str(Path(__file__).resolve().parent / "fixtures.py"),
            str(data_dir),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise SystemExit("seeding failed:\n" + (proc.stderr or proc.stdout)[-1500:])
    return dict(json.loads(proc.stdout.strip().splitlines()[-1]))


def _seed(got: inst.Instance) -> dict[str, str]:
    return _seed_into(got.data_dir, got.home)


def cmd_up(args: argparse.Namespace) -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    print(inst.stop(STATE))
    # A saved browser session belongs to the instance that issued it: it also carries
    # the app's own client state, so reusing it across instances makes the UI request
    # scenes and backdrops for run ids that no longer exist (404s and hung fetches that
    # look like app bugs).
    SESSION.unlink(missing_ok=True)
    print("starting a throwaway instance (its own data home and port)…")
    got = inst.start(WORK / "home", LOG)
    STATE.write_text(got.to_json(), encoding="utf-8")
    print(f"  gateway ready on {got.base_url} (pid {got.pid})")
    if not args.no_seed:
        runs = _seed(got)
        print(f"  seeded {len(runs)} lives: " + ", ".join(f"{k}={v[:8]}" for k, v in runs.items()))
    print(f"  data:   {got.data_dir}")
    print(f"  log:    {LOG}")
    return 0


def cmd_down(_args: argparse.Namespace) -> int:
    print(inst.stop(STATE))
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    print("scenarios (seeded lives):")
    for sc in fixtures.SCENARIOS:
        print(f"  {sc.key:<10} {sc.label}\n             {sc.exercises}")
    print("\nshots:")
    for s in shotdefs.SHOTS:
        sizes = " ".join(f"{w}x{h}" for w, h in s.sizes)
        print(
            f"  {s.key:<16} [{s.scenario}] {sizes} {'/'.join(s.themes)}\n                   {s.describe}"
        )
    return 0


def _run_one(
    got: inst.Instance, shot: shotdefs.Shot, width: int, height: int, theme: str, out_dir: Path
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{shot.key}-{width}-{theme}.png"
    job = {
        "baseUrl": got.base_url,
        "token": got.token,
        "app": inst.APP_NAME,
        "rail": inst.RAIL_LABEL,
        "resetKeys": list(inst.RESET_KEYS),
        # One browser session reused across shots: the ready credential's click window
        # is minutes, the cookie it exchanges for lasts hours.
        "session": str(SESSION),
        "out": str(png),
        "width": width,
        "height": height,
        "theme": theme,
        "fullPage": shot.full_page,
        # Width decides which extra steps apply: this app is two layouts, not one
        # layout at two sizes.
        "steps": [*shot.steps, *(shot.phone_steps if width < 500 else shot.desktop_steps)],
        "measure": list(shot.measure),
        # UI-position expectations travel with the job so the browser judges them where
        # the boxes are, and the CLI only has to report the verdict.
        "expects": [
            {
                "selector": e.selector,
                "presence": e.presence,
                "min_w": e.min_w,
                "min_h": e.min_h,
                "covers_x": e.covers_x,
                "why": e.why,
            }
            for e in shot.expects
        ],
    }
    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "driver.mjs")],
        input=json.dumps(job),
        env={**os.environ, "PLAYWRIGHT_PKG": _node_playwright()},
        capture_output=True,
        text=True,
        timeout=300,
    )
    try:
        rep = json.loads(proc.stdout or "{}")
    except ValueError:
        return {"shot": str(png), "reached": False, "failure": (proc.stderr or "")[-400:]}
    return rep


def _print_report(rep: dict) -> bool:
    ok = (
        bool(rep.get("reached"))
        and not rep.get("badRequests")
        and not rep.get("pending")
        and not rep.get("violations")
    )
    mark = "ok  " if ok else "WARN"
    print(f"  {mark} {rep.get('shot')}")
    measured = rep.get("measured") or {}
    for sel, box in measured.items():
        if sel.startswith("#"):
            continue
        print(f"       {sel}: {box if box else 'ABSENT'}")
    if measured.get("#frames"):
        print(f"       iframes: {measured['#frames']}")
    for line in rep.get("appRequests") or []:
        print(f"       app:     {line}")
    for line in rep.get("pending") or []:
        print(f"       PENDING: {line}")
    for line in rep.get("violations") or []:
        print(f"       BROKE:   {line}")
    for line in rep.get("badRequests") or []:
        print(f"       request: {line}")
    for line in rep.get("consoleErrors") or []:
        print(f"       console: {line}")
    if any("/api/auth/refresh" in line for line in rep.get("badRequests") or []):
        print("       hint:    the dashboard session expired — `uishot up` again")
    if rep.get("failure"):
        print(f"       failed: {rep['failure']}")
        for step in rep.get("steps") or []:
            if step.startswith("FAILED"):
                print(f"       step:   {step}")
    return ok


def _sync_app_code(got: inst.Instance) -> list[str]:
    """Copy the worktree's current app code over the installed copy.

    `install_app` COPIES, so after any edit the instance is still serving the bytes it
    was installed with — a shot then shows the old UI and reports the old geometry,
    which is the most expensive failure this harness can have (it says a change is
    inert when it was never loaded). Syncing before every shot run removes the
    possibility rather than documenting it.

    The UI bundle takes effect immediately (the app is installed in dev mode, which
    serves it no-store). Backend files are copied too and are reported, because those
    need the instance restarted to take effect and the caller has to know.
    """
    installed = got.home / "apps" / inst.APP_NAME
    notes: list[str] = []
    bundle = ROOT / "ui" / "index.mjs"
    target = installed / "ui" / "index.mjs"
    if bundle.exists() and (not target.exists() or bundle.read_bytes() != target.read_bytes()):
        shutil.copy2(bundle, target)
        notes.append("synced ui/index.mjs (dev mode serves it no-store, no restart needed)")
    stale_backend = [
        p.name
        for p in sorted((ROOT / "backend").glob("*.py"))
        if not (installed / "backend" / p.name).exists()
        or p.read_bytes() != (installed / "backend" / p.name).read_bytes()
    ]
    if stale_backend:
        for name in stale_backend:
            shutil.copy2(ROOT / "backend" / name, installed / "backend" / name)
        notes.append(
            f"synced backend/{{{','.join(stale_backend[:4])}{'…' if len(stale_backend) > 4 else ''}}}"
            " — a running gateway keeps the code it imported, so `uishot up` to load it"
        )
    return notes


def cmd_shot(args: argparse.Namespace) -> int:
    if not STATE.exists():
        print("no instance running — `uishot up` first", file=sys.stderr)
        return 2
    got = inst.Instance.from_json(STATE.read_text(encoding="utf-8"))
    for note in _sync_app_code(got):
        print(note)
    wanted = args.names or [s.key for s in shotdefs.SHOTS]
    unknown = [n for n in wanted if n not in shotdefs.BY_KEY]
    if unknown:
        print(f"unknown shot(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    all_ok = True
    for name in wanted:
        shot = shotdefs.BY_KEY[name]
        sizes = [(args.width, args.height)] if args.width else list(shot.sizes)
        themes = [args.theme] if args.theme else list(shot.themes)
        print(f"{shot.key} — {shot.describe}")
        for width, height in sizes:
            for theme in themes:
                rep = _run_one(got, shot, width, height, theme, args.out or OUT)
                all_ok &= _print_report(rep)
    return 0 if all_ok else 1


def cmd_review(args: argparse.Namespace) -> int:
    """Capture everything and reduce it to one sheet per (width, theme) plus a report.

    This is the shape an agent can actually review: reading forty PNGs costs about as
    much as reading the app's source, and a per-file loop encourages skimming the
    filenames instead of the pixels. One sheet is one read, the numbers and the
    verdicts are in `report.json` next to it, and a failing tile is outlined so it is
    found before it is read.
    """
    if not STATE.exists():
        print("no instance running — `uishot up` first", file=sys.stderr)
        return 2
    got = inst.Instance.from_json(STATE.read_text(encoding="utf-8"))
    for note in _sync_app_code(got):
        print(note)
    out = args.out or (OUT / "review")
    out.mkdir(parents=True, exist_ok=True)
    wanted = args.names or [s.key for s in shotdefs.SHOTS]

    lanes: dict[tuple[int, str], list[dict]] = {}
    report: list[dict] = []
    failed = 0
    for name in wanted:
        shot = shotdefs.BY_KEY[name]
        for width, height in shot.sizes:
            for theme in shot.themes:
                if args.theme and theme != args.theme:
                    continue
                if args.width and width != args.width:
                    continue
                rep = _run_one(got, shot, width, height, theme, out)
                # One predicate for the count, the printed reasons, and the sheet's own
                # red marker — three readers that must never disagree about what is red.
                reasons = _attention(rep)
                failed += 1 if reasons else 0
                rep["shotKey"] = shot.key
                rep["width"] = width
                rep["theme"] = theme
                report.append(rep)
                lanes.setdefault((width, theme), []).append(
                    {
                        "png": rep.get("shot"),
                        "bad": bool(reasons),
                        "caption": _caption(shot, rep),
                    }
                )

    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    sheets: list[str] = []
    for (width, theme), tiles in sorted(lanes.items()):
        # Fewer columns = bigger tiles = readable app text, at the cost of more sheets.
        # The default is a TRIAGE density: enough to spot an empty pane or a white-on-
        # white surface, not enough to read the app's own 13px body text (measured, not
        # assumed — at 3 columns a 1440px shot lands at ~0.35x and CJK body text is a
        # smudge). Read the individual PNG once a tile looks wrong; at 1440x900 it is
        # within the image-size cap and fully legible.
        columns = args.cols or (4 if width < 500 else 3)
        # Rows per sheet are budgeted by TILE SHAPE, not by count: a phone capture is
        # taller than it is wide, so the same grid that fits on a desktop sheet runs
        # past the 2000px cap and gets downscaled until nothing is legible. Fewer rows
        # of narrow tiles keeps the scale near 1.
        per_sheet = columns * (2 if width < 500 else 4)
        pages = [tiles[i : i + per_sheet] for i in range(0, len(tiles), per_sheet)]
        for n, group in enumerate(pages, 1):
            suffix = f"-{n}" if len(pages) > 1 else ""
            sheet = out / f"sheet-{width}-{theme}{suffix}.png"
            proc = subprocess.run(
                ["node", str(Path(__file__).resolve().parent / "sheet.mjs")],
                input=json.dumps(
                    {
                        "out": str(sheet),
                        "title": (
                            f"uishot · {width}px · {theme} · {len(group)} shots"
                            + (f" · sheet {n}/{len(pages)}" if len(pages) > 1 else "")
                        ),
                        "columns": columns,
                        "tiles": group,
                    }
                ),
                env={**os.environ, "PLAYWRIGHT_PKG": _node_playwright()},
                capture_output=True,
                text=True,
                timeout=300,
            )
            lines = (proc.stdout or "").strip().splitlines()[-1:] or [""]
            try:
                meta = json.loads(lines[0])
                sheets.append(f"{meta['out']}  {meta['px'][0]}x{meta['px'][1]}px")
            except ValueError:
                print(
                    f"sheet failed for {width}/{theme}{suffix}: {(proc.stderr or '')[-300:]}",
                    file=sys.stderr,
                )

    print(f"\n{len(report)} shots, {failed} needing attention")
    for rep in report:
        reasons = _attention(rep)
        if not reasons:
            continue
        print(f"  {rep['shotKey']} {rep['width']}/{rep['theme']}")
        for line in reasons:
            print(f"      {line}")
    print("\nreport: " + str(out / "report.json"))
    for sheet in sheets:
        print("sheet:  " + sheet)
    return 1 if failed else 0


def _attention(rep: dict) -> list[str]:
    """Every reason this shot needs a human, as printable lines. Empty means clean.

    The counter and the printer both read THIS list, because the two used to be written
    separately and drifted: a shot with a failed request was counted in "N needing
    attention" while the printer explained only violations and unreached shots, so a red
    run said something was wrong and refused to say what. A gate that withholds the
    reason costs an artifact download to read one line.
    """
    out: list[str] = []
    # Why a shot never reached its surface comes first: the violations that follow from
    # it are consequences, and reading them first sends you to the wrong place.
    if not rep.get("reached"):
        out.append(f"UNREACHED: {rep.get('failure') or 'unknown'}")
        out += [f"  step: {s}" for s in rep.get("steps") or [] if s.startswith("FAILED")]
        out += [f"  console: {line}" for line in (rep.get("consoleErrors") or [])[:3]]
    out += [f"BROKE: {line}" for line in rep.get("violations") or []]
    out += [f"REQUEST: {line}" for line in rep.get("badRequests") or []]
    out += [f"PENDING: {line}" for line in rep.get("pending") or []]
    return out


def _caption(shot: shotdefs.Shot, rep: dict) -> str:
    """One tile's caption: what it is, then only the facts a picture cannot carry."""
    parts = [f"{shot.key} — {shot.describe.split('—')[0].strip()[:70]}"]
    for sel, box in (rep.get("measured") or {}).items():
        if sel.startswith("#") or not box:
            continue
        parts.append(f"{sel} {box['w']}x{box['h']}")
    for line in rep.get("violations") or []:
        parts.append("BROKE " + line.split(" — ")[0])
    for line in rep.get("badRequests") or []:
        parts.append("req " + line[:60])
    for line in rep.get("pending") or []:
        parts.append("pending " + line[:60])
    if rep.get("failure"):
        parts.append("failed: " + str(rep["failure"])[:70])
    return "\n".join(parts)


def cmd_compare(args: argparse.Namespace) -> int:
    """Shoot the same surfaces from a baseline ref and from the working tree.

    The bundle is what the dashboard serves, so the baseline is produced by building
    the ref's own web sources — not by checking out files over the working tree, which
    would destroy uncommitted work.
    """
    if not STATE.exists():
        print("no instance running — `uishot up` first", file=sys.stderr)
        return 2
    got = inst.Instance.from_json(STATE.read_text(encoding="utf-8"))
    installed_ui = got.home / "apps" / inst.APP_NAME / "ui" / "index.mjs"
    if not installed_ui.exists():
        print(f"installed bundle missing at {installed_ui}", file=sys.stderr)
        return 2

    after = (args.out or OUT) / "after"
    before = (args.out or OUT) / "before"
    wanted = args.names or [s.key for s in shotdefs.SHOTS]

    # Sync first, exactly as `shot` and `review` do. Without it the "after" side
    # renders whatever bundle happens to be installed — and the previous run of THIS
    # command installed the baseline's bundle and then restored a copy of that, so
    # before and after came out byte-identical and the change read as inert. That is
    # the failure this harness is least able to afford here: `compare` is the command
    # someone runs specifically to decide whether an edit did anything.
    for note in _sync_app_code(got):
        print(note)

    print(f"after  — working tree ({len(wanted)} shot(s))")
    for name in wanted:
        _print_report(_run_one(got, shotdefs.BY_KEY[name], *shotdefs.DESKTOP, "dark", after))

    print(f"before — building {args.ref} in a scratch worktree…")
    with tempfile.TemporaryDirectory(prefix="uishot-base-") as tmp:
        tree = Path(tmp) / "tree"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(tree), args.ref],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
        )
        try:
            subprocess.run(["npm", "ci"], cwd=str(tree / "web"), check=True, capture_output=True)
            subprocess.run(
                ["npm", "run", "build"], cwd=str(tree / "web"), check=True, capture_output=True
            )
            keep = installed_ui.with_suffix(".mjs.uishot-keep")
            shutil.copy2(installed_ui, keep)
            shutil.copy2(tree / "ui" / "index.mjs", installed_ui)
            try:
                for name in wanted:
                    _print_report(
                        _run_one(got, shotdefs.BY_KEY[name], *shotdefs.DESKTOP, "dark", before)
                    )
            finally:
                shutil.move(str(keep), str(installed_ui))
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(tree)],
                cwd=str(ROOT),
                capture_output=True,
            )
    print(f"\nbefore: {before}\nafter:  {after}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="uishot", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("up", help="start a throwaway instance and seed it")
    up.add_argument("--no-seed", action="store_true", help="start empty (no fixture lives)")
    up.set_defaults(fn=cmd_up)

    sub.add_parser("down", help="stop the instance").set_defaults(fn=cmd_down)
    sub.add_parser("list", help="list scenarios and shots").set_defaults(fn=cmd_list)

    sd = sub.add_parser("seed", help="seed fixture lives into an app data dir")
    sd.add_argument(
        "--data-dir",
        type=Path,
        help="the app data dir to seed (default: the running throwaway instance's)",
    )
    sd.set_defaults(fn=cmd_seed)

    sh = sub.add_parser("shot", help="capture named shots (default: all)")
    sh.add_argument("names", nargs="*")
    sh.add_argument("--theme", choices=("dark", "light"))
    sh.add_argument("--width", type=int)
    sh.add_argument("--height", type=int, default=900)
    sh.add_argument("--out", type=Path)
    sh.set_defaults(fn=cmd_shot)

    rv = sub.add_parser("review", help="capture everything as contact sheets + a report")
    rv.add_argument("names", nargs="*")
    rv.add_argument("--theme", choices=("dark", "light"))
    rv.add_argument("--width", type=int)
    rv.add_argument("--out", type=Path)
    rv.add_argument(
        "--cols",
        type=int,
        help="tiles per row (default 3, or 2 at phone width). Use 1-2 when you need to "
        "read the app's own text in the sheet rather than just spot a broken surface",
    )
    rv.set_defaults(fn=cmd_review)

    cp = sub.add_parser("compare", help="shoot a baseline ref and the working tree")
    cp.add_argument("ref")
    cp.add_argument("names", nargs="*")
    cp.add_argument("--out", type=Path)
    cp.set_defaults(fn=cmd_compare)

    args = ap.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
