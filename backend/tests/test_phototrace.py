"""The SCENE lane's photo-trace pipeline: underlay fragments, composition, store.

Network is always faked through phototrace._FETCH; CI never touches Commons.
"""
from __future__ import annotations

import io
import json
import subprocess
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
    build_underlay_fragment_bounded,
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
    assert fragment.startswith('<g opacity="0.65">') and "<svg" not in fragment
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


@pytest.mark.parametrize("quote", ['"', "'"])
def test_compose_replaces_both_placeholder_quote_styles(quote):
    svg = (
        f'<svg xmlns="x"><rect/><g id={quote}etr-underlay{quote}/>'
        '<path d="M0 0h1"/></svg>'
    )
    out = compose_with_underlay(
        svg, '<g opacity="0.50"><path d="M1 1h2"/></g>',
        require_placeholder=True,
    )
    assert "etr-underlay" not in out and "M1 1h2" in out


def test_compose_fails_closed_for_missing_duplicate_or_unbacked_placeholders():
    plain = "<svg><rect/></svg>"
    marker = '<g id="etr-underlay"/>'
    assert compose_with_underlay(plain, None) == plain
    with pytest.raises(BackdropError, match="exactly one"):
        compose_with_underlay(plain, "<g/>", require_placeholder=True)
    with pytest.raises(BackdropError, match="exactly one"):
        compose_with_underlay(f"<svg>{marker}{marker}</svg>", "<g/>")
    with pytest.raises(BackdropError, match="endless_trace_reference"):
        compose_with_underlay(f"<svg>{marker}</svg>", None)


def test_trace_store_binds_fragments_and_audit_to_the_turn(tmp_path):
    store = TraceStore(tmp_path, "run-abc")
    store.save(
        turn=4, desktop="<g/>", mobile="<g/>", source=None,
        kind="base", query="unfindable castle",
    )
    stored = store.load(4)
    assert stored["desktop"] == "<g/>"
    assert stored["kind"] == "base" and stored["query"] == "unfindable castle"
    assert store.load(5) is None, "a stale trace must never reach another page"
    store.clear()
    assert store.load(4) is None


def test_search_reference_keeps_only_attribution_free_bitmaps(monkeypatch):
    payload = {"query": {"pages": {
        "1": {"title": "File:BySa.jpg", "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/by-sa.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:BySa.jpg",
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}},
        }]},
        "2": {"title": "File:CC0.jpg", "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/cc0.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:CC0.jpg",
            "extmetadata": {"LicenseShortName": {"value": "CC0"}},
        }]},
        "3": {"title": "File:PublicDomain.png", "imageinfo": [{
            "mime": "image/png",
            "thumburl": "https://upload.wikimedia.org/public-domain.png",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:PublicDomain.png",
            "extmetadata": {"LicenseShortName": {"value": "Public domain"}},
        }]},
        "4": {"title": "File:Owned.jpg", "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/owned.jpg",
            "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}},
        }]},
        # Attribution-free does not make a book scan a photograph.
        "5": {"title": "File:Scan.djvu", "imageinfo": [{
            "mime": "image/vnd.djvu",
            "thumburl": "https://upload.wikimedia.org/scan.jpg",
            "extmetadata": {"LicenseShortName": {"value": "Public domain"}},
        }]},
    }}}
    monkeypatch.setattr(
        phototrace, "_FETCH", lambda url: json.dumps(payload).encode("utf-8")
    )

    rows = search_reference("castle")

    assert [r["title"] for r in rows] == ["File:CC0.jpg", "File:PublicDomain.png"]
    assert [r["license"] for r in rows] == ["CC0", "Public domain"]


def test_the_search_excludes_book_scans_and_samples_wide_enough_to_survive_filtering(
    monkeypatch,
):
    """Both halves were measured against live Commons. Attribution-free material
    there skews to scanned BOOKS: a four-word village query returned ten pages whose
    every public-domain hit was a PDF or DjVu scan and whose every photograph was
    CC BY-SA, so nothing survived and the lane degraded on a query that had matched.
    `filetype:bitmap` removes the scans at the source, and sampling `_RAW_SEARCH_ROWS`
    rather than a small multiple of the wanted count leaves the thin surviving
    intersection something to be drawn from — the same single request either way
    (widening it turned a night-castle query from zero usable rows into ten)."""
    seen: list[str] = []

    def fake(url: str) -> bytes:
        seen.append(url)
        return json.dumps({"query": {"pages": {}}}).encode("utf-8")

    monkeypatch.setattr(phototrace, "_FETCH", fake)
    search_reference("castle tower night")

    assert len(seen) == 1
    assert "filetype%3Abitmap" in seen[0], "book scans must be excluded at the source"
    assert f"gsrlimit={phototrace._RAW_SEARCH_ROWS}" in seen[0]


