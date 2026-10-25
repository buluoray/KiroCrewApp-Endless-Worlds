"""Element patches against a stored backdrop draft.

A revision used to be a whole new SVG pair: the illustrator re-typed every byte of
two documents to change a few of them, and typing is where the page's wait goes
(~200 bytes/s). This module lets it name the elements it wants to change instead.

* :func:`annotate` gives the draft's elements stable ids, carried in the stored
  draft source as ``data-eid`` attributes. They are stripped (:func:`strip_eids`)
  before anything is rendered, validated or published, so the art that ships is
  the bytes the illustrator wrote.
* :func:`outline` is the compact map the illustrator gets back: one line per
  element with its id, tag and a few key attributes, never the markup.
* :func:`apply_ops` applies ``replace`` / ``insert_after`` / ``insert_before`` /
  ``remove`` / ``set_attrs`` to the annotated source, all or nothing.

This module only splices text. It is NOT a safety gate: the caller runs the full
``compile_backdrop`` sanitizer on the merged result, exactly as it does for a
first draft, so a patch can never carry what a whole draft could not.
"""

from __future__ import annotations

import re
import xml.parsers.expat
from dataclasses import dataclass, field
from typing import Any

from backdrop import BackdropError

EID_ATTR = "data-eid"

#: The illustrator's three SVGs and the one-letter prefix that says which one an
#: element id belongs to, so an op never needs to name the document separately.
PREFIXES = {"markup": "d", "mobile": "m", "buttons": "b"}

_EID_STRIP_RE = re.compile(r"""\s+data-eid\s*=\s*(?:"[^"]*"|'[^']*')""")
_EID_VALUE_RE = re.compile(r"^[dmb][0-9]{1,4}$")
_ATTR_NAME_RE = re.compile(r"^[A-Za-z_][-A-Za-z0-9_.]*(?::[A-Za-z_][-A-Za-z0-9_.]*)?$")

#: A child of an id'd element gets its own id when its parent is bigger than this
#: (a big group or a crowded <defs>), so the illustrator can patch one tree in a
#: forest without replacing the forest. Children of a <filter> always get ids: the
#: style skills tune filter primitives, and a filter is a handful of them.
BIG_PARENT_BYTES = 600
_ALWAYS_SPLIT = {"filter"}
_MAX_DEPTH = 4
_LEAF_TAGS = {
    "text",
    "tspan",
    "textPath",
    "animate",
    "animateTransform",
    "animateMotion",
    "set",
    "style",
    "title",
    "desc",
}

#: Per-op markup ceiling and op-count ceiling; the tool schema says the same.
MAX_OPS = 40
OPS = ("replace", "insert_after", "insert_before", "remove", "set_attrs")


class PatchError(BackdropError):
    """An op that cannot be applied. Nothing was changed."""


@dataclass
class _El:
    tag: str
    attrs: dict[str, str]
    start: int
    tag_end: int  # index just past the start tag's '>'
    end: int = 0  # index just past the whole element
    depth: int = 0
    parent: _El | None = None
    children: list[_El] = field(default_factory=list)
    text: str = ""
    self_closing: bool = False


def _start_tag_end(buf: bytes, i: int) -> int:
    quote = 0
    n = len(buf)
    while i < n:
        c = buf[i]
        if quote:
            if c == quote:
                quote = 0
        elif c in (0x22, 0x27):
            quote = c
        elif c == 0x3E:  # '>'
            return i + 1
        i += 1
    raise PatchError("the SVG has an unterminated tag")


def _parse(svg: str) -> tuple[bytes, _El]:
    """Parse ``svg`` into element spans (byte offsets into its UTF-8 encoding)."""
    buf = svg.encode("utf-8")
    parser = xml.parsers.expat.ParserCreate()
    parser.ordered_attributes = True
    stack: list[_El] = []
    roots: list[_El] = []

    def start(name: str, attrs: list[str]) -> None:
        i = parser.CurrentByteIndex
        tag_end = _start_tag_end(buf, i)
        el = _El(
            tag=name,
            attrs=dict(zip(attrs[0::2], attrs[1::2], strict=True)),
            start=i,
            tag_end=tag_end,
            depth=len(stack),
            parent=stack[-1] if stack else None,
            self_closing=buf[tag_end - 2 : tag_end - 1] == b"/",
        )
        if stack:
            stack[-1].children.append(el)
        else:
            roots.append(el)
        stack.append(el)

    def end(name: str) -> None:
        el = stack.pop()
        if el.self_closing:
            el.end = el.tag_end
        else:
            el.end = buf.index(b">", parser.CurrentByteIndex) + 1

    def chars(data: str) -> None:
        if stack and len(stack[-1].text) < 40:
            stack[-1].text += data

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(buf, True)
    except xml.parsers.expat.ExpatError as exc:
        raise PatchError(f"the SVG is not well-formed ({exc})") from None
    if len(roots) != 1 or roots[0].tag.rsplit(":", 1)[-1] != "svg":
        raise PatchError("a backdrop is a single <svg> document")
    return buf, roots[0]


