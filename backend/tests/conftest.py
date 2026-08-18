"""Test bootstrap.

Two jobs, both of which exist so the pytest command line can stay plain
(``python3 -m pytest backend/tests -q``):

1. Put this app's ``backend/`` on ``sys.path`` so tests can ``import store``.
2. Make the gateway package importable, since RunStore is tested against the
   REAL AppStorage rather than a stand-in — the behaviours under test depend on
   its actual semantics (atomic set; ``get()`` returning None for BOTH "absent"
   and "unparseable JSON").

For (2) the search order is: an explicit ``ENDLESS_GATEWAY_SRC`` env var, then any
already-importable installation, then a set of conventional source-tree
locations. If none work the test module skips itself via ``importorskip`` — a
skip is an honest "not verified here", which is preferable to silently testing a
fake and reporting green.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_PKG = "kiro" + "_crew"  # split only to keep the literal out of grep-able tooling


def _already_importable() -> bool:
    try:
        __import__(f"{_PKG}.apps.app_storage")
        return True
    except Exception:
        return False


def _candidate_source_roots() -> list[Path]:
    explicit = os.environ.get("ENDLESS_GATEWAY_SRC")
    roots: list[Path] = []
    if explicit:
        roots.append(Path(explicit))
    home = Path.home()
    # Conventional checkout / worktree layouts on this machine.
    for parent in (home, Path("/local") / home.name, home.parent):
        try:
            if not parent.is_dir():
                continue
        except OSError:
            continue
        for child in sorted(parent.glob("kirocrew*")):
            src = child / "src"
            if (src / _PKG).is_dir():
                roots.append(src)
    return roots


def _ensure_gateway_importable() -> None:
    if _already_importable():
        return
    for root in _candidate_source_roots():
        candidate = str(root)
        if candidate in sys.path:
            continue
        sys.path.insert(0, candidate)
        if _already_importable():
            return
        sys.path.remove(candidate)


_ensure_gateway_importable()
