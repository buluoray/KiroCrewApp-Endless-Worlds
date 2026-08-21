"""The SCENE lane's photo-trace pipeline: underlay fragments, composition, store.

Network is always faked through phototrace._FETCH; CI never touches Commons.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
import phototrace  # noqa: E402
from backdrop import BackdropError, BackdropStore, compile_backdrop  # noqa: E402
from phototrace import (  # noqa: E402
    TraceStore,
    build_underlay_fragment,
    compose_with_underlay,
    procedural_base_fragment,
    search_reference,
)


def _photo_bytes(bright: bool) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 240), (200, 200, 200) if bright else (8, 8, 10))
    d = ImageDraw.Draw(img)
    # A tower-ish rectangle plus a ground band, so the trace has real regions.
    d.rectangle([140, 40, 180, 200], fill=(90, 80, 40) if bright else (60, 52, 26))
    d.rectangle([0, 200, 320, 240], fill=(140, 120, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _wrap(fragment: str, w: int = 800, h: int = 600) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
        f'<rect width="{w}" height="{h}" fill="#0b0e17"/>{fragment}</svg>'
    )


def test_underlay_fragment_is_a_compilable_group_without_the_canvas_blob():
    fragment = build_underlay_fragment(_photo_bytes(bright=True), view=(800, 600))
    assert fragment.startswith('<g opacity="0.50">') and "<svg" not in fragment
    assert fragment.count("<path ") >= 1
    compile_backdrop(_wrap(fragment))  # composes into a valid, safe backdrop


def test_dark_photos_get_the_adaptive_exposure_lift():
    """A night photo must not band into all-darkest and trace to nothing."""
    fragment = build_underlay_fragment(_photo_bytes(bright=False), view=(450, 900))
    # Without the gamma lift the dark synthetic photo collapses into the
    # background blob alone and build_underlay_fragment raises 'nothing usable'.
    assert fragment.count("<path ") >= 1


def test_procedural_base_is_valid_for_both_views_and_custom_ramps():
    for view in ((800, 600), (450, 900)):
        base = procedural_base_fragment(view=view, ramp=["#101018", "#20242e", "#6a5424"])
        compile_backdrop(_wrap(base, *view))
    with pytest.raises(BackdropError):
        procedural_base_fragment(view=(800, 600), ramp=["#nothex1"])


def test_compose_replaces_placeholder_and_fails_loud_without_a_fragment():
    svg = '<svg xmlns="x"><rect/><g id="etr-underlay"/><path d="M0 0h1"/></svg>'
    out = compose_with_underlay(svg, '<g opacity="0.50"><path d="M1 1h2"/></g>')
    assert 'id="etr-underlay"' not in out and 'M1 1h2' in out
    assert compose_with_underlay("<svg><rect/></svg>", None) == "<svg><rect/></svg>"
    with pytest.raises(BackdropError):
        compose_with_underlay(svg, None)


def test_trace_store_binds_fragments_to_the_turn(tmp_path):
    store = TraceStore(tmp_path, "run-abc")
    store.save(turn=4, desktop="<g/>", mobile="<g/>", source=None)
    assert store.load(4)["desktop"] == "<g/>"
    assert store.load(5) is None, "a stale trace must never reach another page"
    store.clear()
    assert store.load(4) is None


def test_search_reference_keeps_only_free_licensed_bitmaps(monkeypatch):
    payload = {"query": {"pages": {
        "1": {"title": "File:Free.jpg", "imageinfo": [{
            "mime": "image/jpeg", "thumburl": "https://x/free.jpg",
            "descriptionurl": "https://commons/x",
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}},
        }]},
        "2": {"title": "File:Owned.jpg", "imageinfo": [{
            "mime": "image/jpeg", "thumburl": "https://x/owned.jpg",
            "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}},
        }]},
    }}}
    monkeypatch.setattr(
        phototrace, "_FETCH", lambda url: json.dumps(payload).encode("utf-8")
    )
    rows = search_reference("castle")
    assert [r["title"] for r in rows] == ["File:Free.jpg"]
    # A free-licensed djvu book scan is still not a photograph: a night-street
    # query once traced a 1918 novel's cover lettering into the underlay.
    payload["query"]["pages"]["3"] = {"title": "File:Scan.djvu", "imageinfo": [{
        "mime": "image/vnd.djvu", "thumburl": "https://x/scan.jpg",
        "extmetadata": {"LicenseShortName": {"value": "Public domain"}},
    }]}
    assert [r["title"] for r in search_reference("castle")] == ["File:Free.jpg"]
    assert rows[0]["license"] == "CC BY-SA 4.0"


# -- the MCP tool + composition through draft/commit ------------------------


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "_DATA", tmp_path)
    return tmp_path


def _call(name, **args):
    return json.loads(srv.call_tool(name, args))


def _request_backdrop(data: Path, run_id: str, turn: int):
    from kiro_crew.apps.app_storage import AppStorage
    from store import RunStore

    RunStore(AppStorage("endless-worlds", data), data).request_backdrop(
        run_id, turn=turn, brief="a scene"
    )


def test_trace_tool_stores_reference_underlay_and_commit_composes_it(data, monkeypatch):
    photo = _photo_bytes(bright=True)

    def fake_fetch(url: str) -> bytes:
        if "api.php" in url:
            return json.dumps({"query": {"pages": {"1": {
                "title": "File:Bridge.jpg",
                "imageinfo": [{
                    "mime": "image/jpeg", "thumburl": "https://x/b.jpg",
                    "descriptionurl": "https://commons/b",
                    "extmetadata": {"LicenseShortName": {"value": "CC0"}},
                }],
            }}}}).encode("utf-8")
        return photo

    monkeypatch.setattr(phototrace, "_FETCH", fake_fetch)
    run_id = "a" * 32
    _request_backdrop(data, run_id, 1)

    out = _call("endless_trace_reference", runId=run_id, turn=1, query="stone bridge")
    assert out["ok"] is True and out["underlay"] == "reference"
    assert out["source"]["title"] == "File:Bridge.jpg"
    for path in out["previews"].values():
        assert Path(path).is_file(), "previews must be readable before drawing"

    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
        '<rect width="{w}" height="{h}" fill="#0b0e17"/><g id="etr-underlay"/>'
        '<path d="M10 10 h40" stroke="#c9a227" fill="none"/></svg>'
    )
    draft = _call(
        "endless_submit_backdrop_draft", runId=run_id, turn=1,
        markup=overlay.format(w=800, h=600), mobile=overlay.format(w=450, h=900),
    )
    assert draft["ok"] is True
    final = _call(
        "endless_commit_backdrop", runId=run_id, turn=1, draftId=draft["draftId"],
        markup=overlay.format(w=800, h=600), mobile=overlay.format(w=450, h=900),
    )
    assert final["ok"] is True
    committed = BackdropStore(data, run_id).current()
    assert 'id="etr-underlay"' not in committed["markup"]
    assert committed["markup"].count("<path ") > 1, "underlay paths were spliced in"
    assert 'id="etr-underlay"' not in committed["mobile"]
    assert TraceStore(data, run_id).load(1) is None, "trace cleared after publication"


def test_trace_tool_passes_a_custom_ramp_through_to_the_base(data, monkeypatch):
    """A world/mood palette reaches the fragment; color is not welded to nocturne."""
    monkeypatch.setattr(
        phototrace, "_FETCH", lambda url: json.dumps({"query": {"pages": {}}}).encode()
    )
    run_id = "e" * 32
    _request_backdrop(data, run_id, 4)
    out = _call(
        "endless_trace_reference", runId=run_id, turn=4,
        query="nothing findable", ramp=["#0a0d14", "#182030", "#2c3c55", "#9db4d4"],
    )
    assert out["ok"] is True and out["underlay"] == "base"
    stored = TraceStore(data, run_id).load(4)
    assert "rgb(157,180,212)" in stored["desktop"], "warm stop must come from the ramp"
    assert "201,162,39" not in stored["desktop"], "nocturne gold must not leak in"


def test_trace_tool_falls_back_to_a_procedural_base_when_search_is_empty(data, monkeypatch):
    monkeypatch.setattr(
        phototrace, "_FETCH", lambda url: json.dumps({"query": {"pages": {}}}).encode()
    )
    run_id = "b" * 32
    _request_backdrop(data, run_id, 2)
    out = _call("endless_trace_reference", runId=run_id, turn=2, query="zombie at the door")
    assert out["ok"] is True and out["underlay"] == "base" and out["source"] is None


def test_a_placeholder_without_a_stored_trace_is_refused_at_draft_time(data):
    run_id = "c" * 32
    _request_backdrop(data, run_id, 3)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">'
        '<g id="etr-underlay"/></svg>'
    )
    out = _call(
        "endless_submit_backdrop_draft", runId=run_id, turn=3, markup=svg, mobile=svg,
    )
    assert out["ok"] is False and "endless_trace_reference" in out["error"]
