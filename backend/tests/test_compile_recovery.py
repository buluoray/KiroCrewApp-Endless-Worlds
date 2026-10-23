"""Creation failures reproduced with small, synthetic worldsmith submissions."""

import json
from copy import deepcopy

import pytest
from test_compile import GOOD, PROSE

from compile import accept_compiled_header
from drafts import DraftStore
from world import read_world


def test_untagged_compiled_panels_get_a_shared_phone_tab():
    header = deepcopy(GOOD)
    for panel in header["panels"]:
        panel.pop("region")
    original = deepcopy(header)
    result = accept_compiled_header(PROSE, header)
    assert result.ok, result.problem
    assert header == original
    assert [p.region for p in result.pack.template.panels] == ["system", "system"]
    assert [p.region for p in read_world(result.world_text).template.panels] == ["system", "system"]
    assert sum("no region" in warning for warning in result.warnings) == 2


@pytest.mark.parametrize("region", ["", "  ", None, 12, []])
def test_blank_or_wrong_typed_region_uses_the_shared_phone_tab(region):
    header = deepcopy(GOOD)
    header["panels"][1]["region"] = region
    result = accept_compiled_header(PROSE, header)
    assert result.ok, result.problem
    assert result.pack.template.panels[1].region == "system"
    assert result.pack.template.panels[0].region == "status"


def test_declared_regions_and_handwritten_worlds_are_not_reassigned():
    header = deepcopy(GOOD)
    header["panels"][1]["region"] = "arcane-studies"
    result = accept_compiled_header(PROSE, header)
    assert result.ok, result.problem
    assert result.pack.template.panels[1].region == "arcane-studies"
    assert result.warnings == []
    header["panels"][1].pop("region")
    pack = read_world(f"---\n{json.dumps(header)}\n---\n{PROSE}")
    assert pack.template.panels[1].region == ""


@pytest.mark.parametrize("header", ["null", "```json\nnull\n```", None])
def test_null_header_is_a_readable_refusal(header):
    result = accept_compiled_header(PROSE, header)
    assert not result.ok
    assert "object" in result.problem


@pytest.mark.parametrize("world_id", ["test-world", "TestWorld"])
@pytest.mark.parametrize("key", ["styles", "opening", "panels", "endings"])
def test_wrong_typed_required_lists_never_crash_the_compile(key, world_id):
    header = deepcopy(GOOD)
    header["id"] = world_id
    header[key] = 7
    result = accept_compiled_header(PROSE, header)
    # A missing styles list has an existing, documented default.
    if key == "styles":
        assert result.ok, result.problem
    else:
        assert not result.ok
        assert result.field == key


@pytest.mark.parametrize("world_id", ["test-world", "TestWorld"])
@pytest.mark.parametrize(
    "key", ["chapters", "lore", "systems", "roles", "milestones", "handToAgent"]
)
def test_wrong_typed_optional_lists_are_dropped_with_a_warning(key, world_id):
    header = deepcopy(GOOD)
    header["id"] = world_id
    header[key] = 7
    result = accept_compiled_header(PROSE, header)
    assert result.ok, result.problem
    assert any(f"dropped {key}" in w for w in result.warnings)


@pytest.mark.parametrize("world_id", ["test-world", "TestWorld"])
def test_wrong_typed_panel_fields_return_a_named_refusal(world_id):
    header = deepcopy(GOOD)
    header["id"] = world_id
    header["panels"][0]["fields"] = 7
    result = accept_compiled_header(PROSE, header)
    assert not result.ok
    assert "fields" in result.field


@pytest.mark.parametrize("kind", ["lore", "systems"])
def test_wrong_typed_nested_optional_lists_drop_only_the_bad_entry(kind):
    header = deepcopy(GOOD)
    header[kind] = (
        [{"id": "port", "keys": ["port"], "text": "A port.", "relations": 7}]
        if kind == "lore"
        else [{"id": "study", "kind": "accrual", "into": "state.hero.xp", "tiers": 7}]
    )
    result = accept_compiled_header(PROSE, header)
    assert result.ok, result.problem
    assert getattr(result.pack.template, kind) == []
    assert any(f"dropped {kind}" in w for w in result.warnings)


def test_malformed_submission_leaves_a_retryable_draft(tmp_path, monkeypatch):
    import mcp_server

    store = DraftStore(tmp_path)
    draft_id = store.create("A life on a coast.")
    store.mark_pending(draft_id)
    monkeypatch.setattr(mcp_server, "_drafts", lambda: store)
    bad = mcp_server._submit_world_draft({"draftId": draft_id, "prose": PROSE, "header": "null"})
    assert bad["stored"] and not bad["accepted"]
    assert store.record(draft_id)["status"] == "failed"
    assert "object" in store.record(draft_id)["problem"]
    store.mark_pending(draft_id)
    good = mcp_server._submit_world_draft(
        {"draftId": draft_id, "prose": PROSE, "header": deepcopy(GOOD)}
    )
    assert good["accepted"]
    assert store.record(draft_id)["status"] == "ready"
