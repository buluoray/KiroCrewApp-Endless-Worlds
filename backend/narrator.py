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

import hashlib
import inspect
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Files that define the installed app. Content catches updates even when mtimes are
#: preserved; inode/ctime metadata catches a same-content reinstall at the same path.
_APP_ROOT = Path(__file__).resolve().parent.parent
_GENERATION_GLOBS = (
    "app.json",
    "agents/*.json",
    "backend/*.py",
    "content/*.json",
    "seeds/*.md",
    "ui/*",
)


def _installation_generation(root: Path = _APP_ROOT) -> str:
    """Stable for one install, different after an update or reinstall."""
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8"))
    files = {path for pattern in _GENERATION_GLOBS for path in root.glob(pattern) if path.is_file()}
    for path in sorted(files, key=lambda item: item.as_posix()):
        try:
            stat = path.stat()
            payload = path.read_bytes()
        except OSError:
            # A concurrent installer can replace a file between glob and read. Its
            # absence still changes the generation; the next app load recomputes it.
            digest.update(f"missing:{path.relative_to(root)}".encode())
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(payload)
        digest.update(
            f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:"
            f"{stat.st_mtime_ns}:{stat.st_ctime_ns}".encode("ascii")
        )
    return digest.hexdigest()[:20]


#: Metadata-only signature of the install: cheap enough to recompute on every
#: turn (stat calls, no file reads). It deliberately over-triggers relative to
#: the content digest — any metadata wobble re-runs the full hash below, which
#: then answers whether the install REALLY changed.
def _metadata_signature(root: Path = _APP_ROOT) -> str:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8"))
    files = {path for pattern in _GENERATION_GLOBS for path in root.glob(pattern) if path.is_file()}
    for path in sorted(files, key=lambda item: item.as_posix()):
        try:
            stat = path.stat()
        except OSError:
            digest.update(f"missing:{path.relative_to(root)}".encode())
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(
            f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:"
            f"{stat.st_mtime_ns}:{stat.st_ctime_ns}".encode("ascii")
        )
    return digest.hexdigest()[:20]


#: ``(metadata signature, full content digest)`` of the last computation.
_GENERATION_CACHE: tuple[str, str] | None = None


def app_install_generation() -> str:
    """The CURRENT install's generation, evaluated per call.

    Persisted per life by RunStore; a different value means the existing narrator
    conversation belongs to another installed build and must be replaced.

    This is a function, not a module constant, for a reason proven on a live
    gateway: App Store Sync replaces the app's files WITHOUT re-importing this
    module (the gateway process survives the disable/enable pair), so a constant
    evaluated at import time keeps naming the pre-update install. Every turn after
    the update then compared stale-to-stale, concluded "no change", and the very
    reset the update should have triggered never fired — and worse, the first turn
    after the update PERSISTED the stale value as the run's marker, so even a
    restart would not have caught up that run.

    The full digest reads every governed file's bytes, so it is memoized on a
    stat-only metadata signature: unchanged metadata reuses the previous answer,
    and the 40-file byte read happens only when something actually moved.
    """
    global _GENERATION_CACHE
    # Root read from the module attribute AT CALL TIME — the helpers' default
    # arguments were bound at def time, which is exactly the frozen-at-import
    # failure this function exists to end.
    root = _APP_ROOT
    signature = _metadata_signature(root)
    if _GENERATION_CACHE is not None and _GENERATION_CACHE[0] == signature:
        return _GENERATION_CACHE[1]
    generation = _installation_generation(root)
    _GENERATION_CACHE = (signature, generation)
    return generation


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


#: Conversation ``n >= 1`` of a life lives at ``endless-run-<runId>-c<n>``;
#: conversation 0 keeps the bare key every life used before keys were numbered.
_CONVERSATION_SUFFIX_RE = re.compile(r"^(?P<run>.+)-c(?P<n>[1-9][0-9]{0,5})$")
_MAX_CONVERSATION = 999_999


