"""What a runtime read leaves out because the narrator already holds it.

Measured on four real lives: a full read at the default depth was 34-261 KB, and
most of it was the page snapshots (``panels``/``digest``) riding on every
recent month; a re-briefed turn received the brief and the shape twice, once in
its prompt and once in the read it makes right after; and every delta read
re-sent the same world summary. Each omission below keeps a baseline the narrator
really holds, and each resets the same way the recall bodies do.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from chapters import brief  # noqa: E402
from store import RunStore  # noqa: E402
from turn import advance_turn, declaration_shape  # noqa: E402
from world import read_world  # noqa: E402

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
The hero does not always win.
"""


@pytest.fixture()
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    return data


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


def _life(turns=1):
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    for n in range(1, turns + 1):
        out = call(
            "endless_advance_turn",
            runId=run,
            turn=n,
            prose=f"month {n}",
            choices=[{"id": "go", "label": "go"}],
            state={"status": {"age": n}},
        )
        assert out.get("committed") is True, out
    return store, run


def _pack():
    return read_world(WORLD)


# -- recent months carry no page snapshots ----------------------------------


def test_a_full_read_re_reads_months_without_their_page_snapshots(app):
    store, run = _life(turns=2)
    # The commit stored the page snapshots: they are what this read must drop.
    assert all("panels" in e for e in store.read_chronicle(run) if e.get("turn"))

    months = call("endless_read_runtime", runId=run)["recentTurns"]
    assert [m["prose"] for m in months] == ["month 1", "month 2"]
    assert all("panels" not in m and "digest" not in m for m in months)
    # The story fields stay: what was written, and what was offered.
    assert all("choices" in m for m in months)


# -- the world summary: once per conversation -------------------------------


def test_the_world_summary_rides_once_per_conversation(app):
    store, run = _life()
    full = call("endless_read_runtime", runId=run)
    assert full["world"]["worldId"] == "w"
    assert "held" not in full

    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert "world" not in delta
    assert "world" in delta["held"]

    # A full read is a narrator that holds nothing: the summary comes back.
    again = call("endless_read_runtime", runId=run)
    assert again["world"]["worldId"] == "w"


def test_a_rotation_makes_the_world_summary_unsent_again(app):
    store, run = _life()
    full = call("endless_read_runtime", runId=run)
    # A new conversation (any rotation path) restamps the record.
    store.mark_rotation(run, turn=1)
    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert delta["world"]["worldId"] == "w"


def test_an_edited_world_summary_is_sent_again(app):
    store, run = _life()
    full = call("endless_read_runtime", runId=run)
    (app / "worlds" / "w.md").write_text(WORLD.replace('"title": "W"', '"title": "W2"'))
    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert delta["world"]["title"] == "W2"


# -- mounted scenes: re-sent only when they changed --------------------------


class _Ledger:
    def __init__(self, rows):
        self.rows = rows

    def mounted(self):
        return self.rows


def test_unchanged_scenes_are_held_and_a_changed_ledger_is_sent(app, monkeypatch):
    store, run = _life()
    rows = [{"id": "ask", "kind": "choice", "answer": None}]
    monkeypatch.setattr(srv, "_scene_ledger", lambda _run: _Ledger(rows))

    full = call("endless_read_runtime", runId=run)
    assert full["scenes"] == rows
    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert "scenes" not in delta and "scenes" in delta["held"]

    answered = [{"id": "ask", "kind": "choice", "answer": "north"}]
    monkeypatch.setattr(srv, "_scene_ledger", lambda _run: _Ledger(answered))
    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert delta["scenes"] == answered


def test_no_scenes_is_still_said_on_every_read(app):
    store, run = _life()
    full = call("endless_read_runtime", runId=run)
    delta = call("endless_read_runtime", runId=run, since=full["fingerprint"])
    assert full["scenes"] == [] and delta["scenes"] == []


# -- the brief and shape this attempt's prompt already carried ---------------