def _walk(el: _El):
    yield el
    for child in el.children:
        yield from _walk(child)


def _local(tag: str) -> str:
    return tag.rsplit(":", 1)[-1]


def _wants_id(el: _El) -> bool:
    parent = el.parent
    if parent is None or el.depth > _MAX_DEPTH:
        return False
    if parent.parent is None:
        return True  # a top-level shape or group
    if EID_ATTR not in parent.attrs or _local(parent.tag) in _LEAF_TAGS:
        return False
    return _local(parent.tag) in _ALWAYS_SPLIT or parent.end - parent.start > BIG_PARENT_BYTES


def strip_eids(svg: str) -> str:
    """The SVG without the server's element ids — what is rendered and published."""
    return _EID_STRIP_RE.sub("", svg) if isinstance(svg, str) else svg


def _next_number(svgs: dict[str, str]) -> int:
    top = 0
    for svg in svgs.values():
        for m in re.finditer(r'data-eid="[dmb]([0-9]+)"', svg or ""):
            top = max(top, int(m.group(1)))
    return top + 1


def _label(svg: str, prefix: str, counter: int) -> tuple[str, int]:
    """Give every element that wants an id and has none the next number.

    Elements that already carry an id keep it: that is what makes ids stable across
    revisions. Re-parsed after each insertion pass so a newly id'd big group's
    children are judged with their parent's id in place.
    """
    for _ in range(_MAX_DEPTH + 1):
        buf, root = _parse(svg)
        todo = [el for el in _walk(root) if EID_ATTR not in el.attrs and _wants_id(el)]
        if not todo:
            return svg, counter
        out = bytearray(buf)
        for el in sorted(todo, key=lambda e: e.start, reverse=True):
            at = el.start + 1 + len(el.tag.encode("utf-8"))
            out[at:at] = f' {EID_ATTR}="{prefix}{counter + todo.index(el)}"'.encode()
        counter += len(todo)
        svg = out.decode("utf-8")
    return svg, counter


def annotate(svgs: dict[str, str]) -> dict[str, str]:
    """Return ``svgs`` with stable element ids added.

    Ids an illustrator typed itself are dropped first, so every id in a draft is
    one the server issued and none can collide. An SVG that does not parse is
    returned unchanged (stripped): the sanitizer refuses it with its own message.
    """
    out = {k: strip_eids(v) for k, v in svgs.items() if isinstance(v, str) and v.strip()}
    return relabel(out, start=1)


def relabel(svgs: dict[str, str], start: int | None = None) -> dict[str, str]:
    counter = _next_number(svgs) if start is None else start
    out: dict[str, str] = {}
    for key in ("markup", "mobile", "buttons"):
        svg = svgs.get(key)
        if not isinstance(svg, str) or not svg.strip():
            continue
        try:
            out[key], counter = _label(svg, PREFIXES[key], counter)
        except PatchError:
            out[key] = svg
    return out


# ── outline ─────────────────────────────────────────────────────────────

_GEOMETRY = {
    "rect": ("x", "y", "width", "height"),
    "circle": ("cx", "cy", "r"),
    "ellipse": ("cx", "cy", "rx", "ry"),
    "line": ("x1", "y1", "x2", "y2"),
    "path": ("d",),
    "polygon": ("points",),
    "polyline": ("points",),
    "use": ("href", "xlink:href", "x", "y"),
    "animate": ("attributeName", "values", "dur"),
    "animateTransform": ("type", "values", "dur"),
    "feTurbulence": ("baseFrequency", "numOctaves"),
    "feDisplacementMap": ("scale",),
    "feGaussianBlur": ("stdDeviation",),
    "stop": ("offset",),
}
_PAINT = ("fill", "stroke", "filter")
_SHORT = 14
#: Hard ceiling on one SVG's outline. A 24 KB draft (the tool's input cap) can
#: hold hundreds of shapes; past this the outline names how many it left out
#: and the illustrator patches their parent group instead.
OUTLINE_MAX_BYTES = 3000


