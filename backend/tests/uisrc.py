"""The UI source, for the guard tests that read it.

These tests scan source rather than exercise a DOM because the app has no JS test
runner. That is a real limitation, and it moved with the build: they used to read
the hand-written ``ui/index.mjs``, which is now a Vite ARTIFACT. Scanning an
artifact would check compiler output — double-quoted attributes, `jsx(...)` calls,
inlined strings — instead of the code a person edits, so a rule could be quietly
lost in the source while the test kept passing on the bundle.
"""

from __future__ import annotations

from pathlib import Path

WEB_SRC = Path(__file__).resolve().parents[2] / "web" / "src"

#: Where the built module lands. Present so a test can assert something about the
#: ARTIFACT (externals, a default export) rather than about the source.
BUILT = Path(__file__).resolve().parents[2] / "ui" / "index.mjs"


def source() -> str:
    """Every TypeScript source file, concatenated. Order is stable (sorted) so a
    failure message points at the same place twice."""
    parts = [
        p.read_text(encoding="utf-8")
        for p in sorted(WEB_SRC.rglob("*"))
        if p.suffix in (".ts", ".tsx")
    ]
    return "\n".join(parts)


def styles() -> str:
    return (WEB_SRC / "styles.css").read_text(encoding="utf-8")


def module(name: str) -> str:
    """One source file by name, e.g. ``scene.tsx`` — for a test that wants to be
    sure a rule lives in the component it is about."""
    return (WEB_SRC / name).read_text(encoding="utf-8")
