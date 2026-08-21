"""Backdrop validator, store, and the two MCP tools.

The load-bearing property: the narrator's drawing is an inert SVG image — it runs
no script and fetches nothing external, so it needs no sandbox. These pin the
denylist (script / handlers / foreignObject / external refs / non-SVG) and that a
rejected background never becomes the stored one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from backdrop import BackdropError, BackdropStore, compile_backdrop  # noqa: E402

OK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">'
    '<defs><radialGradient id="g"><stop offset="0" stop-color="#2a1e4a"/>'
    '<stop offset="1" stop-color="#0c0a1e"/></radialGradient>'
    '<pattern id="p" width="60" height="72" patternUnits="userSpaceOnUse">'
    '<path d="M0 72 V40 A30 30 0 0 1 60 40 V72" stroke="#d9b45a" fill="none"/></pattern></defs>'
    '<rect width="800" height="600" fill="url(#g)"/>'
    '<rect width="800" height="600" fill="url(#p)" opacity="0.14"/></svg>'
)


# -- the validator is the trust surface ----------------------------------


def test_compile_accepts_a_self_contained_svg():
    out = compile_backdrop(OK_SVG)
    assert out.startswith("<svg") and "<pattern" in out and "radialGradient" in out


def test_compile_injects_the_namespace_when_missing():
    out = compile_backdrop('<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
    assert 'xmlns="http://www.w3.org/2000/svg"' in out


@pytest.mark.parametrize(
    "bad",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect onload="x()"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:x()"><rect/></a></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div>x</div></foreignObject></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://x/y.png"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><use xlink:href="//evil/x"/></svg>',
        '<div style="background:#111"></div>',  # not an SVG at all
    ],
)
def test_compile_refuses_script_handlers_foreignobject_external_and_non_svg(bad):
    with pytest.raises(BackdropError):
        compile_backdrop(bad)


def test_compile_refuses_the_empty_and_the_oversized():
    with pytest.raises(BackdropError):
        compile_backdrop("   ")
    with pytest.raises(BackdropError):
        compile_backdrop('<svg xmlns="http://www.w3.org/2000/svg"><!--' + "x" * 25_000 + "--></svg>")


def test_ordinary_attributes_are_not_mistaken_for_handlers():
    out = compile_backdrop('<svg xmlns="http://www.w3.org/2000/svg"><rect class="on-stage"/></svg>')
    assert "on-stage" in out


# -- the store: one background per run, replace, clear -------------------


def _svg(color: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect fill="{color}" width="10" height="10"/></svg>'


def test_store_set_current_replace_and_clear(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    assert store.current() is None
    assert store.set(_svg("#111")) == 1
    cur = store.current()
    assert cur["version"] == 1 and "#111" in cur["markup"]
    assert store.set(_svg("#222")) == 2
    assert "#222" in store.current()["markup"]
    store.clear()
    assert store.current() is None
    store.clear()  # idempotent


def test_store_rejects_bad_markup_at_set_time_and_stores_nothing(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    with pytest.raises(BackdropError):
        store.set('<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>')
    assert store.current() is None


def test_store_treats_a_corrupt_file_as_no_background(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    store.set(_svg("#111"))
    (tmp_path / "runs" / "run-abc" / "backdrop.json").write_text("{bad", encoding="utf-8")
    assert store.current() is None


# -- the two MCP tools ----------------------------------------------------


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "_DATA", tmp_path / "data")
    return tmp_path / "data"


def _call(name, **args):
    return json.loads(srv.call_tool(name, args))


def test_commit_backdrop_tool_stores_and_versions(data):
    out = _call("endless_commit_backdrop", runId="run-x", turn=1, markup=_svg("#111"))
    assert out["ok"] is True and out["version"] == 1
    assert _call("endless_commit_backdrop", runId="run-x", turn=2,
                 markup=_svg("#222"))["version"] == 2
    assert BackdropStore(data, "run-x").current()["version"] == 2


def test_commit_backdrop_tool_refuses_non_svg(data):
    out = _call("endless_commit_backdrop", runId="run-x", turn=1, markup="<div>x</div>")
    assert out["ok"] is False and "error" in out
    assert BackdropStore(data, "run-x").current() is None


def test_clear_backdrop_tool(data):
    _call("endless_commit_backdrop", runId="run-x", turn=0, markup=_svg("#111"))
    assert _call("endless_clear_backdrop", runId="run-x")["ok"] is True
    assert BackdropStore(data, "run-x").current() is None


def test_store_keeps_a_common_buttons_motif_with_the_backdrop(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    store.set(_svg("#111"), buttons=_svg("#abc"))
    cur = store.current()
    assert cur["buttons"] and "#abc" in cur["buttons"]
    # replacing the backdrop without buttons drops the old motif (they travel together)
    store.set(_svg("#222"))
    assert store.current()["buttons"] is None


def test_store_rejects_bad_buttons_motif(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    with pytest.raises(BackdropError):
        store.set(_svg("#111"), buttons="<div>x</div>")
    assert store.current() is None


def test_store_keeps_a_mobile_variant_with_the_desktop_backdrop(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    version = store.set(_svg("#111"), turn=3, mobile=_svg("#abc"))
    cur = store.current()
    assert cur["version"] == version
    assert "#111" in cur["markup"] and "#abc" in cur["mobile"]
    # Variants travel together: replacing without mobile drops the old portrait.
    store.set(_svg("#222"), turn=3)
    assert store.current()["mobile"] is None


def test_store_rejects_bad_mobile_atomically(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    with pytest.raises(BackdropError):
        store.set(_svg("#111"), mobile="<div>x</div>")
    assert store.current() is None, "desktop must not persist when mobile is invalid"


def test_commit_backdrop_tool_stores_both_variants_in_one_version(data):
    out = _call(
        "endless_commit_backdrop", runId="run-x", turn=1,
        markup=_svg("#111"), mobile=_svg("#abc"),
    )
    cur = BackdropStore(data, "run-x").current()
    assert out["ok"] is True and cur["version"] == out["version"]
    assert "#111" in cur["markup"] and "#abc" in cur["mobile"]

    refused = _call(
        "endless_commit_backdrop", runId="run-y", turn=1,
        markup=_svg("#222"), mobile="<div>x</div>",
    )
    assert refused["ok"] is False
    assert BackdropStore(data, "run-y").current() is None


# -- well-formedness: a malformed SVG renders as a broken image, so refuse it ---


def test_an_xlink_attr_without_its_namespace_is_repaired_not_broken():
    """The reported bug: a narrator put `<animate xlink:href="">` on an SVG that
    declared only `xmlns=`. The undeclared `xlink:` prefix made it malformed XML,
    so the <img> showed a broken-image glyph. The namespace is now injected."""
    art = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="38" y="28" width="24" height="44"/>'
        '<animate xlink:href="" attributeName="opacity" values="0.8;1;0.8" '
        'dur="3.5s" repeatCount="indefinite"/></svg>'
    )
    out = compile_backdrop(art)
    assert "xmlns:xlink" in out
    import xml.etree.ElementTree as ET
    ET.fromstring(out)  # well-formed now — would raise before the fix


def test_a_malformed_svg_is_refused_so_it_never_ships_as_a_broken_image():
    with pytest.raises(BackdropError):
        compile_backdrop('<svg xmlns="http://www.w3.org/2000/svg"><rect x="1"></svg>')


def test_backdrop_is_bound_to_the_turn_and_restores_per_page(tmp_path):
    """Each backdrop is stamped with the page it was set on; re-reading a page
    restores the scene effective then, home/current shows the latest, and clearing
    keeps earlier pages' scenes."""
    (tmp_path / "runs" / "r").mkdir(parents=True)
    b = BackdropStore(tmp_path, "r")
    b.set(OK_SVG, turn=1)
    v2 = b.set(OK_SVG, turn=5)
    assert b.current()["version"] == v2      # latest (home / live page)
    assert b.at(3)["version"] == 1           # persists from turn 1 until 5
    assert b.at(5)["version"] == v2
    assert b.at(0) is None                   # a page before any backdrop
    assert b.version_at(2) == 1 and b.version_at(0) == 0
    b.clear(turn=7)
    assert b.current() is None               # cleared from now on
    assert b.at(6)["version"] == v2          # an earlier page keeps its scene
    assert b.at(8) is None                   # after the clear