def narrator_slot_key(run_id: str, conversation: int = 0) -> str:
    """The slot key of conversation ``conversation`` of this life.

    One key per conversation, never one per life: core keys the resume pointer,
    its transcript and its cold-start history replay by this key, so a fresh
    conversation on a reused key can be handed the old one back.
    """
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        raise BadRunId(f"not a run id: {run_id!r}")
    if (
        not isinstance(conversation, int)
        or isinstance(conversation, bool)
        or not 0 <= conversation <= _MAX_CONVERSATION
    ):
        raise BadRunId(f"not a conversation number: {conversation!r}")
    if conversation == 0:
        return f"{_SLOT_PREFIX}{run_id}"
    return f"{_SLOT_PREFIX}{run_id}-c{conversation}"


def life_slot_keys(store: Any, run_id: str) -> list[str]:
    """Every slot key this life has used, oldest first (current one last)."""
    try:
        current = int(store.conversation_number(run_id))
    except Exception:  # noqa: BLE001 — an unreadable record still has key 0
        current = 0
    try:
        return [narrator_slot_key(run_id, n) for n in range(current + 1)]
    except BadRunId:
        return []


def current_slot_key(store: Any, run_id: str) -> str:
    """The slot key of this life's current conversation."""
    return narrator_slot_key(run_id, int(store.conversation_number(run_id)))


def is_narrator_slot(slot_key: str) -> bool:
    return isinstance(slot_key, str) and slot_key.startswith(_SLOT_PREFIX)


def release_narrator_slot(state: Any, run_id: str, conversation: int = 0) -> bool:
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

    This is the fallback for a core without ``close_slot``; see
    :func:`retire_narrator_conversation` for the path that is normally taken.
    """
    try:
        slot_key = narrator_slot_key(run_id, conversation)
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


def _accepts_replay(fn: Any) -> bool:
    """Whether core's ``discard_conversation`` takes the ``replay`` keyword.

    A ``**kwargs`` signature counts: it forwards. Anything unintrospectable
    answers False, which degrades to the pre-knob call rather than raising.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if "replay" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


async def _suppress_next_replay(sessions: Any, key: str) -> None:
    """Tell core that *key*'s next cold start must begin EMPTY.

    Core arms that one-shot flag from exactly one place — ``discard_conversation``
    with ``replay=False`` — so a teardown that took any other route has to come
    back through this one to set it. Here the teardown has already happened, which
    makes every other effect of the call inert: the live session was popped by
    ``remove``, the map row by ``forget_conversation``, and the subagent-runtime
    reap is a pop of something already gone. The flag is the whole point.

    Best-effort by contract: this only ever spares the fresh narrator a
    reconstruction it should not see, so a failure must not turn a purge that
    otherwise succeeded into a reported failure.
    """
    try:
        if _accepts_replay(sessions.discard_conversation):
            await sessions.discard_conversation(key, replay=False)
    except Exception:  # noqa: BLE001
        pass


async def purge_narrator_session(state: Any, run_id: str, conversation: int = 0) -> bool:
    """Delete the narrator's persisted conversation when a life is deleted.

    ``release_narrator_slot`` drops the in-memory slot; this removes the kiro-cli
    conversation BEHIND it so a deleted life leaves no transcript on disk. The
    sequence mirrors the dashboard's own permanent-delete: shut the session down
    (``sessions.remove`` preserves the files for resume), forget its map entry to
    get the session id, then unlink that id's transcript files.

    Then suppress the next cold start's replay, for the reason spelled out on
    ``reset_narrator_conversation``: a cleared resume pointer is precisely what
    makes core rebuild the transcript from its OWN conversation log as a
    ``[CONVERSATION HISTORY]`` block, and that log is a separate artifact this
    function never touches — ``_unlink_layer_b_files`` removes kiro-cli's copy,
    not core's. Without the suppression a build swap tore the conversation down
    and was handed a reconstruction of it on the very next turn, which is what
    made an updated app look like it had never reset at all.

    Two orderings here are load-bearing, and both fail silently if reversed.
    The suppression must follow ``remove``, which DISCARDS that same flag (it is
    clearing a stale one, correctly, for a session it expects to resume) — armed
    first, it would be wiped by the next line. And it must follow
    ``forget_conversation``, which is the only read of the session id: the
    suppressing call ends in ``clear_sid``, so arming earlier would blank the id
    whose files this is here to unlink.

    Armed before the no-id early return, because a missing id does not mean a
    missing replay. Core's log is keyed by the session key, not by that id, so a
    run whose pointer was already gone still has a transcript to be handed back.

    Best-effort and fully guarded: a runtime without a session store, a missing
    dashboard import (as in unit tests), a bad id, or any per-step failure is a
    no-op that never fails the deletion the player asked for.
    """
    try:
        slot_key = narrator_slot_key(run_id, conversation)
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
    await _suppress_next_replay(sessions, key)
    if not sid:
        return False
    try:
        _unlink_layer_b_files(sid)
    except Exception:  # noqa: BLE001
        return False
    return True


