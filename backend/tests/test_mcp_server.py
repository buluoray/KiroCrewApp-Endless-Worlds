"""MCP tool-surface tests — the closed surface, the write boundary, refusals."""

from __future__ import annotations

import ast
import inspect
import json
import re
import sys
import textwrap
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from scenes import SceneLedger, SceneLedgerError  # noqa: E402

APP_JSON = _BACKEND.parent / "app.json"
AGENT_JSON = _BACKEND.parent / "agents" / "narrator.json"

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
勇者不总是赢。
"""


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Point the server at a throwaway data dir. Its real one is derived from
    the module's own path, so this is the only thing a test must redirect."""
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    return data


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


#: A well-formed run id, for cases probing some OTHER field. The published `runId`
#: pattern is the one the store enforces, so a short placeholder would be refused
#: first and the case would stop testing what it names.
_ID = "0123456789abcdef" * 2


# -- the surface is closed ------------------------------------------------


def test_the_surface_is_exactly_the_declared_tools():
    assert {t["name"] for t in srv.list_tools()} == {
        "endless_advance_turn",
        "endless_read_runtime",
        "endless_mount_scene",
        "endless_update_scene",
        "endless_await_scene",
        "endless_dismiss_scene",
        "endless_paint_backdrop",
        "endless_trace_reference",
        "endless_select_reference",
        "endless_submit_backdrop_draft",
        "endless_commit_backdrop",
        "endless_commit_fallback_backdrop",
        "endless_clear_backdrop",
        "endless_export_world",
        "endless_read_draft",
        "endless_submit_world_draft",
    }
    assert set(srv._HANDLERS) == {t["name"] for t in srv.list_tools()}


def test_the_enforced_schema_is_the_published_schema():
    """A narrator refused for breaking a rule it was never shown is a bug in the
    server, not in the narrator."""
    for tool in srv.list_tools():
        assert srv._INPUT_SCHEMAS[tool["name"]] is tool["inputSchema"]


#: Keywords that are documentation for the reader, not a constraint on the value.
#: A published keyword outside this set MUST be one `_check` acts on.
_DOC_KEYWORDS = {"description", "title"}


def test_every_published_constraint_is_one_the_validator_enforces():
    """The same-object assert above proves the two schemas are one dict; it cannot
    prove the validator READS what that dict says. It did not: `pattern` was
    published as the sentinel string "run-id" (which as a regex reads "must contain
    run-id", and a narrator duly sent `run-id-<hex>`), while `minItems` and
    `minLength` were advertised and never checked at all. A constraint the narrator
    is shown and the server ignores is as much a lie as one it is refused for."""
    enforced = set(re.findall(r'schema\.get\("([a-zA-Z]+)"', inspect.getsource(srv._check))) | {
        "type",
        "properties",
        "items",
    }

    published: dict[str, str] = {}

    def walk(node, where):
        if not isinstance(node, dict):
            return
        for key in node:
            if key not in ("properties", "items"):
                published.setdefault(key, where)
        for name, sub in (node.get("properties") or {}).items():
            walk(sub, f"{where}.{name}")
        if isinstance(node.get("items"), dict):
            walk(node["items"], f"{where}[]")

    for tool in srv.list_tools():
        walk(tool["inputSchema"], tool["name"])

    unenforced = {k: v for k, v in published.items() if k not in enforced | _DOC_KEYWORDS}
    assert not unenforced, f"published but never enforced: {unenforced}"


def test_a_published_pattern_is_a_real_regex_the_validator_applies():
    """`pattern` is honoured as a regex rather than special-cased by value, so the
    run id schema can state the shape the store actually enforces."""
    assert srv._RUN_ID["pattern"] == "^[0-9a-f]{32}$"
    good = call("endless_read_runtime", runId="a" * 32)
    assert good.get("field") != "arguments.runId", good
    # Values no repair can rescue are refused BY THE PUBLISHED PATTERN, and the
    # refusal quotes it — so the narrator is told the shape, not just told "no".
    # (A decorated-but-recoverable id is repaired upstream and never reaches here.)
    for bad in ("run-id", "a" * 31, "../etc", "9a1d8b6f-871e-4ea9"):
        out = call("endless_read_runtime", runId=bad)
        assert out["ok"] is False, f"{bad!r} should not satisfy the published pattern"
        assert out["field"] == "arguments.runId", out
        assert "^[0-9a-f]{32}$" in out["expected"], out
    # An over-long id is refused too, by the length cap that now equals the id's own
    # length rather than the 48 that left room for a prefix.
    assert srv._RUN_ID["maxLength"] == 32
    long_out = call("endless_read_runtime", runId="a" * 33)
    assert long_out["ok"] is False and long_out["field"] == "arguments.runId"
    # The sentinel is gone: nothing in the surface publishes a pattern that is not
    # a regex, which is what let the old value read as an instruction to decorate.
    for tool in srv.list_tools():
        for rule in re.findall(r"'pattern': '([^']*)'", repr(tool["inputSchema"])):
            re.compile(rule)  # raises if a sentinel crept back in
            assert rule.startswith("^"), f"{tool['name']} publishes unanchored {rule!r}"


def test_the_salvaged_arrays_publish_their_shape_without_arming_a_refusal():
    """`choices`/`events`/`gains` are salvaged, so an enforced `items` would turn a
    shape mistake into a whole-turn refusal — the exact failure the salvage exists
    to prevent. They carry the shape as a description instead, and a bare-string
    choice still commits."""
    props = srv._INPUT_SCHEMAS["endless_advance_turn"]["properties"]
    for field in ("choices", "events", "gains"):
        assert "items" not in props[field], f"{field} must not arm a schema refusal"
        assert props[field]["description"], f"{field} must still state its shape"
    # The two salvage paths the description promises are real, not just documented.
    assert "`text`" in props["choices"]["description"]
    assert srv._clean_choices(["逃跑", {"text": "反击"}]) == [
        {"label": "逃跑", "id": "c0"},
        {"label": "反击", "id": "c1"},
    ]


