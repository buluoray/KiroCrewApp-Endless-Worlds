"""Route registration for the 无限世界 app.

External-app contract (verified against apps/route_registry.py:27-32):
``register_routes(ctx)`` returns ``list[AppRoute]`` whose paths are RELATIVE to
``/api/apps/endless-worlds``. Handlers take ``(request, ctx)``. The builtin
pattern of ``app.router.add_get`` never dispatches here — the RouteRegistry
catch-all ``/api/apps/{app_name}/{path:.*}`` shadows it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from kiro_crew.apps.context import AppContext
from kiro_crew.apps.route_registry import AppRoute

# The app's own modules are siblings of this file. The gateway imports this module
# by dotted path, which does not put its directory on sys.path.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


#: True when this module is being imported by the test suite rather than by the
#: gateway's app loader. The sibling purge below is skipped in that case, and the
#: reason is not tidiness: purging swaps module identity underneath anything
#: already holding a reference, and in one process running many test files that
#: is order-dependent — a ``monkeypatch`` can land on one copy of a module while
#: the code under test uses another. In the gateway there is exactly one load per
#: enable, so the hazard does not exist there.
_UNDER_TEST = "pytest" in sys.modules

#: String form of this app's backend directory, for the cheap prefix test in the
#: purge below. Computed once because the purge runs over every loaded module.
_HERE_PREFIX = str(_HERE) + os.sep

#: The module names this app OWNS — one per ``.py`` file beside this one. They are
#: BARE names (``store``, ``view``, ``template``), which is the whole reason the
#: eviction half of the purge below has to exist: a bare name is not this app's
#: property, and ``sys.modules`` is consulted before ``sys.path``.
_MY_MODULES = frozenset(p.stem for p in _HERE.glob("*.py"))


def _drop_stale_siblings(modules: dict[str, Any] | None = None) -> None:
    """Make ``import store`` resolve to THIS app's ``store``, on every load.

    Two different failures, one mechanism.

    **A stale copy of my own module.** An app disable→enable re-executes THIS file
    but does not unload the sibling modules it imported. Those siblings live in
    ``sys.modules`` under bare names for the whole life of the gateway process, so
    after an edit the fresh ``routes`` imports the OLD ``scenes`` — and the symptom
    is a route module that fails to load with ``cannot import name 'X' from
    'scenes'`` while the file on disk plainly has ``X``. No number of
    disable→enable cycles fixes it; only a gateway restart would, which is far too
    big a hammer for editing an app.

    **Someone else's module squatting on a name I own.** This one shipped: after
    this app was renamed and reinstalled under a new id, the new install failed to
    load with ``cannot import name 'Chapter' from 'template'`` — and the path in
    that message was the OLD app's ``template.py``, still held by the live process
    after its app had been uninstalled. The bare name resolved to a foreign file
    and handed this app someone else's code. An earlier revision of this function
    deliberately let that through: it purged only modules whose ``__file__`` was
    under this backend directory, on the grounds that clearing another app's module
    would break them to fix us. That reasoning was right about the risk and wrong
    about the conclusion — a foreign occupant of a name I import is not a module I
    can politely leave alone, it is a module I am about to be handed instead of my
    own.

    Eviction is safe in the direction that matters. Names already bound by the
    other app (``from template import Chapter``) keep working, because they are
    references, not lookups; only a future ``import template`` re-runs — and it
    re-runs against whatever ``sys.path`` that importer has, which is its own. Two
    apps sharing a bare name therefore ping-pong the slot and each restores its own
    view before importing, at the cost of re-executing a module. Not pretty, and
    strictly better than reading the wrong file.

    Purges by PATH, unconditionally. An earlier revision only dropped modules whose
    recorded mtime had moved, to avoid the test-process hazard above — and that
    could not work: the stale module predated the stamping, carried no recorded
    mtime, and was therefore skipped. A mechanism that cannot clear the exact state
    it exists for is worse than none, because it looks like a fix.

    ``modules`` exists so a test can prove every half against a throwaway mapping
    instead of the live one. Verifying the drop half against the real
    ``sys.modules`` means performing the very identity swap the guard above exists
    to avoid — which is how a test asserting this function works broke an unrelated
    one two files away.
    """
    target = sys.modules if modules is None else modules
    if modules is None and _UNDER_TEST:
        return

    # Half one: evict a FOREIGN occupant of a name this app owns. Keyed on the
    # name, so it costs one dict lookup per file this app has — not a walk of the
    # thousands of modules the gateway holds.
    for name in _MY_MODULES:
        if name == __name__:
            continue
        module = target.get(name)
        if module is None:
            continue
        origin = getattr(module, "__file__", None)
        if not origin:
            # A namespace package or a C extension under one of my names is not
            # mine either, and there is no path to compare. Evict: the import that
            # follows can only be better off with my file.
            del target[name]
            continue
        if not str(origin).startswith(_HERE_PREFIX):
            del target[name]

    # Half two: drop a stale copy of my OWN module so an edit actually reloads.
    for name in list(target):
        if name == __name__:
            continue
        module = target.get(name)
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        # Cheap string test before the expensive one. ``resolve()`` is a
        # filesystem call, and the gateway's ``sys.modules`` holds thousands of
        # entries — asking the kernel about every one of them is a cost paid on
        # the event loop to learn something a prefix comparison already answers.
        if not str(origin).startswith(_HERE_PREFIX):
            continue
        try:
            if Path(origin).resolve().parent != _HERE:
                continue
        except (OSError, ValueError):
            continue
        del target[name]


_drop_stale_siblings()

from backdrop import BackdropError, BackdropStore, compile_backdrop  # noqa: E402
from backdrop_timing import BackdropTimeline  # noqa: E402
from chapters import brief as world_brief  # noqa: E402
from chapters import opened_since  # noqa: E402
from drafts import DraftError, DraftStore, worldsmith_prompt  # noqa: E402
from library import LibraryError, WorldLibrary  # noqa: E402
from memory_routes import memory_routes  # noqa: E402
from narrator import (  # noqa: E402
    ensure_narrator_slot_ex,
    ensure_worldsmith_slot,
    narrator_slot_key,
    purge_narrator_session,
    release_narrator_slot,
    release_worldsmith_slot,
    reset_narrator_conversation,
    worldsmith_slot_key,
)
from opening import OpeningError, build_initial_state, compose_opening_prompt  # noqa: E402
from perf import TurnPerf, join_usage  # noqa: E402
from perf import aggregate as perf_aggregate  # noqa: E402
from scenes import AlreadyAnswered, SceneLedger, SceneLedgerError, StaleScene  # noqa: E402
from settings import REASONING_EFFORTS, read_settings, write_settings  # noqa: E402
from store import CorruptRunState, RunStore, StoreError  # noqa: E402
from turn import (  # noqa: E402
    BACKDROP_STALE_SECS,
    OPENING_DEADLINE_SECS,
    advance_turn,
    already_committed,
    declaration_shape,
    generating,
    make_dispatcher,
)
from view import build_play_view, resolve_ending, world_detail  # noqa: E402
from widget import CSP, SceneSpecError, bound_values, compile_cached  # noqa: E402
from world import CONTRACT  # noqa: E402

#: Bumped independently of app.json; identifies the route contract the UI expects.
ROUTE_CONTRACT = 11

logger = logging.getLogger(__name__)


#: Requested art is part of its page, not optional decoration arriving later.
#: Tasks are process-local accelerators; the durable request lets ``get_run``
#: restart recovery after a dropped HTTP request or gateway restart.
_BACKDROP_RECOVERY_TASKS: dict[str, asyncio.Task[None]] = {}
_BACKDROP_ILLUSTRATOR_ATTEMPTS = 2
_BACKDROP_ATTEMPT_SECS = 180.0
_BACKDROP_POLL_SECS = 0.25
#: The whole-recovery budget for the MODEL to land art. When it elapses without a
#: committed backdrop, the server publishes the traced underlay directly (a real
#: photo/base image, no model call) instead of letting the illustrator keep
#: running or the narrator hand-draw. Deliberately shorter than
#: ``_BACKDROP_ATTEMPT_SECS`` × attempts: a scene page's underlay is already the
#: bulk of the image, so a fast real image beats waiting minutes for the overlay.
_BACKDROP_FALLBACK_SECS = 120.0
#: How long one brief may withhold its committed page. Art is part of its page,
#: but a request with no age bound violated the fail-soft principle in the one
#: place it matters most: a pipeline that can never produce art (no renderer,
#: an uncooperative narrator) withheld the committed month FOREVER, while every
#: other enrichment drops with a warning. A replacement brief refreshes
#: ``askedAt`` and buys a fresh window; the recovery-cycle cap below bounds how
#: many silent narrator re-notifications can extend the wait.
#:
#: Imported rather than restated: ``turn.generating`` reads the same ceiling to
#: decide when to stop reporting "painting", and the two drifting apart is what
#: froze a life — the page was released here while the waiting state never ended.
_BACKDROP_STALE_SECS = BACKDROP_STALE_SECS
#: How many silent narrator recovery cycles one brief may spend. Each cycle
#: dispatches a real model turn every ``_BACKDROP_ATTEMPT_SECS``; without a cap
#: an uncooperative narrator burned tokens indefinitely (the illustrator side
#: has ``_BACKDROP_ILLUSTRATOR_ATTEMPTS``; this is its narrator twin). A
#: replacement brief writes a fresh record, so real progress resets the budget.
_BACKDROP_NARRATOR_CYCLES = 3

#: Painterly styles whose technique ships as a per-style skill file in the app.
#: ``photo`` deliberately has no entry: its "skill" is the trace tool chain, which
#: the illustrator's own contract already teaches.
_STYLE_SKILLS = {
    "watercolor": "svg-style-watercolor",
    "oil": "svg-style-oil",
    "minimal": "svg-style-minimal",
}


def _style_directive(style: str) -> str:
    """The task lines that make a declared painterly style teachable.

    The illustrator's system prompt is static JSON and cannot know where the app
    was installed, so the absolute path of the style's skill file is resolved HERE
    (the backend knows its own location) and handed to the illustrator's ``read``
    tool. The skill teaches technique and parameter RANGES, never fixed numbers —
    the illustrator is expected to look at its draft previews and tune.
    """
    name = _STYLE_SKILLS.get(style)
    if not name:
        return ""
    skill = Path(__file__).resolve().parent.parent / "skills" / name / "SKILL.md"
    return (
        f"\nSTYLE: {style} — before drawing, read {skill} with the read tool. "
        "It teaches the technique and parameter RANGES, not fixed values: after "
        "endless_submit_backdrop_draft, judge the painterly texture in the preview "
        "PNGs and tune your filter numbers in your one revision.\n"
    )


def _backdrop_is_pending(
    ctx: AppContext, store: RunStore, run_id: str, state: dict[str, Any] | None = None
) -> bool:
    """Whether the committed page is withheld for its explicitly requested art."""
    request = store.read_backdrop_request(run_id)
    if not request:
        return False
    current = state or store.read_state(run_id)
    turn = int(current.get("turn") or 0)
    if int(request.get("turn") or 0) != turn:
        return False
    # A brief older than the ceiling stops withholding: the committed month is
    # released and the art degrades to "arrives whenever it lands" — the same
    # fail-soft every other enrichment already gets.
    asked_at = request.get("askedAt")
    if isinstance(asked_at, (int, float)) and time.time() - float(asked_at) > _BACKDROP_STALE_SECS:
        return False
    return BackdropStore(ctx.data_dir, run_id).exact(turn) is None


async def _wait_for_backdrop(
    ctx: AppContext,
    store: RunStore,
    run_id: str,
    turn: int,
    spawn_id: str,
    deadline_secs: float = _BACKDROP_ATTEMPT_SECS,
) -> bool:
    """Wait for exact page art, or until this illustrator has ended."""
    spawn = getattr(ctx, "spawn", None)
    deadline = asyncio.get_running_loop().time() + deadline_secs
    while asyncio.get_running_loop().time() < deadline:
        if BackdropStore(ctx.data_dir, run_id).exact(turn) is not None:
            store.clear_backdrop_request(run_id)
            return True
        if spawn is not None and spawn.is_done(spawn_id):
            return False
        await asyncio.sleep(_BACKDROP_POLL_SECS)
    return False


def _narrator_runner() -> Any:
    """The platform runner, imported lazily so backend unit tests stay standalone."""
    from kiro_crew.dashboard.chat_runner import _run_chat  # noqa: PLC0415

    return _run_chat


async def _recover_backdrop(
    ctx: AppContext,
    store: RunStore,
    state_obj: Any,
    run_id: str,
    *,
    painter_model: str,
    narrator_model: str,
    reasoning_effort: str,
    art_quality: str = "standard",
) -> None:
    """Land requested art without exposing orchestration failures to the player.

    Two independent illustrators try first. If neither commits the exact turn, the
    same narrator conversation receives an internal repair prompt: it may issue a
    simpler brief (starting a fresh illustrator cycle) or draw through the
    server-gated direct fallback. The ordinary generation state stays on screen.

    ``art_quality`` is the player's speed/polish trade: ``fast`` caps the
    illustrators at ONE attempt and instructs that attempt to publish its first
    competent draft (the draft tool's answer carries the same instruction), so a
    failed fast attempt falls through to the narrator/server fallbacks sooner.
    """
    try:
        # The model's whole-recovery budget. When it elapses, the server publishes
        # the traced underlay directly rather than waiting longer or hand-drawing.
        loop = asyncio.get_running_loop()
        recovery_deadline = loop.time() + _BACKDROP_FALLBACK_SECS
        while True:
            request = store.read_backdrop_request(run_id)
            if not request:
                return
            turn = int(request.get("turn") or 0)
            if BackdropStore(ctx.data_dir, run_id).exact(turn) is not None:
                store.clear_backdrop_request(run_id)
                return

            attempts = int(request.get("attempts") or 0)
            spawn = getattr(ctx, "spawn", None)
            within_budget = loop.time() < recovery_deadline
            attempt_cap = 1 if art_quality == "fast" else _BACKDROP_ILLUSTRATOR_ATTEMPTS
            if attempts < attempt_cap and spawn is not None and within_budget:
                attempt = attempts + 1
                store.update_backdrop_request(run_id, attempts=attempt)
                BackdropTimeline(ctx.data_dir, run_id).mark(
                    turn, "recover:illustrator-dispatched", attempt=attempt
                )
                review_clause = (
                    (
                        "with EXACTLY this runId and turn, glance at the returned "
                        "preview PNGs only to confirm nothing is structurally broken "
                        "(blank frame, unreadable composition), and publish that "
                        "first draft with endless_commit_backdrop using the returned "
                        "draftId — fast art mode: no revision pass. "
                    )
                    if art_quality == "fast"
                    else (
                        "with EXACTLY this runId and turn, read every returned preview "
                        "PNG together as images, revise at most once, and publish the "
                        "final pair with endless_commit_backdrop using the returned "
                        "draftId. "
                    )
                )
                task = (
                    "Paint the desktop/mobile backdrop pair for one page of a life. "
                    "Follow the ART BRIEF's declared lane exactly. In LANE: scene, "
                    "first call endless_trace_reference with its REFERENCE keywords "
                    "and inspect both trace previews; in LANE: motif, draw directly "
                    "without tracing. A declared painterly STYLE (watercolor/oil/"
                    "minimal) replaces the trace requirement — hand-draw the scene "
                    "in that style instead. Then call endless_submit_backdrop_draft "
                    f"{review_clause}"
                    f"This is invisible recovery attempt {attempt}; use "
                    "only the brief and the lane's provided tools, with no external "
                    "research.\n"
                    f"{_style_directive(str(request.get('style') or ''))}"
                    f"runId: {run_id}\nturn: {turn}\n\nBrief:\n"
                    f"{str(request.get('brief') or '')}"
                )
                try:
                    spawn_id = await spawn.run(
                        task,
                        agent="endless-illustrator",
                        silent=True,
                        model=painter_model,
                    )
                except Exception as exc:  # noqa: BLE001 — continue recovery
                    logger.warning(
                        "endless-worlds: illustrator attempt %s failed for %s/%s: %s",
                        attempt,
                        run_id,
                        turn,
                        exc,
                    )
                    continue
                # Wait only for what is left of the budget, so a slow illustrator
                # cannot push the total past the server-fallback point.
                remaining = max(_BACKDROP_POLL_SECS, recovery_deadline - loop.time())
                if await _wait_for_backdrop(
                    ctx, store, run_id, turn, spawn_id, deadline_secs=remaining
                ):
                    BackdropTimeline(ctx.data_dir, run_id).mark(
                        turn, "recover:illustrator-committed", attempt=attempt
                    )
                    return
                BackdropTimeline(ctx.data_dir, run_id).mark(
                    turn, "recover:illustrator-timeout", attempt=attempt
                )
                continue

            # The model's budget is spent (or it has no illustrator). Before asking
            # the narrator to hand-draw, publish the traced underlay directly: for a
            # SCENE page the illustrator has almost always already traced a photo or
            # a base, and that underlay is itself a finished backdrop — a real image,
            # no model call, no minutes-long hand-draw.
            try:
                from mcp_server import commit_underlay_only  # noqa: PLC0415

                if commit_underlay_only(ctx.data_dir, store, run_id, turn):
                    return
            except Exception as exc:  # noqa: BLE001 — fall through to narrator
                logger.warning(
                    "endless-worlds: server underlay fallback failed for %s/%s: %s",
                    run_id,
                    turn,
                    exc,
                )

            # No traced underlay to publish (a motif page, or the illustrator never
            # traced). Ask the narrator that wrote this page to simplify the
            # direction or use the exceptional direct fallback.
            if state_obj is None:
                return  # a later real gateway GET restarts the durable request
            if int(request.get("recoveryCycles") or 0) >= _BACKDROP_NARRATOR_CYCLES:
                # Budget spent: stop re-dispatching. The request stays for a
                # possible late commit, and staleness releases the page.
                logger.warning(
                    "endless-worlds: backdrop recovery for %s/%s stopped after %s narrator cycles",
                    run_id,
                    turn,
                    _BACKDROP_NARRATOR_CYCLES,
                )
                return
            request = (
                store.update_backdrop_request(run_id, fallbackAllowed=True, narratorNotified=True)
                or request
            )
            marker = float(request.get("askedAt") or 0.0)
            slot, _fresh = ensure_narrator_slot_ex(
                state_obj,
                run_id,
                project=str(ctx.data_dir / "runs" / run_id),
                model=narrator_model,
                reasoning_effort=reasoning_effort,
            )
            prompt = (
                f"Internal page-art recovery for runId {run_id}, turn {turn}. "
                "The prose/state are already committed; do NOT narrate or call "
                "endless_advance_turn. Two illustrators ended without committing art. "
                "Recover invisibly: either call endless_paint_backdrop with a NEW, "
                "simpler brief, or draw one safe SVG yourself and call "
                "endless_commit_fallback_backdrop with this exact runId and turn. "
                "Do not explain the failure and do not write an ordinary reply."
            )
            make_dispatcher(_narrator_runner())(state_obj, slot, prompt)

            # A replacement brief changes askedAt and resets attempts; a direct
            # fallback clears the request. Re-notify after a bounded silent stall.
            deadline = asyncio.get_running_loop().time() + _BACKDROP_ATTEMPT_SECS
            while asyncio.get_running_loop().time() < deadline:
                if BackdropStore(ctx.data_dir, run_id).exact(turn) is not None:
                    store.clear_backdrop_request(run_id)
                    return
                latest = store.read_backdrop_request(run_id)
                if latest is None:
                    return
                if float(latest.get("askedAt") or 0.0) > marker:
                    break
                await asyncio.sleep(_BACKDROP_POLL_SECS)
            else:
                # A silent stall: no art, no replacement brief. Spend one cycle
                # of the narrator budget before asking again — this counter is
                # what makes the loop above finite.
                store.update_backdrop_request(
                    run_id,
                    narratorNotified=False,
                    recoveryCycles=int(request.get("recoveryCycles") or 0) + 1,
                )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — GET can resume the durable request
        logger.exception("endless-worlds: backdrop recovery paused for run %s: %s", run_id, exc)


def _ensure_backdrop_recovery(
    ctx: AppContext,
    store: RunStore,
    state_obj: Any,
    run_id: str,
    settings: dict[str, str],
) -> None:
    """Ensure one recovery task per run; safe from POST and every polling GET."""
    if not _backdrop_is_pending(ctx, store, run_id):
        return
    current = _BACKDROP_RECOVERY_TASKS.get(run_id)
    if current is not None and not current.done():
        return
    task = asyncio.create_task(
        _recover_backdrop(
            ctx,
            store,
            state_obj,
            run_id,
            painter_model=settings.get("painterModel") or "",
            narrator_model=settings.get("model") or "",
            reasoning_effort=settings.get("reasoningEffort") or "",
            art_quality=str(settings.get("artQuality") or "standard"),
        )
    )
    _BACKDROP_RECOVERY_TASKS[run_id] = task

    def _forget(done: asyncio.Task[None]) -> None:
        if _BACKDROP_RECOVERY_TASKS.get(run_id) is done:
            _BACKDROP_RECOVERY_TASKS.pop(run_id, None)

    task.add_done_callback(_forget)


#: Seeds ship in the install tree, one level up from backend/.
_SEEDS_DIR = _HERE.parent / "seeds"


def _unauthorized() -> web.Response:
    return web.json_response({"error": "unauthorized"}, status=401)


def _library(ctx: AppContext) -> WorldLibrary:
    return WorldLibrary(ctx.data_dir, _SEEDS_DIR)


def _drafts(ctx: AppContext) -> DraftStore:
    """The world-draft store — the same files the MCP server reaches from its own
    process (both self-locate from the app data dir)."""
    return DraftStore(ctx.data_dir)


def _store(ctx: AppContext) -> RunStore:
    """The turn loop's store.

    ``ctx.storage`` is the AppStorage the platform populated for us — only
    because ``permissions.storage`` is declared (apps/context.py: "Only services
    declared in the app's permissions are populated; others are None").
    """
    if ctx.storage is None:
        raise RuntimeError("ctx.storage is None — permissions.storage not declared")
    return RunStore(ctx.storage, ctx.data_dir)


def _gateway_state(request: web.Request) -> Any:
    """The gateway state object, or None outside a full gateway (tests, tools).

    Callers hand it to ``generating()`` for the slot-liveness check; None simply
    degrades that check to the age-only judgement, so nothing here may raise.
    """
    app = getattr(request, "app", None)
    return app.get("state") if app is not None else None


def _load_run_state(
    store: RunStore, run_id: str
) -> tuple[dict[str, Any] | None, web.Response | None]:
    """State or a clean error response — exactly one of the pair is None.

    ``read_state`` never returns a falsy value: it raises. An unguarded call in a
    handler turns a deleted life into a 500 on every poll (the play page polls
    ``GET /runs/{id}`` on a 3s loop), so the SPA can never learn the life is gone.
    Route each store exception to the status the client can act on instead.
    """
    try:
        return store.read_state(run_id), None
    except CorruptRunState:
        return None, web.json_response({"error": "this life is damaged"}, status=422)
    except StoreError:
        return None, web.json_response({"error": "no such life"}, status=404)


async def health(request: web.Request, ctx: AppContext) -> web.Response:
    """Liveness plus a real storage probe.

    Answering 200 proves three things at once that are otherwise diagnosed
    separately: the backend module loaded, the route registry dispatches to it,
    and ``ctx.storage`` was actually populated — which only happens when
    ``permissions.storage`` is declared (apps/context.py: "Only services
    declared in the app's permissions are populated; others are None").
    """
    if request.get("user") is None:
        return _unauthorized()

    storage_ok = False
    storage_error: str | None = None
    if ctx.storage is None:
        storage_error = "ctx.storage is None — permissions.storage not declared"
    else:
        try:
            ctx.storage.set("health.probe", {"ok": True})
            storage_ok = ctx.storage.get("health.probe") == {"ok": True}
            if not storage_ok:
                storage_error = "round-trip mismatch"
        except Exception as exc:  # surfaced, never swallowed
            storage_error = f"{type(exc).__name__}: {exc}"

    return web.json_response(
        {
            "ok": True,
            "app": ctx.name,
            "routeContract": ROUTE_CONTRACT,
            "coreContract": CONTRACT,
            "dataDir": str(ctx.data_dir),
            "storageOk": storage_ok,
            "storageError": storage_error,
            "worlds": _library(ctx).count(),
        }
    )


async def get_settings(request: web.Request, ctx: AppContext) -> web.Response:
    """The narrator settings the player set on the home page (model + effort)."""
    if request.get("user") is None:
        return _unauthorized()
    out = read_settings(ctx.data_dir)
    out["efforts"] = list(REASONING_EFFORTS)
    return web.json_response(out)


async def put_settings(request: web.Request, ctx: AppContext) -> web.Response:
    """Save the narrator settings. Applied to every life's narrator slot at the
    next turn (including one already in progress)."""
    if request.get("user") is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "expected an object"}, status=400)
    raw_model = body.get("model")
    model = raw_model if isinstance(raw_model, str) else ""
    raw_effort = body.get("reasoningEffort")
    effort = raw_effort if isinstance(raw_effort, str) else ""
    raw_painter = body.get("painterModel")
    painter = raw_painter if isinstance(raw_painter, str) else ""
    if effort not in REASONING_EFFORTS:
        return web.json_response(
            {"field": "reasoningEffort", "expected": "a known effort level or empty"},
            status=400,
        )
    raw_styles = body.get("styles")
    styles = [s for s in raw_styles if isinstance(s, str)] if isinstance(raw_styles, list) else None
    raw_cadence = body.get("backdropCadence")
    raw_length = body.get("proseLength")
    # A PUT that omits a knob keeps its saved value rather than resetting it to the
    # default — the settings panel sends everything, but a scripted caller (or an
    # older panel) should not wipe knobs it never heard of.
    prior = read_settings(ctx.data_dir)
    saved = write_settings(
        ctx.data_dir,
        model=model,
        reasoning_effort=effort,
        painter_model=painter,
        backdrops=(
            bool(body["backdrops"])
            if isinstance(body.get("backdrops"), bool)
            else prior["backdrops"]
        ),
        styles=styles if styles is not None else prior["styles"],
        backdrop_cadence=(
            raw_cadence if isinstance(raw_cadence, str) else prior["backdropCadence"]
        ),
        choice_art=(
            bool(body["choiceArt"])
            if isinstance(body.get("choiceArt"), bool)
            else prior["choiceArt"]
        ),
        choice_effects=(
            bool(body["choiceEffects"])
            if isinstance(body.get("choiceEffects"), bool)
            else prior["choiceEffects"]
        ),
        prose_length=raw_length if isinstance(raw_length, str) else prior["proseLength"],
        reduced_motion=(
            bool(body["reducedMotion"])
            if isinstance(body.get("reducedMotion"), bool)
            else prior["reducedMotion"]
        ),
        art_quality=(
            body["artQuality"] if isinstance(body.get("artQuality"), str) else prior["artQuality"]
        ),
    )
    return web.json_response(saved)


async def get_models(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /models`` — the gateway's advertised model list, proxied.

    The core ``/api/models`` route needs the dashboard token. An embedded app
    authenticates by a session cookie PATH-SCOPED to ``/api/apps/<app>/*``, so the
    app frontend's bare ``fetch('/api/models')`` carries no credential there and is
    refused 403 — the model picker then falls back to ``auto`` only. Proxying the
    call through this route (which the app's own cookie IS scoped to) reuses the
    core handler verbatim: kiro-bin resolution, the same sandbox wrap, entitlement
    narrowing, and its 503-on-degraded contract. ``api_models`` reads
    ``request.app["state"]`` and this handler runs on the same gateway app, so the
    request object it receives is exactly what the core route would.

    Imported at call time (like ``chat_runner._run_chat`` above) so exactly one
    thing — the call — depends on the private core handler, not module import.
    """
    if request.get("user") is None:
        return _unauthorized()
    from kiro_crew.dashboard.handlers.agents import api_models  # noqa: PLC0415

    return await api_models(request)


async def list_worlds(request: web.Request, ctx: AppContext) -> web.Response:
    """The Library page.

    Installing seeds happens here rather than at enable time: an app's backend
    hooks run on gateway start, and doing filesystem work there would make a
    slow disk delay the whole gateway. Doing it on first read is idempotent and
    pays the cost where someone is waiting for the answer anyway.
    """
    if request.get("user") is None:
        return _unauthorized()

    library = _library(ctx)
    try:
        seeds = library.ensure_seeds_installed()
    except OSError as exc:
        return web.json_response(
            {"error": "could not prepare the world library", "detail": str(exc)},
            status=500,
        )

    return web.json_response(
        {
            "worlds": library.list_worlds(request.query.get("language") or None),
            "seeds": {
                "installed": seeds.installed,
                "alreadyPresent": seeds.already_present,
                "newerAvailable": seeds.newer_seed_available,
                "failed": seeds.failed,
                # Reported rather than silently omitted: a removed seed-backed world is
                # gone AND recoverable, and the shelf is the only place that can offer
                # the way back.
                "removed": seeds.removed,
            },
        }
    )


async def get_world(request: web.Request, ctx: AppContext) -> web.Response:
    """One world. ``?prose=1`` includes the full rulebook (R1.4)."""
    if request.get("user") is None:
        return _unauthorized()

    world_id = request.match_info.get("world_id", "")
    language = request.query.get("language") or None
    library = _library(ctx)
    try:
        pack = library.read(world_id, language)
    except LibraryError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    detail = world_detail(pack, include_prose=bool(request.query.get("prose")))
    detail["languages"] = library.languages_for(world_id)
    return web.json_response(detail)


def lives_claiming(
    store: RunStore, world_id: str, gateway_state: Any = None
) -> list[dict[str, Any]]:
    """Every life that belongs to this world, and what it would cost to lose it.

    A life names its world in TWO places — its own state and its index row — and
    this matches on either. They normally agree; when they do not, taking only the
    state's word would leave a life no world can ever clean up (a real run reached
    ``worldId: None`` in state while its index row still named the world). A life
    that claims a world by either claim is a life that world is responsible for.

    An unreadable life is included and flagged, not skipped. It cannot say which
    world it belongs to, so its index row is the only claim available — and leaving
    it behind would strand it permanently once its world is gone.
    """
    out: list[dict[str, Any]] = []
    for row in store.read_index():
        run_id = row.get("runId")
        if not isinstance(run_id, str) or not run_id:
            continue
        claims = row.get("worldId") == world_id
        life: dict[str, Any] = {
            "runId": run_id,
            "title": row.get("title") or world_id,
            "turn": int(row.get("turn") or 0),
        }
        try:
            state = store.read_state(run_id)
        except Exception:  # noqa: BLE001 — one damaged life must not block the rest
            life["unreadable"] = True
            if claims:
                out.append(life)
            continue
        if state.get("worldId") == world_id:
            claims = True
        if not claims:
            continue
        life["turn"] = int(state.get("turn") or 0)
        life["subtitle"] = life_subtitle(state)
        life["ended"] = bool(state.get("ended"))
        try:
            life["generating"] = generating(store, run_id, gateway_state) is not None
        except Exception:  # noqa: BLE001
            life["generating"] = False
        out.append(life)
    return out


def _deletion_facts(ctx: AppContext, world_id: str, gateway_state: Any = None) -> dict[str, Any]:
    """What the confirmation must be able to say, gathered once.

    The dialog is not allowed to guess any of this. A confirmation that does not
    name the number of lives it ends is a confirmation of the wrong question.
    """
    library = _library(ctx)
    lives = lives_claiming(_store(ctx), world_id, gateway_state)
    title = world_id
    try:
        title = library.read(world_id).template.title
    except Exception:  # noqa: BLE001 — an unreadable world is still deletable
        pass
    return {
        "worldId": world_id,
        "title": title,
        "lives": lives,
        "liveCount": len(lives),
        "generating": any(life.get("generating") for life in lives),
        # Whether deletion is undoable, and honestly scoped: restoring reinstalls
        # the SEED, so a world the player edited comes back as it shipped.
        "restorable": library.seed_path_for(world_id).is_file(),
        "onShelf": library.path_for(world_id).is_file(),
    }


async def world_deletion(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /worlds/{world_id}/deletion`` — what deleting this world would take."""
    if request.get("user") is None:
        return _unauthorized()
    world_id = request.match_info.get("world_id", "")
    try:
        return web.json_response(_deletion_facts(ctx, world_id, _gateway_state(request)))
    except LibraryError as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def delete_world(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /worlds/{world_id}/delete`` — remove a world and the lives lived in it.

    POST rather than DELETE because the confirmation has to ride a body, and a body
    on DELETE is the kind of thing an intermediary is entitled to drop. A stripped
    body here would turn "delete only if you named the target and the cost" into a
    bare path — the request that must not be possible.

    Two independent guards, protecting two different things:

    ``confirm`` must equal the world id. That protects the ROUTE: a retried fetch,
    a copy-pasted curl, or a future caller that has only a path parameter cannot
    delete anything. It is not the player's safeguard — the dialog is.

    ``lives`` must equal the number this server currently sees. That protects the
    PLAYER: it is the precondition token this codebase already uses for destructive
    edits elsewhere. If a life was begun between the dialog opening and the button
    being pressed, the delete is refused rather than quietly destroying a life the
    dialog never mentioned.

    A month being written blocks the delete. The narrator would commit into a run
    that no longer exists and lose the turn, and "wait for the month being written
    to finish" is a state the player can act on. It cannot deadlock: ``generating``
    ages its own record out (``turn.PENDING_STALE_SECS``).
    """
    if request.get("user") is None:
        return _unauthorized()

    world_id = request.match_info.get("world_id", "")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "expected an object"}, status=400)

    library = _library(ctx)
    try:
        facts = _deletion_facts(ctx, world_id, _gateway_state(request))
    except LibraryError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    if body.get("confirm") != world_id:
        return web.json_response(
            {"field": "confirm", "expected": "the world id, to name the target"},
            status=400,
        )

    expected = body.get("lives")
    if not isinstance(expected, int) or isinstance(expected, bool):
        return web.json_response(
            {"field": "lives", "expected": "how many lives you were shown"}, status=400
        )
    if expected != facts["liveCount"]:
        return web.json_response(
            {
                "error": "the lives in this world changed since you were asked",
                "code": "lives_changed",
                **facts,
            },
            status=409,
        )

    if facts["generating"]:
        return web.json_response(
            {
                "error": "a month is being written in this world right now",
                "code": "turn_in_flight",
                **facts,
            },
            status=409,
        )

    store = _store(ctx)
    _app = getattr(request, "app", None)
    state_obj = _app.get("state") if _app is not None else None

    # All-or-nothing where it can be: delete_run is irreversible and this loop
    # cannot roll back, so every life is pre-flighted BEFORE the first one is
    # destroyed. A world that would fail halfway is refused whole — with all its
    # lives intact — instead of surviving on the shelf minus the lives the loop
    # got through, the exact partial outcome the `lives` precondition promises
    # the player cannot happen.
    undeletable = [
        {"runId": str(life["runId"]), "problem": reason}
        for life in facts["lives"]
        if (reason := store.deletable(str(life["runId"]))) is not None
    ]
    if undeletable:
        return web.json_response(
            {
                "error": "some lives cannot be erased, so nothing was deleted",
                "code": "lives_not_erasable",
                "failed": undeletable,
            },
            status=409,
        )

    failed: list[dict[str, str]] = []
    removed: list[str] = []
    for life in facts["lives"]:
        try:
            store.delete_run(str(life["runId"]))
            removed.append(str(life["runId"]))
            # Release the deleted life's narrator slot and delete its persisted
            # conversation so nothing lingers for a run that no longer exists.
            # Best-effort by design.
            if state_obj is not None:
                release_narrator_slot(state_obj, str(life["runId"]))
                await purge_narrator_session(state_obj, str(life["runId"]))
        except Exception as exc:  # noqa: BLE001
            failed.append({"runId": str(life["runId"]), "problem": str(exc)})

    # The lives go first. A world removed while a life it owns survives leaves a
    # shelf row that can only ever produce "this world could not be read" — and the
    # player has no way left to reach the world that would have cleaned it up.
    if failed:
        # Reachable only by a failure that raced past the pre-flight above —
        # rare, but the destruction already done is real, so say so explicitly
        # rather than letting "the world was kept" read as "nothing happened".
        return web.json_response(
            {
                "error": "some lives could not be erased, so the world was kept",
                "code": "lives_not_erased",
                "partial": True,
                "failed": failed,
                "livesRemoved": removed,
            },
            status=500,
        )

    try:
        library.remove(world_id)
    except (LibraryError, OSError) as exc:
        return web.json_response(
            {
                "error": "the world's file could not be removed",
                "detail": str(exc),
                "livesRemoved": removed,
            },
            status=500,
        )

    return web.json_response(
        {
            "worldId": world_id,
            "livesRemoved": removed,
            "restorable": facts["restorable"],
        }
    )


async def restore_world(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /worlds/{world_id}/restore`` — undo a removal, for a seed-backed world.

    Drops the gravestone; the next read of the Library page reinstalls the seed.
    Brings back the world AS IT SHIPPED — never the player's edits, and never the
    lives, which were erased. Refused when no seed exists, because there would be
    nothing to reinstall and a silent no-op would read as a restore that worked.
    """
    if request.get("user") is None:
        return _unauthorized()

    world_id = request.match_info.get("world_id", "")
    library = _library(ctx)
    try:
        if not library.seed_path_for(world_id).is_file():
            return web.json_response(
                {"error": "no seed to restore this world from", "code": "not_restorable"},
                status=409,
            )
        library.restore(world_id)
    except LibraryError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response(
            {"error": "the removal record could not be updated", "detail": str(exc)},
            status=500,
        )
    return web.json_response({"worldId": world_id, "restored": True})


def _life_deletion_facts(ctx: AppContext, run_id: str, gateway_state: Any = None) -> dict[str, Any]:
    """What ending ONE life would cost, gathered once.

    An unreadable life still answers here. It is the one that most needs to be
    deletable: it cannot be opened, so a play-page-only delete could never reach
    it, and until now nothing could erase it at all.
    """
    store = _store(ctx)
    facts: dict[str, Any] = {"runId": run_id, "turn": 0, "unreadable": False}
    row = next((r for r in store.read_index() if r.get("runId") == run_id), None)
    if row:
        facts["title"] = row.get("title") or ""
        facts["worldId"] = row.get("worldId") or ""
    try:
        state = store.read_state(run_id)
    except Exception:  # noqa: BLE001 — a life too damaged to read is still deletable
        facts["unreadable"] = True
        return facts
    facts["turn"] = int(state.get("turn") or 0)
    facts["subtitle"] = life_subtitle(state)
    facts["ended"] = bool(state.get("ended"))
    facts["worldId"] = state.get("worldId") or facts.get("worldId", "")
    try:
        facts["generating"] = generating(store, run_id, gateway_state) is not None
    except Exception:  # noqa: BLE001
        facts["generating"] = False
    return facts


async def life_deletion(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/deletion`` — what ending this life would take."""
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    if not any(r.get("runId") == run_id for r in store.read_index()):
        return web.json_response({"error": "no such life"}, status=404)
    return web.json_response(_life_deletion_facts(ctx, run_id, _gateway_state(request)))


def _usage_rows_for(run_id: str) -> list[dict[str, Any]]:
    """The narrator conversation's per-turn billing rows, or ``[]``.

    Guarded import: the host only grew a per-turn usage reader recently, so a
    gateway without it serves the perf page with tokens as the proxy instead of
    failing the route. Called without the reader's app-ownership filter: this
    route is already dashboard-user-gated, the slot key is this app's own
    deterministic namespace, and rows written before the host stamped ownership
    carry no app field — filtering would blank exactly the history an audit
    reads.
    """
    try:
        from kiro_crew.dashboard.handlers.usage import slot_turn_usage
    except ImportError:
        return []
    try:
        return slot_turn_usage(narrator_slot_key(run_id))
    except Exception as exc:  # noqa: BLE001 — billing is annotation, never a route failure
        logger.debug("per-turn usage read failed for %s: %s", run_id, exc)
        return []


async def life_perf(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/perf`` — the audit page's data: what each turn cost.

    One aggregated row per committed turn since the ledger existed (older turns
    are left out rather than shown half-empty): story latency (ask → commit),
    the narrator's read time, tool-call count, declaration form and size, art
    latency joined from the backdrop timeline, the context meter after the
    turn, and any conversation rotation with its reason. Real per-turn credits
    join from the host's usage ledger when the gateway exposes one;
    ``creditNote`` tells the page which currency it is looking at, so tokens
    are only ever presented as the proxy they are.
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    if not any(r.get("runId") == run_id for r in store.read_index()):
        return web.json_response({"error": "no such life"}, status=404)
    rows = TurnPerf(ctx.data_dir, run_id).rows()
    timeline = BackdropTimeline(ctx.data_dir, run_id)
    events = timeline.events()
    turns = join_usage(perf_aggregate(rows, events), _usage_rows_for(run_id))
    has_credits = any("credits" in t for t in turns)
    return web.json_response(
        {
            "runId": run_id,
            "turns": turns,
            "creditNote": "credits" if has_credits else "tokens-not-credits",
        }
    )


async def reset_life_conversation(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs/{run_id}/reset-conversation`` — a fresh storyteller, same story.

    The player-facing "重开叙事" control: discards the narrator's accumulated
    conversation (its context, its drift, its habits) while keeping every fact of
    the life — state, chronicle, memory graph, backdrops all stay. The next turn
    cold-starts a new conversation and re-delivers the world's rulebook.

    ``confirm`` must equal the run id, same as the delete route and for the same
    reason: it protects the ROUTE from a retried fetch. A month being written
    blocks it — discarding the writer's session mid-commit would lose the turn.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "expected an object"}, status=400)

    store = _store(ctx)
    if not any(r.get("runId") == run_id for r in store.read_index()):
        return web.json_response({"error": "no such life"}, status=404)

    if body.get("confirm") != run_id:
        return web.json_response(
            {"field": "confirm", "expected": "the run id, to name the target"},
            status=400,
        )

    facts = _life_deletion_facts(ctx, run_id, _gateway_state(request))
    if facts.get("generating"):
        return web.json_response(
            {
                "error": "a month is being written for this life right now",
                "code": "turn_in_flight",
                **facts,
            },
            status=409,
        )

    state_obj = _gateway_state(request)
    if state_obj is None:
        return web.json_response({"error": "gateway state unavailable"}, status=503)

    done = await reset_narrator_conversation(state_obj, store, run_id)
    return web.json_response({"runId": run_id, "reset": bool(done)})


async def delete_life(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs/{run_id}/delete`` — erase ONE life, leaving its world alone.

    The companion to deleting a world, and the only way to reach two lives the
    world-level delete cannot help with: one the player wants gone while keeping the
    world, and one too damaged to open (which no play-page control could offer,
    because opening it is exactly what fails).

    Same two guards as the world delete, protecting the same two different things.
    ``confirm`` must equal the run id — that protects the ROUTE from a retried fetch
    or a caller holding only a path parameter. ``turn`` must equal the month this
    life is actually on — that protects the PLAYER, because a life that advanced
    while the dialog was open holds more story than the dialog described. A settled
    life does not advance on its own, so this fires almost only when something real
    happened.

    A month being written blocks it, for the same reason: the narrator would commit
    into a run that no longer exists and lose the turn.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "expected an object"}, status=400)

    store = _store(ctx)
    if not any(r.get("runId") == run_id for r in store.read_index()):
        return web.json_response({"error": "no such life"}, status=404)

    facts = _life_deletion_facts(ctx, run_id, _gateway_state(request))

    if body.get("confirm") != run_id:
        return web.json_response(
            {"field": "confirm", "expected": "the run id, to name the target"},
            status=400,
        )

    expected = body.get("turn")
    if not isinstance(expected, int) or isinstance(expected, bool):
        return web.json_response(
            {"field": "turn", "expected": "the month you were shown"}, status=400
        )
    if expected != facts["turn"]:
        return web.json_response(
            {
                "error": "this life moved on since you were asked",
                "code": "turn_changed",
                **facts,
            },
            status=409,
        )

    if facts.get("generating"):
        return web.json_response(
            {
                "error": "a month is being written for this life right now",
                "code": "turn_in_flight",
                **facts,
            },
            status=409,
        )

    try:
        store.delete_run(run_id)
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this life could not be erased", "detail": str(exc)}, status=500
        )

    # Release the narrator slot and delete its persisted conversation so a deleted
    # life leaves nothing behind — in memory or on disk.
    _app = getattr(request, "app", None)
    state_obj = _app.get("state") if _app is not None else None
    if state_obj is not None:
        release_narrator_slot(state_obj, run_id)
        await purge_narrator_session(state_obj, run_id)

    return web.json_response({"runId": run_id, "deleted": True, "turn": facts["turn"]})


#: A player-chosen life name is a shelf label, not a story: long enough to tell two
#: lives apart, short enough to sit on the rail.
LIFE_LABEL_MAX = 60


async def set_life_meta(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs/{run_id}/meta`` — a player's own name and shelf state for a life.

    Metadata only: a custom ``label`` (shown instead of the answer-derived subtitle)
    and ``archived`` (folded out of the active shelf). It never touches the life's
    state or chronicle, and it deliberately does not bump ``lastPlayed`` — renaming
    a life is not playing it. Send ``label: ""`` to clear a custom name and fall
    back to the derived subtitle.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "expected an object"}, status=400)

    changes: dict[str, Any] = {}
    if "label" in body:
        label = body.get("label")
        if not isinstance(label, str):
            return web.json_response(
                {"field": "label", "expected": 'a name, or "" to clear it'}, status=400
            )
        changes["label"] = label.strip()[:LIFE_LABEL_MAX]
    if "archived" in body:
        changes["archived"] = bool(body.get("archived"))

    if not changes:
        return web.json_response(
            {"error": "nothing to change", "expected": "label and/or archived"},
            status=400,
        )

    if not _store(ctx).patch_index(run_id, changes):
        return web.json_response({"error": "no such life"}, status=404)

    return web.json_response({"runId": run_id, **changes})


async def advance_run_turn(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs/{run_id}/turn`` — ask the world for the next span of this life.

    Idempotent per ``(runId, turn)``: pass the turn you believe is next and a
    retry returns the same month instead of narrating a second one. Omit it and
    the server uses ``current + 1``.

    The chat runner is imported HERE rather than in ``turn.py`` so exactly one
    module depends on gateway internals. ``issue_radar`` and ``spec_builder``
    both reach for the same import, so it is an established path for an app
    backend even though the name is private.
    """
    if request.get("user") is None:
        return _unauthorized()

    state_obj = request.app.get("state")
    if state_obj is None:
        return web.json_response({"error": "no chat runtime"}, status=503)

    run_id = request.match_info.get("run_id", "")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    action = str(body.get("action") or "")[:500]  # R4.5
    style = str(body.get("style") or "")[:64]
    wanted = body.get("turn")

    store = _store(ctx)

    # State first: a missing/damaged life must answer 404/422 here, not surface
    # as a 500 out of `already_committed`'s chronicle scan below.
    run_state, err = _load_run_state(store, run_id)
    if err is not None or run_state is None:
        return err or web.json_response({"error": "no such life"}, status=404)

    if _backdrop_is_pending(ctx, store, run_id, run_state):
        _cfg = read_settings(ctx.data_dir)
        _ensure_backdrop_recovery(ctx, store, state_obj, run_id, _cfg)
        return web.json_response(
            {
                "advanced": False,
                "turn": int(run_state.get("turn") or 0),
                "reason": "generating",
            }
        )

    if isinstance(wanted, int) and not isinstance(wanted, bool):
        done = already_committed(store, run_id, wanted)
        if done is not None:
            return web.json_response(
                {
                    "advanced": False,
                    "turn": wanted,
                    "reason": "already",
                    "prose": done.get("prose", ""),
                    "choices": done.get("choices") or [],
                }
            )

    world_id = run_state.get("worldId")
    if not isinstance(world_id, str) or not world_id:
        return web.json_response({"error": "this life has no world"}, status=422)

    try:
        pack = _library(ctx).read(world_id, run_state.get("language"))
    except (LibraryError, Exception) as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    # A life that has reached an ending is over: refuse to narrate another month
    # and answer with a stable, machine-readable reason so a repeated tap lands on
    # the same terminal page instead of quietly resurrecting the life.
    ending_id = resolve_ending(pack.template, run_state)
    if ending_id:
        return web.json_response(
            {
                "advanced": False,
                "turn": int(run_state.get("turn") or 0),
                "reason": "ended",
                "endingId": ending_id,
                "state": run_state,
            }
        )

    from kiro_crew.dashboard.chat_runner import _run_chat  # noqa: PLC0415

    _cfg = read_settings(ctx.data_dir)
    # Did the LAST committed turn open a chapter? That is the narratively clean
    # point for a planned conversation rotation (turn.py decides; this is only the
    # observation). Compared against the rollback copy, same as the play view's
    # "unlocked" toast; empty prev (a life's first months) never reads as crossed.
    _prev = store.read_prev(run_id)
    chapter_crossed = bool(_prev) and bool(opened_since(pack.template, _prev, run_state))
    outcome = await advance_turn(
        state_obj=state_obj,
        store=store,
        run_id=run_id,
        rulebook=world_brief(pack.template),
        dispatch=make_dispatcher(_run_chat),
        action=action,
        style=style,
        shape=declaration_shape(pack.template),
        language=pack.template.language,
        project=str(ctx.data_dir / "runs" / run_id),
        model=_cfg["model"],
        reasoning_effort=_cfg["reasoningEffort"],
        chapter_crossed=chapter_crossed,
        prose_length=_cfg["proseLength"],
        backdrops_enabled=bool(_cfg["backdrops"]),
    )

    # The prose may be committed, but requested art is the other half of this page.
    # Recover it while GET keeps publishing the previous page.
    if outcome.advanced:
        _ensure_backdrop_recovery(ctx, store, state_obj, run_id, _cfg)

    withheld = outcome.advanced and _backdrop_is_pending(ctx, store, run_id)
    visible_state = (
        store.read_prev(run_id) or store.read_state(run_id)
        if withheld
        else store.read_state(run_id)
    )
    return web.json_response(
        {
            # `advanced` remains true so the initiating client clears its submitted
            # action; the page bytes themselves remain withheld until GET publishes.
            "advanced": outcome.advanced,
            "turn": outcome.turn,
            "reason": outcome.reason,
            "prose": "" if withheld else outcome.prose,
            "state": visible_state,
            "scenes": (
                SceneLedger(ctx.data_dir, run_id).mounted()
                if outcome.advanced and not withheld
                else []
            ),
        }
    )


async def create_run(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs`` — begin a life.

    The run is written to disk BEFORE its opening turn is asked for, so a
    narrator that fails or times out leaves a life waiting to be retried rather
    than nothing at all (R2.9). Everything the player chose is already saved at
    that point; only the first turn is missing.
    """
    if request.get("user") is None:
        return _unauthorized()

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "expected an object"}, status=400)

    store = _store(ctx)
    world_id = body.get("worldId")
    raw_answers = body.get("answers")
    if raw_answers is not None and not isinstance(raw_answers, dict):
        # Silently coercing this to {} turned "the player chose" into "the world
        # decides everything" with no signal — the one drop the fail-soft rule
        # says must be loud, because it is the player's own input.
        return web.json_response({"field": "answers", "expected": "an object"}, status=422)
    answers = raw_answers if isinstance(raw_answers, dict) else {}
    style = str(body.get("style") or "")
    role = str(body.get("role") or "")
    language = body.get("language") if isinstance(body.get("language"), str) else None

    # "Live this again": copy a prior life's opening as the starting point. Only the
    # player's own picks carry over — groups the world decides (including random
    # ones) are stored as null and dropped here, so the world still rolls those
    # afresh rather than the copy handing the player what the world reserved.
    from_run = body.get("fromRunId")
    if isinstance(from_run, str) and from_run:
        try:
            src = store.read_state(from_run)
        except Exception:  # noqa: BLE001
            src = {}
        if not (isinstance(world_id, str) and world_id):
            src_world = src.get("worldId")
            if isinstance(src_world, str):
                world_id = src_world
        if not answers:
            src_opening = src.get("opening")
            if isinstance(src_opening, dict):
                answers = {k: v for k, v in src_opening.items() if isinstance(v, str) and v.strip()}
        if not style:
            style = str(src.get("style") or "")
        if not role:
            role = str(src.get("role") or "")
        if not language:
            src_lang = src.get("language")
            if isinstance(src_lang, str) and src_lang:
                language = src_lang

    if not isinstance(world_id, str) or not world_id:
        return web.json_response({"field": "worldId", "expected": "a world"}, status=400)

    library = _library(ctx)
    if language:
        available = library.languages_for(world_id)
        if available and language not in available:
            return web.json_response(
                {"field": "language", "expected": "a language this world offers"},
                status=400,
            )
    try:
        pack = library.read(world_id, language)
    except LibraryError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    try:
        state = build_initial_state(pack.template, answers, style=style, role=role)
    except OpeningError as exc:
        return web.json_response({"field": exc.field, "expected": exc.expected}, status=400)

    # The legacy bridge (design §9): carry a finished life's chosen inheritance
    # into this one. Validated BEFORE the run exists, so a refused bridge
    # leaves nothing behind. Three gates, in order of who owns the rule: the
    # WORLD must declare continuity (template.lineage), the source life must be
    # over (终章 confirmation is the ending page this request came from), and
    # both lives must be of the same world — an heirloom cannot cross worlds.
    legacy_body = body.get("legacy")
    bridge_entry = None
    if isinstance(legacy_body, dict):
        from legacy import LegacyError, build_bridge_record
        from memory_graph import build_index as _build_graph_index

        if not pack.template.lineage:
            return web.json_response(
                {
                    "field": "legacy",
                    "expected": "a world that declares lineage",
                    "code": "world_without_lineage",
                },
                status=422,
            )
        src_run = str(legacy_body.get("fromRunId") or "")
        try:
            src_state = store.read_state(src_run)
        except Exception:  # noqa: BLE001
            return web.json_response(
                {"field": "legacy.fromRunId", "expected": "a life that exists"},
                status=404,
            )
        if not (resolve_ending(pack.template, src_state) or src_state.get("ended")):
            # The same "is this life over" the ending page uses: a world-declared
            # ending (state.alive == false) carries no narrator flag, and both
            # lives share one world, so the already-loaded pack judges it.
            return web.json_response(
                {
                    "field": "legacy.fromRunId",
                    "expected": "a finished life — inheritance is settled at the ending",
                    "code": "not_ended",
                },
                status=409,
            )
        if src_state.get("worldId") != world_id:
            return web.json_response(
                {"field": "legacy.fromRunId", "expected": "a life of the same world"},
                status=422,
            )
        try:
            bridge_entry = build_bridge_record(
                _build_graph_index(store.read_chronicle(src_run)),
                source_run_id=src_run,
                selected=[str(s) for s in legacy_body.get("selected") or []],
                language=str(state.get("language") or "en"),
            )
        except LegacyError as exc:
            return web.json_response(
                {"field": f"legacy.{exc.field}", "expected": exc.expected}, status=422
            )

    run_id = store.create_run(
        state,
        {
            "runId": "",  # filled by the store
            "worldId": world_id,
            "title": pack.template.title,
            "style": state["style"],
            "turn": 0,
        },
    )
    if bridge_entry is not None:
        # The bridge is the new life's FIRST canonical record — the same form
        # every narrated turn uses, so the graph stays rebuildable from the
        # chronicle alone and dies with the run directory (§9 + Phase 0).
        store.append_turn(run_id, bridge_entry)
    return web.json_response({"runId": run_id, "state": store.read_state(run_id)}, status=201)


async def open_run(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs/{run_id}/open`` — ask for the first turn, or retry it.

    Separate from ``create_run`` on purpose: the run already exists, so this is
    retryable as many times as it takes without ever producing a second life.
    """
    if request.get("user") is None:
        return _unauthorized()

    state_obj = request.app.get("state")
    if state_obj is None:
        return web.json_response({"error": "no chat runtime"}, status=503)

    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    run_state, err = _load_run_state(store, run_id)
    if err is not None or run_state is None:
        return err or web.json_response({"error": "no such life"}, status=404)

    if int(run_state.get("turn") or 0) >= 1:
        # Already opened. A retry after a slow success must not narrate a second
        # first turn. Answer with the entry FOR the committed turn: a legacy
        # life's chronicle starts with the turn-0 bridge record (empty prose),
        # so ``chronicle[0]`` handed a retried opening a blank first month.
        wanted = int(run_state["turn"])
        chronicle = store.read_chronicle(run_id)
        entry = next(
            (e for e in reversed(chronicle) if int(e.get("turn") or 0) == wanted),
            {},
        )
        return web.json_response(
            {
                "advanced": False,
                "reason": "already",
                "turn": wanted,
                "prose": entry.get("prose", ""),
                "state": run_state,
            }
        )

    world_id = run_state.get("worldId")
    if not isinstance(world_id, str) or not world_id:
        return web.json_response({"error": "this life has no world"}, status=422)
    try:
        pack = _library(ctx).read(world_id, run_state.get("language"))
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    from kiro_crew.dashboard.chat_runner import _run_chat  # noqa: PLC0415

    prompt = compose_opening_prompt(template=pack.template, run_id=run_id)
    _cfg = read_settings(ctx.data_dir)
    outcome = await advance_turn(
        state_obj=state_obj,
        store=store,
        run_id=run_id,
        rulebook=world_brief(pack.template),
        dispatch=make_dispatcher(_run_chat),
        style=str(run_state.get("style") or ""),
        project=str(ctx.data_dir / "runs" / run_id),
        prompt_override=prompt,
        model=_cfg["model"],
        reasoning_effort=_cfg["reasoningEffort"],
        budget_secs=OPENING_DEADLINE_SECS,
    )
    if outcome.advanced:
        _ensure_backdrop_recovery(ctx, store, state_obj, run_id, _cfg)
    withheld = outcome.advanced and _backdrop_is_pending(ctx, store, run_id)
    visible_state = (
        store.read_prev(run_id) or store.read_state(run_id)
        if withheld
        else store.read_state(run_id)
    )
    return web.json_response(
        {
            "advanced": outcome.advanced,
            "turn": outcome.turn,
            "reason": outcome.reason,
            "prose": "" if withheld else outcome.prose,
            "state": visible_state,
            # A failed opening leaves the run retryable rather than half-created.
            "retryable": not outcome.advanced,
            "generating": outcome.reason in ("generating", "writing"),
        }
    )


def life_subtitle(state: dict[str, Any]) -> str:
    """What tells this life apart from another in the same world.

    The shelf and the rail were listing four lives with one name: the WORLD's title,
    repeated, three of them also reading "turn 1". Nothing on screen said which life
    was which, so choosing between them was guesswork.

    Built from the player's own opening answers rather than from the narrated state.
    Those answers exist for every world, are chosen per life, and are the player's
    words — so this needs no cooperation from the narrator and no field name this app
    invented. Reading a "name" or "identity" key out of the state instead would be
    the app deciding which of a world's own fields counts as identity, which is the
    world's business, and would silently produce nothing for a world that has no such
    field.

    Returns "" when the life has nothing to distinguish it yet — a caller shows the
    world's title alone rather than an empty line pretending to be a subtitle.
    """
    opening = state.get("opening")
    if not isinstance(opening, dict):
        return ""
    parts: list[str] = []
    for value in opening.values():
        if isinstance(value, (str, int, float)) and str(value).strip():
            parts.append(str(value).strip())
    if not parts:
        return ""
    # A subtitle, not a summary: enough to tell two lives apart at a glance, and
    # short enough to sit on one line of a 248px rail.
    return SUBTITLE_JOIN.join(parts[:SUBTITLE_PARTS])


#: How many opening answers a subtitle carries, and what separates them. Both are
#: presentation, not content: the answers themselves are already in the player's own
#: language because the player picked them from the world's own options.
SUBTITLE_PARTS = 3
SUBTITLE_JOIN = " · "


async def list_runs(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs`` — the lives in progress (R8).

    Turn and status are read from each life's own state rather than from the
    index. The index is a listing cache written when a life begins; the state is
    what the narrator actually commits. Trusting the cache would show a life as
    still unborn hours after it started, and a listing that disagrees with the
    thing it lists is worse than a slower listing — these are a handful of files,
    not a table.
    """
    if request.get("user") is None:
        return _unauthorized()

    store = _store(ctx)
    rows: list[dict[str, Any]] = []
    for row in store.read_index():
        run_id = row.get("runId")
        if not isinstance(run_id, str) or not run_id:
            continue
        live = {**row}
        try:
            state = store.read_state(run_id)
        except Exception:  # noqa: BLE001 — one damaged life must not hide the rest
            live["unreadable"] = True
            rows.append(live)
            continue
        live["turn"] = int(state.get("turn") or 0)
        live["awaitingOpening"] = state.get("status") == "awaiting-opening" and live["turn"] == 0
        live["ended"] = bool(state.get("ended"))
        live["subtitle"] = life_subtitle(state)
        rows.append(live)

    for row in rows:
        rid = row.get("runId")
        if isinstance(rid, str) and rid:
            try:
                row["generating"] = generating(store, rid, _gateway_state(request)) is not None
            except Exception:  # noqa: BLE001 — a broken row must not blank the shelf
                row["generating"] = False
            # The life's backdrop version, so the shelf card can show the same
            # background the play page does. Its own try/except: a missing or
            # damaged backdrop leaves the card plain, never blanks the shelf.
            try:
                bd = BackdropStore(ctx.data_dir, rid).current()
                row["backdrop"] = {"version": bd["version"]} if bd else None
            except Exception:  # noqa: BLE001
                row["backdrop"] = None
    rows.sort(key=lambda r: r.get("lastPlayed") or 0, reverse=True)
    return web.json_response({"runs": rows})


async def get_run(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}`` — the play page, resolved.

    Panel visibility and field lookup happen here, not in the UI: the ``when``
    interpreter is a parser over untrusted template text and there must be
    exactly one of it.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    state, err = _load_run_state(store, run_id)
    if err is not None or state is None:
        return err or web.json_response({"error": "no such life"}, status=404)

    committed_state = state
    generation = generating(store, run_id, _gateway_state(request))
    art_pending = _backdrop_is_pending(ctx, store, run_id, committed_state)
    if art_pending:
        _ensure_backdrop_recovery(
            ctx, store, _gateway_state(request), run_id, read_settings(ctx.data_dir)
        )
        previous = store.read_prev(run_id)
        if previous is not None:
            state = previous

    world_id = state.get("worldId")
    if not isinstance(world_id, str) or not world_id:
        return web.json_response({"error": "this life has no world"}, status=422)
    try:
        pack = _library(ctx).read(world_id, state.get("language"))
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    # Chapters the world opened on the last committed month, in its own headings.
    # Compared against the prior state so "open since birth" is not reported; empty
    # on a life's first month (no prior state).
    prev = None if art_pending else store.read_prev(run_id)
    unlocked: list[str] = []
    if prev:
        headings = {c.id: c.heading for c in pack.template.chapters}
        unlocked = [headings[i] for i in opened_since(pack.template, prev, state) if i in headings]

    # Milestones: ids reached live in run state; map to the world's labels. `reached`
    # is only those new since the prior committed month (for a toast); `all` is every
    # one reached so far (for the ending recap).
    mile_by_id = {m.id: m.label for m in pack.template.milestones}
    reached_ids = [i for i in (state.get("milestones") or []) if isinstance(i, str)]
    prev_reached = {
        i for i in ((prev.get("milestones") or []) if prev else []) if isinstance(i, str)
    }
    milestones_all = [mile_by_id[i] for i in reached_ids if i in mile_by_id]
    milestones_reached = [
        mile_by_id[i] for i in reached_ids if i in mile_by_id and i not in prev_reached
    ]

    view = build_play_view(
        pack.template,
        state,
        chronicle=[
            entry
            for entry in store.read_chronicle(run_id)
            if int(entry.get("turn") or 0) <= int(state.get("turn") or 0)
        ],
        # New scenes may already have been mounted by the hidden page. Do not leak
        # them over the previous prose; an existing client keeps its current frames,
        # and a returning client sees none until the new page publishes.
        scenes=[] if art_pending else SceneLedger(ctx.data_dir, run_id).mounted(),
        unlocked=unlocked,
        milestones_reached=milestones_reached,
        milestones=milestones_all,
        capability_packs=pack.capability_packs,
    )
    view["runId"] = run_id
    view["worldId"] = world_id
    view["title"] = pack.template.title
    view["language"] = pack.template.language
    # What a returning player is owed: leaving the page while a turn was being
    # written used to look identical to never having asked for it.
    view["generating"] = generation
    # The current background, if the narrator has set one. The frontend loads the
    # compiled HTML into a scriptless, behind-text sandbox frame; `version` is the
    # cache-buster so a replaced background actually swaps.
    try:
        # Pinned to the COMMITTED turn, never `current()`: the narrator stores the
        # next page's backdrop mid-generation (tagged with the pending turn), and
        # the play page polls every 3s while it works — `current()` here would
        # swap the background out from under the page the player is still
        # reading. `at(N)` only sees backdrops tagged turn <= N, so the new art
        # appears exactly when the new page does.
        backdrop = BackdropStore(ctx.data_dir, run_id).at(int(view["turn"] or 0))
    except BackdropError:
        backdrop = None
    view["backdrop"] = (
        {
            "version": backdrop["version"],
            "buttons": bool(backdrop.get("buttons")),
            "mobile": bool(backdrop.get("mobile")),
            "trace": backdrop.get("trace"),
        }
        if backdrop
        else None
    )
    view["awaitingOpening"] = state.get("status") == "awaiting-opening" and view["turn"] == 0
    return web.json_response(view)


async def get_scene(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/scenes/{scene_id}`` — one compiled scene document.

    The page loads this ``text/html`` response through a sandboxed iframe ``src``
    rather than ``srcdoc`` (which blank-rendered in WebKit / iOS WKWebView). The
    iframe omits ``allow-same-origin``, and the response repeats that boundary with
    a CSP ``sandbox`` directive. The response-level directive matters independently:
    unlike a meta CSP or iframe attribute, it also gives a directly navigated scene
    an opaque origin. ``frame-ancestors 'self'`` still lets the dashboard embed the
    document while refusing framing by another origin.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    scene_id = request.match_info.get("scene_id", "")

    store = _store(ctx)
    state, err = _load_run_state(store, run_id)
    if err is not None or state is None:
        return err or web.json_response({"error": "no such life"}, status=404)

    ledger = SceneLedger(ctx.data_dir, run_id)
    try:
        mounted = {m["sceneId"] for m in ledger.mounted()}
    except SceneLedgerError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    if scene_id not in mounted:
        return web.json_response({"error": "no such scene"}, status=404)

    # Read the spec and nonce under the same error contract as the mounted
    # check: a scene dismissed or remounted between that check and here raises
    # SceneLedgerError, which must answer as "gone" rather than escape as a 500.
    try:
        spec = ledger.spec(scene_id)
        nonce = ledger.nonce(scene_id)
    except SceneLedgerError:
        return web.json_response({"error": "no such scene"}, status=404)
    try:
        html_text, cached = compile_cached(
            ctx.data_dir,
            run_id,
            scene_id,
            spec,
            state,
            bound_slice=bound_values(spec, state),
            nonce=nonce,
        )
    except SceneSpecError as exc:
        # Named field, no partial mount: the page shows nothing rather than half
        # a scene, and the narrator is told which field to fix on its next turn.
        return web.json_response({"field": exc.field, "expected": exc.expected}, status=422)

    return web.Response(
        text=html_text,
        content_type="text/html",
        charset="utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                f"{CSP}; sandbox allow-scripts allow-forms; frame-ancestors 'self'"
            ),
            "Cross-Origin-Resource-Policy": "same-origin",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
            "X-Scene-Cached": "1" if cached else "0",
        },
    )


async def get_backdrop(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/backdrop`` — the current background, as an SVG image.

    Served as ``image/svg+xml`` so the play page shows it in a plain ``<img>``. An
    SVG in an image context runs no script and fetches nothing external, so the
    narrator's markup is inert without needing a sandbox — and an image renders and
    sizes reliably on iOS, unlike the sandboxed srcdoc iframe this replaced.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    _state, err = _load_run_state(store, run_id)
    if err is not None:
        return err

    try:
        bstore = BackdropStore(ctx.data_dir, run_id)
        # ``?turn=N`` restores the background effective on that page (re-reading the
        # history); default is the latest, which is what the live page and home want.
        turn_q = request.query.get("turn")
        if turn_q is not None and turn_q.isdigit():
            current = bstore.at(int(turn_q))
        else:
            current = bstore.current()
    except BackdropError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    if current is None:
        return web.json_response({"error": "no backdrop"}, status=404)

    # ``?part=buttons`` serves the orientation-agnostic choice-button motif. For
    # the full-page image, ``?variant=mobile`` selects the coordinated portrait
    # composition and falls back to desktop for legacy single-image entries.
    part = request.query.get("part")
    variant = request.query.get("variant")
    if part == "buttons":
        source = current.get("buttons")
    elif variant == "mobile":
        source = current.get("mobile") or current.get("markup")
    else:
        source = current.get("markup")
    if not source:
        return web.json_response({"error": "not set"}, status=404)

    try:
        svg = compile_backdrop(source)
    except BackdropError as exc:
        # A stored SVG that no longer validates (e.g. an older HTML one from before
        # the SVG-image model): refuse rather than serve it, and the page simply
        # shows no background.
        return web.json_response({"error": str(exc)}, status=422)

    return web.Response(
        text=svg,
        content_type="image/svg+xml",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


async def answer_scene(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs/{run_id}/scenes/{scene_id}/answer`` — the result channel.

    The page does the cheap checks so obvious noise never leaves the browser
    (``source``, ``origin === "null"``, message shape), but every rule that
    decides whether a WRITE happens is enforced here. A validation that lives only
    in the page is a validation a page can be made to skip.

    Four ways in and one way through:

    * the scene must be mounted
    * the nonce must match this mount — a click aimed at a replaced scene is stale
    * the choice must be one the spec itself offered — a scene's answers are a
      closed set, and free text has its own path with its own limits
    * first result only — a second answer never overwrites the first, because the
      narrator may already have acted on it

    Every rejection writes a failure record and no state.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    scene_id = request.match_info.get("scene_id", "")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    try:
        ledger = SceneLedger(ctx.data_dir, run_id)
    except SceneLedgerError as exc:
        # A malformed run id fails the ledger's own id check; that is a client
        # error, not a crash (the sibling scene routes already answer this way).
        return web.json_response({"accepted": False, "reason": str(exc)}, status=404)

    def refuse(reason: str, status: int = 422) -> web.Response:
        try:
            ledger.record_failure(scene_id, reason)
        except SceneLedgerError:
            pass  # the scene is gone; there is nothing to attach a record to
        return web.json_response({"accepted": False, "reason": reason}, status=status)

    try:
        mounted = {m["sceneId"] for m in ledger.mounted()}
    except SceneLedgerError as exc:
        return web.json_response({"accepted": False, "reason": str(exc)}, status=422)
    if scene_id not in mounted:
        return web.json_response({"accepted": False, "reason": "no such scene"}, status=404)

    nonce = body.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return refuse("no mount identity")

    choice = body.get("choice")
    if not isinstance(choice, str) or not choice or len(choice) > 64:
        return refuse("not a choice this scene offered")

    spec = ledger.spec(scene_id)
    offered = {
        el.get("id"): el.get("label")
        for el in (spec.get("elements") or [])
        if isinstance(el, dict) and el.get("kind") == "choice"
    }
    if choice not in offered:
        return refuse("not a choice this scene offered")

    try:
        ledger.record_answer(scene_id, choice, nonce=nonce)
    except StaleScene:
        return refuse("aimed at a scene that is gone")
    except AlreadyAnswered:
        return refuse("already answered")
    except SceneLedgerError as exc:
        return refuse(str(exc))

    # The label, not the id: it is what the player actually read, and it is what
    # the narrator should receive as the action taken.
    return web.json_response({"accepted": True, "action": offered.get(choice) or choice})


async def get_chronicle(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/chronicle`` — the months already lived (R8).

    A separate route rather than a field on the play view, because the two have
    opposite shapes. The play view is read on every poll while a month is being
    written and must stay small; the chronicle is read when the player deliberately
    looks back, and by then a long life is a hundred turns of prose. Folding it into
    the play view would make every poll carry the whole life.

    Newest first, and paged from the newest end, because that is the direction a
    player reads backwards in: "what just happened", then further.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    try:
        store.read_state(run_id)
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "no such life"}, status=404)

    entries = store.read_chronicle(run_id)
    if _backdrop_is_pending(ctx, store, run_id):
        visible_turn = max(0, int(store.read_state(run_id).get("turn") or 0) - 1)
        entries = [e for e in entries if int(e.get("turn") or 0) <= visible_turn]
    # Turn 0 is the app's own record (the legacy bridge, design §9), not a page
    # of the story: it has no prose and nobody lived it. The star map still
    # shows the inheritance — through the graph, where it belongs.
    entries = [e for e in entries if int(e.get("turn") or 0) >= 1]

    # Full-text filter across the whole life, applied before paging so "when did I
    # meet the smith" pages through matches rather than raw months. Case-insensitive
    # over prose, the player's action, and the marked events.
    q = request.query.get("q", "").strip().lower()
    if q:

        def _hit(e: dict[str, Any]) -> bool:
            hay = " ".join(
                [
                    str(e.get("prose") or ""),
                    str(e.get("action") or ""),
                    " ".join(str(x) for x in (e.get("events") or [])),
                ]
            ).lower()
            return q in hay

        entries = [e for e in entries if _hit(e)]

    # `before` is a turn NUMBER, not an offset: an offset would shift under a turn
    # committed between two pages and silently skip or repeat a month.
    before = _int_param(request, "before", default=0)
    if before > 0:
        entries = [e for e in entries if int(e.get("turn") or 0) < before]

    limit = max(1, min(_int_param(request, "limit", default=CHRONICLE_PAGE), 100))
    page = list(reversed(entries))[:limit]

    # Each page carries the backdrop that was effective ON that turn, so re-reading
    # the history restores the scene each page had rather than only the latest.
    bstore = BackdropStore(ctx.data_dir, run_id)

    def _bd(turn: int) -> dict[str, Any] | None:
        backdrop = bstore.at(turn)
        return (
            {
                "version": backdrop["version"],
                "mobile": bool(backdrop.get("mobile")),
                "trace": backdrop.get("trace"),
            }
            if backdrop
            else None
        )

    return web.json_response(
        {
            "runId": run_id,
            "turns": [
                {
                    "turn": int(e.get("turn") or 0),
                    "prose": str(e.get("prose") or ""),
                    # What the player chose, so a re-read shows the fork and not only
                    # the outcome. Absent on turns nobody chose from.
                    "action": str(e.get("action") or ""),
                    # What the month marked notable, and what it credited a gain to.
                    # Already stored on every turn (they drive the anti-halo readings);
                    # surfaced here so the player can read a life as a timeline of events
                    # rather than only as pages of prose.
                    "events": [
                        str(x) for x in (e.get("events") or []) if isinstance(x, str) and x.strip()
                    ][:12],
                    # The standing that month ended on, snapshotted at commit, so a page
                    # being re-read shows its own situation. Omitted on turns committed
                    # before this was recorded — the page falls back to the live panels
                    # rather than showing an empty frame.
                    **(
                        {"digest": e["digest"]}
                        if isinstance(e.get("digest"), list) and e["digest"]
                        else {}
                    ),
                    **(
                        {"panels": e["panels"]}
                        if isinstance(e.get("panels"), list) and e["panels"]
                        else {}
                    ),
                    "gains": [
                        {
                            "field": str(g.get("field") or ""),
                            "amount": str(g.get("amount") or ""),
                            "source": str(g.get("source") or ""),
                        }
                        for g in (e.get("gains") or [])
                        if isinstance(g, dict) and g.get("field")
                    ][:12],
                    # The scene this page had, so the history reader can restore it.
                    "backdrop": _bd(int(e.get("turn") or 0)),
                }
                for e in page
            ],
            # Whether reading further back is possible, so the UI offers "more" only
            # when there is more rather than on every page.
            "more": bool(page)
            and any(int(e.get("turn") or 0) < int(page[-1].get("turn") or 0) for e in entries),
        }
    )


#: How many months one read of the chronicle returns. Enough to re-read the recent
#: past in one go, small enough that opening the history is not a download.
CHRONICLE_PAGE = 12


def _int_param(request: web.Request, name: str, *, default: int) -> int:
    """A query integer, defaulting rather than failing on nonsense.

    A malformed ``?limit=abc`` from a stale bookmark should show the player their
    history, not an error about a parameter they never typed.
    """
    raw = request.query.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _retitle(world_text: str, title: str) -> str:
    """Override the display title in a serialized world file's JSON header, leaving
    the prose and every other field byte-for-byte. Used when the player renames a
    world in the review screen before installing it."""
    import json

    if not world_text.startswith("---\n"):
        return world_text
    marker = "\n---\n"
    end = world_text.find(marker, 3)
    if end == -1:
        return world_text
    try:
        header = json.loads(world_text[4:end])
    except ValueError:
        return world_text
    if not isinstance(header, dict):
        return world_text
    header["title"] = title
    prose = world_text[end + len(marker) :]
    return f"---\n{json.dumps(header, ensure_ascii=False, indent=2)}\n---\n{prose}"


async def create_world_draft(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /world-drafts`` — stash pasted text as a draft, BEFORE any agent runs.

    Split from ``/compile`` for the same reason a life's creation is split from its
    opening (R2.9): a failed or slow compile leaves a retryable draft rather than
    nothing, and a retry never produces a second draft.
    """
    if request.get("user") is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "expected an object"}, status=400)
    text = body.get("text")
    if not isinstance(text, str):
        text = ""
    title = str(body.get("title") or "")[:120]
    try:
        draft_id = _drafts(ctx).create(text, title=title)
    except DraftError as exc:
        return web.json_response({"error": str(exc), "code": "bad_draft"}, status=400)
    return web.json_response({"draftId": draft_id}, status=201)


async def compile_world_draft(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /world-drafts/{id}/compile`` — dispatch the worldsmith on a draft.

    Mirrors ``open_run``: the pending marker is written BEFORE dispatch so the
    draft reads as generating immediately, and a draft already in flight is not
    dispatched twice.
    """
    if request.get("user") is None:
        return _unauthorized()
    state_obj = request.app.get("state")
    if state_obj is None:
        return web.json_response({"error": "no chat runtime"}, status=503)
    draft_id = request.match_info.get("draft_id", "")
    store = _drafts(ctx)
    try:
        record = store.record(draft_id)
    except DraftError:
        return web.json_response({"error": "no such draft"}, status=404)
    status = record.get("status")
    if status == "installed":
        return web.json_response({"dispatched": False, "reason": "installed"})
    if status == "generating":
        return web.json_response({"dispatched": False, "reason": "generating"})

    from kiro_crew.dashboard.chat_runner import _run_chat  # noqa: PLC0415

    cfg = read_settings(ctx.data_dir)
    try:
        slot = ensure_worldsmith_slot(
            state_obj,
            draft_id,
            project=str(ctx.data_dir / "world-drafts" / draft_id),
            model=cfg["model"],
            reasoning_effort=cfg["reasoningEffort"],
        )
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "could not start the worldsmith", "detail": str(exc)}, status=503
        )
    store.mark_pending(draft_id)  # BEFORE dispatch, never after
    make_dispatcher(_run_chat)(state_obj, slot, worldsmith_prompt(draft_id))
    return web.json_response({"dispatched": True})


async def list_world_drafts(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /world-drafts`` — the shelf's in-progress and ready-to-review drafts."""
    if request.get("user") is None:
        return _unauthorized()
    return web.json_response({"drafts": _drafts(ctx).list()})


async def get_world_draft(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /world-drafts/{id}`` — the review payload (status, preview, warnings)
    plus the worldsmith's slot key, so the UI can offer a jump-to-chat."""
    if request.get("user") is None:
        return _unauthorized()
    draft_id = request.match_info.get("draft_id", "")
    try:
        record = _drafts(ctx).record(draft_id)
    except DraftError:
        return web.json_response({"error": "no such draft"}, status=404)
    try:
        slot_key = worldsmith_slot_key(draft_id)
    except Exception:  # noqa: BLE001
        slot_key = ""
    return web.json_response(
        {
            "draftId": record.get("draftId", draft_id),
            "title": record.get("title") or "",
            "status": record.get("status", "new"),
            "steps": int(record.get("steps") or 0),
            "stage": record.get("stage") or "",
            "lastTool": record.get("lastTool") or "",
            "problem": record.get("problem") or "",
            "field": record.get("field") or "",
            "worldId": record.get("worldId") or "",
            "preview": record.get("preview") or None,
            "warnings": record.get("warnings") or [],
            "dropped": record.get("dropped") or [],
            "slotKey": slot_key,
        }
    )


async def install_world_draft(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /world-drafts/{id}/install`` — put the reviewed world on the shelf.

    Optional body ``{title}`` renames the world's display title first. Refused if
    the draft is not ``ready`` or its id collides with an existing world.
    """
    if request.get("user") is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    title = str(body.get("title") or "").strip()[:120]
    draft_id = request.match_info.get("draft_id", "")
    store = _drafts(ctx)
    try:
        record = store.record(draft_id)
    except DraftError:
        return web.json_response({"error": "no such draft"}, status=404)
    if record.get("status") != "ready":
        return web.json_response(
            {"error": "this world isn't ready to add yet", "code": "not_ready"}, status=409
        )
    try:
        world_text = store.world_text(draft_id)
    except DraftError as exc:
        return web.json_response({"error": str(exc), "code": "not_ready"}, status=409)
    if title:
        world_text = _retitle(world_text, title)
    try:
        world_id = _library(ctx).install(world_text)
    except LibraryError as exc:
        return web.json_response({"error": str(exc), "code": "install_failed"}, status=409)
    store.mark_installed(draft_id, world_id)
    state_obj = request.app.get("state")
    if state_obj is not None:
        try:
            release_worldsmith_slot(state_obj, draft_id)
        except Exception:  # noqa: BLE001
            pass
    return web.json_response({"worldId": world_id})


async def discard_world_draft(request: web.Request, ctx: AppContext) -> web.Response:
    """``DELETE /world-drafts/{id}`` — throw a draft away. Idempotent."""
    if request.get("user") is None:
        return _unauthorized()
    draft_id = request.match_info.get("draft_id", "")
    try:
        _drafts(ctx).delete(draft_id)
    except DraftError:
        pass
    state_obj = request.app.get("state")
    if state_obj is not None:
        try:
            release_worldsmith_slot(state_obj, draft_id)
        except Exception:  # noqa: BLE001
            pass
    return web.json_response({"deleted": True})


def _absolutized_mcp_spec(data: dict, backend_dir: Path) -> dict | None:
    """The endless-mcp manifest with ``args``/``env`` made absolute for
    *backend_dir*, or ``None`` when no rewrite is needed (already correct) or
    possible (no such server). Pure — no IO — so it is testable without touching
    an install or the gateway.
    """
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    srv = servers.get("endless-mcp")
    if not isinstance(srv, dict):
        return None
    want_script = str(backend_dir / "mcp_server.py")
    want_pythonpath = str(backend_dir)
    raw_env = srv.get("env")
    env = raw_env if isinstance(raw_env, dict) else {}
    if srv.get("args") == [want_script] and env.get("PYTHONPATH") == want_pythonpath:
        return None  # already absolute and correct for this install
    new_srv = {**srv, "args": [want_script], "env": {**env, "PYTHONPATH": want_pythonpath}}
    return {**data, "mcpServers": {**servers, "endless-mcp": new_srv}}


def _heal_mcp_server_path() -> None:
    """Make the ``endless-mcp`` server path absolute for THIS install.

    The gateway resolves an mcpServers ``command`` (a bare ``python3`` becomes the
    app's venv or the gateway interpreter) but passes ``args`` and ``env`` VERBATIM
    — it does NOT resolve a relative script path against the app dir, and it does
    not read ``cwd``. So the shipped ``app.json`` carries a repo-relative
    ``backend/mcp_server.py`` (no machine path, nothing to leak), and this rewrites
    the INSTALLED copy to the absolute path of this file's own directory, then
    re-registers so a fresh install's narrator can reach its MCP tools with no
    hand-edit.

    Idempotent (a no-op once the paths already match) and never raises: a failure
    here must not stop the app's HTTP routes from registering. Skipped under the
    test suite, where there is no install to heal and no gateway to re-register
    with (the pure rewrite is exercised via :func:`_absolutized_mcp_spec`).
    """
    if _UNDER_TEST:
        return
    try:
        app_json = _HERE.parent / "app.json"
        data = json.loads(app_json.read_text(encoding="utf-8"))
        healed = _absolutized_mcp_spec(data, _HERE)
        if healed is None:
            return
        app_json.write_text(
            json.dumps(healed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        try:
            from kiro_crew.apps.bridges import reregister_app_mcp_servers  # noqa: PLC0415

            reregister_app_mcp_servers("endless-worlds")
        except Exception:  # noqa: BLE001 — the rewrite alone fixes the NEXT enable
            pass
    except Exception:  # noqa: BLE001 — never block route registration
        pass


async def backdrop_timeline(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/backdrop-timeline?turn=N`` — audit where the backdrop
    wait went for one page.

    Diagnostic only. Returns the ordered events (each with ``serverMs`` for time
    spent inside a tool and ``gapMs`` for the wait since the previous event — the
    model's own thinking/generation), plus a summary naming the single longest gap
    and the slowest server step. ``turn`` defaults to the life's current turn.
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    if not any(r.get("runId") == run_id for r in store.read_index()):
        return web.json_response({"error": "no such life"}, status=404)
    raw_turn = request.query.get("turn")
    if raw_turn is not None:
        try:
            turn = int(raw_turn)
        except ValueError:
            return web.json_response({"field": "turn", "expected": "an integer"}, status=422)
    else:
        turn = int(store.read_state(run_id).get("turn") or 0)

    events = BackdropTimeline(ctx.data_dir, run_id).read(turn)
    gaps = [
        (int(e["gapMs"]), str(e.get("step") or "")) for e in events if e.get("gapMs") is not None
    ]
    slowest_gap_ms, slowest_gap_before = max(gaps, default=(0, ""))
    server_steps = {
        str(e.get("step") or ""): int(e["serverMs"])
        for e in events
        if isinstance(e.get("serverMs"), (int, float))
    }
    slowest_server = max(server_steps.items(), key=lambda kv: kv[1], default=("", 0))
    total_ms = (
        int((float(events[-1]["at"]) - float(events[0]["at"])) * 1000) if len(events) >= 2 else 0
    )
    return web.json_response(
        {
            "turn": turn,
            "events": events,
            "summary": {
                "totalMs": total_ms,
                # The step that FOLLOWED the longest wait — i.e. what the model spent
                # the most time thinking/generating before doing.
                "slowestGapMs": slowest_gap_ms,
                "slowestGapBefore": slowest_gap_before,
                "slowestServerStep": slowest_server[0],
                "slowestServerMs": slowest_server[1],
            },
        }
    )


def register_routes(ctx: AppContext) -> list[AppRoute]:
    """Declare this app's HTTP surface.

    Called on gateway start and on enable. Backend hook changes take effect only
    on a gateway restart or an app disable→enable cycle; UI files reload without.
    """
    _heal_mcp_server_path()
    return [
        AppRoute(method="GET", path="/health", handler=health),
        AppRoute(method="GET", path="/settings", handler=get_settings),
        AppRoute(method="PUT", path="/settings", handler=put_settings),
        AppRoute(method="GET", path="/models", handler=get_models),
        AppRoute(method="GET", path="/worlds", handler=list_worlds),
        AppRoute(method="GET", path="/worlds/{world_id}", handler=get_world),
        AppRoute(method="GET", path="/worlds/{world_id}/deletion", handler=world_deletion),
        AppRoute(method="POST", path="/worlds/{world_id}/delete", handler=delete_world),
        AppRoute(method="POST", path="/worlds/{world_id}/restore", handler=restore_world),
        AppRoute(method="GET", path="/runs", handler=list_runs),
        AppRoute(method="POST", path="/runs", handler=create_run),
        AppRoute(method="GET", path="/runs/{run_id}", handler=get_run),
        AppRoute(method="GET", path="/runs/{run_id}/deletion", handler=life_deletion),
        AppRoute(method="POST", path="/runs/{run_id}/delete", handler=delete_life),
        AppRoute(
            method="POST",
            path="/runs/{run_id}/reset-conversation",
            handler=reset_life_conversation,
        ),
        AppRoute(method="GET", path="/runs/{run_id}/perf", handler=life_perf),
        AppRoute(method="POST", path="/runs/{run_id}/meta", handler=set_life_meta),
        AppRoute(method="GET", path="/runs/{run_id}/scenes/{scene_id}", handler=get_scene),
        AppRoute(method="GET", path="/runs/{run_id}/backdrop", handler=get_backdrop),
        AppRoute(
            method="GET",
            path="/runs/{run_id}/backdrop-timeline",
            handler=backdrop_timeline,
        ),
        AppRoute(
            method="POST",
            path="/runs/{run_id}/scenes/{scene_id}/answer",
            handler=answer_scene,
        ),
        AppRoute(method="POST", path="/runs/{run_id}/open", handler=open_run),
        AppRoute(method="GET", path="/runs/{run_id}/chronicle", handler=get_chronicle),
        AppRoute(method="POST", path="/runs/{run_id}/turn", handler=advance_run_turn),
        # World drafts: paste raw text → background worldsmith cleans+compiles →
        # review → install. Mirrors the life-creation job (create, then a separate
        # retryable compile), so a slow or failed compile leaves a retryable draft.
        AppRoute(method="GET", path="/world-drafts", handler=list_world_drafts),
        AppRoute(method="POST", path="/world-drafts", handler=create_world_draft),
        AppRoute(method="GET", path="/world-drafts/{draft_id}", handler=get_world_draft),
        AppRoute(
            method="POST", path="/world-drafts/{draft_id}/compile", handler=compile_world_draft
        ),
        AppRoute(
            method="POST", path="/world-drafts/{draft_id}/install", handler=install_world_draft
        ),
        AppRoute(method="DELETE", path="/world-drafts/{draft_id}", handler=discard_world_draft),
        # The life star map + keepsakes (design §8.2/§8.3); handlers live in
        # memory_routes.py so the player meaning layer stays apart from the
        # turn loop.
        *memory_routes(),
    ]
