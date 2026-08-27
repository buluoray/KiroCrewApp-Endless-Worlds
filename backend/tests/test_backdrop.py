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
from backdrop import (  # noqa: E402
    BackdropDraftStore,
    BackdropError,
    BackdropStore,
    compile_backdrop,
)

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
    local_use = compile_backdrop(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<defs><path id="shape" d="M0 0h1v1z"/></defs><use href="#shape"/></svg>'
    )
    assert 'href="#shape"' in local_use


def test_compile_injects_the_namespace_when_missing():
    out = compile_backdrop('<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
    assert 'xmlns="http://www.w3.org/2000/svg"' in out


def test_compile_accepts_inline_css_animation():
    # Inline CSS animation runs in an <img>-embedded SVG (only SCRIPTS are inert
    # there), so a self-contained <style> @keyframes or a style= transition is
    # allowed. The gate blocks only @import and external url(), covered by the
    # reject tests below.
    styled = compile_backdrop(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<style>@keyframes pulse{from{opacity:.2}to{opacity:1}}"
        ".spark{animation:pulse 3s ease-in-out infinite alternate}</style>"
        '<rect class="spark" width="10" height="10" fill="#d9b45a"/></svg>'
    )
    assert "@keyframes" in styled and "animation:pulse" in styled
    inline = compile_backdrop(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect width="10" height="10" style="transition:opacity 2s"/></svg>'
    )
    assert "transition:opacity" in inline


@pytest.mark.parametrize(
    "bad",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect onload="x()"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:x()"><rect/></a></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div>x</div></foreignObject></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://x/y.png"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="../secret.png"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,eA=="/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://x/y)"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://x/y"</style></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><use xlink:href="//evil/x"/></svg>',
        '<div style="background:#111"></div>',  # not an SVG at all
    ],
)
def test_compile_refuses_script_handlers_foreignobject_external_and_non_svg(bad):
    with pytest.raises(BackdropError):
        compile_backdrop(bad)


def test_compile_refuses_the_empty_and_the_oversized():
    from backdrop import MAX_BACKDROP_BYTES

    with pytest.raises(BackdropError):
        compile_backdrop("   ")
    with pytest.raises(BackdropError):
        compile_backdrop(
            '<svg xmlns="http://www.w3.org/2000/svg"><!--'
            + "x" * (MAX_BACKDROP_BYTES + 1_000)
            + "--></svg>"
        )


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


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header.startswith(b"\x89PNG\r\n\x1a\n")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def test_draft_store_renders_private_thumbnails_and_replaces_stale_draft(tmp_path):
    drafts = BackdropDraftStore(tmp_path, "run-abc")
    first = drafts.submit(OK_SVG, OK_SVG, turn=3, buttons=_svg("#abc"))

    assert BackdropStore(tmp_path, "run-abc").exact(3) is None
    assert _png_dimensions(Path(first["previews"]["desktop"])) == (400, 300)
    assert _png_dimensions(Path(first["previews"]["mobile"])) == (150, 300)
    assert _png_dimensions(Path(first["previews"]["buttons"])) == (240, 80)

    second = drafts.submit(_svg("#222"), _svg("#333"), turn=3)
    assert second["draftId"] != first["draftId"]
    assert not any(Path(path).exists() for path in first["previews"].values())
    drafts.require(second["draftId"], 3)
    with pytest.raises(BackdropError):
        drafts.require(first["draftId"], 3)


def test_invalid_draft_is_rejected_before_any_preview_or_publication(tmp_path):
    drafts = BackdropDraftStore(tmp_path, "run-abc")
    with pytest.raises(BackdropError):
        drafts.submit(OK_SVG, '<svg><image href="file:///etc/passwd"/></svg>', turn=3)
    run_dir = tmp_path / "runs" / "run-abc"
    assert not (run_dir / "backdrop-draft.json").exists()
    assert BackdropStore(tmp_path, "run-abc").current() is None


def test_a_wedged_render_child_times_out_instead_of_hanging(tmp_path, monkeypatch):
    """A pathological SVG can spin cairo indefinitely; the render child must be
    killed at RENDER_TIMEOUT_SECS rather than wedging the MCP server process."""
    import backdrop as backdrop_mod

    wedge = tmp_path / "wedge.sh"
    wedge.write_text("#!/bin/sh\nsleep 60\n", encoding="utf-8")
    wedge.chmod(0o755)
    monkeypatch.setattr(backdrop_mod.sys, "executable", str(wedge))
    monkeypatch.setattr(backdrop_mod, "RENDER_TIMEOUT_SECS", 1)

    with pytest.raises(BackdropError) as err:
        backdrop_mod._render_svg_thumbnail(OK_SVG, tmp_path / "out.png", 40, 30)
    assert "timed out" in str(err.value)
    assert not (tmp_path / "out.png").exists()