def _core_close_slot() -> Any:
    """Core's own slot close, or None on a core (or a test) without it.

    ``close_slot`` is what the App Kit's ``DELETE /api/chat/slots/{slot}``
    (``deleteSlot``) runs: it retires the slot's nudge loop, tells the owning app,
    archives the transcript and tears the session down, in the order core's own
    races need. This backend runs inside the gateway, so it calls the same
    function instead of making an HTTP request to itself; the ownership check that
    route adds is :func:`retire_narrator_conversation`'s own.
    """
    try:
        from kiro_crew.dashboard.chat_api.slot_lifecycle import close_slot  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    return close_slot


def _delete_transcript(state: Any, history_key: str) -> None:
    """Delete core's transcript of a retired conversation through its history store.

    The same store method ``DELETE /api/sessions/{key}`` ends in. Best-effort: a
    transcript that cannot be removed is listed and nothing reads it, because no
    later conversation is ever given this key again.
    """
    log = getattr(state, "conversation_log", None)
    delete = getattr(log, "delete_session", None)
    if not callable(delete):
        return
    try:
        delete(history_key)
    except Exception:  # noqa: BLE001
        logger.debug("transcript delete failed for %s", history_key, exc_info=True)


async def retire_narrator_conversation(state: Any, run_id: str, conversation: int) -> bool:
    """Remove one earlier conversation of a life: its slot, session and transcript.

    Returns True when nothing of it is left that this app may remove, so the
    caller can stop tracking it. A slot under this key that another app (or
    nobody) owns is never touched and answers False: it is not ours to close.

    Never called on the CURRENT conversation by the turn loop. A key is only ever
    retired after the life has moved to a newer number, so a retired key is never
    asked for again and none of this has to guard a later reuse.
    """
    try:
        slot_key = narrator_slot_key(run_id, conversation)
    except BadRunId:
        return False
    slot = state.get_slot(slot_key) if hasattr(state, "get_slot") else None
    if slot is not None:
        if (getattr(slot, "_app", "") or "") != APP_NAME:
            return False
        close = _core_close_slot()
        closed = False
        if close is not None:
            try:
                await close(state, slot, slot_key)
                closed = True
            except Exception:  # noqa: BLE001 — core refused (a history write running)
                logger.warning("closing old narrator slot %s failed", slot_key, exc_info=True)
                return False
        if not closed:
            release_narrator_slot(state, run_id, conversation)
    await purge_narrator_session(state, run_id, conversation)
    try:
        from kiro_crew.dashboard.chat_utils import _history_key_for  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return True
    _delete_transcript(state, _history_key_for(slot_key))
    return True


async def retire_stale_conversations(state: Any, store: Any, run_id: str) -> list[str]:
    """Remove every earlier conversation of a life still on record. Returns the keys
    removed. Best-effort: a failure leaves the number on record for the next turn."""
    removed: list[str] = []
    try:
        stale = list(store.stale_conversations(run_id))
    except Exception:  # noqa: BLE001
        return removed
    for n in stale:
        try:
            done = await retire_narrator_conversation(state, run_id, n)
        except Exception:  # noqa: BLE001
            logger.warning("retiring conversation %s of %s failed", n, run_id, exc_info=True)
            continue
        if done:
            try:
                store.forget_stale_conversation(run_id, n)
            except Exception:  # noqa: BLE001
                pass
            removed.append(narrator_slot_key(run_id, n))
    return removed


