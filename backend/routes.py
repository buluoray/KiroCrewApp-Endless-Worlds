"""Route registration for the 无限世界 app.

External-app contract (verified against apps/route_registry.py:27-32):
``register_routes(ctx)`` returns ``list[AppRoute]`` whose paths are RELATIVE to
``/api/apps/endless-worlds``. Handlers take ``(request, ctx)``. The builtin
pattern of ``app.router.add_get`` never dispatches here — the RouteRegistry
catch-all ``/api/apps/{app_name}/{path:.*}`` shadows it.
"""

from __future__ import annotations

import os
import sys
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

from chapters import brief as world_brief  # noqa: E402
from library import LibraryError, WorldLibrary  # noqa: E402
from opening import OpeningError, build_initial_state, compose_opening_prompt  # noqa: E402
from scenes import AlreadyAnswered, SceneLedger, SceneLedgerError, StaleScene  # noqa: E402
from store import RunStore  # noqa: E402
from turn import (  # noqa: E402
    advance_turn,
    already_committed,
    declaration_shape,
    generating,
    make_dispatcher,
)
from view import build_play_view, resolve_ending, world_detail  # noqa: E402
from widget import SceneSpecError, bound_values, compile_cached  # noqa: E402
from world import CONTRACT  # noqa: E402

#: Bumped independently of app.json; identifies the route contract the UI expects.
ROUTE_CONTRACT = 9

#: Seeds ship in the install tree, one level up from backend/.
_SEEDS_DIR = _HERE.parent / "seeds"


def _unauthorized() -> web.Response:
    return web.json_response({"error": "unauthorized"}, status=401)


def _library(ctx: AppContext) -> WorldLibrary:
    return WorldLibrary(ctx.data_dir, _SEEDS_DIR)


def _store(ctx: AppContext) -> RunStore:
    """The turn loop's store.

    ``ctx.storage`` is the AppStorage the platform populated for us — only
    because ``permissions.storage`` is declared (apps/context.py: "Only services
    declared in the app's permissions are populated; others are None").
    """
    if ctx.storage is None:
        raise RuntimeError("ctx.storage is None — permissions.storage not declared")
    return RunStore(ctx.storage, ctx.data_dir)


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

    return web.json_response({
        "worlds": library.list_worlds(),
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
    })


async def get_world(request: web.Request, ctx: AppContext) -> web.Response:
    """One world. ``?prose=1`` includes the full rulebook (R1.4)."""
    if request.get("user") is None:
        return _unauthorized()

    world_id = request.match_info.get("world_id", "")
    library = _library(ctx)
    try:
        pack = library.read(world_id)
    except LibraryError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    return web.json_response(
        world_detail(pack, include_prose=bool(request.query.get("prose")))
    )


def lives_claiming(store: RunStore, world_id: str) -> list[dict[str, Any]]:
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
            life["generating"] = generating(store, run_id) is not None
        except Exception:  # noqa: BLE001
            life["generating"] = False
        out.append(life)
    return out


def _deletion_facts(ctx: AppContext, world_id: str) -> dict[str, Any]:
    """What the confirmation must be able to say, gathered once.

    The dialog is not allowed to guess any of this. A confirmation that does not
    name the number of lives it ends is a confirmation of the wrong question.
    """
    library = _library(ctx)
    lives = lives_claiming(_store(ctx), world_id)
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
        return web.json_response(_deletion_facts(ctx, world_id))
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
        facts = _deletion_facts(ctx, world_id)
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
    failed: list[dict[str, str]] = []
    removed: list[str] = []
    for life in facts["lives"]:
        try:
            store.delete_run(str(life["runId"]))
            removed.append(str(life["runId"]))
        except Exception as exc:  # noqa: BLE001
            failed.append({"runId": str(life["runId"]), "problem": str(exc)})

    # The lives go first. A world removed while a life it owns survives leaves a
    # shelf row that can only ever produce "this world could not be read" — and the
    # player has no way left to reach the world that would have cleaned it up.
    if failed:
        return web.json_response(
            {
                "error": "some lives could not be erased, so the world was kept",
                "code": "lives_not_erased",
                "failed": failed,
                "livesRemoved": removed,
            },
            status=500,
        )

    try:
        library.remove(world_id)
    except (LibraryError, OSError) as exc:
        return web.json_response(
            {"error": "the world's file could not be removed", "detail": str(exc),
             "livesRemoved": removed},
            status=500,
        )

    return web.json_response({
        "worldId": world_id,
        "livesRemoved": removed,
        "restorable": facts["restorable"],
    })


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
                {"error": "no seed to restore this world from",
                 "code": "not_restorable"},
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


