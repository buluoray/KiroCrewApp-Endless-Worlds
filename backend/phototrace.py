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

Reference photos come only from Wikimedia Commons and are kept only when their
license is CC0 or public domain. When no usable reference exists — the brief
describes something no photo archive holds — the pipeline still earns
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
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from backdrop import BackdropError, _ID_RE, compile_backdrop

logger = logging.getLogger(__name__)

#: The nocturne ramp: near-black to dim gold, darkest first. Callers may pass a
#: world-specific ramp of the same shape (5-8 stops, darkest first).
NOCTURNE_RAMP: tuple[tuple[int, int, int], ...] = (
    (7, 8, 13), (11, 14, 23), (26, 28, 38), (58, 50, 28), (120, 95, 32), (201, 162, 39),
)

#: A composed backdrop (underlay + hand-drawn overlay) may reach this size; the
#: Illustrator's own hand-drawn input stays under the tool schema's 24KB.
MAX_TRACE_FRAGMENT_BYTES = 400_000

#: Pillow/vtracer execute in a killable child. One variant must finish within this
#: wall-clock bound so malformed or pathological photos cannot wedge the MCP loop.
TRACE_TIMEOUT_SECS = 30

#: Commons thumbnails are requested at 1200px. These broader hard ceilings catch a
#: forged response or decompression bomb before Pillow decodes its pixel payload.
MAX_PHOTO_PIXELS = 20_000_000
MAX_PHOTO_DIMENSION = 8_000
_ALLOWED_FETCH_HOSTS = frozenset({"commons.wikimedia.org", "upload.wikimedia.org"})

#: Below this median luminance a photo's pixels crowd the darkest bands and the
#: traced layer vanishes against a dark page; lift midtones first.
_DARK_MEDIAN = 90
_DARK_GAMMA = 0.55

_PLACEHOLDER_RE = re.compile(
    r"<g\s+id=(?P<quote>[\"'])etr-underlay(?P=quote)\s*(?:/>|>\s*</g>)"
)

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


def _require_wikimedia_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_FETCH_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise BackdropError("reference photos may be fetched only from Wikimedia")
    return url


class _WikimediaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _require_wikimedia_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url: str) -> bytes:
    _require_wikimedia_url(url)
    if _FETCH is not None:
        return _FETCH(url)
    req = urllib.request.Request(url, headers={"User-Agent": "endless-worlds-backdrop/1.0"})
    opener = urllib.request.build_opener(_WikimediaRedirectHandler())
    with opener.open(req, timeout=20) as resp:  # noqa: S310 — allowlisted HTTPS only
        _require_wikimedia_url(resp.geturl())
        return resp.read(_MAX_PHOTO_BYTES + 1)


def search_reference(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Attribution-free Commons candidates for a keyword query, best-first.

    Only bitmap files whose license short-name reads as CC0 or public domain are
    returned; everything else is dropped so attribution/share-alike obligations
    can never be silently lost from the composed backdrop.
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
        if not _REUSABLE_LICENSE_RE.search(license_name):
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
    opacity: float = 0.65, focal: tuple[float, float] = (0.5, 0.5),
) -> str:
    """Trace one photo into a ``<g>`` fragment sized exactly to ``view``.

    Cover-crops to the view's aspect first, using that variant's own focal point,
    so desktop and mobile can frame the same source independently. The fragment
    needs no scale transform and its coordinates line up 1:1 with the
    Illustrator's overlay. The full-canvas background blob vtracer emits is
    dropped — the page's own sky sits beneath.
    """
    from PIL import Image, ImageFilter, ImageOps  # local: motif lane needs no PIL

    import vtracer  # local: motif lane needs no vtracer

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
    img = ImageOps.fit(img, view, method=Image.LANCZOS, centering=(fx, fy))
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
    photo: bytes, *, view: tuple[int, int], ramp: list[str] | None = None,
    opacity: float = 0.65, focal: tuple[float, float] = (0.5, 0.5),
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
        job_path.write_text(json.dumps({
            "photoPath": str(photo_path),
            "width": int(view[0]),
            "height": int(view[1]),
            "ramp": ramp,
            "opacity": float(opacity),
            "focalX": float(focal[0]),
            "focalY": float(focal[1]),
        }), encoding="utf-8")
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
        raise BackdropError(
            "a traced scene needs exactly one etr-underlay placeholder in each SVG"
        )
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
        self, *, turn: int, desktop: str, mobile: str,
        source: dict[str, str] | None, kind: str, query: str,
    ) -> str:
        if kind not in {"reference", "base"}:
            raise BackdropError("a trace underlay kind must be reference or base")
        fragment_id = secrets.token_hex(8)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "fragmentId": fragment_id, "turn": int(turn),
            "desktop": desktop, "mobile": mobile, "source": source or None,
            "kind": kind, "query": str(query)[:500],
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


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--trace-fragment":
        raise SystemExit(_trace_fragment_child(Path(sys.argv[2]), Path(sys.argv[3])))
    raise SystemExit("phototrace.py is a module; only --trace-fragment is runnable")
