"""The life star map and keepsake HTTP surface (design §8.2, §8.3, §10).

Kept apart from ``routes.py`` deliberately: these handlers are the player
meaning layer over the fact graph, they share almost nothing with the turn
loop, and the smaller the module the smaller the blast radius when either side
changes. ``routes.py`` only splices :func:`memory_routes` into its route list.

The invariants enforced at this boundary (§12.3, §12.4):

* Disclosure filtering is server-side — ``star_payload`` ships ``known`` events
  only, so no client filter can leak a hidden or foreshadowed fact.
* All three views consume the SAME payload from the same endpoint; switching a
  lens must not refetch, so the endpoint is layout-agnostic by construction.
* A keepsake cites facts, never changes them: nothing here can reach
  ``commit_state`` or ``append_turn``.
* The view preference is per-life shelf metadata, stored beside ``label`` and
  ``archived`` — switching lives never inherits another life's lens.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from aiohttp import web

from kiro_crew.apps.context import AppContext
from kiro_crew.apps.route_registry import AppRoute

import memory_graph
from keepsakes import KeepsakeError, KeepsakeStore
from legacy import candidates as legacy_candidates
from library import WorldLibrary
from store import RunStore, StoreError
from story_cards import (
    EXPORT_FORMATS,
    StoryCardError,
    StoryCardStore,
    apply_edits,
    build_draft,
    resolve,
)
from view import strip_terminal_framing

#: The lenses a life remembers as its last-used view (§8.3.2). "life" is the
#: default a fresh life opens with.
MEMORY_VIEWS = ("life", "people", "keepsakes")


def _unauthorized() -> web.Response:
    return web.json_response({"error": "unauthorized"}, status=401)


def _store(ctx: AppContext) -> RunStore:
    if ctx.storage is None:
        raise StoreError("storage permission missing")
    return RunStore(ctx.storage, ctx.data_dir)


def _life_row(store: RunStore, run_id: str) -> dict[str, Any] | None:
    for row in store.read_index():
        if row.get("runId") == run_id:
            return row
    return None


async def _body(request: web.Request) -> dict[str, Any]:
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return raw if isinstance(raw, dict) else {}


# ── the star map ─────────────────────────────────────────────────────────


async def get_star(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/memory/star`` — the sparse graph all three views share.

    One payload per life, whatever lens the player opens it with. The response
    also carries the keepsakes (they are nodes of the 纪念 lens and anchors of
    the other two) and the life's saved view preference, so opening the star
    map is one request.
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    try:
        state = store.read_state(run_id)
    except StoreError:
        return web.json_response({"error": "no such life"}, status=404)

    chronicle = store.read_chronicle(run_id)
    keepsake_rows = KeepsakeStore(ctx.data_dir, run_id).list()
    payload = memory_graph.star_payload(
        memory_graph.build_index(chronicle), keepsake_rows
    )

    row = _life_row(store, run_id) or {}
    view = row.get("memoryView")
    return web.json_response({
        **payload,
        "runId": run_id,
        "turn": int(state.get("turn") or 0),
        "keepsakes": keepsake_rows,
        "view": view if view in MEMORY_VIEWS else "life",
    })


async def set_memory_view(request: web.Request, ctx: AppContext) -> web.Response:
    """``PATCH /runs/{run_id}/preferences/memory-view`` — remember the lens.

    Saved per life (§8.3.2): the smart entry only decides the INITIAL lens, and
    the one the player last chose wins on a plain re-entry. Never touches the
    fact graph or the life's state.
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    body = await _body(request)
    view = body.get("view")
    if view not in MEMORY_VIEWS:
        return web.json_response(
            {"field": "view", "expected": f"one of {', '.join(MEMORY_VIEWS)}"},
            status=400,
        )
    if not _store(ctx).patch_index(run_id, {"memoryView": view}):
        return web.json_response({"error": "no such life"}, status=404)
    return web.json_response({"runId": run_id, "view": view})