def test_backdrop_visual_review_schemas_require_the_complete_pair_and_draft_id():
    schemas = {tool["name"]: tool["inputSchema"] for tool in srv.list_tools()}
    assert schemas["endless_submit_backdrop_draft"]["required"] == [
        "runId",
        "turn",
        "markup",
        "mobile",
    ]
    assert schemas["endless_commit_backdrop"]["required"] == [
        "runId",
        "turn",
        "draftId",
        "markup",
        "mobile",
    ]


def test_an_unknown_tool_is_refused_by_name():
    out = call("endless_delete_everything", runId="r")
    assert out["ok"] is False
    assert out["applied"] is False
    assert "endless_delete_everything" in out["expected"]


# -- only one tool may write state ---------------------------------------


def test_exactly_one_tool_is_declared_a_state_writer():
    assert srv.STATE_WRITERS == frozenset({"endless_advance_turn"})


def test_no_handler_but_advance_turn_can_even_reach_a_writer():
    """Structural, not behavioural: the other handlers never obtain a store, so
    there is nothing for a persuaded narrator to misuse."""
    for name, handler in srv._HANDLERS.items():
        src = inspect.getsource(handler)
        if name in srv.STATE_WRITERS:
            assert "_store()" in src
            continue
        for writer in ("commit_state", "append_turn", "rollback", "create_run", "delete_run"):
            assert writer not in src, f"{name} reaches {writer}"


def test_a_scene_call_leaves_state_byte_identical(app):
    store = srv._store()
    run = store.create_run({"turn": 3, "worldId": "w", "alive": True}, {"runId": "r1"})
    # Resolved through the store's own helper: the kv filename carries a hash, so
    # a hand-built path silently pointed at a file that never existed.
    state_file = store._kv_file(store._state_key(run))
    before = state_file.read_bytes()

    assert call("endless_mount_scene", runId=run, sceneId="map", spec={"kind": "map"})["ok"]
    assert call("endless_update_scene", runId=run, sceneId="map", spec={"kind": "map2"})["ok"]
    assert call("endless_await_scene", runId=run, sceneId="map")["answered"] is False
    assert call("endless_dismiss_scene", runId=run, sceneId="map")["ok"]

    assert state_file.read_bytes() == before, "a scene call changed run state"


def test_the_scene_ledger_cannot_reach_run_state_at_all():
    src = inspect.getsource(SceneLedger)
    for reachable in ("commit_state", "RunStore", "AppStorage", "kv"):
        assert reachable not in src


# -- validation refuses whole calls --------------------------------------


def test_a_malformed_turn_applies_nothing(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})

    # `state` is no longer schema-required (statePatch is the other legal form),
    # so a turn with neither reaches the handler and is refused THERE, with a
    # reason the narrator can act on. The invariant this test exists for is
    # unchanged: a refused call applies nothing.
    out = call("endless_advance_turn", runId=run, turn=2, prose="…")  # state missing
    assert out["committed"] is False
    assert out["reason"] == "state-required"
    assert store.read_state(run)["turn"] == 1, "state moved on a refused call"


@pytest.mark.parametrize(
    ("args", "field"),
    [
        ({"runId": "../etc", "turn": 2, "prose": "p", "state": {}}, "arguments.runId"),
        # A traversal attempt is not the only bad id: the published pattern is the
        # one the store enforces, so a short placeholder is refused here too.
        ({"runId": "r", "turn": 2, "prose": "p", "state": {}}, "arguments.runId"),
        ({"runId": _ID, "turn": 0, "prose": "p", "state": {}}, "arguments.turn"),
        ({"runId": _ID, "turn": True, "prose": "p", "state": {}}, "arguments.turn"),
        ({"runId": _ID, "turn": 2, "prose": "p", "state": []}, "arguments.state"),
        ({"runId": _ID, "turn": 2, "prose": 5, "state": {}}, "arguments.prose"),
    ],
)
def test_every_bad_field_is_named(args, field):
    out = call("endless_advance_turn", **args)
    assert out["ok"] is False
    assert out["field"] == field, out


def test_true_is_not_accepted_as_a_turn_number():
    """``bool`` is an ``int`` in Python; accepting ``True`` would commit turn 1
    for a narrator that meant something else entirely."""
    out = call("endless_advance_turn", runId=_ID, turn=True, prose="p", state={})
    assert out["ok"] is False and out["field"] == "arguments.turn"


@pytest.mark.parametrize(
    ("extra", "field"),
    [
        ({"opacity": "0.5"}, "arguments.opacity"),
        ({"desktopFocalX": True}, "arguments.desktopFocalX"),
        ({"mobileFocalY": float("nan")}, "arguments.mobileFocalY"),
        ({"desktopFocalX": 1.01}, "arguments.desktopFocalX"),
    ],
)
def test_trace_numbers_must_be_finite_numeric_and_in_range(extra, field):
    out = call("endless_trace_reference", runId=_ID, turn=1, **extra)
    assert out["ok"] is False
    assert out["field"] == field


# -- turns ----------------------------------------------------------------


def test_a_turn_commits_prose_state_and_choices(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})

    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="冬天来了。",
        state={"worldId": "w", "age": 15},
        choices=[{"id": "stay", "label": "留在村里"}],
    )
    assert out == {"ok": True, "committed": True, "turn": 2}
    assert store.read_state(run)["age"] == 15
    assert store.read_chronicle(run)[-1]["prose"] == "冬天来了。"


