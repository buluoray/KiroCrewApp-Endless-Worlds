"""Guards on pulling the runtime instead of pushing it.

The change: the state of a life, the months already lived, and the app's readings of
its own recent turns used to be rendered into every prompt. Measured before this, on
a live run's own session file, the prompt for turn four was 21,734 characters and
every part of it was re-sent whether the month needed it or not — including the parts
that had not changed since the turn before.

They are reference material, not instruction, and `endless_read_runtime` already served
them. The prompt merely made calling it pointless.

**The correction worth recording**, because it changes what is worth optimising: a
tool RESULT is also context. Moving the state from the prompt to a tool is roughly
token-neutral on its own. The saving comes from selectivity — the narrator pulls what
this month needs, unchanged fields are named rather than sent, and material nobody
asks for is never paid for.

**The trap**, which is the reason for the fingerprint: "the rest is as it was" is only
safe when the narrator can still see what "was" refers to. A delta against a vanished
baseline does not fail loudly; it hands over a few fields and a promise, and the
narrator fills the rest in from nothing. So the baseline is self-certifying — a
narrator that can still produce the fingerprint still holds the state it named, and
one that cannot asks with nothing and receives everything.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from narrator import APP_NAME  # noqa: E402
from store import RunStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    return RunStore(AppStorage(APP_NAME, data), data)


@pytest.fixture()
def run(store):
    return store.create_run({"turn": 0, "worldId": "w"}, {"worldId": "w", "title": "t"})


# ── the fingerprint is self-certifying ──────────────────────────────────────


def test_the_same_state_always_has_the_same_name(store):
    """Two serialisations of one state must not read as two states — a dict's order
    is not part of its meaning."""
    a = {"turn": 3, "status": {"age": 6, "race": "faerie"}}
    b = {"status": {"race": "faerie", "age": 6}, "turn": 3}
    assert store.fingerprint(a) == store.fingerprint(b)


def test_a_changed_state_has_a_different_name(store):
    a = {"turn": 3, "status": {"age": 6}}
    b = {"turn": 3, "status": {"age": 7}}
    assert store.fingerprint(a) != store.fingerprint(b)


def test_a_baseline_the_store_no_longer_holds_resolves_to_nothing(store, run):
    """And therefore to a full snapshot. This is the correct answer, not a limitation
    to apologise for: a delta against a baseline nobody can produce is precisely what
    makes a narrator invent the parts it cannot see.
    """
    assert store.baseline_for(run, "0" * 16) is None


def test_the_previous_turns_state_is_resolvable(store, run):
    """The one baseline a delta is ever asked from. The narrator reads the runtime, a
    turn commits, and it reads again — so "one turn back" is the whole requirement,
    and it is already on disk as the rollback copy.
    """
    first = {"turn": 1, "worldId": "w", "status": {"age": 6}}
    store.commit_state(run, first)
    name = store.fingerprint(first)

    store.commit_state(run, {"turn": 2, "worldId": "w", "status": {"age": 7}})

    assert store.baseline_for(run, name) == first, (
        "a narrator one turn behind could not be given a delta"
    )


def test_a_narrator_two_turns_behind_gets_no_delta(store, run):
    """Nothing keeps every state a life has passed through, deliberately. Two turns
    back is unresolvable, which yields a snapshot — the safe direction."""
    first = {"turn": 1, "worldId": "w"}
    store.commit_state(run, first)
    store.commit_state(run, {"turn": 2, "worldId": "w"})
    store.commit_state(run, {"turn": 3, "worldId": "w"})

    assert store.baseline_for(run, store.fingerprint(first)) is None


# ── the delta itself ────────────────────────────────────────────────────────


def test_unchanged_keys_are_named_not_sent(store):
    """The whole saving. A panel the month did not touch costs its name."""
    before = {"turn": 1, "status": {"age": 6}, "relations": {"mother": "alive"}}
    after = {"turn": 2, "status": {"age": 7}, "relations": {"mother": "alive"}}

    d = store.diff(before, after)
    assert set(d["changed"]) == {"turn", "status"}
    assert d["same"] == ["relations"]
    assert d["gone"] == []
    assert "relations" not in d["changed"], "an untouched panel was sent anyway"


def test_a_key_that_disappeared_is_reported(store):
    """Silence would read as "unchanged", which is the opposite of what happened."""
    d = store.diff({"turn": 1, "magic": {"awakened": True}}, {"turn": 2})
    assert d["gone"] == ["magic"]


def test_the_diff_is_per_panel_not_per_leaf(store):
    """A per-leaf diff would hand the narrator a shape that no longer resembles what
    it declared. "Wealth went up but the rest of the household is as it was" is a
    sentence about one panel, not about a tree."""
    before = {"status": {"age": 6, "wealth": "poor"}}
    after = {"status": {"age": 6, "wealth": "comfortable"}}
    d = store.diff(before, after)
    assert d["changed"] == {"status": {"age": 6, "wealth": "comfortable"}}, (
        "the panel must arrive whole"
    )


# ── what the prompt no longer carries ───────────────────────────────────────


def test_the_prompt_module_no_longer_renders_state_or_history():
    """The renderers are gone, not merely unused. A dormant `_render_state` is an
    invitation to call it again, and calling it again quietly undoes all of this."""
    src = (_BACKEND / "turn.py").read_text(encoding="utf-8")
    from srcguard import code_only

    code = code_only(src)
    for gone in ("_render_state(", "_render_turns(", "_summarize("):
        assert gone not in code, f"{gone} is still called from the prompt path"


def test_the_narrators_standing_orders_survive_a_compaction():
    """Where the rule has to live.

    The fingerprint self-heals when compaction takes it away with the state. It does
    NOT cover the case where a summary carries the short fingerprint string forward
    while dropping the state it named — the narrator then holds a value it cannot
    back up. Only the narrator knows that happened, so the rule belongs in its
    standing configuration, which survives the very event it is about, rather than in
    a per-turn prompt that a compaction can condense away.
    """
    agent = json.loads(
        (_BACKEND.parent / "agents" / "narrator.json").read_text(encoding="utf-8")
    )
    prompt = agent["prompt"]
    assert "endless_read_runtime" in prompt, "nothing tells it to look before writing"
    assert "compact" in prompt.lower(), (
        "the one case the fingerprint cannot detect is not mentioned"
    )
    assert "since" in prompt, "the delta parameter is never explained"

    # And the seal that makes all of this safe is untouched: the narrator reaches
    # only its own server, and the two tools this pull design needs are granted.
    own_prefix = "@endless-worlds:endless-mcp/"
    assert all(r.startswith(own_prefix) for r in agent["tools"]), "own-server tools only"
    assert own_prefix + "endless_read_runtime" in agent["tools"]
    assert own_prefix + "endless_advance_turn" in agent["tools"]
    assert agent["allowedTools"] == agent["tools"]


def test_the_tool_accepts_the_baseline_it_hands_out():
    """A closed schema refuses unknown arguments, so a `since` the schema does not
    declare would make every delta call fail — and fail as a malformed call, which
    reads like the narrator's mistake."""
    import mcp_server as srv

    tool = next(t for t in srv._TOOLS if t["name"] == "endless_read_runtime")
    props = tool["inputSchema"]["properties"]
    assert "since" in props, "the delta parameter is not accepted"
    assert tool["inputSchema"]["additionalProperties"] is False
    assert "read_runtime" in tool["description"] or "FIRST" in tool["description"], (
        "the description does not tell the narrator this comes first"
    )


