"""World pack tests — round-trip fidelity, provenance, contract refusal."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from world import (  # noqa: E402
    CONTRACT,
    HAND_COMPILED,
    ContractTooNew,
    Provenance,
    WorldError,
    install_seed,
    prose_digest,
    read_world,
    serialize_world,
    summarize,
)

FLAGSHIP = _BACKEND.parent / "seeds" / "jianhuo-jiyuan.md"

MINIMAL_HEADER = {
    "id": "test-world",
    "title": "Test World",
    "version": "1.0",
    "language": "en",
    "clock": {"unit": "month", "label": "{year}/{month}"},
    "styles": [{"id": "standard", "label": "Standard", "default": True}],
    "opening": [{"id": "name", "label": "Name", "kind": "text"}],
    "panels": [
        {"id": "status", "always": True, "fields": [
            {"id": "age", "label": "Age", "primitive": "field"},
        ]},
    ],
    "endings": [{"id": "died", "when": "state.alive == false"}],
}

PROSE = "第一章\n\n世界不围绕玩家存在。\n╔═══╗\n【时间】\n"


def build(header: dict | None = None, prose: str = PROSE) -> str:
    body = json.dumps(header or MINIMAL_HEADER, ensure_ascii=False)
    return f"---\n{body}\n---\n{prose}"


# -- round trip -----------------------------------------------------------


def test_prose_survives_read_write_byte_for_byte() -> None:
    """The whole point: shipping a world must not rewrite its rulebook."""
    pack = read_world(build())
    assert serialize_world(pack).endswith(PROSE)
    assert read_world(serialize_world(pack)).prose == PROSE


def test_round_trip_is_stable_after_two_passes() -> None:
    once = serialize_world(read_world(build()))
    twice = serialize_world(read_world(once))
    assert once == twice, "serialisation must reach a fixed point"


def test_unknown_header_keys_are_preserved_not_dropped() -> None:
    """A build that does not understand a declaration must not delete it.

    Otherwise opening someone's world in an older build silently strips whatever
    that build had not learned yet.
    """
    header = {**MINIMAL_HEADER, "futureThing": {"a": [1, 2]}, "tags": ["x"]}
    out = serialize_world(read_world(build(header)))
    assert json.loads(out.split("---\n")[1])["futureThing"] == {"a": [1, 2]}
    assert json.loads(out.split("---\n")[1])["tags"] == ["x"]


def test_generated_sections_round_trip() -> None:
    pack = read_world(build())
    pack.upsert_capability_pack({"packId": "siege", "version": 1})
    pack.upsert_widget_spec({"widgetId": "ritual", "layout": "grid"})

    reread = read_world(serialize_world(pack))
    assert [p["packId"] for p in reread.capability_packs] == ["siege"]
    assert [s["widgetId"] for s in reread.widget_specs] == ["ritual"]
    assert reread.prose == PROSE


def test_a_prose_starting_with_a_dashed_line_still_round_trips() -> None:
    """Front-matter detection must not eat a rulebook that opens with ---."""
    tricky = "---\n看起来像 front matter，但是正文。\n"
    pack = read_world(build(prose=tricky))
    assert pack.prose == tricky
    assert read_world(serialize_world(pack)).prose == tricky


# -- upsert semantics -----------------------------------------------------


def test_upsert_replaces_rather_than_duplicating() -> None:
    pack = read_world(build())
    pack.upsert_capability_pack({"packId": "siege", "version": 1})
    pack.upsert_capability_pack({"packId": "siege", "version": 2})
    assert len(pack.capability_packs) == 1
    assert pack.capability_packs[0]["version"] == 2


def test_a_widget_spec_carrying_compiled_html_is_refused() -> None:
    """R14.8 — specs travel, HTML does not.

    A pack that shipped finished HTML would break the guarantee that widget bytes
    are always produced by the receiving machine's own compiler (R22.1).
    """
    pack = read_world(build())
    with pytest.raises(WorldError) as exc:
        pack.upsert_widget_spec({"widgetId": "x", "html": "<b>hi</b>"})
    assert "html" in str(exc.value)


@pytest.mark.parametrize("bad", [{}, {"packId": ""}, {"packId": 7}])
def test_a_pack_without_an_id_is_refused(bad: dict) -> None:
    with pytest.raises(WorldError):
        read_world(build()).upsert_capability_pack(bad)


# -- provenance -----------------------------------------------------------


def test_a_fresh_pack_is_not_stale() -> None:
    header = {**MINIMAL_HEADER,
              "compiledFrom": Provenance.for_prose(PROSE).to_dict()}
    assert read_world(build(header)).is_stale() is False


def test_editing_the_prose_flips_staleness_but_the_world_still_loads() -> None:
    """R14.5 — a stale header is worse than a fresh one, better than none.

    Refusing to load would mean fixing a typo locks you out of a world you played
    for two hundred turns.
    """
    header = {**MINIMAL_HEADER,
              "compiledFrom": Provenance.for_prose(PROSE).to_dict()}
    edited = read_world(build(header, prose=PROSE + "补一句。\n"))

    assert edited.is_stale() is True
    assert edited.staleness_note()
    # Still fully usable:
    assert edited.template.panels[0].visible({}) is True
    assert summarize(edited)["panelCount"] == 1


def test_a_pack_with_no_provenance_is_not_reported_stale() -> None:
    """Absence predates the field; flagging it would alarm with nothing to act on."""
    pack = read_world(build())
    assert pack.provenance is None
    assert pack.is_stale() is False
    assert pack.staleness_note() is None


def test_provenance_digest_is_over_the_prose_only() -> None:
    """Changing the header must not read as 'the rulebook moved'."""
    prov = Provenance.for_prose(PROSE)
    header_a = {**MINIMAL_HEADER, "compiledFrom": prov.to_dict()}
    header_b = {**MINIMAL_HEADER, "title": "Renamed",
                "compiledFrom": prov.to_dict()}
    assert read_world(build(header_a)).is_stale() is False
    assert read_world(build(header_b)).is_stale() is False


def test_an_older_compiler_marks_a_pack_improvable(monkeypatch) -> None:
    import world as world_mod

    monkeypatch.setattr(world_mod, "COMPILER_VERSION", 5)
    header = {**MINIMAL_HEADER, "compiledFrom": {
        "proseSha256": prose_digest(PROSE), "compiler": "1", "contract": CONTRACT}}
    assert read_world(build(header)).is_improvable() is True


def test_a_hand_written_header_is_never_improvable() -> None:
    """A person's judgement is not superseded by a compiler bump."""
    header = {**MINIMAL_HEADER, "compiledFrom": {
        "proseSha256": prose_digest(PROSE), "compiler": HAND_COMPILED}}
    assert read_world(build(header)).is_improvable() is False