def test_a_replayed_turn_changes_nothing(app):
    """Idempotent per (runId, turn) — a retry is usually the transport, not a
    mistake, so it is a no-op rather than a double-apply or a scolding."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="a",
        state={"v": 1},
        choices=[{"id": "go", "label": "go on"}],
    )

    again = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="b",
        state={"v": 999},
        choices=[{"id": "go", "label": "go on"}],
    )

    assert again["committed"] is False
    assert store.read_state(run)["v"] == 1
    assert len(store.read_chronicle(run)) == 1


def test_the_turn_number_is_stamped_by_the_server_not_trusted_from_state(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="a",
        state={"turn": 87},
        choices=[{"id": "go", "label": "go on"}],
    )
    assert store.read_state(run)["turn"] == 2


# -- reading --------------------------------------------------------------


def test_read_runtime_returns_state_world_and_scenes(app):
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "w"}, {"runId": "r1"})
    call("endless_mount_scene", runId=run, sceneId="map", spec={"kind": "map"}, asks=True)

    out = call("endless_read_runtime", runId=run)

    assert out["turn"] == 4
    assert out["world"]["title"] == "W"
    assert out["scenes"] == [
        {"sceneId": "map", "asks": True, "answered": False, "region": "", "label": ""}
    ]
    assert "rulebook" not in out, "the rulebook is opt-in; it is large"

    with_prose = call("endless_read_runtime", runId=run, includeProse=True)
    assert "勇者不总是赢" in with_prose["rulebook"]


def test_paint_backdrop_records_a_brief_and_draws_nothing(app):
    """The narrator's paint call only stores a brief — no SVG is authored here, so
    nothing lands in the backdrop store until the illustrator commits."""
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_paint_backdrop", runId=run, brief="a grey dawn over the wall")
    assert out["ok"] is True and out["backdrop"] == "queued"
    req = store.read_backdrop_request(run)
    assert req and req["brief"] == "a grey dawn over the wall"


def test_lenient_json_object_recovers_double_encode_and_repairs_bad_escape():
    assert srv._lenient_json_object('{"a": 1}') == {"a": 1}
    # A lone backslash (an invalid JSON escape, e.g. a Windows path) is repaired.
    assert srv._lenient_json_object('{"p": "C:\\Users"}') == {"p": "C:\\Users"}
    assert srv._lenient_json_object("not json at all") is None
    assert srv._lenient_json_object("[1, 2]") is None  # a list is not an object


def test_advance_turn_recovers_a_double_encoded_state_with_a_bad_escape(app):
    """A narrator that double-encodes `state` as a JSON string — even with a
    malformed escape — must not waste the turn: the server recovers it instead of
    refusing with 'arguments.state: got str'."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="the tower fell",
        ending=True,
        state='{"alive": false, "path": "C:\\Users"}',  # invalid \\U escape
    )
    assert out["ok"] is True, out
    assert store.read_state(run).get("path") == "C:\\Users"


WORLD_WITH_LORE = """---
{"id": "wl", "title": "WL", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "lore": [
   {"id": "premise", "always": true, "keys": [], "text": "the world overview"},
   {"id": "dragon", "keys": ["dragon"], "text": "the last dragon sleeps"}
 ],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
勇者不总是赢。
"""


def test_always_lore_rides_only_a_full_read_not_a_delta(app):
    """`always` lore is the world's standing setting. On a continuous session the
    narrator already holds it, so — like the recent months, restraint reading and
    table of contents — it rides only a FULL read (a missing/unrecognised baseline:
    the first read, or a compaction). Keyword-triggered lore is relevant NOW by
    definition and still surfaces on any read. This is the fix for 'turn 18 still
    receives the whole game premise every turn'."""
    (app / "worlds" / "wl.md").write_text(WORLD_WITH_LORE, encoding="utf-8")
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "wl"}, {"runId": "r1"})
    # The player's action names the dragon, so the keyword entry matches this turn.
    store.mark_pending(run, turn=5, slot="", action="I wake the dragon")

    full = call("endless_read_runtime", runId=run)
    assert "state" in full, "no baseline yet, so this is a full read"
    assert {e["id"] for e in full.get("lore", [])} == {"premise", "dragon"}

    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert "changed" in delta, "same state + valid fingerprint must be a delta read"
    ids = {e["id"] for e in delta.get("lore", [])}
    assert ids == {"dragon"}, f"always-lore must be dropped on a delta read; got {ids}"


WORLD_MANY_LORE = """---
{"id": "wm", "title": "WM", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "lore": [
   {"id": "l1", "keys": ["dragon"], "text": "one"},
   {"id": "l2", "keys": ["dragon"], "text": "two"},
   {"id": "l3", "keys": ["dragon"], "text": "three"},
   {"id": "l4", "keys": ["dragon"], "text": "four"},
   {"id": "l5", "keys": ["dragon"], "text": "five"},
   {"id": "l6", "keys": ["dragon"], "text": "six"}
 ],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
勇者不总是赢。
"""


def test_lore_is_capped_and_carries_no_per_turn_note(app):
    """A theme-heavy action can match many lore entries; the read returns at most
    MAX_LORE of them and never the loreNote/memoryNote instructions (those live in
    the system prompt / tool description), so it stops dumping the setting wholesale."""
    (app / "worlds" / "wm.md").write_text(WORLD_MANY_LORE, encoding="utf-8")
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "wm"}, {"runId": "r1"})
    store.mark_pending(run, turn=5, slot="", action="I hunt the dragon")

    out = call("endless_read_runtime", runId=run)
    assert len(out.get("lore", [])) == srv.MAX_LORE, "lore must be capped, not dumped whole"
    assert "loreNote" not in out, "the lore rule lives in the system prompt now"
    assert "memoryNote" not in out, "the echoes rule lives in the tool description now"


def test_a_held_lore_entry_surfaces_without_its_body(app):
    """A lore entry still SURFACES on a delta read when its keyword matched — that is
    the signal that this month is about it — but the world's standing setting does not
    change, so the text delivered earlier in this conversation is still the current
    text and is named as held instead of re-sent. Measured on one life: a single entry
    delivered 26 times, byte-identical."""
    (app / "worlds" / "wm.md").write_text(WORLD_MANY_LORE, encoding="utf-8")
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "wm"}, {"runId": "r1"})
    store.mark_pending(run, turn=5, slot="", action="I hunt the dragon")

    full = call("endless_read_runtime", runId=run)
    assert all(e.get("text") for e in full["lore"]), "precondition: a full read carries bodies"

    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert delta.get("basedOn") == full["fingerprint"], "precondition: this was a delta"
    assert delta["lore"], "a matched entry must still surface — the month IS about it"
    for e in delta["lore"]:
        assert e["held"] is True and "text" not in e
        assert e["id"], "it must still be identifiable"