# ── the read is now required ─────────────────────────────────────────────────


def test_a_commit_without_a_reading_is_refused(store, run):
    """The prompt no longer carries the state, the history, or the readings on the
    narrator's own recent turns. A narrator that skips `endless_read_runtime` is writing
    a month from the player's sentence and its own memory — not a slow turn or an ugly
    turn, but a turn about a life whose current facts it never read.
    """
    import mcp_server as srv

    srv._store = lambda: store  # type: ignore[assignment]
    store.mark_pending(run, turn=1, slot="s")

    out = srv._advance_turn({"runId": run, "turn": 1, "prose": "p", "state": {}})

    assert out["committed"] is False
    assert out["reason"] == "read-runtime-first", (
        "the refusal must be a machine token the narrator can act on"
    )
    assert int(store.read_state(run).get("turn") or 0) == 0, "the turn landed anyway"


def test_the_same_commit_succeeds_once_the_narrator_has_looked(store, run):
    """The refusal must be recoverable in one step, or it is a deadlock wearing a
    reason."""
    import mcp_server as srv

    srv._store = lambda: store  # type: ignore[assignment]
    store.mark_pending(run, turn=1, slot="s")
    store.note_runtime_read(run, turn=1)

    out = srv._advance_turn({"runId": run, "turn": 1, "prose": "p", "state": {}})
    assert out["committed"] is True
    assert int(store.read_state(run)["turn"]) == 1


