"""Growth a world counts: named to the narrator, read back when it stalls, shown
to the player — and never invented by the app."""

import json

import pytest

import halo
import mcp_server as srv
from template import parse_template
from turn import declaration_shape
from view import growth_rows

HEADER = {
    "id": "w",
    "title": "World",
    "version": "1.0",
    "language": "en",
    "clock": {"unit": "month", "label": "{year}"},
    "styles": [{"id": "s", "label": "S", "default": True}],
    "opening": [{"id": "name", "label": "Name", "kind": "text"}],
    "panels": [
        {
            "id": "status",
            "always": True,
            "fields": [{"id": "magic", "label": "Magic", "primitive": "field"}],
        }
    ],
    "endings": [{"id": "died", "when": "state.alive == false"}],
    "systems": [
        {
            "id": "magic-level",
            "kind": "accrual",
            "into": "state.sys.magicXp",
            "tierInto": "state.status.magic",
            "tiers": [{"at": 50, "name": "Initiate"}, {"at": 1, "name": "Apprentice"}],
        },
        # Counted, but shown in no panel: it has no player-facing name.
        {"id": "hidden", "kind": "accrual", "into": "state.sys.secretXp"},
    ],
}


def _template(header=HEADER):
    return parse_template("---\n" + json.dumps(header) + "\n---\nA world.\n")


@pytest.fixture
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "worlds").mkdir(parents=True)
    (data / "worlds" / "w.md").write_text("---\n" + json.dumps(HEADER) + "\n---\nA world.\n")
    monkeypatch.setattr(srv, "_DATA", data)
    return srv._store()


def commit(store, run, *, gains=None):
    args = {
        "runId": run,
        "turn": int(store.read_state(run).get("turn", 0)) + 1,
        "prose": "An ordinary month at the bakery.",
        "choices": [{"id": "go", "label": "Go"}],
        "state": {"status": {"magic": "Legend"}, "sys": {"magicXp": 999}},
        "gains": gains or [],
    }
    result = json.loads(srv.call_tool("endless_advance_turn", args))
    assert result.get("committed") is True, result
    return store.read_state(run)


def test_the_shape_names_each_counted_gain_and_its_ranks_in_order():
    shape = declaration_shape(_template())
    line = next(ln for ln in shape.splitlines() if ln.startswith("- gains"))
    assert "magicXp (ranks: Apprentice, Initiate)" in line
    assert "secretXp" in line
    assert "earned nothing declares no gain" in line


def test_a_world_that_counts_nothing_gets_no_gains_line():
    header = {**HEADER, "systems": []}
    assert "- gains" not in declaration_shape(_template(header))


def test_growth_is_quiet_only_after_a_full_window_with_no_counted_gain():
    month = {"turn": 1, "gains": []}
    other = {"turn": 1, "gains": [{"field": "gold", "amount": "5", "source": "sale"}]}
    full = [month] * (halo.GROWTH_WINDOW - 1) + [other]
    assert halo.growth_quiet(full, ["magicXp"])["quiet"] is True
    # Too short a life to call it a stall.
    assert halo.growth_quiet(full[:-2], ["magicXp"])["quiet"] is False
    # One counted gain in the window is growth.
    earned = full[:-1] + [{"turn": 9, "gains": [{"field": "magicXp", "amount": "3"}]}]
    assert halo.growth_quiet(earned, ["magicXp"])["quiet"] is False
    # A world that counts nothing is never quiet about growth.
    assert halo.growth_quiet(full, [])["quiet"] is False


def test_the_growth_reading_is_an_observation_that_permits_declaring_nothing():
    lived = [{"turn": i, "gains": [], "events": ["x"]} for i in range(1, halo.GROWTH_WINDOW + 1)]
    assert "magicXp" not in halo.compose_restraint(lived, "en")
    note = halo.compose_restraint(lived, "en", gain_fields=["magicXp"])
    assert "magicXp" in note and "declaring nothing is right" in note
    for word in ("state", "chronicle", "digest", "schema", "JSON"):
        assert word not in note


def test_a_month_that_earned_nothing_gains_nothing_even_after_the_reading_fires(app):
    run = app.create_run({"worldId": "w", "turn": 0}, {})
    for _ in range(halo.GROWTH_WINDOW + 2):
        after = commit(app, run)
    # The narrator echoed a huge total and a top rank every month; the app kept
    # its own zero and added nothing of its own.
    assert after["sys"]["magicXp"] == 0
    assert after["status"]["magic"] is None
    assert all(entry["gains"] == [] for entry in app.read_chronicle(run))
    runtime = json.loads(srv.call_tool("endless_read_runtime", {"runId": run}))
    assert runtime["restraint"]["growth"]["quiet"] is True
    assert "magicXp" in runtime["restraint"]["note"]
    # Reading the stall does not change the ledger either.
    assert app.read_state(run)["sys"]["magicXp"] == 0


def test_an_earned_gain_still_counts_and_clears_the_reading(app):
    run = app.create_run({"worldId": "w", "turn": 0}, {})
    for _ in range(halo.GROWTH_WINDOW):
        commit(app, run)
    after = commit(app, run, gains=[{"field": "magicXp", "amount": "60", "source": "a vigil"}])
    assert after["sys"]["magicXp"] == 60
    assert after["status"]["magic"] == "Initiate"
    runtime = json.loads(srv.call_tool("endless_read_runtime", {"runId": run}))
    assert runtime["restraint"]["growth"]["quiet"] is False


def test_the_page_shows_backend_growth_by_its_panel_label_only():
    tpl = _template()
    prev = {"sys": {"magicXp": 40, "secretXp": 0}, "status": {"magic": "Apprentice"}}
    state = {"sys": {"magicXp": 52, "secretXp": 7}, "status": {"magic": "Initiate"}}
    assert growth_rows(tpl, state, prev) == [
        {"label": "Magic", "delta": 12, "tier": "Initiate", "tierChanged": True}
    ]
    # Same rank, still growth; a fall is not shown as growth; no prior, no row.
    same = {"sys": {"magicXp": 45}, "status": {"magic": "Apprentice"}}
    assert growth_rows(tpl, same, prev)[0]["tierChanged"] is False
    assert growth_rows(tpl, {"sys": {"magicXp": 10}}, prev) == []
    assert growth_rows(tpl, state, None) == []
