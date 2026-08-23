"""The dev fixtures must keep producing a life the UI can actually render.

``devtools/fixtures.py`` seeds screenshot scenarios by driving the app's own writers
rather than by writing JSON, precisely so a schema change breaks it loudly. That only
holds if something runs it — otherwise the harness rots quietly and the next person to
reach for it spends their afternoon on a fixture bug instead of the bug they came for.

These tests seed into a tmp dir and assert the SHAPE the UI depends on: the play view
assembles, the scenes are mounted and compile, the memory graph kept its events,
threads and relations, and the star payload the star map renders is non-empty. Each
assertion names what breaks in the UI when it fails, because "fixtures broke" is not
actionable and "the relations lens reads empty" is.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "devtools"))

pytest.importorskip("kiro_crew.apps.app_storage")

import fixtures  # noqa: E402


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, str], Path]:
    data = tmp_path_factory.mktemp("appdata")
    return fixtures.seed_all(data), data


def test_every_scenario_seeds_a_life(seeded: tuple[dict[str, str], Path]) -> None:
    runs, _data = seeded
    assert set(runs) == {s.key for s in fixtures.SCENARIOS}
    assert all(len(run) == 32 for run in runs.values()), runs


def test_labels_are_unique_so_a_shot_can_address_a_life(
    seeded: tuple[dict[str, str], Path],
) -> None:
    """Shot recipes click a life by its label. Two lives sharing one label makes the
    click land on whichever the shelf renders first, which is a silently wrong shot."""
    labels = [s.label for s in fixtures.SCENARIOS]
    assert len(set(labels)) == len(labels), labels
    runs, data = seeded
    srv = fixtures._import_backend()
    srv._DATA = data
    rows = {r.get("runId"): r for r in srv._store().read_index()}
    for sc in fixtures.SCENARIOS:
        assert rows[runs[sc.key]].get("label") == sc.label


def test_the_rich_life_has_the_surfaces_its_shots_need(
    seeded: tuple[dict[str, str], Path],
) -> None:
    from scenes import SceneLedger  # noqa: PLC0415
    from widget import compile_scene  # noqa: PLC0415

    runs, data = seeded
    run = runs["rich"]
    ledger_store = SceneLedger(data, run)
    mounted = {s["sceneId"]: s for s in ledger_store.mounted()}
    assert set(mounted) == {"local-map", "supply-ledger", "water-order"}, (
        "the scene shots address these ids by name; a renamed scene makes them shoot "
        f"an empty page instead: {sorted(mounted)}"
    )
    assert mounted["water-order"]["asks"], "the asking scene is what renders choices"
    state = fixtures._import_backend()._store().read_state(run)
    # Compiling (not just mounting) is what proves the specs are legal for the real
    # widget compiler — a spec it rejects renders as a blank frame. Each scene is
    # checked by content of its own, since a document that compiled to an empty shell
    # is exactly the failure a shot cannot see.
    signatures = {
        "local-map": "陈屿的据点",
        "supply-ledger": "整车囤货",
        "water-order": "先把满的搬回去",
    }
    for scene_id, needle in signatures.items():
        html = compile_scene(scene_id, ledger_store.spec(scene_id), state, nonce="n")
        assert f'data-scene="{scene_id}"' in html, scene_id
        assert needle in html, (
            f"{scene_id} compiled without its own content ({needle!r}) — the frame would "
            "render as an empty box"
        )


def test_the_memory_graph_keeps_what_the_star_map_draws(
    seeded: tuple[dict[str, str], Path],
) -> None:
    from memory_graph import build_index, project_relations, star_payload  # noqa: PLC0415

    runs, data = seeded
    srv = fixtures._import_backend()
    srv._DATA = data
    index = build_index(srv._store().read_chronicle(runs["rich"]))
    assert len(index["events"]) >= 3, (
        "the timeline lens draws one row per known event; too few makes a populated "
        "map look empty in every shot"
    )
    assert index["threads"], (
        "threads are declared BY an event, not at the memory root — one put at the root "
        "is dropped in silence and the 线索 filter has nothing to show"
    )
    relations = project_relations(index)
    assert relations, "the relations lens reads '还没有记下与人的往来' without these"
    assert any(rel["from"] == "player" for rel in relations.values()), (
        "the relations lens orbits the life's centre (the protagonist entity), so edges "
        "between two side characters leave it reading empty"
    )
    payload = star_payload(index)
    assert payload["nodes"] and payload["centre"], payload.keys()


def test_the_ended_life_reads_as_ended(seeded: tuple[dict[str, str], Path]) -> None:
    runs, data = seeded
    srv = fixtures._import_backend()
    srv._DATA = data
    state = srv._store().read_state(runs["ended"])
    assert state.get("ended"), "the `ended` shot waits for the closed-life badge"
    assert state.get("alive") is False