def test_a_missing_record_does_not_refuse(store, run):
    """Enforced on EVIDENCE, never on the absence of it.

    A missing in-flight record proves nothing about the narrator — the app may simply
    not have written one — and refusing on that would wedge a live life over the app's
    own bookkeeping gap. An unproven omission is allowed through.
    """
    import mcp_server as srv

    srv._store = lambda: store  # type: ignore[assignment]
    assert store.read_pending(run) is None

    out = srv._advance_turn({"runId": run, "turn": 1, "prose": "p", "state": {}})
    assert out["committed"] is True


def test_a_record_for_another_turn_does_not_vouch_for_this_one(store, run):
    """A reading taken before the previous month is not a reading of this one."""
    import mcp_server as srv

    srv._store = lambda: store  # type: ignore[assignment]
    store.mark_pending(run, turn=1, slot="s")
    store.note_runtime_read(run, turn=1)
    store.commit_state(run, {**store.read_state(run), "turn": 1})

    # Turn 2 asked for, never read.
    store.mark_pending(run, turn=2, slot="s")
    out = srv._advance_turn({"runId": run, "turn": 2, "prose": "p", "state": {}})
    assert out["reason"] == "read-runtime-first"


def test_the_refusal_explains_itself_without_leaking_implementation():
    """The narrator recovers from a refusal it understands. It must not read as an
    internal error, and it must not name a file, a module, or a store."""
    import mcp_server as srv

    src = inspect.getsource(srv._advance_turn)
    detail = src[src.index("read-runtime-first"):]
    detail = detail[: detail.index("}")]
    assert "endless_read_runtime" in detail, "the fix is not named"
    for leak in ("store", "pending", "kv", ".py"):
        assert leak not in detail.lower(), f"the refusal leaks {leak!r}"


def test_a_fresh_pull_serves_what_the_opening_prompt_stopped_pushing(store, tmp_path, monkeypatch):
    """The opening prompt is now only the run id, so the narrator's first (no-`since`)
    read must carry what used to be pushed: the world's brief, the shape of the state
    to record, and the opening groups — including which the world decides rather than
    the player, the anti-halo signal (R7) that would otherwise be lost."""
    import mcp_server as srv

    flagship = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"
    if not flagship.is_file():
        pytest.skip("flagship seed not present")

    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True, exist_ok=True)
    (data / "worlds" / "age-of-sword-and-flame.md").write_text(
        flagship.read_text(encoding="utf-8"), encoding="utf-8"
    )
    run = store.create_run({"turn": 0, "worldId": "age-of-sword-and-flame"}, {"worldId": "age-of-sword-and-flame"})
    monkeypatch.setattr(srv, "_store", lambda: store)
    monkeypatch.setattr(srv, "_DATA", data)

    out = srv._read_runtime({"runId": run})

    assert out["brief"], "the world's rules must reach a narrator that was sent only an id"
    assert out["shape"], "how to record state must be pullable, not pushed"
    assert out["opening"] and "worldDecides" in out["opening"][0], (
        "the narrator must be able to tell a player's choice from one the world settled"
    )


