"""Agent-authored background art as an inert SVG image.

This is the ONE place the app accepts drawing markup from the narrator instead of
a declared spec (contrast ``widget.py``). It is safe because the markup is served
and shown as an **image** (`<img>`), never as a live document:

* an SVG loaded in an ``<img>`` runs in a NON-SCRIPTED context — ``<script>`` and
  ``on*=`` handlers never execute and external resource loads are disabled — so the
  narrator's SVG cannot run code or exfiltrate anything, with or without a sandbox;
* the page lays the image BEHIND the prose with ``pointer-events: none``, so a
  background that draws a fake control cannot be clicked or cover the real one.

An earlier version wrapped the markup in a sandboxed ``<iframe srcdoc>``. iOS
Safari blank-rendered that frame (empty-sandbox srcdoc, then size-collapse), which
showed as a flat grey background on iPhone. An ``<img>`` renders and sizes
reliably on every browser, so the visual bug and the whole sandbox/CSP surface
both go away — the image context is a stronger boundary than the sandbox was.

A background is decoration: SVG gradients, patterns, and filters. That is all it
needs, so the format is a single self-contained SVG document. Refused as defense
in depth (the image context already neuters them, but the narrator is told, not
silently stripped):

* ``<script>``, ``on*=`` handlers, ``javascript:`` — execution.
* ``<foreignObject>`` — it can embed arbitrary HTML/JS inside the SVG.
* ``<image>``/``<use>``/``href`` pointing off-box (``http(s):`` or protocol-relative)
  — an external fetch. Only self-contained drawing is allowed.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

#: A background is decoration, not a document — but a SCENE-lane background
#: carries a server-composed traced underlay (tens of KB of paths), so the
#: composed-document ceiling is generous. The Illustrator's own hand-drawn
#: input is separately capped at 24KB by the tool input schemas.
MAX_BACKDROP_BYTES = 1_000_000

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'

#: Substrings refused outright (scanned case-insensitively).
_FORBIDDEN_SUBSTRINGS = (
    "<script",
    "<foreignobject",
    "javascript:",
    "<iframe",
    "<html",
    "<body",
)

#: An inline event handler attribute (``onclick=``, ``onload=`` …). At least one
#: letter between ``on`` and ``=`` so ordinary attributes never match.
_HANDLER_RE = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)

#: Fast pre-parse rejection for obviously remote hrefs. The parsed-attribute gate in
#: ``compile_backdrop`` below is authoritative and rejects every non-fragment href,
#: including relative/file/data references, before a server-side renderer sees it.
_EXTERNAL_REF_RE = re.compile(r'(?:xlink:href|href)\s*=\s*["\']?\s*(?:https?:|//)', re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(([^)]*)\)", re.IGNORECASE)


class BackdropError(ValueError):
    """A background that cannot be used. Names what was wrong so the narrator can
    fix the one thing, rather than guessing."""


def _clean_trace_audit(raw: Any) -> dict[str, Any] | None:
    """Keep only a conclusive receipt that a trace underlay was composed.

    Rebuilt field by field rather than passed through, so a caller cannot widen the
    receipt by handing over extra keys. Two optional fields say WHY the lane ended
    where it did: ``fallback`` on a base underlay and ``matched`` on a reference one.
    Without them a base underlay is indistinguishable from a deliberate choice, and a
    lane that missed on every good-faith brief read as one nobody had asked for.
    """
    if not isinstance(raw, dict):
        return None
    pipeline = str(raw.get("pipeline") or "")
    underlay = str(raw.get("underlay") or "")
    fragment_id = str(raw.get("fragmentId") or "")
    if (
        pipeline != "trace"
        or underlay not in {"reference", "base"}
        or re.fullmatch(r"[0-9a-f]{16}", fragment_id) is None
        or raw.get("used") is not True
    ):
        return None
    clean: dict[str, Any] = {
        "pipeline": "trace",
        "underlay": underlay,
        "fragmentId": fragment_id,
        "query": str(raw.get("query") or "")[:500],
        "used": True,
    }
    fallback = raw.get("fallback")
    if underlay == "base" and isinstance(fallback, dict):
        clean["fallback"] = {
            # no-candidates: every source answered and holds nothing usable for this
            # subject. search-failed: a source did not answer — ask again, and this
            # says nothing about the subject. fetch-failed: candidates existed and
            # none became an underlay. cached-miss attempts name a negative that was
            # already known, so a reader can tell a skipped request from a spent one.
            "reason": str(fallback.get("reason") or "")[:40],
            "attempts": [
                {
                    "query": str(a.get("query") or "")[:200],
                    "source": str(a.get("source") or "")[:24],
                    "outcome": str(a.get("outcome") or "")[:24],
                }
                for a in (fallback.get("attempts") or [])[:8]
                if isinstance(a, dict)
            ],
        }
    matched = raw.get("matched")
    if underlay == "reference" and isinstance(matched, str) and matched.strip():
        clean["matched"] = matched[:200]
    return clean


def compile_backdrop(svg: str) -> str:
    """Validate narrator SVG and return it ready to serve as an image.

    The SVG is NOT escaped — it is authored art. Safety is the image context it is
    served into plus this denylist as defense in depth. A missing ``xmlns`` is
    injected rather than rejected, because a data/image-loaded SVG will not render
    without it and forgetting it is an easy mistake, not an attack.
    """
    if not isinstance(svg, str) or not svg.strip():
        raise BackdropError("a background needs an SVG image")

    size = len(svg.encode("utf-8"))
    if size > MAX_BACKDROP_BYTES:
        raise BackdropError(
            f"a background is at most {MAX_BACKDROP_BYTES} bytes, got {size}"
        )

    low = svg.lower()
    if "<svg" not in low:
        raise BackdropError(
            "a background must be a single SVG image (a <svg>…</svg> document)"
        )
    for banned in _FORBIDDEN_SUBSTRINGS:
        if banned in low:
            raise BackdropError(
                f"a background may not contain {banned!r} — it is a self-contained "
                "SVG drawing, never script, HTML, or a nested document"
            )
    if _HANDLER_RE.search(svg):
        raise BackdropError("a background may not carry an inline event handler (on…=)")
    if _EXTERNAL_REF_RE.search(svg):
        raise BackdropError(
            "a background may not link to an external resource — draw it inline"
        )

    # A data/image-loaded SVG needs the namespace declared on its root or it will
    # not render. Inject it when the narrator left it off the first <svg>.
    if "xmlns=" not in low[: low.index("<svg") + 200]:
        svg = re.sub(r"<svg\b", f"<svg {_SVG_NS}", svg, count=1, flags=re.IGNORECASE)

    # A very common narrator mistake: using an `xlink:` attribute (e.g. on a SMIL
    # <animate>) without declaring the xlink namespace. That is an UNDECLARED prefix,
    # which makes the SVG malformed XML — so an <img> cannot decode it and the player
    # sees a broken-image glyph instead of the emblem. Declare it for them rather
    # than reject art that is otherwise fine.
    if "xlink:" in low and "xmlns:xlink" not in low:
        svg = re.sub(
            r"<svg\b",
            '<svg xmlns:xlink="http://www.w3.org/1999/xlink"',
            svg, count=1, flags=re.IGNORECASE,
        )

    # Well-formedness is the last gate. The denylist above catches dangerous
    # content; this catches BROKEN content — an unclosed tag, a stray entity, a
    # prefix still undeclared — which renders as a broken image rather than a
    # picture. Rejecting here means a bad backdrop is refused at the call, and a bad
    # choice `art` is DROPPED by _clean_choices, so neither ever ships as a broken
    # glyph. Parsed after the injections above so a merely-missing xmlns is repaired,
    # not rejected.
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise BackdropError(f"the SVG is not well-formed and would not render ({exc})") from None

    # Server-side preview rendering has a stronger trust boundary than browser
    # <img>: a renderer may resolve relative paths or file: URLs. Permit only
    # same-document fragment references (plus the historical empty xlink href we
    # repair for compatibility). Embedded data, relative paths, and every scheme
    # are refused even though the final browser image context would neuter them.
    for element in root.iter():
        for attr, value in element.attrib.items():
            if attr.rsplit("}", 1)[-1].lower() != "href":
                continue
            ref = value.strip()
            if ref and not ref.startswith("#"):
                raise BackdropError(
                    "a background reference must stay inside this SVG (#id); "
                    "relative, data, file, and network resources are not allowed"
                )
    for match in _CSS_URL_RE.finditer(svg):
        ref = match.group(1).strip().strip("\"'").strip()
        if not ref.startswith("#"):
            raise BackdropError(
                "a background CSS url() must reference an element inside this SVG (#id)"
            )
    if "@import" in low:
        raise BackdropError("a background may not import CSS or any external resource")
    return svg


class _RsvgRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("width", ctypes.c_double),
        ("height", ctypes.c_double),
    ]


def _load_shared_library(name: str, fallbacks: tuple[str, ...]) -> ctypes.CDLL:
    candidates = [ctypes.util.find_library(name), *fallbacks]
    last: Exception | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ctypes.CDLL(candidate)
        except OSError as exc:
            last = exc
    raise OSError(f"shared library {name!r} is unavailable") from last


def _render_with_librsvg(svg: str, target: Path, width: int, height: int) -> None:
    """Rasterize one already-compiled SVG through librsvg into a bounded PNG."""
    rsvg = _load_shared_library(
        "rsvg-2", ("librsvg-2.so.2", "librsvg-2.dylib", "librsvg-2-2.dll")
    )
    cairo = _load_shared_library(
        "cairo", ("libcairo.so.2", "libcairo.2.dylib", "libcairo-2.dll")
    )
    gobject = _load_shared_library(
        "gobject-2.0",
        ("libgobject-2.0.so.0", "libgobject-2.0.0.dylib", "libgobject-2.0-0.dll"),
    )

    rsvg.rsvg_handle_new_from_data.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)
    ]
    rsvg.rsvg_handle_new_from_data.restype = ctypes.c_void_p
    rsvg.rsvg_handle_render_document.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_RsvgRectangle),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    rsvg.rsvg_handle_render_document.restype = ctypes.c_int
    cairo.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    cairo.cairo_image_surface_create.restype = ctypes.c_void_p
    cairo.cairo_surface_status.argtypes = [ctypes.c_void_p]
    cairo.cairo_surface_status.restype = ctypes.c_int
    cairo.cairo_create.argtypes = [ctypes.c_void_p]
    cairo.cairo_create.restype = ctypes.c_void_p
    cairo.cairo_status.argtypes = [ctypes.c_void_p]
    cairo.cairo_status.restype = ctypes.c_int
    cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    cairo.cairo_surface_write_to_png.restype = ctypes.c_int
    cairo.cairo_destroy.argtypes = [ctypes.c_void_p]
    cairo.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
    gobject.g_object_unref.argtypes = [ctypes.c_void_p]

    raw = svg.encode("utf-8")
    buf = ctypes.create_string_buffer(raw)
    error = ctypes.c_void_p()
    handle = rsvg.rsvg_handle_new_from_data(buf, len(raw), ctypes.byref(error))
    if not handle:
        raise BackdropError("the safe SVG renderer could not decode this draft")

    surface = ctypes.c_void_p()
    drawing = ctypes.c_void_p()
    try:
        surface = cairo.cairo_image_surface_create(0, width, height)  # ARGB32
        if not surface or cairo.cairo_surface_status(surface) != 0:
            raise BackdropError("the safe SVG renderer could not allocate a thumbnail")
        drawing = cairo.cairo_create(surface)
        if not drawing or cairo.cairo_status(drawing) != 0:
            raise BackdropError("the safe SVG renderer could not start a thumbnail")
        viewport = _RsvgRectangle(0.0, 0.0, float(width), float(height))
        error = ctypes.c_void_p()
        if not rsvg.rsvg_handle_render_document(
            handle, drawing, ctypes.byref(viewport), ctypes.byref(error)
        ):
            raise BackdropError("the safe SVG renderer refused this draft")
        if cairo.cairo_surface_write_to_png(surface, os.fsencode(target)) != 0:
            raise BackdropError("the safe SVG renderer could not write its thumbnail")
    finally:
        if drawing:
            cairo.cairo_destroy(drawing)
        if surface:
            cairo.cairo_surface_destroy(surface)
        gobject.g_object_unref(handle)


#: Wall-clock bound on ONE thumbnail render, whichever backend serves it. The
#: render runs in a killable child process because a pathological (never
#: malicious — already compile-gated) SVG can make cairo rasterization spin
#: arbitrarily long, and an in-process C call cannot be interrupted.
RENDER_TIMEOUT_SECS = 20


def _render_thumbnail_backends(svg: str, tmp: Path, width: int, height: int) -> list[str]:
    """Try each local renderer in turn; return the per-backend error trail.

    CairoSVG and ``rsvg-convert`` are optional compatibility paths; the app's Linux
    runtime normally reaches librsvg directly through ``ctypes`` and needs no Python
    package. Every backend receives only the already-compiled, off-box-reference-free
    SVG. Runs inside the render child process, never in the gateway process.
    """
    errors: list[str] = []
    try:
        import cairosvg  # type: ignore[import-not-found]  # optional runtime

        cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            write_to=str(tmp),
            output_width=width,
            output_height=height,
            unsafe=False,
        )
    except Exception as exc:  # noqa: BLE001 — try the next local renderer
        errors.append(f"CairoSVG:{type(exc).__name__}")
        tmp.unlink(missing_ok=True)

    converter = shutil.which("rsvg-convert")
    if not tmp.is_file() and converter:
        try:
            subprocess.run(
                [
                    converter,
                    "--width", str(width),
                    "--height", str(height),
                    "--output", str(tmp),
                ],
                input=svg.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
                timeout=RENDER_TIMEOUT_SECS,
            )
        except Exception as exc:  # noqa: BLE001 — try direct librsvg
            errors.append(f"rsvg-convert:{type(exc).__name__}")
            tmp.unlink(missing_ok=True)

    if not tmp.is_file():
        try:
            _render_with_librsvg(svg, tmp, width, height)
        except Exception as exc:  # noqa: BLE001 — normalized by the caller
            errors.append(f"librsvg:{type(exc).__name__}")
            tmp.unlink(missing_ok=True)
    return errors


def _render_thumbnail_child(argv: list[str]) -> int:
    """The render child's entry point: SVG on stdin, PNG at the target path.

    Exit status is advisory only — the parent trusts the PNG signature check,
    never the child's word.
    """
    width, height, target = int(argv[0]), int(argv[1]), Path(argv[2])
    svg = sys.stdin.read()
    errors = _render_thumbnail_backends(svg, target, width, height)
    if not target.is_file():
        print(", ".join(errors) or "no renderer produced a PNG", file=sys.stderr)
        return 1
    return 0


def _render_svg_thumbnail(svg: str, target: Path, width: int, height: int) -> None:
    """Render a compiled SVG to a small PNG without allowing network/file input.

    The renderer chain runs in a separate Python process bounded by
    ``RENDER_TIMEOUT_SECS``, so a render that wedges (deep filter stacks can make
    cairo spin) is killed instead of hanging the MCP server. The PNG signature and
    dimensions are checked here, in the parent, before the draft can be read.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".png.tmp")
    detail = ""

    try:
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--render-thumbnail", str(width), str(height), str(tmp),
                ],
                input=svg.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=RENDER_TIMEOUT_SECS,
            )
            detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        except subprocess.TimeoutExpired:
            raise BackdropError(
                f"backdrop preview rendering timed out after {RENDER_TIMEOUT_SECS}s"
            ) from None
        except OSError as exc:
            detail = f"render child failed to start: {type(exc).__name__}"

        try:
            header = tmp.read_bytes()[:24]
        except OSError:
            header = b""
        if (
            not header.startswith(b"\x89PNG\r\n\x1a\n")
            or len(header) < 24
            or int.from_bytes(header[16:20], "big") != width
            or int.from_bytes(header[20:24], "big") != height
        ):
            raise BackdropError(
                "safe backdrop preview rendering is unavailable "
                f"({detail or 'no renderer produced a PNG'})"
            )
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


