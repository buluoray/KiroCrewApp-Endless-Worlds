"""Guards on reading a life backwards, and on the shelf appearing once.

Two things the screenshot made obvious.

**The shelf was on screen twice.** On desktop the rail lists every life and every
world, permanently. The reading column listed them again — "你正在过的人生" over four
rows, and the identical four rows two inches to the left. A rail is only worth its
width if it replaces something.

**A life could not be re-read.** The play page shows the newest month and nothing
before it, so a player twelve months in had no way back to what happened in the
third. The store had every turn on disk the whole time; nothing exposed them.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import routes as routes_mod  # noqa: E402
from narrator import APP_NAME  # noqa: E402
from store import RunStore  # noqa: E402
from srcguard import code_only  # noqa: E402
from uisrc import WEB_SRC, module, styles  # noqa: E402

BREAKPOINT = 1100


@pytest.fixture()
def store(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    return RunStore(AppStorage(APP_NAME, data), data)


# ── the route ───────────────────────────────────────────────────────────────


def test_the_chronicle_is_its_own_route_not_a_field_on_the_play_view():
    """They have opposite shapes. The play view is re-read every few seconds while a
    month is written and must stay small; a life's history is a hundred turns of
    prose. Folding one into the other makes every poll carry the whole life.
    """
    src = (_BACKEND / "routes.py").read_text(encoding="utf-8")
    assert 'path="/runs/{run_id}/chronicle"' in src, "the history is not reachable"

    from view import build_play_view
    from world import read_world

    seed = _BACKEND.parent / "seeds" / "jianhuo-jiyuan.md"
    if not seed.is_file():
        pytest.skip("flagship seed not present")
    pack = read_world(seed.read_text(encoding="utf-8"))
    view = build_play_view(
        pack.template,
        {"turn": 3},
        chronicle=[{"turn": i, "prose": "p" * 500} for i in range(1, 4)],
        scenes=[],
    )
    assert "turns" not in view, "the play view carries the whole history"
    assert isinstance(view.get("prose"), str), "the newest month is still shown"


def test_paging_is_by_turn_number_not_by_offset():
    """An offset shifts under a turn committed between two pages, which silently
    skips or repeats a month. A turn number cannot."""
    src = (_BACKEND / "routes.py").read_text(encoding="utf-8")
    fn = code_only(
        src[src.index("async def get_chronicle") : src.index("CHRONICLE_PAGE = ")]
    )
    assert '"before"' in fn, "there is no way to ask for earlier months"
    # Searched in the CODE: the comment above this route explains why an offset is
    # wrong, and therefore contains the word.
    assert "offset" not in fn, "paging by offset can skip or repeat a month"


def test_a_malformed_query_shows_the_history_rather_than_an_error():
    """A stale bookmark carrying ``?limit=abc`` is not the player's mistake, and the
    honest response is their history, not a complaint about a parameter."""
    assert routes_mod._int_param(_FakeReq({"limit": "abc"}), "limit", default=12) == 12
    assert routes_mod._int_param(_FakeReq({}), "limit", default=12) == 12
    assert routes_mod._int_param(_FakeReq({"limit": "3"}), "limit", default=12) == 3


class _FakeReq:
    def __init__(self, query):
        self.query = query


# ── the fork, not only the outcome ──────────────────────────────────────────


def test_the_players_action_is_recorded_with_the_month(store):
    """A month re-read without the choice that caused it is the least useful half of
    the memory — and the commit path never learns the action any other way, because
    the narrator is told the intent in prose and does not echo it back.
    """
    run = store.create_run({"turn": 0, "worldId": "w"}, {"worldId": "w", "title": "t"})
    store.mark_pending(run, turn=1, slot="s", action="go down to the marsh")

    pending = store.read_pending(run)
    assert pending is not None
    assert pending["action"] == "go down to the marsh", (
        "the in-flight record is the only place the action exists when the narrator "
        "commits"
    )


def test_the_commit_folds_the_action_into_the_chronicle():
    src = (_BACKEND / "mcp_server.py").read_text(encoding="utf-8")
    start = src.index("def _advance_turn")
    end = src.index("\ndef ", start)  # the whole function, not a fixed window
    commit = src[start:end]
    assert "read_pending" in commit, "the commit never recovers what was asked for"
    assert re.search(r'"action":\s*action', commit), (
        "the chronicle entry does not carry the action"
    )
    # And only for the turn it belongs to: a leftover record from an earlier month
    # must not attribute the wrong choice.
    assert 'int(asked.get("turn") or 0) == turn' in commit


def test_the_ui_shows_the_action_it_is_sent():
    src = module("history.tsx")
    assert "p.action" in src, "the choice that caused a month is never shown"
    assert "history.chose" in src


# ── the shelf, once ─────────────────────────────────────────────────────────


def test_the_shelf_list_is_hidden_where_the_rail_shows_it():
    """The rail lists every life and every world. The same list in the reading column
    is the same information twice, side by side."""
    css = styles()
    wide = re.search(
        rf"@media \(min-width: {BREAKPOINT}px\)\s*\{{(.*?)\n\}}", css, re.S
    )
    assert wide, "no rule block at the rail's breakpoint"
    assert re.search(r"\.ew-shelflist\s*\{[^}]*display:\s*none", wide.group(1)), (
        "the shelf list is still rendered beside the rail that already lists it"
    )

    bare = re.search(r"^\.ew-shelflist\s*\{([^}]*)\}", css, re.MULTILINE)
    if bare:
        assert "display: none" not in bare.group(1), (
            "hiding it by default would leave a phone with no shelf at all — the "
            "rail does not render there"
        )


def test_the_landing_appears_only_where_the_rail_does():
    """Below the rail's width the shelf list IS the page, so a "carry on" card would
    be a second copy of its first row."""
    css = styles()
    bare = re.search(r"^\.ew-onlywide\s*\{([^}]*)\}", css, re.MULTILINE)
    assert bare and "display: none" in bare.group(1)
    wide = re.search(
        rf"@media \(min-width: {BREAKPOINT}px\)\s*\{{[^@]*?\.ew-onlywide\s*\{{"
        r"[^}]*display:\s*block",
        css,
        re.S,
    )
    assert wide, "the landing never appears at any width"


def test_the_desktop_landing_offers_something_the_rail_cannot():
    """A rail of names cannot carry "continue this one" or a notice that a world
    failed to load. If the landing only repeated names it would not be worth the
    space it takes."""
    src = module("main.tsx")
    assert "shelf.continue" in src, "the landing offers no way to carry on"
    assert re.search(r"\.find\(", src), (
        "the landing does not identify which life to continue"
    )
    assert "!r.ended" in src, "a finished life must not be offered as the one to resume"


def test_both_languages_carry_the_new_text():
    import json

    root = WEB_SRC / "strings"
    zh = json.loads((root / "zh.json").read_text(encoding="utf-8"))
    en = json.loads((root / "en.json").read_text(encoding="utf-8"))
    for key in (
        "shelf.continue", "shelf.pick", "history.open", "history.close",
        "history.earlier", "history.beginning", "history.none", "history.chose",
    ):
        assert key in zh, f"missing from zh.json: {key}"
        assert key in en, f"missing from en.json: {key}"
