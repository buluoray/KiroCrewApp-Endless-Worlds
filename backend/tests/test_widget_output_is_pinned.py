"""The forcing function behind ``widget.COMPILER``.

A compiled scene is cached on disk under the key (COMPILER, spec, bound state,
nonce). A mounted scene's spec, state and nonce do not change on their own, so for
every scene a player already has open, COMPILER is the ONLY part of that key a fix
can move — and a fix that does not move it is never served. The bug that earned this
test: the compiler learned to render a ``keyvalue`` block's ``pairs`` rows, the
number stayed at 1, and every already-mounted 物资账本 went on serving the blank
version it had been compiled into. Nothing was red; the fix simply never ran.

So the compiled bytes are pinned here. Change what the compiler emits and this test
fails, telling you to bump COMPILER and re-pin — which is the whole point: the
failure is the reminder that existing scenes need to recompile.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import widget  # noqa: E402

#: Exercises every element kind whose markup a cache would otherwise freeze.
CANON_SPEC = {
    "title": "锁定用场景",
    "elements": [
        {"kind": "heading", "text": "食物"},
        {
            "kind": "keyvalue",
            "pairs": [
                {"key": "存货", "value": "两周"},
                {"key": "结论", "value": "省着用"},
            ],
        },
        {"kind": "keyvalue", "label": "饮水", "value": "三天"},
        {"kind": "divider"},
        {"kind": "note", "text": "一条提示"},
        {
            "kind": "grid",
            "columns": 2,
            "cells": [
                {"label": "旧楼", "note": "封死", "mark": "⚠"},
                {"label": "邻楼", "note": "有人"},
            ],
        },
        {
            "kind": "table",
            "columns": ["名称", "数量"],
            "rows": [["罐头", "12"], ["纱布", "3"]],
        },
        {"kind": "gauge", "label": "体力", "value": 42, "max": 100},
    ],
}

#: The pinned pair. Both halves move together, deliberately: re-pinning the digest
#: without bumping the compiler leaves every mounted scene on the old bytes, and
#: bumping the compiler without re-pinning means the output was not actually checked.
PINNED_COMPILER = 2
PINNED_SHA256 = "5da7f6c0200e70db8a13c7ae9c9382779cd13d14adaf0de6d0c63e9d5bcc16cf"


def _compiled() -> str:
    return widget.compile_scene("canon", CANON_SPEC, {}, nonce="0" * 16)


def test_compiled_output_is_pinned_to_the_compiler_version() -> None:
    got = hashlib.sha256(_compiled().encode("utf-8")).hexdigest()
    assert widget.COMPILER == PINNED_COMPILER, (
        f"widget.COMPILER is {widget.COMPILER}, pinned at {PINNED_COMPILER}. If the "
        "compiler's output changed, update BOTH: the number (so mounted scenes "
        "recompile) and PINNED_SHA256 (so the next change is caught too)."
    )
    assert got == PINNED_SHA256, (
        "the compiled bytes changed, so every scene a player already has mounted is "
        f"still being served the old ones. Bump widget.COMPILER to "
        f"{widget.COMPILER + 1} and re-pin PINNED_SHA256 to {got}."
    )


def test_the_compiler_version_is_part_of_the_cache_key() -> None:
    """Without this the pin above guards nothing: the digest could be stable across
    a compiler bump, and a mounted scene would keep its cached file anyway."""
    before = widget.spec_digest(CANON_SPEC, None)
    original = widget.COMPILER
    try:
        widget.COMPILER = original + 1
        after = widget.spec_digest(CANON_SPEC, None)
    finally:
        widget.COMPILER = original
    assert before != after, "bumping COMPILER does not invalidate a cached scene"


def test_a_pairs_ledger_renders_one_row_per_pair() -> None:
    """The fix the version bump exists to deliver, pinned on its own so a later
    refactor cannot quietly return to one blank row per element."""
    html = _compiled()
    assert '<div class="k">存货</div><div class="v">两周</div>' in html
    assert '<div class="k">结论</div><div class="v">省着用</div>' in html
    assert '<div class="k"></div>' not in html, "a pair rendered as an empty row"
