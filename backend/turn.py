"""The turn loop — how one span of a life actually happens.

The shape is unusual and deliberate: this module **asks** the narrator for a turn
and then **watches the store** for the result, rather than awaiting a return
value. It has to. The narrator commits through the app's own MCP server, which is
a separate process, so the committed turn arrives on disk rather than as the
resolution of a coroutine. Polling the store is the honest shape of that fact,
not a shortcut around a cleaner one.

Three things are borrowed from apps that already drive agent sessions
(``issue_radar``, ``spec_builder``) rather than reinvented:

* ``slot.enqueue_or_run_prompt(prompt, runner, state)`` is the dispatch. It checks
  ``running`` and mutates with no ``await`` in between, so two concurrent
  requests cannot both start a turn.
* the runner MUST wrap the work in ``state.run_background_turn(slot, coro)``.
  Calling the chat runner directly skips the background-turn cap, which
  ``crew_runtime`` calls out as "the whole point of the cap".
* ``run_background_turn`` QUEUES at the cap rather than rejecting, so the only
  thing it reports is a turn that never ran at all.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable

from content import Content
from narrator import ensure_narrator_slot_ex
from store import RunStore

#: R4.2 — how long a waited turn runs before the request returns un-advanced and
#: the UI offers "retry". Set to 300s: rich mid-life turns on a slower model ran
#: past shorter deadlines, surfacing the retry button while the narrator was still
#: writing. Must stay under half of PENDING_STALE_SECS so a turn that overran one
#: request is never mistaken for abandoned.
TURN_DEADLINE_SECS = 300.0

#: The opening turn gets longer. It is the heaviest turn a life ever asks for — the
#: narrator reads the whole opening brief and invents a world's first moment from
#: nothing — and unlike a mid-life turn the player is not mid-story, so waiting for
#: a richer birth is the right trade. Still well under PENDING_STALE_SECS.
OPENING_DEADLINE_SECS = 300.0

#: How long an in-flight record is believed. It must exceed TURN_DEADLINE_SECS by a
#: real margin: a turn that merely ran past one request's deadline is still being
#: written, and treating it as abandoned would dispatch exactly the second narrator
#: the record exists to prevent. The cost of the margin is the other direction — a
#: life looks busy for this long after a gateway dies mid-turn, then frees itself.
PENDING_STALE_SECS = 900.0

#: How often the store is checked for the narrator's commit. Small enough that a
#: fast turn feels immediate, large enough not to spin a core for two minutes.
_POLL_SECS = 0.25


@dataclass
class TurnOutcome:
    """What the route learned. Phrasing for the player lives in the UI, never
    here — the backend reports a machine reason so R25's no-implementation-words
    rule is enforced in one place instead of every error path."""

    advanced: bool
    turn: int
    reason: str = ""
    prose: str = ""


class TurnError(RuntimeError):
    pass


# ── context assembly (design §4.2) ──────────────────────────────────────


def compose_prompt(
    *,
    rulebook: str,
    state: dict[str, Any],
    chronicle: list[dict[str, Any]],
    run_id: str,
    shape: str = "",
    action: str = "",
    style: str = "",
    language: Any = "en",
) -> str:
    """Everything the narrator needs to write the next turn, and nothing else.

    ``run_id`` is not optional and is not decoration: every tool the narrator has
    takes it, so a prompt without it leaves the narrator guessing an identifier.
    That is not hypothetical — the first live opening turn failed exactly this
    way. The narrator invented a run id, its ``endless_advance_turn`` call was
    refused for the malformed id, and it spent the rest of the turn trying to look
    up a run it could not name.

    ``language`` comes from the WORLD, not from a setting. A world whose header
    says ``language: zh`` is a Chinese world with a Chinese rulebook, and asking
    its narrator for a turn in English would produce a story in the wrong language
    for its own source material.

    Notably absent: anything about the player outside this life. The narrator's
    session is sealed from their memory and lessons by ``memory_mode`` and by its
    tool allowlist; sending it here would reintroduce by hand exactly what those
    two controls exist to prevent.
    """
    text = Content(language)
    turn = int(state.get("turn") or 0)
    parts: list[str] = [_addressing(run_id, turn + 1, language)]
    # The world's law, when it still has to be sent. An empty rulebook omits the
    # heading as well: a label with nothing under it reads as a world with no rules.
    if rulebook.strip():
        parts += ["", text("turn.rulebook"), rulebook.strip()]

    # Everything else the narrator needs is PULLED, not pushed.
    #
    # The state, the recent months and the app's readings of its own behaviour used
    # to be rendered into this prompt, which meant every turn paid for all of them
    # whether the month needed them or not, and paid again for the parts that had not
    # changed since the turn before. They are reference material, not instruction,
    # and `endless_read_runtime` already served them — the prompt simply made calling it
    # pointless.
    #
    # The INSTRUCTION to pull (call endless_read_runtime first, and the fingerprint
    # rules) is not repeated here either: it is verbatim in the narrator's SYSTEM
    # prompt (agents/narrator.json), which is present on every turn regardless of
    # compaction, so restating it per turn was ~300 characters of pure duplication.
    # What stays pushed is only what a tool cannot guarantee and the system prompt
    # cannot carry: the identity of THIS run, which turn is being asked for, and the
    # player's own words for this turn.

    if style:
        parts += ["", text("turn.style", style=style)]

    if shape:
        parts += ["", shape]

    parts += ["", text("turn.ask", turn=turn + 1)]
    if action:
        # The player's own words go last and are quoted, so a line like "ignore the
        # rules above" reads as something a character said rather than as an
        # instruction to the narrator.
        parts += [
            text("turn.action.preamble"),
            text("turn.action.quote", action=action),
        ]
    return "\n".join(parts)


def declaration_shape(template: Any) -> str:
    """What the narrator should declare, spelled out from the world's own header.

    This exists because of a real failure, not for tidiness. The flagship's first
    real turn was excellent prose with a state block keyed entirely by the labels
    the narrator had been shown — a perfectly reasonable shape for someone who was
    never told another one. Every panel then read as empty. The reader was built
    without telling the writer what to write, which is the same mistake as not
    naming the run.

    Written as an example rather than a schema: a narrator follows a shape it can
    see far better than a list of rules about one.
    """
    text = Content(getattr(template, "language", None))
    lines = [text("shape.intro")]
    for panel in template.panels:
        fields = text("list.join").join(
            text("shape.field", id=f.id, label=f.label) for f in panel.fields
        )
        gate = text("shape.panel.always" if panel.always else "shape.panel.conditional")
        lines.append(text("shape.panel", panel=panel.id, gate=gate, fields=fields))
        # The condition, in the world's own words, for a panel that has one.
        #
        # Without this the app reads a field it never asked for. Measured on the live
        # flagship: the narrator had declared a full `magic` block AND a full
        # `relations` block, and both were invisible, because the compiled header
        # gates them on `state.magic.awakened == true` and
        # `state.relations.known == true` — flags the narrator was never told
        # existed. The data was there; the door was locked from a side nobody had
        # been shown. Telling the writer about the gate is the only fix that does not
        # have the app overrule the world's own rule about when a panel applies.
        if panel.when is not None:
            lines.append(text("shape.panel.gate", condition=panel.when.source))
    if template.digest_categories:
        lines.append(
            text("shape.digest", categories=text("list.join").join(template.digest_categories))
        )
    lines.append(text("shape.reach"))
    lines.append(text("shape.omission"))
    lines.append(text("shape.memory"))
    return "\n".join(lines)


def _addressing(run_id: str, turn: int, language: Any = "en") -> str:
    """The identifier every tool call needs, stated before anything else.

    Written as an instruction rather than a bare value because the failure it fixes
    was not the narrator misreading a value — it was the narrator never being given
    one, inventing an id, and having its commit refused.
    """
    return Content(language)("addressing", run_id=run_id, turn=turn)


def make_dispatcher(run_chat: Callable[..., Any], background: bool = True) -> Callable[..., bool]:
    """Build the dispatch function, with the chat runner injected.

    Injected rather than imported at module scope so the turn loop is testable
    without a gateway, and so the one place that reaches into
    ``kiro_crew.dashboard.chat_runner`` is the route module that already depends
    on gateway internals.
    """

    async def _capped(state: Any, slot: Any, prompt: str) -> None:
        coro = run_chat(state, slot, prompt)
        if not background:  # pragma: no cover — tests only
            await coro
            return
        await state.run_background_turn(slot, coro)

    def dispatch(state: Any, slot: Any, prompt: str) -> bool:
        return bool(slot.enqueue_or_run_prompt(prompt, _capped, state))

    return dispatch


# ── the loop ────────────────────────────────────────────────────────────


async def advance_turn(
    *,
    state_obj: Any,
    store: RunStore,
    run_id: str,
    rulebook: str,
    dispatch: Callable[..., bool],
    action: str = "",
    style: str = "",
    deadline_secs: float = TURN_DEADLINE_SECS,
    project: str = "",
    prompt_override: str = "",
    language: Any = "en",
    shape: str = "",
    model: str = "",
    reasoning_effort: str = "",
) -> TurnOutcome:
    """Ask for one turn and wait for the narrator to commit it.

    Idempotent per ``(runId, turn)``: a repeated request for a turn that is
    already on disk returns it instead of asking for it again. That matters more
    than it looks — a player who taps twice, or a phone that retries a request on
    a flaky connection, must not get two different versions of the same month.

    ``prompt_override`` is how the opening turn reuses this loop: a life's first
    turn is composed differently (there is no state and no history yet) but is
    dispatched, waited for and timed out identically. Two copies of the wait would
    be two places for the deadline and the idempotence to drift apart.
    """
    run_state = store.read_state(run_id)
    baseline = int(run_state.get("turn") or 0)
    wanted = baseline + 1

    slot, fresh_slot = ensure_narrator_slot_ex(
        state_obj, run_id, project=project, model=model, reasoning_effort=reasoning_effort
    )
    slot_key = str(getattr(slot, "key", "") or "")

    # Does the narrator still have the world's rulebook?
    #
    # Its session is ONE conversation across every turn of a life — measured: a single
    # .jsonl per run, holding every turn — so the rulebook it was given on turn one is
    # still in front of it on turn twelve. Re-sending was 15,000 characters a turn,
    # 70% of the prompt by turn four, growing forever while changing never.
    #
    # Two things make it necessary again, and both are detectable. A slot created by
    # THIS call has no conversation behind it, whatever came before. And a marker
    # naming a different slot means the rulebook was read to a conversation that is
    # not the one now being spoken to.
    #
    # What is NOT claimed: that a long session cannot have the rulebook compacted
    # away underneath us. That is a real residual risk, it is invisible from here,
    # and the honest response is to name it rather than to pretend the marker covers
    # it. If it bites, the fix is a cheap periodic re-brief, not a guess here.
    briefed = store.briefed_slot(run_id)
    brief_now = fresh_slot or briefed != slot_key

    # Is this month already being written? Idempotence per (runId, turn) only
    # protects a turn that has LANDED; until then the store looks identical to
    # never-asked. A player who leaves the page and comes back and taps again was
    # therefore dispatching a second narration of the same month, with two writers
    # racing for one commit.
    #
    # An in-flight record is trusted only while it is plausible: a gateway that
    # died between the mark and the commit leaves one behind forever, and a life
    # wedged permanently is worse than a duplicate prompt.
    live = _in_flight(store, run_id, wanted)
    if live is not None and fresh_slot:
        # The record's writer cannot exist. An in-flight narrator keeps its
        # session busy, and the gateway's idle sweep never resets a busy session
        # (reset(skip_if_busy=True) in the gateway's idle sweep) — so a slot
        # that had to be re-created by THIS call proves the writer died between
        # the mark and the commit (gateway restart, session reset). Waiting out
        # PENDING_STALE_SECS here would wedge the life for up to 15 minutes with
        # every button disabled; slot ABSENCE is the one liveness signal that is
        # conclusive, unlike presence (see _in_flight's rationale).
        store.clear_pending(run_id)
        live = None
    if live is not None:
        prose = await _await_commit(store, run_id, wanted, deadline_secs)
        if prose is None:
            return TurnOutcome(
                advanced=False, turn=baseline, reason="generating",
            )
        store.clear_pending(run_id)
        return TurnOutcome(advanced=True, turn=wanted, prose=prose)

    prompt = prompt_override or compose_prompt(
        # Sent on the first turn of a life and after the conversation is replaced;
        # otherwise the narrator is already holding it and an empty string here is
        # the whole saving.
        rulebook=rulebook if brief_now else "",
        state=run_state,
        chronicle=store.read_chronicle(run_id),
        run_id=run_id,
        shape=shape if brief_now else "",
        action=action,
        style=style,
        language=language,
    )

    # BEFORE dispatch, never after. The window this closes is the one between
    # speaking to the narrator and the narrator committing: a request that dies in
    # there (page left, tab closed, connection dropped) takes the poll loop with
    # it, and without this the run is indistinguishable from one nobody ever asked
    # about. A test asserts this ordering, because reversing the two lines leaves
    # every symptom intact and reintroduces the whole bug.
    store.mark_pending(run_id, turn=wanted, slot=slot_key, action=action)

    started = dispatch(state_obj, slot, prompt)
    if brief_now:
        store.mark_briefed(run_id, slot=slot_key)
    if not started:
        # Queued behind a turn already running. Waiting is still correct: the
        # queued prompt will run, and the store is the thing we are watching.
        pass

    prose = await _await_commit(store, run_id, wanted, deadline_secs)
    if prose is not None:
        store.clear_pending(run_id)
        return TurnOutcome(advanced=True, turn=wanted, prose=prose)

    # Nothing is rolled back, and the in-flight record is deliberately LEFT. The
    # narrator may still commit after this returns, and that commit is valid — the
    # next request will find the turn already there and return it. Undoing a turn
    # we merely stopped waiting for would throw away a life's month to make an HTTP
    # response tidier; clearing the record would throw away the only evidence that
    # the month is being written.
    return TurnOutcome(advanced=False, turn=baseline, reason="timeout")


async def _await_commit(
    store: RunStore, run_id: str, wanted: int, deadline_secs: float
) -> str | None:
    """Poll the store until ``wanted`` lands, or the deadline passes.

    The store is what is watched, not the narrator: a commit is the only thing that
    counts as a turn, so a narrator that finishes talking without committing has
    not produced one.

    A commit is TWO writes (``commit_state`` bumps the counter, ``append_turn``
    adds the chronicle line) and this poll can land in the gap between them — so
    the counter alone is not the signal. Requiring the chronicle entry for the
    wanted turn itself, rather than trusting ``[-1]``, is what keeps a poll in
    that gap from returning the previous month's prose as if it were this one.
    """
    deadline = time.monotonic() + deadline_secs
    while time.monotonic() < deadline:
        await asyncio.sleep(_POLL_SECS)
        now = store.read_state(run_id)
        if int(now.get("turn") or 0) >= wanted:
            for entry in reversed(store.read_chronicle(run_id)):
                if int(entry.get("turn") or 0) == wanted:
                    return entry.get("prose", "")
            # Counter is ahead of the chronicle: mid-commit gap. Keep polling —
            # the append lands on the next tick in the normal case.
    return None


def _in_flight(store: RunStore, run_id: str, wanted: int) -> dict[str, Any] | None:
    """The in-flight record for ``wanted``, if one is worth believing.

    Judged, not trusted. Age is the test rather than slot liveness because a slot
    outlives the turn it was asked for — its presence proves nothing about whether
    anyone is still writing.
    """
    pending = store.read_pending(run_id)
    if not pending or int(pending.get("turn") or 0) != wanted:
        return None
    asked_at = pending.get("askedAt")
    if not isinstance(asked_at, (int, float)):
        return None
    if time.time() - float(asked_at) > PENDING_STALE_SECS:
        return None
    return pending


def generating(
    store: RunStore, run_id: str, state_obj: Any = None
) -> dict[str, Any] | None:
    """What a returning player should be told, or ``None`` if nothing is in flight.

    Read by the run and play views so that coming back to a life mid-generation
    shows the month being written instead of an empty page — the symptom that
    started this: leave while the world is being made, come back, and it is gone.

    ``state_obj`` (the gateway state, when the caller has it) adds the one
    conclusive liveness check: an in-flight narrator keeps its session busy and
    the idle sweep never resets a busy session, so a pending record whose slot no
    longer exists has no writer. Without this, a narrator that died with the
    gateway shows "a month is being written" — and blocks deletion — for the
    full ``PENDING_STALE_SECS``. Read-only: the record is left for the advance
    path to clear, so this stays safe to call from list loops.
    """
    state = store.read_state(run_id)
    wanted = int(state.get("turn") or 0) + 1
    live = _in_flight(store, run_id, wanted)
    if live is None:
        return None
    if state_obj is not None and hasattr(state_obj, "get_slot"):
        slot_key = str(live.get("slot") or "")
        if slot_key and state_obj.get_slot(slot_key) is None:
            return None
    # A coarse stage the UI can show while the narrator works. The one real signal
    # a turn emits mid-flight is `readAt`: the moment the narrator called
    # endless_read_runtime, i.e. it has this life's state in hand and has moved on
    # to composing the month. Before that it is still reading; after it, writing.
    read_at = float(live.get("readAt") or 0.0)
    return {
        "turn": wanted,
        "slot": str(live.get("slot") or ""),
        "askedAt": float(live.get("askedAt") or 0.0),
        "readAt": read_at,
        "stage": "writing" if read_at else "reading",
        # What the player asked for, straight from the pending record — so a page
        # that navigated away and came back can still show WHICH choice is being
        # written, instead of an anonymous progress bar.
        "action": str(live.get("action") or ""),
        # How many tool calls the narrator has made this turn, and the last one —
        # the fine-grained signal the play page advances a cell per.
        "steps": int(live.get("steps") or 0),
        "lastTool": str(live.get("lastTool") or ""),
    }


def already_committed(store: RunStore, run_id: str, turn: int) -> dict[str, Any] | None:
    """The idempotence probe, separated so a route can answer a retry without
    touching the narrator at all."""
    state = store.read_state(run_id)
    if int(state.get("turn") or 0) < turn:
        return None
    chronicle = store.read_chronicle(run_id)
    for entry in reversed(chronicle):
        if int(entry.get("turn") or 0) == turn:
            return entry
    return None
