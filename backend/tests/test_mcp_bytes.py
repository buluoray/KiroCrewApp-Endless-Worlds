"""What the narrator pays for every byte the MCP surface hands it.

A turn makes 3-4 model calls and every call resends the whole conversation, so
a tool result is paid on every later call of the conversation, and each tool's
name, description and schema sit in the prefix of EVERY call. These pin the cuts
measured on real lives: no padding whitespace, no empty fields outside the
state, a world block with only what narrating needs, and a budget on the tool
specs the narrator is given.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "card": {"promise": "A promise for the shelf.", "possibilities": ["One", "Two"]},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"},
             {"id": "fate", "label": "Fate", "kind": "text", "random": true}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
The hero does not always win.
"""

#: The ceiling on the narrator's own tool specs, in bytes of compact JSON. Measured
#: at 15,222 before the descriptions were cut to what calling each tool needs, and
#: 10,361 after; a spec that grows past this should earn its bytes in review.
NARRATOR_SPEC_BUDGET = 10_800


@pytest.fixture()
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    return data


def _raw(name, **args):
    return srv.call_tool(name, args)


def _life():
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    _raw("endless_read_runtime", runId=run)
    raw = _raw(
        "endless_advance_turn",
        runId=run,
        turn=1,
        prose="month one, a long page of story",
        choices=[{"id": "go", "label": "go"}],
        state={"status": {"age": 1, "notes": None}, "empty": {}},
    )
    return store, run, raw


def _empties(value, path=""):
    """Every dict entry under ``value`` that is null or empty, outside the state."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("state", "changed"):
                continue
            if item is None or (isinstance(item, (str, list, dict)) and not item):
                found.append(f"{path}.{key}")
            found += _empties(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            found += _empties(item, f"{path}[]")
    return found


def test_replies_carry_no_padding_whitespace(app):
    _store, run, commit = _life()
    full = _raw("endless_read_runtime", runId=run)
    delta = _raw("endless_read_runtime", runId=run, since=json.loads(full)["fingerprint"])
    error = _raw("endless_read_runtime", runId="nope")
    for raw in (commit, full, delta, error):
        compact = json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
        assert raw == compact, raw[:200]
    # The commit reply says it committed; it never echoes what was just sent.
    reply = json.loads(commit)
    assert reply["committed"] is True
    assert not {"state", "prose", "choices", "memory"} & set(reply)


def test_no_empty_field_is_sent_outside_the_state(app):
    store, run, _commit = _life()
    full = json.loads(_raw("endless_read_runtime", runId=run))
    delta = json.loads(_raw("endless_read_runtime", runId=run, since=full["fingerprint"]))
    assert _empties(full) == [] and _empties(delta) == []
    # The state itself is sent verbatim: its null and empty panel are the
    # narrator's own declaration and the baseline its fingerprint names.
    assert full["state"] == store.read_state(run)


def test_the_world_block_carries_only_what_narrating_needs(app):
    _store, run, _commit = _life()
    full = json.loads(_raw("endless_read_runtime", runId=run))
    assert set(full["world"]) <= set(srv._NARRATOR_WORLD_FIELDS)
    assert full["world"]["worldId"] == "w" and full["world"]["clockUnit"] == "month"
    # The Library card is the shelf's, not the story's.
    assert "A promise for the shelf." not in json.dumps(full)
    # Flags are sent only when true: the world-settled group says so, the
    # player's does not carry a false. The groups ride on the first page, where
    # the questions are still open.
    first = srv._store().create_run({"turn": 0, "worldId": "w"}, {"runId": "r2"})
    opening = json.loads(_raw("endless_read_runtime", runId=first))["opening"]
    assert opening == [
        {"id": "name", "label": "Name"},
        {"id": "fate", "label": "Fate", "worldDecides": True},
    ]


def test_narrator_tool_specs_fit_their_budget():
    agent = json.loads((_BACKEND.parent / "agents" / "narrator.json").read_text())
    names = {t.rsplit("/", 1)[-1] for t in agent["tools"]}
    specs = [t for t in srv.list_tools() if t["name"] in names]
    assert {t["name"] for t in specs} == names, "every narrator tool is published"
    size = len(json.dumps(specs, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert size <= NARRATOR_SPEC_BUDGET, f"narrator tool specs are {size} bytes"
