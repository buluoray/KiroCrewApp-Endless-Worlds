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
import math
import os
import re
import sys
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

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


def _warn(message: str) -> None:
    """Report a degradation the operator has to fix, without failing the tool.

    stderr, not stdout: stdout is the protocol channel kiro-cli is parsing.
    """
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr)


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

import memory_graph  # noqa: E402
from backdrop import (  # noqa: E402
    BackdropDraftStore,
    BackdropError,
    BackdropStore,
    compile_backdrop,
    strip_motion,
)
from backdrop_timing import BackdropTimeline  # noqa: E402
from chapters import (  # noqa: E402
    ChapterError,
    brief,
    contents,
    opened_since,
    read_chapter,
)
from compile import CLEANING_CONTRACT, COMPILER_BRIEF, accept_compiled_header, preview  # noqa: E402
from drafts import DraftError, DraftStore  # noqa: E402
from halo import attribution, compose_restraint, event_density, gate_digest  # noqa: E402
from perf import TurnPerf  # noqa: E402
from phototrace import (  # noqa: E402
    TRACE_CANDIDATE_COUNT,
    CandidateStore,
    MissCache,
    TracerUnavailable,
    TraceStore,
    build_underlay_fragment_bounded,
    compose_with_underlay,
    fetch_photo,
    procedural_base_fragment,
    search_candidates,
)
from scenes import (  # noqa: E402
    SceneLedger,
    SceneLedgerError,
    slugify_scene_id,
)
from settings import SPARSE_GAP_TURNS, preferred_style, read_settings  # noqa: E402
from store import RunStore, StoreError, brief_lane, rewrite_brief_style  # noqa: E402
from systems import apply_systems  # noqa: E402
from turn import declaration_shape  # noqa: E402
from view import always_panels_empty, shape_panels  # noqa: E402
from widget import scene_warnings  # noqa: E402
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

