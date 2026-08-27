"""Settings store: defaults, round-trip, validation, and the style helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from settings import (  # noqa: E402
    PAINT_STYLES,
    preferred_style,
    read_settings,
    write_settings,
)
from store import rewrite_brief_style  # noqa: E402

_DEFAULTS = {
    "model": "",
    "reasoningEffort": "",
    "painterModel": "",
    "backdrops": True,
    "styles": list(PAINT_STYLES),
    "backdropCadence": "normal",
    "choiceArt": True,
    "choiceEffects": True,
    "proseLength": "",
    "reducedMotion": False,
    "artQuality": "standard",
}


def test_defaults_when_nothing_saved(tmp_path: Path) -> None:
    assert read_settings(tmp_path) == _DEFAULTS


def test_round_trip(tmp_path: Path) -> None:
    write_settings(
        tmp_path,
        model="some-model",
        reasoning_effort="high",
        painter_model="paint-model",
        backdrops=False,
        styles=["watercolor", "oil"],
        backdrop_cadence="sparse",
        choice_art=False,
        choice_effects=False,
        prose_length="short",
        reduced_motion=True,
        art_quality="fast",
    )
    assert read_settings(tmp_path) == {
        "model": "some-model",
        "reasoningEffort": "high",
        "painterModel": "paint-model",
        "backdrops": False,
        "styles": ["watercolor", "oil"],
        "backdropCadence": "sparse",
        "choiceArt": False,
        "choiceEffects": False,
        "proseLength": "short",
        "reducedMotion": True,
        "artQuality": "fast",
    }


def test_the_painter_model_defaults_to_empty_and_round_trips(tmp_path: Path) -> None:
    # Chosen separately from the narrator's model; omitting it keeps the default.
    assert write_settings(tmp_path, model="m", reasoning_effort="")["painterModel"] == ""
    assert (
        write_settings(tmp_path, model="m", reasoning_effort="", painter_model="p")["painterModel"]
        == "p"
    )
    assert read_settings(tmp_path)["painterModel"] == "p"


def test_an_unknown_effort_is_coerced_to_default(tmp_path: Path) -> None:
    # It becomes a subprocess argument downstream, so an unknown value is dropped
    # rather than stored.
    saved = write_settings(tmp_path, model="", reasoning_effort="turbo")
    assert saved["reasoningEffort"] == ""
    assert read_settings(tmp_path)["reasoningEffort"] == ""


def test_a_damaged_file_reads_as_default(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert read_settings(tmp_path) == _DEFAULTS


def test_a_pre_upgrade_file_reads_with_the_new_knobs_at_their_defaults(tmp_path: Path) -> None:
    # A settings.json written before the playability knobs existed carries only
    # the three model fields; the missing knobs must read as "everything on",
    # never as "art off".
    (tmp_path / "settings.json").write_text(
        '{"model": "m", "reasoningEffort": "high", "painterModel": "p"}', encoding="utf-8"
    )
    got = read_settings(tmp_path)
    assert got["backdrops"] is True
    assert got["styles"] == list(PAINT_STYLES)
    assert got["choiceArt"] is True and got["choiceEffects"] is True
    assert got["proseLength"] == "" and got["backdropCadence"] == "normal"


def test_unknown_enum_values_coerce_to_defaults(tmp_path: Path) -> None:
    saved = write_settings(
        tmp_path,
        model="",
        reasoning_effort="",
        backdrop_cadence="hourly",
        prose_length="epic",
        styles=["watercolor", "crayon"],
        art_quality="turbo",
    )
    assert saved["backdropCadence"] == "normal"
    assert saved["proseLength"] == ""
    assert saved["artQuality"] == "standard"
    # The unknown style is dropped; the known one survives.
    assert saved["styles"] == ["watercolor"]


def test_reduced_motion_and_art_quality_round_trip(tmp_path: Path) -> None:
    write_settings(tmp_path, model="", reasoning_effort="", reduced_motion=True, art_quality="fast")
    got = read_settings(tmp_path)
    assert got["reducedMotion"] is True and got["artQuality"] == "fast"
    # And a pre-upgrade file reads as motion on, standard quality.
    (tmp_path / "settings.json").write_text('{"model": ""}', encoding="utf-8")
    got = read_settings(tmp_path)
    assert got["reducedMotion"] is False and got["artQuality"] == "standard"


def test_an_empty_style_list_reads_as_all_enabled(tmp_path: Path) -> None:
    # "No styles" is not a state the UI offers; failing open keeps a hand-edited
    # file from turning every page blank.
    saved = write_settings(tmp_path, model="", reasoning_effort="", styles=[])
    assert saved["styles"] == list(PAINT_STYLES)


def test_preferred_style_orders_watercolor_first_and_photo_last() -> None:
    assert preferred_style(["photo", "watercolor", "oil", "minimal"]) == "watercolor"
    assert preferred_style(["photo", "minimal"]) == "minimal"
    assert preferred_style(["photo"]) == "photo"


# -- the brief rewrite (where the allowlist is enforced) --------------------


def test_a_disabled_style_is_rewritten_in_place() -> None:
    brief = 'LANE: scene\nSTYLE: photo\nREFERENCE: subject="stone bridge"\na misty crossing'
    out = rewrite_brief_style(brief, ["watercolor", "oil"], "watercolor")
    assert "STYLE: watercolor" in out
    assert "photo" not in out.split("REFERENCE")[0]
    # The rest of the art direction survives verbatim.
    assert 'REFERENCE: subject="stone bridge"' in out and "a misty crossing" in out


def test_an_enabled_style_is_left_alone() -> None:
    brief = "LANE: scene\nSTYLE: oil\nheavy dusk"
    assert rewrite_brief_style(brief, ["oil", "watercolor"], "watercolor") == brief


def test_a_styleless_scene_gets_a_style_when_photo_is_off() -> None:
    # A style-less SCENE brief MEANS the photo pipeline, so with photo disabled it
    # must be routed to a painterly style instead of a search the player switched off.
    brief = 'LANE: scene\nREFERENCE: subject="walled town"'
    out = rewrite_brief_style(brief, ["watercolor", "oil", "minimal"], "watercolor")
    assert out.endswith("STYLE: watercolor")


def test_a_styleless_motif_is_never_touched() -> None:
    # Motifs are hand-drawn and never reach the photo pipeline.
    brief = "LANE: motif\nTHESIS: grief arriving before the news does"
    assert rewrite_brief_style(brief, ["watercolor"], "watercolor") == brief
