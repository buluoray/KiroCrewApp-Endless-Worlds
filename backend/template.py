"""Template loading: header + verbatim prose, and the ``when`` interpreter.

A template is one file — YAML front matter, then the rulebook. The prose is
stored and handed to the narrator **byte for byte**; nothing here parses it. The
header declares only what the app itself must render or enforce (design §4.1).

``when`` expressions gate conditional panels and endings. They are evaluated by
the small explicit interpreter below rather than by ``eval`` — a template is
untrusted content, and a condition is never a place to execute code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Iterator

import yaml

#: Primitives a panel field may name (design §7.1). ``panelGroup`` is the
#: container itself and is therefore not a field primitive.
FIELD_PRIMITIVES = frozenset(
    {"field", "stat", "rank", "people", "trend", "resource", "inventory", "threads"}
)

OPENING_KINDS = frozenset({"pick", "text", "number"})

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)


class TemplateError(ValueError):
    """A template could not be used. Names the field and what was expected.

    R14.3 requires the Library to show *which* field was wrong, so the message
    is the product surface here, not just a log line.
    """

    def __init__(self, field: str, expected: str) -> None:
        super().__init__(f"{field}: {expected}")
        self.field = field
        self.expected = expected


# ---------------------------------------------------------------------------
# when interpreter
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<op>==|!=|>=|<=|>|<)
  | (?P<lparen>\()
  | (?P<rparen>\))
  | (?P<str>'[^']*'|"[^"]*")
  | (?P<num>-?\d+(?:\.\d+)?)
  | (?P<word>[A-Za-z_][A-Za-z0-9_.]*)
    """,
    re.VERBOSE,
)

_KEYWORDS = {"and", "or", "not", "true", "false", "null"}

#: Parenthesis / ``not`` nesting cap. A template is untrusted content, so a
#: pathological expression must fail as a TemplateError the Library can show —
#: never as a RecursionError escaping into the turn loop. 32 is far past any
#: legible condition and far below Python's own recursion limit.
_MAX_DEPTH = 32


@dataclass(frozen=True)
class _Tok:
    kind: str
    text: str


def _tokenize(src: str) -> list[_Tok]:
    out: list[_Tok] = []
    pos = 0
    while pos < len(src):
        m = _TOKEN_RE.match(src, pos)
        if m is None:
            raise TemplateError("when", f"unexpected character at offset {pos}: {src[pos]!r}")
        pos = m.end()
        kind = m.lastgroup or ""
        if kind == "ws":
            continue
        text = m.group()
        if kind == "word" and text in _KEYWORDS:
            kind = text
        out.append(_Tok(kind, text))
    return out


class Condition:
    """A parsed ``when`` expression. Immutable and reusable across turns."""

    def __init__(self, source: str, node: "_Node") -> None:
        self.source = source
        self._node = node

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Condition({self.source!r})"

    def evaluate(self, state: dict[str, Any]) -> bool:
        """Evaluate against *state*.

        A path that does not exist yields ``None`` rather than raising: a panel
        whose trigger references state the run has not reached yet must simply
        stay hidden, not break the turn.
        """
        return bool(self._node.eval({"state": state}))

    def referenced_paths(self) -> list[str]:
        """Every dotted path this expression reads, for diagnostics.

        A compiled header's state paths are invented by the compiler, so the
        backend cannot verify they will ever exist. What it CAN do is surface the
        whole set, which is how a typo like `state.magik.awake` alongside
        `state.magic.awakened` becomes visible instead of silently hiding a panel
        forever.
        """
        found: list[str] = []
        _collect_paths(self._node, found)
        return sorted(set(found))

    @staticmethod
    def parse(source: str) -> "Condition":
        if not isinstance(source, str) or not source.strip():
            raise TemplateError("when", "expected a non-empty expression string")
        toks = _tokenize(source)
        if not toks:
            raise TemplateError("when", "expected a non-empty expression string")
        parser = _Parser(toks, source)
        node = parser.parse_or()
        parser.expect_end()
        return Condition(source, node)


class _Node:
    def eval(self, env: dict[str, Any]) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError


def _collect_paths(node: "_Node", out: list[str]) -> None:
    """Walk the tree gathering dotted paths. Kept next to the node types so a new
    node kind cannot be added without this being obviously incomplete."""
    if isinstance(node, _Path):
        out.append(".".join(node.parts))
    elif isinstance(node, _Not):
        _collect_paths(node.inner, out)
    elif isinstance(node, (_BoolOp, _Compare)):
        _collect_paths(node.left, out)
        _collect_paths(node.right, out)


@dataclass
class _Lit(_Node):
    value: Any

    def eval(self, env: dict[str, Any]) -> Any:
        return self.value


@dataclass
class _Path(_Node):
    parts: tuple[str, ...]

    def eval(self, env: dict[str, Any]) -> Any:
        cur: Any = env
        for part in self.parts:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur


@dataclass
class _Not(_Node):
    inner: _Node

    def eval(self, env: dict[str, Any]) -> Any:
        return not self.inner.eval(env)


@dataclass
class _BoolOp(_Node):
    op: str
    left: _Node
    right: _Node

    def eval(self, env: dict[str, Any]) -> Any:
        if self.op == "and":
            return bool(self.left.eval(env)) and bool(self.right.eval(env))
        return bool(self.left.eval(env)) or bool(self.right.eval(env))


@dataclass
class _Compare(_Node):
    op: str
    left: _Node
    right: _Node

    def eval(self, env: dict[str, Any]) -> Any:
        a = self.left.eval(env)
        b = self.right.eval(env)
        if self.op == "==":
            return a == b
        if self.op == "!=":
            return a != b
        # Ordering against a missing path is false rather than a TypeError:
        # "renown > 50" on a run with no renown yet is simply not satisfied.
        if a is None or b is None:
            return False
        try:
            if self.op == ">":
                return a > b
            if self.op == ">=":
                return a >= b
            if self.op == "<":
                return a < b
            return a <= b
        except TypeError:
            return False


class _Parser:
    def __init__(self, toks: list[_Tok], source: str) -> None:
        self._toks = toks
        self._i = 0
        self._src = source
        self._depth = 0

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > _MAX_DEPTH:
            raise TemplateError(
                "when", f"nested more than {_MAX_DEPTH} levels deep in {self._src!r}"
            )

    def _leave(self) -> None:
        self._depth -= 1

    def _peek(self) -> _Tok | None:
        return self._toks[self._i] if self._i < len(self._toks) else None

    def _take(self) -> _Tok:
        tok = self._peek()
        if tok is None:
            raise TemplateError("when", f"unexpected end of expression in {self._src!r}")
        self._i += 1
        return tok

    def expect_end(self) -> None:
        tok = self._peek()
        if tok is not None:
            raise TemplateError("when", f"unexpected trailing {tok.text!r} in {self._src!r}")

    def parse_or(self) -> _Node:
        node = self.parse_and()
        while (tok := self._peek()) and tok.kind == "or":
            self._take()
            node = _BoolOp("or", node, self.parse_and())
        return node

    def parse_and(self) -> _Node:
        node = self.parse_not()
        while (tok := self._peek()) and tok.kind == "and":
            self._take()
            node = _BoolOp("and", node, self.parse_not())
        return node

    def parse_not(self) -> _Node:
        if (tok := self._peek()) and tok.kind == "not":
            self._take()
            self._enter()
            try:
                return _Not(self.parse_not())
            finally:
                self._leave()
        return self.parse_compare()

    def parse_compare(self) -> _Node:
        left = self.parse_atom()
        if (tok := self._peek()) and tok.kind == "op":
            self._take()
            return _Compare(tok.text, left, self.parse_atom())
        return left

    def parse_atom(self) -> _Node:
        tok = self._take()
        if tok.kind == "lparen":
            self._enter()
            try:
                node = self.parse_or()
            finally:
                self._leave()
            closing = self._peek()
            if closing is None or closing.kind != "rparen":
                raise TemplateError("when", f"unclosed '(' in {self._src!r}")
            self._take()
            return node
        if tok.kind == "str":
            return _Lit(tok.text[1:-1])
        if tok.kind == "num":
            text = tok.text
            return _Lit(float(text) if "." in text else int(text))
        if tok.kind == "true":
            return _Lit(True)
        if tok.kind == "false":
            return _Lit(False)
        if tok.kind == "null":
            return _Lit(None)
        if tok.kind == "word":
            parts = tuple(p for p in tok.text.split(".") if p)
            if not parts:
                raise TemplateError("when", f"empty path in {self._src!r}")
            return _Path(parts)
        raise TemplateError("when", f"unexpected {tok.text!r} in {self._src!r}")