async def retire_all_conversations(state: Any, run_id: str, conversations: list[int]) -> None:
    """Remove every conversation a deleted life ever had, current one included.

    ``conversations`` is read by the caller BEFORE the store forgets the life,
    because the record of how many there were is deleted with it.
    """
    for n in conversations:
        try:
            await retire_narrator_conversation(state, run_id, n)
        except Exception:  # noqa: BLE001 — a deletion never fails on cleanup
            logger.warning("retiring conversation %s of %s failed", n, run_id, exc_info=True)


def start_new_conversation(store: Any, run_id: str) -> int:
    """Point this life at a brand-new conversation key. Synchronous on purpose.

    The new number is written before anything awaits, so a second request that
    arrives while the old conversation is still being removed already finds the
    new key. The briefed marker is cleared first: it names the old key anyway,
    and cleared first a failed write costs a re-send rather than a conversation
    that was never told its world's rules.
    """
    try:
        store.clear_briefed(run_id)
    except Exception:  # noqa: BLE001
        pass
    return int(store.begin_conversation(run_id))


async def reset_narrator_conversation(state: Any, store: Any, run_id: str) -> bool:
    """Give this run a FRESH narrator conversation while keeping everything else.

    The life moves to a new conversation number, so its next turn opens a slot
    under a key core has never seen: no resume pointer, no transcript, nothing to
    replay. Then the previous conversation's slot, session and transcript are
    removed. Narrative state is untouched.

    Every path that starts a conversation over goes through here or through
    :func:`start_new_conversation`: the player's reset control, the dismissal
    hook, and the planned rotations (chapter, budget, idle). The install change
    and the slot heal in ``turn.py`` call the two halves directly.

    Returns False only for a bad run id.
    """
    try:
        narrator_slot_key(run_id)
    except BadRunId:
        return False
    start_new_conversation(store, run_id)
    await retire_stale_conversations(state, store, run_id)
    return True


def conversation_from_slot_key(slot_key: str) -> tuple[str, int]:
    """``(run_id, conversation)`` for a narrator slot key, or ``("", 0)``.

    The inverse of :func:`narrator_slot_key`, and validated the same way: core
    hands the hook a slot name, and a name that does not decode to a real run id
    must be ignored rather than fed to the store.
    """
    if not is_narrator_slot(slot_key):
        return "", 0
    rest = slot_key[len(_SLOT_PREFIX) :]
    numbered = _CONVERSATION_SUFFIX_RE.match(rest)
    if numbered and _RUN_ID_RE.match(numbered.group("run")):
        return numbered.group("run"), int(numbered.group("n"))
    return (rest, 0) if _RUN_ID_RE.match(rest) else ("", 0)


def run_id_from_slot_key(slot_key: str) -> str:
    """The run a narrator slot belongs to, or ``""`` if the key is not one."""
    return conversation_from_slot_key(slot_key)[0]


