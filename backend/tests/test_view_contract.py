"""Cross-file contract: every field the UI reads is a field the backend sends.

This file exists because of a real failure, not a hypothetical one. Renaming
``openingLabels`` to ``opening`` in the world-detail body left the UI reading a
key that no longer arrived, and the dashboard renders an app that throws as a
single error card — so one stale field name blanked the entire page with
``Cannot read properties of undefined (reading 'map')``.

Nothing tied the two sides together. These tests do: they read the UI source and
the real response bodies, and fail when a key drifts on either side.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from view import build_play_view, world_detail  # noqa: E402
from world import read_world  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uisrc  # noqa: E402

FLAGSHIP = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"


@pytest.fixture(scope="module")
def ui_src() -> str:
    """The TypeScript SOURCE, not the built bundle — see ``uisrc``."""
    if not uisrc.WEB_SRC.is_dir():
        pytest.skip("web/src not present")
    return uisrc.source() + "\n" + uisrc.styles()


@pytest.fixture(scope="module")
def pack():
    if not FLAGSHIP.is_file():
        pytest.skip("flagship seed not present")
    return read_world(FLAGSHIP.read_text(encoding="utf-8"))


def _reads(src: str, obj: str) -> set[str]:
    """Field names the UI reads off ``obj``, e.g. ``world.title`` → ``title``.

    Also catches the guarded form ``(world.panels ?? [])`` — a guard stops the crash
    but does NOT make a wrong name correct, so a guarded read of a key that no
    longer exists must still fail this test.

    **And the optional-chained form** ``v?.generating``. That was a hole, not a
    subtlety: ``play.tsx`` reads most of its fields through ``v?.`` because the view
    is null until the first fetch lands, so the pattern that only matched ``v.``
    silently checked a fraction of the reads it claimed to. It was found by adding a
    field the route sends, watching the life-list test fail, and noticing the play
    test — which reads the same new field — had stayed green.

    Occurrences preceded by a quote or by another word character are skipped. The
    quote rule keeps the string table's own namespaced keys (``t('world.back')``)
    from reading as properties. The word rule matters for a short object name: with
    only the quote rule, ``t('opening.sealed')`` matched a read of ``g.sealed``,
    because "openin|g." ends in one.
    """
    return set(
        re.findall(
            rf"(?<![\w'\"]){re.escape(obj)}\??\.([a-zA-Z][a-zA-Z0-9]*)", src
        )
    )


#: Keys the UI computes locally rather than receiving from the backend.
_LOCAL = {"length", "map", "find", "filter", "slice", "some", "trim", "id"}


def test_the_world_bodies_carry_every_field_the_ui_reads(ui_src, pack, tmp_path):
    """Both the library row and the detail body are read through a prop named
    ``world``, so the contract is against their UNION — a key the UI reads must
    come from one of them."""
    from library import WorldLibrary

    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "w.md").write_text(
        FLAGSHIP.read_text(encoding="utf-8"), encoding="utf-8"
    )
    lib = WorldLibrary(tmp_path / "data", tmp_path / "seeds")
    lib.ensure_seeds_installed()
    row = lib.list_worlds()[0]

    # An unusable row carries the keys a broken world reports instead.
    unusable = {"usable", "problem", "needsCore", "localCore", "field"}
    # The detail page asks for the world's prose (?prose=1), so the body it reads
    # against is the include_prose shape.
    sent = set(world_detail(pack, include_prose=True)) | set(row) | unusable

    read = (_reads(uisrc.module("library.tsx"), "world")
            | _reads(uisrc.module("opening.tsx"), "world")) - _LOCAL
    missing = sorted(read - sent)
    assert not missing, f"the UI reads fields the backend does not send: {missing}"


def test_the_play_view_carries_every_field_the_ui_reads(ui_src, pack):
    view = build_play_view(
        pack.template,
        {"turn": 1, "style": "classic"},
        chronicle=[{"turn": 1, "prose": "p"}],
        scenes=[],
    )
    # Overlaid by the route, exactly as get_run does.
    view.update({
        "runId": "r", "worldId": "w", "title": "t", "awaitingOpening": False,
        "language": "en", "generating": None, "backdrop": None,
    })
    read = _reads(uisrc.module("play.tsx"), "v") - _LOCAL
    missing = sorted(read - set(view))
    assert not missing, f"the play page reads fields the view does not send: {missing}"


def test_the_life_list_carries_every_field_the_ui_reads(ui_src):
    """The shelf's "lives in progress" rows. ``turn`` / ``awaitingOpening`` /
    ``ended`` are overlaid from each life's own state by the route, not taken
    from the index — so they must be in the row the UI reads."""
    row = {
        "runId": "r", "worldId": "w", "title": "t", "style": "classic",
        "turn": 0, "lastPlayed": 0.0,
        "awaitingOpening": True, "ended": False, "unreadable": False,
        # Set for every row by list_runs, so a life mid-generation is not shown as
        # one that stalled.
        "generating": False,
        # What tells two lives in one world apart.
        "subtitle": "",
        # Player-set metadata, carried on the index row and spread by list_runs.
        "label": "",
        "archived": False,
        # The life's narrator backdrop version, set per row by list_runs so the
        # shelf card can show the same background the play page does.
        "backdrop": None,
    }
    # Both readers of a life row, not just the shelf. The rail was added later and
    # reads the same shape; checking only one of them would let the other drift,
    # which is the failure this whole file exists to prevent.
    for where in ("library.tsx", "rail.tsx"):
        read = _reads(uisrc.module(where), "run") - _LOCAL
        missing = sorted(read - set(row))
        assert not missing, f"{where} reads fields the route does not send: {missing}"


def test_a_rumour_is_visibly_a_rumour(ui_src):
    """An unreliable report that reads exactly like a reliable one makes the reach
    gating invisible, which is the same as not having it."""
    assert "dg.rumour" in ui_src
    assert "play.rumourSuffix" in ui_src, "the rumour marker is not rendered"


def test_the_digest_row_shape_matches_what_the_ui_reads(ui_src):
    from halo import gate_digest

    row = gate_digest(["国家"], {"digest": {"国家": "t"}})[0]
    # `dg`, not `d`: `d` names fetch payloads elsewhere in the file, so it
    # cannot say which reads belong to a digest row.
    read = _reads(uisrc.module("play.tsx"), "dg") - _LOCAL
    missing = sorted(read - set(row))
    assert not missing, f"the digest reads fields the gate does not send: {missing}"


def test_leaving_the_page_cannot_lose_a_life(ui_src):
    """The two halves of the fix, asserted separately because either alone is a
    worse product: the shelf LISTS lives in progress (so a life is findable even
    when the app forgot the screen), and the app REMEMBERS the play page (so
    coming back does not cost a tap).

    An interrupted OPENING screen is deliberately not restored — its answers live
    in React state, and showing an empty form claiming to be where you left off
    would be a lie. It lands on the shelf, where its life is listed.
    """
    assert "api.runs()" in ui_src, "the shelf never asks for the lives in progress"
    assert "LifeRow" in ui_src
    assert "localStorage" in ui_src
    assert "where.view === 'live'" in ui_src, "the play page is not restored"


def test_the_opening_group_shape_matches_what_the_ui_expects(ui_src, pack):
    group = world_detail(pack)["opening"][0]
    read = _reads(uisrc.module("opening.tsx"), "g") - _LOCAL - {"options"}
    missing = sorted(read - set(group))
    assert not missing, f"the UI reads group fields that are not sent: {missing}"
    # options is read as `g.options.length` / `g.options[...]`, so it must be a list
    assert isinstance(group["options"], list)


def test_the_stale_field_that_caused_the_outage_is_gone(ui_src, pack):
    """A named regression: the exact key whose rename blanked the app."""
    assert "openingLabels" not in ui_src
    assert "openingLabels" not in world_detail(pack)


def test_the_narrators_markdown_is_rendered_as_markdown(ui_src):
    """The narrator writes markdown; rendering it as plain text showed the player
    raw ``**`` and ``#``.

    Asserted on the HOST's renderer specifically. A hand-rolled markdown-to-HTML
    path would be a new, unaudited route from model bytes to the DOM — the
    dashboard already renders model markdown in chat through this component, so
    it is the audited one.
    """
    assert "MarkdownRenderer" in ui_src
    assert "__kirocrew_modules" in ui_src, "must feature-detect, not static-import"
    assert "'@kirocrew/ui'" in ui_src
    # A static import of a key an older host's map lacks fails the WHOLE module,
    # so the app would not load at all rather than losing one nicety. Matched as
    # a real import STATEMENT: an earlier version of this assertion searched for
    # the bare substring and tripped over the comment explaining the rule.
    import re as _re

    assert not _re.search(r"(?m)^\s*import\b[^\n]*'@kirocrew/ui'", ui_src)
    assert "__kirocrew_modules" in ui_src


def test_there_is_a_readable_fallback_when_the_host_has_no_renderer(ui_src):
    """Worse than markdown, never worse than unreadable."""
    assert "ew-prose-plain" in ui_src


def test_pre_wrap_is_not_applied_to_rendered_markdown(ui_src):
    """With real paragraphs, ``white-space: pre-wrap`` doubles every blank line."""
    import re as _re

    block = _re.search(r"\.ew-prose \{[^}]*\}", uisrc.styles())
    assert block and "pre-wrap" not in block.group(0)
    """A primitive the view shapes but the UI has no case for renders as nothing,
    with no error — the quiet half of the same class of drift."""
    from template import FIELD_PRIMITIVES

    for primitive in sorted(FIELD_PRIMITIVES):
        assert f"'{primitive}'" in ui_src, f"the UI has no case for {primitive!r}"


def test_every_primitive_the_backend_can_emit_has_a_branch_in_the_ui(ui_src):
    """A primitive the view shapes but the UI has no case for renders as nothing,
    with no error — the quiet half of the same class of drift."""
    from template import FIELD_PRIMITIVES

    for primitive in sorted(FIELD_PRIMITIVES):
        assert f"'{primitive}'" in ui_src, f"the UI has no case for {primitive!r}"


def test_a_missing_array_degrades_instead_of_taking_the_page_down(ui_src):
    """R15.9 — the dashboard renders a throwing app as one error card, so an
    unguarded ``.map`` on an absent field costs the player everything on screen,
    not just that section."""
    unguarded = [
        line.strip()
        for line in ui_src.splitlines()
        if re.search(r"(?<!\?\? \[\])\b(?:world|v|panel|f)\.[a-zA-Z]+\.map\(", line)
    ]
    assert not unguarded, f"unguarded .map on a server-sent field: {unguarded}"


def test_the_flagships_locked_panels_tell_the_narrator_their_key(pack):
    """The live bug, on the real world that produced it.

    Measured from the user's own run: the narrator had declared a full ``magic``
    block and a full ``relations`` block, and both were invisible in the app. The
    compiled header gates them on ``state.magic.awakened == true`` and
    ``state.relations.known == true`` — flags the declaration shape never mentioned,
    so the app was reading fields it had never asked anyone to write. The data was
    there and the door was locked from a side nobody had been shown.

    Asserted against the flagship rather than a fixture because the mismatch is
    between two real artefacts: a world's own ``when`` expressions and the prompt
    this app builds from them.
    """
    from turn import declaration_shape

    shape = declaration_shape(pack.template)
    gated = [p for p in pack.template.panels if p.when is not None]
    assert gated, "the flagship has no conditional panels; this test proves nothing"

    for panel in gated:
        assert panel.when.source in shape, (
            f"panel {panel.id!r} only appears while {panel.when.source!r}, and the "
            "narrator is never told — so it can fill the panel and still leave it "
            "invisible"
        )
