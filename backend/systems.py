"""The systems engine — world mechanics the BACKEND runs, not the narrator.

A world declares `systems` in its header (see ``template.System`` and
docs/design/world-as-data.md). Each turn, at commit, the app applies them off the
narrator's declared ``gains`` and the PRIOR committed state, writing derived state
the narrator may read but never overwrite. The narrator only declares what happened
(prose + gains/events); every number is the app's.

Why base off the PRIOR state, not the narrator's declaration: the narrator restates
the whole state each turn and could echo or invent a value. Reading the base from the
last committed turn and overwriting the system-owned path makes the value the app's
regardless of what the model wrote — the same ownership ``state.milestones`` has.

Best-effort by contract: a bad system is enrichment gone wrong, never a reason to
block a committed turn, so each system is applied in isolation and a failure in one
leaves the rest (and the turn) intact.
"""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> float:
    """A number from whatever the state or a gain's amount holds. Gains carry amount
    as a STRING (the tool schema), and a narrator may write '5', '5 gold', or ''."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        # Take a leading signed number if the string carries units ("5 gold").
        num = ""
        for ch in s:
            if ch in "+-" and not num:
                num += ch
            elif ch.isdigit() or (ch == "." and "." not in num):
                num += ch
            else:
                break
        try:
            return float(num) if num not in ("", "+", "-", ".") else 0.0
        except ValueError:
            return 0.0
    return 0.0


def _tail(path: str) -> str:
    """The last segment of a ``state.a.b.c`` path — how a gain's ``field`` matches a
    system's ``into`` (a gain with field 'xp' feeds into: state.hero.xp)."""
    return path.split(".")[-1] if path else ""


def _get(state: dict[str, Any], path: str) -> Any:
    """Read a ``state.a.b`` path from the state dict (the leading 'state.' is the
    grammar's root, not a real key)."""
    parts = [p for p in path.split(".") if p]
    if parts and parts[0] == "state":
        parts = parts[1:]
    cur: Any = state
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _set(state: dict[str, Any], path: str, value: Any) -> None:
    """Write a ``state.a.b`` path, creating intermediate dicts. Refuses to descend
    through a non-dict (a narrator that put a string where the system needs an object
    keeps its string; the system simply does not write, rather than corrupting it)."""
    parts = [p for p in path.split(".") if p]
    if parts and parts[0] == "state":
        parts = parts[1:]
    if not parts:
        return
    cur = state
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _clamp(value: float, floor: float | None, cap: float | None) -> float:
    if floor is not None and value < floor:
        value = floor
    if cap is not None and value > cap:
        value = cap
    return value


def _tidy(value: float) -> Any:
    """A whole number reads as an int (7, not 7.0) in a panel; keep fractions."""
    return int(value) if float(value).is_integer() else round(value, 3)


def _matched_sum(gains: list[Any], into: str) -> float:
    """Sum of the amounts of gains whose ``field`` matches this system's target — by
    the target's last path segment (into: state.hero.xp <- gains with field 'xp')."""
    target = _tail(into)
    total = 0.0
    for g in gains or []:
        if isinstance(g, dict) and str(g.get("field") or "").strip() == target:
            total += _num(g.get("amount"))
    return total


def _tier_name(tiers: list[dict[str, Any]], value: float) -> str:
    """The highest tier whose threshold `at` is <= value; '' if below the first."""
    name = ""
    best = None
    for t in tiers:
        at = t.get("at")
        if isinstance(at, (int, float)) and value >= at and (best is None or at >= best):
            best, name = at, str(t.get("name") or "")
    return name


def apply_systems(
    template: Any,
    state: dict[str, Any],
    prev: dict[str, Any],
    gains: list[Any],
) -> None:
    """Apply every declared system to ``state`` in place, reading base values from
    ``prev`` (the prior committed state) and this turn's ``gains``. Mutates ``state``.
    """
    for s in getattr(template, "systems", None) or []:
        try:
            if s.kind == "unlock":
                # Monotonic: once unlocked, stays unlocked (base from prior state).
                already = _get(prev, s.into) is True
                if already or (s.when is not None and s.when.evaluate(state)):
                    _set(state, s.into, True)
                continue

            base = _num(_get(prev, s.into))
            if s.kind == "accrual":
                value = _clamp(base + _matched_sum(gains, s.into), s.floor, s.cap)
                _set(state, s.into, _tidy(value))
                if s.tiers and s.tier_into:
                    name = _tier_name(s.tiers, value)
                    if name:
                        _set(state, s.tier_into, name)
            elif s.kind == "resource":
                value = _clamp(base + _matched_sum(gains, s.into) + s.per_turn, s.floor, s.cap)
                _set(state, s.into, _tidy(value))
            elif s.kind == "decay":
                value = _clamp(base + s.per_turn, s.floor, s.cap)
                _set(state, s.into, _tidy(value))
        except Exception:  # noqa: BLE001
            continue  # a system is enrichment; one bad system never blocks the turn