#: The id of the life every call addresses. Published as the pattern the store
#: ACTUALLY enforces (``store._RUN_ID_RE``), because a narrator reads this schema as
#: the shape it must produce: the previous value was the sentinel string "run-id",
#: which as a regex reads "must contain run-id" — and a narrator duly sent
#: "run-id-<32 hex>", which the store then refused as malformed. A schema that
#: describes a shape the store rejects is an instruction to fail.
_RUN_ID = {
    "type": "string",
    "pattern": "^[0-9a-f]{32}$",
    "maxLength": 32,
    "description": (
        "The run id EXACTLY as the message addressed to you gives it — 32 lowercase "
        "hex characters, copied verbatim. Do not prefix, wrap, quote or re-case it."
    ),
}

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "endless_advance_turn",
        "description": (
            "Commit one turn: the prose the player reads, the state that follows, "
            "and the choices offered. THE ONLY call that changes a life. A living "
            "turn MUST include `choices` — each an object whose `label` is the "
            "button text the player reads (optional: `id`, `fateful`, `art`, and — "
            "for a moment that earns motion — `effect`: one of "
            "shimmer|aura|embers|ripple, with an optional `tint` hex color); omit "
            "them only on a terminal turn, marked "
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
            'effect "opened" — that declares it, no separate entity needed; only '
            "`advanced`/`resolved` need a thread opened before. Memory is REPAIRED, "
            "not rejected: a namespaced id, a synonym for a closed vocabulary, a "
            "reused key or a missing title are all read and fixed server-side, and "
            "only a reference to something never declared is dropped and warned. "
            "Facts are never extracted from your prose."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "turn", "prose"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "turn": {"type": "integer", "minimum": 1},
                "prose": {"type": "string", "maxLength": 20000},
                "state": {
                    "type": "object",
                    "description": (
                        "The panels this world declares, as endless_read_runtime hands "
                        "them to you — the field ids come from the world, not from "
                        "here. Declare it IN FULL: a field you leave out reads to the "
                        "player as a fact that vanished. `digest` and `relations` are "
                        "the exceptions and merge forward, so there you declare only "
                        "what changed (a null value retires one entry). PREFER "
                        "`statePatch` when you still hold the fingerprint you read — "
                        "it says the same thing in a fraction of the tokens."
                    ),
                },
                "statePatch": {
                    "type": "object",
                    "description": (
                        "Only what changed this turn, merged onto the state named by "
                        "`basedOn`: a nested object where a leaf you send replaces "
                        "that leaf, a null retires it, and everything you do not "
                        "mention stays exactly as you read it. Requires `basedOn` "
                        "(the fingerprint from your endless_read_runtime call this "
                        "turn); if the fingerprint no longer matches, the commit is "
                        "refused and you re-read, then resend. Use `state` instead "
                        "when you have lost the fingerprint."
                    ),
                },
                "basedOn": {
                    "type": "string",
                    "maxLength": 64,
                    "description": (
                        "The `fingerprint` your statePatch is built on. Same "
                        "self-certification as read_runtime's `since`: if you can "
                        "still produce it, the state you are patching is the state "
                        "on file."
                    ),
                },
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
                                    # sanitize_memory reads the kind against KINDS
                                    # and COERCES an unknown one (to the entity's
                                    # established kind, else the generic "object"),
                                    # so a mangled value never refuses the turn nor
                                    # costs the entity. The
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
                #
                # The three salvaged arrays below carry their shape as a
                # `description` rather than an enforced `items` schema, and that is
                # the point: `items` would make a shape MISTAKE refuse the whole
                # turn, which is exactly what the salvage exists to prevent (a bare
                # string choice and a `text` caption are both understood). A
                # description tells the narrator the shape without arming a refusal.
                "events": {
                    "type": "array",
                    "description": (
                        "Up to 12 short strings, one per notable thing that happened "
                        "this turn (not the whole prose — the line a later turn would "
                        "need to know it happened)."
                    ),
                },
                # Enrichment (per-turn gains the systems engine reads): relaxed to
                # a bare array; `_clean_gains` drops any entry with no string
                # `field`, strips unknown keys, and caps the list at 12, warning on
                # each drop instead of refusing the turn.
                "gains": {
                    "type": "array",
                    "description": (
                        "Up to 12 objects, each naming what this turn credited: "
                        "`field` (required, the state field that grew), `amount`, and "
                        "`source` (where it came from — how the anti-halo reading is "
                        "made measurable). An entry naming no `field` is dropped."
                    ),
                },
                # Player-facing, but SALVAGED rather than schema-refused:
                # `_clean_choices` is the gate. It drops entries with no usable
                # `label`, synthesizes a missing id, strips unknown keys, caps the
                # list at 8, and drops invalid/over-size `art`. The
                # choices-required gate still fires on the CLEANED result, so a
                # living turn left with no usable choice is still refused.
                "choices": {
                    "type": "array",
                    "description": (
                        "Up to 8 objects, one per button the player can press: "
                        "`label` (REQUIRED — the text they read; `text`/`title`/"
                        "`caption`/`name` are accepted and folded onto it, and a bare "
                        "string entry is read as a label), `id` (optional, "
                        "synthesized when absent), `fateful` (bool), `art` (a small "
                        "self-contained SVG), `effect` (one of shimmer, aura, embers, "
                        "ripple) and `tint` (#rrggbb). An entry with no usable label "
                        "is dropped, and a living turn left with none is refused — so "
                        "the label is the one part that must be right."
                    ),
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
            "get the whole state. A `since` read also stops re-sending what you are "
            "already holding: the months you wrote come back empty, and a `lore` "
            "entry or `memoryCandidates` event whose body reached you earlier in "
            "this conversation comes back marked `held: true` with the body left "
            "out. A held entry is still being surfaced BECAUSE it bears on this "
            "month — read it from where it was first given rather than asking "
            "again. Lose your baseline (a compaction) and everything arrives whole."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "recentTurns": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 50,
                    "description": (
                        "How many recent months to re-read. Applies to a FULL read "
                        "only — on a `since` read you wrote those months and they "
                        "are not sent back at any depth. To reach one specific "
                        "older month, name it in `memoryEvents`."
                    ),
                },
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
                        "difference is sent — and of the difference, only what the "
                        "APP computed (system-derived values, merged panels, "
                        "milestones). Panels that changed only because of your own "
                        "declaration are NAMED in `yours` rather than re-sent: you "
                        "wrote them this turn and still hold them. If you have lost "
                        "the fingerprint, leave this out — asking with a baseline "
                        "you no longer hold is how a turn ends up inventing the "
                        "parts it cannot see."
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
            "`grid` ({columns, cells:[{label, note?, mark?}]} — a cell's `mark` is "
            "either one short symbol shown as its badge, which is how cells of a map "
            "are told apart, or `true` to tint the whole cell; a symbol does not also "
            "tint, so marking every cell still leaves each one distinct); for a "
            "relationship web "
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
            "the choice buttons. An optional `STYLE:` line picks the painting style — "
            "photo (traced photograph, the scene default), watercolor, oil, or "
            "minimal. Describe the picture; never write SVG here. Setting a "
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
        "name": "endless_trace_reference",
        "description": (
            "SCENE lane only: search attribution-free (CC0/public-domain) reference "
            "images and trace the top few into palette-disciplined desktop+mobile "
            "underlay candidates, stored server-side. `source` picks the lane: "
            "'photo' (default) searches Openverse — a CC aggregator spanning "
            "Wikimedia Commons, Flickr and museums, far larger than Commons alone — "
            "then Commons; 'art' searches the Met (public-domain artworks) then the "
            "Smithsonian. `query` is the page's SUBJECT and nothing else: two or "
            "three of the commonest English nouns for the thing a photographer "
            "could have stood in front of — 'thatched cottage', 'stone bridge', "
            "'walled town'. NOT the era, region, weather, time of day or mood. Both "
            "archives match every word, so each extra word removes results: "
            "measured live, 'thatched roofs' returns a full set of candidates while "
            "the same subject inside an 18-word brief returns NONE. Put the era and "
            "the atmosphere in the brief's own context, which is never searched; "
            "optional desktop/mobile "
            "focal X/Y move each crop from 0 (left/top) to 1 (right/bottom). Returns "
            "a `candidates` list, each with its own preview PNG paths (fragments "
            "never enter your context) — READ every candidate's previews, then call "
            "endless_select_reference with the best `index`. When a multi-word query "
            "finds nothing the tool does NOT settle immediately: it returns "
            "`underlay: none` and asks you to call it ONCE more with a single "
            "most-relevant noun (the free-license slice is narrow, so a compound "
            "subject misses while its head noun hits). Only after that retry, a "
            "single-word miss, or a transient error does it return a procedural "
            "tonal base (`underlay: base`) that is already active, with nothing to "
            "select."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "turn"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "turn": {"type": "integer", "minimum": 0},
                "query": {"type": "string", "maxLength": 200},
                "source": {"type": "string", "enum": ["photo", "art"]},
                "opacity": {"type": "number", "minimum": 0.2, "maximum": 0.8},
                "desktopFocalX": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "desktopFocalY": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "mobileFocalX": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "mobileFocalY": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "ramp": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 8,
                    "items": {"type": "string", "pattern": "^#?[0-9a-fA-F]{6}$"},
                },
            },
        },
    },
    {
        "name": "endless_select_reference",
        "description": (
            "SCENE lane only: after reading the candidate previews from "
            "endless_trace_reference, choose the one whose real structure and light "
            "best fit the brief by passing its `index`. The chosen reference becomes "
            "the page's active underlay; the others are discarded. Only call this "
            "when endless_trace_reference returned `candidates` — a procedural "
            "`base` result is already active and needs no selection. After "
            'selecting, place exactly one `<g id="etr-underlay"/>` in each SVG.'
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "turn", "index"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "turn": {"type": "integer", "minimum": 0},
                "index": {"type": "integer", "minimum": 0},
            },
        },
    },
    {
        "name": "endless_submit_backdrop_draft",
        "description": (
            "Submit the ILLUSTRATOR's unpublished first draft for visual review. "
            "The server validates all supplied SVGs, renders small safe PNG thumbnails, "
            "and returns their local paths plus an opaque `draftId`. This does NOT "
            "publish art or clear the waiting page. Read every returned PNG together "
            "with the built-in `read` tool in Image mode before making at most one "
            "revision and calling endless_commit_backdrop."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "turn", "markup", "mobile"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "turn": {"type": "integer", "minimum": 0},
                "markup": {"type": "string", "maxLength": 24000},
                "mobile": {"type": "string", "maxLength": 24000},
                "buttons": {"type": "string", "maxLength": 8000},
            },
        },
    },
    {
        "name": "endless_commit_backdrop",
        "description": (
            "Publish the ILLUSTRATOR's final backdrop after visual draft review. "
            "Pass the opaque `draftId` returned by endless_submit_backdrop_draft, "
            "the final desktop SVG as `markup`, the independently composed portrait "
            "SVG as `mobile`, and optional `buttons`. The final may be the reviewed "
            "draft unchanged or its one revision. Publication is atomic and refused "
            "unless the draft id and page match; draft thumbnails are never public."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "turn", "draftId", "markup", "mobile"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "turn": {"type": "integer", "minimum": 0},
                "draftId": {"type": "string", "minLength": 24, "maxLength": 24},
                "markup": {"type": "string", "maxLength": 24000},
                "mobile": {"type": "string", "maxLength": 24000},
                "buttons": {"type": "string", "maxLength": 8000},
            },
        },
    },
    {
        "name": "endless_commit_fallback_backdrop",
        "description": (
            "Emergency page-art recovery for the NARRATOR only. Use this solely "
            "when an internal recovery prompt says illustrator attempts failed. "
            "Commit one safe backdrop set for the exact runId and turn in that "
            "prompt: required desktop `markup`, plus optional coordinated portrait "
            "`mobile` and choice motif `buttons`. The server refuses this tool unless "
            "that page's persisted fallback gate is open."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["runId", "turn", "markup"],
            "additionalProperties": False,
            "properties": {
                "runId": _RUN_ID,
                "turn": {"type": "integer", "minimum": 0},
                "markup": {"type": "string", "maxLength": 24000},
                "mobile": {"type": "string", "maxLength": 24000},
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


@lru_cache(maxsize=64)
def _pattern(rule: str) -> re.Pattern[str]:
    """Compile a published ``pattern`` once. Cached because the schemas are fixed
    and every call re-walks them."""
    return re.compile(rule)


#: A stored run id is a bare uuid4 hex (store._RUN_ID_RE). The addressing hands it
#: over bare, but a narrator decorates it anyway — observed live as "run-<id>",
#: "run_<id>" and "run-id-<id>" (the slot-key shape) — and the store then rejects it
#: as malformed, which fails the mandatory first read and wedges the turn.
_BARE_RUN_ID = re.compile(r"^[0-9a-f]{32}$")

#: One bare id embedded in a decorated string. The negative lookarounds keep it from
#: matching a 32-hex window inside a longer hex run, so a genuinely different value
#: is left to fail loudly rather than being silently truncated into some other run.
_EMBEDDED_RUN_ID = re.compile(r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])")


def _normalize_run_id_arg(args: dict[str, Any]) -> None:
    """Recover the bare run id from a decorated ``runId``, in place.

    A stored id is ``uuid4().hex`` — 32 lowercase hex and nothing else — so any
    surrounding text (a ``run-``/``run_``/``run-id-`` prefix, quotes, whitespace, a
    case mangle) is decoration the narrator added, and the one embedded bare id is
    the id it meant. Repairing the whole class here rather than a fixed prefix list
    is what stops the next spelling of the same mistake from wedging a life: the
    narrator cannot debug "malformed run id" from its side, because the addressing
    already told it the id it is holding is correct.

    Anything with no single embedded id is left untouched, so a real mistake still
    reaches the store and is reported as one.
    """
    rid = args.get("runId")
    if not isinstance(rid, str):
        return
    trimmed = rid.strip().lower()
    if _BARE_RUN_ID.match(trimmed):
        if trimmed != rid:
            args["runId"] = trimmed
        return
    found = _EMBEDDED_RUN_ID.findall(trimmed)
    # Exactly one candidate, or nothing: two ids in one string is ambiguous, and
    # guessing which life to write would be worse than refusing the call.
    if len(found) == 1:
        args["runId"] = found[0]


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
    """Check one node, and STRIP a null-valued optional field on the way past.

    A narrator with nothing for an optional field writes ``"place": null`` as
    readily as it omits the key, and the two are the same statement — so treating
    the first as a type error refused whole turns (prose, choices and state
    included) over a field that was saying "nothing here". Absent is what it
    means, so absent is what it becomes, in place, before any type check. A
    REQUIRED field is untouched: ``prose: null`` is a real failure and must still
    refuse the call rather than commit a blank page.
    """
    kind = schema.get("type")

    if kind == "object":
        if not isinstance(value, dict):
            raise ToolInputError(path, f"an object, got {type(value).__name__}")
        required = schema.get("required", [])
        for field in required:
            if field not in value:
                raise ToolInputError(f"{path}.{field}", "required, and absent")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    raise ToolInputError(f"{path}.{key}", "not a field of this call")
        for key, sub in props.items():
            if key not in value:
                continue
            if value[key] is None and key not in required:
                del value[key]  # a null optional field is an absent one
                continue
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
            # A null ENTRY is not a statement about a field, it is a hole in a list
            # the narrator built — drop it rather than refuse the turn over it.
            value[:] = [entry for entry in value if entry is not None]
            for i, entry in enumerate(value):
                _check(item, entry, f"{path}[{i}]")
        # After the null holes are gone, so the count judged is the count that
        # would be applied rather than the one that arrived.
        floor = schema.get("minItems")
        if floor is not None and len(value) < floor:
            raise ToolInputError(path, f"at least {floor} entries, got {len(value)}")
        return

    if kind == "string":
        if not isinstance(value, str):
            raise ToolInputError(path, f"a string, got {type(value).__name__}")
        cap = schema.get("maxLength")
        if cap is not None and len(value) > cap:
            raise ToolInputError(path, f"at most {cap} characters, got {len(value)}")
        floor = schema.get("minLength")
        if floor is not None and len(value) < floor:
            raise ToolInputError(path, f"at least {floor} characters, got {len(value)}")
        allowed = schema.get("enum")
        if allowed is not None and value not in allowed:
            raise ToolInputError(path, f"one of {', '.join(allowed)}, got {value!r}")
        rule = schema.get("pattern")
        if rule is not None and not _pattern(rule).search(value):
            raise ToolInputError(path, f"a string matching {rule}")
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

    if kind == "number":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ToolInputError(path, f"a finite number, got {type(value).__name__}")
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


def _backdrop_draft_store(run_id: str) -> BackdropDraftStore:
    """A handle for unpublished raster previews; runtime routes never read it."""
    return BackdropDraftStore(_DATA, run_id)


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
_CHOICE_KEYS = ("id", "label", "fateful", "art", "effect", "tint")

#: The runtime effect vocabulary for choice buttons. The narrator DECLARES a
#: name; the app's own CSS/canvas renders it — model bytes never carry code
#: into the dashboard document (the play page is NOT an iframe). Unknown names
#: are dropped fail-soft, so an over-imaginative narrator degrades to the
#: static styling instead of losing the turn.
_CHOICE_EFFECTS = ("shimmer", "aura", "embers", "ripple")
_TINT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

#: Key names a narrator plausibly uses for a choice's visible text. `label` is
#: canonical; the rest are salvaged onto it. A model that invents a key here is
#: describing the same thing — a button caption — and dropping the entry over
#: the spelling turns into a "choices-required" refusal that names a field the
#: narrator DID send, which it cannot debug from its side (observed live: six
#: identical retries, each cleaned to an empty list).
_CHOICE_LABEL_ALIASES = ("label", "text", "title", "caption", "name")

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
    cfg = read_settings(_DATA)
    choice_art = bool(cfg["choiceArt"])
    choice_effects = bool(cfg["choiceEffects"])
    out: list[Any] = []
    for i, c in enumerate(choices):
        # A bare string IS a caption: a narrator that sends ["逃跑", "反击"] has
        # answered the question the schema asks, just not in the dict shape.
        if isinstance(c, str) and c.strip():
            c = {"label": c}
        if not isinstance(c, dict):
            continue
        label = next(
            (c[k] for k in _CHOICE_LABEL_ALIASES if isinstance(c.get(k), str) and c[k].strip()),
            None,
        )
        if label is None:
            continue
        clean = {k: v for k, v in c.items() if k in _CHOICE_KEYS}
        clean["label"] = label[:200]
        cid = clean.get("id")
        clean["id"] = cid[:64] if isinstance(cid, str) and cid.strip() else f"c{i}"
        # The player's decoration switches, enforced at the one gate every choice
        # passes: with choice art or effects off the narrator may still send them,
        # and they are stripped here rather than argued about — the choice itself
        # always survives its decoration.
        if not choice_art:
            clean.pop("art", None)
        if not choice_effects:
            clean.pop("effect", None)
            clean.pop("tint", None)
        art = clean.get("art")
        if isinstance(art, str) and art.strip() and len(art) <= 6000:
            try:
                clean["art"] = compile_backdrop(art)
                # Choice art is stored per turn and has no single read boundary
                # like the backdrop store's _view, so reduced motion is applied
                # here at commit: new pages are still from now on. (Backdrops —
                # the dominant moving surface — de-animate retroactively.)
                if cfg["reducedMotion"]:
                    clean["art"] = strip_motion(clean["art"])
            except BackdropError:
                clean.pop("art", None)
        else:
            clean.pop("art", None)
        if clean.get("effect") not in _CHOICE_EFFECTS:
            clean.pop("effect", None)
        tint = clean.get("tint")
        if isinstance(tint, str) and _TINT_RE.match(tint.strip()):
            clean["tint"] = tint.strip()
        else:
            clean.pop("tint", None)
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
        args["memoryEvents"] = [str(e)[:96] for e in list(v)][:6] if isinstance(v, list) else []
    if "chapters" in args:
        v = args.get("chapters")
        args["chapters"] = [str(c)[:64] for c in list(v)][:8] if isinstance(v, list) else []
    if "includeProse" in args:
        args["includeProse"] = bool(args.get("includeProse"))


# ── handlers ─────────────────────────────────────────────────────────────


#: Keys the APP owns. The narrator never declares them — they are bookkeeping, not
#: story — so a commit carries them forward instead of letting a full-state
#: declaration drop them. Losing ``worldId`` this way made a life unreadable the
#: moment its first turn landed: the play view could no longer find its world.
RESERVED_STATE_KEYS = (
    "worldId",
    "style",
    "language",
    "opening",
    "status",
    "role",
    "granted",
    "milestones",
)

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


def _merge_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """``statePatch`` semantics: ``_merge_forward`` applied recursively.

    A dict patched onto a dict merges key by key; ``None`` retires a key at any
    depth; any other value (scalar, list, or a dict landing on a non-dict)
    replaces the leaf whole. Unmentioned keys survive untouched — which is the
    whole point: the narrator sends what moved and vouches for the rest with
    ``basedOn``. The empty-string retirement sentinel is deliberately NOT
    honoured here: it exists in ``_merge_forward`` for the prose-valued digest
    entries, but a general state leaf can legitimately hold ``""``.
    """
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_patch(merged[key], value)
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
        for e in template.lore
        if picked("lore", e.id)
    ]
    systems = [
        {"id": s.id, "kind": s.kind, "into": s.into}
        for s in template.systems
        if picked("systems", s.id)
    ]
    roles = [
        {"id": r.id, "name": r.name or r.id, "summary": r.summary, "grants": r.grants}
        for r in template.roles
        if picked("roles", r.id)
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
    # it is REPAIRED, never rejected whole. sanitize_memory fixes what the narrator
    # merely mis-spelled — a colon-namespaced id (the shape read_runtime itself shows
    # it), an unslugified space, a synonym for a closed vocabulary, a key already used
    # this turn, a title it wrote only into the summary — and drops only what would
    # have to be INVENTED to keep: a reference to an entity never declared. So a
    # stray slip never costs the real memory around it, let alone the prose and
    # choices already written. Repairs are logged, not warned; only genuine drops
    # reach the narrator, so it can re-declare them later. Facts are never
    # back-filled from prose, so a block whose parts all fail records no memory.
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

    patch = args.get("statePatch")
    if isinstance(args.get("state"), dict):
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
    elif isinstance(patch, dict):
        # The write-side twin of read_runtime's `since`, and the same
        # self-certification: a narrator that can still produce the fingerprint it
        # read is patching the state it believes it is patching. Measured before
        # this existed, re-declaring the whole state was 22 KB per commit on a
        # real life — the single largest line in the narrator's transcript — and
        # every retry re-paid it in full.
        based_on = str(args.get("basedOn") or "")
        if not based_on:
            return {
                "committed": False,
                "turn": committed,
                "reason": "based-on-required",
                "detail": (
                    "A statePatch needs `basedOn`: the exact `fingerprint` your "
                    "endless_read_runtime call handed you this turn. If you no "
                    "longer hold one, send the full `state` instead."
                ),
            }
        if based_on != store.fingerprint(current):
            return {
                "committed": False,
                "turn": committed,
                "reason": "baseline-mismatch",
                "detail": (
                    "Your statePatch is built on a state this run is no longer in. "
                    "Call endless_read_runtime again, then resend the WHOLE call — "
                    "either a statePatch with the fresh fingerprint, or the full "
                    "state. Do not guess at what changed."
                ),
            }
        # NOT the full-declaration blocks above: starting from the current state,
        # the reserved keys are already present, and the recursive merge gives the
        # digest/relations semantics directly (declare what moved, null retires).
        # Running _merge_forward here as well would resurrect entries the patch
        # just retired, out of the very `prior` they were retired from.
        state = _merge_patch(current, patch)
    else:
        return {
            "committed": False,
            "turn": committed,
            "reason": "state-required",
            "detail": (
                "A turn declares where the life now stands: send `state` in full, "
                "or `statePatch` + `basedOn` when you still hold the fingerprint "
                "you read this turn."
            ),
        }
    # Snapshot of the state the NARRATOR intends, taken after its own declaration
    # is assembled but before any backend amendment. Compared with the final
    # committed state, it yields the leaf paths the backend wrote — which is
    # exactly what a delta read is allowed to send back (the narrator remembers
    # its own declarations; it cannot know these).
    declared = json.loads(json.dumps(state, default=str))
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
        fired = any(e.when is not None and e.when.evaluate(state) for e in pack.template.endings)
        if args.get("ending") is not True and not fired:
            sent = args.get("choices")
            # Name the TRUE failure. "No choices" when the narrator sent some is
            # undebuggable from its side — it retries the same call forever
            # (observed live). Distinguish absent from sent-but-unusable, and spell
            # out the exact accepted shape.
            if isinstance(sent, list) and sent:
                detail = (
                    f"You sent {len(sent)} choices but none had a usable caption, so "
                    "all were dropped. Each choice must be an object with a "
                    "non-empty string `label` (optional: `id`, `fateful`, `art`), "
                    'e.g. {"id": "flee", "label": "逃跑"}. Resend the WHOLE call '
                    "with choices in that shape."
                )
            else:
                detail = (
                    "This turn has no `choices`, so the player would have nothing to "
                    "do. Resend the WHOLE call with `choices`. A character who cannot "
                    "deliberately act — a newborn, an infant, someone asleep, bound, "
                    "or carried along by events — still gets choices: offer what this "
                    "life leans into or takes from what happens around it, written in "
                    "the player's own voice (\"I reach toward the noise beyond the "
                    'door", "I keep the name they gave me"), not as a deliberate '
                    "plan they are too young to make. If the life or world has ended, "
                    "pass `ending: true` (or declare state that fires a world ending) "
                    "— only a terminal turn may omit choices."
                )
            return {
                "committed": False,
                "turn": committed,
                "reason": "choices-required",
                "detail": detail,
            }
    store.commit_state(run_id, state)
    # Provenance rides with the commit: leaves where the final state differs from
    # the narrator's declaration were backend-written (reserved-key carry,
    # digest/relations merge results, turn, milestones, systems). A failure here
    # only degrades the next delta read to whole-panel resends — never the commit.
    try:
        store.mark_provenance(run_id, turn=turn, paths=store.leaf_diff_paths(declared, state))
    except Exception:  # noqa: BLE001
        pass
    # What the player asked for, recovered from the in-flight record the app wrote
    # before speaking. The narrator is told the intent in prose and never echoes it
    # back, so this is the only place it can be preserved — and without it, reviewing
    # a past month shows the outcome with the choice that caused it missing.
    asked = store.read_pending(run_id) or {}
    action = str(asked.get("action") or "") if int(asked.get("turn") or 0) == turn else ""

    # The turn's cost, recorded where the commit happens (only this process sees
    # it). storyMs runs from the app's own ask (mark_pending, written before
    # dispatch) to this commit; readMs is how long the narrator took to look
    # before it wrote. Advisory rows for the perf page — never a reason to fail
    # the commit they measure.
    if int(asked.get("turn") or 0) == turn:
        now = time.time()
        asked_at = float(asked.get("askedAt") or 0.0)
        read_at = float(asked.get("readAt") or 0.0)
        TurnPerf(_DATA, run_id).mark(
            turn,
            "commit",
            storyMs=int((now - asked_at) * 1000) if asked_at else None,
            readMs=int((read_at - asked_at) * 1000) if asked_at and read_at >= asked_at else None,
            toolCalls=int(asked.get("steps") or 0) or None,
            form="patch" if isinstance(patch, dict) else "full",
            declaredBytes=len(
                json.dumps(patch if isinstance(patch, dict) else args.get("state"), default=str)
            ),
        )

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
    # The standing this month ENDED on, so re-reading a past page shows that
    # month's situation instead of today's. A snapshot rather than the state itself:
    # a chronicle records what the page looked like, and resolving panels later
    # would need the world pack that was in force then — a later pack edit would
    # silently rewrite history. Absent when the pack could not be loaded; the page
    # then falls back to the live panels.
    if pack is not None:
        try:
            entry["digest"] = gate_digest(pack.template.digest_categories, state)
            entry["panels"] = shape_panels(pack.template, state, pack.capability_packs)
        except Exception:  # noqa: BLE001
            # A month that narrated fine is not lost over a summary snapshot.
            pass
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

#: The fields that let a narrator RECOGNISE a recall candidate it is already
#: holding. Everything else is body, which a held candidate does not re-send.
_RECALL_IDENTITY = ("id", "turn", "title")


def _pluck_paths(state: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    """A nested dict holding only the leaves ``paths`` name, read from ``state``.

    Paths are the dotted form ``RunStore.leaf_diff_paths`` produces. A path that
    no longer resolves (a backend-retired leaf: present in the baseline, absent
    now) is skipped — its retirement was the narrator's own declared null, so
    there is nothing new to show it.
    """
    root: dict[str, Any] = {}
    for path in paths:
        parts = path.split(".")
        src: Any = state
        for part in parts:
            if isinstance(src, dict) and part in src:
                src = src[part]
            else:
                src = _PLUCK_MISS
                break
        if src is _PLUCK_MISS:
            continue
        dst = root
        for part in parts[:-1]:
            nxt = dst.setdefault(part, {})
            if not isinstance(nxt, dict):
                nxt = dst[part] = {}
            dst = nxt
        dst[parts[-1]] = src
    return root


#: Sentinel for a path that stopped resolving mid-walk (never a real state value).
_PLUCK_MISS = object()


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

    # Recall material the narrator is already holding. A delta read is the narrator
    # CERTIFYING that its context survived (it could not otherwise name the
    # baseline), so every body delivered earlier in this conversation is still in
    # front of it and re-sending it buys nothing. On a full read it is holding
    # nothing, so everything goes in full and the record is replaced.
    held = set() if full_read else store.recall_sent(run_id)
    # Bodies actually delivered by THIS read, recorded once at the end.
    delivered: list[str] = []

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
                    # A held entry still SURFACES — the keyword matched, so this
                    # month is about it and the narrator should know that — but its
                    # body is omitted and named as held instead. The world's standing
                    # setting does not change, so the text it received earlier in
                    # this conversation is still the current text.
                    matched = []
                    for _, e in ranked[:MAX_LORE]:
                        row: dict[str, Any] = {"id": e.id}
                        if e.name:
                            row["name"] = e.name
                        if e.id in held:
                            row["held"] = True
                        else:
                            row["text"] = e.text
                            delivered.append(e.id)
                        matched.append(row)
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
            #
            # A held candidate keeps the fields the narrator needs to RECOGNISE it
            # (`id`, `turn`, `title`) and loses the body it already has. A committed
            # event is immutable, so the summary it received earlier in this
            # conversation is still the whole truth about that month — which is why
            # omitting it costs nothing, while re-sending it cost a measured 43
            # deliveries of one event on a single life.
            rows: list[dict[str, Any]] = []
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                cid = str(c.get("id") or "")
                if cid and cid in held:
                    row = {k: c[k] for k in _RECALL_IDENTITY if k in c}
                    row["held"] = True
                else:
                    row = {k: v for k, v in c.items() if k not in ("reasons", "lastEchoedTurn")}
                    if cid:
                        delivered.append(cid)
                rows.append(row)
            out["memoryCandidates"] = rows
    wanted_events = args.get("memoryEvents") or []
    if wanted_events:
        out["memoryEvents"] = memory_graph.event_neighbourhood(
            graph, [str(e) for e in wanted_events]
        )

    # Written AFTER both recall blocks, so it records what this read actually put in
    # front of the narrator rather than what was merely selected. A full read replaces
    # the set: the narrator has just proved it is holding nothing.
    store.mark_recall_sent(run_id, delivered, reset=full_read)

    if baseline is not None:
        delta = store.diff(baseline, state)
        prov_turn, prov_paths = store.provenance(run_id)
        # Provenance is trusted only when it describes THIS state's commit: an
        # older record would suppress amendments the narrator has never seen.
        # Without trustworthy provenance the whole changed panel is sent — the
        # fail-safe direction is more data, never a silently missing fact.
        if prov_paths and prov_turn == int(state.get("turn") or 0):
            prov = set(prov_paths)
            changed_leaves = store.leaf_diff_paths(baseline, state)
            computed = [p for p in changed_leaves if p in prov and p != "turn"]
            out["changed"] = _pluck_paths(state, computed)
            # Panels the narrator changed by its OWN declaration: named, not
            # re-sent. It wrote those words this turn; within a surviving session
            # (which a resolvable baseline proves) it still holds them, and
            # echoing them back was the bulk of a delta on a real life.
            out["yours"] = sorted(
                {p.split(".", 1)[0] for p in changed_leaves if p not in prov and p != "turn"}
            )
        else:
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
    # ``recentTurns`` used to have an escape hatch — an explicit request was always
    # honoured, on the theory that it was how a narrator deliberately paged back
    # through older history. Measured on a real life, that hatch was the whole
    # behaviour: the narrator supplied the parameter on 48 calls and every one asked
    # for the TAIL (1, 2, 3 or 5), never once for anything older. A gate keyed on a
    # parameter's ABSENCE is dead the moment the model helpfully fills it in, and this
    # one was. So the certification is now the only rule: a narrator that can name its
    # baseline is holding the months it wrote and gets none of them back. Reaching one
    # specific old month already has its own door in ``memoryEvents``, which asks by
    # id instead of by depth.
    if full_read:
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
                        "id": g.id,
                        "label": g.label,
                        "worldDecides": g.random,
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


def _probe_state(run_id: str) -> dict[str, Any]:
    """Run state for a compile-probe, best-effort. A scene binds against state, so
    the probe wants it, but a scene mounts whether or not state is readable — an
    unreadable state just means binds fall back to literals."""
    try:
        return _store().read_state(run_id) or {}
    except Exception:  # noqa: BLE001
        return {}


def _mount_scene(args: dict[str, Any]) -> dict[str, Any]:
    ledger = _scene_ledger(args["runId"])
    ledger.mount(
        args["sceneId"],
        args["spec"],
        asks=bool(args.get("asks")),
        region=str(args.get("region") or ""),
        label=str(args.get("label") or ""),
    )
    # A compile-probe of the STORED (normalized) spec, so the narrator learns which
    # elements will not render — the scene still mounts regardless, and this never
    # raises. The mount identity is NOT returned: a narrator holding it could forge
    # an answer to the question it just asked.
    sid = slugify_scene_id(args["sceneId"])
    warnings = scene_warnings(sid, ledger.spec(sid), _probe_state(args["runId"]))
    return {"mounted": sid, **({"warnings": warnings} if warnings else {})}


def _update_scene(args: dict[str, Any]) -> dict[str, Any]:
    ledger = _scene_ledger(args["runId"])
    ledger.update(args["sceneId"], args["spec"])
    sid = slugify_scene_id(args["sceneId"])
    warnings = scene_warnings(sid, ledger.spec(sid), _probe_state(args["runId"]))
    return {"updated": sid, **({"warnings": warnings} if warnings else {})}


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

    This is also where the player's art settings are ENFORCED, because every brief
    passes through exactly here:

    - ``backdrops`` off: the brief is acknowledged and dropped — nothing is queued,
      no illustrator runs, and the page never enters a "painting" wait. The answer
      tells the narrator plainly so it stops spending the call.
    - ``sparse`` cadence: a new brief within ``SPARSE_GAP_TURNS`` turns of the last
      committed art is declined and the current backdrop stays. A replacement brief
      for a page whose art is ALREADY pending passes — that is recovery, not a new
      spend.
    - style allowlist: a disabled style is rewritten to the player's preferred
      enabled one before the brief is stored, so the illustrator only ever reads
      briefs it is allowed to paint.
    """
    run_id = args["runId"]
    turn = _backdrop_turn(run_id)
    cfg = read_settings(_DATA)
    if not cfg["backdrops"]:
        BackdropTimeline(_DATA, run_id).mark(turn, "declined:art-off")
        return {
            "backdrop": "off",
            "turn": turn,
            "note": (
                "the player has turned page art off in the app settings; no image "
                "will be drawn. Skip endless_paint_backdrop for the rest of this life."
            ),
        }
    brief = rewrite_brief_style(str(args["brief"]), cfg["styles"], preferred_style(cfg["styles"]))
    if cfg["backdropCadence"] == "sparse":
        pending = _store().read_backdrop_request(run_id)
        replacing = bool(pending and int(pending.get("turn") or 0) == turn)
        last = _backdrop_store(run_id).latest_turn()
        if not replacing and last is not None and turn - last < SPARSE_GAP_TURNS:
            BackdropTimeline(_DATA, run_id).mark(turn, "declined:cadence")
            return {
                "backdrop": "kept",
                "turn": turn,
                "note": (
                    "the player chose sparse page art: the current backdrop stays "
                    f"for now (a new one is accepted after turn {last + SPARSE_GAP_TURNS}). "
                    "Continue the turn without art."
                ),
            }
    _store().request_backdrop(run_id, turn=turn, brief=brief)
    BackdropTimeline(_DATA, run_id).mark(turn, "requested", lane=brief_lane(brief))
    return {"backdrop": "queued", "turn": turn}


def _trace_store(run_id: str) -> TraceStore:
    """Server-side traced underlays; fragments never enter the model's context."""
    return TraceStore(_DATA, run_id)


def _candidate_store(run_id: str) -> CandidateStore:
    """Server-side traced reference candidates awaiting the Illustrator's pick."""
    return CandidateStore(_DATA, run_id)


def _render_trace_previews(run_id: str, tag: str, desktop: str, mobile: str) -> dict[str, str]:
    """Render safe desktop+mobile PNG thumbnails for one underlay; return their paths."""
    from backdrop import _render_svg_thumbnail

    preview_dir = _DATA / "runs" / run_id / "backdrop-previews"
    previews: dict[str, str] = {}
    for label, fragment in (("desktop", desktop), ("mobile", mobile)):
        vw, vh, w, h = (800, 600, 400, 300) if label == "desktop" else (450, 900, 150, 300)
        doc = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw} {vh}">'
            f'<rect width="{vw}" height="{vh}" fill="#0b0e17"/>{fragment}</svg>'
        )
        path = preview_dir / f"backdrop-preview-trace-{tag}-{label}.png"
        _render_svg_thumbnail(doc, path, w, h)
        previews[label] = str(path.resolve())
    return previews


def _require_scene_underlay(run_id: str, turn: int, request: dict[str, Any]) -> None:
    """A brief that asked for a SCENE must have gone through the trace tool.

    Nothing used to check this. `_apply_underlay` requires the `etr-underlay`
    placeholder only when a trace record EXISTS, so an Illustrator that skipped
    `endless_trace_reference` entirely and hand-drew the page committed cleanly and
    was stored as an ordinary motif — no underlay, no receipt, no trace of the
    intent. A real page did exactly that, and afterwards nothing could tell whether
    the narrator had asked for a motif or the scene lane had been quietly abandoned,
    because the brief is cleared the moment art commits.

    A base underlay satisfies this: the gate is "the lane ran", not "a photograph was
    found". The refusal names the one call that fixes it, and it fires at draft time
    as well as commit so the Illustrator learns before it renders previews.

    A brief that declares a painterly STYLE (watercolor/oil/minimal) opts OUT of the
    trace pipeline by design: the scene is hand-drawn in that style, so requiring a
    trace record would force a search the narrator explicitly routed around. Only the
    ``photo`` style — and the historical style-less scene brief, which keeps its old
    meaning — must run the trace lane.
    """
    if str(request.get("lane") or "") != "scene":
        return
    if str(request.get("style") or "") in {"watercolor", "oil", "minimal"}:
        return
    if isinstance(_trace_store(run_id).load(turn), dict):
        return
    raise BackdropError(
        "this brief declared LANE: scene, so the page must be built on a traced "
        "underlay: call endless_trace_reference first (then endless_select_reference "
        'if it offers candidates) and put one <g id="etr-underlay"/> in each SVG. '
        "If the search finds nothing it hands you a procedural base, which also "
        "satisfies this — what is refused is skipping the lane silently."
    )


def _apply_underlay(run_id: str, turn: int, svg: str, variant: str) -> str:
    """Splice a stored underlay, failing closed when a traced scene omits it."""
    trace = _trace_store(run_id).load(turn)
    if isinstance(trace, dict):
        fragment = trace.get(variant)
        if not isinstance(fragment, str) or not fragment:
            raise BackdropError(f"the stored trace has no {variant} underlay")
        return compose_with_underlay(svg, fragment, require_placeholder=True)
    return compose_with_underlay(svg, None)


#: The degradation shared by every TERMINAL scene miss — no photograph exists, or none
#: can be traced here. Both leave the same page to draw, so they must not drift apart:
#: the base is a tonal ground and the Illustrator still owes a real scene above it.
_HAND_DRAWN_GROUND = (
    "The procedural tonal base is NOT the finished image; it is a tonal GROUND. Put "
    'one <g id="etr-underlay"/> in each SVG for that ground, then author a real '
    "hand-drawn scene above it — architecture, light, and evidence composed with the "
    "same care as any scene, never a few bars over bare tone. Paint it in a painterly "
    "style (watercolor suits most scenes; read that style's skill file if your task "
    "names one) and take it through the full review pass before committing. Do not "
    "settle for the bare base."
)


def _base_underlay_next(search: dict[str, Any]) -> str:
    """What to tell the Illustrator when the lane produced a procedural base.

    A base underlay used to be reported as a finished outcome — "here is a tonal
    base, compose over it" — which left no way back even when the search had failed
    for a reason the Illustrator could fix in one call. The reasons need different
    answers, so this branches on the audit rather than saying one thing:

    - ``no-candidates``: the search is SPENT — the forced single-keyword retry (see
      _trace_reference) already ran and still found nothing, so no free-license
      photograph exists for this page. The base is a tonal GROUND, not the finished
      image: the Illustrator authors a real hand-drawn scene over it, with the full
      review pass. This is the intended degradation; committing the bare base is only
      the timeout safety net (commit_underlay_only), never the instruction here.
    - ``tracer-unavailable``: references WERE found and this host cannot trace any of
      them. Terminal for the same reason and answered the same way — a hand-drawn
      scene — because no query and no later turn can install a missing dependency. It
      gets its own lead sentence so nobody reading the page hunts for a photograph
      that was there all along.
    - ``search-failed``: the archive did not answer. Retrying the SAME query is the
      right move here, and rewording would be superstition.
    - ``fetch-failed`` / no query: nothing to retry — compose over the base.
    """
    reason = str(search.get("reason") or "")
    tail = (
        ' Put one <g id="etr-underlay"/> in each SVG with no other marks and commit '
        "that — the base alone is a finished backdrop. Add a few sparse marks only if "
        "they clearly help; never paint a full scene from scratch over it."
    )
    if reason == "no-candidates":
        return (
            "no free-license photograph exists for this page — the search is spent "
            "(only the narrow CC0/public-domain slice is searched, so many subjects "
            "have no usable photo even when the open web does). " + _HAND_DRAWN_GROUND
        )
    if reason == "tracer-unavailable":
        return (
            "references were found for this page but this host cannot trace a "
            "photograph at all — the tracer is not installed, so no query and no "
            "retry can produce an underlay here. " + _HAND_DRAWN_GROUND
        )
    if reason == "photo-off":
        return (
            "the player disabled the photo-trace pipeline in the app settings, so no "
            "archive was searched. The procedural tonal base is a GROUND, not the "
            'finished image: put one <g id="etr-underlay"/> in each SVG for it, then '
            "author a real hand-drawn scene above it in a painterly style (watercolor "
            "suits most scenes; read that style's skill file if your task names one) "
            "and take it through the full review pass before committing."
        )
    if reason == "search-failed":
        return (
            "the image archive did not answer (a network error or a rate limit), so "
            "a procedural tonal base is ready. This says nothing about your query: "
            "call endless_trace_reference once more with the SAME words before "
            "changing them." + tail
        )
    return (
        "no usable photographic reference exists for this page, so a quiet "
        "procedural tonal base is active." + tail
    )


#: How many times a SCENE miss is handed back to the illustrator to retry with a
#: better single keyword before the lane settles for a procedural base. One forced
#: retry: the common failure is a multi-word subject that misses the narrow
#: free-license slice while its head noun hits, and one re-search fixes it. A
#: second miss settles rather than wedging the page.
_TRACE_RETRY_CAP = 1

#: A transient fetch failure or a rate-limit (429) on the image host can fail EVERY
#: candidate even though the search FOUND them, and a backdrop is never re-fetched on
#: a later turn — so a one-second blip would cost that page its photo permanently.
#: When the search returned candidates but none traced, the fetch/trace pass is
#: repeated up to this many times (total, including the first) with a short backoff —
#: the search itself is not repeated — before settling for the procedural base.
_FETCH_RETRY_ATTEMPTS = 2
_FETCH_RETRY_BACKOFF_SECS = 0.75


def _trace_reference(args: dict[str, Any]) -> dict[str, Any]:
    """Trace the top reference candidates for the Illustrator to choose among.

    The *photo* lane (default) searches Openverse then Wikimedia Commons; the *art*
    lane searches the Met then the (key-gated) Smithsonian. Up to
    TRACE_CANDIDATE_COUNT references are traced and stashed server-side; the
    Illustrator reads the per-candidate previews and calls endless_select_reference
    to pick the most fitting one. When no photo matches, a single procedural tonal
    base is set active directly — there is nothing to choose.
    """
    run_id = args["runId"]
    turn = int(args["turn"])
    request = _store().read_backdrop_request(run_id)
    if not request or int(request.get("turn") or 0) != turn:
        raise BackdropError("no backdrop is waiting for this run and turn")
    # 0.65, not 0.5: the fragment sits over a dark sky, so opacity is a
    # brightness dial for the whole composition — at 0.5 every traced tone is
    # pulled halfway to near-black and pages read darker than intended.
    opacity = float(args.get("opacity", 0.65))
    ramp = args.get("ramp")
    query = (args.get("query") or "").strip()
    lane = str(args.get("source", "photo"))
    if lane not in {"photo", "art"}:
        raise BackdropError("a trace source must be 'photo' or 'art'")
    desktop_focal = (
        float(args.get("desktopFocalX", 0.5)),
        float(args.get("desktopFocalY", 0.5)),
    )
    mobile_focal = (
        float(args.get("mobileFocalX", 0.5)),
        float(args.get("mobileFocalY", 0.5)),
    )

    traced: list[dict[str, Any]] = []
    search_audit: dict[str, Any] = {"reason": "no-query", "matched": "", "attempts": []}
    # The player can disable the traced-reference pipeline entirely (settings
    # ``styles`` without "photo"). Briefs are rewritten to a painterly style before
    # the illustrator reads them, so this path is a defensive belt for an
    # illustrator that reached the tool anyway: no archive is contacted, no photo is
    # fetched, and the answer routes it to the hand-drawn path the settings chose.
    if query and "photo" not in read_settings(_DATA)["styles"]:
        query = ""
        search_audit = {"reason": "photo-off", "matched": "", "attempts": []}
    if query:
        candidates, search_audit = search_candidates(query, lane, misses=MissCache(_DATA))
        # Candidates existed but the fetch/trace can transiently fail every one (a
        # network blip or a 429 on the image host). Retry the fetch pass a bounded
        # number of times with a short backoff — the search is not repeated — before
        # settling for the base. The happy path breaks on the first success and the
        # backoff sleep never runs.
        tracer_missing = ""
        for fetch_attempt in range(_FETCH_RETRY_ATTEMPTS):
            for candidate in candidates:
                try:
                    photo = fetch_photo(candidate["url"])
                    desktop = build_underlay_fragment_bounded(
                        photo,
                        view=(800, 600),
                        ramp=ramp,
                        opacity=opacity,
                        focal=desktop_focal,
                    )
                    mobile = build_underlay_fragment_bounded(
                        photo,
                        view=(450, 900),
                        ramp=ramp,
                        opacity=opacity,
                        focal=mobile_focal,
                    )
                except TracerUnavailable as exc:
                    # Nothing about this photograph: the tracer is absent, so every
                    # remaining candidate fails identically. Trying the next one — or
                    # the whole pass again — buys nothing but a slower page. Caught
                    # before BackdropError because it is a subclass of it.
                    tracer_missing = str(exc)
                    break
                except BackdropError:
                    continue
                traced.append(
                    {
                        "desktop": desktop,
                        "mobile": mobile,
                        "source": {k: candidate[k] for k in ("title", "pageUrl", "license")},
                    }
                )
                if len(traced) >= TRACE_CANDIDATE_COUNT:
                    break
            if traced or tracer_missing or fetch_attempt + 1 >= _FETCH_RETRY_ATTEMPTS:
                break
            time.sleep(_FETCH_RETRY_BACKOFF_SECS)
        # Candidates existed and not one of them became an underlay even after the
        # bounded re-fetch — a different failure from "nothing matched", recorded so
        # it is not mistaken for a query miss. Which failure matters: a missing tracer
        # is a HOST fault that no query and no later turn can fix, and calling it
        # fetch-failed is what told the Illustrator to ship the bare tonal base.
        if not traced and candidates:
            if tracer_missing:
                _warn(
                    f"scene lane degraded: {len(candidates)} reference(s) matched "
                    f"{query!r} but none could be traced — {tracer_missing}"
                )
                search_audit = {
                    **search_audit,
                    "reason": "tracer-unavailable",
                    "detail": tracer_missing,
                }
            else:
                search_audit = {**search_audit, "reason": "fetch-failed"}

    if traced:
        # Offer the choice: stash candidates and clear any stale active underlay so a
        # leftover from an earlier trace cannot be spliced before the Illustrator picks.
        _candidate_store(run_id).save(
            turn=turn,
            query=query,
            candidates=traced,
            search=search_audit,
        )
        _trace_store(run_id).clear()
        options = [
            {
                "index": i,
                "source": cand["source"],
                "previews": _render_trace_previews(
                    run_id, f"cand{turn}-{i}", cand["desktop"], cand["mobile"]
                ),
            }
            for i, cand in enumerate(traced)
        ]
        return {
            "underlay": "reference",
            "candidateCount": len(options),
            "candidates": options,
            "turn": turn,
            "next": (
                "read every candidate's desktop AND mobile previews together, then "
                "call endless_select_reference with the `index` whose real structure "
                "and light best fit the brief. Draw only after selecting."
            ),
        }

    # No usable CC0/public-domain reference matched. The miss is almost always the
    # QUERY, not the world: only the attribution-free slice is searched and it is
    # narrow, so a multi-word subject rarely lands in it while a single common noun
    # usually does (the images exist under CC BY-SA etc. and are dropped by the
    # permit gate). Rather than silently settle for a procedural base — which the
    # illustrator then decorates into a flat page — hand the miss back ONCE and make
    # the illustrator pick its single most-relevant keyword and search again. The
    # scene gate refuses a commit while no trace exists, so the retry is enforced,
    # not merely advised. A single-word query has nothing left to simplify, and the
    # retry is bounded by _TRACE_RETRY_CAP; either of those settles for the base
    # instead of wedging the page.
    retries = int(request.get("traceRetries") or 0)
    if (
        search_audit.get("reason") == "no-candidates"
        and len(query.split()) > 1
        and retries < _TRACE_RETRY_CAP
    ):
        _store().update_backdrop_request(run_id, traceRetries=retries + 1)
        _candidate_store(run_id).clear()
        _trace_store(run_id).clear()
        return {
            "underlay": "none",
            "turn": turn,
            "retry": retries + 1,
            "next": (
                f"No attribution-free (CC0/public-domain) reference matched "
                f'"{query}". Only the free-license slice is searched and it is '
                "narrow, so a multi-word subject usually misses while a single "
                "common noun hits. Call endless_trace_reference ONCE more with the "
                "SINGLE most-relevant noun for the thing itself — the commonest "
                "word a photographer could have stood in front of (the core object "
                "or place), with no qualifier, era, weather, or mood. Do not settle "
                "for a base yet: the page cannot commit a scene without a trace."
            ),
        }

    # Retry budget spent, a single-word miss, or a transient / absent-query miss:
    # settle on a single procedural base so the page can still commit and never wedges.
    desktop = procedural_base_fragment(view=(800, 600), ramp=ramp, opacity=opacity)
    mobile = procedural_base_fragment(view=(450, 900), ramp=ramp, opacity=opacity)
    _candidate_store(run_id).clear()
    fragment_id = _trace_store(run_id).save(
        turn=turn,
        desktop=desktop,
        mobile=mobile,
        source=None,
        kind="base",
        query=query,
        search=search_audit,
    )
    previews = _render_trace_previews(run_id, fragment_id, desktop, mobile)
    return {
        "underlay": "base",
        "fragmentId": fragment_id,
        "turn": turn,
        "source": None,
        "previews": previews,
        "next": _base_underlay_next(search_audit),
    }


def _select_reference(args: dict[str, Any]) -> dict[str, Any]:
    """Promote one traced candidate to the active underlay after the Illustrator's review."""
    run_id = args["runId"]
    turn = int(args["turn"])
    index = int(args["index"])
    candidates = _candidate_store(run_id).load(turn)
    if not candidates:
        raise BackdropError(
            "no reference candidates are waiting for this page; call endless_trace_reference first"
        )
    options = candidates.get("candidates") or []
    if not 0 <= index < len(options):
        raise BackdropError(f"pick an index between 0 and {len(options) - 1}")
    chosen = options[index]
    fragment_id = _trace_store(run_id).save(
        turn=turn,
        desktop=chosen["desktop"],
        mobile=chosen["mobile"],
        source=chosen.get("source"),
        kind="reference",
        query=str(candidates.get("query") or ""),
        # Carried from the trace that produced these candidates, so the committed
        # receipt can name which ladder rung actually matched.
        search=candidates.get("search"),
    )
    _candidate_store(run_id).clear()
    return {
        "selected": index,
        "fragmentId": fragment_id,
        "source": chosen.get("source"),
        "next": (
            "the chosen reference is now the page's underlay. Put exactly one "
            '<g id="etr-underlay"/> in each SVG (above your sky, below every mark); '
            "the server splices it in at draft and commit."
        ),
    }


def _submit_backdrop_draft(args: dict[str, Any]) -> dict[str, Any]:
    """Validate one Illustrator draft and return safe raster preview paths."""
    run_id = args["runId"]
    turn = int(args["turn"])
    request = _store().read_backdrop_request(run_id)
    if not request or int(request.get("turn") or 0) != turn:
        raise BackdropError("no backdrop is waiting for this run and turn")
    _require_scene_underlay(run_id, turn, request)
    markup = _apply_underlay(run_id, turn, args["markup"], "desktop")
    mobile = _apply_underlay(run_id, turn, args["mobile"], "mobile")
    draft = _backdrop_draft_store(run_id).submit(
        markup, mobile, turn=turn, buttons=args.get("buttons")
    )
    # The player's art-quality tier decides what the review pass owes: standard
    # keeps the lane's full review contract; fast turns it into a structural
    # sanity glance so the first competent draft ships.
    fast = read_settings(_DATA)["artQuality"] == "fast"
    return {
        "backdrop": "drafted",
        "draftId": draft["draftId"],
        "turn": turn,
        "previews": draft["previews"],
        "next": (
            (
                "fast art mode: glance at the previews only to confirm nothing is "
                "structurally broken (blank frame, unreadable composition), then "
                "commit THIS draft with endless_commit_backdrop — do not spend a "
                "revision pass."
            )
            if fast
            else "read every preview together, then follow the lane's review-pass contract"
        ),
    }


def _commit_backdrop(args: dict[str, Any]) -> dict[str, Any]:
    """Publish one reviewed Illustrator final; the draft itself was never public."""
    run_id = args["runId"]
    turn = int(args["turn"])
    draft_id = args["draftId"]
    drafts = _backdrop_draft_store(run_id)
    drafts.require(draft_id, turn)
    # Enforced at publication too, not only at draft: the draft store survives a
    # gateway restart, so a draft accepted before this gate existed must not walk
    # through it. `endless_commit_fallback_backdrop` is deliberately NOT gated — it
    # is the repair path for a page whose illustrators already failed, and refusing
    # it would leave the page with no art at all.
    _live = _store().read_backdrop_request(run_id)
    if isinstance(_live, dict) and int(_live.get("turn") or 0) == turn:
        _require_scene_underlay(run_id, turn, _live)
    trace = _trace_store(run_id).load(turn)
    source = trace.get("source") if isinstance(trace, dict) else None
    trace_audit = None
    if isinstance(trace, dict):
        kind = trace.get("kind")
        if kind not in {"reference", "base"}:
            kind = "reference" if isinstance(source, dict) else "base"
        trace_audit = {
            "pipeline": "trace",
            "underlay": kind,
            "fragmentId": str(trace.get("fragmentId") or ""),
            "query": str(trace.get("query") or ""),
            "used": True,
        }
        search = trace.get("search")
        if isinstance(search, dict):
            if kind == "base":
                fallback: dict[str, Any] = {
                    "reason": str(search.get("reason") or "no-candidates"),
                    "attempts": search.get("attempts") or [],
                }
                # A HOST fault (no tracer) is the one reason a reader cannot deduce
                # from the reason word alone — and the one that makes every later page
                # flat too — so it carries what was missing.
                if search.get("detail"):
                    fallback["detail"] = str(search.get("detail"))
                trace_audit["fallback"] = fallback
            elif search.get("matched"):
                # Which ladder rung won, so a brief that only ever matches after
                # widening is visible as a brief to rewrite, not a silent success.
                trace_audit["matched"] = str(search.get("matched"))
    markup = _apply_underlay(run_id, turn, args["markup"], "desktop")
    mobile = _apply_underlay(run_id, turn, args["mobile"], "mobile")
    version = _backdrop_store(run_id).set(
        markup,
        args.get("buttons"),
        turn,
        mobile,
        source=source if isinstance(source, dict) else None,
        trace=trace_audit,
    )
    try:
        drafts.discard(draft_id, turn)
        _trace_store(run_id).clear()
    except (BackdropError, OSError):
        # The final is already atomically published. A stale or concurrently
        # replaced draft record and leftover private thumbnails are cleanup debt,
        # never a reason to report that publication failed.
        pass
    try:
        store = _store()
        request = store.read_backdrop_request(run_id)
        if request and int(request.get("turn") or 0) == turn:
            store.clear_backdrop_request(run_id)
    except StoreError:
        # BackdropStore deliberately accepts human-shaped ids in isolated tooling;
        # recovery bookkeeping uses the stricter production run-id contract. Art
        # that already validated and stored must not be rolled back over cleanup.
        pass
    return {"backdrop": "committed", "version": version, "turn": turn}


#: Underlay-only shells: a valid backdrop that is nothing but the traced photo (or
#: procedural base) spliced into the one placeholder. The overlay was always
#: optional, so this is a complete page — used by the server-side timeout fallback.
_UNDERLAY_ONLY_DESKTOP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" '
    'preserveAspectRatio="xMidYMid slice"><g id="etr-underlay"/></svg>'
)
_UNDERLAY_ONLY_MOBILE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 450 900" '
    'preserveAspectRatio="xMidYMid slice"><g id="etr-underlay"/></svg>'
)


