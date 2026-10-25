"""Revising a backdrop draft by element patches (endless_revise_backdrop_draft).

The illustrator used to revise by re-typing both whole SVGs. These pin the patch
path: the server's element ids, each op, the all-or-nothing refusals, the full
sanitizer on the merged result, and draft versions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402
from backdrop import BackdropStore  # noqa: E402

DESKTOP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">'
    '<defs><linearGradient id="sky"><stop offset="0" stop-color="#123"/></linearGradient></defs>'
    '<rect fill="url(#sky)" width="800" height="600"/>'
    '<g id="town"><rect x="10" y="300" width="40" height="80" fill="#334"/>'
    '<circle cx="200" cy="100" r="30" fill="#fe8"/></g>'
    "</svg>"
)
MOBILE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 450 900">'
    '<rect fill="#223" width="450" height="900"/>'
    '<circle cx="225" cy="200" r="40" fill="#fe8"/>'
    "</svg>"
)


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "_DATA", tmp_path / "data")
    return tmp_path / "data"


def _call(name, **args):
    return json.loads(srv.call_tool(name, args))


def _draft(data: Path, run_id: str, markup: str = DESKTOP, mobile: str = MOBILE):
    from kiro_crew.apps.app_storage import AppStorage

    from store import RunStore

    RunStore(AppStorage("endless-worlds", data), data).request_backdrop(
        run_id, turn=1, brief="test art"
    )
    out = _call("endless_submit_backdrop_draft", runId=run_id, turn=1, markup=markup, mobile=mobile)
    assert out["ok"] is True, out
    return out


def _revise(run_id: str, draft_id: str, *ops):
    return _call(
        "endless_revise_backdrop_draft", runId=run_id, turn=1, draftId=draft_id, ops=list(ops)
    )


def _commit(run_id: str, draft_id: str):
    out = _call("endless_commit_backdrop", runId=run_id, turn=1, draftId=draft_id)
    assert out["ok"] is True, out
    return BackdropStore(srv._DATA, run_id).exact(1)


def _record(data: Path, run_id: str) -> bytes:
    return (data / "runs" / run_id / "backdrop-draft.json").read_bytes()


def _ids(outline_text: str) -> dict[str, str]:
    """id -> the rest of its outline line."""
    return {ln.split()[0]: ln.strip() for ln in outline_text.splitlines() if ln.strip()}


# ── ids and outline ─────────────────────────────────────────────────────


def test_the_draft_answer_outlines_each_svg_by_element_id_without_markup(data):
    out = _draft(data, "a" * 32)
    desk = _ids(out["outline"]["desktop"])
    mob = _ids(out["outline"]["mobile"])
    assert list(desk) == ["d1", "d2", "d3"]
    assert desk["d3"].startswith("d3 g#town")
    assert desk["d2"] == "d2 rect 0,0 800x600 fill=url(#sky)"
    assert list(mob) == ["m4", "m5"]
    assert "<" not in json.dumps(out["outline"]), "the outline must never carry markup"


def test_ids_stay_stable_across_a_revision(data):
    run = "b" * 32
    first = _draft(data, run)
    before = _ids(first["outline"]["desktop"])
    out = _revise(
        run,
        first["draftId"],
        {"op": "insert_before", "id": "d2", "markup": '<rect width="5" height="5" fill="#000"/>'},
        {"op": "remove", "id": "m5"},
    )
    assert out["ok"] is True, out
    after = _ids(out["outline"]["desktop"])
    for eid, line in before.items():
        assert after[eid] == line, f"{eid} moved or changed"
    new = set(after) - set(before)
    assert len(new) == 1 and new.isdisjoint({"m4", "m5"}), new
    assert list(_ids(out["outline"]["mobile"])) == ["m4"]
    # A second revision keeps every id the first one issued.
    again = _revise(
        run, out["draftId"], {"op": "set_attrs", "id": "d3", "attrs": {"opacity": "0.5"}}
    )
    assert set(_ids(again["outline"]["desktop"])) == set(after)


def test_big_groups_get_ids_for_their_children(data):
    trees = "".join(f'<path d="M{i * 30} 500 l10 -60 l10 60z" fill="#2a4"/>' for i in range(20))
    markup = DESKTOP.replace("</svg>", f'<g id="forest">{trees}</g></svg>')
    out = _draft(data, "c" * 32, markup=markup)
    lines = out["outline"]["desktop"].splitlines()
    forest = next(i for i, ln in enumerate(lines) if "g#forest" in ln)
    kids = [ln for ln in lines[forest + 1 :] if ln.startswith(" ")]
    assert len(kids) == 20 and kids[0].strip().startswith("d") and "path d=M0 500" in kids[0]


def test_the_outline_stays_under_its_pinned_cap(data):
    """A 24 KB draft can hold hundreds of shapes; the outline it returns may not
    grow with it. 3000 bytes per SVG is the pinned ceiling."""
    shapes = "".join(f'<circle cx="{i}" cy="{i % 600}" r="2" fill="#abc"/>' for i in range(470))
    big = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">{shapes}</svg>'
    assert len(big) < 24000
    out = _draft(data, "d" * 32, markup=big)
    desk = out["outline"]["desktop"]
    assert len(desk.encode("utf-8")) <= 3000
    assert desk.splitlines()[-1].startswith("… ") and "more elements" in desk


def test_the_server_ids_are_never_published(data):
    run = "e" * 32
    first = _draft(data, run)
    final = _commit(run, first["draftId"])
    assert "data-eid" not in final["markup"] and "data-eid" not in final["mobile"]
    assert final["markup"] == DESKTOP and final["mobile"] == MOBILE


def test_ids_an_illustrator_typed_itself_are_replaced_by_the_servers(data):
    typed = DESKTOP.replace('<rect fill="url(#sky)"', '<rect data-eid="d3" fill="url(#sky)"')
    out = _draft(data, "f" * 32, markup=typed)
    assert list(_ids(out["outline"]["desktop"])) == ["d1", "d2", "d3"]


# ── each op ─────────────────────────────────────────────────────────────


def test_replace_swaps_one_element_and_keeps_its_id(data):
    run = "1" * 32
    first = _draft(data, run)
    out = _revise(
        run,
        first["draftId"],
        {"op": "replace", "id": "d3", "markup": '<g id="ruin"><path d="M0 0L9 9"/></g>'},
    )
    assert out["ok"] is True, out
    assert _ids(out["outline"]["desktop"])["d3"].startswith("d3 g#ruin")
    final = _commit(run, out["draftId"])
    assert '<g id="ruin"><path d="M0 0L9 9"/></g></svg>' in final["markup"]
    assert "town" not in final["markup"]


def test_insert_after_and_before_place_new_elements_beside_the_target(data):
    run = "2" * 32
    first = _draft(data, run)
    out = _revise(
        run,
        first["draftId"],
        {"op": "insert_after", "id": "d2", "markup": '<rect id="a1"/><rect id="a2"/>'},
        {"op": "insert_before", "id": "m4", "markup": '<rect id="b1"/>'},
    )
    final = _commit(run, out["draftId"])
    assert 'height="600"/><rect id="a1"/><rect id="a2"/><g id="town">' in final["markup"]
    assert 'viewBox="0 0 450 900"><rect id="b1"/><rect fill="#223"' in final["mobile"]


def test_remove_drops_the_element(data):
    run = "3" * 32
    first = _draft(data, run)
    out = _revise(run, first["draftId"], {"op": "remove", "id": "d3"})
    final = _commit(run, out["draftId"])
    assert "town" not in final["markup"] and "circle" not in final["markup"]


def test_set_attrs_sets_escapes_and_removes(data):
    run = "4" * 32
    first = _draft(data, run)
    out = _revise(
        run,
        first["draftId"],
        {"op": "set_attrs", "id": "d2", "attrs": {"fill": "#f00", "opacity": 0.5, "width": None}},
        {"op": "set_attrs", "id": "m5", "attrs": {"class": 'a"b<c'}},
    )
    assert out["ok"] is True, out
    final = _commit(run, out["draftId"])
    assert '<rect fill="#f00" height="600" opacity="0.5"/>' in final["markup"]
    assert 'class="a&quot;b&lt;c"' in final["mobile"]


def test_the_revision_answer_measures_the_patch_against_the_whole_draft(data):
    run = "5" * 32
    first = _draft(data, run)
    out = _revise(run, first["draftId"], {"op": "set_attrs", "id": "d2", "attrs": {"fill": "#f00"}})
    assert out["patchBytes"] == len("fill") + len("#f00")
    assert out["draftBytes"] == len(DESKTOP.replace("url(#sky)", "#f00")) + len(MOBILE)


# ── refusals change nothing ─────────────────────────────────────────────


def test_an_unknown_id_is_refused_and_the_draft_is_unchanged(data):
    run = "6" * 32
    first = _draft(data, run)
    before = _record(data, run)
    out = _revise(
        run,
        first["draftId"],
        {"op": "set_attrs", "id": "d2", "attrs": {"fill": "#f00"}},
        {"op": "remove", "id": "d99"},
    )
    assert out["ok"] is False
    assert out["error"] == (
        f"unknown element id 'd99'; use an id from draft {first['draftId']}'s outline"
    )
    assert _record(data, run) == before
    assert "#f00" not in _commit(run, first["draftId"])["markup"]


def test_an_op_on_an_id_removed_earlier_in_the_same_call_is_refused(data):
    run = "7" * 32
    first = _draft(data, run)
    before = _record(data, run)
    out = _revise(run, first["draftId"], {"op": "remove", "id": "d3"}, {"op": "remove", "id": "d3"})
    assert out["ok"] is False and "unknown element id 'd3'" in out["error"]
    assert _record(data, run) == before


@pytest.mark.parametrize(
    "op",
    [
        {"op": "insert_after", "id": "d2", "markup": "<script>alert(1)</script>"},
        {"op": "replace", "id": "d2", "markup": '<rect onload="alert(1)"/>'},
        {"op": "set_attrs", "id": "d2", "attrs": {"onclick": "alert(1)"}},
        {
            "op": "insert_after",
            "id": "m4",
            "markup": '<s:script xmlns:s="http://www.w3.org/2000/svg">x</s:script>',
        },
        {
            "op": "insert_before",
            "id": "d3",
            "markup": '<f:foreignObject xmlns:f="http://www.w3.org/2000/svg"><p/></f:foreignObject>',
        },
        {"op": "set_attrs", "id": "d2", "attrs": {"href": "https://example.com/x.png"}},
        {"op": "insert_after", "id": "d2", "markup": '<image href="file:///etc/passwd"/>'},
    ],
    ids=[
        "script",
        "handler",
        "handler-attr",
        "ns-script",
        "ns-foreign",
        "remote-href",
        "file-href",
    ],
)
def test_unsafe_markup_in_a_patch_is_refused_by_the_full_sanitizer(data, op):
    run = "8" * 32
    first = _draft(data, run)
    before = _record(data, run)
    out = _revise(run, first["draftId"], op)
    assert out["ok"] is False, out
    assert _record(data, run) == before
    previews = data / "runs" / run / "backdrop-previews"
    assert sorted(p.name for p in previews.iterdir()) == sorted(
        Path(p).name for p in first["previews"].values()
    )


def test_markup_that_would_break_the_document_is_refused(data):
    run = "9" * 32
    first = _draft(data, run)
    before = _record(data, run)
    for op in (
        {"op": "replace", "id": "d2", "markup": "<rect/><rect/>"},
        {"op": "insert_after", "id": "d2", "markup": "<g>"},
        {"op": "insert_after", "id": "d2", "markup": "</g><rect/>"},
        {"op": "replace", "id": "d2", "markup": DESKTOP},
        {"op": "set_attrs", "id": "d2", "attrs": {"data-eid": "d1"}},
    ):
        out = _revise(run, first["draftId"], op)
        assert out["ok"] is False, op
    assert _record(data, run) == before


# ── versions ────────────────────────────────────────────────────────────


def test_a_revision_is_a_new_version_and_the_patched_draft_stays_committable(data):
    run = "ab" * 16
    first = _draft(data, run)
    out = _revise(run, first["draftId"], {"op": "set_attrs", "id": "d2", "attrs": {"fill": "#f00"}})
    assert out["ok"] is True
    assert out["draftId"] != first["draftId"] and out["revisionOf"] == first["draftId"]
    assert out["version"] == 2
    for path in list(first["previews"].values()) + list(out["previews"].values()):
        assert Path(path).is_file()
    # The illustrator judged the revision worse: the first draft still publishes.
    final = _commit(run, first["draftId"])
    assert final["markup"] == DESKTOP
    assert not (data / "runs" / run / "backdrop-draft.json").exists()
    assert not any(Path(p).exists() for p in out["previews"].values())


def test_the_revision_itself_publishes_when_committed(data):
    run = "cd" * 16
    first = _draft(data, run)
    out = _revise(run, first["draftId"], {"op": "set_attrs", "id": "d2", "attrs": {"fill": "#f00"}})
    assert _commit(run, out["draftId"])["markup"] == DESKTOP.replace("url(#sky)", "#f00")


def test_a_fresh_draft_still_replaces_every_earlier_version(data):
    run = "ef" * 16
    first = _draft(data, run)
    rev = _revise(run, first["draftId"], {"op": "remove", "id": "d3"})
    fresh = _draft(data, run)
    for stale in (first["draftId"], rev["draftId"]):
        out = _call("endless_commit_backdrop", runId=run, turn=1, draftId=stale)
        assert out["ok"] is False
    assert _commit(run, fresh["draftId"])["markup"] == DESKTOP


def test_old_versions_fall_off_past_the_cap(data):
    run = "0f" * 16
    first = _draft(data, run)
    ids = [first["draftId"]]
    for n in range(4):
        out = _revise(run, ids[-1], {"op": "set_attrs", "id": "d2", "attrs": {"opacity": str(n)}})
        ids.append(out["draftId"])
    # Four kept (the cap): the very first fell off, with its previews.
    assert _call("endless_commit_backdrop", runId=run, turn=1, draftId=ids[0])["ok"] is False
    assert not any(Path(p).exists() for p in first["previews"].values())
    assert 'opacity="0"' in _commit(run, ids[1])["markup"]


# ── the illustrator is told to patch ────────────────────────────────────


def test_both_art_modes_tell_the_illustrator_to_revise_by_patch(data):
    from settings import write_settings

    standard = _draft(data, "12" * 16)
    write_settings(data, model="", reasoning_effort="", art_quality="polished")
    polished = _draft(data, "34" * 16)
    for answer in (standard, polished):
        assert "endless_revise_backdrop_draft" in answer["next"]
        assert "never re-type the whole SVG" in answer["next"]


def test_the_underlay_placeholder_survives_ids_and_patches():
    """A traced scene's `<g id="etr-underlay"/>` is matched byte-exactly by the
    splice; the id the server gives it must strip back to that exact text."""
    import svgpatch

    scene = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">'
        '<rect width="800" height="600" fill="#123"/><g id="etr-underlay"/></svg>'
    )
    annotated = svgpatch.annotate({"markup": scene})
    assert 'data-eid="d2" id="etr-underlay"' in annotated["markup"]
    patched = svgpatch.apply_ops(
        annotated,
        [{"op": "insert_after", "id": "d2", "markup": '<path d="M0 0L9 9" stroke="#fff"/>'}],
        "x",
    )
    clean = svgpatch.strip_eids(patched["markup"])
    assert '<g id="etr-underlay"/><path d="M0 0L9 9" stroke="#fff"/></svg>' in clean