# -- contract -------------------------------------------------------------


def test_a_pack_needing_a_newer_core_is_refused_with_both_versions() -> None:
    header = {**MINIMAL_HEADER, "compiledFrom": {
        "proseSha256": prose_digest(PROSE), "compiler": "1", "contract": 99}}
    with pytest.raises(ContractTooNew) as exc:
        read_world(build(header))
    assert exc.value.needed == 99
    assert exc.value.local == CONTRACT
    assert "99" in str(exc.value)


def test_a_pack_on_the_current_contract_loads() -> None:
    header = {**MINIMAL_HEADER, "compiledFrom": {
        "proseSha256": prose_digest(PROSE), "compiler": "1", "contract": CONTRACT}}
    assert read_world(build(header)).id == "test-world"


# -- seed install ---------------------------------------------------------


def test_install_stamps_provenance_and_emits_json() -> None:
    installed = install_seed(build())
    pack = read_world(installed)
    assert pack.provenance is not None
    assert pack.provenance.compiler == HAND_COMPILED
    assert pack.is_stale() is False
    # The runtime copy is machine-managed JSON.
    json.loads(installed.split("---\n")[1])


def test_install_preserves_existing_provenance() -> None:
    prov = Provenance.for_prose(PROSE, compiler="3")
    header = {**MINIMAL_HEADER, "compiledFrom": prov.to_dict()}
    pack = read_world(install_seed(build(header)))
    assert pack.provenance.compiler == "3"
    assert pack.provenance.compiled_at == prov.compiled_at


def test_installing_the_real_flagship_seed_keeps_its_prose_intact() -> None:
    """The seed is hand-written YAML with per-chapter comments; the installed copy
    is JSON. The comments stay in the repo, the rulebook does not change."""
    if not FLAGSHIP.is_file():
        pytest.skip("flagship seed not present")
    seed_text = FLAGSHIP.read_text(encoding="utf-8")
    original = read_world(seed_text)

    installed = read_world(install_seed(seed_text))

    assert installed.prose == original.prose
    assert installed.id == "jianhuo-jiyuan"
    assert len(installed.template.panels) == 6
    assert len(installed.template.opening) == 13
    assert installed.is_stale() is False

    # Comments are gone from the runtime copy, by design.
    #
    # Witnessed by comment-only ENGLISH prose. The witness used to be a chapter
    # number, which worked until the pack began declaring chapters — those name their
    # headings verbatim, because a pointer into prose the app may not edit has to be
    # the heading text, so the number then appeared in a real field. A witness that a
    # legitimate field can contain is not a witness.
    installed_header = install_seed(seed_text).split("---\n")[1]
    for comment_only in ("machine-readable header", "traceable to a chapter"):
        assert comment_only not in installed_header

    # …but every declaration they annotated survived.
    assert [p.id for p in installed.template.panels] == [
        "status", "magic", "relations", "nation", "academy", "family",
    ]
    # Including the chapter declarations, whose headings ARE prose text and must
    # survive exactly: a heading that no longer matches the prose is refused at load,
    # so an installed copy that mangled one would make the world unplayable.
    assert [c.id for c in installed.template.chapters] == [
        c.id for c in original.template.chapters
    ]
    for got, want in zip(installed.template.chapters, original.template.chapters):
        assert got.heading == want.heading
        assert got.heading in installed.prose


def test_summarize_gives_the_library_what_it_needs() -> None:
    row = summarize(read_world(install_seed(build())))
    assert row["worldId"] == "test-world"
    assert row["version"] == "1.0"
    assert row["stale"] is False
    assert row["capabilityPacks"] == 0
    assert row["openingGroups"] == 1
