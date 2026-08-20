"""Capability-pack rendering and degradation (task 16, design §7.2).

Pinned here rather than only in test_view because the load-bearing behaviour is
that a *bad* pack degrades to a labelled value list and never breaks the turn, and
that one bad pack cannot take down a sibling — properties that must hold no matter
what a world file carries.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from packs import render_pack_panels, resolve_path  # noqa: E402
from view import _shape, build_play_view  # noqa: E402
from world import CONTRACT, read_world  # noqa: E402

FLAGSHIP = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"


def render(packs, state):
    return render_pack_panels(packs, state, shape=_shape)


# -- path resolution ------------------------------------------------------


def test_resolve_walks_dotted_paths_and_strips_the_state_root():
    state = {"war": {"morale": 40}}
    assert resolve_path(state, "state.war.morale") == 40
    assert resolve_path(state, "war.morale") == 40


def test_resolve_maps_over_a_list_with_the_bracket_marker():
    state = {"war": {"fronts": [{"commander": "A"}, {"commander": "B"}]}}
    assert resolve_path(state, "state.war.fronts[].commander") == ["A", "B"]


def test_resolve_returns_none_or_empty_for_absent_or_mistyped_paths():
    assert resolve_path({}, "state.war.morale") is None
    # a scalar where a list was expected is a gap, not a crash
    assert resolve_path({"war": {"fronts": 5}}, "war.fronts[].commander") == []


# -- a well-formed pack renders like any panel ----------------------------


def test_a_well_formed_pack_renders_composed_fields_shaped_by_primitive():
    pack = {
        "packId": "siege-map",
        "provides": {"panelKind": "siege"},
        "consumes": ["state.war.fronts", "state.war.morale"],
        "compose": [
            {"primitive": "people", "as": "commanders", "from": "state.war.fronts[].commander"},
            {"primitive": "trend", "as": "morale", "from": "state.war.morale"},
        ],
    }
    state = {
        "war": {
            "fronts": [{"commander": "Aldric"}, {"commander": "Bren"}],
            "morale": {"value": "shaky", "direction": "down"},
        }
    }
    [panel] = render([pack], state)
    assert panel["id"] == "siege-map"
    assert panel["label"] == "siege"
    assert panel["pack"] is True
    assert "degraded" not in panel
    kinds = {f["id"]: f["kind"] for f in panel["fields"]}
    assert kinds == {"commanders": "people", "morale": "trend"}
    # `from` with [] fed the people primitive its list; shaping is the real one.
    commanders = next(f for f in panel["fields"] if f["id"] == "commanders")
    assert [e["name"] for e in commanders["entries"]] == ["Aldric", "Bren"]


# -- degradation, and its scope ------------------------------------------


def test_an_unknown_primitive_degrades_to_a_labelled_value_list():
    pack = {
        "packId": "bad",
        "consumes": ["state.war.morale"],
        "compose": [{"primitive": "renown-meter", "as": "m", "from": "state.war.morale"}],
    }
    [panel] = render([pack], {"war": {"morale": "high"}})
    assert panel["degraded"] is True and panel["pack"] is True
    # the consumes path shows as a plain labelled line
    assert [(f["label"], f["value"]) for f in panel["fields"]] == [("morale", "high")]
    assert all(f["kind"] in ("field", "gap") for f in panel["fields"])


def test_a_pack_declaring_a_newer_contract_degrades():
    pack = {
        "packId": "future",
        "contract": CONTRACT + 1,
        "consumes": ["state.x"],
        "compose": [{"primitive": "field", "as": "x", "from": "state.x"}],
    }
    [panel] = render([pack], {"x": "v"})
    assert panel["degraded"] is True


def test_a_malformed_pack_never_raises_and_degrades():
    for bad in ({"packId": ""}, {"packId": "p", "compose": "nope"}, {"packId": "p"}):
        panels = render([bad], {})
        assert len(panels) == 1
        assert panels[0]["degraded"] is True


def test_one_bad_pack_does_not_take_down_a_good_sibling():
    good = {
        "packId": "good",
        "compose": [{"primitive": "field", "as": "name", "from": "state.name"}],
    }
    bad = {"packId": "bad", "compose": [{"primitive": "nope", "as": "x", "from": "state.x"}]}
    panels = render([bad, good], {"name": "Aria", "x": 1})
    by_id = {p["id"]: p for p in panels}
    assert by_id["bad"]["degraded"] is True
    assert "degraded" not in by_id["good"]
    assert by_id["good"]["fields"][0]["value"] == "Aria"


def test_degradation_reads_compose_sources_when_consumes_is_absent():
    # No `consumes`: the fallback still names something, from the compose froms.
    pack = {"packId": "p", "compose": [{"primitive": "nope", "as": "hp", "from": "state.hp"}]}
    [panel] = render([pack], {"hp": 7})
    assert [(f["label"], f["value"]) for f in panel["fields"]] == [("hp", "7")]


# -- region tagging --------------------------------------------------------


def test_pack_panels_default_to_the_canonical_pack_region():
    # Without a region the phone tab bar drops the panel entirely (tabbar.tsx
    # skips region-less panels), so every pack panel must carry one.
    good = {"packId": "g", "compose": [{"primitive": "field", "as": "n", "from": "state.n"}]}
    bad = {"packId": "b", "compose": [{"primitive": "nope", "as": "x", "from": "state.x"}]}
    panels = render([good, bad], {"n": 1, "x": 2})
    assert [p["region"] for p in panels] == ["pack", "pack"]


def test_pack_declared_region_wins_over_the_default():
    pack = {
        "packId": "quests",
        "region": "tasks",
        "compose": [{"primitive": "field", "as": "q", "from": "state.q"}],
    }
    [panel] = render([pack], {"q": "find water"})
    assert panel["region"] == "tasks"


# -- integration through the play view -----------------------------------


@pytest.mark.skipif(not FLAGSHIP.is_file(), reason="flagship seed not present")
def test_build_play_view_appends_pack_panels_after_the_primitive_ones():
    tpl = read_world(FLAGSHIP.read_text(encoding="utf-8")).template
    pack = {
        "packId": "extra",
        "compose": [{"primitive": "field", "as": "note", "from": "state.note"}],
    }
    base = build_play_view(tpl, {"turn": 1})
    withpack = build_play_view(tpl, {"turn": 1, "note": "hi"}, capability_packs=[pack])
    assert len(withpack["panels"]) == len(base["panels"]) + 1
    added = withpack["panels"][-1]
    assert added["id"] == "extra" and added["pack"] is True
    assert added["fields"][0]["value"] == "hi"


@pytest.mark.skipif(not FLAGSHIP.is_file(), reason="flagship seed not present")
def test_no_packs_leaves_the_view_unchanged():
    tpl = read_world(FLAGSHIP.read_text(encoding="utf-8")).template
    a = build_play_view(tpl, {"turn": 1})
    b = build_play_view(tpl, {"turn": 1}, capability_packs=[])
    assert [p["id"] for p in a["panels"]] == [p["id"] for p in b["panels"]]
