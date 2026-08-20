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
import re
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
from backdrop import BackdropError, BackdropStore, compile_backdrop  # noqa: E402
from chapters import (  # noqa: E402
    ChapterError,
    brief,
    contents,
    opened_since,
    read_chapter,
)
from halo import attribution, compose_restraint, event_density  # noqa: E402
import memory_graph  # noqa: E402
from store import RunStore, StoreError  # noqa: E402
from turn import declaration_shape  # noqa: E402
from systems import apply_systems  # noqa: E402
from view import always_panels_empty  # noqa: E402
from world import WorldError, read_world, serialize_world, summarize  # noqa: E402
from compile import COMPILER_BRIEF, CLEANING_CONTRACT, accept_compiled_header, preview  # noqa: E402
from drafts import DraftError, DraftStore  # noqa: E402


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
            "and the choices offered. THE ONLY call that changes a life. A living "
            "turn MUST include `choices`; omit them only on a terminal turn, marked "
            "`ending: true` or via state that fires a world ending. Declare "
            "state in full — a field you leave out reads to the player as a fact "
            "that vanished; the exceptions are `digest` and `relations`, which merge "
            "forward, so there you declare only what changed this turn (a null value "
            "retires one entry) instead of re-sending the whole block. Idempotent "
            "per (runId, turn): re-sending a turn you "
            "already committed changes nothing. The optional `memory` block is how "
            "this world REMEMBERS: declare the people/places/things this turn "
            "introduced, the events that happened, and any relation changes. When "
            "a new event answers an old one, name the old event's canonical id in "
            "`echoes` — that is the only thing that makes the world's memory of it "
            "real. To open a NEW thread, list it under an event's `threads` with "
            "effect \"opened\" — that declares it, no separate entity needed; only "
            "`advanced`/`resolved` need a thread opened before. Memory is salvaged, "
            "not rejected: an unresolved reference is dropped and warned while the "
            "event around it is still recorded. Facts are never extracted from your "
            "prose."
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
                # Terminal marker. A living turn MUST include `choices`; only a
                # terminal turn may omit them, and it says so with `ending: true`
                # (or by declaring state that fires a declared world ending).
                "ending": {"type": "boolean"},
                "memory": {
                    "type": "object",
                    # Unknown top-level memory keys are tolerated: sanitize_memory
                    # rebuilds a clean block from entities/events/relations only, so
                    # anything else is silently dropped rather than refusing the turn.
                    "additionalProperties": True,
                    "properties": {
                        "entities": {
                            "type": "array",
                            "maxItems": 12,
                            "items": {
                                "type": "object",
                                # No `required`: memory is enrichment and must never
                                # block a turn at the schema layer. sanitize_memory is
                                # the content gate — it drops a malformed sub-item and
                                # commits the rest. The schema still bounds types and
                                # rejects unknown fields for a clean message.
                                "additionalProperties": False,
                                "properties": {
                                    "id": {"type": "string", "maxLength": 64},
                                    # Relaxed from an enum to a bounded string:
                                    # sanitize_memory validates the kind against
                                    # KINDS and DROPS an entity with an unknown one,
                                    # so a mangled value never refuses the turn. The
                                    # `additionalProperties: False` here is KEPT on
                                    # purpose — it is the security guard that stops a
                                    # narrator declaring the app-only `inheritsFrom`
                                    # provenance (see legacy.py), which sanitize does
                                    # not strip.
                                    "kind": {"type": "string", "maxLength": 64},
                                    "name": {"type": "string", "maxLength": 120},
                                    "aliases": {
                                        "type": "array",
                                        "maxItems": 6,
                                        "items": {"type": "string", "maxLength": 120},
                                    },
                                    "summary": {"type": "string", "maxLength": 300},
                                },
                            },
                        },
                        "events": {
                            "type": "array",
                            "maxItems": 6,
                            "items": {
                                "type": "object",
                                # No `required` — see the entities note above. Unknown
                                # fields are tolerated (not refused): sanitize_memory
                                # is the sole gate, and there is no security-critical
                                # reserved field on an event the way `inheritsFrom` is
                                # on an entity.
                                "additionalProperties": True,
                                "properties": {
                                    "key": {"type": "string", "maxLength": 64},
                                    "title": {"type": "string", "maxLength": 120},
                                    "summary": {"type": "string", "maxLength": 300},
                                    "importance": {"type": "string", "maxLength": 64},
                                    "participants": {
                                        "type": "array",
                                        "maxItems": 8,
                                        "items": {"type": "string", "maxLength": 64},
                                    },
                                    "place": {"type": "string", "maxLength": 64},
                                    "threads": {
                                        "type": "array",
                                        "maxItems": 4,
                                        "items": {
                                            "type": "object",
                                            "additionalProperties": True,
                                            "properties": {
                                                "id": {"type": "string", "maxLength": 64},
                                                "effect": {
                                                    "type": "string",
                                                    "maxLength": 64,
                                                },
                                            },
                                        },
                                    },
                                    "echoes": {
                                        "type": "array",
                                        "maxItems": 4,
                                        "items": {"type": "string", "maxLength": 96},
                                    },
                                    "corrects": {"type": "string", "maxLength": 96},
                                    "disclosure": {"type": "string", "maxLength": 64},
                                },
                            },
                        },
                        "relations": {
                            "type": "array",
                            "maxItems": 12,
                            "items": {
                                "type": "object",
                                # No `required` — see the entities note above.
                                "additionalProperties": True,
                                "properties": {
                                    "from": {"type": "string", "maxLength": 64},
                                    "type": {"type": "string", "maxLength": 64},
                                    "to": {"type": "string", "maxLength": 64},
                                    "change": {"type": "string", "maxLength": 64},
                                    "value": {"type": "string", "maxLength": 64},
                                    "reasonEvent": {"type": "string", "maxLength": 96},
                                },
                            },
                        },
                    },
                },
                # Enrichment (the anti-halo notable-events log): relaxed to a
                # bare array so a mangled entry never refuses the turn. Coerced to
                # at most 12 strings of 200 chars each at commit.
                "events": {"type": "array"},
                # Enrichment (per-turn gains the systems engine reads): relaxed to
                # a bare array; `_clean_gains` drops any entry with no string
                # `field`, strips unknown keys, and caps the list at 12, warning on
                # each drop instead of refusing the turn.
                "gains": {"type": "array"},
                # Player-facing, but SALVAGED rather than schema-refused:
                # `_clean_choices` is the gate. It drops entries with no usable
                # `label`, synthesizes a missing id, strips unknown keys, caps the
                # list at 8, and drops invalid/over-size `art`. The
                # choices-required gate still fires on the CLEANED result, so a
                # living turn left with no usable choice is still refused.
                "choices": {"type": "array"},
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
                "memoryEvents": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {"type": "string", "maxLength": 96},
                    "description": (
                        "Canonical event ids (from `memoryCandidates` or an earlier "
                        "turn's memory) whose full record you want now, with the "
                        "entities they involve. A bounded look, never the whole "
                        "graph."
                    ),
                },
            },
        },
    },
    {
        "name": "endless_mount_scene",
        "description": (
            "Put a purpose-built scene in front of the player — a region map, a "
            "relationship web, a family or skill tree, a ledger, a choice laid out "
            "as something other than a list. `spec` is {title?, elements:[...]}, and "
            "each element is one of these kinds: heading, text, note, stat, bar, "
            "keyvalue, list, table, choice, divider, grid, links, tree. For a map use "
            "`grid` ({columns, cells:[{label, note?, mark?}]}); for a relationship web "
            "use `links` ({nodes:[{id, label}], edges:[{from, to, label?}]}); for a "
            "hierarchy use `tree` ({nodes:[{id, label, parent?, note?}]}). You give the "
            "STRUCTURE — cells, nodes, edges, parents — and NEVER any coordinates or "
            "markup; the app computes every position and draws it. Optionally set "
            "`region` to group this scene under a system tab on a phone — one of "
            "`status` (the person), `world` (the world around them), `pack` (what "
            "they carry), `tasks` (what is open), or your own word for anything else "
            "— and `label` for that tab's short name; both are optional."
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
                "region": {"type": "string", "maxLength": 24},
                "label": {"type": "string", "maxLength": 24},
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
        "name": "endless_paint_backdrop",
        "description": (
            "Ask for background art behind the story — you do NOT draw it. Pass a "
            "short BRIEF and a separate illustrator paints the SVG and hangs it "
            "behind this page while you move on; call this BEFORE endless_advance_turn "
            "and never wait for it. The brief is the art direction, in a few lines: "
            "the turn's irreversible change or mood, one dominant image, a small "
            "palette, at most one motion verb (or none), and how it should differ "
            "from the previous backdrop — plus, if you want one, the common motif for "
            "the choice buttons. Describe the picture; never write SVG here. Setting a "
            "new one replaces the old, so ask for a fresh backdrop at a major turning "
            "point or a real jump in time or place, and simply omit this call when the "
            "current background still fits."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "brief"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "brief": {"type": "string", "maxLength": 2000},
            },
        },
    },
    {
        "name": "endless_commit_backdrop",
        "description": (
            "Hang a finished backdrop behind a page. This is the ILLUSTRATOR's "
            "commit — `markup` is a single self-contained SVG image, and `turn` is "
            "the page it belongs to (given to you in your task). Optionally also pass "
            "`buttons`: a second SVG, the common motif shown behind the ordinary "
            "choice buttons this scene. Refused if either is not an <svg> document or "
            "carries script, an event handler, <foreignObject>, or an external link."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "turn", "markup"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "turn": {"type": "integer", "minimum": 0},
                "markup": {"type": "string", "maxLength": 24000},
                "buttons": {"type": "string", "maxLength": 8000},
            },
        },
    },
    {
        "name": "endless_clear_backdrop",
        "description": (
            "Remove the background art, returning the story to the plain page. "
            "Idempotent — clearing when there is none is fine."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId"],
            "additionalProperties": False,
            "properties": {"runId": _RUN_ID},
        },
    },
    {
        "name": "endless_export_world",
        "description": (
            "Export a world as one portable file — its rulebook, its compiled "
            "structure, and any scenes built for it — so it can be replayed or "
            "handed to someone else. This writes out the WHOLE world; it does not "
            "generate a capability pack (that is compilation, done at import)."
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
    {
        "name": "endless_read_draft",
        "description": (
            "Read the raw text a player pasted to turn into a new world. Returns it "
            "verbatim as `rawText`. You then clean and compile it and call "
            "endless_submit_world_draft. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["draftId"],
            "additionalProperties": False,
            "properties": {"draftId": {"type": "string", "maxLength": 72}},
        },
    },
    {
        "name": "endless_submit_world_draft",
        "description": (
            "Store your compiled world for the player to review. Pass the draftId, "
            "the CLEANED rulebook `prose` (kept verbatim for play — strip anything "
            "that is not playable in this framework), and the compiled `header` (an "
            "object shaped per your brief). Every id in the header — the world id and "
            "every nested id (styles, opening, panels, fields, endings, chapters, "
            "lore) — must be a lowercase-hyphen slug like `birth-city`, never "
            "`birthCity`; that is the most common first-try error. Optionally pass "
            "`dropped`: short notes on what you removed as unplayable, shown to the "
            "player in the review. The header is validated exactly like a hand-written "
            "world; on failure the draft records the problem so it can be fixed — by "
            "you on a retry, or by the player talking to you in chat."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["draftId", "prose", "header"],
            "additionalProperties": False,
            "properties": {
                "draftId": {"type": "string", "maxLength": 72},
                "prose": {"type": "string", "maxLength": 600000},
                "header": {"type": "object"},
                "dropped": {"type": "array", "items": {"type": "string"}},
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

#: A stored run id is a bare uuid4 hex (store._RUN_ID_RE). The addressing hands it
#: over bare, but a narrator sometimes prepends "run-"/"run_" (the slot-key shape),
#: which the store then rejects as malformed and the opening read fails. Since a real
#: id never starts with "run", that prefix is safe to strip.
_BARE_RUN_ID = re.compile(r"^[0-9a-f]{32}$")


def _normalize_run_id_arg(args: dict[str, Any]) -> None:
    """Strip a stray ``run-``/``run_`` prefix off ``runId`` in place, when the rest
    is a bare run id. Tolerates the one id-mangling the narrator model repeats
    despite the addressing telling it to use the id verbatim."""
    rid = args.get("runId")
    if not isinstance(rid, str):
        return
    for prefix in ("run-", "run_"):
        if rid.startswith(prefix) and _BARE_RUN_ID.match(rid[len(prefix):]):
            args["runId"] = rid[len(prefix):]
            return
    # Surrounding whitespace or a case-mangle of an otherwise-bare id. A stored id
    # is uuid4().hex — always 32 lowercase hex — so if the trimmed, lowercased value
    # is a bare id, that is the id the narrator meant; any other value is left alone.
    trimmed = rid.strip().lower()
    if trimmed != rid and _BARE_RUN_ID.match(trimmed):
        args["runId"] = trimmed


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
        allowed = schema.get("enum")
        if allowed is not None and value not in allowed:
            raise ToolInputError(path, f"one of {', '.join(allowed)}, got {value!r}")
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


def _drafts() -> DraftStore:
    """World-draft store, self-located from this process's own data dir — the same
    files the backend route process created."""
    return DraftStore(_DATA)


def _scene_ledger(run_id: str) -> SceneLedger:
    """A handle that can reach ``scenes.json`` and nothing else.

    This is why a scene call cannot write panels, chronicle, or facts: not
    because it declines to, but because it is never handed anything that could.
    """
    return SceneLedger(_DATA, run_id)


def _backdrop_store(run_id: str) -> BackdropStore:
    """A handle that can reach ``backdrop.json`` and nothing else — the same
    one-file confinement the scene ledger has, so a backdrop call can never write
    panels, chronicle, or facts."""
    return BackdropStore(_DATA, run_id)


def _backdrop_turn(run_id: str) -> int:
    """The page a backdrop being set/cleared belongs to — the turn the narrator is
    writing. That is the in-flight (pending) turn when one is being written, else the
    latest committed turn. Binding by this turn is what lets re-reading a page
    restore the scene it had. Best-effort: falls back to 0 if the store is
    unavailable, so setting a backdrop never fails over turn bookkeeping."""
    try:
        store = _store()
        committed = int((store.read_state(run_id) or {}).get("turn") or 0)
        pending = store.read_pending(run_id) or {}
        pend_turn = int(pending.get("turn") or 0)
        return pend_turn if pend_turn > committed else committed
    except Exception:  # noqa: BLE001
        return 0


#: The only keys a stored choice carries. Anything else the narrator sends is
#: model noise and is stripped rather than stored.
_CHOICE_KEYS = ("id", "label", "fateful", "art")

#: The only keys a stored gain carries (the anti-halo `source` is optional).
_GAIN_KEYS = ("field", "amount", "source")


def _clean_choices(choices: list[Any]) -> list[Any]:
    """The gate for the player's choices — the schema only bounds the array, so
    this is what makes each entry usable.

    An entry with no usable ``label`` is dropped (a button with no text is nothing
    to click); a missing/blank ``id`` is synthesized (``c<index>``) so the click
    always resolves; unknown keys are stripped; the list is capped at 8. Any
    narrator-designed ``art`` (a small SVG shown behind the button) is validated
    exactly as a backdrop and DROPPED if invalid or over-size, rather than refusing
    the turn — a fateful choice losing its art still narrates a real month. The
    choices-required gate runs on THIS result, so dropping every entry on a living
    turn still (correctly) forces a resend.
    """
    out: list[Any] = []
    for i, c in enumerate(choices):
        if not isinstance(c, dict):
            continue
        label = c.get("label")
        if not (isinstance(label, str) and label.strip()):
            continue
        clean = {k: v for k, v in c.items() if k in _CHOICE_KEYS}
        clean["label"] = label[:200]
        cid = clean.get("id")
        clean["id"] = cid[:64] if isinstance(cid, str) and cid.strip() else f"c{i}"
        art = clean.get("art")
        if isinstance(art, str) and art.strip() and len(art) <= 6000:
            try:
                clean["art"] = compile_backdrop(art)
            except BackdropError:
                clean.pop("art", None)
        else:
            clean.pop("art", None)
        out.append(clean)
        if len(out) >= 8:
            break
    return out


def _clean_gains(gains: list[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    """Salvage the anti-halo ``gains`` list the way choices are salvaged. An entry
    with no string ``field`` anchors nothing, so it is dropped; unknown keys are
    stripped; the list is capped at 12. Each drop is returned as a warning so the
    narrator learns of it, and the turn commits regardless. Mirrors _clean_choices.
    """
    out: list[Any] = []
    drops: list[dict[str, Any]] = []
    for i, g in enumerate(gains):
        path = f"gains[{i}]"
        if not isinstance(g, dict):
            drops.append(
                {
                    "panel": "gains",
                    "field": path,
                    "expected": "an object with a `field`",
                    "detail": f"Dropped the gain at {path}: it is not an object.",
                }
            )
            continue
        field = g.get("field")
        if not (isinstance(field, str) and field.strip()):
            drops.append(
                {
                    "panel": "gains",
                    "field": f"{path}.field",
                    "expected": "a non-empty field name",
                    "detail": f"Dropped the gain at {path}: it names no field.",
                }
            )
            continue
        out.append({k: v for k, v in g.items() if k in _GAIN_KEYS})
        if len(out) >= 12:
            break
    return out, drops


def _sanitize_read_runtime_args(args: dict[str, Any]) -> None:
    """Normalize the optional, model-manglable args of the MANDATORY first read so
    a bad one never refuses it — the narrator must be able to look before it
    narrates. ``recentTurns`` is clamped to [0, 50] (dropped if not an int);
    ``since`` is dropped if not a string and truncated to 64; ``memoryEvents`` and
    ``chapters`` are coerced to bounded string lists; ``includeProse`` is coerced to
    a bool. ``runId`` is left for _validate — the read cannot resolve without it.
    Mirrors the advance_turn recovery block.
    """
    if "recentTurns" in args:
        rt = args.get("recentTurns")
        if isinstance(rt, bool) or not isinstance(rt, int):
            args.pop("recentTurns", None)
        else:
            args["recentTurns"] = max(0, min(50, rt))
    if "since" in args:
        since = args.get("since")
        if not isinstance(since, str):
            args.pop("since", None)
        elif len(since) > 64:
            args["since"] = since[:64]
    if "memoryEvents" in args:
        v = args.get("memoryEvents")
        args["memoryEvents"] = (
            [str(e)[:96] for e in list(v)][:6] if isinstance(v, list) else []
        )
    if "chapters" in args:
        v = args.get("chapters")
        args["chapters"] = (
            [str(c)[:64] for c in list(v)][:8] if isinstance(v, list) else []
        )
    if "includeProse" in args:
        args["includeProse"] = bool(args.get("includeProse"))


# ── handlers ─────────────────────────────────────────────────────────────


#: Keys the APP owns. The narrator never declares them — they are bookkeeping, not
#: story — so a commit carries them forward instead of letting a full-state
#: declaration drop them. Losing ``worldId`` this way made a life unreadable the
#: moment its first turn landed: the play view could no longer find its world.
RESERVED_STATE_KEYS = ("worldId", "style", "language", "opening", "status", "role", "granted", "milestones")

#: State keys that MERGE forward at the sub-key level instead of replacing wholesale.
#: `digest` (world news by category) and `relations` (per-figure standing) are
#: cumulative dicts the narrator would otherwise re-declare in full every turn — most
#: of it unchanged boilerplate. Merging lets it declare only the categories/figures
#: that moved this span; an omitted sub-entry PERSISTS, and a sub-value of null or ""
#: RETIRES that entry (the clear sentinel). Omitting the whole key carries the prior
#: forward unchanged. Everything NOT listed here still replaces wholesale — a plain
#: fact the narrator stops declaring is a fact that stopped being true.
MERGE_STATE_KEYS = ("digest", "relations")


def _merge_forward(prior: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """A partial declaration merged onto the prior value at the sub-key level.

    A key present in ``incoming`` replaces that one entry; a key whose value is
    ``None`` or ``""`` retires it; every other entry in ``prior`` is kept. Used for
    ``MERGE_STATE_KEYS`` so the narrator can send only what changed this turn.
    """
    merged = dict(prior) if isinstance(prior, dict) else {}
    for key, value in incoming.items():
        if value is None or value == "":
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _apply_milestones(run_id: str, state: dict[str, Any], prev: dict[str, Any]) -> None:
    """Record any milestones newly reached this turn into a reserved state key.

    Achievements are permanent and app-owned: the achieved set is rebuilt from the
    PRIOR committed state (not the narrator's declaration, which must not be able to
    grant or revoke one), then any milestone whose `when` is now true is added and
    never removed. Evaluated with the same interpreter as endings. Best-effort — a
    world with no milestones, or a bad condition, simply records nothing."""
    world_id = state.get("worldId")
    if not isinstance(world_id, str) or not world_id:
        return
    worlds = _DATA / "worlds"
    language = state.get("language")
    path = worlds / f"{world_id}.md"
    if isinstance(language, str) and language:
        variant = worlds / f"{world_id}.{language}.md"
        if variant.is_file():
            path = variant
    if not path.is_file():
        return
    milestones = read_world(path.read_text(encoding="utf-8")).template.milestones
    if not milestones:
        return
    achieved = [m for m in (prev.get("milestones") or []) if isinstance(m, str)]
    have = set(achieved)
    for m in milestones:
        if m.id in have:
            continue
        try:
            if m.when.evaluate(state):
                achieved.append(m.id)
                have.add(m.id)
        except Exception:  # noqa: BLE001
            pass
    state["milestones"] = achieved


def _apply_systems(
    run_id: str, state: dict[str, Any], prev: dict[str, Any], gains: list[Any]
) -> None:
    """Apply the world's declared systems at commit, writing derived state the
    narrator may read but not own. Reads base values from the PRIOR committed state
    so a value is the app's regardless of what the narrator declared. Best-effort — a
    world with no systems does nothing, and a bad system never blocks the turn."""
    world_id = state.get("worldId")
    if not isinstance(world_id, str) or not world_id:
        return
    worlds = _DATA / "worlds"
    language = state.get("language")
    path = worlds / f"{world_id}.md"
    if isinstance(language, str) and language:
        variant = worlds / f"{world_id}.{language}.md"
        if variant.is_file():
            path = variant
    if not path.is_file():
        return
    template = read_world(path.read_text(encoding="utf-8")).template
    if template.systems:
        apply_systems(template, state, prev, gains)


def _resolve_handoff(template: Any) -> dict[str, Any]:
    """What the world hands the narrator at the opening (`handToAgent`): the named
    lore / systems / roles, resolved to payloads. `<kind>.*` takes all of a kind. A
    ref that resolves to nothing simply contributes nothing — never an error."""
    refs = getattr(template, "hand_to_agent", None) or []
    if not refs:
        return {}
    stars: set[str] = set()
    want: dict[str, set[str]] = {"lore": set(), "systems": set(), "roles": set()}
    for r in refs:
        kind, _, ident = str(r).partition(".")
        if ident == "*":
            stars.add(kind)
        elif kind in want:
            want[kind].add(ident)

    def picked(kind: str, ident: str) -> bool:
        return kind in stars or ident in want[kind]

    out: dict[str, Any] = {}
    lore = [
        {"id": e.id, "name": e.name or e.id, "summary": e.summary, "text": e.text}
        for e in template.lore if picked("lore", e.id)
    ]
    systems = [
        {"id": s.id, "kind": s.kind, "into": s.into}
        for s in template.systems if picked("systems", s.id)
    ]
    roles = [
        {"id": r.id, "name": r.name or r.id, "summary": r.summary, "grants": r.grants}
        for r in template.roles if picked("roles", r.id)
    ]
    if lore:
        out["lore"] = lore
    if systems:
        out["systems"] = systems
    if roles:
        out["roles"] = roles
    return out


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
                    "life reaches you no other way. Then resend the WHOLE call — "
                    "prose, choices, state (and memory) — not just part of it."
                ),
            }

    # The world's memory is enrichment, not the story (like milestones and systems):
    # it is SALVAGED, never rejected whole. sanitize_memory returns the block with only
    # its valid parts kept — a structurally broken event is dropped, but an otherwise
    # good event keeps its title/summary and loses only the references that do not
    # resolve — so a stray slip (a space in a CJK id, one unopened thread tag) never
    # costs the real memory around it, let alone the prose and choices already written.
    # Each dropped piece is surfaced as a non-blocking warning so the narrator can
    # re-declare it later. Facts are never back-filled from prose, so a block whose
    # parts all fail simply records no structured memory.
    memory = args.get("memory")
    memory_drops: list[dict[str, Any]] = []
    if memory is not None:
        index = memory_graph.build_index(store.read_chronicle(run_id))
        clean, memory_drops = memory_graph.sanitize_memory(memory, index, turn=turn)
        memory = clean or None

    # Enrichment lists are salvaged, never rejected: gains with no `field` are
    # dropped-and-warned, and the notable-events log is coerced to bounded strings.
    gains, gain_drops = _clean_gains(args.get("gains") or [])
    events = [str(e)[:200] for e in (args.get("events") or [])][:12]

    state = dict(args["state"])
    # The declaration is the story's whole state, so it REPLACES the previous one
    # — a field the narrator stops declaring is a fact that stopped being true.
    # The app's own keys are the exception: they were never the narrator's to
    # declare, and dropping them silently breaks the page rather than the story.
    for key in RESERVED_STATE_KEYS:
        if key in current and key not in state:
            state[key] = current[key]
    # The cumulative panels (digest, relations) merge forward instead of replacing,
    # so the narrator declares only what moved this span rather than re-sending the
    # whole block every turn. Omitted entirely → carry the prior forward; declared
    # partially → merge onto the prior; a null/"" sub-value retires that entry.
    for key in MERGE_STATE_KEYS:
        prior = current.get(key)
        if key not in state:
            if isinstance(prior, dict) and prior:
                state[key] = prior
        elif isinstance(state[key], dict) and isinstance(prior, dict):
            state[key] = _merge_forward(prior, state[key])
    state["turn"] = turn
    # Record milestones reached this turn (permanent, app-owned) before committing.
    try:
        _apply_milestones(run_id, state, current)
    except Exception:  # noqa: BLE001
        pass  # an achievement is a reward, never a reason to block a committed turn
    # Then the world's systems: mechanics the backend runs off this turn's gains and
    # the prior state, writing derived keys (xp/level, resources, unlocks) the
    # narrator declared but does not own.
    try:
        _apply_systems(run_id, state, current, gains)
    except Exception:  # noqa: BLE001
        pass  # a system is enrichment; a bad one never blocks a committed turn

    # Load the world pack once (reused for the choices gate and the panel warnings).
    pack = None
    _wid = state.get("worldId")
    if isinstance(_wid, str) and _wid:
        try:
            _worlds = _DATA / "worlds"
            _lang = state.get("language")
            _path = _worlds / f"{_wid}.md"
            if isinstance(_lang, str) and _lang and (_worlds / f"{_wid}.{_lang}.md").is_file():
                _path = _worlds / f"{_wid}.{_lang}.md"
            if _path.is_file():
                pack = read_world(_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pack = None

    # A living turn MUST offer choices; only a terminal turn may omit them. Refuse a
    # choiceless non-ending turn BEFORE anything commits, so the player is never handed
    # a page with no action. Terminal = the narrator passes `ending: true`, or the
    # committed state fires a declared world ending. Gated on a loadable pack: a
    # synthetic turn with no world cannot be judged for endings and is left alone.
    choices = _clean_choices(args.get("choices") or [])
    if not choices and pack is not None:
        fired = any(
            e.when is not None and e.when.evaluate(state) for e in pack.template.endings
        )
        if args.get("ending") is not True and not fired:
            return {
                "committed": False,
                "turn": committed,
                "reason": "choices-required",
                "detail": (
                    "This turn has no `choices`, so the player would have nothing to "
                    "do. Resend the WHOLE call with `choices`. If the life or world "
                    "has ended, pass `ending: true` (or declare state that fires a "
                    "world ending) — only a terminal turn may omit choices."
                ),
            }
    store.commit_state(run_id, state)
    # What the player asked for, recovered from the in-flight record the app wrote
    # before speaking. The narrator is told the intent in prose and never echoes it
    # back, so this is the only place it can be preserved — and without it, reviewing
    # a past month shows the outcome with the choice that caused it missing.
    asked = store.read_pending(run_id) or {}
    action = str(asked.get("action") or "") if int(asked.get("turn") or 0) == turn else ""

    entry: dict[str, Any] = {
        "turn": turn,
        "prose": args["prose"],
        "action": action,
        "choices": choices,
        # What this turn marked notable, and what it credited a gain to. Both
        # are how the anti-halo readings become measurable; `source` is
        # deliberately NOT required — a narrator that forgot to say where five
        # gold came from has still narrated a real turn, and the omission is
        # surfaced to the next turn rather than refused here.
        "events": events,
        "gains": gains,
    }
    if memory is not None:
        # Same JSON record as the prose (design §6.2): the fact delta and the
        # story it narrates commit together or not at all, and every index over
        # them is derived and rebuildable from this line.
        entry["memory"] = memory
    store.append_turn(run_id, entry)
    result: dict[str, Any] = {"committed": True, "turn": turn}
    # Non-blocking corrections: a dropped memory block, and an always-on panel that
    # resolved blank (renamed field ids). The turn is committed either way. (A
    # choiceless non-ending turn is refused ABOVE, before commit, not warned here.)
    warnings: list[dict[str, Any]] = []
    for _drop in memory_drops:
        warnings.append(
            {
                "panel": "memory",
                "field": _drop["field"],
                "expected": _drop["expected"],
                "detail": _drop["detail"],
            }
        )
    # Salvaged enrichment: gains that named no field, and stray top-level args the
    # schema would once have refused the whole turn over.
    warnings.extend(gain_drops)
    for _key in args.get("_dropped_top_level") or []:
        warnings.append(
            {
                "field": _key,
                "expected": "a declared field of endless_advance_turn",
                "detail": (
                    f"Dropped the unknown top-level argument {_key!r}; the turn "
                    "committed without it."
                ),
            }
        )
    declared = any(k not in RESERVED_STATE_KEYS and k != "turn" for k in state)
    if pack is not None and declared:
        try:
            empties = always_panels_empty(pack.template, state)
            if empties:
                warnings.extend(empties)
                result["hint"] = (
                    "A panel below came out blank even though you declared state. "
                    "Declare each field by the exact id shown in `declareById`, "
                    "inside the `state` you pass here (at the top level, or nested "
                    "under `state.<panel>`) — a value under a renamed key or a "
                    "label does not reach the panel and shows as empty."
                )
        except Exception:  # noqa: BLE001
            pass  # a warning is a nicety; never let it disturb a committed turn
    if warnings:
        result["warnings"] = warnings
    return result


#: How many months one read returns when the narrator does not say.
#:
#: Inherited from the rolling-summary era, where turns beyond this many were folded
#: into an app-computed summary and pushed into every prompt. The summary is gone —
#: the narrator pages its own history from the newest end now — but the number kept
#: its meaning: about a year of months is what carries the texture of where a life
#: currently is, and anything older is something to go and look up rather than
#: something to be handed unasked.
RECENT_TURNS = 12

#: How many lore entries one read may surface. A theme-heavy turn can match many
#: keyword entries at once (measured: 9 full entries), which is the wholesale dump
#: the narrator's prompt forbids; the cap keeps only the most relevant few.
MAX_LORE = 4


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
    # Turn 0 is the app's own bridge record (design §9), not a narrated month:
    # the narrator learns of an inheritance through the SUMMARY below and the
    # graph, never by re-reading the raw record as if it were story.
    lived = [e for e in chronicle if int(e.get("turn") or 0) >= 1]
    recent = args.get("recentTurns", RECENT_TURNS)
    fingerprint = store.fingerprint(state)

    # Resolved here, ABOVE the lore block, because lore now respects it too: a
    # delta read (a baseline the narrator could only still name if its context
    # survived) means the continuous session already holds the world's standing
    # setting, so `always` lore rides only on a FULL read — the same rule the
    # recent months, restraint reading and table of contents already follow.
    since = str(args.get("since") or "")
    baseline = store.baseline_for(run_id, since) if since else None
    full_read = baseline is None

    out: dict[str, Any] = {
        "runId": run_id,
        "turn": int(state.get("turn") or 0),
        # Hand this back as `since` next turn and only the changes come with it.
        "fingerprint": fingerprint,
        "scenes": _scene_ledger(run_id).mounted(),
    }

    # Lorebook — keyword-triggered setting, complementing the state-gated chapters.
    # The world's reserve of background, surfaced only when a name/place/force it
    # names shows up in the recent months or the player's action this turn (matched
    # case-insensitively as substrings); `always` entries surface every turn. This
    # is the lighter, ST-lorebook-style companion to chapters: chapters gate on
    # STATE, lore on KEYWORDS.
    try:
        world_id = state.get("worldId")
        if isinstance(world_id, str) and world_id:
            worlds = _DATA / "worlds"
            language = state.get("language")
            lore_path = worlds / f"{world_id}.md"
            if isinstance(language, str) and language:
                variant = worlds / f"{world_id}.{language}.md"
                if variant.is_file():
                    lore_path = variant
            if lore_path.is_file():
                entries = read_world(lore_path.read_text(encoding="utf-8")).template.lore
                if entries:
                    pending = store.read_pending(run_id) or {}
                    action_low = str(pending.get("action") or "").lower()
                    prose_low = "\n".join(
                        str(e.get("prose") or "") for e in lived[-recent:]
                    ).lower()
                    # Rank what surfaces so the few we send are the most relevant:
                    # entries named in the player's ACTION first, then ones only in
                    # recent prose, then `always` entries (full reads only). Capped —
                    # dumping every keyword match (measured: 9 full entries on a
                    # theme-heavy turn) is exactly the "never dump it wholesale" the
                    # narrator's own prompt already forbids, so the cap enforces it
                    # instead of restating it in a per-turn note.
                    ranked: list[tuple[int, Any]] = []
                    for e in entries:
                        keys = [k.lower() for k in e.keys]
                        if action_low and any(k in action_low for k in keys):
                            ranked.append((0, e))
                        elif prose_low and any(k in prose_low for k in keys):
                            ranked.append((1, e))
                        elif e.always and full_read:
                            ranked.append((2, e))
                    ranked.sort(key=lambda t: t[0])
                    matched = [
                        {
                            "id": e.id,
                            **({"name": e.name} if e.name else {}),
                            "text": e.text,
                        }
                        for _, e in ranked[:MAX_LORE]
                    ]
                    if matched:
                        out["lore"] = matched
    except Exception:  # noqa: BLE001
        pass  # lore is an enrichment; a failure here must never break a runtime read

    # The world's memory, recalled — never pushed whole (design §7.1). The
    # system offers a handful of old events scored by deterministic rules; the
    # narrator decides whether any of them naturally comes due this turn. Using
    # one means declaring `echoes` on the new event in the commit — mentioning
    # it in prose alone creates nothing.
    graph = memory_graph.build_index(chronicle)
    if graph["events"]:
        pending = store.read_pending(run_id) or {}
        candidates = memory_graph.recall_candidates(
            graph,
            turn=int(state.get("turn") or 0) + 1,
            action=str(pending.get("action") or ""),
        )
        if candidates:
            # Drop the internal scoring fields (`reasons`, `lastEchoedTurn`): they
            # exist for the recall ranking, not for the narrator, which acts on the
            # event's id/title/summary. The "declare echoes when you use one" rule
            # lives in the endless_advance_turn tool description, so no per-turn
            # memoryNote is needed.
            out["memoryCandidates"] = [
                {k: v for k, v in c.items() if k not in ("reasons", "lastEchoedTurn")}
                for c in candidates
                if isinstance(c, dict)
            ]
    wanted_events = args.get("memoryEvents") or []
    if wanted_events:
        out["memoryEvents"] = memory_graph.event_neighbourhood(
            graph, [str(e) for e in wanted_events]
        )

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
        out["recentTurns"] = lived[-recent:] if recent else []
    elif baseline is None:
        out["recentTurns"] = lived[-recent:] if recent else []
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
            "density": event_density(lived),
            "attribution": attribution(lived),
            # The same readings as a sentence, in the world's own language. Kept
            # because a narrator acts on "you have handed this life three windfalls
            # in six months" and merely notices `{"perTurn": 3.0}`.
            "note": compose_restraint(lived, state.get("language") or "en"),
        }
        # What the last life left to this one (design §9): names and one-line
        # summaries, stamped by the bridge — never the ancestor's graph, whose
        # run id is not even in this payload. Rides only on a full read, like
        # everything else a continuous session already holds.
        from legacy import narrator_summary

        inherited = narrator_summary(graph, str(state.get("language") or "en"))
        if inherited is not None:
            out["legacy"] = inherited

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
                # The opening groups AND the player's own answer to each — the
                # value is what the narrator must honour (the chosen sex, race,
                # name…). Listing only the questions here, with the answers buried
                # in state.opening, is why a choice like sex went unhonoured. A
                # blank/world-decided group carries no value; the narrator settles
                # those itself.
                answers = state.get("opening")
                answers = answers if isinstance(answers, dict) else {}
                opening_out: list[dict[str, Any]] = []
                for g in pack.template.opening:
                    entry: dict[str, Any] = {
                        "id": g.id, "label": g.label, "worldDecides": g.random,
                    }
                    val = answers.get(g.id)
                    if isinstance(val, (str, int, float)) and str(val).strip():
                        entry["value"] = str(val)
                    opening_out.append(entry)
                out["opening"] = opening_out
                # What the world hands the narrator at the opening: the lore/systems/
                # roles it named in `handToAgent`. Turn 1 has no prior prose for
                # keyword injection to match, so this is how the opening's setting and
                # mechanics reach the narrator; a chosen role's grants seed the state.
                handoff = _resolve_handoff(pack.template)
                if handoff:
                    out["handToAgent"] = handoff
                    out["handToAgentNote"] = (
                        "What this world hands you to open with — its key setting, the "
                        "systems the app runs for you, and the starting archetypes. Weave "
                        "the setting in as it becomes relevant; if the player took a role, "
                        "honour its grants in the state you declare."
                    )
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
    ledger.mount(
        args["sceneId"],
        args["spec"],
        asks=bool(args.get("asks")),
        region=str(args.get("region") or ""),
        label=str(args.get("label") or ""),
    )
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


def _paint_backdrop(args: dict[str, Any]) -> dict[str, Any]:
    """Record the narrator's brief; the backend spawns the illustrator to draw it.

    Bound to the turn the narrator is writing (the in-flight page), so the art the
    illustrator commits lands on the right page even though it arrives a beat later.
    """
    run_id = args["runId"]
    turn = _backdrop_turn(run_id)
    _store().request_backdrop(run_id, turn=turn, brief=args["brief"])
    return {"backdrop": "queued", "turn": turn}


def _commit_backdrop(args: dict[str, Any]) -> dict[str, Any]:
    """The illustrator's commit: validate the SVG and hang it on ``turn``."""
    turn = int(args["turn"])
    version = _backdrop_store(args["runId"]).set(args["markup"], args.get("buttons"), turn)
    return {"backdrop": "committed", "version": version, "turn": turn}


def _clear_backdrop(args: dict[str, Any]) -> dict[str, Any]:
    _backdrop_store(args["runId"]).clear(_backdrop_turn(args["runId"]))
    return {"backdrop": "cleared"}


def _export_world(args: dict[str, Any]) -> dict[str, Any]:
    world_id = args["worldId"]
    if not world_id or "/" in world_id or "\\" in world_id or world_id.startswith("."):
        raise ToolInputError("arguments.worldId", "a world id, not a path")
    path = _DATA / "worlds" / f"{world_id}.md"
    if not path.is_file():
        raise WorldError(f"no such world: {world_id}")

    world = read_world(path.read_text(encoding="utf-8"))
    out_dir = _DATA / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{world_id}.md"
    tmp = target.with_suffix(".md.tmp")
    tmp.write_text(serialize_world(world), encoding="utf-8")
    os.replace(tmp, target)
    return {"worldId": world_id, "path": str(target), "bytes": target.stat().st_size}


def _read_draft(args: dict[str, Any]) -> dict[str, Any]:
    """Hand the worldsmith the pasted text AND the authoritative spec to follow.

    The brief is assembled from ``compile.py`` (COMPILER_BRIEF for structure +
    CLEANING_CONTRACT for playability), never duplicated into the agent prompt, so
    the one place the header spec lives is the same one the gate enforces.
    """
    draft_id = args["draftId"]
    store = _drafts()
    raw = store.read_raw(draft_id)
    store.note_step(draft_id, "endless_read_draft", stage="reading")
    return {"rawText": raw, "brief": f"{COMPILER_BRIEF}\n\n{CLEANING_CONTRACT}"}


def _submit_world_draft(args: dict[str, Any]) -> dict[str, Any]:
    """Validate the worldsmith's compiled world and store it for review.

    The header is checked by ``accept_compiled_header`` — the SAME gate a
    hand-written world goes through — so an unplayable structure (a bad primitive,
    a panel with no `always`, an illegal `when`) is refused here rather than at
    play time. A refusal is stored as the draft's problem, not raised, so the
    review page can say what could not be worked out.
    """
    draft_id = args["draftId"]
    prose = args["prose"]
    header = args["header"]
    dropped = [d for d in (args.get("dropped") or []) if isinstance(d, str)]
    store = _drafts()
    store.note_step(draft_id, "endless_submit_world_draft", stage="writing")

    result = accept_compiled_header(prose, header)
    if not result.ok or result.pack is None or result.world_text is None:
        store.store_failed(
            draft_id,
            result.problem or "the world could not be compiled",
            field=result.field or "",
        )
        return {"stored": True, "accepted": False, "problem": result.problem, "field": result.field}

    world_id = result.pack.template.id
    store.store_ready(
        draft_id,
        world_text=result.world_text,
        world_id=world_id,
        preview=preview(result.pack),
        warnings=result.warnings,
        referenced_paths=result.referenced_paths,
        dropped=dropped,
    )
    return {"stored": True, "accepted": True, "worldId": world_id, "warnings": result.warnings}


_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "endless_advance_turn": _advance_turn,
    "endless_read_runtime": _read_runtime,
    "endless_mount_scene": _mount_scene,
    "endless_update_scene": _update_scene,
    "endless_await_scene": _await_scene,
    "endless_dismiss_scene": _dismiss_scene,
    "endless_paint_backdrop": _paint_backdrop,
    "endless_commit_backdrop": _commit_backdrop,
    "endless_clear_backdrop": _clear_backdrop,
    "endless_export_world": _export_world,
    "endless_read_draft": _read_draft,
    "endless_submit_world_draft": _submit_world_draft,
}


# ── protocol ─────────────────────────────────────────────────────────────


def list_tools() -> list[dict[str, Any]]:
    return _TOOLS


#: A backslash that does NOT begin a valid JSON escape (``\" \\ \/ \b \f \n \r \t
#: \uXXXX``). A narrator that hand-writes a JSON string for ``state``/``memory``
#: often leaves a lone backslash (a Windows path, a LaTeX-ish token, an escaped
#: quote it forgot to double), which makes the whole string un-parseable and wastes
#: the turn. Doubling exactly those backslashes repairs the common case without
#: touching a real escape.
_BAD_JSON_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')


def _repair_json_escapes(raw: str) -> str:
    return _BAD_JSON_ESCAPE.sub(r"\\\\", raw)


def _lenient_json_object(raw: str) -> dict[str, Any] | None:
    """Parse *raw* as a JSON object, repairing a malformed escape once if needed.

    A narrator sometimes double-encodes ``state``/``memory`` as a JSON STRING, and
    that string sometimes carries a malformed escape (a lone backslash). Both are
    recoverable server-side rather than worth a refused, wasted turn: try a plain
    parse, then a parse with stray backslashes doubled. Returns the object, or
    ``None`` when it is not a recoverable JSON object.
    """
    text = raw.strip()
    if not text:
        return None
    for attempt in (text, _repair_json_escapes(text)):
        try:
            value = json.loads(attempt)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(value, dict):
            return value
    return None


def call_tool(name: str, args: dict[str, Any]) -> str:
    """Validate, dispatch, and answer as JSON text.

    Every failure is reported as data rather than raised: a raised exception
    reaches the narrator as a protocol error it cannot act on, while a named
    field is something it can fix on the next attempt.
    """
    dropped_top_level: list[str] = []
    try:
        # A narrator sometimes prepends "run-"/"run_" to the run id despite the
        # addressing giving it bare; strip it before anything validates or looks it
        # up, so the opening read does not fail on an id-mangling the model repeats.
        _normalize_run_id_arg(args)
        # The mandatory first read must never be refused over a bad OPTIONAL arg —
        # the narrator has to be able to look before it narrates. Normalize/drop the
        # enrichment args before the schema sees them.
        if name == "endless_read_runtime":
            _sanitize_read_runtime_args(args)
        # A narrator that double-encodes an object sends it as a JSON STRING, and
        # that string sometimes carries a malformed escape — both would otherwise
        # refuse the whole turn. Recover server-side instead of wasting a round.
        #
        # `state` is REQUIRED, so it is recovered (parse, then parse-with-repair)
        # and left as-is only when unrecoverable — the schema then still gives the
        # narrator the clear "got str" message. `memory` is enrichment, so an
        # unrecoverable block is DROPPED and the turn still commits.
        if name == "endless_advance_turn":
            if isinstance(args.get("state"), str):
                recovered = _lenient_json_object(args["state"])
                if recovered is not None:
                    args["state"] = recovered
            if isinstance(args.get("memory"), str):
                recovered = _lenient_json_object(args["memory"])
                if recovered is not None:
                    args["memory"] = recovered
                else:
                    args.pop("memory", None)
            # A stray top-level key (a model typo, a field from a different tool) is
            # DROPPED-and-warned rather than letting `additionalProperties: False`
            # refuse the whole turn. The prose/choices/state the narrator DID send
            # are the story; one misplaced key must not cost them.
            _props = _INPUT_SCHEMAS["endless_advance_turn"].get("properties", {})
            for _key in [k for k in args if k not in _props]:
                dropped_top_level.append(_key)
                args.pop(_key, None)
        _validate(name, args)
    except ToolInputError as exc:
        return json.dumps(
            {"ok": False, "field": exc.field, "expected": exc.expected, "applied": False},
            ensure_ascii=False,
        )

    handler = _HANDLERS.get(name)
    if handler is None:  # unreachable: _validate rejects unknown names first
        return json.dumps({"ok": False, "error": "unknown tool", "applied": False})

    # Count this call as a unit of in-flight progress, so the play page advances a
    # cell per tool call. Best-effort and before dispatch (the call is happening
    # regardless of what the handler returns); it only records while a turn is
    # actually pending, and never blocks the tool.
    run_id = args.get("runId")
    if isinstance(run_id, str) and run_id:
        try:
            _store().note_tool_call(run_id, name)
        except Exception:  # noqa: BLE001
            pass

    try:
        call_args = dict(args)
        if dropped_top_level:
            # Handed to the handler under a private key (added AFTER validation, so
            # the schema never sees it) so it can surface each drop as a warning.
            call_args["_dropped_top_level"] = dropped_top_level
        result = handler(call_args)
    except ToolInputError as exc:
        return json.dumps(
            {"ok": False, "field": exc.field, "expected": exc.expected, "applied": False},
            ensure_ascii=False,
        )
    except (StoreError, WorldError, SceneLedgerError, BackdropError, DraftError) as exc:
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
