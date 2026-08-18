"""Guards on the content layer, and on the call sites that reach it.

The expensive lesson behind this file: a ``language=`` keyword was added to the
``compose_opening_prompt`` call in ``routes.py`` while that function had no such
parameter. Every test passed — 474 of them — because **no test executes a route
handler**, so the ``TypeError`` was only reachable by playing the game. It shipped.

That is the same blind spot that produced two earlier live failures: a `NameError`
for a function used but never imported, and stale sibling modules after a hot
reload. The pattern is always "the suite proves the units and the route is the one
line nothing covers", so the guard has to read the call sites themselves.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import sys
from pathlib import Path

import halo
import opening
import turn
from content import FALLBACK, LANGUAGES, Content

BACKEND = Path(__file__).resolve().parents[1]
CONTENT = BACKEND.parent / "content"

#: The modules whose text a narrator reads. Comments and docstrings in ANY module
#: may quote world content — explaining why 【魔力】 is a bounded stat needs the
#: example — so the scan below is deliberately limited to string literals.
PROMPT_MODULES = ("turn.py", "opening.py", "halo.py", "content.py")


# ── the call sites nothing else executes ────────────────────────────────────


def _resolvable(module: ast.Module) -> dict[str, object]:
    """Names imported into ``routes.py`` from the app's own modules, mapped to the
    real objects — so a signature can be inspected rather than guessed."""
    found: dict[str, object] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        mod = sys.modules.get(node.module or "")
        if mod is None:
            continue
        for alias in node.names:
            target = getattr(mod, alias.name, None)
            if callable(target):
                found[alias.asname or alias.name] = target
    return found


def test_every_keyword_at_a_route_call_site_exists_in_the_callee():
    """The failure that shipped, made unshippable.

    Checked against the REAL signature via ``inspect``, not against a list written
    here: a list would need updating in the same edit that breaks the call, which is
    exactly the edit that forgets.
    """
    src = (BACKEND / "routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    known = _resolvable(tree)
    assert known, "no app callables resolved from routes.py — the guard is inert"

    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        target = known.get(node.func.id)
        if target is None:
            continue
        try:
            sig = inspect.signature(target)
        except (TypeError, ValueError):  # pragma: no cover - builtins
            continue
        if any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        ):
            continue  # **kwargs accepts anything
        for kw in node.keywords:
            if kw.arg is None:
                continue  # **spread — not statically checkable
            if kw.arg not in sig.parameters:
                problems.append(
                    f"line {node.lineno}: {node.func.id}(...) is passed "
                    f"{kw.arg}=, which it does not accept"
                )
    assert not problems, "\n".join(problems)


def test_the_opening_prompt_takes_its_language_from_the_world_not_the_caller():
    """Why the fix was to REMOVE the argument rather than add the parameter.

    The function already receives the ``template`` whose rulebook it is quoting. A
    separate language argument is a second source of truth for one fact, and the
    only thing it can add is disagreement.
    """
    sig = inspect.signature(opening.compose_opening_prompt)
    assert "language" not in sig.parameters, (
        "a language argument here can disagree with the template in the same call"
    )
    assert "template" in sig.parameters


# ── no language baked into the code ─────────────────────────────────────────


def _string_literals(path: Path) -> list[tuple[int, str]]:
    """Every string literal, with its line — docstrings and comments excluded.

    Uses ``ast`` rather than a regex over the file because the docstrings in these
    modules explain the rules by quoting the content, and a whole-file substring
    match would flag the explanation of a rule as a violation of it. That mistake
    has already cost three rounds in this codebase.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            out.append((node.lineno, node.value))
    return out


#: Ideographs, CJK punctuation (、。：「」), and fullwidth forms. The punctuation
#: matters as much as the characters: a hardcoded ``、`` joined an English world's
#: field list with a Chinese comma, which no ideograph scan would have caught.
CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")


def test_no_prompt_module_carries_language_in_a_string_literal():
    """Player- and narrator-facing text is CONTENT and lives in a language-keyed
    table. Code only looks it up."""
    problems: list[str] = []
    for name in PROMPT_MODULES:
        for line, value in _string_literals(BACKEND / name):
            if CJK.search(value):
                problems.append(f"{name}:{line}: {value[:60]!r}")
    assert not problems, (
        "language belongs in content/*.json, not in code:\n" + "\n".join(problems)
    )


def test_the_scan_would_catch_a_bare_separator():
    """Proof the scan above is not inert — the punctuation case specifically, since
    that is the one an ideograph-only pattern misses."""
    assert CJK.search("、")
    assert CJK.search("；")
    assert CJK.search("（")
    assert not CJK.search("plain ascii, semicolons; and commas")


# ── the tables themselves ───────────────────────────────────────────────────


def test_both_tables_carry_the_same_keys():
    tables = {
        lang: json.loads((CONTENT / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in LANGUAGES
    }
    keys = [set(t) for t in tables.values()]
    assert keys[0] == keys[1], f"tables disagree: {keys[0] ^ keys[1]}"


def test_a_placeholder_missing_from_one_table_is_a_failure():
    """A key whose ``{name}`` slots differ between languages renders a prompt with a
    hole in one of them — and only for the players who read that one."""
    tables = {
        lang: json.loads((CONTENT / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in LANGUAGES
    }
    slots = {
        lang: {k: set(re.findall(r"\{(\w+)\}", v)) for k, v in t.items()}
        for lang, t in tables.items()
    }
    first, second = LANGUAGES[0], LANGUAGES[1]
    for key in slots[first]:
        assert slots[first][key] == slots[second].get(key), (
            f"{key} takes {slots[first][key]} in {first} but "
            f"{slots[second].get(key)} in {second}"
        )


def test_an_unknown_language_falls_back_instead_of_failing():
    """A world is not broken for being written in a language nobody has translated
    the app into yet."""
    assert Content("kling")("turn.rulebook") == Content(FALLBACK)("turn.rulebook")


def test_a_missing_key_returns_the_key():
    """Visible, rather than a silent gap. A prompt containing ``turn.nope`` is
    obviously broken; a prompt with an empty line where an instruction should be
    reads as a complete prompt that never asked for anything."""
    assert Content(FALLBACK)("turn.nope") == "turn.nope"


def test_the_separators_are_content_too():
    """The bug this closes: an English world's field list joined with ``、``."""
    assert Content("en")("list.join") != Content("zh")("list.join")
    for lang in LANGUAGES:
        assert Content(lang)("list.join").strip() != "", "a joiner cannot be empty"


def test_every_key_the_prompt_modules_ask_for_exists():
    """A lookup for a key nobody added renders as the key name — in a prompt, which
    is the one place nobody is reading closely."""
    table = json.loads((CONTENT / f"{FALLBACK}.json").read_text(encoding="utf-8"))
    asked: set[str] = set()
    for name in PROMPT_MODULES:
        src = (BACKEND / name).read_text(encoding="utf-8")
        asked |= set(re.findall(r"text\(\s*[\"']([\w.]+)[\"']", src))
        asked |= set(re.findall(r"Content\([^)]*\)\(\s*[\"']([\w.]+)[\"']", src))
    assert asked, "no lookups found — the guard is inert"
    missing = sorted(k for k in asked if k not in table)
    assert not missing, f"asked for but never defined: {missing}"


def test_the_three_prompt_builders_all_read_the_table():
    """Each of the three has to be wired, not two of them. ``opening.py`` was the
    one left hardcoded while the other two were converted, and nothing noticed."""
    for module in (turn, opening, halo):
        src = inspect.getsource(module)
        assert "Content(" in src, f"{module.__name__} never consults the table"
