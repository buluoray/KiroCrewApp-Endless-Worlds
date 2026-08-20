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
    role: str = "",
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Validate the player's answers and produce the state a run starts from.

    Validates EVERYTHING before building anything: a half-validated opening would
    create a run whose first turn contradicts what the player chose. A chosen `role`
    presets the opening: its `grants` fill matching opening groups the player left
    blank (the player's own answer always wins), and any grant that is not an opening
    group is kept as `granted` so the narrator and panels still see it.
    """
    if not isinstance(answers, dict):
        raise OpeningError("answers", "an object keyed by opening group")

    known = {g.id: g for g in template.opening}

    role_id = ""
    granted_extra: dict[str, Any] = {}
    if role:
        role_obj = next((r for r in template.roles if r.id == role), None)
        if role_obj is None:
            raise OpeningError("role", "one of this world's declared roles")
        role_id = role_obj.id
        answers = dict(answers)  # never mutate the caller's dict
        for gk, gv in role_obj.grants.items():
            group = known.get(gk)
            # A grant only pre-fills a real, player-answerable group the player has
            # not already answered; a world-decided (random) group is never preset,
            # and a grant for something the world does not ask becomes `granted`.
            if group is not None and not group.random:
                if answers.get(gk) in (None, ""):
                    answers[gk] = gv
            else:
                granted_extra[gk] = gv

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

    state: dict[str, Any] = {
        "worldId": template.id,
        "turn": 0,
        "style": _resolve_style(template, style),
        "language": template.language,
        "opening": resolved,
        # The run exists before its first turn does, so a failed opening turn
        # leaves something to retry rather than a half-created life (R2.9).
        "status": "awaiting-opening",
    }
    # A chosen role is a permanent fact of the life (app-owned, carried forward),
    # and its non-group grants seed state the narrator honours from turn one.
    if role_id:
        state["role"] = role_id
    if granted_extra:
        state["granted"] = granted_extra
    return state


def compose_opening_prompt(*, template: Template, run_id: str) -> str:
    """The opening turn's prompt: the run id, and an instruction to go read the
    rest. Nothing else.

    Everything a first turn needs — the world's rules, the player's opening
    choices (and which the world settled rather than the player), and the shape of
    the state to record — is served by ``endless_read_runtime`` on the narrator's
    first, no-``since`` call. It is kept OUT of this message on purpose: the
    narrator's session is visible to the player, and a 15,000-character rulebook
    plus a dump of every opening answer pushed into it makes that transcript a wall
    of setup. What is pushed is only what cannot be pulled — which run this is.

    ``run_id`` is still required and still named first, for the reason the turn
    prompt names it: every tool the narrator has takes it, and the first live
    opening turn failed because the prompt never named it — the narrator invented
    an id, its commit was refused, and it spent the turn hunting a run it could not
    name.
    """
    text = Content(template.language)
    return "\n".join([text("addressing", run_id=run_id, turn=1), "", text("opening.pull")])


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
