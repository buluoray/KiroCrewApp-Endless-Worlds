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
import re
from pathlib import Path
from typing import Any

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


async def reset_narrator_conversation(state: Any, store: Any, run_id: str) -> bool:
    """Give this run a FRESH narrator conversation while keeping everything else.

    Unlike ``purge_narrator_session`` (a deletion's scorched-earth companion), this
    is the seam for a life that continues: the live session is torn down and its
    resume pointer cleared through the running manager's ``discard_conversation``
    — never a detached map, whose whole-file write both misses the live manager's
    in-memory copy and can clobber entries it never loaded — so the next turn
    cold-starts a new conversation. The session-map ENTRY survives (channel
    linkage stays), the slot survives (the tab stays open), and narrative state is
    untouched.

    The briefed marker is cleared IN THE SAME seam, not left to callers: the turn
    loop re-sends the world's rulebook only when ``fresh_slot or briefed !=
    slot_key`` (turn.py), and a discard that keeps the slot leaves both false — a
    new conversation that was never told the rules of its world. One seam, one
    invariant: a discarded conversation always re-briefs.

    Best-effort like its siblings: a missing runtime or a bad id is a no-op.
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
    except Exception:  # noqa: BLE001
        return False
    try:
        await sessions.discard_conversation(_history_key_for(slot_key))
    except Exception:  # noqa: BLE001
        return False
    try:
        store.clear_briefed(run_id)
    except Exception:  # noqa: BLE001
        pass
    return True


#: Narrator slot keys THIS process created (or validated as its own). Exists for
#: close-detection only: a key registered here whose slot is gone from ``_slots``
#: was closed by the player, because nothing else removes an app slot mid-process.
#: Deliberately process-local — a gateway restart clears it, so a restart (where
#: the temporary-mode slot is simply absent, not closed) never reads as a close
#: and resumes the conversation exactly as it does today.
_LIVE_SLOT_KEYS: set[str] = set()


def consume_closed_slot(state: Any, run_id: str) -> bool:
    """True once per close: this process made the run's slot, and it is gone.

    ``consume`` because the answer resets on read — the caller acts on it (one
    conversation reset), and the key re-registers when the slot is re-created, so
    a second close later is detected again. Guarded like every sibling: a bad id
    or an unreadable runtime answers False, failing toward "continue".
    """
    try:
        slot_key = narrator_slot_key(run_id)
    except BadRunId:
        return False
    if slot_key not in _LIVE_SLOT_KEYS:
        return False
    slots = getattr(state, "_slots", None)
    if not isinstance(slots, dict) or slot_key in slots:
        return False
    _LIVE_SLOT_KEYS.discard(slot_key)
    return True


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


def release_stale_narrator_slot(state: Any, run_id: str) -> bool:
    """Release an older-install slot after enforcing the normal reuse guards.

    A foreign or memory-enabled slot is never removed automatically. A missing
    slot is fine: its persisted conversation is still purged separately before
    the replacement is created.
    """
    slot_key = narrator_slot_key(run_id)
    existing = state.get_slot(slot_key) if hasattr(state, "get_slot") else None
    if existing is None:
        return False
    _validate_existing_narrator_slot(existing, slot_key)
    if not release_narrator_slot(state, run_id):
        raise NarratorSlotError(
            f"{slot_key} belongs to an older app install and could not be replaced"
        )
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
        _validate_existing_narrator_slot(existing, slot_key)
        # Registered on the reuse path too: a slot that predates this module's
        # import (module reload) must still be close-detectable afterwards.
        _LIVE_SLOT_KEYS.add(slot_key)
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
    _LIVE_SLOT_KEYS.add(slot_key)
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
