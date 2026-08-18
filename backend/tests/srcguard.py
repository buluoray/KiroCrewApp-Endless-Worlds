"""Helpers for guards that read source code.

Every guard in this suite that searches source text for a forbidden construct has
made the same mistake at least once: the comment explaining WHY the construct is
forbidden contains the construct, so the test goes red on the fixed code. It has now
happened six times, on six unrelated rules —

* a rule forbidding ``label_`` whose comment said ``label_``;
* a rule forbidding the field id ``"age"`` that matched the word "p*age*";
* a rule forbidding ``offset`` whose comment explained why offsets are wrong;
* and three earlier ones in the same family.

Six repeats of one mistake is not carelessness, it is a missing tool. So the fix
lives here instead of in each author's memory: strip the prose, then search the code.

Use ``code_only`` for anything that reads source as text. When the construct can be
expressed structurally instead — a comparison, a keyword argument, an attribute —
prefer ``ast``: it cannot be fooled by prose at all.
"""

from __future__ import annotations

import ast
import re


def code_only(src: str, *, lang: str = "py") -> str:
    """*src* with comments and docstrings removed.

    ``lang`` is ``"py"`` or ``"ts"``. TypeScript is handled with regexes rather than
    a parser because there is no TS parser here and the shapes that matter — ``//``
    to end of line, ``/* … */`` including JSX ``{/* … */}`` — are unambiguous enough
    for a guard. A string literal containing ``//`` would be over-stripped; no guard
    in this suite depends on one, and a guard that did should use ``ast`` on the
    backend side of the same rule instead.
    """
    if lang == "py":
        return _python_code_only(src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _python_code_only(src: str) -> str:
    """Python with ``#`` comments and every docstring dropped.

    Docstrings are removed via the parse tree rather than by matching triple quotes,
    because a docstring's own text can contain triple quotes and a regex cannot tell
    the difference.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # A fragment rather than a module — fall back to dropping comments only, and
        # say so by not pretending docstrings were handled.
        return re.sub(r"#[^\n]*", "", src)

    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
        ):
            spans.append((first.lineno, first.end_lineno))

    drop = {n for start, end in spans for n in range(start, end + 1)}
    kept = [
        re.sub(r"#[^\n]*", "", line)
        for i, line in enumerate(src.splitlines(), start=1)
        if i not in drop
    ]
    return "\n".join(kept)
