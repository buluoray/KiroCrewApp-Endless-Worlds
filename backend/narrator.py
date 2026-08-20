"""The narrator's session — one app-owned slot per run.

Three properties have to hold at once, and each is enforced here rather than
hoped for:

1. **The narrator cannot read or write the player's memory** (R26). The mechanism
   is ``memory_mode="temporary"``, which is load-bearing in BOTH directions:
   ``slot.blocks_reads`` stops memory/lessons context injection
   (``context.py:2003``, ``:2073``, wired at ``chat_runner.py:4614``) and
   ``slot.is_restricted`` stops the consolidator (``chat_utils.py:1225``).
   ``temporary``'s *prompt prefix* also tells the model not to call memory tools
   (``chat_utils.py:1139``), but that is advice a model can ignore — so the
   agent's ``tools`` allowlist (``agents/narrator.json``) is what actually makes
   a memory tool unreachable. Advisory and mechanism are kept distinct on
   purpose; only the second is relied on.

2. **The slot belongs to this app.** ``get_or_create_slot`` keys off the name and
   stamps ``_app`` only on CREATE (``state.py:4501-4520``), so a slot that came
   up by any other route is unowned — it shows in the player's main chat list and
   its approved tools run from the gateway's working directory. We create it
   here, first, and refuse a slot another app owns rather than taking it over.
   This mirrors ``spec_builder``'s ``_ensure_worker_slot``, which learned it the
   hard way.

3. **This app never grants itself tool approval at runtime.** No ``_trust``, no
   ``_trusted_patterns``. ``spec_builder`` removed exactly that after finding a
   backend grant could not be bounded honestly (its TTL was enforced on a UI
   poll, so closing the page stopped enforcement while the grant lived on) — see
   its ``test_app_never_grants_worker_trust``. Approval-free play comes from the
   *declared* allowlist in the packaged agent, which the governance ceiling can
   still veto (``governance.py:may_skip_gate``), not from a runtime stamp.
"""

from __future__ import annotations

import re
from typing import Any

#: Must equal app.json's ``name`` — it is what ``_app`` is compared against.
APP_NAME = "endless-worlds"

#: Must equal agents/narrator.json's ``name``.
NARRATOR_AGENT = "endless-narrator"

#: The app's own MCP server, as the agent must reference it.
#:
#: NAMESPACED, not the bare manifest key. Registration writes every app server
#: under ``f"{app_name}:{server_name}"`` (bridges.py:2064, :2094);
#: ``_own_mcp_servers`` returns those entries unrenamed (bridges.py:549) and
#: ``_register_agents`` merges them into the materialized agent's ``mcpServers``
#: (bridges.py:945-948). kiro-cli resolves ``@x`` against those keys, so the bare
#: form resolves to nothing and is dropped silently at mount time.
OWN_SERVER_KEY = "endless-mcp"
OWN_SERVER_REF = f"@{APP_NAME}:{OWN_SERVER_KEY}"

#: Not negotiable per run. ``persistent`` would let the narrator read the
#: player's real life, and ``incognito`` still READS memory — only ``temporary``
#: blocks injection (``state.py:2039-2041``).
MEMORY_MODE = "temporary"

_SLOT_PREFIX = "endless-run-"

#: Run ids reach here from stored app state, which the narrator itself can be
#: talked into rewriting. From here the value becomes a slot key and then a
#: history filename, so it is validated before it can flow into either.
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


class NarratorSlotError(RuntimeError):
    """Base: the narrator must not run."""


class BadRunId(NarratorSlotError):
    pass


class SlotOwnedByAnother(NarratorSlotError):
    """Something else holds this key. Never adopt it."""


class MemoryModeConflict(NarratorSlotError):
    """The slot exists but is not sealed from the player's memory.

    Refusing is the only safe answer. Continuing would narrate into a session
    that reads the player's preferences and lessons and writes back to them,
    which is the one thing R26 exists to prevent — and a fallback to
    ``persistent`` would make the seal look present while being absent.
    """


