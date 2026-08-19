"""Story card gates (design §12.3 + the §11 Phase 3 completion bar).

The property under test everywhere: the export is a pure function of the draft
through the same ``resolve()`` the preview uses, so what was previewed is what
ships — and nothing outside the allowlist has a path into either.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import memory_graph as mg  # noqa: E402
import story_cards as sc  # noqa: E402


def turn_entry(turn, memory=None, action="", prose="p"):
    entry = {"turn": turn, "prose": prose, "action": action,
             "choices": [], "events": [], "gains": []}
    if memory is not None:
        entry["memory"] = memory
    return entry


def life_chronicle():
    return [
        turn_entry(1, {
            "entities": [
                {"id": "elin", "kind": "character", "name": "艾琳"},
                {"id": "bridge", "kind": "place", "name": "老石桥"},
                {"id": "debt", "kind": "thread", "name": "人情"},
            ],
            "events": [
                {"key": "saved", "title": "救出艾琳", "summary": "你把艾琳拉上岸。",
                 "importance": "major", "participants": ["player", "elin"],
                 "place": "bridge",
                 "threads": [{"id": "debt", "effect": "opened"}],
                 "disclosure": "known"},
                {"key": "watcher", "title": "暗处的注视", "summary": "有人看见了。",
                 "participants": ["elin"], "disclosure": "hidden"},
            ],
        }, action="把她拉上岸"),
        turn_entry(5, {
            "events": [
                {"key": "repaid", "title": "艾琳还了人情", "summary": "她记得那一天。",
                 "participants": ["player", "elin"],
                 "threads": [{"id": "debt", "effect": "resolved"}],
                 "echoes": ["event:1:saved"], "disclosure": "known"},
            ],
        }),
        turn_entry(9, {
            "events": [
                {"key": "ending", "title": "落幕", "summary": "她陪你走完最后一程。",
                 "participants": ["player", "elin"], "disclosure": "known"},
            ],
        }),
    ]


def keepsake(cites, kp_id="k1", title="石桥下的那一天", thought="一切由此开始"):
    return {"id": kp_id, "kind": "echo", "title": title, "thought": thought,
            "cites": cites, "entities": [], "turn": 0, "spoiler": False,
            "excerpt": ""}


def make_card(cites=("event:1:saved", "event:5:repaid"), *, ended_turn=0):
    index = mg.build_index(life_chronicle())
    return sc.build_draft(index, keepsake(list(cites)), ended_turn=ended_turn,
                          language="zh")


def all_exports(card):
    return {"md": sc.to_markdown(card), "html": sc.to_html(card),
            "svg": sc.to_svg(card)}


# ── the allowlist is the whole card ──────────────────────────────────────


def test_the_card_holds_exactly_the_cited_events_and_their_entities():
    card = make_card()
    assert [e["id"] for e in card["events"]] == ["event:1:saved", "event:5:repaid"]
    assert {e["id"] for e in card["entities"]} == {"elin", "bridge", "debt"}
    # The uninvolved ending event never entered, and neither did anything hidden.
    for text in all_exports(card).values():
        assert "落幕" not in text and "暗处" not in text


def test_a_hidden_event_cannot_be_cited_into_a_card():
    index = mg.build_index(life_chronicle())
    with pytest.raises(sc.StoryCardError):
        sc.build_draft(index, keepsake(["event:1:watcher"]))


def test_edits_can_narrow_but_never_add():
    card = make_card()
    with pytest.raises(sc.StoryCardError):
        sc.apply_edits(card, {"events": {"event:9:ending": True}})
    with pytest.raises(sc.StoryCardError):
        sc.apply_edits(card, {"entities": {"stranger": {"included": True}}})
    with pytest.raises(sc.StoryCardError):
        sc.apply_edits(card, {"order": ["event:1:saved"]})  # dropping via order


def test_reorder_keeps_turn_numbers_untouched():
    card = make_card()
    sc.apply_edits(card, {"order": ["event:5:repaid", "event:1:saved"]})
    by_id = {e["id"]: e["turn"] for e in card["events"]}
    assert by_id == {"event:1:saved": 1, "event:5:repaid": 5}
    assert [e["id"] for e in card["events"]] == ["event:5:repaid", "event:1:saved"]


# ── §12.3: removing a node removes its edges everywhere ──────────────────


def test_excluding_an_entity_takes_its_edges_with_it():
    card = make_card()
    assert any(e["from"] == "elin" for e in sc.resolve(card)["edges"])
    sc.apply_edits(card, {"entities": {"elin": {"included": False}}})
    view = sc.resolve(card)
    assert not any(e["from"] == "elin" or e["to"] == "elin" for e in view["edges"])
    for text in all_exports(card).values():
        assert "艾琳" not in text, "an excluded entity's name survived in an export"


def test_excluding_an_event_takes_its_edges_and_text():
    card = make_card()
    sc.apply_edits(card, {"events": {"event:5:repaid": False}})
    view = sc.resolve(card)
    ids = {e["id"] for e in view["events"]}
    assert ids == {"event:1:saved"}
    assert not any("repaid" in e["from"] or "repaid" in e["to"] for e in view["edges"])
    for text in all_exports(card).values():
        assert "还了人情" not in text


# ── §12.3: anonymisation covers every surface ─────────────────────────────


def test_a_renamed_entity_leaves_no_trace_of_the_real_name():
    card = make_card()
    sc.apply_edits(card, {
        "title": "那一天",  # keep the name out of the player-authored title
        "entities": {"elin": {"display": "少女A"}},
    })
    for fmt, text in all_exports(card).items():
        assert "艾琳" not in text, f"real name survived in {fmt}"
        assert "少女A" in text
    # The SVG's accessibility text uses the display name too.
    svg = sc.to_svg(card)
    assert "<title>少女A" in svg or ">少女A<" in svg


def test_anonymisation_reaches_summaries_and_titles_written_by_the_narrator():
    card = make_card()
    sc.apply_edits(card, {"entities": {"elin": {"display": "她"}}})
    view = sc.resolve(card)
    (first, second) = view["events"]
    assert "艾琳" not in first["title"] and "艾琳" not in first["summary"]
    assert "艾琳" not in second["title"]


# ── §12.3: spoilers off filters ending content ────────────────────────────


def test_ending_content_is_filtered_until_spoilers_are_shown():
    card = make_card(("event:1:saved", "event:9:ending"), ended_turn=9)
    for text in all_exports(card).values():
        assert "落幕" not in text and "最后一程" not in text
    sc.apply_edits(card, {"showSpoilers": True})
    assert "落幕" in sc.to_markdown(card)


# ── §12.3: the file phones nobody and names nothing ──────────────────────


def test_exports_carry_no_network_no_script_no_run_or_event_ids():
    card = make_card()
    run_id = "a" * 32
    for fmt, text in all_exports(card).items():
        assert "<script" not in text.lower(), f"script in {fmt}"
        assert "token" not in text.lower(), f"token in {fmt}"
        assert run_id not in text
        assert "event:" not in text, f"internal event id leaked into {fmt}"
        # The one URL an SVG needs is its xmlns namespace; nothing else may
        # reference the network.
        urls = re.findall(r"https?://[^\s\"'<>]+", text)
        assert all(u.startswith("http://www.w3.org/") for u in urls), (
            f"network reference in {fmt}: {urls}"
        )


def test_the_export_is_a_pure_function_of_the_draft():
    """§11 Phase 3 bar: 导出内容严格等于预览 allowlist — same draft, same bytes."""
    card = make_card()
    sc.apply_edits(card, {"entities": {"elin": {"display": "少女A"}}})
    assert sc.to_html(card) == sc.to_html(card)
    assert sc.to_markdown(card) == sc.to_markdown(card)
    assert sc.to_svg(card) == sc.to_svg(card)


# ── the player's excerpt rides its turn ───────────────────────────────────


def test_an_excerpt_keepsake_replaces_that_turns_summary():
    index = mg.build_index(life_chronicle())
    kp = keepsake(["event:1:saved"])
    kp["kind"] = "excerpt"
    kp["excerpt"] = "洪水漫过桥面时，你伸出了手。"
    kp["turn"] = 1
    card = sc.build_draft(index, kp)
    md = sc.to_markdown(card)
    assert "洪水漫过桥面时" in md
    assert "你把艾琳拉上岸" not in md  # the excerpt replaced the summary


def test_store_roundtrip_and_bad_ids(tmp_path):
    store = sc.StoryCardStore(tmp_path, "b" * 32)
    card = make_card()
    store.put(card)
    assert store.get(card["id"])["title"] == card["title"]
    assert store.get("../escape") is None
    assert store.get("nope") is None