def _short(value: str) -> str:
    value = " ".join(value.split())
    return value if len(value) <= _SHORT else value[: _SHORT - 1] + "…"


def _geometry(tag: str, a: dict[str, str]) -> list[str]:
    def g(k: str) -> str:
        return _short(a.get(k, "0"))

    if tag == "rect":
        return [f"{g('x')},{g('y')} {g('width')}x{g('height')}"]
    if tag == "circle":
        return [f"@{g('cx')},{g('cy')} r{g('r')}"]
    if tag == "ellipse":
        return [f"@{g('cx')},{g('cy')} r{g('rx')}/{g('ry')}"]
    if tag == "line":
        return [f"{g('x1')},{g('y1')}>{g('x2')},{g('y2')}"]
    return [f"{k}={_short(a[k])}" for k in _GEOMETRY.get(tag, ()) if k in a]


def _line(el: _El, indent: int) -> str:
    tag = _local(el.tag)
    parts = [el.attrs[EID_ATTR], tag + (f"#{el.attrs['id']}" if el.attrs.get("id") else "")]
    parts += _geometry(tag, el.attrs)
    for key in _PAINT:
        if key in el.attrs:
            parts.append(f"{key}={_short(el.attrs[key])}")
    if tag == "text" and el.text.strip():
        parts.append(repr(_short(el.text.strip())))
    if el.children:
        parts.append(f"kids={len(el.children)} {el.end - el.start}B")
    return " " * indent + " ".join(parts)


def outline(svg: str) -> str:
    """One line per id'd element: id, tag, key attributes. Never markup.

    Geometry is the start of a path or the box of a rect/circle, enough to tell
    which shape sits where; the illustrator has its own first draft in context.
    Ids run in document order. Capped at :data:`OUTLINE_MAX_BYTES`.
    """
    try:
        _, root = _parse(svg)
    except PatchError:
        return ""
    lines: list[str] = []

    def visit(el: _El, indent: int) -> None:
        for child in el.children:
            if EID_ATTR in child.attrs:
                lines.append(_line(child, indent))
                visit(child, indent + 1)

    visit(root, 0)
    out: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        size = len(line.encode("utf-8")) + 1
        if used + size > OUTLINE_MAX_BYTES - 40:
            out.append(f"… {len(lines) - i} more elements (patch their parent group)")
            break
        out.append(line)
        used += size
    return "\n".join(out)


# ── ops ─────────────────────────────────────────────────────────────────


def _find(svgs: dict[str, str], eid: Any, draft_id: str) -> tuple[str, bytes, _El]:
    if not isinstance(eid, str) or not _EID_VALUE_RE.match(eid):
        raise PatchError(f"unknown element id {eid!r}; use an id from draft {draft_id}'s outline")
    key = next(k for k, p in PREFIXES.items() if p == eid[0])
    svg = svgs.get(key)
    if svg:
        buf, root = _parse(svg)
        for el in _walk(root):
            if el.attrs.get(EID_ATTR) == eid:
                return key, buf, el
    raise PatchError(f"unknown element id {eid!r}; use an id from draft {draft_id}'s outline")


def _fragment(markup: Any, *, single: bool, where: str) -> tuple[bytes, int]:
    """Validate a patch's markup as an XML fragment of whole elements.

    Returns the fragment and the byte offset just past its first element's tag
    name (where ``replace`` writes the id it keeps).
    """
    if not isinstance(markup, str) or not markup.strip():
        raise PatchError(f"{where} needs `markup`: one or more SVG elements")
    clean = strip_eids(markup).strip()
    if clean.lower().startswith("<svg") or clean.lower().startswith("<?xml"):
        raise PatchError(f"{where}: `markup` is elements to splice in, not a whole <svg>")
    try:
        _, holder = _parse(f"<svg>{clean}</svg>")
    except PatchError as exc:
        raise PatchError(f"{where}: {exc}") from None
    if not holder.children:
        raise PatchError(f"{where} needs `markup`: one or more SVG elements")
    if single and len(holder.children) != 1:
        raise PatchError(f"{where}: replace takes exactly one element")
    first = holder.children[0]
    name_end = first.start - len(b"<svg>") + 1 + len(first.tag.encode("utf-8"))
    return clean.encode("utf-8"), name_end


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;").replace(">", "&gt;")
    )