# -- the draft/final MCP tools -------------------------------------------


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "_DATA", tmp_path / "data")
    return tmp_path / "data"


def _call(name, **args):
    return json.loads(srv.call_tool(name, args))


def _submit_draft(data: Path, run_id: str, turn: int, markup: str, mobile: str):
    from kiro_crew.apps.app_storage import AppStorage

    from store import RunStore

    runs = RunStore(AppStorage("endless-worlds", data), data)
    runs.request_backdrop(run_id, turn=turn, brief="test art")
    return _call(
        "endless_submit_backdrop_draft",
        runId=run_id,
        turn=turn,
        markup=markup,
        mobile=mobile,
    )


def test_draft_then_final_backdrop_stores_and_versions(data):
    run_id = "a" * 32
    draft = _submit_draft(data, run_id, 1, _svg("#111"), _svg("#112"))
    assert draft["ok"] is True and draft["backdrop"] == "drafted"
    assert BackdropStore(data, run_id).current() is None, "draft must not publish"

    out = _call(
        "endless_commit_backdrop",
        runId=run_id,
        turn=1,
        draftId=draft["draftId"],
        markup=_svg("#121"),
        mobile=_svg("#122"),
    )
    assert out["ok"] is True and out["version"] == 1
    assert "#121" in BackdropStore(data, run_id).current()["markup"]
    assert not (data / "runs" / run_id / "backdrop-draft.json").exists()
    assert not any(draft_path.exists() for draft_path in map(Path, draft["previews"].values()))

    second = _submit_draft(data, run_id, 2, _svg("#222"), _svg("#223"))
    out2 = _call(
        "endless_commit_backdrop",
        runId=run_id,
        turn=2,
        draftId=second["draftId"],
        markup=_svg("#222"),
        mobile=_svg("#223"),
    )
    assert out2["version"] == 2


def test_submit_backdrop_draft_refuses_non_svg_atomically(data):
    run_id = "b" * 32
    out = _submit_draft(data, run_id, 1, "<div>x</div>", _svg("#111"))
    assert out["ok"] is False and "error" in out
    assert BackdropStore(data, run_id).current() is None
    assert not (data / "runs" / run_id / "backdrop-draft.json").exists()


def test_final_backdrop_is_refused_without_the_matching_reviewed_draft(data):
    run_id = "c" * 32
    out = _call(
        "endless_commit_backdrop",
        runId=run_id,
        turn=1,
        draftId="0" * 24,
        markup=_svg("#111"),
        mobile=_svg("#112"),
    )
    assert out["ok"] is False
    assert "visually review" in out["error"]
    assert BackdropStore(data, run_id).current() is None


def test_clear_backdrop_tool(data):
    run_id = "d" * 32
    BackdropStore(data, run_id).set(_svg("#111"), turn=0)
    assert _call("endless_clear_backdrop", runId=run_id)["ok"] is True
    assert BackdropStore(data, run_id).current() is None


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


