"""MCP tool-surface tests — the closed surface, the write boundary, refusals."""

from __future__ import annotations

import ast
import inspect
import json
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


# -- the surface is closed ------------------------------------------------


def test_the_surface_is_exactly_the_declared_tools():
    assert {t["name"] for t in srv.list_tools()} == {
        "endless_advance_turn", "endless_read_runtime", "endless_mount_scene",
        "endless_update_scene", "endless_await_scene", "endless_dismiss_scene",
        "endless_paint_backdrop", "endless_commit_backdrop", "endless_clear_backdrop",
        "endless_export_world",
        "endless_read_draft", "endless_submit_world_draft",
    }
    assert set(srv._HANDLERS) == {t["name"] for t in srv.list_tools()}


def test_the_enforced_schema_is_the_published_schema():
    """A narrator refused for breaking a rule it was never shown is a bug in the
    server, not in the narrator."""
    for tool in srv.list_tools():
        assert srv._INPUT_SCHEMAS[tool["name"]] is tool["inputSchema"]


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

    out = call("endless_advance_turn", runId=run, turn=2, prose="…")  # state missing
    assert out["ok"] is False
    assert out["field"] == "arguments.state"
    assert out["applied"] is False
    assert store.read_state(run)["turn"] == 1, "state moved on a refused call"


@pytest.mark.parametrize(
    ("args", "field"),
    [
        ({"runId": "../etc", "turn": 2, "prose": "p", "state": {}}, "arguments.runId"),
        ({"runId": "r", "turn": 0, "prose": "p", "state": {}}, "arguments.turn"),
        ({"runId": "r", "turn": True, "prose": "p", "state": {}}, "arguments.turn"),
        ({"runId": "r", "turn": 2, "prose": "p", "state": []}, "arguments.state"),
        ({"runId": "r", "turn": 2, "prose": 5, "state": {}}, "arguments.prose"),
        ({"runId": "r", "turn": 2, "prose": "p", "state": {}, "nope": 1}, "arguments.nope"),
        (
            {"runId": "r", "turn": 2, "prose": "p", "state": {}, "choices": [{"id": "a"}]},
            "arguments.choices[0].label",
        ),
    ],
)
def test_every_bad_field_is_named(args, field):
    out = call("endless_advance_turn", **args)
    assert out["ok"] is False
    assert out["field"] == field, out


def test_true_is_not_accepted_as_a_turn_number():
    """``bool`` is an ``int`` in Python; accepting ``True`` would commit turn 1
    for a narrator that meant something else entirely."""
    out = call("endless_advance_turn", runId="r", turn=True, prose="p", state={})
    assert out["ok"] is False and out["field"] == "arguments.turn"


# -- turns ----------------------------------------------------------------


