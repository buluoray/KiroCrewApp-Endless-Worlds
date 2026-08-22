"""Photo-reference underlays for scene backdrops.

The SCENE lane's foundation: an attribution-free reference photograph is traced into
a palette-disciplined SVG fragment that the Illustrator composes UNDER its own
crisp line work. The photo supplies what a model cannot draw freehand — real
perspective, light distribution, and mass — while the world palette supplies
color discipline (a native-color trace reads as a cheap photo filter and is
never produced here).

Context economy is the design constraint: a traced fragment runs tens of
kilobytes, so it is stored server-side in :class:`TraceStore` and NEVER returned
to the model. The Illustrator places one ``<g id="etr-underlay"/>`` placeholder
in its SVG and the server splices the stored fragment in at draft/commit time
(:func:`compose_with_underlay`).

Reference images come from attribution-free archives only. The default *photo*
lane searches Openverse (a CC aggregator spanning Wikimedia Commons, Flickr and
more, filtered to CC0 + Public Domain Mark) and falls back to Wikimedia Commons;
the *art* lane draws public-domain artworks from the Met (and, when an
``SI_API_KEY`` is set, the Smithsonian). Every candidate is kept only when its
license reads as CC0 or public domain. When no usable reference exists — the
brief describes something no archive holds — the pipeline still earns its keep by
producing a procedural tonal base (:func:`procedural_base_fragment`) for the
Illustrator to paint over.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backdrop import _ID_RE, BackdropError, compile_backdrop

logger = logging.getLogger(__name__)

#: The nocturne ramp: near-black to dim gold, darkest first. Callers may pass a
#: world-specific ramp of the same shape (5-8 stops, darkest first).
NOCTURNE_RAMP: tuple[tuple[int, int, int], ...] = (
    (7, 8, 13),
    (11, 14, 23),
    (26, 28, 38),
    (58, 50, 28),
    (120, 95, 32),
    (201, 162, 39),
)

#: A composed backdrop (underlay + hand-drawn overlay) may reach this size; the
#: Illustrator's own hand-drawn input stays under the tool schema's 24KB.
MAX_TRACE_FRAGMENT_BYTES = 400_000

#: Pillow/vtracer execute in a killable child. One variant must finish within this
#: wall-clock bound so malformed or pathological photos cannot wedge the MCP loop.
TRACE_TIMEOUT_SECS = 30

#: How many traceable references the Illustrator is offered to choose among. Each
#: costs two bounded traces (desktop + mobile), so this is a small number: enough
#: for a real pick, bounded so a broad query cannot fan out into many trace jobs.
TRACE_CANDIDATE_COUNT = 3

#: Commons thumbnails are requested at 1200px. These broader hard ceilings catch a
#: forged response or decompression bomb before Pillow decodes its pixel payload.
MAX_PHOTO_PIXELS = 20_000_000
MAX_PHOTO_DIMENSION = 8_000
#: Every host from which reference bytes (or a search response) may be fetched.
#: Image bytes are pulled only through vetted proxy/host endpoints, never from a
#: raw third-party CDN: Openverse hands back a thumbnail on its OWN host
#: (api.openverse.org) even when the original lives on Flickr, and the Met serves
#: images from images.metmuseum.org — so the SSRF surface stays this fixed set.
_ALLOWED_FETCH_HOSTS = frozenset(
    {
        "commons.wikimedia.org",
        "upload.wikimedia.org",  # Wikimedia Commons
        "api.openverse.org",  # Openverse search + thumbnail proxy
        "collectionapi.metmuseum.org",
        "images.metmuseum.org",  # Met Museum API + image bytes
        "api.si.edu",
        "ids.si.edu",  # Smithsonian Open Access API + bytes
    }
)

#: Below this median luminance a photo's pixels crowd the darkest bands and the
#: traced layer vanishes against a dark page; lift midtones first.
_DARK_MEDIAN = 90
_DARK_GAMMA = 0.55

_PLACEHOLDER_RE = re.compile(r"<g\s+id=(?P<quote>[\"'])etr-underlay(?P=quote)\s*(?:/>|>\s*</g>)")

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
#: Only attribution-free material enters a backdrop. CC BY/SA would require a
#: persistent player-visible credit and may impose share-alike terms on the
#: composed artwork; keeping only CC0/public-domain avoids silently losing those
#: obligations when the private trace record is cleared.
_REUSABLE_LICENSE_RE = re.compile(
    r"(?:^|\W)cc0(?:\W|$)|public domain|(?:^|\W)pd(?:\W|$)",
    re.IGNORECASE,
)
#: Only real photographic raster formats. A bare image/ prefix admits djvu and
#: tiff page scans — a live query for a night street returned a 1918 novel's
#: cover scan, which traced into legible title lettering.
_PHOTO_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
_PIL_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
_MAX_PHOTO_BYTES = 12_000_000

#: Injectable fetcher so tests never touch the network: (url) -> bytes.
_FETCH: Callable[[str], bytes] | None = None


class SearchUnavailable(BackdropError):
    """A search REQUEST did not answer — a network error, a timeout, or a 429.

    Raised instead of returning no rows so the two facts stay apart: an empty list
    now means "the source answered and nothing it holds is usable", which is a
    statement about the subject, while this means "ask again later" and says nothing
    about the subject at all. Every source used to collapse both into ``[]``, which
    is why a rate-limited minute was indistinguishable from a world that genuinely
    has no attribution-free photograph — and why neither could be cached safely.
    """


#: How many search hits to sample from Commons before filtering. The photo ∩
#: attribution-free intersection is a small fraction of any result page, so a sample
#: sized to the number of candidates WANTED yields none: measured live, a four-word
#: village query returned ten pages whose every public-domain hit was a PDF or DjVu
#: page scan and whose every actual photograph was CC BY-SA. Widening the same
#: single request took a night-castle query from zero usable rows to ten.
_RAW_SEARCH_ROWS = 50

#: Added to every Commons search: its attribution-free material is largely scanned
#: books, and excluding them at the source leaves the sample for real photographs.
_BITMAP_ONLY = "filetype:bitmap"

#: A rephotographed DOCUMENT is not a reference photograph. The MIME gate cannot
#: catch one — a live castle query returned two handwritten letters and an
#: illuminated manuscript folio, as ordinary JPEGs, ABOVE the one real castle, and
#: the caller traces the first candidate that fetches. Traced, those become pages of
#: legible handwriting standing in for a place: worse than the procedural base,
#: because it is confidently wrong rather than merely plain.
_DOCUMENT_RE = re.compile(
    r"letters?\b|correspondence|manuscript|folio|codex|incunab|title pages?\b"
    r"|book scans?\b|scanned (?:book|page|document)|sheet music|musical scores?\b"
    r"|maps?\b|atlas|charters?\b|newspapers?\b|handwriting",
    re.IGNORECASE,
)

#: How much of a description to judge. The object names ITSELF at the front (the
#: letters above opened "Manuscript letter") and those files carried no telling
#: category at all, so categories alone are not enough. Reading only the lead keeps
#: an incidental mention further down ("carved letters above the arch") from
#: dropping a real photograph.
_DESCRIPTION_LEAD = 160


def _looks_like_document(*fields: str) -> bool:
    """True when the naming fields a source gives describe a reproduced document
    rather than a photograph of a place. Sources differ in what they expose, so each
    passes what it has: Commons its categories, object name and description lead;
    Openverse, the Met and the Smithsonian their title."""
    return bool(_DOCUMENT_RE.search(" ".join(f for f in fields if f)))


def _description_lead(raw: str) -> str:
    """The first `_DESCRIPTION_LEAD` characters of a description, tags stripped."""
    return re.sub(r"<[^>]+>", " ", raw)[:_DESCRIPTION_LEAD]


def _require_allowed_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_FETCH_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise BackdropError("reference images may be fetched only from an allowed archive")
    return url


class _AllowedHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _require_allowed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url: str) -> bytes:
    _require_allowed_url(url)
    if _FETCH is not None:
        return _FETCH(url)
    req = urllib.request.Request(url, headers={"User-Agent": "endless-worlds-backdrop/1.0"})
    opener = urllib.request.build_opener(_AllowedHostRedirectHandler())
    with opener.open(req, timeout=20) as resp:  # noqa: S310 — allowlisted HTTPS only
        _require_allowed_url(resp.geturl())
        return resp.read(_MAX_PHOTO_BYTES + 1)


def search_reference(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Attribution-free Commons candidates for a keyword query, best-first.

    Only bitmap files whose license short-name reads as CC0 or public domain are
    returned; everything else is dropped so attribution/share-alike obligations
    can never be silently lost from the composed backdrop. Book scans are excluded
    at the source (`_BITMAP_ONLY`) and the page sample is `_RAW_SEARCH_ROWS`, both
    because the surviving intersection is otherwise routinely empty.

    Raises :class:`SearchUnavailable` when the request itself does not answer.
    """
    search = query if _BITMAP_ONLY in query else f"{query} {_BITMAP_ONLY}"
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": search,
            "gsrnamespace": 6,
            "gsrlimit": _RAW_SEARCH_ROWS,
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 1200,
        }
    )
    try:
        data = json.loads(_http_get(f"{_COMMONS_API}?{params}").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — reported as unavailable, not as empty
        logger.warning("commons search failed: %s", exc)
        raise SearchUnavailable(f"commons search failed: {exc}") from exc
    rows: list[dict[str, str]] = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = str((meta.get("LicenseShortName") or {}).get("value", ""))
        if info.get("mime", "") not in _PHOTO_MIMES:
            continue
        if not _REUSABLE_LICENSE_RE.search(license_name):
            continue
        if _looks_like_document(
            str((meta.get("Categories") or {}).get("value", "")),
            str((meta.get("ObjectName") or {}).get("value", "")),
            _description_lead(str((meta.get("ImageDescription") or {}).get("value", ""))),
        ):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        rows.append(
            {
                "title": str(page.get("title", "")),
                "url": str(url),
                "pageUrl": str(info.get("descriptionurl", "")),
                "license": license_name,
            }
        )
        if len(rows) >= limit:
            break
    return rows


_OPENVERSE_API = "https://api.openverse.org/v1/images/"
_MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
_MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/"
_SI_SEARCH = "https://api.si.edu/openaccess/api/v1.0/search"


def search_openverse(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Attribution-free candidates from Openverse — the primary *photo* source.

    Openverse aggregates Wikimedia Commons, Flickr and museum feeds and filters
    server-side to CC0 + Public Domain Mark, so its usable pool dwarfs a
    Commons-only search. The fetchable ``url`` is Openverse's OWN thumbnail proxy
    (``api.openverse.org``), the single host we allowlist for it — image bytes
    never come from an un-vetted third-party CDN even when the original does.
    """
    params = urllib.parse.urlencode(
        {
            "q": query,
            "license": "cc0,pdm",
            "page_size": max(1, limit),
            "mature": "false",
        }
    )
    try:
        data = json.loads(_http_get(f"{_OPENVERSE_API}?{params}").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — reported as unavailable, not as empty
        logger.warning("openverse search failed: %s", exc)
        raise SearchUnavailable(f"openverse search failed: {exc}") from exc
    rows: list[dict[str, str]] = []
    for r in data.get("results") or []:
        lic = str(r.get("license", "")).lower()
        thumb = str(r.get("thumbnail") or "")
        if lic not in {"cc0", "pdm"} or not thumb:
            continue
        # Openverse exposes no categories, so the title is the whole descriptor.
        if _looks_like_document(str(r.get("title") or "")):
            continue
        try:
            _require_allowed_url(thumb)  # never fetch bytes off a raw CDN
        except BackdropError:
            continue
        rows.append(
            {
                "title": str(r.get("title") or r.get("id") or ""),
                "url": thumb,
                "pageUrl": str(r.get("foreign_landing_url", "")),
                "license": "CC0" if lic == "cc0" else "Public domain",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def search_met(query: str, limit: int = 5, probe: int = 12) -> list[dict[str, str]]:
    """Public-domain artworks from the Met — the *art* motif lane, not scene photos.

    Two-step (search ids, then per-object detail); only objects flagged
    ``isPublicDomain`` with an image are kept, and bytes come from
    ``images.metmuseum.org``. ``probe`` bounds how many objects are inspected so a
    broad query cannot fan out into an unbounded number of detail requests.
    """
    params = urllib.parse.urlencode({"q": query, "hasImages": "true"})
    try:
        data = json.loads(_http_get(f"{_MET_SEARCH}?{params}").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — reported as unavailable, not as empty
        logger.warning("met search failed: %s", exc)
        raise SearchUnavailable(f"met search failed: {exc}") from exc
    rows: list[dict[str, str]] = []
    for oid in (data.get("objectIDs") or [])[:probe]:
        try:
            obj = json.loads(_http_get(f"{_MET_OBJECT}{int(oid)}").decode("utf-8"))
        except Exception:  # noqa: BLE001 — skip one unreadable object, keep going
            continue
        img = str(obj.get("primaryImageSmall") or "")
        if not obj.get("isPublicDomain") or not img:
            continue
        # A manuscript page in the art lane traces into lettering just as it does
        # in the photo lane, so the same gate applies to an artwork's own title.
        if _looks_like_document(str(obj.get("title") or "")):
            continue
        try:
            _require_allowed_url(img)
        except BackdropError:
            continue
        rows.append(
            {
                "title": str(obj.get("title", "")),
                "url": img,
                "pageUrl": str(obj.get("objectURL", "")),
                "license": "Public domain",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def search_smithsonian(query: str, limit: int = 5) -> list[dict[str, str]]:
    """CC0 items from Smithsonian Open Access — an optional *art* lane source.

    Requires an ``SI_API_KEY`` (a free api.data.gov key); without it this source
    is inert so the art lane still works from the Met alone. NOTE: the response
    shape below is per the documented v1.0 Open Access API and is exercised only
    against a faked payload — it is not verified against the live service in CI.
    Only items whose usage flag is CC0 with an image on ``ids.si.edu`` are kept.
    """
    key = os.environ.get("SI_API_KEY")
    if not key:
        return []
    params = urllib.parse.urlencode(
        {
            "q": f"{query} AND online_media_type:Images",
            "rows": max(1, limit),
            "api_key": key,
        }
    )
    try:
        data = json.loads(_http_get(f"{_SI_SEARCH}?{params}").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — reported as unavailable, not as empty
        logger.warning("smithsonian search failed: %s", exc)
        raise SearchUnavailable(f"smithsonian search failed: {exc}") from exc
    rows: list[dict[str, str]] = []
    for row in (data.get("response") or {}).get("rows") or []:
        dnr = ((row.get("content") or {}).get("descriptiveNonRepeating")) or {}
        usage = str(((dnr.get("metadata_usage") or {}).get("access")) or "")
        if usage.upper() != "CC0":
            continue
        if _looks_like_document(str(row.get("title") or "")):
            continue
        img = ""
        for m in (dnr.get("online_media") or {}).get("media") or []:
            if str(m.get("type")) == "Images" and m.get("content"):
                img = str(m["content"])
                break
        if not img:
            continue
        try:
            _require_allowed_url(img)
        except BackdropError:
            continue
        rows.append(
            {
                "title": str(row.get("title", "")),
                "url": img,
                "pageUrl": str(dnr.get("record_link", "")),
                "license": "CC0",
            }
        )
        if len(rows) >= limit:
            break
    return rows


#: How many words a ladder rung keeps. Both search backends match CONJUNCTIVELY, so
#: a brief written the way the Illustrator is asked to write one — a REFERENCE line
#: of concrete keywords — matches nothing at all: measured live against Commons, an
#: 18-word river-mill brief returns ZERO hits while its first two words return
#: several. A specific brief therefore failed BECAUSE it was specific, on every
#: good-faith attempt.
#:
#: The rungs keep FRONT words, and it is worth being honest that this is the weaker
#: half of the fix. On the only two real briefs recorded, the front held the era
#: ("medieval European ...") and the photographable subject sat in the MIDDLE:
#: measured live, "thatched roofs", "stone keep", "walled town", "river valley" and
#: "watermill" each returned a full set of candidates on their own, and every one of
#: them was already inside a brief that returned nothing. Truncating from the front
#: never reaches them. The real remedy is upstream — the brief now declares its
#: `subject=` separately (see the narrator and illustrator contracts, and the tool's
#: own `query` description), and a total miss tells the Illustrator to retry with the
#: bare subject. The ladder stays as the backstop for when it does not.
#:
#: The ladder FLOORS at four words rather than bottoming out at two, and that floor
#: is the judgement: two words stop being about the subject — the river-mill brief's
#: two-word rung matched an amphora and a manuscript page — and an unrelated
#: photograph traced as the place is worse than the honest procedural base.
_LADDER_RUNGS = (6, 4)


#: A cached miss is only ever a miss for the CONFIGURATION that produced it. Fold
#: the license gate, the format gate, the document gate, the sample width, the rungs
#: and whether the key-gated art source is configured into one short digest, so
#: changing any of them retires every stale negative instead of silently answering
#: "no image" from a cache built under the old rules — the nastiest shape this
#: feature could take, because a fix would look like it had not worked.
def _search_fingerprint() -> str:
    material = "|".join(
        (
            _REUSABLE_LICENSE_RE.pattern,
            ",".join(sorted(_PHOTO_MIMES)),
            _DOCUMENT_RE.pattern,
            str(_DESCRIPTION_LEAD),
            str(_RAW_SEARCH_ROWS),
            _BITMAP_ONLY,
            ",".join(str(r) for r in _LADDER_RUNGS),
            "si" if os.environ.get("SI_API_KEY") else "no-si",
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _query_key(query: str) -> str:
    """The identity of a query for caching: its lowercased word SET, ordered.

    A set rather than the string, because both backends match conjunctively — word
    ORDER does not change which items match, so "castle tower night" and "night
    castle tower" have the same negative outcome and should not each pay for it.
    """
    words = {w for w in re.split(r"[^0-9a-z\u4e00-\u9fff]+", query.lower()) if w}
    return " ".join(sorted(words))


#: How long a recorded miss stands. The corpora GROW, so "this subject has no
#: attribution-free photograph" is true of a moment, not forever; a negative with no
#: expiry is a claim about the future that nothing would ever revisit.
_MISS_TTL_SECS = 14 * 24 * 3600

#: Bounded so the file cannot grow without limit; the oldest entries go first.
_MISS_CACHE_CAP = 500

#: Injectable clock, so a test can age an entry past its TTL without sleeping.
_NOW: Callable[[], float] = time.time


class MissCache:
    """Which (source, query) pairs answered with nothing usable, and when.

    Shared across runs and worlds — the point is that a subject with no
    attribution-free photograph should be discovered once, not once per page — and
    per SOURCE rather than per query, because Openverse missing while Commons hits
    is the normal case and a composite negative would throw that away.

    Only a genuine "answered, nothing usable" is ever recorded. A
    :class:`SearchUnavailable` is never cached: one rate-limited minute would
    otherwise mark a subject imageless for a fortnight.
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "search-misses.json"

    def _read(self) -> dict[str, float]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}

    @staticmethod
    def _key(source: str, query: str) -> str:
        return f"{_search_fingerprint()}|{source}|{_query_key(query)}"

    def missed(self, source: str, query: str) -> bool:
        at = self._read().get(self._key(source, query))
        return at is not None and (_NOW() - at) < _MISS_TTL_SECS

    def record(self, source: str, query: str) -> None:
        entries = {k: v for k, v in self._read().items() if (_NOW() - v) < _MISS_TTL_SECS}
        entries[self._key(source, query)] = _NOW()
        if len(entries) > _MISS_CACHE_CAP:
            for k, _ in sorted(entries.items(), key=lambda kv: kv[1])[
                : len(entries) - _MISS_CACHE_CAP
            ]:
                entries.pop(k, None)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(entries), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:  # a cache is an optimisation, never a failure path
            logger.warning("could not record a search miss: %s", exc)


def search_candidates(
    query: str,
    lane: str = "photo",
    limit: int = 5,
    misses: MissCache | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ordered, deduplicated candidates for a lane, plus an audit of how it went.

    ``photo`` (default): environmental scene references — Openverse first (the
    largest CC0/PDM pool), Wikimedia Commons as a fallback. ``art``: public-domain
    artworks as motif references — the Met, then the (key-gated) Smithsonian.

    Three things bound the request count, which matters because Wikimedia
    rate-limits a burst (an unbounded probe earned a 429 inside about twenty calls):
    a source is skipped when `misses` already holds a fresh negative for it, the
    source loop STOPS once ``limit`` candidates are in hand rather than always
    querying every source, and the query ladder stops at the first rung that
    matches.

    The audit names the outcome so a caller can record WHY it ended where it did:
    ``ok`` with the winning rung, ``no-candidates`` (every source answered and holds
    nothing usable for this subject) or ``search-failed`` (a source did not answer —
    ask again; this says nothing about the subject).
    """
    cache = misses
    sources: tuple[tuple[str, Callable[[str, int], list[dict[str, str]]]], ...] = (
        (("met", search_met), ("smithsonian", search_smithsonian))
        if lane == "art"
        else (("openverse", search_openverse), ("commons", search_reference))
    )
    words = query.split()
    attempts: list[dict[str, Any]] = []
    tried: list[str] = []
    unavailable = False

    for rung in (len(words), *_LADDER_RUNGS):
        step = " ".join(words[:rung]).strip()
        if not step or step in tried:
            continue
        tried.append(step)
        seen: set[str] = set()
        out: list[dict[str, str]] = []
        for name, src in sources:
            if cache is not None and cache.missed(name, step):
                attempts.append({"query": step, "source": name, "outcome": "cached-miss"})
                continue
            try:
                rows = src(step, limit)
            except SearchUnavailable:
                unavailable = True
                attempts.append({"query": step, "source": name, "outcome": "search-failed"})
                continue
            if not rows and cache is not None:
                cache.record(name, step)
            attempts.append(
                {
                    "query": step,
                    "source": name,
                    "outcome": "ok" if rows else "no-candidates",
                }
            )
            for cand in rows:
                if cand["url"] in seen:
                    continue
                seen.add(cand["url"])
                out.append(cand)
            # Enough to choose among: a further source would spend a request (and a
            # slice of the rate limit) on candidates nobody would reach.
            if len(out) >= limit:
                break
        if out:
            return out, {"reason": "ok", "matched": step, "attempts": attempts}

    # A request that never answered says nothing about the subject, so it outranks
    # "nothing usable" as the reported reason even when a later rung answered empty.
    return [], {
        "reason": "search-failed" if unavailable else "no-candidates",
        "matched": "",
        "attempts": attempts,
    }


def fetch_photo(url: str) -> bytes:
    raw = _http_get(url)
    if len(raw) > _MAX_PHOTO_BYTES:
        raise BackdropError("the reference photo is too large to trace")
    return raw


def _parse_ramp(ramp: list[str] | None) -> tuple[tuple[int, int, int], ...]:
    if not ramp:
        return NOCTURNE_RAMP
    stops: list[tuple[int, int, int]] = []
    for hexstr in ramp:
        m = re.fullmatch(r"#?([0-9a-fA-F]{6})", hexstr.strip())
        if not m:
            raise BackdropError(f"not a palette hex color: {hexstr!r}")
        v = m.group(1)
        stops.append((int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)))
    if not 3 <= len(stops) <= 8:
        raise BackdropError("a trace ramp needs 3 to 8 stops, darkest first")
    return tuple(stops)


def build_underlay_fragment(
    photo: bytes,
    *,
    view: tuple[int, int],
    ramp: list[str] | None = None,
    opacity: float = 0.65,
    focal: tuple[float, float] = (0.5, 0.5),
) -> str:
    """Trace one photo into a ``<g>`` fragment sized exactly to ``view``.

    Cover-crops to the view's aspect first, using that variant's own focal point,
    so desktop and mobile can frame the same source independently. The fragment
    needs no scale transform and its coordinates line up 1:1 with the
    Illustrator's overlay. The full-canvas background blob vtracer emits is
    dropped — the page's own sky sits beneath.
    """
    import vtracer  # local: motif lane needs no vtracer
    from PIL import Image, ImageFilter, ImageOps  # local: motif lane needs no PIL

    stops = _parse_ramp(ramp)
    fx, fy = float(focal[0]), float(focal[1])
    if not 0.0 <= fx <= 1.0 or not 0.0 <= fy <= 1.0:
        raise BackdropError("a trace focal point must stay between 0 and 1")
    with Image.open(io.BytesIO(photo)) as opened:
        if opened.format not in _PIL_FORMATS:
            raise BackdropError("the reference bytes are not a supported photograph")
        width, height = opened.size
        if (
            width <= 0
            or height <= 0
            or width > MAX_PHOTO_DIMENSION
            or height > MAX_PHOTO_DIMENSION
            or width * height > MAX_PHOTO_PIXELS
        ):
            raise BackdropError("the reference photo dimensions are too large to trace")
        img = opened.convert("RGB")
    img = ImageOps.fit(img, view, method=Image.Resampling.LANCZOS, centering=(fx, fy))
    g = ImageOps.autocontrast(img.convert("L")).filter(ImageFilter.GaussianBlur(1.6))
    median = sorted(g.getdata())[view[0] * view[1] // 2]
    if median < _DARK_MEDIAN:
        g = g.point(lambda v: int((v / 255) ** _DARK_GAMMA * 255))
    idx = g.point(lambda v: min(v * len(stops) // 256, len(stops) - 1))
    banded = Image.new("P", idx.size)
    banded.putdata(list(idx.getdata()))
    flat: list[int] = []
    for c in stops:
        flat += list(c)
    flat += list(stops[0]) * (256 - len(stops))
    banded.putpalette(flat)

    with tempfile.TemporaryDirectory(prefix="etr-") as tmp:
        pre = Path(tmp) / "pre.png"
        out = Path(tmp) / "trace.svg"
        banded.convert("RGB").save(pre)
        vtracer.convert_image_to_svg_py(
            str(pre),
            str(out),
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            filter_speckle=6,
            color_precision=6,
            layer_difference=32,
            corner_threshold=60,
            length_threshold=4.0,
            splice_threshold=45,
            path_precision=0,
        )
        paths = re.findall(r"<path [^>]*/>", out.read_text(encoding="utf-8"))
    if len(paths) < 2:
        raise BackdropError("the reference traced to nothing usable; try another query")
    body = "\n".join(paths[1:])
    if len(body) > MAX_TRACE_FRAGMENT_BYTES:
        raise BackdropError("the traced reference is too heavy; try a simpler photo")
    return f'<g opacity="{opacity:.2f}">\n{body}\n</g>'


def _trace_fragment_child(job_path: Path, output_path: Path) -> int:
    """Child entry point: decode/trace one variant and write only its SVG group."""
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        fragment = build_underlay_fragment(
            Path(job["photoPath"]).read_bytes(),
            view=(int(job["width"]), int(job["height"])),
            ramp=job.get("ramp"),
            opacity=float(job["opacity"]),
            focal=(float(job["focalX"]), float(job["focalY"])),
        )
        tmp = output_path.with_suffix(".tmp")
        tmp.write_text(fragment, encoding="utf-8")
        os.replace(tmp, output_path)
        return 0
    except Exception as exc:  # noqa: BLE001 — parent normalizes child failure
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def build_underlay_fragment_bounded(
    photo: bytes,
    *,
    view: tuple[int, int],
    ramp: list[str] | None = None,
    opacity: float = 0.65,
    focal: tuple[float, float] = (0.5, 0.5),
) -> str:
    """Trace one variant in a killable child and validate its bounded output."""
    if len(photo) > _MAX_PHOTO_BYTES:
        raise BackdropError("the reference photo is too large to trace")
    with tempfile.TemporaryDirectory(prefix="etr-parent-") as tmp_dir:
        root = Path(tmp_dir)
        photo_path = root / "photo.bin"
        job_path = root / "job.json"
        output_path = root / "fragment.svg"
        photo_path.write_bytes(photo)
        job_path.write_text(
            json.dumps(
                {
                    "photoPath": str(photo_path),
                    "width": int(view[0]),
                    "height": int(view[1]),
                    "ramp": ramp,
                    "opacity": float(opacity),
                    "focalX": float(focal[0]),
                    "focalY": float(focal[1]),
                }
            ),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--trace-fragment",
                    str(job_path),
                    str(output_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=TRACE_TIMEOUT_SECS,
            )
        except subprocess.TimeoutExpired:
            raise BackdropError(
                f"reference tracing timed out after {TRACE_TIMEOUT_SECS}s"
            ) from None
        except OSError as exc:
            raise BackdropError(
                f"reference trace worker could not start ({type(exc).__name__})"
            ) from None
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        if proc.returncode != 0 or not output_path.is_file():
            raise BackdropError(
                f"reference trace worker failed ({detail or 'no fragment produced'})"
            )
        if output_path.stat().st_size > MAX_TRACE_FRAGMENT_BYTES:
            raise BackdropError("the traced reference is too heavy; try a simpler photo")
        fragment = output_path.read_text(encoding="utf-8")
        width, height = view
        compile_backdrop(
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {width} {height}">{fragment}</svg>'
        )
        return fragment


def procedural_base_fragment(
    *,
    view: tuple[int, int],
    ramp: list[str] | None = None,
    opacity: float = 0.65,
) -> str:
    """A quiet tonal base for scenes with no photographic reference.

    Horizontal tonal bands from the ramp's dark end, deepening toward the
    bottom, with two soft off-center pools of the ramp's warmest stop — enough
    ground for the Illustrator to paint a scene over, asserting nothing itself.
    """
    stops = _parse_ramp(ramp)
    w, h = view
    dark = stops[: max(3, len(stops) - 2)]
    warm = stops[-1]
    band_h = h / len(dark)
    rects = [
        f'<rect x="0" y="{int(i * band_h)}" width="{w}" height="{int(band_h) + 2}" '
        f'fill="rgb({c[0]},{c[1]},{c[2]})" opacity="{0.5 + 0.5 * i / len(dark):.2f}"/>'
        for i, c in enumerate(dark)
    ]
    pools = (
        f'<ellipse cx="{int(w * 0.3)}" cy="{int(h * 0.78)}" rx="{int(w * 0.22)}" '
        f'ry="{int(h * 0.05)}" fill="rgb({warm[0]},{warm[1]},{warm[2]})" opacity="0.10"/>'
        f'<ellipse cx="{int(w * 0.72)}" cy="{int(h * 0.62)}" rx="{int(w * 0.14)}" '
        f'ry="{int(h * 0.04)}" fill="rgb({warm[0]},{warm[1]},{warm[2]})" opacity="0.07"/>'
    )
    return f'<g opacity="{opacity:.2f}">\n' + "\n".join(rects) + pools + "\n</g>"


def compose_with_underlay(
    svg: str, fragment: str | None, *, require_placeholder: bool = False
) -> str:
    """Splice the stored underlay into the Illustrator's placeholder.

    The placeholder marks WHERE in the paint order the underlay belongs (above
    the sky, below every mark). A placeholder with no stored fragment is a hard
    error — silently dropping it would publish art missing its foundation. Motif
    SVGs pass through only when no trace requires composition; once the SCENE lane
    has created a trace, each variant must carry exactly one placeholder.
    """
    count = len(_PLACEHOLDER_RE.findall(svg))
    if count == 0:
        if require_placeholder:
            raise BackdropError(
                "a traced scene needs exactly one etr-underlay placeholder in each SVG"
            )
        return svg
    if count != 1:
        raise BackdropError("a traced scene needs exactly one etr-underlay placeholder in each SVG")
    if not fragment:
        raise BackdropError(
            "this SVG carries an etr-underlay placeholder but no traced reference "
            "is stored for this page; call endless_trace_reference first"
        )
    composed = _PLACEHOLDER_RE.sub(lambda _: fragment, svg, count=1)
    if "etr-underlay" in composed:
        raise BackdropError("the etr-underlay placeholder was not fully composed")
    return composed


class TraceStore:
    """One page's traced underlay fragments, server-side only.

    Keyed like the draft store: one live entry per run, bound to a turn and an
    opaque id so a stale trace can never be spliced under a different page's
    art. Fragments never travel through the model's context.
    """

    def __init__(self, data_dir: Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not _ID_RE.match(run_id):
            raise BackdropError(f"not a run id: {run_id!r}")
        self._path = data_dir / "runs" / run_id / "trace-underlay.json"

    def save(
        self,
        *,
        turn: int,
        desktop: str,
        mobile: str,
        source: dict[str, str] | None,
        kind: str,
        query: str,
        search: dict[str, Any] | None = None,
    ) -> str:
        if kind not in {"reference", "base"}:
            raise BackdropError("a trace underlay kind must be reference or base")
        fragment_id = secrets.token_hex(8)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "fragmentId": fragment_id,
                    "turn": int(turn),
                    "desktop": desktop,
                    "mobile": mobile,
                    "source": source or None,
                    "kind": kind,
                    "query": str(query)[:500],
                    # Why the lane ended where it did, so the committed receipt can say
                    # whether a base underlay was a miss, a rate-limited request, or a page
                    # that asked for no photograph at all.
                    "search": search or None,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)
        return fragment_id

    def load(self, turn: int) -> dict[str, Any] | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or int(data.get("turn", -1)) != int(turn):
            return None
        return data

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)


class CandidateStore:
    """Traced reference candidates awaiting the Illustrator's pick, server-side only.

    ``endless_trace_reference`` traces the top few references and stashes them here
    (fragments never enter the model's context); ``endless_select_reference`` then
    promotes the chosen one into the active :class:`TraceStore` underlay. Bound to a
    run + turn exactly like :class:`TraceStore`, so a stale candidate set from an
    earlier page can never be selected onto a later one.
    """

    def __init__(self, data_dir: Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not _ID_RE.match(run_id):
            raise BackdropError(f"not a run id: {run_id!r}")
        self._path = data_dir / "runs" / run_id / "trace-candidates.json"

    def save(
        self,
        *,
        turn: int,
        query: str,
        candidates: list[dict[str, Any]],
        search: dict[str, Any] | None = None,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "turn": int(turn),
                    "query": str(query)[:500],
                    "candidates": candidates,
                    "search": search or None,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def load(self, turn: int) -> dict[str, Any] | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or int(data.get("turn", -1)) != int(turn):
            return None
        return data

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--trace-fragment":
        raise SystemExit(_trace_fragment_child(Path(sys.argv[2]), Path(sys.argv[3])))
    raise SystemExit("phototrace.py is a module; only --trace-fragment is runnable")