def commit_underlay_only(data_dir: Path, store: RunStore, run_id: str, turn: int) -> bool:
    """Publish the traced underlay ALONE as the page's backdrop, with no model.

    The server-side fallback for a page whose illustrator ran out of time: the
    underlay (a traced photograph or a procedural tonal base) is already a complete
    backdrop — the overlay was always optional — so composing it into a bare
    placeholder shell and publishing it hands the player a real image instead of
    the hand-drawn one the narrator recovery would otherwise produce.

    Parameterized by ``data_dir``/``store`` rather than the module globals so the
    route layer (which owns the RunStore and the real data dir) can call it. Returns
    whether it published: ``False`` when no usable trace exists yet (the illustrator
    never reached ``endless_trace_reference``), leaving the narrator recovery as the
    last resort.
    """
    trace = TraceStore(data_dir, run_id).load(turn)
    if not isinstance(trace, dict):
        return False
    desktop_frag = trace.get("desktop")
    mobile_frag = trace.get("mobile")
    if not (isinstance(desktop_frag, str) and desktop_frag):
        return False
    if not (isinstance(mobile_frag, str) and mobile_frag):
        return False
    source = trace.get("source") if isinstance(trace.get("source"), dict) else None
    kind = trace.get("kind")
    if kind not in {"reference", "base"}:
        kind = "reference" if source else "base"
    trace_audit = {
        "pipeline": "trace",
        "underlay": kind,
        "fragmentId": str(trace.get("fragmentId") or ""),
        "query": str(trace.get("query") or ""),
        "used": True,
        "serverFallback": True,
    }
    markup = compose_with_underlay(_UNDERLAY_ONLY_DESKTOP, desktop_frag, require_placeholder=True)
    mobile = compose_with_underlay(_UNDERLAY_ONLY_MOBILE, mobile_frag, require_placeholder=True)
    version = BackdropStore(data_dir, run_id).set(
        markup, None, turn, mobile, source=source, trace=trace_audit
    )
    try:
        TraceStore(data_dir, run_id).clear()
        request = store.read_backdrop_request(run_id)
        if request and int(request.get("turn") or 0) == turn:
            store.clear_backdrop_request(run_id)
    except (BackdropError, StoreError, OSError):
        # The backdrop is already atomically published; cleanup debt is not a
        # reason to report the fallback failed.
        pass
    BackdropTimeline(data_dir, run_id).mark(
        turn, "server-fallback-commit", underlay=kind, version=version
    )
    return True


