"""Rendering capability packs into panels (design §7.2, task 16).

A capability pack is declarative JSON — never code (R21.1) — that composes the
existing field primitives into a panel a world needs but no single primitive
covers. It lives inside the world file (``world.py``) and travels with the world.

This module is the *render* half: given the packs a world already carries and a
run's state, it produces panels the play view appends alongside the primitive
ones. Generation (the compiler turning an unmet panel kind into a pack) is a
separate, import-time concern and is deliberately not here.

Two invariants shape everything below:

* **A bad pack degrades; it never breaks the turn.** Each pack is rendered inside
  its own guard. A malformed pack, an unknown primitive, a path that will not
  resolve, or a pack declaring a newer contract than this build — any of these
  degrades *that one panel* to a labelled list of its raw values (R5.9) and play
  continues. The player is told nothing. A sibling pack that is well-formed still
  renders, so one broken pack cannot blank the others.

* **No dependency on ``view``.** The shaping function is passed in, so this module
  is testable in isolation and there is no import cycle with ``view`` (which is
  what calls it). The same ``_shape`` a primitive panel uses shapes a pack's
  composed values, so a pack renders identically to a hand-declared panel.
"""

from __future__ import annotations

from typing import Any, Callable

from template import FIELD_PRIMITIVES
from world import CONTRACT

#: How a pack's composed values are turned into renderable fields. Matches
#: ``view._shape``'s signature ``(primitive, raw, options) -> dict``.
Shaper = Callable[[str, Any, Any], dict[str, Any]]


def resolve_path(state: dict[str, Any], path: str) -> Any:
    """Read a value out of state by a dotted ``from`` path (design §7.2).

    Explicit and bounded, never ``eval`` — the same stance the ``when`` interpreter
    takes toward untrusted template text. Understands three things and nothing
    more:

    * ``state.a.b`` — walk dict keys; a missing key yields ``None``.
    * ``a[].b`` — ``a`` is a list; map the remaining path over each element,
      returning a list.
    * a leading ``state.`` (or a bare ``state``) is the root and is stripped.

    A path that cannot be walked (a scalar where a dict was expected, a non-list
    before ``[]``) yields ``None``/``[]`` rather than raising: a pack consuming a
    field the narrator has not filled yet is a gap, not a failure.
    """
    if not isinstance(path, str) or not path:
        return None
    if path == "state":
        return state
    if path.startswith("state."):
        path = path[len("state."):]
    return _walk(state, [seg for seg in path.split(".") if seg])


def _walk(node: Any, segments: list[str]) -> Any:
    if not segments:
        return node
    seg, rest = segments[0], segments[1:]
    if seg.endswith("[]"):
        key = seg[:-2]
        container = node.get(key) if isinstance(node, dict) else None
        if not isinstance(container, list):
            return []
        return [_walk(item, rest) for item in container]
    if isinstance(node, dict):
        return _walk(node.get(seg), rest)
    return None


def render_pack_panels(
    capability_packs: list[dict[str, Any]] | None,
    state: dict[str, Any],
    *,
    shape: Shaper,
    contract: int = CONTRACT,
) -> list[dict[str, Any]]:
    """Panels for every capability pack a world carries, degradation included.

    Returns one panel per pack, in declaration order, each shaped like a primitive
    panel so the play page's existing ``PanelBox`` renders it with no new
    component. A pack that cannot render becomes a degraded panel rather than an
    exception — see the module docstring.
    """
    out: list[dict[str, Any]] = []
    for pack in capability_packs or []:
        if not isinstance(pack, dict):
            continue
        try:
            out.append(_render_one(pack, state, shape, contract))
        except Exception:  # noqa: BLE001 — degradation is the contract, not a leak
            out.append(_degrade(pack, state))
    return out


def _pack_region(pack: dict[str, Any]) -> str:
    """The tab-bar bucket a pack panel lands in.

    Honors a region the pack declares for itself; otherwise the canonical
    ``pack`` region, which the tab bar orders and labels out of the box. Must
    never raise — it runs on the degradation path too.
    """
    region = pack.get("region") if isinstance(pack, dict) else None
    if isinstance(region, str) and region.strip():
        return region.strip()
    return "pack"