# ---------------------------------------------------------------------------
# template
# ---------------------------------------------------------------------------


@dataclass
class PanelField:
    id: str
    label: str
    primitive: str
    options: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class Panel:
    id: str
    fields: list[PanelField]
    always: bool = False
    when: Condition | None = None

    def visible(self, state: dict[str, Any]) -> bool:
        if self.always or self.when is None:
            return True
        return self.when.evaluate(state)


@dataclass
class OpeningGroup:
    id: str
    label: str
    kind: str
    options: list[str] = dc_field(default_factory=list)
    custom: bool = False
    random: bool = False


@dataclass
class Style:
    id: str
    label: str
    default: bool = False


@dataclass
class Ending:
    id: str
    when: Condition


@dataclass
class Chapter:
    """One section of a world's rulebook, and when the narrator may see it.

    A 15,000-character rulebook is not uniformly relevant. Most of it describes
    institutions a given life never touches — the academy's grading system matters to
    a student and to nobody else — so sending all of it on turn one buys context the
    life will never use and, worse, hands the narrator material it may start reaching
    for because it is there.

    The split is DECLARED, not detected. This world marks its chapters with
    ``第N章 · …`` and another might use ``Chapter N`` or nothing recognisable at all;
    a regex here would be the first world-specific line in the app, which is the one
    thing the primitives exist to avoid. So the world names its own headings, in its
    own words, and the app finds them verbatim.

    Three kinds, and the difference is what a request for the body is answered with:

    * ``always`` — part of the opening brief. Sent without being asked for.
    * ``when`` set — the world's law about relevance. Readable only while the
      condition holds; asking earlier is refused, which is what makes disclosure real
      rather than a suggestion.
    * neither — always readable, never volunteered. Reference the narrator can reach
      for when it decides the month needs it.
    """

    id: str
    heading: str
    always: bool = False
    when: Condition | None = None

    def available(self, state: dict[str, Any]) -> bool:
        """Whether the narrator may read this chapter's body right now."""
        if self.always or self.when is None:
            return True
        return self.when.evaluate(state)


@dataclass
class Template:
    id: str
    title: str
    version: str
    language: str
    clock_unit: str
    clock_label: str
    lineage: bool
    styles: list[Style]
    opening: list[OpeningGroup]
    panels: list[Panel]
    endings: list[Ending]
    digest_categories: list[str]
    digest_rumours: bool
    save_schema: list[str]
    prose: str
    #: Declared chapters, in the order the world lists them. Empty means the world
    #: has not been split — the whole prose is one always-disclosed body, which is
    #: exactly how every pack behaved before chapters existed.
    chapters: list[Chapter] = dc_field(default_factory=list)
    source_path: str | None = None

    @property
    def default_style(self) -> Style:
        for style in self.styles:
            if style.default:
                return style
        return self.styles[0]

    def panels_for(self, state: dict[str, Any]) -> Iterator[Panel]:
        for panel in self.panels:
            if panel.visible(state):
                yield panel