class BackdropDraftStore:
    """One unpublished Illustrator draft and its safe raster thumbnails.

    Drafts live beside but never inside ``backdrop.json``. Runtime routes read only
    :class:`BackdropStore`, so a draft cannot leak into live play, chronicle history,
    or shelf thumbnails. A reviewed revision or newer recovery attempt replaces the
    stale draft. The opaque id binds the eventual final commit to the latest preview
    the Illustrator was asked to inspect.
    """

    def __init__(self, data_dir: Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not _ID_RE.match(run_id):
            raise BackdropError(f"not a run id: {run_id!r}")
        run_dir = data_dir / "runs" / run_id
        self._path = run_dir / "backdrop-draft.json"
        self._preview_dir = run_dir / "backdrop-previews"

    def _load(self) -> dict[str, Any] | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        if not isinstance(data.get("draftId"), str) or not isinstance(data.get("turn"), int):
            return None
        return data

    def _save(self, draft: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def _remove_previews(self, draft: dict[str, Any] | None) -> None:
        previews = draft.get("previews") if isinstance(draft, dict) else None
        if not isinstance(previews, dict):
            return
        expected_parent = self._preview_dir.resolve()
        for value in previews.values():
            if not isinstance(value, str):
                continue
            path = Path(value)
            try:
                if (
                    path.resolve().parent == expected_parent
                    and path.name.startswith("backdrop-preview-")
                    and path.suffix == ".png"
                ):
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    def submit(
        self,
        markup: str,
        mobile: str,
        *,
        turn: int,
        buttons: str | None = None,
    ) -> dict[str, Any]:
        """Validate all draft SVGs, then atomically expose only raster previews."""
        clean_markup = compile_backdrop(markup)
        clean_mobile = compile_backdrop(mobile)
        clean_buttons = (
            compile_backdrop(buttons)
            if isinstance(buttons, str) and buttons.strip()
            else None
        )

        draft_id = secrets.token_hex(12)
        previews: dict[str, str] = {}
        specs = [
            ("desktop", clean_markup, 400, 300),
            ("mobile", clean_mobile, 150, 300),
        ]
        if clean_buttons:
            specs.append(("buttons", clean_buttons, 240, 80))
        created: list[Path] = []
        try:
            for label, svg, width, height in specs:
                path = self._preview_dir / f"backdrop-preview-{draft_id}-{label}.png"
                _render_svg_thumbnail(svg, path, width, height)
                created.append(path)
                previews[label] = str(path.resolve())
            draft = {"draftId": draft_id, "turn": int(turn), "previews": previews}
            old = self._load()
            self._save(draft)
            self._remove_previews(old)
            return draft
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    def require(self, draft_id: str, turn: int) -> dict[str, Any]:
        draft = self._load()
        if not draft:
            raise BackdropError("submit and visually review a backdrop draft before publishing")
        if draft.get("draftId") != draft_id or int(draft.get("turn") or 0) != int(turn):
            raise BackdropError("this final backdrop does not match the current reviewed draft")
        return draft

    def discard(self, draft_id: str, turn: int) -> None:
        draft = self.require(draft_id, turn)
        self._remove_previews(draft)
        self._path.unlink(missing_ok=True)


class BackdropStore:
    """One run's current background, persisted as a single JSON file.

    Like the scene ledger, this is a handle that can reach exactly one file and
    nothing else: a backdrop call can never touch panels, chronicle, or facts,
    because it is never handed anything that could. A run has at most one
    background at a time — setting a new one replaces the old.
    """

    def __init__(self, data_dir: Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not _ID_RE.match(run_id):
            raise BackdropError(f"not a run id: {run_id!r}")
        self._path = data_dir / "runs" / run_id / "backdrop.json"

    def _load(self) -> list[dict[str, Any]]:
        """The backdrop history, oldest-first. Each entry is
        ``{turn, markup, mobile?, buttons?, version, source?, trace?}``; an entry with
        empty ``markup`` is a tombstone (the narrator cleared the background at that
        turn). Migrates the old single-object format to a one-entry history, and
        treats a corrupt file as no history rather than an error that would break
        the play view."""
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if isinstance(data, dict) and isinstance(data.get("history"), list):
            entries = data["history"]
        elif isinstance(data, dict) and isinstance(data.get("markup"), str):
            # Pre-history format: one current backdrop. Treat it as set at turn 0.
            entries = [dict(data, turn=0)]
        else:
            return []
        out: list[dict[str, Any]] = []
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("version"), int):
                out.append(e)
        return out

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"history": entries}, ensure_ascii=False)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)

    @staticmethod
    def _view(entry: dict[str, Any] | None) -> dict[str, Any] | None:
        """Shape a public backdrop entry, or ``None`` for a tombstone/missing row."""
        if not entry:
            return None
        markup = entry.get("markup")
        version = entry.get("version")
        if not isinstance(markup, str) or not markup.strip() or not isinstance(version, int):
            return None
        mobile = entry.get("mobile")
        buttons = entry.get("buttons")
        raw_source = entry.get("source")
        source = None
        if isinstance(raw_source, dict):
            candidate = {
                key: str(raw_source.get(key) or "")
                for key in ("title", "pageUrl", "license")
            }
            if candidate["pageUrl"] and candidate["license"]:
                source = candidate
        trace = _clean_trace_audit(entry.get("trace"))
        return {
            "markup": markup,
            "mobile": mobile if isinstance(mobile, str) and mobile.strip() else None,
            "version": version,
            "buttons": buttons if isinstance(buttons, str) and buttons.strip() else None,
            "source": source,
            "trace": trace,
        }

    def current(self) -> dict[str, Any] | None:
        """The LATEST background as ``{markup, mobile, buttons, version}``, or ``None`` when
        unset/cleared/unreadable. This is what the home shelf and the live play page
        want — the most recent scene."""
        history = self._load()
        return self._view(history[-1]) if history else None

    def at(self, turn: int) -> dict[str, Any] | None:
        """The background effective on ``turn`` — the latest one set at a turn ≤ it,
        since a backdrop persists until the narrator changes it. ``None`` if the page
        predates any backdrop, or the effective one is a tombstone (cleared)."""
        chosen: dict[str, Any] | None = None
        for e in self._load():
            if int(e.get("turn") or 0) <= turn:
                chosen = e
            else:
                break
        return self._view(chosen)

    def exact(self, turn: int) -> dict[str, Any] | None:
        """The background explicitly committed for ``turn``, not an inherited one.

        Atomic page reveal needs this stricter question: ``at(turn)`` may return the
        previous page's still-effective art, which does not prove that an illustrator
        finished the new page the narrator explicitly briefed.
        """
        for entry in reversed(self._load()):
            entry_turn = int(entry.get("turn") or 0)
            if entry_turn == int(turn):
                return self._view(entry)
            if entry_turn < int(turn):
                break
        return None

    def version_at(self, turn: int) -> int:
        """The version effective on ``turn`` (0 when the page has no background). Used
        to stamp each chronicle turn so the history reader restores that page's
        scene and caches it correctly."""
        view = self.at(turn)
        return int(view["version"]) if view else 0

    def set(
        self, markup: str, buttons: str | None = None, turn: int = 0,
        mobile: str | None = None, source: dict[str, str] | None = None,
        trace: dict[str, Any] | None = None,
    ) -> int:
        """Validate and append coordinated desktop/mobile backgrounds (and the
        optional common button motif),
        stamped with the ``turn`` it belongs to, returning the version.

        Bound to the page: re-reading turn N restores the background set at N (or the
        latest before it). Setting twice on the same turn replaces that page's entry
        rather than stacking two. Both SVGs are validated here so the narrator is
        refused at the call it made, not later at render — a rejected background never
        becomes stored — and the button motif travels WITH the backdrop, so a page's
        buttons always match its scene. The mobile variant is validated and stored
        atomically with desktop; legacy single-image entries simply expose no mobile.
        """
        clean_markup = compile_backdrop(markup)  # raises BackdropError on bad input
        clean_buttons = (
            compile_backdrop(buttons)
            if isinstance(buttons, str) and buttons.strip()
            else None
        )
        clean_mobile = (
            compile_backdrop(mobile)
            if isinstance(mobile, str) and mobile.strip()
            else None
        )
        clean_source = None
        if isinstance(source, dict):
            candidate = {
                key: str(source.get(key) or "")[:500]
                for key in ("title", "pageUrl", "license")
            }
            if candidate["pageUrl"] and candidate["license"]:
                clean_source = candidate
        clean_trace = _clean_trace_audit(trace)
        history = self._load()
        version = (max(int(e.get("version") or 0) for e in history) + 1) if history else 1
        entry: dict[str, Any] = {"turn": int(turn), "markup": clean_markup, "version": version}
        if clean_mobile:
            entry["mobile"] = clean_mobile
        if clean_buttons:
            entry["buttons"] = clean_buttons
        if clean_source:
            entry["source"] = clean_source
        if clean_trace:
            entry["trace"] = clean_trace
        if history and int(history[-1].get("turn") or 0) == int(turn):
            history[-1] = entry  # a second set on the same page replaces it
        else:
            history.append(entry)
        self._save(history)
        return version

    def clear(self, turn: int = 0) -> None:
        """Clear the background FROM this turn onward, keeping earlier pages' scenes.

        Recorded as a tombstone rather than deleting the file, so re-reading a page
        before the clear still restores its backdrop while the live page and home
        show none. Idempotent — clearing when nothing is showing on this page is a
        no-op."""
        history = self._load()
        if self.at(turn) is None:
            return  # nothing effective here to clear
        version = max(int(e.get("version") or 0) for e in history) + 1
        tomb: dict[str, Any] = {"turn": int(turn), "markup": "", "version": version}
        if int(history[-1].get("turn") or 0) == int(turn):
            history[-1] = tomb
        else:
            history.append(tomb)
        self._save(history)



if __name__ == "__main__":  # the render child — see _render_svg_thumbnail
    if len(sys.argv) == 5 and sys.argv[1] == "--render-thumbnail":
        raise SystemExit(_render_thumbnail_child(sys.argv[2:]))
    raise SystemExit("backdrop.py is a module; only --render-thumbnail is runnable")