def test_the_search_ladder_widens_a_specific_brief_and_stops_at_the_first_hit(
    monkeypatch,
):
    """Commons' generator search is CONJUNCTIVE, so a brief written the way the
    illustrator is ASKED to write one matches nothing: measured live, the 18-word
    river-mill brief returns zero search hits while its first two words return
    several. A specific brief therefore failed BECAUSE it was specific, on every
    good-faith attempt. The ladder buys recall in a bounded number of requests and
    stops the moment something matches."""
    brief = (
        "medieval European river-mill village timber granary dirt road low stone "
        "bridge dawn mist farmland distant walled town horizon"
    )
    hit = {"query": {"pages": {"1": {"title": "File:Mill.jpg", "imageinfo": [{
        "mime": "image/jpeg", "thumburl": "https://upload.wikimedia.org/mill.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Mill.jpg",
        "extmetadata": {"LicenseShortName": {"value": "CC0"}},
    }]}}}}
    asked: list[str] = []

    def fake(url: str) -> bytes:
        asked.append(url)
        # Only the narrowest rung matches, exactly as live Commons behaved.
        body = hit if len(asked) == phototrace._MAX_SEARCH_STEPS else {"query": {"pages": {}}}
        return json.dumps(body).encode("utf-8")

    monkeypatch.setattr(phototrace, "_FETCH", fake)
    rows, audit = phototrace.search_reference_ladder(brief)

    assert [r["title"] for r in rows] == ["File:Mill.jpg"]
    assert audit["reason"] == "ok"
    assert audit["matched"] == "medieval European river-mill village", "the rung is named"
    assert len(asked) == phototrace._MAX_SEARCH_STEPS, "bounded, and it used the bound"
    assert [a["words"] for a in audit["attempts"]] == [18, 6, 4]


def test_the_ladder_is_bounded_and_never_walks_every_truncation(monkeypatch):
    """Wikimedia rate-limits a burst — an unbounded probe earned a 429 inside about
    twenty calls, and a 429 is indistinguishable from an honest miss from the
    caller's side. So recall is bought in a few steps, never by trying every
    truncation of a long brief."""
    calls: list[str] = []

    def fake(url: str) -> bytes:
        calls.append(url)
        return json.dumps({"query": {"pages": {}}}).encode("utf-8")

    monkeypatch.setattr(phototrace, "_FETCH", fake)
    rows, audit = phototrace.search_reference_ladder(" ".join(f"w{i}" for i in range(40)))

    assert rows == []
    assert len(calls) <= phototrace._MAX_SEARCH_STEPS == 3
    assert audit["reason"] == "no-candidates"


def test_a_rate_limited_search_is_not_filed_as_a_world_without_photographs(monkeypatch):
    """`search-failed` and `no-candidates` are different facts and the receipt must
    not merge them: one says try again, the other says this subject has no
    attribution-free photograph. The old code returned `[]` for both."""
    def boom(url: str) -> bytes:
        raise OSError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(phototrace, "_FETCH", boom)
    rows, audit = phototrace.search_reference_ladder("castle tower night")

    assert rows == []
    assert audit["reason"] == "search-failed"
    assert all(a["outcome"] == "search-failed" for a in audit["attempts"])