def test_a_second_backdrop_on_the_same_turn_replaces_that_pages_entry(tmp_path):
    (tmp_path / "runs" / "r").mkdir(parents=True)
    b = BackdropStore(tmp_path, "r")
    b.set(OK_SVG, turn=3)
    b.set(OK_SVG, turn=3)
    # Two sets on turn 3 leave ONE entry for that page, not two.
    assert len(b._load()) == 1


def test_exact_requires_art_committed_for_that_page(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    store.set(_svg("#111"), turn=1)
    assert store.at(2) is not None, "the previous art remains effective"
    assert store.exact(2) is None, "inherited art cannot publish a newly briefed page"
    store.set(_svg("#222"), turn=2)
    assert "#222" in store.exact(2)["markup"]


def test_successful_illustrator_commit_clears_the_waiting_request(data):
    from kiro_crew.apps.app_storage import AppStorage
    from store import RunStore

    run_id = "a" * 32
    runs = RunStore(AppStorage("endless-worlds", data), data)
    runs.request_backdrop(run_id, turn=1, brief="a closed red gate")
    out = _call("endless_commit_backdrop", runId=run_id, turn=1, markup=_svg("#111"))
    assert out["ok"] is True
    assert runs.read_backdrop_request(run_id) is None


def test_narrator_fallback_commit_is_refused_until_recovery_opens_its_gate(data):
    from kiro_crew.apps.app_storage import AppStorage
    from store import RunStore

    run_id = "b" * 32
    runs = RunStore(AppStorage("endless-worlds", data), data)
    runs.request_backdrop(run_id, turn=1, brief="a closed red gate")

    refused = _call(
        "endless_commit_fallback_backdrop", runId=run_id, turn=1, markup=_svg("#111")
    )
    assert refused["ok"] is False
    assert BackdropStore(data, run_id).exact(1) is None

    runs.update_backdrop_request(run_id, fallbackAllowed=True)
    accepted = _call(
        "endless_commit_fallback_backdrop", runId=run_id, turn=1,
        markup=_svg("#222"), mobile=_svg("#abc"),
    )
    assert accepted["ok"] is True
    committed = BackdropStore(data, run_id).exact(1)
    assert "#222" in committed["markup"] and "#abc" in committed["mobile"]
    assert runs.read_backdrop_request(run_id) is None