def _parse_chapters(raw: Any, prose: str) -> list["Chapter"]:
    """Declared chapters, checked against the prose they claim to name.

    A heading that does not appear in the body is refused at read time rather than
    at disclosure time. The alternative is a pack that loads, plays, and then hands
    the narrator an empty chapter twelve months in — a failure that looks like the
    world having nothing to say about its own academy.

    Absent or empty is not an error: a world that has not been split is one chapter,
    which is how every pack behaved before this existed.
    """
    if raw in (None, [], {}):
        return []
    if not isinstance(raw, list):
        raise TemplateError("chapters", "a list of chapter declarations")

    out: list[Chapter] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise TemplateError(f"chapters[{i}]", "an object with an id and a heading")
        cid = str(_require(item, "id", str, f"chapter {i}")).strip()
        heading = str(_require(item, "heading", str, f"chapter {cid}")).strip()
        if not cid or not heading:
            raise TemplateError(f"chapters[{i}]", "a non-empty id and heading")
        if cid in seen:
            raise TemplateError(f"chapters[{cid}]", "an id no other chapter uses")
        seen.add(cid)
        if heading not in prose:
            raise TemplateError(
                f"chapters[{cid}].heading",
                f"a heading present in this world's prose ({heading!r} is not)",
            )
        when_src = item.get("when")
        out.append(
            Chapter(
                id=cid,
                heading=heading,
                always=bool(item.get("always", False)),
                when=Condition.parse(str(when_src)) if when_src else None,
            )
        )
    return out


def _require(mapping: Any, key: str, kind: type | tuple[type, ...], what: str) -> Any:
    if not isinstance(mapping, dict):
        raise TemplateError(key, "expected the enclosing value to be a mapping")
    if key not in mapping:
        raise TemplateError(key, f"required, {what}")
    value = mapping[key]
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise TemplateError(key, what)
    return value


def _require_id(mapping: Any, where: str) -> str:
    value = _require(mapping, "id", str, "a lowercase slug (a-z, 0-9, hyphen)")
    if not _ID_RE.match(value):
        raise TemplateError(f"{where}.id", f"a lowercase slug (a-z, 0-9, hyphen), got {value!r}")
    return value


def _parse_styles(raw: Any) -> list[Style]:
    if not isinstance(raw, list) or not raw:
        raise TemplateError("styles", "a non-empty list of simulation styles")
    styles: list[Style] = []
    defaults = 0
    for i, item in enumerate(raw):
        sid = _require_id(item, f"styles[{i}]")
        label = _require(item, "label", str, "a display label")
        is_default = bool(item.get("default", False))
        defaults += 1 if is_default else 0
        styles.append(Style(sid, label, is_default))
    if defaults > 1:
        raise TemplateError("styles", "at most one style may set default: true")
    return styles


def _parse_opening(raw: Any) -> list[OpeningGroup]:
    if not isinstance(raw, list) or not raw:
        raise TemplateError("opening", "a non-empty list of opening groups")
    groups: list[OpeningGroup] = []
    for i, item in enumerate(raw):
        gid = _require_id(item, f"opening[{i}]")
        label = _require(item, "label", str, "a display label")
        kind = _require(item, "kind", str, f"one of {sorted(OPENING_KINDS)}")
        if kind not in OPENING_KINDS:
            raise TemplateError(f"opening[{i}].kind", f"one of {sorted(OPENING_KINDS)}, got {kind!r}")
        options = item.get("options", [])
        if kind == "pick":
            if not isinstance(options, list) or not options:
                raise TemplateError(f"opening[{i}].options", "a non-empty list, required for kind: pick")
            if not all(isinstance(o, str) for o in options):
                raise TemplateError(f"opening[{i}].options", "a list of strings")
        groups.append(
            OpeningGroup(
                gid,
                label,
                kind,
                list(options) if isinstance(options, list) else [],
                bool(item.get("custom", False)),
                bool(item.get("random", False)),
            )
        )
    return groups


def _parse_panels(raw: Any) -> list[Panel]:
    if not isinstance(raw, list) or not raw:
        raise TemplateError("panels", "a non-empty list of panels")
    panels: list[Panel] = []
    always_count = 0
    for i, item in enumerate(raw):
        pid = _require_id(item, f"panels[{i}]")
        raw_fields = _require(item, "fields", list, "a non-empty list of fields")
        if not raw_fields:
            raise TemplateError(f"panels[{i}].fields", "a non-empty list of fields")
        fields: list[PanelField] = []
        for j, rf in enumerate(raw_fields):
            fid = _require_id(rf, f"panels[{i}].fields[{j}]")
            flabel = _require(rf, "label", str, "a display label")
            prim = _require(rf, "primitive", str, f"one of {sorted(FIELD_PRIMITIVES)}")
            if prim not in FIELD_PRIMITIVES:
                raise TemplateError(
                    f"panels[{i}].fields[{j}].primitive",
                    f"one of {sorted(FIELD_PRIMITIVES)}, got {prim!r}",
                )
            extras = {k: v for k, v in rf.items() if k not in ("id", "label", "primitive")}
            fields.append(PanelField(fid, flabel, prim, extras))
        always = bool(item.get("always", False))
        when_src = item.get("when")
        if always and when_src:
            raise TemplateError(f"panels[{i}]", "a panel may set always OR when, not both")
        if not always and not when_src:
            raise TemplateError(f"panels[{i}]", "needs always: true or a when expression")
        always_count += 1 if always else 0
        panels.append(
            Panel(pid, fields, always, Condition.parse(when_src) if when_src else None)
        )
    if always_count == 0:
        raise TemplateError("panels", "exactly one panel must set always: true")
    if always_count > 1:
        raise TemplateError("panels", "only one panel may set always: true")
    return panels