def _life_deletion_facts(ctx: AppContext, run_id: str) -> dict[str, Any]:
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
        facts["generating"] = generating(store, run_id) is not None
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
    return web.json_response(_life_deletion_facts(ctx, run_id))


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

    facts = _life_deletion_facts(ctx, run_id)

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
                {"field": "label", "expected": "a name, or \"\" to clear it"}, status=400
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

    if isinstance(wanted, int) and not isinstance(wanted, bool):
        done = already_committed(store, run_id, wanted)
        if done is not None:
            return web.json_response(
                {"advanced": False, "turn": wanted, "reason": "already",
                 "prose": done.get("prose", ""), "choices": done.get("choices") or []}
            )

    run_state = store.read_state(run_id)
    world_id = run_state.get("worldId")
    if not isinstance(world_id, str) or not world_id:
        return web.json_response({"error": "this life has no world"}, status=422)

    try:
        pack = _library(ctx).read(world_id)
    except (LibraryError, Exception) as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    # A life that has reached an ending is over: refuse to narrate another month
    # and answer with a stable, machine-readable reason so a repeated tap lands on
    # the same terminal page instead of quietly resurrecting the life.
    ending_id = resolve_ending(pack.template, run_state)
    if ending_id:
        return web.json_response({
            "advanced": False,
            "turn": int(run_state.get("turn") or 0),
            "reason": "ended",
            "endingId": ending_id,
            "state": run_state,
        })

    from kiro_crew.dashboard.chat_runner import _run_chat  # noqa: PLC0415

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
    )

    return web.json_response({
        "advanced": outcome.advanced,
        "turn": outcome.turn,
        "reason": outcome.reason,
        "prose": outcome.prose,
        "state": store.read_state(run_id),
        "scenes": SceneLedger(ctx.data_dir, run_id).mounted() if outcome.advanced else [],
    })


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
    answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
    style = str(body.get("style") or "")

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
                answers = {
                    k: v for k, v in src_opening.items()
                    if isinstance(v, str) and v.strip()
                }
        if not style:
            style = str(src.get("style") or "")

    if not isinstance(world_id, str) or not world_id:
        return web.json_response({"field": "worldId", "expected": "a world"}, status=400)

    try:
        pack = _library(ctx).read(world_id)
    except LibraryError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    try:
        state = build_initial_state(pack.template, answers, style=style)
    except OpeningError as exc:
        return web.json_response(
            {"field": exc.field, "expected": exc.expected}, status=400
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
    return web.json_response({"runId": run_id, "state": store.read_state(run_id)},
                             status=201)


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
    run_state = store.read_state(run_id)

    if int(run_state.get("turn") or 0) >= 1:
        # Already opened. A retry after a slow success must not narrate a second
        # first turn.
        chronicle = store.read_chronicle(run_id)
        return web.json_response({
            "advanced": False, "reason": "already", "turn": int(run_state["turn"]),
            "prose": chronicle[0].get("prose", "") if chronicle else "",
            "state": run_state,
        })

    world_id = run_state.get("worldId")
    if not isinstance(world_id, str) or not world_id:
        return web.json_response({"error": "this life has no world"}, status=422)
    try:
        pack = _library(ctx).read(world_id)
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    from kiro_crew.dashboard.chat_runner import _run_chat  # noqa: PLC0415

    prompt = compose_opening_prompt(
        rulebook=world_brief(pack.template), template=pack.template, state=run_state, run_id=run_id,
        shape=declaration_shape(pack.template),
    )
    outcome = await advance_turn(
        state_obj=state_obj,
        store=store,
        run_id=run_id,
        rulebook=world_brief(pack.template),
        dispatch=make_dispatcher(_run_chat),
        style=str(run_state.get("style") or ""),
        project=str(ctx.data_dir / "runs" / run_id),
        prompt_override=prompt,
    )
    return web.json_response({
        "advanced": outcome.advanced,
        "turn": outcome.turn,
        "reason": outcome.reason,
        "prose": outcome.prose,
        "state": store.read_state(run_id),
        # A failed opening leaves the run retryable rather than half-created.
        "retryable": not outcome.advanced,
        "generating": outcome.reason in ("generating", "timeout"),
    })


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
        live["awaitingOpening"] = (
            state.get("status") == "awaiting-opening" and live["turn"] == 0
        )
        live["ended"] = bool(state.get("ended"))
        live["subtitle"] = life_subtitle(state)
        rows.append(live)

    for row in rows:
        rid = row.get("runId")
        if isinstance(rid, str) and rid:
            try:
                row["generating"] = generating(store, rid) is not None
            except Exception:  # noqa: BLE001 — a broken row must not blank the shelf
                row["generating"] = False
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
    state = store.read_state(run_id)
    if not state:
        return web.json_response({"error": "no such life"}, status=404)

    world_id = state.get("worldId")
    if not isinstance(world_id, str) or not world_id:
        return web.json_response({"error": "this life has no world"}, status=422)
    try:
        pack = _library(ctx).read(world_id)
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": "this world could not be read", "detail": str(exc)}, status=422
        )

    view = build_play_view(
        pack.template,
        state,
        chronicle=store.read_chronicle(run_id),
        scenes=SceneLedger(ctx.data_dir, run_id).mounted(),
    )
    view["runId"] = run_id
    view["worldId"] = world_id
    view["title"] = pack.template.title
    view["language"] = pack.template.language
    # What a returning player is owed: leaving the page while a turn was being
    # written used to look identical to never having asked for it.
    view["generating"] = generating(store, run_id)
    view["awaitingOpening"] = state.get("status") == "awaiting-opening" and view["turn"] == 0
    return web.json_response(view)