def _carried(store, run, turn, *, brief_text=None, shape_text=None):
    pack = _pack()
    b = brief(pack.template).strip() if brief_text is None else brief_text
    s = declaration_shape(pack.template) if shape_text is None else shape_text
    store.mark_briefed(
        run,
        slot="endless-run-" + run,
        turn=turn,
        carried={"brief": RunStore.content_tag(b), "shape": RunStore.content_tag(s)},
    )


def test_a_full_read_omits_the_brief_and_shape_its_own_prompt_carried(app):
    store, run = _life()
    store.mark_pending(run, turn=2, slot="endless-run-" + run)
    _carried(store, run, 2)

    read = call("endless_read_runtime", runId=run)
    assert "brief" not in read and "shape" not in read
    assert {"brief", "shape"} <= set(read["held"])
    assert "state" in read, "the rest of a full read is unchanged"


def test_a_different_text_in_the_prompt_does_not_hold_the_reads_copy(app):
    store, run = _life()
    store.mark_pending(run, turn=2, slot="endless-run-" + run)
    _carried(store, run, 2, brief_text="another variant", shape_text="another shape")

    read = call("endless_read_runtime", runId=run)
    assert read["brief"] == brief(_pack().template)
    assert read["shape"] == declaration_shape(_pack().template)


def test_a_retried_attempt_without_the_brief_in_its_prompt_gets_it_whole(app):
    store, run = _life()
    store.mark_pending(run, turn=2, slot="endless-run-" + run)
    _carried(store, run, 2)
    # A newer ask for the same month, whose prompt did not re-brief: its pending
    # record is newer than the marker, so the marker describes another attempt.
    pending = store.read_pending(run)
    pending["askedAt"] = float(pending["askedAt"]) + 10
    store._kv.set(f"pending-{run}", pending)

    read = call("endless_read_runtime", runId=run)
    assert "brief" in read and "shape" in read


def test_a_marker_for_another_turn_holds_nothing(app):
    store, run = _life(turns=2)
    _carried(store, run, 2)  # the marker of the attempt that wrote month 2
    store.mark_pending(run, turn=3, slot="endless-run-" + run)

    read = call("endless_read_runtime", runId=run)
    assert "brief" in read and "shape" in read


# -- the turn loop records what its prompt carried ---------------------------


class _Slot:
    def __init__(self, key):
        self.key = key
        self._app = "endless-worlds"
        self.memory_mode = "temporary"
        self.project = ""

    def enqueue_or_run_prompt(self, prompt, runner, state):
        state.prompts.append(prompt)
        return True


class _State:
    def __init__(self):
        self.slots = {}
        self.prompts = []

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, **_kw):
        self.slots[name] = _Slot(name)
        return self.slots[name]


def _dispatch(st, slot, prompt, **_kw):
    return slot.enqueue_or_run_prompt(prompt, None, st)


def _ask(store, run, **kw):
    # The caller pins the install generation; matching it means no install rotation.
    store.mark_narrator_generation(run, "g")
    return asyncio.run(
        advance_turn(
            state_obj=kw.pop("state"),
            store=store,
            run_id=run,
            dispatch=_dispatch,
            inline_wait_secs=0.01,
            **kw,
        )
    )


def test_a_rebriefed_prompt_records_the_exact_blocks_it_carried(app, monkeypatch):
    import narrator

    monkeypatch.setattr(narrator, "app_install_generation", lambda: "g")
    store, run = _life()
    state = _State()
    _ask(store, run, state=state, rulebook="  THE LAW  ", shape="THE SHAPE")
    assert "THE LAW" in state.prompts[0]
    assert store.prompt_carried(run, 2) == {
        "brief": RunStore.content_tag("THE LAW"),
        "shape": RunStore.content_tag("THE SHAPE"),
    }


def test_an_opening_prompt_records_that_it_carried_neither(app, monkeypatch):
    import narrator

    monkeypatch.setattr(narrator, "app_install_generation", lambda: "g")
    store, run = _life()
    state = _State()
    _ask(
        store,
        run,
        state=state,
        rulebook="THE LAW",
        shape="THE SHAPE",
        prompt_override="just the run id",
    )
    assert state.prompts == ["just the run id"]
    assert store.prompt_carried(run, 2) == {}