# ── keepsakes ────────────────────────────────────────────────────────────

#: Characters dropped before the excerpt honesty check: markdown structure the
#: play page renders away, plus whitespace. A selection made on the RENDERED
#: page must still verify against the raw prose it came from.
_EXCERPT_NOISE = re.compile(r"[\s*_~`#>|\-]+")


def _normalise(text: str) -> str:
    return _EXCERPT_NOISE.sub("", text)


async def create_keepsake(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs/{run_id}/keepsakes`` — save "why this moment matters".

    Three shapes (§8.2): ``event`` cites one fact node; ``echo`` cites a whole
    declared echo path; ``excerpt`` preserves the player's own selected prose
    with its turn and content hash. Every cited event must be a ``known`` event
    of THIS life — the player keeps what they lived, never what the world has
    not shown them, and never another life's facts (§12.2).
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    try:
        store.read_state(run_id)
    except StoreError:
        return web.json_response({"error": "no such life"}, status=404)

    body = await _body(request)
    chronicle = store.read_chronicle(run_id)
    index = memory_graph.build_index(chronicle)

    cites = [str(c) for c in body.get("cites") or []]
    for cid in cites:
        ev = index["events"].get(cid)
        if ev is None or ev["disclosure"] != "known":
            return web.json_response(
                {"field": "cites",
                 "expected": f"a known event of this life, got {cid!r}"},
                status=422,
            )

    kind = str(body.get("kind") or "")
    excerpt = str(body.get("excerpt") or "")
    turn = body.get("turn")
    turn = turn if isinstance(turn, int) and not isinstance(turn, bool) else 0
    if kind == "excerpt":
        entry = next(
            (e for e in chronicle if int(e.get("turn") or 0) == turn), None
        )
        if entry is None:
            return web.json_response(
                {"field": "turn", "expected": "a turn this life has lived"},
                status=422,
            )
        page = _normalise(strip_terminal_framing(str(entry.get("prose") or "")))
        if excerpt and _normalise(excerpt) not in page:
            # The keepsake claims "this was on the page"; refuse a claim the
            # page cannot back.
            return web.json_response(
                {"field": "excerpt", "expected": "a passage from that turn's prose"},
                status=422,
            )
        if not cites:
            # Anchor the passage to that turn's own known events, so the
            # excerpt participates in the keepsake map instead of floating.
            cites = [
                cid for cid, ev in index["events"].items()
                if ev["turn"] == turn and ev["disclosure"] == "known"
            ]

    entities = [str(e) for e in body.get("entities") or []]
    for eid in entities:
        if eid != memory_graph.PLAYER and eid not in index["entities"]:
            return web.json_response(
                {"field": "entities", "expected": f"a known entity, got {eid!r}"},
                status=422,
            )

    try:
        kp = KeepsakeStore(ctx.data_dir, run_id).create(
            kind=kind,
            title=str(body.get("title") or ""),
            cites=cites,
            entities=entities,
            thought=str(body.get("thought") or ""),
            excerpt=excerpt,
            turn=turn,
            spoiler=bool(body.get("spoiler")),
        )
    except KeepsakeError as exc:
        return web.json_response(
            {"field": exc.field, "expected": exc.expected}, status=422
        )
    return web.json_response(kp)


async def update_keepsake(request: web.Request, ctx: AppContext) -> web.Response:
    """``PATCH /runs/{run_id}/keepsakes/{keepsake_id}`` — title, thought, spoiler.

    The cited path is immutable: editing what a keepsake points at would turn a
    memento into a claim. Point at something else by making a new one.
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    keepsake_id = request.match_info.get("keepsake_id", "")
    body = await _body(request)
    try:
        kp = KeepsakeStore(ctx.data_dir, run_id).update(
            keepsake_id,
            {k: body[k] for k in ("title", "thought", "spoiler") if k in body},
        )
    except KeepsakeError as exc:
        return web.json_response(
            {"field": exc.field, "expected": exc.expected}, status=422
        )
    if kp is None:
        return web.json_response({"error": "no such keepsake"}, status=404)
    return web.json_response(kp)


async def delete_keepsake(request: web.Request, ctx: AppContext) -> web.Response:
    """``DELETE /runs/{run_id}/keepsakes/{keepsake_id}`` — forget the meaning,
    never the fact. The cited events stay exactly where they were."""
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    keepsake_id = request.match_info.get("keepsake_id", "")
    if not KeepsakeStore(ctx.data_dir, run_id).delete(keepsake_id):
        return web.json_response({"error": "no such keepsake"}, status=404)
    return web.json_response({"deleted": keepsake_id})


# ── story cards (design §8.4) ────────────────────────────────────────────


async def preview_story_card(request: web.Request, ctx: AppContext) -> web.Response:
    """``POST /runs/{run_id}/story-cards/preview`` — a keepsake becomes a draft.

    The allowlist is fixed here (the keepsake's known cited events + their
    directly involved entities) and every later edit can only narrow it. The
    response is the editable draft plus its resolved preview — the same
    ``resolve()`` the exporters render from, so what the player sees IS what
    the file will contain (§11 Phase 3 completion bar).
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    try:
        state = store.read_state(run_id)
    except StoreError:
        return web.json_response({"error": "no such life"}, status=404)

    body = await _body(request)
    keepsake_id = str(body.get("keepsakeId") or "")
    kp = KeepsakeStore(ctx.data_dir, run_id).get(keepsake_id)
    if kp is None:
        return web.json_response({"error": "no such keepsake"}, status=404)

    chronicle = store.read_chronicle(run_id)
    index = memory_graph.build_index(chronicle)
    ended = int(state.get("turn") or 0) if state.get("ended") else 0
    try:
        card = build_draft(
            index, kp,
            ended_turn=ended,
            language=str(state.get("language") or "en"),
        )
    except StoryCardError as exc:
        return web.json_response(
            {"field": exc.field, "expected": exc.expected}, status=422
        )
    StoryCardStore(ctx.data_dir, run_id).put(card)
    return web.json_response({"card": card, "preview": resolve(card)})


async def edit_story_card(request: web.Request, ctx: AppContext) -> web.Response:
    """``PATCH /runs/{run_id}/story-cards/{card_id}`` — narrow, relabel, reorder.

    Adding is structurally impossible: an id not already on the card is
    refused, and turn numbers have no edit path (§8.4 调整顺序但不能篡改回合).
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    card_id = request.match_info.get("card_id", "")
    cards = StoryCardStore(ctx.data_dir, run_id)
    card = cards.get(card_id)
    if card is None:
        return web.json_response({"error": "no such story card"}, status=404)
    try:
        card = apply_edits(card, await _body(request))
    except StoryCardError as exc:
        return web.json_response(
            {"field": exc.field, "expected": exc.expected}, status=422
        )
    cards.put(card)
    return web.json_response({"card": card, "preview": resolve(card)})


async def export_story_card(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/story-cards/{card_id}/export?format=html|md|svg``.

    Renders from the stored draft through the same ``resolve()`` the preview
    used — the export cannot diverge from what was shown. The file is served
    as a download and is self-contained: no script, no external reference, no
    run id (§12.3). Nothing is uploaded anywhere (§8.4 不自动上传).
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    card_id = request.match_info.get("card_id", "")
    card = StoryCardStore(ctx.data_dir, run_id).get(card_id)
    if card is None:
        return web.json_response({"error": "no such story card"}, status=404)

    fmt = request.query.get("format", "html")
    if fmt not in EXPORT_FORMATS:
        return web.json_response(
            {"field": "format", "expected": f"one of {', '.join(EXPORT_FORMATS)}"},
            status=400,
        )
    content_type, render = EXPORT_FORMATS[fmt]
    text = render(card)
    # The filename comes from the card id alone — never the title (a header
    # cannot carry arbitrary unicode safely) and never the run id (§12.3).
    return web.Response(
        text=text,
        content_type=content_type.split(";")[0],
        charset="utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="story-card-{card_id}.{fmt}"'
        },
    )


# ── the legacy bridge (design §9) ────────────────────────────────────────


def _life_over(ctx: AppContext, state: dict[str, Any]) -> bool:
    """One answer to "is this life over", shared with the ending page.

    ``resolve_ending`` is the single evaluator (view.py): a life ended by the
    WORLD's own declared condition (``state.alive == false``) never carries a
    narrator-written ``ended`` flag, yet its ending page rightly offers the
    bridge — so a gate keyed on the flag alone answers 409 to a player the UI
    just invited. Found by the full-chain simulation, pinned by it since.
    Falls back to the flag when the world itself cannot be read.
    """
    from view import resolve_ending

    world_id = state.get("worldId")
    if isinstance(world_id, str) and world_id:
        try:
            seeds = Path(__file__).resolve().parent.parent / "seeds"
            pack = WorldLibrary(ctx.data_dir, seeds).read(world_id, state.get("language"))
            return bool(resolve_ending(pack.template, state))
        except Exception:  # noqa: BLE001 — an unreadable world falls back to the flag
            pass
    return bool(state.get("ended"))


async def get_legacy_candidates(request: web.Request, ctx: AppContext) -> web.Response:
    """``GET /runs/{run_id}/legacy/candidates`` — what a finished life may pass on.

    Offered only at the ending (§9: 玩家在人生终章确认): a life still being
    lived answers 409, so the bridge cannot become a mid-life duplication
    device. Whether the WORLD permits continuity at all is the创建-side gate —
    ``create_run`` checks the template's ``lineage`` flag before accepting a
    bridge — this endpoint only reports what exists to choose from.
    """
    if request.get("user") is None:
        return _unauthorized()
    run_id = request.match_info.get("run_id", "")
    store = _store(ctx)
    try:
        state = store.read_state(run_id)
    except StoreError:
        return web.json_response({"error": "no such life"}, status=404)
    if not _life_over(ctx, state):
        return web.json_response(
            {"error": "this life is still being lived", "code": "not_ended"},
            status=409,
        )
    index = memory_graph.build_index(store.read_chronicle(run_id))
    return web.json_response({
        "runId": run_id,
        "worldId": state.get("worldId") or "",
        "candidates": legacy_candidates(index),
    })


def memory_routes() -> list[AppRoute]:
    """The routes ``routes.register_routes`` splices in."""
    return [
        AppRoute(method="GET", path="/runs/{run_id}/memory/star", handler=get_star),
        AppRoute(
            method="PATCH",
            path="/runs/{run_id}/preferences/memory-view",
            handler=set_memory_view,
        ),
        AppRoute(method="POST", path="/runs/{run_id}/keepsakes", handler=create_keepsake),
        AppRoute(
            method="PATCH",
            path="/runs/{run_id}/keepsakes/{keepsake_id}",
            handler=update_keepsake,
        ),
        AppRoute(
            method="DELETE",
            path="/runs/{run_id}/keepsakes/{keepsake_id}",
            handler=delete_keepsake,
        ),
        AppRoute(
            method="POST",
            path="/runs/{run_id}/story-cards/preview",
            handler=preview_story_card,
        ),
        AppRoute(
            method="PATCH",
            path="/runs/{run_id}/story-cards/{card_id}",
            handler=edit_story_card,
        ),
        AppRoute(
            method="GET",
            path="/runs/{run_id}/story-cards/{card_id}/export",
            handler=export_story_card,
        ),
        AppRoute(
            method="GET",
            path="/runs/{run_id}/legacy/candidates",
            handler=get_legacy_candidates,
        ),
    ]