# -- scenes ---------------------------------------------------------------


def test_a_spec_carrying_markup_is_refused_not_stripped(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_mount_scene", runId=run, sceneId="x", spec={"html": "<b>hi</b>"})
    assert out["ok"] is False
    assert "html" in out["error"]


def test_updating_an_unmounted_scene_upserts_rather_than_erroring(app):
    """An update to a scene that is not mounted is treated as a mount with a fresh
    nonce, so a narrator that lost track of the mount still recovers."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_update_scene", runId=run, sceneId="ghost", spec={"k": 1})
    assert out["ok"] is True and out["updated"] == "ghost"
    assert SceneLedger(srv._DATA, run).nonce("ghost")


def test_dismissing_twice_is_not_an_error(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    call("endless_mount_scene", runId=run, sceneId="m", spec={"k": 1})
    assert call("endless_dismiss_scene", runId=run, sceneId="m")["ok"]
    assert call("endless_dismiss_scene", runId=run, sceneId="m")["ok"]


def test_await_never_blocks_and_reports_the_players_answer(app, tmp_path):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    call("endless_mount_scene", runId=run, sceneId="ask", spec={"k": 1}, asks=True)

    assert call("endless_await_scene", runId=run, sceneId="ask")["answered"] is False

    # The app's own channel writes the answer — not any narrator tool.
    SceneLedger(srv._DATA, run).record_answer("ask", {"picked": "north"})

    out = call("endless_await_scene", runId=run, sceneId="ask")
    assert out["answered"] is True
    assert out["answer"] == {"picked": "north"}


def test_recording_an_answer_is_not_reachable_from_any_tool():
    """R23 — the player's side of a scene is written by the app, so no handler
    may reach it; otherwise a narrator could answer its own question."""
    for handler in srv._HANDLERS.values():
        assert "record_answer" not in inspect.getsource(handler)


def test_a_remount_clears_a_stale_answer(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    call("endless_mount_scene", runId=run, sceneId="ask", spec={"k": 1}, asks=True)
    SceneLedger(srv._DATA, run).record_answer("ask", "old")

    call("endless_mount_scene", runId=run, sceneId="ask", spec={"k": 2}, asks=True)

    assert call("endless_await_scene", runId=run, sceneId="ask")["answered"] is False


@pytest.mark.parametrize("bad", ["../x", "A", "-x", "", "a/b"])
def test_a_malformed_scene_id_is_slugified_and_never_becomes_a_path(app, bad):
    """A mangled scene id is normalized to a safe slug at the mount boundary rather
    than refused, so it can never carry a path separator or a traversal segment
    into the ledger key or the widget path."""
    import re as _re

    from widget import widget_path

    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_mount_scene", runId=run, sceneId=bad, spec={"k": 1})
    assert out["ok"] is True
    sid = out["mounted"]
    assert _re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", sid)
    assert "/" not in sid and ".." not in sid
    # The compiled-bytes path stays under the run, keyed by the slug.
    assert widget_path(srv._DATA, run, sid).name == f"{sid}.html"


def test_the_ledger_lives_under_the_run_not_beside_it(app):
    ledger = SceneLedger(app, "run-1")
    assert ledger._path == app / "runs" / "run-1" / "scenes.json"
    with pytest.raises(SceneLedgerError):
        SceneLedger(app, "../escape")


# -- packs ----------------------------------------------------------------


def test_export_world_writes_one_portable_file(app):
    out = call("endless_export_world", worldId="w")
    assert out["ok"] is True
    exported = Path(out["path"])
    assert exported.is_file()
    assert "勇者不总是赢" in exported.read_text(encoding="utf-8")


def test_export_world_refuses_a_path_dressed_as_a_world_id(app):
    for bad in ("../../etc/passwd", "a/b", ".hidden"):
        out = call("endless_export_world", worldId=bad)
        assert out["ok"] is False, bad


def test_export_world_on_an_absent_world_is_a_clean_error(app):
    out = call("endless_export_world", worldId="nope")
    assert out["ok"] is False and "nope" in out["error"]


# -- nothing here can talk to the player ---------------------------------


def test_no_tool_description_leaks_implementation_vocabulary():
    """R25.2 — these descriptions are the narrator's mental model of the game.
    Implementation words here are what end up echoed at the player."""
    for tool in srv.list_tools():
        text = f"{tool['name']} {tool['description']}".lower()
        for word in ("schema", "primitive", "contract", "json", "mcp", "database"):
            assert word not in text, f"{tool['name']} says {word!r}"


def test_no_handler_can_emit_a_prompt_or_approval():
    src = inspect.getsource(srv)
    for banned in ("request_permission", "ask_question", "input(", "approval"):
        assert banned not in src


def test_the_server_fails_loudly_when_its_dependency_is_missing():
    """kiro-cli drops an unresolvable tool silently, so a server that limped
    along with a hand-rolled protocol would be the one failure with no signal."""
    src = inspect.getsource(srv._die)
    assert "stderr" in src and "exit(1)" in src


def test_stdout_is_never_written_to_outside_the_protocol():
    """stdout is the JSON-RPC channel; a stray print corrupts the stream.

    Checked as a CALL, via the parse tree, and not as the substring ``print(``. The
    substring form failed on the line ``fingerprint = store.fingerprint(state)`` —
    "finger*print*(" — which is the seventh time in this codebase that a source guard
    matched something that merely contained its forbidden text. A rule about calling
    a function should be expressed as a call.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(srv)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "print"):
            continue
        to_stderr = any(
            kw.arg == "file" and "stderr" in ast.unparse(kw.value) for kw in node.keywords
        )
        if not to_stderr:
            pytest.fail(f"print without stderr on line {node.lineno}")


# -- the app's own keys survive a full-state declaration -----------------


def test_a_commit_keeps_the_keys_the_narrator_never_declares(app):
    """A named regression. ``endless_advance_turn`` replaces state wholesale, which
    is right — a field the narrator stops declaring is a fact that stopped being
    true. But ``worldId`` was never the narrator's to declare, and losing it made
    the life unreadable the moment its first turn landed: the play view could no
    longer find its world, so the world vanished from the page."""
    store = srv._store()
    run = store.create_run(
        {
            "turn": 0,
            "worldId": "w",
            "style": "classic",
            "language": "zh",
            "opening": {"name": "艾琳"},
            "status": "awaiting-opening",
        },
        {"runId": "r1"},
    )

    # Exactly what the narrator sent: story state, keyed its own way, no worldId.
    call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="他出生了。",
        state={"时间": "312年·狼月", "年龄": "0岁"},
        choices=[{"id": "go", "label": "去看看"}],
    )

    after = store.read_state(run)
    assert after["worldId"] == "w", "the life lost its world"
    assert after["style"] == "classic"
    assert after["language"] == "zh"
    assert after["opening"] == {"name": "艾琳"}
    assert after["时间"] == "312年·狼月", "the narrator's own declaration survived"