def test_a_turn_commits_prose_state_and_choices(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})

    out = call(
        "endless_advance_turn", runId=run, turn=2, prose="冬天来了。",
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
    call("endless_advance_turn", runId=run, turn=2, prose="a", state={"v": 1},
         choices=[{"id": "go", "label": "go on"}])

    again = call("endless_advance_turn", runId=run, turn=2, prose="b", state={"v": 999},
                 choices=[{"id": "go", "label": "go on"}])

    assert again["committed"] is False
    assert store.read_state(run)["v"] == 1
    assert len(store.read_chronicle(run)) == 1


def test_the_turn_number_is_stamped_by_the_server_not_trusted_from_state(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    call("endless_advance_turn", runId=run, turn=2, prose="a", state={"turn": 87},
         choices=[{"id": "go", "label": "go on"}])
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
        runId=run, turn=2, prose="the tower fell", ending=True,
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


# -- scenes ---------------------------------------------------------------


def test_a_spec_carrying_markup_is_refused_not_stripped(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_mount_scene", runId=run, sceneId="x", spec={"html": "<b>hi</b>"})
    assert out["ok"] is False
    assert "html" in out["error"]


def test_updating_an_unmounted_scene_is_an_error_not_a_silent_mount(app):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_update_scene", runId=run, sceneId="ghost", spec={"k": 1})
    assert out["ok"] is False and "ghost" in out["error"]


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
def test_a_malformed_scene_id_never_becomes_a_path(app, bad):
    store = srv._store()
    run = store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    out = call("endless_mount_scene", runId=run, sceneId=bad, spec={"k": 1})
    assert out["ok"] is False


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
            kw.arg == "file" and "stderr" in ast.unparse(kw.value)
            for kw in node.keywords
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
        {"turn": 0, "worldId": "w", "style": "classic", "language": "zh",
         "opening": {"name": "艾琳"}, "status": "awaiting-opening"},
        {"runId": "r1"},
    )

    # Exactly what the narrator sent: story state, keyed its own way, no worldId.
    call("endless_advance_turn", runId=run, turn=1, prose="他出生了。",
         state={"时间": "312年·狼月", "年龄": "0岁"},
         choices=[{"id": "go", "label": "去看看"}])

    after = store.read_state(run)
    assert after["worldId"] == "w", "the life lost its world"
    assert after["style"] == "classic"
    assert after["language"] == "zh"
    assert after["opening"] == {"name": "艾琳"}
    assert after["时间"] == "312年·狼月", "the narrator's own declaration survived"


def test_the_narrator_can_still_change_a_reserved_key_by_declaring_it(app):
    """Carried forward is not frozen: a narrator that DOES declare one means it."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w", "status": "awaiting-opening"},
                           {"runId": "r1"})
    call("endless_advance_turn", runId=run, turn=1, prose="p", state={"status": "alive"},
         choices=[{"id": "go", "label": "go on"}])
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
    call("endless_advance_turn", runId=run, turn=1, prose="p",
         choices=[{"id": "go", "label": "go"}],
         state={"digest": {"war": "帝国宣战", "trade": "商路如常"},
                "relations": {"mother": "alive", "mentor": "trusted"}})
    # Turn 2 touches only one entry in each; the rest must survive.
    call("endless_advance_turn", runId=run, turn=2, prose="p",
         choices=[{"id": "go", "label": "go"}],
         state={"digest": {"war": "战事平息"}, "relations": {"mentor": "exiled"}})
    after = store.read_state(run)
    assert after["digest"] == {"war": "战事平息", "trade": "商路如常"}
    assert after["relations"] == {"mother": "alive", "mentor": "exiled"}


def test_a_null_sub_value_retires_a_merged_entry(app):
    """The clear sentinel: null (or "") on a digest category / relation figure
    retires just that entry, leaving the rest of the cumulative block intact."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call("endless_advance_turn", runId=run, turn=1, prose="p",
         choices=[{"id": "go", "label": "go"}],
         state={"digest": {"war": "帝国宣战", "trade": "商路如常"}})
    call("endless_advance_turn", runId=run, turn=2, prose="p",
         choices=[{"id": "go", "label": "go"}],
         state={"digest": {"war": None}})
    assert store.read_state(run)["digest"] == {"trade": "商路如常"}


def test_omitting_a_merge_key_carries_the_whole_block_forward(app):
    """Unlike a plain field, a cumulative panel the narrator does not mention this
    turn is kept whole, not cleared."""
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call("endless_advance_turn", runId=run, turn=1, prose="p",
         choices=[{"id": "go", "label": "go"}],
         state={"digest": {"war": "帝国宣战"}, "年龄": "0岁"})
    call("endless_advance_turn", runId=run, turn=2, prose="p",
         choices=[{"id": "go", "label": "go"}], state={"年龄": "1岁"})
    after = store.read_state(run)
    assert after["digest"] == {"war": "帝国宣战"}, "the cumulative block persisted"
    assert after["年龄"] == "1岁"


def test_milestones_are_reached_once_and_then_permanent(app):
    """An achievement is recorded the turn its condition first holds, and stays
    recorded afterwards even if the condition later goes false (app-owned)."""
    from compile import accept_compiled_header
    header = {
        "id": "m", "title": "M", "version": "1.0", "language": "en",
        "clock": {"unit": "month", "label": "{year}"},
        "styles": [{"id": "s", "label": "S", "default": True}],
        "opening": [{"id": "name", "label": "Name", "kind": "text"}],
        "panels": [{"id": "status", "always": True,
                    "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
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
    assert [e["id"] for e in out["lore"]] == ["keep"]      # only the named lore
    assert out["lore"][0]["summary"] == "a fort"
    assert [s["id"] for s in out["systems"]] == ["xp"]     # systems.* = all
    assert "roles" not in out                               # roles not referenced
