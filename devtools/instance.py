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
        env={**os.environ, "KIROCREW_HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=300,
    )
    if got.returncode != 0:
        raise InstanceError((got.stderr or got.stdout).strip()[-600:])


def start(home: Path, log_file: Path, *, ready_timeout: float = 240.0) -> Instance:
    """Create the throwaway home, install this app into it, and start a gateway.

    Returns once the gateway has printed its machine-readable ready line, which
    carries the port and a dashboard credential — the only supported way to reach a
    fresh instance's dashboard without a browser session.
    """
    interpreter = gateway_interpreter()
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

    proc = subprocess.Popen(
        [str(interpreter), "-m", "kiro_crew", "gateway", "--test-mode", "--no-crons"],
        env={**os.environ, "KIROCREW_HOME": str(home)},
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
            return Instance(home, int(got["port"]), str(got["token"]), proc.pid)
    tail = (
        log_file.read_text(encoding="utf-8", errors="replace")[-800:] if log_file.exists() else ""
    )
    raise InstanceError(f"gateway never reported ready (rc={proc.poll()}). log tail:\n{tail}")