def test_the_narrator_can_still_change_a_reserved_key_by_declaring_it(app):
    """Carried forward is not frozen: a narrator that DOES declare one means it."""
    store = srv._store()
    run = store.create_run(
        {"turn": 0, "worldId": "w", "status": "awaiting-opening"}, {"runId": "r1"}
    )
    call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        state={"status": "alive"},
        choices=[{"id": "go", "label": "go on"}],
    )
    assert store.read_state(run)["status"] == "alive"


def test_a_field_the_narrator_stops_declaring_is_gone(app):
    """The other half, and it must stay true: state is a full declaration, so a
    fact that stopped being declared stopped being true."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call("endless_advance_turn", runId=run, turn=1, prose="p", state={"债务": "父亲欠债"})
    call("endless_advance_turn", runId=run, turn=2, prose="p", state={"年龄": "1岁"})
    after = store.read_state(run)
    assert "债务" not in after
    assert after["worldId"] == "w"


def test_digest_and_relations_merge_forward_only_what_changed(app):
    """The cumulative panels are the exception to whole-state replace: the narrator
    declares only the categories/figures that moved this span, and the unmentioned
    ones persist rather than vanishing — so it stops re-sending the whole block."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={
            "digest": {"war": "帝国宣战", "trade": "商路如常"},
            "relations": {"mother": "alive", "mentor": "trusted"},
        },
    )
    # Turn 2 touches only one entry in each; the rest must survive.
    call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"digest": {"war": "战事平息"}, "relations": {"mentor": "exiled"}},
    )
    after = store.read_state(run)
    assert after["digest"] == {"war": "战事平息", "trade": "商路如常"}
    assert after["relations"] == {"mother": "alive", "mentor": "exiled"}


def test_a_null_sub_value_retires_a_merged_entry(app):
    """The clear sentinel: null (or "") on a digest category / relation figure
    retires just that entry, leaving the rest of the cumulative block intact."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"digest": {"war": "帝国宣战", "trade": "商路如常"}},
    )
    call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"digest": {"war": None}},
    )
    assert store.read_state(run)["digest"] == {"trade": "商路如常"}


def test_omitting_a_merge_key_carries_the_whole_block_forward(app):
    """Unlike a plain field, a cumulative panel the narrator does not mention this
    turn is kept whole, not cleared."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"digest": {"war": "帝国宣战"}, "年龄": "0岁"},
    )
    call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"年龄": "1岁"},
    )
    after = store.read_state(run)
    assert after["digest"] == {"war": "帝国宣战"}, "the cumulative block persisted"
    assert after["年龄"] == "1岁"


def test_a_run_prefix_the_narrator_adds_is_stripped_from_the_run_id():
    """The addressing hands the run id over bare, but the narrator decorates it
    anyway; a stored id is 32 lowercase hex and nothing else, so the embedded bare id
    is the one it meant — whatever spelling the decoration took."""
    hexid = "a" * 32
    for bad in (
        f"run-{hexid}",
        f"run_{hexid}",
        f"run-id-{hexid}",  # observed live: wedged the mandatory first read
        f"runId-{hexid}",
        f'"{hexid}"',
        f"run id: {hexid}",
    ):
        args = {"runId": bad}
        srv._normalize_run_id_arg(args)
        assert args["runId"] == hexid, f"{bad} should normalize to the bare id"
    # A bare id and a genuinely different value are both left untouched.
    for keep in (hexid, "run-not-a-bare-id", "endless-run-x"):
        args = {"runId": keep}
        srv._normalize_run_id_arg(args)
        assert args["runId"] == keep


def test_two_candidate_ids_in_one_arg_are_left_to_fail_loudly():
    """Repair is only safe while the id is unambiguous: two bare ids in one string
    give no way to tell which life to write, and guessing is worse than refusing."""
    args = {"runId": f"run-{'a' * 32}-{'b' * 32}"}
    srv._normalize_run_id_arg(args)
    assert args["runId"] == f"run-{'a' * 32}-{'b' * 32}", "ambiguous input is untouched"
    # A longer hex run is not a bare id with decoration either — truncating it would
    # silently address some other run.
    long_hex = "c" * 40
    args = {"runId": long_hex}
    srv._normalize_run_id_arg(args)
    assert args["runId"] == long_hex