def test_a_rephotographed_document_is_not_a_reference_photograph():
    """Widening the search surfaced this: a live castle query returned two
    handwritten letters ABOVE the one actual castle, and taking the first fetchable
    candidate would have traced a page of handwriting as the place — worse than the
    procedural base, because it is confidently wrong rather than merely plain.
    Neither letter carried a document CATEGORY; what named them was the description,
    which opened "Manuscript letter". Both fields are judged, with the real metadata
    shapes below copied from those files."""
    letter = {
        "Categories": {"value": (
            "PD US expired|Images from NPGallery|Frances (Appleton) Longfellow to "
            "Emmeline (Austin) Wadsworth, 1840s"
        )},
        "ObjectName": {"value": "Frances (Appleton) Longfellow to Emmeline Wadsworth"},
        "ImageDescription": {"value": "<p>Manuscript letter</p>\n<p>Archives Number: 1011</p>"},
    }
    castle = {
        "Categories": {"value": (
            "CC-Zero|Urquhart Castle|Flickr images reviewed by FlickreviewR 2|"
            "Digitally manipulated photographs with artistic effects"
        )},
        "ObjectName": {"value": "Urquhart Castle on Loch Ness"},
        "ImageDescription": {"value": "<p>The castle above the loch at dusk.</p>"},
    }
    assert phototrace._is_document(letter) is True
    assert phototrace._is_document(castle) is False


def test_the_search_itself_drops_a_rephotographed_document(monkeypatch):
    """Pins the CALL SITE, not just the predicate: a document that ranks above the
    real subject must never reach the caller, because the caller traces the FIRST
    candidate that fetches."""
    payload = {"query": {"pages": {
        "1": {"title": "File:Letter.jpg", "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/letter.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Letter.jpg",
            "extmetadata": {
                "LicenseShortName": {"value": "Public domain"},
                "ImageDescription": {"value": "<p>Manuscript letter</p>"},
            },
        }]},
        "2": {"title": "File:Castle.jpg", "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/castle.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Castle.jpg",
            "extmetadata": {
                "LicenseShortName": {"value": "CC0"},
                "ImageDescription": {"value": "<p>The castle above the loch.</p>"},
            },
        }]},
    }}}
    monkeypatch.setattr(
        phototrace, "_FETCH", lambda url: json.dumps(payload).encode("utf-8")
    )

    rows = search_reference("castle tower night stone")

    assert [r["title"] for r in rows] == ["File:Castle.jpg"]


def test_an_incidental_word_deep_in_a_caption_keeps_a_real_photograph():
    """Only the LEAD of the description names the object, so a photograph whose
    caption mentions a document further down is still a photograph. Judging the
    whole caption would drop real scenes."""
    photo = {
        "Categories": {"value": "CC-Zero|Castles in Wales"},
        "ObjectName": {"value": "Gate tower at dawn"},
        "ImageDescription": {"value": (
            "<p>The gate tower seen from the causeway at first light.</p>" + "x" * 200
            + " carved letters above the arch record the mason's name"
        )},
    }
    assert phototrace._is_document(photo) is False


@pytest.mark.parametrize(
    "url",
    [
        "http://upload.wikimedia.org/photo.jpg",
        "https://example.com/photo.jpg",
        "https://upload.wikimedia.org.evil.example/photo.jpg",
        "https://user@upload.wikimedia.org/photo.jpg",
    ],
)
def test_photo_fetch_refuses_urls_outside_the_wikimedia_https_boundary(url, monkeypatch):
    monkeypatch.setattr(phototrace, "_FETCH", lambda candidate: b"")
    with pytest.raises(BackdropError, match="only from Wikimedia"):
        phototrace._http_get(url)


def test_redirect_to_a_non_wikimedia_host_is_refused_before_following():
    handler = phototrace._WikimediaRedirectHandler()
    with pytest.raises(BackdropError, match="only from Wikimedia"):
        handler.redirect_request(
            None, None, 302, "Found", {}, "https://example.com/redirected.jpg"
        )


def test_unsupported_actual_image_format_is_refused_before_tracing():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="GIF")
    with pytest.raises(BackdropError, match="supported photograph"):
        build_underlay_fragment(buf.getvalue(), view=(20, 20))


@pytest.mark.parametrize(
    "size",
    [(phototrace.MAX_PHOTO_DIMENSION + 1, 1), (5_000, 5_000)],
)
def test_excessive_image_dimensions_are_refused_before_decode(monkeypatch, size):
    from PIL import Image

    class OversizedImage:
        format = "PNG"

        def __init__(self):
            self.size = size

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def convert(self, mode):  # pragma: no cover - the guard must run first
            raise AssertionError("oversized pixels were decoded")

    monkeypatch.setattr(Image, "open", lambda source: OversizedImage())
    with pytest.raises(BackdropError, match="dimensions are too large"):
        build_underlay_fragment(b"not-decoded", view=(20, 20))