def _start_tag(el: _El, attrs: dict[str, str]) -> bytes:
    body = "".join(f' {k}="{_escape(v)}"' for k, v in attrs.items())
    return f"<{el.tag}{body}{'/' if el.self_closing else ''}>".encode()


def _apply_one(svgs: dict[str, str], op: Any, draft_id: str, n: int) -> None:
    if not isinstance(op, dict):
        raise PatchError(f"op {n} must be an object")
    kind = op.get("op")
    where = f"op {n} ({kind})"
    if kind not in OPS:
        raise PatchError(f"op {n}: `op` must be one of {', '.join(OPS)}")
    key, buf, el = _find(svgs, op.get("id"), draft_id)
    eid = el.attrs[EID_ATTR]
    if kind == "remove":
        new = buf[: el.start] + buf[el.end :]
    elif kind == "replace":
        frag, name_end = _fragment(op.get("markup"), single=True, where=where)
        # The replacement keeps the id it replaces, so the outline stays stable.
        frag = frag[:name_end] + f' {EID_ATTR}="{eid}"'.encode() + frag[name_end:]
        new = buf[: el.start] + frag + buf[el.end :]
    elif kind in ("insert_after", "insert_before"):
        frag, _ = _fragment(op.get("markup"), single=False, where=where)
        at = el.end if kind == "insert_after" else el.start
        new = buf[:at] + frag + buf[at:]
    else:  # set_attrs
        changes = op.get("attrs")
        if not isinstance(changes, dict) or not changes:
            raise PatchError(f"{where} needs `attrs`: an object of attribute -> value")
        attrs = dict(el.attrs)
        for name, value in changes.items():
            if not isinstance(name, str) or not _ATTR_NAME_RE.match(name):
                raise PatchError(f"{where}: {name!r} is not an attribute name")
            if name == EID_ATTR:
                raise PatchError(f"{where}: {EID_ATTR} is the server's id and cannot be set")
            if value is None:
                attrs.pop(name, None)
            elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
                attrs[name] = str(value)
            else:
                raise PatchError(f"{where}: the value of {name!r} must be a string, or null")
        new = buf[: el.start] + _start_tag(el, attrs) + buf[el.tag_end :]
    svgs[key] = new.decode("utf-8")


def apply_ops(svgs: dict[str, str], ops: Any, draft_id: str) -> dict[str, str]:
    """Apply ``ops`` in order to a copy of the annotated draft ``svgs``.

    All or nothing: the first op that cannot apply raises :class:`PatchError` and
    the caller's draft is untouched. New elements get fresh ids; ids already in
    the draft never change.
    """
    if not isinstance(ops, list) or not ops:
        raise PatchError("pass `ops`: a non-empty list of element patches")
    if len(ops) > MAX_OPS:
        raise PatchError(f"at most {MAX_OPS} ops per revision, got {len(ops)}")
    work = dict(svgs)
    for n, op in enumerate(ops, 1):
        _apply_one(work, op, draft_id, n)
    for svg in work.values():
        _parse(svg)  # the merged document must still be one well-formed <svg>
    return relabel(work)


def patch_bytes(ops: list[Any]) -> int:
    """How many bytes of SVG the ops carried (markup plus attribute values)."""
    total = 0
    for op in ops if isinstance(ops, list) else []:
        if not isinstance(op, dict):
            continue
        total += len(str(op.get("markup") or "").encode("utf-8"))
        attrs = op.get("attrs")
        if isinstance(attrs, dict):
            total += sum(len(str(k)) + len(str(v)) for k, v in attrs.items())
    return total


__all__ = [
    "EID_ATTR",
    "MAX_OPS",
    "OPS",
    "PatchError",
    "annotate",
    "apply_ops",
    "outline",
    "patch_bytes",
    "relabel",
    "strip_eids",
]