def test_a_run_prefixed_id_reaches_the_handler_instead_of_being_refused(app):
    """End to end: a read whose runId carries the stray prefix resolves the run
    rather than failing with 'malformed run id', so the opening turn is not blocked."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    bare = json.dumps(call("endless_read_runtime", runId=run))
    prefixed = json.dumps(call("endless_read_runtime", runId=f"run-{run}"))
    assert "malformed" not in prefixed, "the run- prefix should be tolerated"
    assert prefixed == bare, "a run-prefixed id must resolve the same run as the bare id"


def test_a_memory_event_missing_a_field_is_repaired_not_dropped(app):
    """Memory blocks the turn at neither layer AND loses nothing repairable: an event
    missing its title passes the structure-only schema, then takes its title from the
    summary the narrator did write, so it is recorded with no warning at all."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"alive": True},
        memory={"events": [{"key": "k", "summary": "s", "disclosure": "known"}]},
    )
    assert out.get("committed") is True and out.get("ok") is not False
    (entry,) = store.read_chronicle(run)
    (ev,) = entry["memory"]["events"]
    assert ev["title"] == "s", "the summary named the event"
    assert not [w for w in out.get("warnings") or [] if w.get("panel") == "memory"]


def test_a_null_optional_field_is_absent_not_a_type_error(app):
    """The live report: `memory.events[0].place: null` was refused at the SCHEMA
    layer with `a string, got NoneType` and applied:false — the whole turn, prose and
    choices included, lost to a field that was saying "nothing here". A null optional
    field now means what omitting it means."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"alive": True},
        memory={
            "events": [
                {
                    "key": "k",
                    "title": "t",
                    "summary": "s",
                    "place": None,
                    "importance": None,
                    "participants": None,
                    "disclosure": "known",
                }
            ]
        },
    )
    assert out.get("ok") is not False, f"the turn was refused: {out}"
    assert out.get("committed") is True
    (entry,) = store.read_chronicle(run)
    (ev,) = entry["memory"]["events"]
    assert "place" not in ev and ev["title"] == "t"
    assert not [w for w in out.get("warnings") or [] if w.get("panel") == "memory"]


def test_a_null_entry_in_a_list_is_a_hole_not_a_refusal(app):
    """A null ENTRY is a gap in a list the narrator built. Drop the hole, keep the
    list — refusing would cost the turn over nothing at all."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"alive": True},
        memory={"entities": [None, {"id": "elin", "kind": "character", "name": "Elin"}]},
    )
    assert out.get("ok") is not False and out.get("committed") is True
    (entry,) = store.read_chronicle(run)
    assert [e["id"] for e in entry["memory"]["entities"]] == ["elin"]


def test_a_null_REQUIRED_field_is_still_refused(app):
    """The line the repair does not cross: `prose: null` is a real failure, and
    committing a blank page would be worse than refusing the call."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose=None,
        choices=[{"id": "go", "label": "go"}],
        state={"alive": True},
    )
    assert out.get("ok") is False and out.get("applied") is False
    assert out.get("field") == "arguments.prose"


def test_the_reported_warning_batch_now_repairs_to_zero_warnings(app):
    """The live report, verbatim: five colon-namespaced entity ids and one titleless
    event produced six warnings and lost all six pieces. The same block now commits
    whole with no memory warning."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    memory = {
        "entities": [
            {"id": "character:lin-shuang", "kind": "character", "name": "林霜"},
            {"id": "character:hui-ya", "kind": "character", "name": "灰鸦"},
            {"id": "group:darkflame-court", "kind": "group", "name": "黑焰廷"},
            {"id": "place:old stone bridge", "kind": "place", "name": "老石桥"},
            {"id": "concept:resonant-notation", "kind": "concept", "name": "共鸣符记法"},
        ],
        "events": [
            {
                "key": "event:1:met-hui-ya",
                "summary": "他在桥上遇见灰鸦。",
                "participants": ["character:hui-ya"],
                "place": "place:old stone bridge",
                "disclosure": "known",
            }
        ],
    }
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="p",
        choices=[{"id": "go", "label": "go"}],
        state={"alive": True},
        memory=memory,
    )
    assert out.get("committed") is True
    assert not [w for w in out.get("warnings") or [] if w.get("panel") == "memory"], (
        "every piece of the reported batch is repairable"
    )
    (entry,) = store.read_chronicle(run)
    assert [e["id"] for e in entry["memory"]["entities"]] == [
        "lin-shuang",
        "hui-ya",
        "darkflame-court",
        "old-stone-bridge",
        "resonant-notation",
    ]
    (ev,) = entry["memory"]["events"]
    assert ev["key"] == "met-hui-ya" and ev["title"] == "他在桥上遇见灰鸦。"
    assert ev["participants"] == ["hui-ya"] and ev["place"] == "old-stone-bridge"


def test_milestones_are_reached_once_and_then_permanent(app):
    """An achievement is recorded the turn its condition first holds, and stays
    recorded afterwards even if the condition later goes false (app-owned)."""
    from compile import accept_compiled_header

    header = {
        "id": "m",
        "title": "M",
        "version": "1.0",
        "language": "en",
        "clock": {"unit": "month", "label": "{year}"},
        "styles": [{"id": "s", "label": "S", "default": True}],
        "opening": [{"id": "name", "label": "Name", "kind": "text"}],
        "panels": [
            {
                "id": "status",
                "always": True,
                "fields": [{"id": "age", "label": "Age", "primitive": "field"}],
            }
        ],
        "endings": [{"id": "died", "when": "state.dead == true"}],
        "milestones": [{"id": "adult", "label": "Came of age", "when": "state.age >= 18"}],
    }
    res = accept_compiled_header("prose\n", header)
    assert res.ok, res.problem
    (srv._DATA / "worlds" / "m.md").write_text(res.world_text, encoding="utf-8")

    state = {"worldId": "m", "age": 20}
    srv._apply_milestones("r", state, {})
    assert state["milestones"] == ["adult"]

    # Permanent: reached before, condition now false → still there, not duplicated.
    later = {"worldId": "m", "age": 5}
    srv._apply_milestones("r", later, {"milestones": ["adult"]})
    assert later["milestones"] == ["adult"]


