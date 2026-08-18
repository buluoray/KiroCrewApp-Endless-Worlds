"""The opening — how a life starts, on the world's own terms.

The template decides what a new life is asked, in what order, with which words.
This module only enforces the three rules that make those answers honest:

* **A group marked ``random`` is the world's call, not the player's.** In the
  flagship that is magic aptitude, and the rulebook is explicit that it is rolled
  rather than chosen. So a client that supplies a value for such a group is
  REFUSED rather than obeyed — accepting it would hand the player the one thing
  the world reserved, which is the anti-protagonist-halo rule at its most
  concrete (R7).
* **An unanswered group is not an error.** It means "let the world decide", and
  the narrator fills it in the opening turn. Forcing thirteen answers before
  anyone has read a sentence is how a life sim turns into a form.
* **A picked value must be one the world offered**, unless the group allows a
  custom answer — in which case anything the player typed is theirs to keep.
"""

from __future__ import annotations

import random
from typing import Any

from content import Content
from template import Template


class OpeningError(ValueError):
    """A malformed opening. Names the group so the UI can point at it."""

    def __init__(self, field: str, expected: str) -> None:
        super().__init__(f"{field}: {expected}")
        self.field = field
        self.expected = expected


#: What an unanswered group becomes. Stored rather than omitted so the narrator
#: can tell "the player left this to me" from "this world never asks it".
WORLD_DECIDES = None


def world_rolled_groups(template: Template) -> list[str]:
    return [g.id for g in template.opening if g.random]


def roll(template: Template, group_id: str, rng: random.Random | None = None) -> Any:
    """Roll one group. Only a group with options can be rolled.

    A ``text`` group has nothing to draw from — there is no list of plausible
    names in a rulebook — so rolling it yields "the world decides" rather than a
    fabricated value. Inventing one here would put the app's imagination where
    the narrator's belongs.
    """
    group = _group(template, group_id)
    if not group.options:
        return WORLD_DECIDES
    return (rng or random).choice(group.options)


def build_initial_state(
    template: Template,
    answers: dict[str, Any],
    *,
    style: str = "",
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Validate the player's answers and produce the state a run starts from.

    Validates EVERYTHING before building anything: a half-validated opening would
    create a run whose first turn contradicts what the player chose.
    """
    if not isinstance(answers, dict):
        raise OpeningError("answers", "an object keyed by opening group")

    known = {g.id: g for g in template.opening}
    for key in answers:
        if key not in known:
            raise OpeningError(f"answers.{key}", "not something this world asks")

    resolved: dict[str, Any] = {}
    for group in template.opening:
        if group.random:
            if group.id in answers and answers[group.id] not in (None, ""):
                raise OpeningError(
                    f"answers.{group.id}",
                    "decided by the world, not chosen — do not send a value",
                )
            resolved[group.id] = roll(template, group.id, rng)
            continue

        raw = answers.get(group.id)
        if raw is None or raw == "":
            resolved[group.id] = WORLD_DECIDES
            continue
        resolved[group.id] = _coerce(group, raw)

    return {
        "worldId": template.id,
        "turn": 0,
        "style": _resolve_style(template, style),
        "language": template.language,
        "opening": resolved,
        # The run exists before its first turn does, so a failed opening turn
        # leaves something to retry rather than a half-created life (R2.9).
        "status": "awaiting-opening",
    }


def compose_opening_prompt(
    *, rulebook: str, template: Template, state: dict[str, Any], run_id: str,
    shape: str = "",
) -> str:
    """Ask for the first turn: a life placed in the world, not a summary of a form.

    ``run_id`` is required for the same reason it is in ``turn.compose_prompt``:
    every tool the narrator has takes it, and the first live opening turn failed
    because the prompt never named it — the narrator invented an id, its commit was
    refused, and it spent the turn looking for a run it could not name.

    The language is read off the ``template`` rather than taken as an argument.
    A caller cannot then pass one that disagrees with the world whose rulebook is
    in the same call — which is not hypothetical: a ``language=`` argument WAS
    added at the call site while this signature had no such parameter, and because
    no test executes this route the resulting ``TypeError`` shipped.
    """
    text = Content(template.language)
    join = text("list.join")

    chosen: list[str] = []
    left: list[str] = []
    for group in template.opening:
        value = (state.get("opening") or {}).get(group.id)
        if value in (None, ""):
            left.append(group.label)
        elif group.random:
            chosen.append(text("opening.chosen.rolled", label=group.label, value=value))
        else:
            chosen.append(text("opening.chosen.line", label=group.label, value=value))

    parts = [
        text("addressing", run_id=run_id, turn=1),
        "",
        text("opening.rulebook"),
        rulebook.strip(),
        "",
        text("turn.pull"),
        "",
        text("opening.chosen"),
        "\n".join(chosen) if chosen else text("opening.chosen.none"),
    ]
    if left:
        parts += ["", text("opening.left"), join.join(left)]
    if shape:
        parts += ["", shape]
    parts += [
        "",
        text("opening.style", style=state.get("style")),
        "",
        text("opening.ask"),
    ]
    return "\n".join(parts)


# ── internals ────────────────────────────────────────────────────────────


def _group(template: Template, group_id: str) -> Any:
    for g in template.opening:
        if g.id == group_id:
            return g
    raise OpeningError(f"answers.{group_id}", "not something this world asks")


def _coerce(group: Any, raw: Any) -> Any:
    if group.kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise OpeningError(f"answers.{group.id}", "a number")
        try:
            return int(str(raw).strip())
        except ValueError as exc:
            raise OpeningError(f"answers.{group.id}", f"a number, got {raw!r}") from exc

    if not isinstance(raw, str):
        raise OpeningError(f"answers.{group.id}", "text")
    value = raw.strip()
    if len(value) > 200:
        raise OpeningError(f"answers.{group.id}", "at most 200 characters")

    if group.kind == "pick" and group.options and value not in group.options:
        if not group.custom:
            raise OpeningError(
                f"answers.{group.id}", "one of the options this world offers"
            )
    return value


def _resolve_style(template: Template, style: str) -> str:
    ids = {s.id for s in template.styles}
    if style and style in ids:
        return style
    for s in template.styles:
        if s.default:
            return s.id
    return next(iter(sorted(ids)), "")