def _commit_fallback_backdrop(args: dict[str, Any]) -> dict[str, Any]:
    """Rare narrator-authored art, accepted only after worker recovery failed."""
    run_id = args["runId"]
    turn = int(args["turn"])
    store = _store()
    request = store.read_backdrop_request(run_id)
    if not (
        request and request.get("fallbackAllowed") is True and int(request.get("turn") or 0) == turn
    ):
        raise BackdropError(
            "direct narrator backdrop commit is available only for the page "
            "whose illustrator recovery failed"
        )
    version = _backdrop_store(run_id).set(
        args["markup"], args.get("buttons"), turn, args.get("mobile")
    )
    store.clear_backdrop_request(run_id)
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
    "endless_trace_reference": _trace_reference,
    "endless_select_reference": _select_reference,
    "endless_submit_backdrop_draft": _submit_backdrop_draft,
    "endless_commit_backdrop": _commit_backdrop,
    "endless_commit_fallback_backdrop": _commit_fallback_backdrop,
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


def _lenient_json_array(raw: str) -> list[Any] | None:
    """The array twin of :func:`_lenient_json_object`, for ``choices``."""
    text = raw.strip()
    if not text:
        return None
    for attempt in (text, _repair_json_escapes(text)):
        try:
            value = json.loads(attempt)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(value, list):
            return value
    return None


