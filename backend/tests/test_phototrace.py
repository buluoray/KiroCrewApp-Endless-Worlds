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
    CandidateStore,
    TraceStore,
    build_underlay_fragment,
    build_underlay_fragment_bounded,
    compose_with_underlay,
    procedural_base_fragment,
    search_candidates,
    search_met,
    search_openverse,
    search_reference,
    search_smithsonian,
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


def test_search_openverse_keeps_cc0_pdm_via_the_thumbnail_proxy(monkeypatch):
    payload = {"results": [
        {"title": "A", "license": "cc0", "license_version": "1.0",
         "thumbnail": "https://api.openverse.org/v1/images/a/thumb/",
         "foreign_landing_url": "https://commons.wikimedia.org/wiki/File:A"},
        {"title": "B", "license": "pdm", "license_version": "1.0",
         "thumbnail": "https://api.openverse.org/v1/images/b/thumb/",
         "foreign_landing_url": "https://flickr.com/b"},
        {"title": "ByDrop", "license": "by", "license_version": "4.0",
         "thumbnail": "https://api.openverse.org/v1/images/c/thumb/", "foreign_landing_url": "x"},
        # A CC0 item whose thumbnail is a raw CDN, not the Openverse proxy: dropped
        # so image bytes never come off an un-allowlisted host.
        {"title": "OffHost", "license": "cc0", "license_version": "1.0",
         "thumbnail": "https://live.staticflickr.com/x/raw.jpg", "foreign_landing_url": "x"},
    ]}
    monkeypatch.setattr(phototrace, "_FETCH", lambda url: json.dumps(payload).encode("utf-8"))
    rows = search_openverse("bridge")
    assert [r["title"] for r in rows] == ["A", "B"]
    assert [r["license"] for r in rows] == ["CC0", "Public domain"]
    assert all(r["url"].startswith("https://api.openverse.org/") for r in rows)


def test_search_met_keeps_only_public_domain_objects_with_an_image(monkeypatch):
    def fake(url):
        if "/search?" in url:
            return json.dumps({"total": 3, "objectIDs": [1, 2, 3]}).encode("utf-8")
        if url.endswith("/objects/1"):
            return json.dumps({"isPublicDomain": True, "title": "PD art",
                "primaryImageSmall": "https://images.metmuseum.org/1.jpg",
                "objectURL": "https://www.metmuseum.org/1"}).encode("utf-8")
        if url.endswith("/objects/2"):
            return json.dumps({"isPublicDomain": False, "title": "Owned",
                "primaryImageSmall": "https://images.metmuseum.org/2.jpg"}).encode("utf-8")
        if url.endswith("/objects/3"):
            return json.dumps({"isPublicDomain": True, "title": "No image",
                "primaryImageSmall": ""}).encode("utf-8")
        raise AssertionError(url)
    monkeypatch.setattr(phototrace, "_FETCH", fake)
    rows = search_met("castle")
    assert [r["title"] for r in rows] == ["PD art"]
    assert rows[0]["url"] == "https://images.metmuseum.org/1.jpg"
    assert rows[0]["license"] == "Public domain"


def test_search_smithsonian_is_inert_without_an_api_key(monkeypatch):
    monkeypatch.delenv("SI_API_KEY", raising=False)
    called = {"hit": False}

    def fake(url):  # pragma: no cover - must never run without a key
        called["hit"] = True
        return b"{}"

    monkeypatch.setattr(phototrace, "_FETCH", fake)
    assert search_smithsonian("anything") == []
    assert called["hit"] is False


