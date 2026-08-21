"""Photo-reference underlays for scene backdrops.

The SCENE lane's foundation: a free-licensed reference photograph is traced into
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

Reference photos come only from Wikimedia Commons and are kept only when their
license reads as free (CC or public domain). When no usable reference exists —
the brief describes something no photo archive holds — the pipeline still earns
its keep by producing a procedural tonal base (:func:`procedural_base_fragment`)
for the Illustrator to paint over.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from backdrop import BackdropError, _ID_RE

logger = logging.getLogger(__name__)

#: The nocturne ramp: near-black to dim gold, darkest first. Callers may pass a
#: world-specific ramp of the same shape (5-8 stops, darkest first).
NOCTURNE_RAMP: tuple[tuple[int, int, int], ...] = (
    (7, 8, 13), (11, 14, 23), (26, 28, 38), (58, 50, 28), (120, 95, 32), (201, 162, 39),
)

#: A composed backdrop (underlay + hand-drawn overlay) may reach this size; the
#: Illustrator's own hand-drawn input stays under the tool schema's 24KB.
MAX_TRACE_FRAGMENT_BYTES = 400_000

#: Below this median luminance a photo's pixels crowd the darkest bands and the
#: traced layer vanishes against a dark page; lift midtones first.
_DARK_MEDIAN = 90
_DARK_GAMMA = 0.55

_PLACEHOLDER_RE = re.compile(r'<g\s+id="etr-underlay"\s*(?:/>|>\s*</g>)')

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
#: Accepts CC family (including CC0 — no word boundary exists between "cc" and
#: "0", so a plain \bcc\b wrongly rejects the freest license), Creative Commons
#: spelled out, and public-domain markers.
_FREE_LICENSE_RE = re.compile(
    r"(?:^|\W)cc(?:0|[- ]|$)|creative commons|public domain|(?:^|\W)pd(?:\W|$)",
    re.IGNORECASE,
)
#: Only real photographic raster formats. A bare image/ prefix admits djvu and
#: tiff page scans — a live query for a night street returned a 1918 novel's
#: cover scan, which traced into legible title lettering.
_PHOTO_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
_MAX_PHOTO_BYTES = 12_000_000

#: Injectable fetcher so tests never touch the network: (url) -> bytes.
_FETCH: Callable[[str], bytes] | None = None


def _http_get(url: str) -> bytes:
    if _FETCH is not None:
        return _FETCH(url)
    req = urllib.request.Request(url, headers={"User-Agent": "endless-worlds-backdrop/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — https Commons only
        return resp.read(_MAX_PHOTO_BYTES + 1)


def search_reference(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Free-licensed Commons candidates for a keyword query, best-first.

    Only bitmap files whose license short-name reads as CC or public domain are
    returned; everything else is dropped so an unusable license can never reach
    the composed backdrop.
    """
    params = urllib.parse.urlencode({
        "action": "query", "format": "json",
        "generator": "search", "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": limit * 2,
        "prop": "imageinfo", "iiprop": "url|mime|extmetadata", "iiurlwidth": 1200,
    })
    try:
        data = json.loads(_http_get(f"{_COMMONS_API}?{params}").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — the caller degrades to the base lane
        logger.warning("commons search failed: %s", exc)
        return []
    rows: list[dict[str, str]] = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = str((meta.get("LicenseShortName") or {}).get("value", ""))
        if info.get("mime", "") not in _PHOTO_MIMES:
            continue
        if not _FREE_LICENSE_RE.search(license_name):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        rows.append({
            "title": str(page.get("title", "")),
            "url": str(url),
            "pageUrl": str(info.get("descriptionurl", "")),
            "license": license_name,
        })
        if len(rows) >= limit:
            break
    return rows


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
    photo: bytes, *, view: tuple[int, int], ramp: list[str] | None = None,
    opacity: float = 0.65,
) -> str:
    """Trace one photo into a ``<g>`` fragment sized exactly to ``view``.

    Cover-crops to the view's aspect first, so the fragment needs no scale
    transform and its coordinates line up 1:1 with the Illustrator's overlay.
    The full-canvas background blob vtracer emits is dropped — the page's own
    sky sits beneath.
    """
    from PIL import Image, ImageFilter, ImageOps  # local: pattern lane needs no PIL

    import vtracer  # local: pattern lane needs no vtracer

    stops = _parse_ramp(ramp)
    img = Image.open(io.BytesIO(photo)).convert("RGB")
    img = ImageOps.fit(img, view, method=Image.LANCZOS)
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
            str(pre), str(out), colormode="color", hierarchical="stacked",
            mode="spline", filter_speckle=6, color_precision=6, layer_difference=32,
            corner_threshold=60, length_threshold=4.0, splice_threshold=45,
            path_precision=0,
        )
        paths = re.findall(r"<path [^>]*/>", out.read_text(encoding="utf-8"))
    if len(paths) < 2:
        raise BackdropError("the reference traced to nothing usable; try another query")
    body = "\n".join(paths[1:])
    if len(body) > MAX_TRACE_FRAGMENT_BYTES:
        raise BackdropError("the traced reference is too heavy; try a simpler photo")
    return f'<g opacity="{opacity:.2f}">\n{body}\n</g>'


def procedural_base_fragment(
    *, view: tuple[int, int], ramp: list[str] | None = None, opacity: float = 0.65,
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


def compose_with_underlay(svg: str, fragment: str | None) -> str:
    """Splice the stored underlay into the Illustrator's placeholder.

    The placeholder marks WHERE in the paint order the underlay belongs (above
    the sky, below every mark). A placeholder with no stored fragment is a hard
    error — silently dropping it would publish art missing its foundation. A
    document without a placeholder passes through untouched, so the pattern
    lane never pays for this feature.
    """
    has_placeholder = _PLACEHOLDER_RE.search(svg) is not None
    if not has_placeholder:
        return svg
    if not fragment:
        raise BackdropError(
            "this SVG carries an etr-underlay placeholder but no traced reference "
            "is stored for this page; call endless_trace_reference first"
        )
    return _PLACEHOLDER_RE.sub(lambda _: fragment, svg, count=1)


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
        self, *, turn: int, desktop: str, mobile: str, source: dict[str, str] | None,
    ) -> str:
        fragment_id = secrets.token_hex(8)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "fragmentId": fragment_id, "turn": int(turn),
            "desktop": desktop, "mobile": mobile, "source": source or None,
        }, ensure_ascii=False), encoding="utf-8")
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