def test_store_keeps_sanitized_source_provenance_with_the_backdrop(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    store.set(
        _svg("#111"),
        source={
            "title": "x" * 600,
            "pageUrl": "https://commons.wikimedia.org/wiki/File:Bridge.jpg",
            "license": "CC0",
            "ignored": "not persisted",
        },
        trace={
            "pipeline": "trace",
            "underlay": "reference",
            "fragmentId": "a" * 16,
            "query": "bridge " * 100,
            "used": True,
            "ignored": "not persisted",
        },
    )

    source = store.current()["source"]
    assert source == {
        "title": "x" * 500,
        "pageUrl": "https://commons.wikimedia.org/wiki/File:Bridge.jpg",
        "license": "CC0",
    }
    assert store._load()[-1]["source"] == source
    trace = store.current()["trace"]
    assert trace == {
        "pipeline": "trace",
        "underlay": "reference",
        "fragmentId": "a" * 16,
        "query": ("bridge " * 100)[:500],
        "used": True,
    }
    assert store._load()[-1]["trace"] == trace


def test_store_rejects_bad_mobile_atomically(tmp_path):
    store = BackdropStore(tmp_path, "run-abc")
    with pytest.raises(BackdropError):
        store.set(_svg("#111"), mobile="<div>x</div>")
    assert store.current() is None, "desktop must not persist when mobile is invalid"


def test_commit_backdrop_tool_stores_both_variants_in_one_version(data):
    run_id = "e" * 32
    draft = _submit_draft(data, run_id, 1, _svg("#111"), _svg("#abc"))
    out = _call(
        "endless_commit_backdrop",
        runId=run_id,
        turn=1,
        draftId=draft["draftId"],
        markup=_svg("#111"),
        mobile=_svg("#abc"),
    )
    cur = BackdropStore(data, run_id).current()
    assert out["ok"] is True and cur["version"] == out["version"]
    assert "#111" in cur["markup"] and "#abc" in cur["mobile"]

    refused_run = "f" * 32
    refused_draft = _submit_draft(data, refused_run, 1, _svg("#222"), _svg("#223"))
    refused = _call(
        "endless_commit_backdrop",
        runId=refused_run,
        turn=1,
        draftId=refused_draft["draftId"],
        markup=_svg("#222"),
        mobile="<div>x</div>",
    )
    assert refused["ok"] is False
    assert BackdropStore(data, refused_run).current() is None


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
    assert b.current()["version"] == v2  # latest (home / live page)
    assert b.at(3)["version"] == 1  # persists from turn 1 until 5
    assert b.at(5)["version"] == v2
    assert b.at(0) is None  # a page before any backdrop
    assert b.version_at(2) == 1 and b.version_at(0) == 0
    b.clear(turn=7)
    assert b.current() is None  # cleared from now on
    assert b.at(6)["version"] == v2  # an earlier page keeps its scene
    assert b.at(8) is None  # after the clear


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
    draft = _submit_draft(data, run_id, 1, _svg("#111"), _svg("#112"))
    assert runs.read_backdrop_request(run_id) is not None
    out = _call(
        "endless_commit_backdrop",
        runId=run_id,
        turn=1,
        draftId=draft["draftId"],
        markup=_svg("#111"),
        mobile=_svg("#112"),
    )
    assert out["ok"] is True
    assert runs.read_backdrop_request(run_id) is None


def test_narrator_fallback_commit_is_refused_until_recovery_opens_its_gate(data):
    from kiro_crew.apps.app_storage import AppStorage

    from store import RunStore

    run_id = "b" * 32
    runs = RunStore(AppStorage("endless-worlds", data), data)
    runs.request_backdrop(run_id, turn=1, brief="a closed red gate")

    refused = _call("endless_commit_fallback_backdrop", runId=run_id, turn=1, markup=_svg("#111"))
    assert refused["ok"] is False
    assert BackdropStore(data, run_id).exact(1) is None

    runs.update_backdrop_request(run_id, fallbackAllowed=True)
    accepted = _call(
        "endless_commit_fallback_backdrop",
        runId=run_id,
        turn=1,
        markup=_svg("#222"),
        mobile=_svg("#abc"),
    )
    assert accepted["ok"] is True
    committed = BackdropStore(data, run_id).exact(1)
    assert "#222" in committed["markup"] and "#abc" in committed["mobile"]
    assert runs.read_backdrop_request(run_id) is None


# -- reduced motion (the settings' read-boundary strip) ---------------------


def test_strip_motion_removes_smil_and_css_animation_but_keeps_the_scene():
    from backdrop import strip_motion

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<style>@keyframes drift{from{opacity:.2}to{opacity:1}}"
        ".cloud{animation:drift 4s infinite;fill:#8aa}</style>"
        '<rect width="10" height="10" fill="#123"/>'
        '<circle class="cloud" r="2" style="transition: opacity 1s; opacity:.5">'
        '<animate attributeName="r" values="2;3;2" dur="5s" repeatCount="indefinite"/>'
        "</circle>"
        '<g><animateTransform attributeName="transform" type="rotate" dur="9s"/></g>'
        "</svg>"
    )
    out = strip_motion(svg)
    assert "<animate" not in out and "animateTransform" not in out
    assert "@keyframes" not in out and "animation" not in out and "transition" not in out
    # The scene itself survives: shapes, static styling, structure.
    assert "<rect" in out and "<circle" in out and 'fill="#123"' in out
    assert "opacity:.5" in out  # a static declaration next to a stripped one stays


def test_strip_motion_leaves_a_still_svg_byte_identical():
    from backdrop import strip_motion

    svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4" fill="#345"/></svg>'
    assert strip_motion(svg) == svg


def test_the_store_serves_stored_art_still_once_reduced_motion_is_on(tmp_path):
    from settings import write_settings

    animated = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect width="4" height="4"><animate attributeName="opacity" dur="3s"/></rect></svg>'
    )
    # Stored BEFORE the setting flips: the strip is a read-boundary rule, so art
    # from any era obeys the CURRENT preference, and flipping back restores motion
    # (the stored bytes are untouched).
    BackdropStore(tmp_path, "run-abc").set(animated, turn=1)

    write_settings(tmp_path, model="", reasoning_effort="", reduced_motion=True)
    still = BackdropStore(tmp_path, "run-abc").current()
    assert still and "<animate" not in still["markup"] and "<rect" in still["markup"]

    write_settings(tmp_path, model="", reasoning_effort="", reduced_motion=False)
    moving = BackdropStore(tmp_path, "run-abc").current()
    assert moving and "<animate" in moving["markup"]
