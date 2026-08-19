#!/usr/bin/env python3
"""无限世界's own MCP server — the narrator's entire tool surface.

Spawned by kiro-cli as a stdio server, declared in ``app.json``'s ``mcpServers``.
**stdout is the JSON-RPC channel**: anything printed there corrupts the stream
kiro-cli is parsing, so every diagnostic goes to stderr.

Two boundaries are structural here rather than checked at runtime:

* **Only ``endless_advance_turn`` can write run state.** The scene and read tools
  are not given a writer at all — they receive a read-only view or a ledger that
  can reach nothing but ``scenes.json``. A capability the code does not hold
  cannot be misused by a narrator that has been talked into trying, and the turn
  loop's idempotence and rewind both assume state changes only at a turn
  boundary.
* **Nothing here can prompt the player.** These tools return data to the
  narrator; the only thing the player ever sees is what the app's own UI renders
  from committed state.

Self-locating on purpose: the data directory is derived from this file's own
path, not from an environment variable. ``env`` in a manifest ``mcpServers``
entry is passed through verbatim (only ``PATH`` is normalised), so an env-based
data dir would be one more absolute path to keep in sync.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

#: ``<install>/backend/mcp_server.py`` → ``<install>``
_APP_ROOT = _HERE.parent
_DATA = _APP_ROOT / "data"

SERVER_NAME = "endless-mcp"
SERVER_VERSION = "1"

#: Must equal app.json's ``name`` — AppStorage keys its audit trail by it.
APP_NAME = "endless-worlds"


def _die(message: str) -> None:
    """Fail loudly on stderr. An unimportable dependency must not become a
    half-working server: kiro-cli drops an unresolvable tool silently, so a
    server that limps along with a hand-rolled protocol would be the one
    failure mode with no signal anywhere."""
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr)
    sys.exit(1)


try:  # the gateway's own stdio loop — see the module docstring in mcp_shared
    from kiro_crew.mcp_shared import run_mcp_stdio_loop
except Exception as exc:  # noqa: BLE001
    run_mcp_stdio_loop = None  # type: ignore[assignment]
    _IMPORT_ERROR = f"cannot import kiro_crew.mcp_shared: {exc}"
else:
    _IMPORT_ERROR = ""

try:
    from kiro_crew.apps.app_storage import AppStorage
except Exception as exc:  # noqa: BLE001
    AppStorage = None  # type: ignore[assignment]
    if not _IMPORT_ERROR:
        _IMPORT_ERROR = f"cannot import kiro_crew.apps.app_storage: {exc}"

from scenes import SceneLedger, SceneLedgerError  # noqa: E402
from chapters import (  # noqa: E402
    ChapterError,
    brief,
    contents,
    opened_since,
    read_chapter,
)
from halo import attribution, compose_restraint, event_density  # noqa: E402
from store import RunStore, StoreError  # noqa: E402
from turn import declaration_shape  # noqa: E402
from world import WorldError, read_world, serialize_world, summarize  # noqa: E402


# ── errors ───────────────────────────────────────────────────────────────


class ToolInputError(ValueError):
    """A call whose shape is wrong. Carries the FIELD so the narrator can fix
    the one thing that was wrong instead of guessing at the whole call."""

    def __init__(self, field: str, expected: str) -> None:
        super().__init__(f"{field}: {expected}")
        self.field = field
        self.expected = expected


# ── the declared surface ────────────────────────────────────────────────

_RUN_ID = {"type": "string", "pattern": "run-id", "maxLength": 48}

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "endless_advance_turn",
        "description": (
            "Commit one turn: the prose the player reads, the state that follows, "
            "and the choices offered. THE ONLY call that changes a life. Declare "
            "state in full — a field you leave out reads to the player as a fact "
            "that vanished. Idempotent per (runId, turn): re-sending a turn you "
            "already committed changes nothing."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "turn", "prose", "state"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "turn": {"type": "integer", "minimum": 1},
                "prose": {"type": "string", "maxLength": 20000},
                "state": {"type": "object"},
                "events": {
                    "type": "array",
                    "maxItems": 12,
                    "items": {"type": "string", "maxLength": 200},
                },
                "gains": {
                    "type": "array",
                    "maxItems": 12,
                    "items": {
                        "type": "object",
                        "required": ["field"],
                        "additionalProperties": False,
                        "properties": {
                            "field": {"type": "string", "maxLength": 64},
                            "amount": {"type": "string", "maxLength": 32},
                            "source": {"type": "string", "maxLength": 200},
                        },
                    },
                },
                "choices": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "required": ["id", "label"],
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "maxLength": 64},
                            "label": {"type": "string", "maxLength": 200},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "endless_read_runtime",
        "description": (
            "Read everything you need to narrate the next turn: the world's own "
            "rulebook, the state as it stands, and the recent turns. Read-only. "
            "Call this FIRST every turn — the prompt carries only the player's own "
            "words, and nothing else about the life reaches you any other way. "
            "Pass the `fingerprint` you were given last turn as `since` and you get "
            "only what changed, with the rest named as unchanged; omit it and you "
            "get the whole state."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "recentTurns": {"type": "integer", "minimum": 0, "maximum": 50},
                "includeProse": {"type": "boolean"},
                "chapters": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {"type": "string", "maxLength": 64},
                    "description": (
                        "Chapter ids from the table of contents whose text you want "
                        "now. One that this world does not disclose yet comes back "
                        "refused, with the condition that would open it."
                    ),
                },
                "since": {
                    "type": "string",
                    "maxLength": 64,
                    "description": (
                        "A `fingerprint` from an earlier call. If you can still "
                        "produce one you still hold the state it named, so only the "
                        "difference is sent. If you have lost it, leave this out — "
                        "asking with a baseline you no longer hold is how a turn "
                        "ends up inventing the parts it cannot see."
                    ),
                },
            },
        },
    },
    {
        "name": "endless_mount_scene",
        "description": (
            "Put a purpose-built scene in front of the player — a map, a ledger, a "
            "choice laid out as something other than a list. You describe what it "
            "should show and what it may ask; you never write its markup."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "sceneId", "spec"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "sceneId": {"type": "string", "maxLength": 64},
                "spec": {"type": "object"},
                "asks": {"type": "boolean"},
            },
        },
    },
    {
        "name": "endless_update_scene",
        "description": "Change what a mounted scene shows, without remounting it.",
        "inputSchema": {
            "type": "object",
            "required": ["runId", "sceneId", "spec"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "sceneId": {"type": "string", "maxLength": 64},
                "spec": {"type": "object"},
            },
        },
    },
    {
        "name": "endless_await_scene",
        "description": (
            "Read what the player did in a scene that asks something. Returns "
            "immediately: answered true with their answer, or answered false if "
            "they have not acted yet. Never blocks a turn waiting on a person."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "sceneId"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "sceneId": {"type": "string", "maxLength": 64},
            },
        },
    },
    {
        "name": "endless_dismiss_scene",
        "description": "Take a scene away when it has served its purpose.",
        "inputSchema": {
            "type": "object",
            "required": ["runId", "sceneId"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "sceneId": {"type": "string", "maxLength": 64},
            },
        },
    },
    {
        "name": "endless_make_pack",
        "description": (
            "Export a world as one portable file — its rulebook, its compiled "
            "structure, and any scenes built for it — so it can be replayed or "
            "handed to someone else."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["worldId"],
            "additionalProperties": False,
            "properties": {
                "worldId": {"type": "string", "maxLength": 64},
            },
        },
    },
]

#: Enforced schema is the PUBLISHED schema, read from the same list ``tools/list``
#: advertises — so a narrator cannot be refused for violating a rule it was never
#: shown. (The shape of this idea is borrowed from the mochi app's server.)
_INPUT_SCHEMAS: dict[str, Any] = {t["name"]: t["inputSchema"] for t in _TOOLS}

#: The single writer. Kept as data so a test can assert the set never grows
#: without someone noticing.
STATE_WRITERS = frozenset({"endless_advance_turn"})


# ── validation ───────────────────────────────────────────────────────────

_RUN_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def _validate(name: str, args: Any, *, path: str = "") -> None:
    """Validate a call against its declared schema, naming the first bad field.

    Deliberately validates the WHOLE call before any handler runs, so a
    malformed call applies nothing partial — a half-applied turn is worse than a
    refused one, because the player would see a life that half-moved.
    """
    schema = _INPUT_SCHEMAS.get(name)
    if schema is None:
        raise ToolInputError("tool", f"a known tool, got {name!r}")
    _check(schema, args, path or "arguments")


def _check(schema: dict[str, Any], value: Any, path: str) -> None:
    kind = schema.get("type")

    if kind == "object":
        if not isinstance(value, dict):
            raise ToolInputError(path, f"an object, got {type(value).__name__}")
        for field in schema.get("required", []):
            if field not in value:
                raise ToolInputError(f"{path}.{field}", "required, and absent")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    raise ToolInputError(f"{path}.{key}", "not a field of this call")
        for key, sub in props.items():
            if key in value:
                _check(sub, value[key], f"{path}.{key}")
        return

    if kind == "array":
        if not isinstance(value, list):
            raise ToolInputError(path, f"an array, got {type(value).__name__}")
        cap = schema.get("maxItems")
        if cap is not None and len(value) > cap:
            raise ToolInputError(path, f"at most {cap} entries, got {len(value)}")
        item = schema.get("items")
        if item:
            for i, entry in enumerate(value):
                _check(item, entry, f"{path}[{i}]")
        return

    if kind == "string":
        if not isinstance(value, str):
            raise ToolInputError(path, f"a string, got {type(value).__name__}")
        cap = schema.get("maxLength")
        if cap is not None and len(value) > cap:
            raise ToolInputError(path, f"at most {cap} characters, got {len(value)}")
        if schema.get("pattern") == "run-id":
            if not value or set(value) - _RUN_ID_CHARS or value[0] == "-":
                raise ToolInputError(path, "a run id (lowercase, digits, hyphens)")
        return

    if kind == "integer":
        # bool is an int in Python, and accepting True as a turn number would
        # commit turn 1 for a narrator that meant something else entirely.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolInputError(path, f"an integer, got {type(value).__name__}")
        low, high = schema.get("minimum"), schema.get("maximum")
        if low is not None and value < low:
            raise ToolInputError(path, f"at least {low}, got {value}")
        if high is not None and value > high:
            raise ToolInputError(path, f"at most {high}, got {value}")
        return

    if kind == "boolean":
        if not isinstance(value, bool):
            raise ToolInputError(path, f"true or false, got {type(value).__name__}")
        return


# ── capability handles ──────────────────────────────────────────────────


def _store() -> RunStore:
    if AppStorage is None:  # pragma: no cover — guarded at entry
        raise StoreError("AppStorage unavailable")
    return RunStore(AppStorage(APP_NAME, _DATA), _DATA)


def _scene_ledger(run_id: str) -> SceneLedger:
    """A handle that can reach ``scenes.json`` and nothing else.

    This is why a scene call cannot write panels, chronicle, or facts: not
    because it declines to, but because it is never handed anything that could.
    """
    return SceneLedger(_DATA, run_id)


# ── handlers ─────────────────────────────────────────────────────────────


#: Keys the APP owns. The narrator never declares them — they are bookkeeping, not
#: story — so a commit carries them forward instead of letting a full-state
#: declaration drop them. Losing ``worldId`` this way made a life unreadable the
#: moment its first turn landed: the play view could no longer find its world.
RESERVED_STATE_KEYS = ("worldId", "style", "language", "opening", "status")


def _advance_turn(args: dict[str, Any]) -> dict[str, Any]:
    run_id = args["runId"]
    turn = args["turn"]
    store = _store()

    current = store.read_state(run_id)
    committed = int(current.get("turn") or 0)
    if turn <= committed:
        # Idempotent per (runId, turn). A retried turn must not double-apply, and
        # the narrator is not told off for it — a retry is usually the transport,
        # not a mistake.
        return {"committed": False, "turn": committed, "reason": "already recorded"}

    # Did the narrator look before it narrated?
    #
    # The prompt no longer carries the state, the history, or the readings on the
    # narrator's own recent turns. A narrator that skips `endless_read_runtime` is
    # therefore writing a month from the player's sentence and its own memory — which
    # is not a slow turn or an ugly turn, it is a turn about a life whose current
    # facts it never read. That is worth refusing.
    #
    # Enforced on EVIDENCE, never on the absence of it. The refusal fires only when
    # the app's own in-flight record for THIS turn exists and says no read happened.
    # A missing record proves nothing about the narrator — the app may simply not have
    # written one — and refusing on that would wedge a live life over the app's own
    # bookkeeping gap. Wrong in the safe direction: an unproven omission is allowed.
    asked_before = store.read_pending(run_id)
    if isinstance(asked_before, dict) and int(asked_before.get("turn") or 0) == turn:
        if not asked_before.get("readAt"):
            return {
                "committed": False,
                "turn": committed,
                # A machine token, and one the narrator can act on: read, then commit
                # again. The same shape as the run-id refusal, which it recovered
                # from unaided.
                "reason": "read-runtime-first",
                "detail": (
                    "Call endless_read_runtime for this run before committing a turn. "
                    "The prompt carries only the player's words; the state of this "
                    "life reaches you no other way."
                ),
            }

    state = dict(args["state"])
    # The declaration is the story's whole state, so it REPLACES the previous one
    # — a field the narrator stops declaring is a fact that stopped being true.
    # The app's own keys are the exception: they were never the narrator's to
    # declare, and dropping them silently breaks the page rather than the story.
    for key in RESERVED_STATE_KEYS:
        if key in current and key not in state:
            state[key] = current[key]
    state["turn"] = turn
    store.commit_state(run_id, state)
    # What the player asked for, recovered from the in-flight record the app wrote
    # before speaking. The narrator is told the intent in prose and never echoes it
    # back, so this is the only place it can be preserved — and without it, reviewing
    # a past month shows the outcome with the choice that caused it missing.
    asked = store.read_pending(run_id) or {}
    action = str(asked.get("action") or "") if int(asked.get("turn") or 0) == turn else ""

    store.append_turn(
        run_id,
        {
            "turn": turn,
            "prose": args["prose"],
            "action": action,
            "choices": args.get("choices") or [],
            # What this turn marked notable, and what it credited a gain to. Both
            # are how the anti-halo readings become measurable; `source` is
            # deliberately NOT required — a narrator that forgot to say where five
            # gold came from has still narrated a real turn, and the omission is
            # surfaced to the next turn rather than refused here.
            "events": args.get("events") or [],
            "gains": args.get("gains") or [],
        },
    )
    return {"committed": True, "turn": turn}


#: How many months one read returns when the narrator does not say.
#:
#: Inherited from the rolling-summary era, where turns beyond this many were folded
#: into an app-computed summary and pushed into every prompt. The summary is gone —
#: the narrator pages its own history from the newest end now — but the number kept
#: its meaning: about a year of months is what carries the texture of where a life
#: currently is, and anything older is something to go and look up rather than
#: something to be handed unasked.
RECENT_TURNS = 12


def _read_runtime(args: dict[str, Any]) -> dict[str, Any]:
    """What the narrator needs to know, pulled rather than pushed.

    The prompt used to carry all of this — state, recent turns, the anti-halo
    readings — which meant the narrator paid for every part of it on every turn
    whether the month needed it or not. It is reference material, not instruction,
    and reference material belongs behind a tool.

    ``since`` is a fingerprint from a previous call and is what makes a delta safe.
    A narrator that can still produce one still holds the state it named; a narrator
    whose context was compacted lost the fingerprint along with the state, asks with
    nothing, and receives everything. The app never has to guess whether the
    baseline survived, because the question answers itself.
    """
    run_id = args["runId"]
    store = _store()
    state = store.read_state(run_id)
    chronicle = store.read_chronicle(run_id)
    recent = args.get("recentTurns", RECENT_TURNS)
    fingerprint = store.fingerprint(state)

    out: dict[str, Any] = {
        "runId": run_id,
        "turn": int(state.get("turn") or 0),
        # Hand this back as `since` next turn and only the changes come with it.
        "fingerprint": fingerprint,
        "scenes": _scene_ledger(run_id).mounted(),
    }

    since = str(args.get("since") or "")
    baseline = store.baseline_for(run_id, since) if since else None
    if baseline is not None:
        delta = store.diff(baseline, state)
        out["changed"] = delta["changed"]
        # Named rather than sent. "The rest is as it was" is only a sentence the
        # narrator can trust because it named the state that "was" refers to.
        out["unchanged"] = delta["same"]
        out["gone"] = delta["gone"]
        out["basedOn"] = since
    else:
        out["state"] = state
        if since:
            # Said out loud: a narrator that asked for a delta and got a snapshot
            # should know its baseline was not recognised, not quietly assume the
            # world reset.
            out["note"] = "baseline unknown; full state returned"

    # The narrator's session is ONE continuous conversation across a life's turns,
    # so on a delta read — one that carried a baseline it could only still name if
    # its context survived — it already holds every month it wrote. Re-sending the
    # recent chronicle there pays, every turn, for prose the narrator has in front
    # of it. So the recent months ride only on a FULL snapshot: the same missing
    # baseline that means "this narrator was compacted and needs re-anchoring" (and
    # the life's first read). An explicit recentTurns request is always honoured —
    # that is how the narrator deliberately pages back through older history.
    if "recentTurns" in args:
        out["recentTurns"] = chronicle[-recent:] if recent else []
    elif baseline is None:
        out["recentTurns"] = chronicle[-recent:] if recent else []
    else:
        out["recentTurns"] = []
    # The app's own readings of its recent behaviour (R7). A measurement, not an
    # instruction — which is exactly why it belongs in a tool result and not in the
    # imperative part of a prompt.
    #
    # Gated like the recent months, and for the same reason: this reading exists to
    # remind a narrator of generosity it might have FORGOTTEN, but on a continuous
    # session it has forgotten nothing — every month it wrote is still in front of
    # it. So the reading rides only on a FULL read, which is precisely the moment a
    # narrator lost that context (a compaction, or the first turn) and genuinely
    # needs reminding. On a delta read it is omitted rather than recomputed and
    # re-pushed every turn.
    if baseline is None:
        out["restraint"] = {
            "density": event_density(chronicle),
            "attribution": attribution(chronicle),
            # The same readings as a sentence, in the world's own language. Kept
            # because a narrator acts on "you have handed this life three windfalls
            # in six months" and merely notices `{"perTurn": 3.0}`.
            "note": compose_restraint(chronicle, state.get("language") or "en"),
        }

    world_id = state.get("worldId")
    if isinstance(world_id, str) and world_id:
        # A run is bound to one language for its whole life; its variant file
        # (``<id>.<lang>.md``) is the rulebook the narrator reads, falling back to
        # the base ``<id>.md`` when the run is in the world's primary language.
        worlds = _DATA / "worlds"
        language = state.get("language")
        path = worlds / f"{world_id}.md"
        if isinstance(language, str) and language:
            variant = worlds / f"{world_id}.{language}.md"
            if variant.is_file():
                path = variant
        if path.is_file():
            pack = read_world(path.read_text(encoding="utf-8"))
            out["world"] = summarize(pack)
            # The table of contents, but not on every turn.
            #
            # A narrator cannot ask for a chapter it was never told exists, so the
            # contents has to reach it — but the contents is static per world and
            # measured on the flagship it is about a fifth of the book, which means
            # sending it every turn costs more than the book did by the fifth turn.
            #
            # So: with a full snapshot it comes whole, and with a delta only the
            # chapters the world has just opened come with it. Same rule as the state,
            # and self-healing for the same reason — a narrator that lost its baseline
            # gets no delta and therefore gets the contents again.
            if baseline is None:
                out["chapters"] = contents(pack.template, state)
                # A fresh pull is what the opening turn makes, and what a compacted
                # narrator falls back to. It carries everything that used to be
                # pushed into the opening prompt, so that prompt can be just the run
                # id: the world's always-open rules, how to record state, and the
                # opening groups — including which the world settles rather than the
                # player, the anti-halo signal that must not be lost (R7).
                out["brief"] = brief(pack.template)
                out["shape"] = declaration_shape(pack.template)
                out["opening"] = [
                    {"id": g.id, "label": g.label, "worldDecides": g.random}
                    for g in pack.template.opening
                ]
            else:
                newly = opened_since(pack.template, baseline, state)
                if newly:
                    out["chaptersOpened"] = newly

            # Bodies only when named. `includeProse` still means the whole book, for
            # a world that declared no chapters and for a caller that genuinely wants
            # all of it.
            wanted = args.get("chapters") or []
            if wanted:
                got: dict[str, str] = {}
                refused: list[dict[str, str]] = []
                for cid in wanted:
                    try:
                        got[str(cid)] = read_chapter(pack.template, state, str(cid))
                    except ChapterError as exc:
                        # Refused with a reason, never silently omitted: a chapter
                        # that vanishes from the answer reads as a world with nothing
                        # to say on the subject.
                        refused.append({"id": exc.chapter_id, "reason": exc.reason})
                out["chapterText"] = got
                if refused:
                    out["chaptersRefused"] = refused
            if args.get("includeProse"):
                out["rulebook"] = pack.prose

    # Recorded so the app can see whether the narrator actually looked before it
    # narrated. Not enforced yet, on purpose: refusing a commit from a narrator that
    # skipped this would be a hard stop on a live life, and the honest order is to
    # measure the behaviour first and enforce once it is known.
    store.note_runtime_read(run_id, turn=int(state.get("turn") or 0) + 1)
    return out


def _mount_scene(args: dict[str, Any]) -> dict[str, Any]:
    ledger = _scene_ledger(args["runId"])
    ledger.mount(args["sceneId"], args["spec"], asks=bool(args.get("asks")))
    # The nonce is NOT returned to the narrator: it is the page's proof that a
    # click came from the frame currently on screen, and a narrator holding it
    # could forge an answer to its own question.
    return {"mounted": args["sceneId"]}


def _update_scene(args: dict[str, Any]) -> dict[str, Any]:
    ledger = _scene_ledger(args["runId"])
    ledger.update(args["sceneId"], args["spec"])
    return {"updated": args["sceneId"]}


def _await_scene(args: dict[str, Any]) -> dict[str, Any]:
    """Never blocks.

    A blocking wait would hold a turn open against a person who may have walked
    away, and the turn loop's own timeout would then kill the narration rather
    than the wait. So this reports whether an answer is there yet and lets the
    narrator decide.
    """
    ledger = _scene_ledger(args["runId"])
    answer = ledger.answer(args["sceneId"])
    if answer is None:
        return {"answered": False, "sceneId": args["sceneId"]}
    return {"answered": True, "sceneId": args["sceneId"], "answer": answer}


def _dismiss_scene(args: dict[str, Any]) -> dict[str, Any]:
    ledger = _scene_ledger(args["runId"])
    ledger.dismiss(args["sceneId"])
    return {"dismissed": args["sceneId"]}


def _make_pack(args: dict[str, Any]) -> dict[str, Any]:
    world_id = args["worldId"]
    if not world_id or "/" in world_id or "\\" in world_id or world_id.startswith("."):
        raise ToolInputError("arguments.worldId", "a world id, not a path")
    path = _DATA / "worlds" / f"{world_id}.md"
    if not path.is_file():
        raise WorldError(f"no such world: {world_id}")

    pack = read_world(path.read_text(encoding="utf-8"))
    out_dir = _DATA / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{world_id}.md"
    tmp = target.with_suffix(".md.tmp")
    tmp.write_text(serialize_world(pack), encoding="utf-8")
    os.replace(tmp, target)
    return {"worldId": world_id, "path": str(target), "bytes": target.stat().st_size}


_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "endless_advance_turn": _advance_turn,
    "endless_read_runtime": _read_runtime,
    "endless_mount_scene": _mount_scene,
    "endless_update_scene": _update_scene,
    "endless_await_scene": _await_scene,
    "endless_dismiss_scene": _dismiss_scene,
    "endless_make_pack": _make_pack,
}


# ── protocol ─────────────────────────────────────────────────────────────


def list_tools() -> list[dict[str, Any]]:
    return _TOOLS


def call_tool(name: str, args: dict[str, Any]) -> str:
    """Validate, dispatch, and answer as JSON text.

    Every failure is reported as data rather than raised: a raised exception
    reaches the narrator as a protocol error it cannot act on, while a named
    field is something it can fix on the next attempt.
    """
    try:
        _validate(name, args)
    except ToolInputError as exc:
        return json.dumps(
            {"ok": False, "field": exc.field, "expected": exc.expected, "applied": False},
            ensure_ascii=False,
        )

    handler = _HANDLERS.get(name)
    if handler is None:  # unreachable: _validate rejects unknown names first
        return json.dumps({"ok": False, "error": "unknown tool", "applied": False})

    try:
        result = handler(dict(args))
    except ToolInputError as exc:
        return json.dumps(
            {"ok": False, "field": exc.field, "expected": exc.expected, "applied": False},
            ensure_ascii=False,
        )
    except (StoreError, WorldError, SceneLedgerError) as exc:
        return json.dumps(
            {"ok": False, "error": str(exc), "applied": False}, ensure_ascii=False
        )
    return json.dumps({"ok": True, **result}, ensure_ascii=False)


def main() -> None:  # pragma: no cover — process entry point
    if _IMPORT_ERROR or run_mcp_stdio_loop is None:
        _die(_IMPORT_ERROR or "stdio loop unavailable")
    run_mcp_stdio_loop(SERVER_NAME, SERVER_VERSION, list_tools, call_tool)


if __name__ == "__main__":  # pragma: no cover
    main()
