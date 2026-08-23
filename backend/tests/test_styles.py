"""Painterly STYLE routing: header parsing, the scene-gate opt-out, the spawn
task's skill injection, and the filter-faithful preview renderer order."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent


@pytest.fixture()
def data(tmp_path, monkeypatch):
    import mcp_server as srv

    monkeypatch.setattr(srv, "_DATA", tmp_path)
    return tmp_path


def test_brief_style_is_parsed_leniently() -> None:
    """`STYLE:` follows `LANE:`'s lenient contract: odd spellings and unknown
    styles become "" rather than a refusal — losing a page's art over a header
    is worse than not enforcing it on that one page."""
    from store import brief_style

    assert brief_style("LANE: scene\nSTYLE: watercolor\nx") == "watercolor"
    assert brief_style("style:  OIL  \nx") == "oil"
    assert brief_style("STYLE: minimal") == "minimal"
    assert brief_style("STYLE: photo") == "photo"
    assert brief_style("STYLE: gouache") == "", "unknown styles degrade to no style"
    assert brief_style("a watercolor mood") == "", "prose is not a declaration"
    assert brief_style("") == ""


def test_request_backdrop_stores_the_style_beside_the_lane(data, monkeypatch) -> None:
    """The style is parsed once, at request time, exactly like the lane — the brief
    is cleared on commit, so the record is the only place the intent survives."""
    import mcp_server as srv

    store = srv._store()
    run_id = "d" * 32
    store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    store.request_backdrop(run_id, turn=1, brief="LANE: scene\nSTYLE: watercolor\nA river garden.")
    request = store.read_backdrop_request(run_id)
    assert request["lane"] == "scene"
    assert request["style"] == "watercolor"


@pytest.mark.parametrize("style", ["watercolor", "oil", "minimal"])
def test_a_painterly_style_frees_a_scene_from_the_trace_gate(data, monkeypatch, style) -> None:
    """A brief that declares a painterly STYLE opts out of the photo pipeline by
    design: the scene is hand-drawn in that style, so the gate must not force a
    trace the narrator explicitly routed around."""
    import mcp_server as srv
    from tests.test_phototrace import _call

    store = srv._store()
    run_id = "e" * 32
    store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    store.request_backdrop(run_id, turn=1, brief=f"LANE: scene\nSTYLE: {style}\nA hill town.")

    plain = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    out = _call("endless_submit_backdrop_draft", runId=run_id, turn=1, markup=plain, mobile=plain)
    assert out["ok"] is True, out


def test_the_photo_style_still_requires_the_trace_lane(data, monkeypatch) -> None:
    """`STYLE: photo` names the traced-photograph pipeline explicitly, so the
    scene gate keeps its full force there — as it does for a style-less scene
    brief, which keeps its historical meaning."""
    import mcp_server as srv
    from tests.test_phototrace import _call

    store = srv._store()
    run_id = "f" * 32
    store.create_run({"turn": 1, "worldId": "w"}, {"runId": "r1"})
    store.request_backdrop(
        run_id, turn=1, brief='LANE: scene\nSTYLE: photo\nREFERENCE: subject="stone bridge"'
    )

    plain = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    out = _call("endless_submit_backdrop_draft", runId=run_id, turn=1, markup=plain, mobile=plain)
    assert out["ok"] is False
    assert "declared LANE: scene" in out["error"]


def test_style_directive_names_an_existing_skill_file() -> None:
    """The spawn task hands the illustrator the ABSOLUTE path of the style's skill
    file (the static agent prompt cannot know the install dir). The path must exist
    in the shipped app for every declared style, and the directive must teach the
    ranges-not-constants contract."""
    from routes import _STYLE_SKILLS, _style_directive

    for style in ("watercolor", "oil", "minimal"):
        directive = _style_directive(style)
        assert f"STYLE: {style}" in directive
        assert "RANGES" in directive
        path_str = directive.split("read ", 1)[1].split(" with the read tool")[0]
        skill = Path(path_str)
        assert skill.is_file(), f"style skill missing on disk: {skill}"
        assert skill.name == "SKILL.md"
        assert _STYLE_SKILLS[style] == skill.parent.name

    assert _style_directive("photo") == "", "photo's skill is the trace tool chain"
    assert _style_directive("") == ""


def test_every_style_skill_teaches_ranges_and_matte_oil() -> None:
    """The skills carry the user's art direction: parameter RANGES with a
    look-and-adjust loop (never fixed constants), and the oil style is matte —
    no specular pass, ever."""
    core = (REPO / "skills" / "svg-style-core" / "SKILL.md").read_text()
    assert "look-and-adjust" in core.lower() or "look at" in core.lower()
    assert "solid" in core.lower()

    wc = (REPO / "skills" / "svg-style-watercolor" / "SKILL.md").read_text()
    assert "ranges" in wc.lower()
    assert "feDisplacementMap" in wc

    oil = (REPO / "skills" / "svg-style-oil" / "SKILL.md").read_text()
    assert "feSpecularLighting" in oil, "the ban must be named to be teachable"
    assert "NO gloss" in oil or "no gloss" in oil.lower()
    assert "matte" in oil.lower()

    minimal = (REPO / "skills" / "svg-style-minimal" / "SKILL.md").read_text()
    assert "negative space" in minimal.lower()


def test_preview_renderers_run_librsvg_before_cairosvg(monkeypatch, tmp_path) -> None:
    """The preview chain is ordered by FILTER FIDELITY: librsvg implements the
    painterly filter primitives (feTurbulence/feDisplacementMap); CairoSVG silently
    skips them, rendering every painterly style as the same flat vector — an
    illustrator reviewing such a preview would tune its brush parameters blind.
    When librsvg succeeds, CairoSVG must not run at all."""
    import backdrop as bd

    calls: list[str] = []

    def fake_librsvg(svg: str, target: Path, width: int, height: int) -> None:
        calls.append("librsvg")
        target.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(bd, "_render_with_librsvg", fake_librsvg)
    # Any cairosvg import attempt would append here via a poisoned module.
    import sys

    class _Poison:
        def __getattr__(self, name: str):  # noqa: ANN204
            calls.append("cairosvg")
            raise AssertionError("CairoSVG must not run when librsvg succeeded")

    monkeypatch.setitem(sys.modules, "cairosvg", _Poison())

    tmp = tmp_path / "out.png"
    errors = bd._render_thumbnail_backends("<svg xmlns='x'/>", tmp, 40, 50)
    assert calls == ["librsvg"]
    assert errors == []
    assert tmp.is_file()


def test_preview_renderers_fall_back_to_cairosvg_last(monkeypatch, tmp_path) -> None:
    """Hosts without librsvg (or rsvg-convert) still get a preview: CairoSVG stays
    as the portable last resort, and the error trail names what failed before it."""
    import backdrop as bd

    def broken_librsvg(svg: str, target: Path, width: int, height: int) -> None:
        raise OSError("no librsvg on this host")

    monkeypatch.setattr(bd, "_render_with_librsvg", broken_librsvg)
    monkeypatch.setattr(bd.shutil, "which", lambda name: None)

    import sys
    import types

    fake = types.ModuleType("cairosvg")

    def svg2png(bytestring: bytes, write_to: str, **kwargs) -> None:  # noqa: ANN003
        Path(write_to).write_bytes(b"\x89PNG\r\n\x1a\nfake")

    fake.svg2png = svg2png  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cairosvg", fake)

    tmp = tmp_path / "out.png"
    errors = bd._render_thumbnail_backends("<svg xmlns='x'/>", tmp, 40, 50)
    assert tmp.is_file()
    assert any(e.startswith("librsvg:") for e in errors)