async def get_scene(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/scenes/{scene_id}`` — one scene, compiled.

    Returns HTML as **text**, for the page to hand to a sandboxed frame's
    ``srcdoc``. It is deliberately not served as a document the browser could
    navigate to: nothing here should ever become a top-level page, and a scene
    that could be opened in its own tab would have escaped the frame's sandbox
    along with it.
    """
    if request.get("user") is None:
        return _unauthorized()

    run_id = request.match_info.get("run_id", "")
    scene_id = request.match_info.get("scene_id", "")

    store = _store(ctx)
    state = store.read_state(run_id)
    if not state:
        return web.json_response({"error": "no such life"}, status=404)

    ledger = SceneLedger(ctx.data_dir, run_id)
    try:
        mounted = {m["sceneId"] for m in ledger.mounted()}
    except SceneLedgerError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    if scene_id not in mounted:
        return web.json_response({"error": "no such scene"}, status=404)

    spec = ledger.spec(scene_id)
    try:
        html_text, cached = compile_cached(
            ctx.data_dir, run_id, scene_id, spec, state,
            bound_slice=bound_values(spec, state),
            nonce=ledger.nonce(scene_id),
        )
    except SceneSpecError as exc:
        # Named field, no partial mount: the page shows nothing rather than half
        # a scene, and the narrator is told which field to fix on its next turn.
        return web.json_response(
            {"field": exc.field, "expected": exc.expected}, status=422
        )

    return web.Response(
        text=html_text,
        content_type="text/plain",
        charset="utf-8",
        headers={"Cache-Control": "no-store", "X-Scene-Cached": "1" if cached else "0"},
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

    ledger = SceneLedger(ctx.data_dir, run_id)

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
        return web.json_response(
            {"accepted": False, "reason": "no such scene"}, status=404
        )

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

    # Full-text filter across the whole life, applied before paging so "when did I
    # meet the smith" pages through matches rather than raw months. Case-insensitive
    # over prose, the player's action, and the marked events.
    q = request.query.get("q", "").strip().lower()
    if q:
        def _hit(e: dict[str, Any]) -> bool:
            hay = " ".join([
                str(e.get("prose") or ""),
                str(e.get("action") or ""),
                " ".join(str(x) for x in (e.get("events") or [])),
            ]).lower()
            return q in hay
        entries = [e for e in entries if _hit(e)]

    # `before` is a turn NUMBER, not an offset: an offset would shift under a turn
    # committed between two pages and silently skip or repeat a month.
    before = _int_param(request, "before", default=0)
    if before > 0:
        entries = [e for e in entries if int(e.get("turn") or 0) < before]

    limit = max(1, min(_int_param(request, "limit", default=CHRONICLE_PAGE), 100))
    page = list(reversed(entries))[:limit]

    return web.json_response({
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
                    str(x) for x in (e.get("events") or [])
                    if isinstance(x, str) and x.strip()
                ][:12],
                "gains": [
                    {
                        "field": str(g.get("field") or ""),
                        "amount": str(g.get("amount") or ""),
                        "source": str(g.get("source") or ""),
                    }
                    for g in (e.get("gains") or [])
                    if isinstance(g, dict) and g.get("field")
                ][:12],
            }
            for e in page
        ],
        # Whether reading further back is possible, so the UI offers "more" only
        # when there is more rather than on every page.
        "more": bool(page) and any(
            int(e.get("turn") or 0) < int(page[-1].get("turn") or 0) for e in entries
        ),
    })


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


def register_routes(ctx: AppContext) -> list[AppRoute]:
    """Declare this app's HTTP surface.

    Called on gateway start and on enable. Backend hook changes take effect only
    on a gateway restart or an app disable→enable cycle; UI files reload without.
    """
    return [
        AppRoute(method="GET", path="/health", handler=health),
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
        AppRoute(method="POST", path="/runs/{run_id}/meta", handler=set_life_meta),
        AppRoute(method="GET", path="/runs/{run_id}/scenes/{scene_id}", handler=get_scene),
        AppRoute(
            method="POST",
            path="/runs/{run_id}/scenes/{scene_id}/answer",
            handler=answer_scene,
        ),
        AppRoute(method="POST", path="/runs/{run_id}/open", handler=open_run),
        AppRoute(
            method="GET", path="/runs/{run_id}/chronicle", handler=get_chronicle
        ),
        AppRoute(method="POST", path="/runs/{run_id}/turn", handler=advance_run_turn),
    ]