def test_resolve_handoff_selects_named_entries_and_stars() -> None:
    from types import SimpleNamespace

    from template import Lore, Role, System

    tmpl = SimpleNamespace(
        hand_to_agent=["lore.keep", "systems.*"],
        lore=[
            Lore(id="keep", keys=["x"], text="body", name="Keep", summary="a fort"),
            Lore(id="other", keys=["y"], text="b2"),
        ],
        systems=[System(id="xp", kind="accrual", into="state.xp")],
        roles=[Role(id="r1", name="R1")],
    )
    out = srv._resolve_handoff(tmpl)
    assert [e["id"] for e in out["lore"]] == ["keep"]  # only the named lore
    assert out["lore"][0]["summary"] == "a fort"
    assert [s["id"] for s in out["systems"]] == ["xp"]  # systems.* = all
    assert "roles" not in out  # roles not referenced


# -- per-turn tool calls are fail-soft (Tier 1) ---------------------------


def test_sanitize_read_runtime_args_clamps_and_coerces():
    """The optional read args are model-manglable, so they are normalized rather
    than allowed to refuse the mandatory first read."""
    a = {
        "runId": "x",
        "recentTurns": 9999,
        "since": 123,
        "memoryEvents": "nope",
        "chapters": [1, 2],
        "includeProse": "yes",
    }
    srv._sanitize_read_runtime_args(a)
    assert a["recentTurns"] == 50  # clamped into [0, 50]
    assert "since" not in a  # a non-string since is dropped
    assert a["memoryEvents"] == []  # a non-list becomes empty
    assert a["chapters"] == ["1", "2"]  # coerced to bounded strings
    assert a["includeProse"] is True  # coerced to a bool

    b = {"recentTurns": -3}
    srv._sanitize_read_runtime_args(b)
    assert b["recentTurns"] == 0  # negative clamps to 0

    c = {"recentTurns": "nope"}
    srv._sanitize_read_runtime_args(c)
    assert "recentTurns" not in c  # a non-int is dropped, not clamped

    d = {"since": "z" * 100}
    srv._sanitize_read_runtime_args(d)
    assert len(d["since"]) == 64  # over-long since is truncated


def test_read_runtime_is_never_refused_over_a_bad_optional_arg(app):
    """End to end: the first read survives every mangled optional arg and returns,
    instead of a schema refusal that would leave the narrator unable to look."""
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_read_runtime",
        runId=run,
        recentTurns=9999,
        since=123,
        memoryEvents="not-a-list",
        chapters=[1, 2],
        includeProse="yes",
    )
    assert out["ok"] is True, out
    assert out["turn"] == 4


def test_a_stray_top_level_arg_is_dropped_and_warned_not_refused(app):
    """A misplaced top-level key (a model typo, a field from another tool) is
    dropped-and-warned; the prose/choices/state the narrator DID send still commit."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"worldId": "w", "age": 1},
        choices=[{"id": "go", "label": "go on"}],
        nonsense={"x": 1},
    )
    assert out["ok"] is True and out["committed"] is True
    assert "nonsense" in {w["field"] for w in out.get("warnings") or []}
    assert store.read_state(run)["age"] == 1


def test_gains_without_a_field_are_dropped_and_warned(app):
    """A gain anchors on its `field`; one without a usable field is dropped-and-
    warned and unknown keys are stripped, rather than refusing the turn."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"worldId": "w"},
        choices=[{"id": "go", "label": "go on"}],
        gains=[{"amount": "5"}, {"field": "gold", "amount": "5", "junk": 1}],
    )
    assert out["ok"] is True and out["committed"] is True
    gain_fields = {w["field"] for w in out.get("warnings") or [] if w.get("panel") == "gains"}
    assert "gains[0].field" in gain_fields
    assert store.read_chronicle(run)[-1]["gains"] == [{"field": "gold", "amount": "5"}]


def test_choices_are_salvaged_labelless_dropped_id_synthesized(app):
    """_clean_choices is the gate: a labelless entry is dropped, a missing id is
    synthesized, and unknown keys are stripped — the schema only bounds the array."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"worldId": "w"},
        choices=[
            {"label": "no id here", "junk": 9},
            {"id": ""},
            {"id": "keep", "label": "keep me"},
        ],
    )
    assert out["ok"] is True and out["committed"] is True
    assert store.read_chronicle(run)[-1]["choices"] == [
        {"label": "no id here", "id": "c0"},
        {"id": "keep", "label": "keep me"},
    ]


def test_a_living_turn_left_with_no_usable_choice_is_still_refused(app):
    """The choices-required gate runs on the CLEANED result: a living turn whose
    only choice was unusable is refused, exactly as an empty choices array is."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"worldId": "w", "alive": True},
        choices=[{"id": "x"}],
    )
    assert out["committed"] is False
    assert out["reason"] == "choices-required"
    # The refusal must name the TRUE failure — entries were sent but unusable —
    # and spell out the accepted shape, or the narrator retries the same call
    # forever (observed live: six identical retries on `text` captions).
    assert "none had a usable caption" in out["detail"]
    assert "`label`" in out["detail"]


def test_choice_effects_are_vocabulary_gated_and_tints_validated(app):
    """The narrator declares an effect NAME; only the app's vocabulary passes.
    An invented effect or a non-hex tint degrades to static styling — never a
    refused turn, and never a model-authored value reaching the DOM as code."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"worldId": "w"},
        choices=[
            {"label": "接过王剑", "fateful": True, "effect": "embers", "tint": "#c9a227"},
            {"label": "退后一步", "effect": "sparkle-explosion"},
            {"label": "沉默", "effect": "aura", "tint": "red"},
        ],
    )
    assert out["ok"] is True and out["committed"] is True
    committed = store.read_chronicle(run)[-1]["choices"]
    assert committed[0]["effect"] == "embers" and committed[0]["tint"] == "#c9a227"
    assert "effect" not in committed[1], "an invented effect name is dropped"
    assert committed[2]["effect"] == "aura"
    assert "tint" not in committed[2], "a non-hex tint is dropped"


def test_a_double_encoded_choices_array_is_recovered_not_refused(app):
    """A narrator that JSON-encodes the choices array into a string must not
    lose the whole turn: the same courtesy state/memory already get."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"worldId": "w"},
        choices='[{"id": "flee", "label": "逃跑"}, {"label": "反击"}]',
    )
    assert out["ok"] is True and out["committed"] is True
    committed = store.read_chronicle(run)[-1]["choices"]
    assert [c["label"] for c in committed] == ["逃跑", "反击"]