@pytest.mark.parametrize("focal", [(-0.01, 0.5), (1.01, 0.5), (0.5, -0.01), (0.5, 1.01)])
def test_invalid_focal_points_are_refused(focal):
    with pytest.raises(BackdropError, match="between 0 and 1"):
        build_underlay_fragment(_photo_bytes(bright=True), view=(200, 200), focal=focal)


def test_each_variant_uses_its_own_focal_point(monkeypatch):
    from PIL import ImageOps

    original_fit = ImageOps.fit
    seen: list[tuple[float, float]] = []

    def capture_fit(image, size, *args, **kwargs):
        seen.append(kwargs["centering"])
        return original_fit(image, size, *args, **kwargs)

    monkeypatch.setattr(ImageOps, "fit", capture_fit)
    left = build_underlay_fragment(
        _photo_bytes(bright=True), view=(200, 200), focal=(0.0, 0.25)
    )
    right = build_underlay_fragment(
        _photo_bytes(bright=True), view=(200, 200), focal=(1.0, 0.75)
    )

    assert seen == [(0.0, 0.25), (1.0, 0.75)]
    assert left != right, "different focal framing must change an asymmetric trace"


def test_bounded_worker_returns_a_valid_fragment():
    fragment = build_underlay_fragment_bounded(
        _photo_bytes(bright=True), view=(200, 150), focal=(0.25, 0.75)
    )
    assert fragment.startswith('<g opacity="0.65">')
    compile_backdrop(_wrap(fragment, 200, 150))


def test_bounded_worker_timeout_is_a_clear_error(monkeypatch):
    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(phototrace.subprocess, "run", time_out)
    monkeypatch.setattr(phototrace, "TRACE_TIMEOUT_SECS", 1)
    with pytest.raises(BackdropError, match="timed out after 1s"):
        build_underlay_fragment_bounded(_photo_bytes(bright=True), view=(20, 20))


def test_bounded_worker_refuses_missing_output(monkeypatch):
    monkeypatch.setattr(
        phototrace.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stderr=b""),
    )
    with pytest.raises(BackdropError, match="no fragment produced"):
        build_underlay_fragment_bounded(_photo_bytes(bright=True), view=(20, 20))


def test_bounded_worker_refuses_malformed_output(monkeypatch):
    def write_malformed(command, **kwargs):
        Path(command[-1]).write_text("<script/>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stderr=b"")

    monkeypatch.setattr(phototrace.subprocess, "run", write_malformed)
    with pytest.raises(BackdropError, match="script"):
        build_underlay_fragment_bounded(_photo_bytes(bright=True), view=(20, 20))


def test_bounded_worker_rejects_oversized_input_before_writing_or_spawning(monkeypatch):
    monkeypatch.setattr(phototrace, "_MAX_PHOTO_BYTES", 3)

    def must_not_spawn(*args, **kwargs):  # pragma: no cover - guard must run first
        raise AssertionError("worker spawned for oversized input")

    monkeypatch.setattr(phototrace.subprocess, "run", must_not_spawn)
    with pytest.raises(BackdropError, match="too large to trace"):
        build_underlay_fragment_bounded(b"four", view=(20, 20))


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
                    "mime": "image/jpeg",
                    "thumburl": "https://upload.wikimedia.org/b.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Bridge.jpg",
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
        '<rect width="{w}" height="{h}" fill="#0b0e17"/><g id=\'etr-underlay\'/>'
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
    assert committed["source"] == {
        "title": "File:Bridge.jpg",
        "pageUrl": "https://commons.wikimedia.org/wiki/File:Bridge.jpg",
        "license": "CC0",
    }
    assert committed["trace"] == {
        "pipeline": "trace",
        "underlay": "reference",
        "fragmentId": out["fragmentId"],
        "query": "stone bridge",
        "used": True,
        # Which search rung won. A brief that only ever matches after widening is
        # then visible as a brief to rewrite rather than a silent success.
        "matched": "stone bridge",
    }
    assert TraceStore(data, run_id).load(1) is None, "trace cleared after publication"


@pytest.mark.parametrize(
    ("source", "expected_underlay"),
    [
        (None, "base"),
        ({
            "title": "Legacy reference",
            "pageUrl": "https://commons.wikimedia.org/wiki/File:Legacy.jpg",
            "license": "CC0",
        }, "reference"),
    ],
)
def test_legacy_inflight_trace_gets_a_durable_receipt(
    data, source, expected_underlay
):
    run_id = "f" * 32
    turn = 6
    _request_backdrop(data, run_id, turn)
    trace_path = data / "runs" / run_id / "trace-underlay.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    fragment = '<g opacity="0.50"><rect width="10" height="10" fill="#334455"/></g>'
    trace_path.write_text(json.dumps({
        "fragmentId": "0123456789abcdef",
        "turn": turn,
        "desktop": fragment,
        "mobile": fragment,
        "source": source,
    }), encoding="utf-8")
    scene = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect width="10" height="10" fill="#111111"/>'
        '<g id="etr-underlay"/></svg>'
    )

    draft = _call(
        "endless_submit_backdrop_draft", runId=run_id, turn=turn,
        markup=scene, mobile=scene,
    )
    final = _call(
        "endless_commit_backdrop", runId=run_id, turn=turn,
        draftId=draft["draftId"], markup=scene, mobile=scene,
    )

    assert final["ok"] is True
    assert BackdropStore(data, run_id).current()["trace"] == {
        "pipeline": "trace",
        "underlay": expected_underlay,
        "fragmentId": "0123456789abcdef",
        "query": "",
        "used": True,
    }