def test_search_smithsonian_keeps_cc0_items_with_an_image(monkeypatch):
    monkeypatch.setenv("SI_API_KEY", "k")
    payload = {"response": {"rows": [
        {"title": "CC0 thing", "content": {"descriptiveNonRepeating": {
            "record_link": "https://www.si.edu/object/x",
            "metadata_usage": {"access": "CC0"},
            "online_media": {"media": [
                {"type": "Images", "content": "https://ids.si.edu/ids/deliveryService?id=x"}
            ]},
        }}},
        {"title": "Restricted", "content": {"descriptiveNonRepeating": {
            "metadata_usage": {"access": "Usage conditions apply"},
            "online_media": {"media": [{"type": "Images", "content": "https://ids.si.edu/y"}]},
        }}},
    ]}}
    monkeypatch.setattr(phototrace, "_FETCH", lambda url: json.dumps(payload).encode("utf-8"))
    rows = search_smithsonian("bird")
    assert [r["title"] for r in rows] == ["CC0 thing"]
    assert rows[0]["license"] == "CC0"
    assert rows[0]["url"].startswith("https://ids.si.edu/")


def test_search_candidates_photo_lane_lists_openverse_before_commons(monkeypatch):
    def fake(url):
        if "openverse.org/v1/images/?" in url:
            return json.dumps({"results": [{"title": "OV", "license": "cc0",
                "thumbnail": "https://api.openverse.org/v1/images/z/thumb/",
                "foreign_landing_url": "x"}]}).encode("utf-8")
        if "api.php" in url:
            return json.dumps({"query": {"pages": {"1": {"title": "File:C.jpg",
                "imageinfo": [{"mime": "image/jpeg",
                    "thumburl": "https://upload.wikimedia.org/c.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:C.jpg",
                    "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]}}}}).encode("utf-8")
        raise AssertionError(url)
    monkeypatch.setattr(phototrace, "_FETCH", fake)
    rows, audit = search_candidates("village", "photo")
    assert [r["title"] for r in rows] == ["OV", "File:C.jpg"]
    assert audit["reason"] == "ok" and audit["matched"] == "village"


def test_search_candidates_art_lane_uses_the_met(monkeypatch):
    def fake(url):
        if "metmuseum.org" in url and "/search?" in url:
            return json.dumps({"objectIDs": [7]}).encode("utf-8")
        if url.endswith("/objects/7"):
            return json.dumps({"isPublicDomain": True, "title": "Met art",
                "primaryImageSmall": "https://images.metmuseum.org/7.jpg",
                "objectURL": "https://www.metmuseum.org/7"}).encode("utf-8")
        raise AssertionError(url)
    monkeypatch.delenv("SI_API_KEY", raising=False)
    monkeypatch.setattr(phototrace, "_FETCH", fake)
    rows, audit = search_candidates("angel", "art")
    assert [r["title"] for r in rows] == ["Met art"]
    assert audit["reason"] == "ok"


# -- recall: the ladder, the sample, and what is not a photograph ---------


def test_the_commons_search_excludes_book_scans_and_samples_wide(monkeypatch):
    """Measured live: Commons' attribution-free material skews to scanned BOOKS. A
    four-word village query returned ten pages whose every public-domain hit was a
    PDF or DjVu scan and whose every actual photograph was CC BY-SA, so nothing
    survived the gates on a query that HAD matched. `filetype:bitmap` removes the
    scans at the source and the sample is wide enough for the thin surviving
    intersection — the same single request either way."""
    seen: list[str] = []

    def fake(url: str) -> bytes:
        seen.append(url)
        return json.dumps({"query": {"pages": {}}}).encode("utf-8")

    monkeypatch.setattr(phototrace, "_FETCH", fake)
    search_reference("castle tower night")

    assert len(seen) == 1
    assert "filetype%3Abitmap" in seen[0]
    assert f"gsrlimit={phototrace._RAW_SEARCH_ROWS}" in seen[0]


def test_the_ladder_widens_a_specific_brief_and_stops_at_the_first_rung(monkeypatch):
    """Both backends match CONJUNCTIVELY, so a brief written the way the Illustrator
    is ASKED to write one matches nothing: measured live, the 18-word river-mill
    brief returns zero Commons hits while its first two words return several. The
    ladder buys recall in a bounded number of rungs and stops at the first that
    matches."""
    brief = (
        "medieval European river-mill village timber granary dirt road low stone "
        "bridge dawn mist farmland distant walled town horizon"
    )
    asked: list[str] = []

    def fake(url: str) -> bytes:
        asked.append(url)
        # Only the narrowest rung matches, and only on the second source, exactly as
        # live Commons behaved for this brief.
        if "api.php" in url and "granary" not in url and "timber" not in url:
            return json.dumps({"query": {"pages": {"1": {"title": "File:Mill.jpg",
                "imageinfo": [{"mime": "image/jpeg",
                    "thumburl": "https://upload.wikimedia.org/mill.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Mill.jpg",
                    "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]}}}}).encode()
        return json.dumps({"results": [], "query": {"pages": {}}}).encode("utf-8")

    monkeypatch.setattr(phototrace, "_FETCH", fake)
    rows, audit = search_candidates(brief, "photo")

    assert [r["title"] for r in rows] == ["File:Mill.jpg"]
    assert audit["reason"] == "ok"
    assert audit["matched"] == "medieval European river-mill village", "the rung is named"
    # Front words first, floored at four: never a two-word rung, which measured out
    # as an amphora and a manuscript page standing in for a river-mill village.
    assert {len(a["query"].split()) for a in audit["attempts"]} == {18, 6, 4}


def test_a_rephotographed_document_is_not_a_reference_photograph():
    """Widening the search surfaced this: a live castle query returned two
    handwritten letters ABOVE the one real castle, and the caller traces the FIRST
    candidate that fetches — so it would have traced a page of handwriting as the
    place. Neither letter carried a document CATEGORY; what named them was the
    description, which opened "Manuscript letter". The real metadata shapes are
    copied from those files."""
    assert phototrace._looks_like_document(
        "PD US expired|Images from NPGallery",
        "Frances (Appleton) Longfellow to Emmeline Wadsworth",
        phototrace._description_lead("<p>Manuscript letter</p>\n<p>Archives 1011</p>"),
    ) is True
    assert phototrace._looks_like_document(
        "CC-Zero|Urquhart Castle|Flickr images reviewed by FlickreviewR 2",
        "Urquhart Castle on Loch Ness",
        phototrace._description_lead("<p>The castle above the loch at dusk.</p>"),
    ) is False
    # Only the LEAD of a description names the object, so an incidental mention
    # further down still keeps a real photograph.
    assert phototrace._looks_like_document(
        "CC-Zero|Castles in Wales", "Gate tower at dawn",
        phototrace._description_lead(
            "<p>The gate tower from the causeway.</p>" + "x" * 200
            + " carved letters above the arch record the mason's name"
        ),
    ) is False


def test_the_search_itself_drops_a_document_that_outranks_the_subject(monkeypatch):
    """Pins the CALL SITE, not just the predicate."""
    payload = {"query": {"pages": {
        "1": {"title": "File:Letter.jpg", "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/letter.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Letter.jpg",
            "extmetadata": {"LicenseShortName": {"value": "Public domain"},
                            "ImageDescription": {"value": "<p>Manuscript letter</p>"}},
        }]},
        "2": {"title": "File:Castle.jpg", "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/castle.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Castle.jpg",
            "extmetadata": {"LicenseShortName": {"value": "CC0"},
                            "ImageDescription": {"value": "<p>The castle.</p>"}},
        }]},
    }}}
    monkeypatch.setattr(
        phototrace, "_FETCH", lambda url: json.dumps(payload).encode("utf-8")
    )
    assert [r["title"] for r in search_reference("castle")] == ["File:Castle.jpg"]


# -- cost: stop early, and remember a miss --------------------------------


def test_a_satisfied_lane_does_not_pay_for_the_next_source(monkeypatch):
    """The loop used to query EVERY source even with enough candidates in hand, so a
    photo query always cost two requests. Wikimedia rate-limits a burst, and the
    second request buys candidates nobody reaches."""
    asked: list[str] = []

    def fake(url: str) -> bytes:
        asked.append(url)
        if "openverse" in url:
            return json.dumps({"results": [
                {"title": f"OV{i}", "license": "cc0",
                 "thumbnail": f"https://api.openverse.org/v1/images/{i}/thumb/",
                 "foreign_landing_url": "x"} for i in range(3)
            ]}).encode("utf-8")
        raise AssertionError(f"commons must not be asked: {url}")

    monkeypatch.setattr(phototrace, "_FETCH", fake)
    rows, audit = search_candidates("castle tower night", "photo", limit=3)

    assert len(rows) == 3
    assert len(asked) == 1, "one request, not one per source"
    assert [a["source"] for a in audit["attempts"]] == ["openverse"]


def test_a_source_that_answered_with_nothing_is_not_asked_again(tmp_path, monkeypatch):
    """The miss cache: a subject with no attribution-free photograph is discovered
    once, not once per page. Keyed per SOURCE, because Openverse missing while
    Commons hits is the normal case."""
    calls: list[str] = []

    def fake(url: str) -> bytes:
        calls.append(url)
        return json.dumps({"results": [], "query": {"pages": {}}}).encode("utf-8")

    monkeypatch.setattr(phototrace, "_FETCH", fake)
    cache = phototrace.MissCache(tmp_path)

    first, audit1 = search_candidates("a windmill on a salt flat", "photo", misses=cache)
    assert first == [] and audit1["reason"] == "no-candidates"
    spent = len(calls)
    assert spent > 0

    second, audit2 = search_candidates("a windmill on a salt flat", "photo", misses=cache)
    assert second == []
    assert len(calls) == spent, "a known miss must not spend a request"
    assert {a["outcome"] for a in audit2["attempts"]} == {"cached-miss"}
    # A conjunctive match does not depend on word ORDER, so the same words in
    # another order are the same negative fact and hit the same entry. This holds
    # per query; the LADDER is deliberately order-dependent (it keeps front words,
    # which carry the subject), so a reordered brief still explores its own rungs.
    assert cache.missed("commons", "salt flat windmill a on a")
    assert cache.missed("openverse", "FLAT  salt  a on  windmill a")


def test_a_rate_limited_search_is_never_cached_as_a_world_without_photographs(
    tmp_path, monkeypatch
):
    """The distinction the whole cache rests on. One 429 would otherwise mark a
    subject imageless for a fortnight."""
    def boom(url: str) -> bytes:
        raise OSError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(phototrace, "_FETCH", boom)
    cache = phototrace.MissCache(tmp_path)
    rows, audit = search_candidates("castle tower night", "photo", misses=cache)

    assert rows == []
    assert audit["reason"] == "search-failed", "not a statement about the subject"
    assert not cache.missed("openverse", "castle tower night")
    assert not cache.missed("commons", "castle tower night")


def test_a_recorded_miss_expires_and_does_not_outlive_a_filter_change(
    tmp_path, monkeypatch
):
    """Two ways a negative stops being true: time (the corpora grow) and a change to
    the gates that produced it. The second is the dangerous one — without the
    fingerprint, fixing a filter would keep answering "no image" from a cache built
    under the old rules, and the fix would look like it had not worked."""
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(phototrace, "_NOW", lambda: clock["t"])
    cache = phototrace.MissCache(tmp_path)
    cache.record("commons", "a windmill on a salt flat")
    assert cache.missed("commons", "a windmill on a salt flat")

    clock["t"] += phototrace._MISS_TTL_SECS + 1
    assert not cache.missed("commons", "a windmill on a salt flat"), "TTL expired"

    clock["t"] = 1_000_000.0
    cache.record("commons", "a windmill on a salt flat")
    assert cache.missed("commons", "a windmill on a salt flat")
    monkeypatch.setattr(phototrace, "_RAW_SEARCH_ROWS", phototrace._RAW_SEARCH_ROWS + 1)
    assert not cache.missed("commons", "a windmill on a salt flat"), "config changed"


def test_the_miss_cache_is_bounded_and_evicts_the_oldest(tmp_path, monkeypatch):
    clock = {"t": 1.0}
    monkeypatch.setattr(phototrace, "_NOW", lambda: clock["t"])
    monkeypatch.setattr(phototrace, "_MISS_CACHE_CAP", 5)
    cache = phototrace.MissCache(tmp_path)
    for i in range(8):
        clock["t"] += 1
        cache.record("commons", f"subject {i}")
    assert len(cache._read()) == 5
    assert not cache.missed("commons", "subject 0"), "the oldest went first"
    assert cache.missed("commons", "subject 7")


@pytest.mark.parametrize(
    "url",
    [
        "http://upload.wikimedia.org/photo.jpg",
        "https://example.com/photo.jpg",
        "https://upload.wikimedia.org.evil.example/photo.jpg",
        "https://user@upload.wikimedia.org/photo.jpg",
    ],
)
def test_photo_fetch_refuses_urls_outside_the_allowed_https_boundary(url, monkeypatch):
    monkeypatch.setattr(phototrace, "_FETCH", lambda candidate: b"")
    with pytest.raises(BackdropError, match="allowed archive"):
        phototrace._http_get(url)


def test_redirect_to_a_disallowed_host_is_refused_before_following():
    handler = phototrace._AllowedHostRedirectHandler()
    with pytest.raises(BackdropError, match="allowed archive"):
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
    assert out["candidateCount"] == 1
    assert out["candidates"][0]["source"]["title"] == "File:Bridge.jpg"
    for path in out["candidates"][0]["previews"].values():
        assert Path(path).is_file(), "previews must be readable before choosing"

    picked = _call("endless_select_reference", runId=run_id, turn=1, index=0)
    assert picked["ok"] is True and picked["source"]["title"] == "File:Bridge.jpg"
    assert CandidateStore(data, run_id).load(1) is None, "candidates cleared after a pick"

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
        "fragmentId": picked["fragmentId"],
        "query": "stone bridge",
        "used": True,
        # Which ladder rung won. A brief that only matches after widening is then
        # visible as a brief to rewrite rather than a silent success.
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
        query="unfindable", ramp=["#0a0d14", "#182030", "#2c3c55", "#9db4d4"],
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
    out = _call("endless_trace_reference", runId=run_id, turn=2, query="zombies")
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
    # A base underlay now says WHY, per source, so the fallback is never mistaken
    # for a deliberate choice: both photo sources answered and held nothing usable.
    fb = committed["trace"].pop("fallback")
    assert committed["trace"] == {
        "pipeline": "trace",
        "underlay": "base",
        "fragmentId": out["fragmentId"],
        "query": "zombies",
        "used": True,
    }
    assert fb["reason"] == "no-candidates"
    assert {(a["source"], a["outcome"]) for a in fb["attempts"]} == {
        ("openverse", "no-candidates"), ("commons", "no-candidates"),
    }


def test_a_total_miss_offers_a_way_back_and_names_the_subject_rule(data, monkeypatch):
    """A multi-word SCENE miss is handed back ONCE for a single-keyword retry rather
    than settled for a base: only the narrow free-license slice is searched, so a
    compound subject misses while its head noun hits. The first miss creates NO base
    (the scene gate then forces the retry), and the directive asks for one noun."""
    import mcp_server as srv
    monkeypatch.setattr(
        phototrace, "_FETCH",
        lambda url: json.dumps({"results": [], "query": {"pages": {}}}).encode("utf-8"),
    )
    run_id = "e" * 32
    _request_backdrop(data, run_id, 2)
    out = _call("endless_trace_reference", runId=run_id, turn=2,
                query="medieval European river-mill village timber granary dirt road")

    assert out["ok"] is True and out["underlay"] == "none", "a multi-word miss is not settled"
    assert TraceStore(data, run_id).load(2) is None, "no base is created on the first miss"
    nxt = out["next"]
    assert "SINGLE most-relevant noun" in nxt, "it must ask for one keyword"
    assert "Do not settle for a base yet" in nxt

    # The terminal base hint (used once the retry budget is spent) still names the
    # three miss reasons distinctly. search-failed retries the SAME words; nothing
    # to retry for fetch-failed / no-query.
    retry = srv._base_underlay_next({"reason": "search-failed"})
    assert "did not answer" in retry and "SAME words" in retry
    assert "just the subject" not in retry
    for reason in ("fetch-failed", "no-query"):
        quiet = srv._base_underlay_next({"reason": reason})
        assert "procedural tonal base is active" in quiet
        assert "once more" not in quiet.lower()


def test_the_query_contract_asks_for_a_subject_not_a_scene():
    """`query` is the page's SUBJECT. Both archives match every word, so the schema
    the Illustrator reads must say that plainly — it is the only machine-readable
    instruction it gets, and the old wording ('concrete English keywords for a place
    or structure, e.g. "stone bridge river mist"') invited exactly the four-word-plus
    query that returns nothing."""
    import mcp_server as srv
    desc = next(
        t["description"] for t in srv._TOOLS if t["name"] == "endless_trace_reference"
    )
    assert "SUBJECT" in desc
    assert "NOT the era, region, weather, time of day or mood" in desc
    assert "each extra word removes results" in desc
    assert "river mist" not in desc, "the old scene-shaped example must be gone"


def test_a_scene_brief_cannot_be_published_as_a_hand_drawn_motif(data, monkeypatch):
    """Nothing used to check that a SCENE brief actually ran the trace lane.
    `_apply_underlay` requires the placeholder only when a trace record EXISTS, so an
    Illustrator that skipped `endless_trace_reference` and hand-drew the page
    committed cleanly and was stored as an ordinary motif — no underlay, no receipt,
    no trace of the intent. A real page did exactly that, and afterwards nothing could
    tell whether the narrator had asked for a motif or the scene lane had been quietly
    abandoned, because the brief is cleared the moment art commits."""
    import mcp_server as srv
    store = srv._store()
    run_id = "a" * 32
    store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    store.request_backdrop(run_id, turn=1, brief="LANE: scene\nREFERENCE: subject=\"stone bridge\"")

    # The lane is parsed once, at request time, and kept beside the brief.
    assert store.read_backdrop_request(run_id)["lane"] == "scene"

    plain = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    out = _call("endless_submit_backdrop_draft", runId=run_id, turn=1,
                markup=plain, mobile=plain)
    assert out["ok"] is False
    assert "declared LANE: scene" in out["error"]
    assert "endless_trace_reference" in out["error"], "the refusal names the fix"


def test_a_motif_brief_is_still_free_to_be_hand_drawn(data, monkeypatch):
    """The gate is scoped to the lane the brief declared: a motif page must stay
    exactly as cheap and unconstrained as it was."""
    import mcp_server as srv
    store = srv._store()
    run_id = "b" * 32
    store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    store.request_backdrop(run_id, turn=1, brief="LANE: motif\nTHESIS: a vow hardening")
    assert store.read_backdrop_request(run_id)["lane"] == "motif"

    plain = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    out = _call("endless_submit_backdrop_draft", runId=run_id, turn=1,
                markup=plain, mobile=plain)
    assert out["ok"] is True, out


def test_a_base_underlay_satisfies_the_scene_gate(data, monkeypatch):
    """The gate is "the lane RAN", not "a photograph was found". A search that finds
    nothing hands back a procedural base, and that page is a legitimate scene."""
    import mcp_server as srv
    monkeypatch.setattr(
        phototrace, "_FETCH",
        lambda url: json.dumps({"results": [], "query": {"pages": {}}}).encode("utf-8"),
    )
    store = srv._store()
    run_id = "c" * 32
    store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    store.request_backdrop(run_id, turn=1, brief="LANE: scene\nREFERENCE: subject=\"stone bridge\"")

    traced = _call("endless_trace_reference", runId=run_id, turn=1, query="castle")
    assert traced["underlay"] == "base"

    scene = ('<svg xmlns="http://www.w3.org/2000/svg"><g id="etr-underlay"/>'
             '<rect width="10" height="10"/></svg>')
    out = _call("endless_submit_backdrop_draft", runId=run_id, turn=1,
                markup=scene, mobile=scene)
    assert out["ok"] is True, out


def test_an_undeclared_lane_is_not_enforced(data):
    """`brief_lane` is lenient on purpose: a brief whose header the narrator spelled
    oddly, or omitted, is still art direction. Losing a page's art over a header is a
    worse outcome than not enforcing the lane on that page."""
    from store import brief_lane
    assert brief_lane("LANE: scene\nx") == "scene"
    assert brief_lane("lane:  MOTIF  \nx") == "motif"
    assert brief_lane("REFERENCE: subject=\"bridge\"") == ""
    assert brief_lane("a scene of a bridge") == "", "prose is not a declaration"
    assert brief_lane("") == ""


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


def test_trace_offers_multiple_candidates_and_select_promotes_the_chosen(data, monkeypatch):
    photo = _photo_bytes(bright=True)

    def fake_fetch(url: str) -> bytes:
        if "openverse.org/v1/images/?" in url:
            return json.dumps({"results": [
                {"title": "Bridge A", "license": "cc0", "license_version": "1.0",
                 "thumbnail": "https://api.openverse.org/v1/images/a/thumb/",
                 "foreign_landing_url": "https://commons.wikimedia.org/wiki/File:A"},
                {"title": "Bridge B", "license": "pdm", "license_version": "1.0",
                 "thumbnail": "https://api.openverse.org/v1/images/b/thumb/",
                 "foreign_landing_url": "https://www.flickr.com/b"},
            ]}).encode("utf-8")
        return photo  # thumbnail proxy bytes; commons api.php parse-fails to []

    monkeypatch.setattr(phototrace, "_FETCH", fake_fetch)
    run_id = "a" * 32
    _request_backdrop(data, run_id, 1)

    out = _call("endless_trace_reference", runId=run_id, turn=1, query="stone bridge")
    assert out["ok"] is True and out["underlay"] == "reference"
    assert out["candidateCount"] == 2
    assert [c["source"]["title"] for c in out["candidates"]] == ["Bridge A", "Bridge B"]

    bad = _call("endless_select_reference", runId=run_id, turn=1, index=9)
    assert bad["ok"] is False and "between 0 and 1" in bad["error"]

    picked = _call("endless_select_reference", runId=run_id, turn=1, index=1)
    assert picked["ok"] is True and picked["source"]["title"] == "Bridge B"

    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
        '<rect width="{w}" height="{h}" fill="#0b0e17"/><g id=\'etr-underlay\'/></svg>'
    )
    draft = _call(
        "endless_submit_backdrop_draft", runId=run_id, turn=1,
        markup=overlay.format(w=800, h=600), mobile=overlay.format(w=450, h=900),
    )
    final = _call(
        "endless_commit_backdrop", runId=run_id, turn=1, draftId=draft["draftId"],
        markup=overlay.format(w=800, h=600), mobile=overlay.format(w=450, h=900),
    )
    assert final["ok"] is True
    committed = BackdropStore(data, run_id).current()
    assert committed["source"]["title"] == "Bridge B", "the SELECTED candidate is the underlay"
    assert committed["trace"]["underlay"] == "reference"


def test_select_reference_is_refused_when_no_candidates_are_waiting(data):
    run_id = "d" * 32
    _request_backdrop(data, run_id, 1)
    out = _call("endless_select_reference", runId=run_id, turn=1, index=0)
    assert out["ok"] is False and "endless_trace_reference" in out["error"]


def test_trace_art_lane_routes_to_the_met(data, monkeypatch):
    photo = _photo_bytes(bright=True)

    def fake_fetch(url: str) -> bytes:
        if "metmuseum.org" in url and "/search?" in url:
            return json.dumps({"objectIDs": [7]}).encode("utf-8")
        if url.endswith("/objects/7"):
            return json.dumps({"isPublicDomain": True, "title": "PD Painting",
                "primaryImageSmall": "https://images.metmuseum.org/7.jpg",
                "objectURL": "https://www.metmuseum.org/7"}).encode("utf-8")
        return photo

    monkeypatch.delenv("SI_API_KEY", raising=False)
    monkeypatch.setattr(phototrace, "_FETCH", fake_fetch)
    run_id = "e" * 32
    _request_backdrop(data, run_id, 3)
    out = _call("endless_trace_reference", runId=run_id, turn=3, query="angel", source="art")
    assert out["ok"] is True and out["underlay"] == "reference"
    assert out["candidates"][0]["source"]["title"] == "PD Painting"


def test_the_server_publishes_the_base_underlay_when_the_model_never_commits(data, monkeypatch):
    """The 120s server fallback: when a SCENE page's illustrator runs out of time but
    the lane already produced an underlay (here a procedural base), the server
    publishes that underlay ALONE as the page's backdrop — a real image, with no
    model call and no hand-drawn recovery."""
    import mcp_server as srv
    monkeypatch.setattr(
        phototrace, "_FETCH",
        lambda url: json.dumps({"results": [], "query": {"pages": {}}}).encode("utf-8"),
    )
    store = srv._store()
    run_id = "d" * 32
    store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    store.request_backdrop(
        run_id, turn=1, brief="LANE: scene\nREFERENCE: subject=\"stone bridge\""
    )
    assert _call(
        "endless_trace_reference", runId=run_id, turn=1, query="castle"
    )["underlay"] == "base"

    # The model never drafts or commits — it "timed out". The base underlay is in
    # the trace store but is NOT yet the page's backdrop.
    assert BackdropStore(data, run_id).exact(1) is None

    assert srv.commit_underlay_only(data, store, run_id, 1) is True
    assert BackdropStore(data, run_id).exact(1) is not None, (
        "the base underlay is now the page's backdrop"
    )
    assert store.read_backdrop_request(run_id) is None, "the request clears once art lands"


def test_the_server_fallback_is_a_noop_when_nothing_was_traced(data):
    """A page whose illustrator never reached the trace tool has no underlay to
    publish; the fallback declines (returns False) and commits nothing, leaving the
    narrator recovery as the last resort."""
    import mcp_server as srv
    store = srv._store()
    run_id = "e" * 32
    store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    store.request_backdrop(
        run_id, turn=1, brief="LANE: scene\nREFERENCE: subject=\"stone bridge\""
    )

    assert srv.commit_underlay_only(data, store, run_id, 1) is False
    assert BackdropStore(data, run_id).exact(1) is None


def test_a_multiword_scene_miss_is_handed_back_then_settles(data, monkeypatch):
    """A multi-word SCENE miss returns underlay:none with a single-keyword retry
    directive and creates NO base (so the scene gate forces the retry); a SECOND
    miss settles for the base rather than wedging the page."""
    import mcp_server as srv
    monkeypatch.setattr(
        phototrace, "_FETCH",
        lambda url: json.dumps({"results": [], "query": {"pages": {}}}).encode("utf-8"),
    )
    store = srv._store()
    run_id = "f" * 32
    _request_backdrop(data, run_id, 1)

    first = _call("endless_trace_reference", runId=run_id, turn=1,
                  query="stone forge workshop")
    assert first["underlay"] == "none", "the first multi-word miss is handed back"
    assert TraceStore(data, run_id).load(1) is None, "no base created on the first miss"
    assert "SINGLE most-relevant noun" in first["next"]
    assert int(store.read_backdrop_request(run_id).get("traceRetries") or 0) == 1

    # The retry (still a miss here) now settles for the base — bounded, never wedged.
    second = _call("endless_trace_reference", runId=run_id, turn=1, query="forge anvil")
    assert second["underlay"] == "base"
    assert TraceStore(data, run_id).load(1) is not None


def test_a_single_word_scene_miss_settles_for_base_immediately(data, monkeypatch):
    """A single-word query has nothing left to simplify, so a miss settles for the
    base on the first call rather than asking for a pointless retry."""
    monkeypatch.setattr(
        phototrace, "_FETCH",
        lambda url: json.dumps({"results": [], "query": {"pages": {}}}).encode("utf-8"),
    )
    run_id = "0" * 32
    _request_backdrop(data, run_id, 1)
    out = _call("endless_trace_reference", runId=run_id, turn=1, query="forge")
    assert out["underlay"] == "base", "a single-word miss has no keyword to retry"
    assert TraceStore(data, run_id).load(1) is not None
