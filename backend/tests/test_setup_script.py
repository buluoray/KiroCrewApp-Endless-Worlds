"""The optional-dependency install script is wired and can never fail the install."""

from __future__ import annotations

import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_app_json_declares_the_best_effort_install_script():
    app = json.loads((_ROOT / "app.json").read_text(encoding="utf-8"))
    assert app["setup"]["onInstall"] == "bash setup.sh"


def test_setup_script_cannot_fail_the_install():
    """setup.sh installs OPTIONAL art deps; a failure must never block the app
    install. It overrides the caller's `set -e` and always exits 0."""
    sh = (_ROOT / "setup.sh").read_text(encoding="utf-8")
    assert "set +e" in sh, "must override the runner's set -e"
    assert sh.rstrip().endswith("exit 0"), "must always exit 0"