def test_choice_captions_are_salvaged_from_common_alias_keys(app):
    """Observed live: a narrator sent `text` captions and every entry was silently
    dropped, turning into a choices-required refusal for a field it DID send.
    The caption is the content; the key spelling is not."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"worldId": "w"},
        choices=[{"text": "逃跑"}, {"title": "反击", "id": "fight"}, "大声呼救", {"junk": 9}],
    )
    assert out["ok"] is True and out["committed"] is True
    committed = store.read_chronicle(run)[-1]["choices"]
    assert [c["label"] for c in committed] == ["逃跑", "反击", "大声呼救"]
    assert committed[1]["id"] == "fight"
    assert all(c.get("id") for c in committed)


def test_events_are_coerced_to_bounded_strings(app):
    """The anti-halo events log is enrichment: non-strings are coerced, long lines
    truncated, and the list capped at 12 — a mangled entry never refuses the turn."""
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"worldId": "w"},
        choices=[{"id": "go", "label": "go on"}],
        events=[123, "x" * 500] + ["e"] * 20,
    )
    assert out["ok"] is True and out["committed"] is True
    stored = store.read_chronicle(run)[-1]["events"]
    assert len(stored) == 12
    assert stored[0] == "123"
    assert len(stored[1]) == 200
    assert all(isinstance(e, str) for e in stored)


def test_a_whitespace_or_case_mangled_bare_run_id_is_repaired():
    """A stored id is uuid4().hex — 32 lowercase hex — so a trimmed/lowercased
    value that IS a bare id is the one the narrator meant; anything else is left."""
    hexid = "a1b2c3d4" * 4  # 32 lowercase hex
    for bad in (f"  {hexid}  ", hexid.upper(), f"\n{hexid.upper()}\t"):
        args = {"runId": bad}
        srv._normalize_run_id_arg(args)
        assert args["runId"] == hexid, f"{bad!r} should repair to the bare id"
    for keep in ("Run-Not-Bare", "some-slug-id"):
        args = {"runId": keep}
        srv._normalize_run_id_arg(args)
        assert args["runId"] == keep


# -- the player's playability settings are enforced at the gates -----------


def test_paint_backdrop_is_a_no_op_when_the_player_turned_art_off(app):
    from settings import write_settings

    write_settings(app, model="", reasoning_effort="", backdrops=False)
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_paint_backdrop", runId=run, brief="a grey dawn over the wall")
    assert out["ok"] is True and out["backdrop"] == "off"
    # Nothing queued: no illustrator will run and the page never waits on art.
    assert store.read_backdrop_request(run) is None


def test_sparse_cadence_declines_a_brief_too_soon_after_the_last_art(app):
    from backdrop import BackdropStore
    from settings import SPARSE_GAP_TURNS, write_settings

    write_settings(app, model="", reasoning_effort="", backdrop_cadence="sparse")
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "w"}, {"runId": "r1"})
    BackdropStore(app, run).set('<svg xmlns="http://www.w3.org/2000/svg"/>', turn=4)

    out = call("endless_paint_backdrop", runId=run, brief="LANE: motif\nTHESIS: too soon")
    assert out["backdrop"] == "kept"
    assert store.read_backdrop_request(run) is None

    # Far enough from the last art, the same brief is accepted again.
    store.commit_state(run, {"turn": 4 + SPARSE_GAP_TURNS, "worldId": "w"})
    out = call("endless_paint_backdrop", runId=run, brief="LANE: motif\nTHESIS: earned now")
    assert out["backdrop"] == "queued"


def test_sparse_cadence_still_accepts_a_replacement_brief_for_a_pending_page(app):
    # A re-brief for a page whose art is already pending is recovery, not a new
    # spend — refusing it would wedge the recovery loop.
    from backdrop import BackdropStore
    from settings import write_settings

    write_settings(app, model="", reasoning_effort="", backdrop_cadence="sparse")
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "w"}, {"runId": "r1"})
    BackdropStore(app, run).set('<svg xmlns="http://www.w3.org/2000/svg"/>', turn=3)
    store.request_backdrop(run, turn=4, brief="LANE: motif\nTHESIS: first direction")

    out = call("endless_paint_backdrop", runId=run, brief="LANE: motif\nTHESIS: simpler")
    assert out["backdrop"] == "queued"
    req = store.read_backdrop_request(run)
    assert req and "simpler" in req["brief"]


def test_a_disabled_style_is_rewritten_before_the_brief_is_stored(app):
    from settings import write_settings

    write_settings(app, model="", reasoning_effort="", styles=["watercolor", "oil", "minimal"])
    store = srv._store()
    run = store.create_run({"turn": 4, "worldId": "w"}, {"runId": "r1"})
    call(
        "endless_paint_backdrop",
        runId=run,
        brief='LANE: scene\nSTYLE: photo\nREFERENCE: subject="stone bridge"',
    )
    req = store.read_backdrop_request(run)
    assert req and req["style"] == "watercolor"
    assert "STYLE: photo" not in req["brief"]


def test_choice_decoration_switches_strip_art_and_effects(app):
    from settings import write_settings

    write_settings(app, model="", reasoning_effort="", choice_art=False, choice_effects=False)
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="p",
        state={"turn": 2},
        choices=[
            {
                "label": "I open the door",
                "fateful": True,
                "art": '<svg xmlns="http://www.w3.org/2000/svg"/>',
                "effect": "shimmer",
                "tint": "#aabbcc",
            }
        ],
    )
    assert out["ok"] is True
    stored = store.read_chronicle(run)[-1]["choices"][0]
    assert "art" not in stored and "effect" not in stored and "tint" not in stored
    # The choice itself always survives its decoration.
    assert stored["label"] == "I open the door" and stored["fateful"] is True
