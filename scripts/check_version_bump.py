#!/usr/bin/env python3
"""Fail when a pull request changes shipped code without bumping app.json.

The app ships as a directory a registry install copies verbatim, and the version
in ``app.json`` is the only thing that tells an installed copy it is out of date:
the App Store compares it, the shelf footer prints it, and narrator slots are
recreated when it changes. So a change that alters what a player runs while
leaving the version alone installs as a no-op — the user syncs, sees the same
number, and reasonably concludes nothing arrived. That happened twice in one
evening (two merged pull requests changed backend behaviour at an unchanged
0.5.3), which is why this is a gate rather than a convention.

Scoped to the SHIPPED surface on purpose. A docs-only, test-only or CI-only pull
request changes nothing a player runs and must not be forced to invent a version:
a rule that fires on changes it should not is a rule people learn to bypass.

Usage:  check_version_bump.py [base-ref]        (default: origin/main)
"""

from __future__ import annotations

import json
import subprocess
import sys

#: A change under one of these reaches the player: backend behaviour, the agent
#: contracts, the world packs, the built UI bundle, or the manifest itself.
#: ``web/src`` is deliberately absent — it reaches a player only through the built
#: ``ui/index.mjs``, which is tracked and has its own CI step, so listing the
#: source as well would double-report one change.
SHIPPED = ("app.json", "agents/", "backend/", "seeds/", "ui/")

#: Tests live under a shipped directory but are not shipped behaviour: an
#: installed app never runs them.
NOT_SHIPPED = ("backend/tests/",)


def _git(*args: str) -> str:
    return subprocess.run(
        ("git",) + args, check=True, capture_output=True, text=True
    ).stdout.strip()


def changed_files(base: str) -> list[str]:
    """What this branch changes relative to its merge base with ``base``.

    Three dots, not two: a branch must not be asked to account for commits that
    landed on the base after it forked.
    """
    return [p for p in _git("diff", "--name-only", f"{base}...HEAD").splitlines() if p]


def shipped_changes(paths: list[str]) -> list[str]:
    return [p for p in paths if p.startswith(SHIPPED) and not p.startswith(NOT_SHIPPED)]


def version_at(ref: str) -> str:
    """``app.json``'s version at ``ref``, or "" when it cannot be read there."""
    try:
        raw = _git("show", f"{ref}:app.json")
    except subprocess.CalledProcessError:
        return ""
    try:
        return str(json.loads(raw).get("version") or "")
    except ValueError:
        return ""


def as_tuple(version: str) -> tuple[int, ...]:
    """A comparable form of a dotted version; unreadable parts sort as 0.

    Deliberately lenient about a suffix (``0.5.4-rc1`` reads as ``(0, 5, 4)``):
    the question here is only whether the number moved forward, and refusing to
    parse would turn a release-shaped version into a broken build.
    """
    parts: list[int] = []
    for chunk in version.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else "origin/main"
    shipped = shipped_changes(changed_files(base))
    if not shipped:
        print("version gate: no shipped file changed — no bump required")
        return 0

    before, after = version_at(base), version_at("HEAD")
    if not after:
        print("version gate: app.json declares no version on this branch", file=sys.stderr)
        return 1
    if as_tuple(after) > as_tuple(before):
        print(f"version gate: {before or '<none>'} -> {after}, and {len(shipped)} shipped file(s) changed")
        return 0

    listed = "\n  ".join(shipped[:10])
    more = f"\n  … and {len(shipped) - 10} more" if len(shipped) > 10 else ""
    print(
        f"version gate: app.json is still {after} but this branch changes files a "
        f"player runs:\n  {listed}{more}\n"
        f"Raise \"version\" in app.json (it was {before or '<none>'} on {base}). An "
        f"installed copy compares that number to decide it is out of date, so a "
        f"change shipped under an unchanged version arrives as a no-op.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