def install_close_hook(state: Any, store: Any) -> None:
    """Ask core to TELL us when the player dismisses one of this app's tabs.

    Core draws the distinction we need and draws it by which call site fires:
    ``notify_slot_closed`` runs only for a deliberate dismissal, and the bulk
    idle-archive path deliberately does not come through it. That matters because
    both paths stamp the same ``closed_at`` on the transcript, so a slot's mere
    ABSENCE from ``state._slots`` cannot tell "the player closed this" from "this
    was quiet for three days" — and the second must not discard a conversation
    nobody asked to end.

    Dismissing the CURRENT conversation's tab moves the life to a new
    conversation. The dismissed slot itself is left to core, which is closing it
    as this runs; its session and transcript are removed with the other stale
    conversations on the next turn. Closing an OLD conversation's slot (which
    :func:`retire_narrator_conversation` does through core, so it arrives here
    too) changes nothing.

    A failure here must NOT block the close. Core refuses the dismissal when the
    hook raises — right for an app whose hook is the write that pauses a worker,
    wrong for ours: the player wants the tab gone. So the hook swallows its own
    failure.

    Re-registered from the turn path rather than once at import, because core's
    registry is process memory: a gateway restart or a module reload empties it,
    and a hook installed only at import would go quiet with no signal. Core keys
    the registry by app name and re-registering replaces, so calling this every
    turn costs one dict write and cannot accumulate hooks.
    """
    try:
        from kiro_crew.apps.teardown import register_slot_close_hook  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — no dashboard runtime (unit tests)
        return

    async def _on_slot_closed(slot_key: str) -> None:
        run_id, conversation = conversation_from_slot_key(slot_key)
        if not run_id:
            return
        try:
            if int(store.conversation_number(run_id)) != conversation:
                return  # an old conversation being retired, or a stranger
            # Marked BEFORE the switch: the marker is what stops the next turn's
            # planned rotation from switching again away from a conversation
            # this just made fresh.
            store.mark_rotation(run_id, turn=int(store.read_state(run_id).get("turn") or 0))
            start_new_conversation(store, run_id)
        except Exception:  # noqa: BLE001 — see the docstring: a raise here would
            # make core REFUSE the player's close.
            logger.warning("conversation reset on dismissal failed for %s", run_id, exc_info=True)

    try:
        register_slot_close_hook(APP_NAME, _on_slot_closed)
    except Exception:  # noqa: BLE001
        pass


def _validate_existing_narrator_slot(slot: Any, slot_key: str) -> None:
    """Refuse slots that this app cannot safely reuse or replace."""
    owner = getattr(slot, "_app", "") or ""
    if owner != APP_NAME:
        raise SlotOwnedByAnother(
            f"{slot_key} is held by {owner or 'nobody'}; refusing to take it over"
        )
    # Checked explicitly, and ALSO passed to the create call, so the two
    # enforcement points are independent: core's own memory-mode guard is the
    # backstop if this branch is ever bypassed.
    if getattr(slot, "memory_mode", "") != MEMORY_MODE:
        raise MemoryModeConflict(
            f"{slot_key} has memory_mode={getattr(slot, 'memory_mode', '')!r}, need {MEMORY_MODE!r}"
        )


def ensure_narrator_slot(state: Any, run_id: str, *, project: str = "") -> Any:
    """Return this run's narrator slot, creating it scoped if it is not there.

    Raises rather than degrading. Every failure here means "do not narrate": a slot
    we do not own, or one not sealed from the player's memory, is not something to
    work around.
    """
    return ensure_narrator_slot_ex(state, run_id, project=project)[0]


def ensure_narrator_slot_ex(
    state: Any,
    run_id: str,
    *,
    project: str = "",
    model: str = "",
    reasoning_effort: str = "",
    conversation: int = 0,
) -> tuple[Any, bool]:
    """The slot of conversation ``conversation``, and whether THIS call created it.

    The second value exists for one caller and one reason: a slot that already
    existed has a conversation behind it. The turn loop uses that to decide whether
    the world's rulebook still has to be sent — 15,000 characters, measured,
    re-sent on every single turn before this — or whether the narrator is already
    holding it from earlier in the same session.

    A created slot is NOT proof of an empty conversation on its own: a slot that
    core archived for idleness is recreated under the same key and resumes. Only a
    new conversation NUMBER (``store.begin_conversation``) guarantees one.

    Kept as a separate function so the plain name keeps its plain signature; a
    caller that does not care about the distinction should not have to unpack it.
    """
    slot_key = narrator_slot_key(run_id, conversation)

    existing = state.get_slot(slot_key) if hasattr(state, "get_slot") else None
    if existing is not None:
        _validate_existing_narrator_slot(existing, slot_key)
        # Re-applied on an EXISTING slot too, so a player who changes model or
        # effort sees it take on the very next turn.
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