def narrator_slot_key(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        raise BadRunId(f"not a run id: {run_id!r}")
    return f"{_SLOT_PREFIX}{run_id}"


def is_narrator_slot(slot_key: str) -> bool:
    return isinstance(slot_key, str) and slot_key.startswith(_SLOT_PREFIX)


def release_narrator_slot(state: Any, run_id: str) -> bool:
    """Drop this run's narrator slot when its life is deleted. Returns whether a
    slot was released.

    Deleting a life removes its store rows, but the in-memory slot — one per run —
    would otherwise linger for the gateway's lifetime, holding a conversation for a
    life that no longer exists. This releases it.

    Best-effort and defensive on purpose: a slot-cleanup failure must never fail
    the deletion the player asked for, so every step is guarded and a missing
    runtime, a bad id, or a slot this app does not own is simply a no-op. Only a
    slot stamped with THIS app is ever removed — we never reach into another
    owner's slot.
    """
    try:
        slot_key = narrator_slot_key(run_id)
    except BadRunId:
        return False
    slots = getattr(state, "_slots", None)
    if not isinstance(slots, dict):
        return False
    slot = slots.get(slot_key)
    if slot is None:
        return False
    if (getattr(slot, "_app", "") or "") != APP_NAME:
        return False
    slots.pop(slot_key, None)
    # Pending question cards belong to a life that is gone; drop them, then refresh
    # the slot list the dashboard renders. Both are conveniences — a failure here
    # leaves the slot already removed.
    cancel = getattr(state, "cancel_questions_for_slot", None)
    if callable(cancel):
        try:
            cancel(slot_key)
        except Exception:  # noqa: BLE001
            pass
    push = getattr(state, "_push_slots", None)
    if callable(push):
        try:
            push()
        except Exception:  # noqa: BLE001
            pass
    return True


async def purge_narrator_session(state: Any, run_id: str) -> bool:
    """Delete the narrator's persisted conversation when a life is deleted.

    ``release_narrator_slot`` drops the in-memory slot; this removes the kiro-cli
    conversation BEHIND it so a deleted life leaves no transcript on disk. The
    sequence mirrors the dashboard's own permanent-delete: shut the session down
    (``sessions.remove`` preserves the files for resume), forget its map entry to
    get the session id, then unlink that id's transcript files.

    Best-effort and fully guarded: a runtime without a session store, a missing
    dashboard import (as in unit tests), a bad id, or any per-step failure is a
    no-op that never fails the deletion the player asked for.
    """
    try:
        slot_key = narrator_slot_key(run_id)
    except BadRunId:
        return False
    sessions = getattr(state, "sessions", None)
    if sessions is None:
        return False
    try:
        from kiro_crew.dashboard.chat_utils import _history_key_for  # noqa: PLC0415
        from kiro_crew.dashboard.session_transfer import (  # noqa: PLC0415
            _unlink_layer_b_files,
        )
    except Exception:  # noqa: BLE001
        return False
    key = _history_key_for(slot_key)
    try:
        await sessions.remove(key)
    except Exception:  # noqa: BLE001
        pass
    sid = ""
    try:
        sid = sessions.forget_conversation(key) or ""
    except Exception:  # noqa: BLE001
        pass
    if not sid:
        return False
    try:
        _unlink_layer_b_files(sid)
    except Exception:  # noqa: BLE001
        return False
    return True


def ensure_narrator_slot(state: Any, run_id: str, *, project: str = "") -> Any:
    """Return this run's narrator slot, creating it scoped if it is not there.

    Raises rather than degrading. Every failure here means "do not narrate": a slot
    we do not own, or one not sealed from the player's memory, is not something to
    work around.
    """
    return ensure_narrator_slot_ex(state, run_id, project=project)[0]


def ensure_narrator_slot_ex(
    state: Any, run_id: str, *, project: str = "", model: str = "", reasoning_effort: str = ""
) -> tuple[Any, bool]:
    """The slot, and whether THIS call created it.

    The second value exists for one caller and one reason: a slot that already
    existed has a conversation behind it, and a slot created just now does not. The
    turn loop uses that to decide whether the world's rulebook still has to be sent
    — 15,000 characters, measured, re-sent on every single turn before this — or
    whether the narrator is already holding it from earlier in the same session.

    Kept as a separate function so the plain name keeps its plain signature; a
    caller that does not care about the distinction should not have to unpack it.
    """
    slot_key = narrator_slot_key(run_id)

    existing = state.get_slot(slot_key) if hasattr(state, "get_slot") else None
    if existing is not None:
        owner = getattr(existing, "_app", "") or ""
        if owner != APP_NAME:
            raise SlotOwnedByAnother(
                f"{slot_key} is held by {owner or 'nobody'}; refusing to take it over"
            )
        # Checked explicitly, and ALSO passed to the create call below, so the
        # two enforcement points are independent: core's own guard
        # (state.py:4501) is the backstop if this branch is ever bypassed.
        if getattr(existing, "memory_mode", "") != MEMORY_MODE:
            raise MemoryModeConflict(
                f"{slot_key} has memory_mode="
                f"{getattr(existing, 'memory_mode', '')!r}, need {MEMORY_MODE!r}"
            )
        # Re-applied on an EXISTING slot too, so a player who changes the model or
        # effort on the home page sees it take on the very next turn of a life
        # already in progress, not only on a fresh one.
        _apply_choice(existing, model, reasoning_effort)
        return existing, False

    slot = state.get_or_create_slot(
        name=slot_key,
        agent=NARRATOR_AGENT,
        app=APP_NAME,
        memory_mode=MEMORY_MODE,
    )
    # Passing ``app`` is also what tags the slot's ORIGIN as APP, not USER: core
    # derives ``slot._origin = origin or (SlotOrigin.APP if app else "")``
    # (state.py). That origin is what a ``slots:user`` grant keys off, so an
    # app-created narrator slot is never mistaken for one the player opened.

    # kwargs apply only on CREATE, so anything else the slot needs is assigned
    # after — see the same note in auto_research/handlers.py:1705.
    if project:
        slot.project = project
    _apply_choice(slot, model, reasoning_effort)

    # Deliberately absent: slot._trust / slot._trusted_patterns. See the module
    # docstring. A test asserts this file never assigns them.
    return slot, True


# ── the worldsmith: a second agent, driven the same way ────────────────────
#
# Compiling a pasted rulebook into a playable world is the same kind of job as a
# turn — an app-owned chat slot, memory sealed, driven by _run_chat and answering
# through the app's MCP server — but a DIFFERENT agent (its prompt is the compiler
# brief + the framework's playability contract, not a life narration) and keyed on
# the draft, not a run. It reuses the narrator's guards rather than inventing new
# ones; a compiler slot has no life to be sealed FROM, but temporary memory is
# still correct (it must not read or write the player's memory either).

#: Must equal agents/worldsmith.json's ``name``.
WORLDSMITH_AGENT = "endless-worldsmith"

#: Distinct from ``_SLOT_PREFIX`` so ``is_narrator_slot`` never claims a draft slot
#: and vice versa.
_DRAFT_SLOT_PREFIX = "endless-worlddraft-"

#: A draft id reaches here from stored app state; validated before it becomes a
#: slot key. Same shape as drafts._DRAFT_ID_RE (kept local to avoid an import).
_DRAFT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def worldsmith_slot_key(draft_id: str) -> str:
    if not isinstance(draft_id, str) or not _DRAFT_ID_RE.match(draft_id):
        raise BadRunId(f"not a draft id: {draft_id!r}")
    return f"{_DRAFT_SLOT_PREFIX}{draft_id}"


def is_worldsmith_slot(slot_key: str) -> bool:
    return isinstance(slot_key, str) and slot_key.startswith(_DRAFT_SLOT_PREFIX)


def ensure_worldsmith_slot(
    state: Any, draft_id: str, *, project: str = "", model: str = "", reasoning_effort: str = ""
) -> Any:
    """The draft's worldsmith slot, created if absent. Mirrors
    ``ensure_narrator_slot_ex`` (same ownership + memory-mode guards) but binds the
    worldsmith agent and keys on the draft."""
    slot_key = worldsmith_slot_key(draft_id)

    existing = state.get_slot(slot_key) if hasattr(state, "get_slot") else None
    if existing is not None:
        owner = getattr(existing, "_app", "") or ""
        if owner != APP_NAME:
            raise SlotOwnedByAnother(
                f"{slot_key} is held by {owner or 'nobody'}; refusing to take it over"
            )
        if getattr(existing, "memory_mode", "") != MEMORY_MODE:
            raise MemoryModeConflict(
                f"{slot_key} has memory_mode="
                f"{getattr(existing, 'memory_mode', '')!r}, need {MEMORY_MODE!r}"
            )
        _apply_choice(existing, model, reasoning_effort)
        return existing

    slot = state.get_or_create_slot(
        name=slot_key,
        agent=WORLDSMITH_AGENT,
        app=APP_NAME,
        memory_mode=MEMORY_MODE,
    )
    if project:
        slot.project = project
    _apply_choice(slot, model, reasoning_effort)
    return slot


def release_worldsmith_slot(state: Any, draft_id: str) -> bool:
    """Drop a draft's worldsmith slot when the draft is discarded or installed.
    Best-effort; only ever removes a slot this app owns."""
    try:
        slot_key = worldsmith_slot_key(draft_id)
    except BadRunId:
        return False
    slots = getattr(state, "_slots", None)
    if not isinstance(slots, dict):
        return False
    slot = slots.get(slot_key)
    if slot is None:
        return False
    if (getattr(slot, "_app", "") or "") != APP_NAME:
        return False
    slots.pop(slot_key, None)
    return True


def _apply_choice(slot: Any, model: str, reasoning_effort: str) -> None:
    """Set the player's chosen model / reasoning effort on the slot.

    Empty means "leave the agent's own default" (``auto`` model, no effort
    override), so an unset preference never forces a concrete id onto a slot — an
    explicit pick is the only thing that overrides.
    """
    if isinstance(model, str) and model:
        slot.model = model
    if isinstance(reasoning_effort, str) and reasoning_effort:
        slot.reasoning_effort = reasoning_effort