def test_recent_turns_ride_only_on_a_full_read(store, run):
    """The narrator's session already holds the months it wrote, so a delta read
    (one that carried a baseline it could still name) gets no recent chronicle —
    only a full snapshot (a lost baseline, or the first read) does, and an explicit
    request is always honoured."""
    import mcp_server as srv

    srv._store = lambda: store  # type: ignore[assignment]
    st = {"turn": 2, "worldId": "w", "status": {"age": 7}}
    store.commit_state(run, st)
    store.append_turn(run, {"turn": 1, "prose": "born", "action": ""})
    store.append_turn(run, {"turn": 2, "prose": "a year passes", "action": "wait"})

    full = srv._read_runtime({"runId": run})
    assert full["recentTurns"], "a full read re-anchors with the recent months"
    assert "restraint" in full, "a full read carries the R7 reading"
    since = full["fingerprint"]

    delta = srv._read_runtime({"runId": run, "since": since})
    assert delta.get("basedOn") == since, "precondition: this was a delta"
    assert delta["recentTurns"] == [], "a delta must not re-push prose the session holds"
    assert "restraint" not in delta, "a delta must not re-push the R7 reading"

    asked = srv._read_runtime({"runId": run, "since": since, "recentTurns": 1})
    assert len(asked["recentTurns"]) == 1, "an explicit request is always honoured"


def test_a_commit_that_misnames_status_fields_lands_but_warns(store, tmp_path, monkeypatch):
    """The turn still commits — a live month is never held hostage — but a status
    declared under a name the panel does not key on comes back with a non-blocking
    warning naming the ids it should have used, so the narrator self-corrects."""
    import mcp_server as srv

    flagship = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"
    if not flagship.is_file():
        pytest.skip("flagship seed not present")
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True, exist_ok=True)
    (data / "worlds" / "age-of-sword-and-flame.md").write_text(
        flagship.read_text(encoding="utf-8"), encoding="utf-8"
    )
    run = store.create_run(
        {"turn": 0, "worldId": "age-of-sword-and-flame"}, {"worldId": "age-of-sword-and-flame"}
    )
    monkeypatch.setattr(srv, "_store", lambda: store)
    monkeypatch.setattr(srv, "_DATA", data)
    store.mark_pending(run, turn=1, slot="s")
    store.note_runtime_read(run, turn=1)

    bad = srv._advance_turn({
        "runId": run, "turn": 1, "prose": "p",
        "choices": [{"id": "look", "label": "look around"}],
        "state": {"worldId": "age-of-sword-and-flame", "Made Up Section": {"whatever": "x"}},
    })
    assert bad["committed"] is True, "the month lands regardless"
    warned = bad.get("warnings") or []
    assert any(w["panel"] == "status" for w in warned), "the empty always-panel is flagged"
    assert "time" in warned[0]["declareById"], "and the correct ids are offered"

    # A status keyed correctly (even partially) does not warn.
    ok = srv._advance_turn({
        "runId": run, "turn": 2, "prose": "p",
        "state": {"worldId": "age-of-sword-and-flame", "status": {"time": "Year 1"}},
        "choices": [{"id": "go", "label": "go on"}],
    })
    assert ok["committed"] is True
    assert "warnings" not in ok