def test_trace_tool_passes_independent_focal_points_to_the_worker(data, monkeypatch):
    payload = {"query": {"pages": {"1": {
        "title": "File:Bridge.jpg",
        "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/bridge.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Bridge.jpg",
            "extmetadata": {"LicenseShortName": {"value": "CC0"}},
        }],
    }}}}

    def fake_fetch(url: str) -> bytes:
        return json.dumps(payload).encode("utf-8") if "api.php" in url else b"photo"

    seen: list[tuple[tuple[int, int], tuple[float, float]]] = []

    def fake_worker(photo, *, view, ramp, opacity, focal):
        seen.append((view, focal))
        return procedural_base_fragment(view=view, ramp=ramp, opacity=opacity)

    monkeypatch.setattr(phototrace, "_FETCH", fake_fetch)
    monkeypatch.setattr(srv, "build_underlay_fragment_bounded", fake_worker)
    run_id = "f" * 32
    _request_backdrop(data, run_id, 5)

    out = _call(
        "endless_trace_reference",
        runId=run_id,
        turn=5,
        query="stone bridge",
        desktopFocalX=0.1,
        desktopFocalY=0.2,
        mobileFocalX=0.8,
        mobileFocalY=0.9,
    )

    assert out["ok"] is True and out["underlay"] == "reference"
    assert seen == [((800, 600), (0.1, 0.2)), ((450, 900), (0.8, 0.9))]


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

    plain = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    missing = _call(
        "endless_submit_backdrop_draft", runId=run_id, turn=2,
        markup=plain, mobile=plain,
    )
    assert missing["ok"] is False and "exactly one etr-underlay" in missing["error"]

    scene = plain.replace("</svg>", "<g id='etr-underlay'/></svg>")
    draft = _call(
        "endless_submit_backdrop_draft", runId=run_id, turn=2,
        markup=scene, mobile=scene,
    )
    final = _call(
        "endless_commit_backdrop", runId=run_id, turn=2,
        draftId=draft["draftId"], markup=scene, mobile=scene,
    )
    assert final["ok"] is True
    committed = BackdropStore(data, run_id).current()
    assert "etr-underlay" not in committed["markup"]
    assert committed["source"] is None
    assert committed["trace"] == {
        "pipeline": "trace",
        "underlay": "base",
        "fragmentId": out["fragmentId"],
        "query": "zombie at the door",
        "used": True,
        # A base underlay now says WHY, so the fallback is never mistaken for a
        # deliberate choice: this run searched, was answered, and nothing survived.
        # One attempt, not three: every rung of a four-word brief truncates to the
        # same words, and a repeated request would only spend the rate limit.
        "fallback": {
            "reason": "no-candidates",
            "attempts": [
                {"query": "zombie at the door", "words": 4,
                 "outcome": "no-candidates"},
            ],
        },
    }


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