def _parse_endings(raw: Any) -> list[Ending]:
    if not isinstance(raw, list) or not raw:
        raise TemplateError("endings", "a non-empty list of ending conditions")
    endings: list[Ending] = []
    for i, item in enumerate(raw):
        eid = _require_id(item, f"endings[{i}]")
        when_src = _require(item, "when", str, "a when expression")
        endings.append(Ending(eid, Condition.parse(when_src)))
    return endings


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split a template file into (header mapping, verbatim prose).

    The prose is everything after the closing ``---``, returned unchanged — no
    stripping, no normalisation. R14.1 requires it to reach the narrator exactly
    as the author wrote it.
    """
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        raise TemplateError("front matter", "a YAML block delimited by --- at the very start")
    try:
        header = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise TemplateError("front matter", f"valid YAML ({exc.__class__.__name__})") from None
    if not isinstance(header, dict):
        raise TemplateError("front matter", "a mapping of fields")
    return header, text[match.end():]


def _require_version(header: Any) -> str:
    """Versions must be QUOTED strings, and this refuses to guess.

    PyYAML implements YAML 1.1, whose implicit typing silently corrupts version
    numbers: ``version: 1.10`` parses as the float ``1.1``, which is a DIFFERENT
    version and is now indistinguishable from ``1.1``. Since R14.7's migration
    check compares versions exactly, accepting a number here and ``str()``-ing it
    would launder a data-loss bug into a plausible-looking string.

    The same family of traps is why an agent-compiled header must be emitted as
    JSON: ``yes``/``off`` become booleans, ``1:30`` becomes ``90``, and
    ``language: no`` (Norwegian) becomes ``False``.
    """
    if not isinstance(header, dict) or "version" not in header:
        raise TemplateError("version", 'required, a quoted version string like "1.0"')
    value = header["version"]
    if isinstance(value, str):
        return value
    raise TemplateError(
        "version",
        f"a QUOTED string, got {type(value).__name__} {value!r} — unquoted YAML "
        f'reads 1.10 as the number 1.1, losing a version, so write "{value}"',
    )


def parse_template(text: str, *, source_path: str | None = None) -> Template:
    header, prose = split_front_matter(text)

    tid = _require_id(header, "template")
    clock = _require(header, "clock", dict, "a mapping with a unit and a label")
    clock_unit = _require(clock, "unit", str, "the clock's unit, e.g. month")

    return Template(
        id=tid,
        title=_require(header, "title", str, "the world's display title"),
        version=_require_version(header),
        language=_require(header, "language", str, "a language tag, e.g. zh or en"),
        clock_unit=clock_unit,
        clock_label=str(clock.get("label") or f"{{{clock_unit}}}"),
        lineage=bool(header.get("lineage", False)),
        styles=_parse_styles(header.get("styles")),
        opening=_parse_opening(header.get("opening")),
        panels=_parse_panels(header.get("panels")),
        endings=_parse_endings(header.get("endings")),
        digest_categories=list((header.get("digest") or {}).get("categories") or []),
        digest_rumours=bool((header.get("digest") or {}).get("rumours", False)),
        save_schema=list(header.get("save") or []),
        prose=prose,
        chapters=_parse_chapters(header.get("chapters"), prose),
        source_path=source_path,
    )