def test_a_living_turn_with_no_choices_is_refused(store, tmp_path, monkeypatch):
    """A turn with no choices and no ending is a dead page; refused BEFORE it commits,
    so the player is never handed a page with nothing to do. `ending: true` is the
    escape hatch for a terminal turn."""
    import mcp_server as srv

    flagship = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"
    if not flagship.is_file():
        pytest.skip("flagship seed not present")
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True, exist_ok=True)
    (data / "worlds" / "age-of-sword-and-flame.md").write_text(
        flagship.read_text(encoding="utf-8"), encoding="utf-8")
    run = store.create_run(
        {"turn": 0, "worldId": "age-of-sword-and-flame"}, {"worldId": "age-of-sword-and-flame"})
    monkeypatch.setattr(srv, "_store", lambda: store)
    monkeypatch.setattr(srv, "_DATA", data)
    store.mark_pending(run, turn=1, slot="s")
    store.note_runtime_read(run, turn=1)

    out = srv._advance_turn({
        "runId": run, "turn": 1, "prose": "p",
        "state": {"worldId": "age-of-sword-and-flame", "status": {"time": "Y1"}},
    })
    assert out["committed"] is False and out["reason"] == "choices-required"
    assert int(store.read_state(run).get("turn") or 0) == 0, "nothing committed"
    assert store.read_chronicle(run) == []

    done = srv._advance_turn({
        "runId": run, "turn": 1, "prose": "the end", "ending": True,
        "state": {"worldId": "age-of-sword-and-flame", "status": {"time": "Y1"}},
    })
    assert done["committed"] is True
    assert store.read_chronicle(run)[0]["choices"] == []


def test_a_declared_ending_lets_a_turn_omit_choices(store, tmp_path, monkeypatch):
    """No marker needed when the committed state fires a declared world ending
    (flagship: line-ended when alive is false and there is no heir)."""
    import mcp_server as srv

    flagship = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"
    if not flagship.is_file():
        pytest.skip("flagship seed not present")
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True, exist_ok=True)
    (data / "worlds" / "age-of-sword-and-flame.md").write_text(
        flagship.read_text(encoding="utf-8"), encoding="utf-8")
    run = store.create_run(
        {"turn": 0, "worldId": "age-of-sword-and-flame"}, {"worldId": "age-of-sword-and-flame"})
    monkeypatch.setattr(srv, "_store", lambda: store)
    monkeypatch.setattr(srv, "_DATA", data)
    store.mark_pending(run, turn=1, slot="s")
    store.note_runtime_read(run, turn=1)

    out = srv._advance_turn({
        "runId": run, "turn": 1, "prose": "she dies with no heir",
        "state": {"worldId": "age-of-sword-and-flame",
                  "alive": False, "lineage": {"hasHeir": False}},
    })
    assert out["committed"] is True, "a terminal state may omit choices without a marker"


def test_a_full_read_surfaces_the_players_opening_answers(store, tmp_path, monkeypatch):
    """The narrator must honour the player's picks (sex, race, name…), so the
    opening groups carry the chosen value, not just the question."""
    import mcp_server as srv

    flagship = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"
    if not flagship.is_file():
        pytest.skip("flagship seed not present")
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True, exist_ok=True)
    (data / "worlds" / "age-of-sword-and-flame.md").write_text(
        flagship.read_text(encoding="utf-8"), encoding="utf-8"
    )
    run = store.create_run(
        {"turn": 0, "worldId": "age-of-sword-and-flame", "opening": {"sex": "Female", "name": "Aria"}},
        {"worldId": "age-of-sword-and-flame"},
    )
    monkeypatch.setattr(srv, "_store", lambda: store)
    monkeypatch.setattr(srv, "_DATA", data)

    out = srv._read_runtime({"runId": run})
    by_id = {g["id"]: g for g in out["opening"]}
    assert by_id["sex"].get("value") == "Female", "the chosen sex must reach the narrator"
    assert by_id["name"].get("value") == "Aria"
    # A group the player did not answer carries no value.
    assert "value" not in by_id["race"]
