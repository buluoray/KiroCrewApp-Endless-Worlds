"""Guards on the shape of a ``people`` field: a list of people, never one string.

Found on a real life: the shape line said only "holds figures (Key Figures)", the
narrator wrote the whole cast as one string, and the page showed one "person"
whose name was 938 characters long.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from turn import declaration_shape  # noqa: E402
from view import PERSON_NAME_MAX, _people, shape_panels, split_people  # noqa: E402
from world import read_world  # noqa: E402

WORLD = """---
{"id": "w", "title": "W", "version": "1.0", "language": "en",
 "clock": {"unit": "month", "label": "{year}"},
 "styles": [{"id": "s", "label": "S", "default": true}],
 "opening": [{"id": "name", "label": "Name", "kind": "text"}],
 "panels": [{"id": "status", "always": true,
             "fields": [{"id": "age", "label": "Age", "primitive": "field"}]},
            {"id": "relations", "when": "state.relations.known == true",
             "fields": [{"id": "figures", "label": "Key Figures", "primitive": "people",
                         "attributes": ["Name", "Station", "Trust"]}]}],
 "endings": [{"id": "died", "when": "state.alive == false"}]}
---
The hero does not always win.
"""

#: The two layouts measured on the pod test, shortened.
CLAUSES = (
    "Father Osric (gave his blessing); brother Tam; Mags Fenner (my employer for "
    "the winter); Pell (north; we are square)"
)
HEADS = (
    "Osric Hollis: father, in Millbrook; gave me his knife. Tam Hollis: brother, 11; "
    "learning letters. Mags Fenner: master of the Heron."
)
#: A paragraph that names nobody in either way.
PROSE = (
    "everyone I have met since leaving home has been kind in one way or another and "
    "I keep thinking about all of them at night when the ship is quiet and dark"
)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text(WORLD, encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA", data)
    return data


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


def _life():
    store = srv._store()
    run = store.create_run({"turn": 0, "worldId": "w"}, {"runId": "r1"})
    call("endless_read_runtime", runId=run)
    return store, run


def _commit(run, turn, **state):
    return call(
        "endless_advance_turn",
        runId=run,
        turn=turn,
        prose=f"month {turn}",
        choices=[{"id": "go", "label": "go"}],
        state={"status": {"age": turn}, **state},
    )


# -- splitting ---------------------------------------------------------------


def test_clauses_that_each_name_someone_become_people():
    assert split_people(CLAUSES) == [
        {"name": "Father Osric", "note": "gave his blessing"},
        {"name": "brother Tam", "note": ""},
        {"name": "Mags Fenner", "note": "my employer for the winter"},
        {"name": "Pell", "note": "north; we are square"},
    ]


def test_a_colon_head_starts_a_person_and_later_clauses_are_their_note():
    assert [p["name"] for p in split_people(HEADS)] == [
        "Osric Hollis",
        "Tam Hollis",
        "Mags Fenner",
    ]
    assert split_people(HEADS)[0]["note"] == "father, in Millbrook; gave me his knife"


def test_fullwidth_separators_split_too():
    text = "Li Si\uff1abrother\uff1bdislikes me\u3002Wang Wu\uff1aneighbour"
    assert [p["name"] for p in split_people(text)] == ["Li Si", "Wang Wu"]


def test_an_old_lives_string_renders_as_people_not_one_paragraph():
    rows = _people(CLAUSES, [])
    assert len(rows) == 4
    long = _people(PROSE, [])
    assert len(long) == 1
    assert len(long[0]["name"]) <= PERSON_NAME_MAX, "a paragraph is never a card's name"
    assert long[0]["note"] == PROSE, "and the words are kept, as its note"


# -- the commit ----------------------------------------------------------------


def test_a_roster_string_that_names_people_is_stored_as_a_list(app):
    store, run = _life()
    out = _commit(run, 1, relations={"known": True, "figures": CLAUSES})
    assert out.get("committed") is True, out
    figures = store.read_state(run)["relations"]["figures"]
    assert isinstance(figures, list)
    assert [p["name"] for p in figures] == ["Father Osric", "brother Tam", "Mags Fenner", "Pell"]


def test_a_string_that_names_nobody_is_refused_with_the_exact_shape(app):
    store, run = _life()
    out = _commit(run, 1, relations={"known": True, "figures": PROSE})
    assert out.get("committed") is False
    assert out["reason"] == "people-list-required"
    detail = out["detail"]
    assert "relations.figures" in detail
    assert '[{"name": "...", "note": "...", "Station": "...", "Trust": "..."}, ...]' in detail
    assert "Resend the WHOLE call" in detail
    assert int(store.read_state(run).get("turn") or 0) == 0, "nothing was committed"


def test_a_list_of_people_is_untouched(app):
    store, run = _life()
    people = [{"name": "Mags", "note": "employer", "Trust": "high"}]
    assert _commit(run, 1, relations={"known": True, "figures": people}).get("committed") is True
    assert store.read_state(run)["relations"]["figures"] == people


def test_an_old_string_carried_forward_never_refuses_a_turn(app):
    """A life committed before this rule holds the paragraph already; a turn that
    does not send that field must still commit."""
    store, run = _life()
    state = store.read_state(run)
    store.commit_state(run, {**state, "turn": 1, "relations": {"known": True, "figures": PROSE}})
    store.append_turn(run, {"turn": 1, "prose": "before"})
    call("endless_read_runtime", runId=run)
    out = call(
        "endless_advance_turn",
        runId=run,
        turn=2,
        prose="month 2",
        choices=[{"id": "go", "label": "go"}],
        state={"status": {"age": 2}},
    )
    assert out.get("committed") is True, out


# -- the shape the narrator is shown -------------------------------------------


def test_the_shape_says_a_people_field_is_a_list_and_shows_it():
    template = read_world(WORLD).template
    shape = declaration_shape(template)
    assert "figures is a LIST of people" in shape
    assert '[{"name": "...", "note": "...", "Station": "...", "Trust": "..."}, ...]' in shape


def test_the_panel_shows_one_card_per_person():
    template = read_world(WORLD).template
    panels = shape_panels(template, {"relations": {"known": True, "figures": CLAUSES}})
    figures = next(f for p in panels for f in p["fields"] if f["id"] == "figures")
    assert len(figures["entries"]) == 4
