"""World library tests — seed install, listing, and one-bad-world isolation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from library import LibraryError, WorldLibrary  # noqa: E402
from world import CONTRACT, prose_digest  # noqa: E402

REAL_SEEDS = _BACKEND.parent / "seeds"

PROSE = "第一章\n\n世界不围绕玩家存在。\n"

HEADER = {
    "id": "test-world",
    "title": "Test World",
    "version": "1.0",
    "language": "en",
    "clock": {"unit": "month", "label": "{year}/{month}"},
    "styles": [{"id": "standard", "label": "Standard", "default": True}],
    "opening": [{"id": "name", "label": "Name", "kind": "text"}],
    "panels": [{"id": "status", "always": True, "fields": [
        {"id": "age", "label": "Age", "primitive": "field"}]}],
    "endings": [{"id": "died", "when": "state.alive == false"}],
}


def world_file(header: dict | None = None, prose: str = PROSE) -> str:
    return f"---\n{json.dumps(header or HEADER, ensure_ascii=False)}\n---\n{prose}"


@pytest.fixture()
def lib(tmp_path: Path) -> WorldLibrary:
    (tmp_path / "seeds").mkdir()
    return WorldLibrary(tmp_path / "data", tmp_path / "seeds")


def write_seed(lib: WorldLibrary, name: str, text: str) -> None:
    (lib._seeds / f"{name}.md").write_text(text, encoding="utf-8")


# -- seed install ---------------------------------------------------------


def test_a_seed_is_installed_once_and_then_left_alone(lib: WorldLibrary) -> None:
    write_seed(lib, "test-world", world_file())

    first = lib.ensure_seeds_installed()
    assert first.installed == ["test-world"]

    installed_path = lib.path_for("test-world")
    marker = installed_path.read_text(encoding="utf-8")

    second = lib.ensure_seeds_installed()
    assert second.installed == []
    assert second.already_present == ["test-world"]
    assert installed_path.read_text(encoding="utf-8") == marker, "must not rewrite"


def test_an_edited_installed_world_survives_a_newer_seed(lib: WorldLibrary) -> None:
    """R1.6 — an app update carrying a newer seed reports, never overwrites.

    The user may have edited or played it; silently replacing it would discard
    both.
    """
    write_seed(lib, "test-world", world_file())
    lib.ensure_seeds_installed()

    edited = json.loads(json.dumps(HEADER))
    edited["title"] = "My Edited World"
    lib.path_for("test-world").write_text(world_file(edited), encoding="utf-8")

    bumped = json.loads(json.dumps(HEADER))
    bumped["version"] = "2.0"
    write_seed(lib, "test-world", world_file(bumped))

    report = lib.ensure_seeds_installed()

    assert report.installed == []
    assert report.newer_seed_available == [
        {"worldId": "test-world", "installed": "1.0", "available": "2.0"}
    ]
    assert lib.read("test-world").template.title == "My Edited World"


def test_the_installed_copy_carries_provenance(lib: WorldLibrary) -> None:
    write_seed(lib, "test-world", world_file())
    lib.ensure_seeds_installed()
    pack = lib.read("test-world")
    assert pack.provenance is not None
    assert pack.provenance.prose_sha256 == prose_digest(PROSE)
    assert pack.is_stale() is False


def test_a_broken_seed_does_not_stop_a_good_one(lib: WorldLibrary) -> None:
    write_seed(lib, "good", world_file())
    write_seed(lib, "broken", "no front matter here")

    report = lib.ensure_seeds_installed()

    assert report.installed == ["test-world"]
    assert len(report.failed) == 1
    assert report.failed[0]["seed"] == "broken.md"


def test_no_seeds_directory_is_not_an_error(tmp_path: Path) -> None:
    lib = WorldLibrary(tmp_path / "data", tmp_path / "absent-seeds")
    report = lib.ensure_seeds_installed()
    assert report.installed == []
    assert lib.list_worlds() == []


# -- listing --------------------------------------------------------------


def test_listing_reports_usable_worlds(lib: WorldLibrary) -> None:
    write_seed(lib, "test-world", world_file())
    lib.ensure_seeds_installed()

    rows = lib.list_worlds()
    assert len(rows) == 1
    assert rows[0]["usable"] is True
    assert rows[0]["worldId"] == "test-world"
    assert rows[0]["title"] == "Test World"
    assert rows[0]["panelCount"] == 1


def test_one_unusable_world_appears_as_a_row_and_the_rest_still_list(
    lib: WorldLibrary,
) -> None:
    """R1.8 / R14.13 — a typo in one file must not look like a lost world."""
    write_seed(lib, "good", world_file())
    lib.ensure_seeds_installed()

    bad = json.loads(json.dumps(HEADER))
    bad["panels"][0]["fields"][0]["primitive"] = "nope-meter"
    lib.path_for("broken-one").write_text(world_file(bad), encoding="utf-8")

    rows = {r["worldId"]: r for r in lib.list_worlds()}
    assert rows["test-world"]["usable"] is True
    assert rows["broken-one"]["usable"] is False
    assert "primitive" in rows["broken-one"]["field"]
    assert "nope-meter" in rows["broken-one"]["problem"]


def test_a_world_needing_a_newer_core_lists_both_versions(lib: WorldLibrary) -> None:
    future = json.loads(json.dumps(HEADER))
    future["compiledFrom"] = {
        "proseSha256": prose_digest(PROSE), "compiler": "1", "contract": 99}
    lib._worlds.mkdir(parents=True, exist_ok=True)
    lib.path_for("from-the-future").write_text(world_file(future), encoding="utf-8")

    row = lib.list_worlds()[0]
    assert row["usable"] is False
    assert row["needsCore"] == 99
    assert row["localCore"] == CONTRACT


def test_a_stale_world_is_still_usable_and_carries_its_note(lib: WorldLibrary) -> None:
    write_seed(lib, "test-world", world_file())
    lib.ensure_seeds_installed()

    path = lib.path_for("test-world")
    path.write_text(path.read_text(encoding="utf-8") + "补一句。\n", encoding="utf-8")

    row = lib.list_worlds()[0]
    assert row["usable"] is True, "stale must not mean unusable"
    assert row["stale"] is True
    assert row["stalenessNote"]


# -- ids ------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["", "../escape", "a/b", "Upper", "-lead", "x" * 65, "!"]
)
def test_a_malformed_world_id_never_touches_a_path(lib: WorldLibrary, bad: str) -> None:
    with pytest.raises(LibraryError):
        lib.path_for(bad)
    with pytest.raises(LibraryError):
        lib.read(bad)


def test_reading_an_absent_world_is_a_clean_error(lib: WorldLibrary) -> None:
    with pytest.raises(LibraryError) as exc:
        lib.read("not-installed")
    assert "no such world" in str(exc.value)


# -- the real seed --------------------------------------------------------


def test_the_shipped_flagship_seed_installs_and_lists(tmp_path: Path) -> None:
    if not (REAL_SEEDS / "jianhuo-jiyuan.md").is_file():
        pytest.skip("flagship seed not present")
    lib = WorldLibrary(tmp_path / "data", REAL_SEEDS)

    report = lib.ensure_seeds_installed()
    assert "jianhuo-jiyuan" in report.installed

    row = next(r for r in lib.list_worlds() if r["worldId"] == "jianhuo-jiyuan")
    assert row["usable"] is True
    assert row["title"] == "剑火纪元·西方幻想人生模拟器"
    assert row["panelCount"] == 6
    assert row["openingGroups"] == 13
    assert row["lineage"] is True
    assert row["stale"] is False
    assert len(row["styles"]) == 6