#: The tools whose wall-clock is worth auditing — the backdrop pipeline. Every
#: other tool (reads, advance_turn) is timed by the turn loop already; recording
#: them here would only bury the backdrop steps the audit is about.
_BACKDROP_TIMED_TOOLS = frozenset(
    {
        "endless_paint_backdrop",
        "endless_trace_reference",
        "endless_select_reference",
        "endless_submit_backdrop_draft",
        "endless_commit_backdrop",
        "endless_commit_fallback_backdrop",
    }
)


def _record_backdrop_timing(run_id: Any, name: str, args: dict[str, Any], t0: float) -> None:
    """Append one backdrop-pipeline timing event. Best-effort and non-raising.

    ``serverMs`` is the time spent INSIDE the handler (the trace, the render); the
    gap the reader computes between two events is the model's own thinking and
    generation between calls. Together they say which half of the wait to fix.
    """
    if name not in _BACKDROP_TIMED_TOOLS or not isinstance(run_id, str) or not run_id:
        return
    try:
        raw_turn = args.get("turn")
        turn = (
            int(raw_turn)
            if raw_turn is not None
            else int(_store().read_state(run_id).get("turn") or 0)
        )
        BackdropTimeline(_DATA, run_id).mark(
            turn, f"tool:{name}", serverMs=int((time.monotonic() - t0) * 1000)
        )
    except Exception:  # noqa: BLE001 — timing must never break a tool
        pass