def _render_one(
    pack: dict[str, Any], state: dict[str, Any], shape: Shaper, contract: int
) -> dict[str, Any]:
    pack_id = pack.get("packId")
    if not isinstance(pack_id, str) or not pack_id:
        raise ValueError("a capability pack needs a packId")

    needed = pack.get("contract")
    if isinstance(needed, int) and needed > contract:
        # A pack built against a newer core: we cannot honestly render its
        # composition, so degrade rather than guess.
        raise ValueError(f"pack contract {needed} exceeds {contract}")

    provides = pack.get("provides")
    panel_kind = provides.get("panelKind") if isinstance(provides, dict) else None
    label = pack.get("label") or panel_kind or pack_id

    compose = pack.get("compose")
    if not isinstance(compose, list) or not compose:
        raise ValueError("a capability pack needs a non-empty compose list")

    fields: list[dict[str, Any]] = []
    for entry in compose:
        if not isinstance(entry, dict):
            raise ValueError("each compose entry must be an object")
        primitive = entry.get("primitive")
        if primitive not in FIELD_PRIMITIVES:
            # The compiler must never invent a primitive that does not exist
            # (design §7.3). At render time an unknown one degrades the pack.
            raise ValueError(f"unknown primitive {primitive!r}")
        as_ = entry.get("as") or entry.get("from") or primitive
        raw = resolve_path(state, str(entry.get("from") or ""))
        shaped = shape(str(primitive), raw, entry.get("options"))
        fields.append({
            "id": str(as_),
            "label": str(as_),
            "primitive": str(primitive),
            "options": entry.get("options") or {},
            **shaped,
        })

    return {
        "id": str(pack_id),
        "label": str(label),
        "always": False,
        # A pack panel is never "always"; it is shown because the world carries the
        # pack. The flag lets the UI style it distinctly later without any new type.
        "pack": True,
        # Without a region the phone tab bar has no bucket for the panel and it
        # renders nowhere on narrow viewports. A pack may tag its own region; the
        # canonical "pack" bucket (already labelled in both locales) is the floor.
        "region": _pack_region(pack),
        "fields": fields,
        "empty": all(f.get("kind") == "gap" for f in fields),
    }


def _degrade(pack: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """One panel reduced to a labelled list of its raw values (R5.9).

    The fallback path, and it must itself never raise. It reads the pack's
    declared ``consumes`` paths (falling back to its ``compose`` sources) and shows
    each as a plain labelled line. The player sees a plain panel, not an error.
    """
    pack_id = pack.get("packId")
    label = pack.get("label")
    if not isinstance(label, str) or not label:
        provides = pack.get("provides")
        label = (provides.get("panelKind") if isinstance(provides, dict) else None) or (
            pack_id if isinstance(pack_id, str) and pack_id else "…"
        )

    paths = pack.get("consumes")
    if not isinstance(paths, list) or not paths:
        compose = pack.get("compose")
        paths = (
            [e.get("from") for e in compose if isinstance(e, dict) and e.get("from")]
            if isinstance(compose, list)
            else []
        )

    fields: list[dict[str, Any]] = []
    for path in paths or []:
        if not isinstance(path, str) or not path:
            continue
        try:
            raw = resolve_path(state, path)
        except Exception:  # noqa: BLE001 — degradation cannot itself fail
            raw = None
        fields.append({
            "id": path,
            "label": _leaf(path),
            "primitive": "field",
            "kind": "gap" if raw is None else "field",
            "value": "" if raw is None else _readable(raw),
        })

    return {
        "id": str(pack_id) if isinstance(pack_id, str) and pack_id else "pack",
        "label": str(label),
        "always": False,
        "pack": True,
        "degraded": True,
        "region": _pack_region(pack),
        "fields": fields,
        "empty": all(f.get("kind") == "gap" for f in fields) if fields else True,
    }


def _leaf(path: str) -> str:
    """The last readable segment of a path, used as a degraded field's label."""
    seg = path.rsplit(".", 1)[-1]
    return seg[:-2] if seg.endswith("[]") else seg


def _readable(raw: Any) -> str:
    """A plain string for a degraded value — never a Python repr.

    Scalars stringify directly; a list/dict shows its string leaves joined, which
    keeps ``{'held': True, 'title': 'x'}`` from leaking as a repr the way a bare
    ``str()`` would.
    """
    if isinstance(raw, (str, int, float, bool)):
        return str(raw)
    if isinstance(raw, dict):
        parts = [v for v in raw.values() if isinstance(v, (str, int, float))]
        return "，".join(str(p) for p in parts)
    if isinstance(raw, list):
        parts = [x for x in raw if isinstance(x, (str, int, float))]
        return "，".join(str(p) for p in parts)
    return ""
