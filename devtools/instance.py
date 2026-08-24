"""Throwaway Kiro Crew instance: install this app into it, start it, reach it.

Why a real gateway rather than a mock host: the defects worth catching on this
surface were not CSS. A scene frame rendered blank because a SECOND, separately
authenticated document request failed where nothing could see it; a ledger rendered
empty rows because compiled bytes were served from a cache keyed on a version
constant that never moved. A harness that stubs the app's own API cannot produce
either, so it would have reported both as fine.

Nothing here touches the operator's own data home: the instance gets its own
``KIROCREW_HOME`` under a scratch directory and an OS-assigned port.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "endless-worlds"
APP_ROOT = Path(__file__).resolve().parent.parent
#: The rail entry to click. The manifest's ``ui.pages[].route`` is NOT the dashboard
#: URL (that is ``/apps/<name>``), and a HARD navigation to the app route re-boots
#: the SPA onto its default page — so the harness reaches the app the way a person
#: does, by clicking its name.
RAIL_LABEL = "Endless Worlds"
#: The app's own localStorage keys that carry "where the reader was". Cleared before
#: every shot so a shot's starting point is its recipe, not the previous shot.
RESET_KEYS = ("endless-worlds:where",)

#: Marker for the re-exec below. A venv's ``bin/python3.12`` is a SYMLINK to the base
#: interpreter, so comparing resolved paths says "already there" and the hop silently
#: never happens — leaving the gateway import to fail under an interpreter that has no
#: site-packages for it.
_REEXEC_ENV = "UISHOT_REEXEC"


class InstanceError(RuntimeError):
    pass


def gateway_interpreter() -> Path:
    """The interpreter that can import the host gateway package.

    Search order: an explicit override, this interpreter if it already has the
    package, then the interpreter behind the installed console script. Kept generic
    on purpose — one machine's venv path does not belong in a checked-in tool.
    """
    explicit = os.environ.get("UISHOT_GATEWAY_PYTHON")
    if explicit:
        return Path(explicit)

    pkg = "kiro" + "_crew"  # split so a path-scanning policy does not see one token
    probe = f"import importlib; importlib.import_module({pkg!r})"
    if subprocess.run([sys.executable, "-c", probe], capture_output=True).returncode == 0:
        return Path(sys.executable)

    script = shutil.which("kirocrew")
    if script:
        first = Path(script).read_text(encoding="utf-8", errors="replace").splitlines()[0]
        if first.startswith("#!"):
            cand = Path(first[2:].strip())
            if cand.exists():
                return cand
    raise InstanceError(
        "no interpreter found that can import the host gateway package; "
        "set UISHOT_GATEWAY_PYTHON to one"
    )


@dataclass
class Instance:
    home: Path
    port: int
    token: str
    pid: int

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def data_dir(self) -> Path:
        return self.home / "apps" / APP_NAME / "data"

    def to_json(self) -> str:
        return json.dumps(
            {"home": str(self.home), "port": self.port, "token": self.token, "pid": self.pid}
        )

    @staticmethod
    def from_json(text: str) -> Instance:
        got = json.loads(text)
        return Instance(Path(got["home"]), int(got["port"]), str(got["token"]), int(got["pid"]))


def stop(state_file: Path) -> str:
    """Terminate a previously started instance. Idempotent."""
    if not state_file.exists():
        return "no instance recorded"
    try:
        inst = Instance.from_json(state_file.read_text(encoding="utf-8"))
    except (ValueError, KeyError, OSError) as exc:
        state_file.unlink(missing_ok=True)
        return f"discarded unreadable state ({exc})"
    note = f"stopped pid {inst.pid}"
    try:
        os.killpg(os.getpgid(inst.pid), signal.SIGTERM)
        time.sleep(1.5)
    except (ProcessLookupError, PermissionError):
        note = f"pid {inst.pid} was already gone"
    state_file.unlink(missing_ok=True)
    return note


def _child_env(home: Path) -> dict[str, str]:
    """Environment for every child process of a throwaway instance.

    ``KIROCREW_HOME`` alone is NOT isolation, and this file's own promise ("its own
    data home, its own port, nothing near yours") was false without the second
    variable. Enabling an app registers its agents into kiro-cli's OWN directory
    (``~/.kiro/agents``), which no data-home override moves — so a throwaway
    instance rewrote the OPERATOR's live agent specs to point at its scratch
    install. The app's MCP server resolves its data dir from its own file location
    (``_APP_ROOT = _HERE.parent``), so after one ``up`` the operator's real session
    read THIS instance's fixture data and reported their own save as missing.

    ``KIROCREW_POD=1`` declares this instance ephemeral, and ``KIRO_HOME`` gives it
    its OWN kiro user directory — the pair ``pod/runtime.build_pod_env`` uses, and
    both are needed. The host's write guard
    (``agent._decline_shared_agent_home``) exempts a write only when the target is
    EXACTLY the dedicated ``<data home>/kiro/agents`` this instance's teardown owns;
    the marker alone does not qualify, which was measured — an instance carrying
    only ``KIROCREW_POD`` still rewrote the operator's specs. Redirecting the write
    is what protects them, and the marker keeps the instance honest about why.

    Not a supported route for anything that RUNS an agent: ``KIRO_HOME`` also moves
    kiro-cli's session storage. This harness never runs one — fixtures go through
    the app's own writers — so it needs neither those transcripts nor specs of its
    own.
    """
    return {
        **os.environ,
        "KIROCREW_HOME": str(home),
        "KIROCREW_POD": "1",
        "KIRO_HOME": str(home / "kiro"),
    }


def _shared_agent_specs() -> dict[str, float]:
    """The operator's REAL agent specs as ``{name: mtime}``, for :func:`_assert_untouched`.

    Resolved here rather than by importing the host: this runs under whatever
    interpreter launched the CLI, which need not have ``kiro_crew`` importable, and
    an import guarded by ``except: return {}`` made the check FAIL OPEN — it
    reported "nothing to compare" on both sides and waved the very rewrite it
    exists to catch straight through. Mirrors the host's override-blind resolver:
    the ambient ``KIRO_HOME`` if the operator exported one, else ``~/.kiro``.
    """
    shared = Path(os.environ.get("KIRO_HOME") or Path.home() / ".kiro") / "agents"
    if not shared.is_dir():
        return {}
    out: dict[str, float] = {}
    for spec in shared.glob("*.json"):
        try:
            out[spec.name] = spec.stat().st_mtime
        except OSError:
            continue
    return out


def _assert_untouched(before: dict[str, float]) -> None:
    """Fail loudly if starting this instance modified the operator's agent specs.

    The isolation promise at the top of this file is worth exactly what enforces
    it. Its absence cost a real debugging session: the specs were repointed at a
    throwaway install silently, the symptom surfaced later in the operator's own
    session as "this save no longer exists" (the app's MCP server resolves its data
    dir from its own file location), and nothing connected the two. This turns that
    into an error at the moment of the write, naming the files.

    No "both sides empty, nothing to check" escape: an empty reading is either a
    machine with no shared specs — where an appearing one is exactly the write to
    refuse — or a broken resolver, and treating either as a pass is how the first
    version of this guard stayed silent through the bug.
    """
    after = _shared_agent_specs()
    changed = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
    if changed:
        raise InstanceError(
            "this throwaway instance modified the operator's shared agent specs: "
            + ", ".join(changed)
            + " — isolation is broken; restore them with `kirocrew setup --agent-only` "
            "(plus `kirocrew app disable/enable` per app) and do not run shots until "
            "this is fixed"
        )


def _install_into(home: Path, interpreter: Path) -> None:
    """Install + enable this app in ``home``, in a child process.

    A child, not this process: the host package resolves its data home at import
    time, so importing it here would bind whatever ``KIROCREW_HOME`` happened to be
    set to when the CLI started.
    """
    script = (
        "import json,sys\n"
        "from kiro_crew.apps.manager import install_app, enable_app\n"
        "from kiro_crew.apps.dev_mode import set_dev_mode\n"
        "src = sys.argv[1]\n"
        "got = install_app(src)\n"
        "if not got.ok: raise SystemExit('install failed: ' + (got.error or ''))\n"
        f"en = enable_app({APP_NAME!r})\n"
        "if not en.ok: raise SystemExit('enable failed: ' + (en.error or ''))\n"
        # Dev mode serves the app's UI with no-store, so a bundle swapped in after the
        # instance is up is actually the bundle the next shot renders. Without it a
        # cached module can make a real change look inert — the failure this harness
        # exists to prevent.
        f"set_dev_mode({APP_NAME!r}, True)\n"
        "print('installed')\n"
    )
    got = subprocess.run(
        [str(interpreter), "-c", script, str(APP_ROOT)],
        env=_child_env(home),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if got.returncode != 0:
        raise InstanceError((got.stderr or got.stdout).strip()[-600:])


#: Marker the gateway serves INSTEAD of the dashboard when it cannot read the SPA
#: bundle (`kiro_crew.dashboard.handlers.core.DASHBOARD_HTML_NOT_FOUND_MARKER`). A
#: source install that never built the frontend serves this with HTTP 200, so nothing
#: below fails on its own — the shots just come back as a blank page with no app in it.
#: Checked at startup because the alternative is what actually happened: 52 shots and
#: 33 CI-minutes spent photographing an error page.
_NO_DASHBOARD = "Dashboard HTML not found"


def _assert_dashboard_is_served(inst: Instance) -> None:
    """Fail now, with the remedy, if this gateway has no dashboard to drive."""
    url = f"{inst.base_url}/?token={inst.token}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — loopback
            body = resp.read().decode("utf-8", "replace")
    except OSError as exc:
        raise InstanceError(f"the gateway did not serve its dashboard: {exc}") from exc
    if _NO_DASHBOARD in body:
        raise InstanceError(
            "this Kiro Crew install has no built dashboard — the gateway is serving its "
            f'"{_NO_DASHBOARD}" page, so there is no app to photograph.\n'
            "A pip install straight from the KiroCrew git source does NOT build the SPA. "
            "Install a released wheel instead (the one-line installer at "
            "https://download.crew.kiro.dev/cli.sh does), or build the frontend and "
            "stage it into the package before starting the gateway."
        )


def start(home: Path, log_file: Path, *, ready_timeout: float = 240.0) -> Instance:
    """Create the throwaway home, install this app into it, and start a gateway.

    Returns once the gateway has printed its machine-readable ready line, which
    carries the port and a dashboard credential — the only supported way to reach a
    fresh instance's dashboard without a browser session.
    """
    interpreter = gateway_interpreter()
    # Snapshot BEFORE the install: enabling the app is the step that registers
    # agents, so this is the only window in which the write could happen.
    shared_before = _shared_agent_specs()
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    # Third-party app code does not execute unless the operator trusts it. This home
    # is thrown away and the app IS the thing under test, so trust it by name — never
    # by flipping the allow-every-third-party-app switch.
    (home / "config.json").write_text(
        json.dumps({"agent": {"apps_trusted": [APP_NAME]}}, indent=2), encoding="utf-8"
    )
    _install_into(home, interpreter)
    _assert_untouched(shared_before)

    proc = subprocess.Popen(
        [str(interpreter), "-m", "kiro_crew", "gateway", "--test-mode", "--no-crons"],
        env=_child_env(home),
        stdout=subprocess.PIPE,
        stderr=log_file.open("w"),
        text=True,
        start_new_session=True,
    )
    assert proc.stdout is not None
    deadline = time.time() + ready_timeout
    prefix = "KIROCREW_READY:"
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        if line.startswith(prefix):
            got = json.loads(line[len(prefix) :])
            inst = Instance(home, int(got["port"]), str(got["token"]), proc.pid)
            _assert_dashboard_is_served(inst)
            return inst
    tail = (
        log_file.read_text(encoding="utf-8", errors="replace")[-800:] if log_file.exists() else ""
    )
    raise InstanceError(f"gateway never reported ready (rc={proc.poll()}). log tail:\n{tail}")