def call_tool(name: str, args: dict[str, Any]) -> str:
    """Validate, dispatch, and answer as JSON text.

    Every failure is reported as data rather than raised: a raised exception
    reaches the narrator as a protocol error it cannot act on, while a named
    field is something it can fix on the next attempt.
    """
    dropped_top_level: list[str] = []
    try:
        # A narrator decorates the run id despite the addressing giving it bare
        # ("run-<id>", "run-id-<id>"); recover the embedded id before anything
        # validates or looks it up, so the opening read is not wedged by a mangling
        # the model cannot see is wrong.
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
            if isinstance(args.get("statePatch"), str):
                recovered = _lenient_json_object(args["statePatch"])
                if recovered is not None:
                    args["statePatch"] = recovered
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
            # `choices` gets the same courtesy: a double-encoded array would fail
            # the schema ("got str"), and player-facing choices are the one field
            # whose loss refuses the whole turn at the choices-required gate — the
            # narrator then sees a refusal for a field it sent (observed live).
            if isinstance(args.get("choices"), str):
                recovered_list = _lenient_json_array(args["choices"])
                if recovered_list is not None:
                    args["choices"] = recovered_list
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

    _timer_start = time.monotonic()
    try:
        call_args = dict(args)
        if dropped_top_level:
            # Handed to the handler under a private key (added AFTER validation, so
            # the schema never sees it) so it can surface each drop as a warning.
            call_args["_dropped_top_level"] = dropped_top_level
        result = handler(call_args)
    except ToolInputError as exc:
        _record_backdrop_timing(run_id, name, args, _timer_start)
        return json.dumps(
            {"ok": False, "field": exc.field, "expected": exc.expected, "applied": False},
            ensure_ascii=False,
        )
    except (StoreError, WorldError, SceneLedgerError, BackdropError, DraftError) as exc:
        _record_backdrop_timing(run_id, name, args, _timer_start)
        return json.dumps({"ok": False, "error": str(exc), "applied": False}, ensure_ascii=False)
    _record_backdrop_timing(run_id, name, args, _timer_start)
    return json.dumps({"ok": True, **result}, ensure_ascii=False)


def main() -> None:  # pragma: no cover — process entry point
    if _IMPORT_ERROR or run_mcp_stdio_loop is None:
        _die(_IMPORT_ERROR or "stdio loop unavailable")
    run_mcp_stdio_loop(SERVER_NAME, SERVER_VERSION, list_tools, call_tool)


if __name__ == "__main__":  # pragma: no cover
    main()
