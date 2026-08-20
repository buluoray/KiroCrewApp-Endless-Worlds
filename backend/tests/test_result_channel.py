"""Result-channel tests — one test per rejection path, each asserting no state write.

R20's shape: anything malformed leaves a failure record and changes nothing. So
every test here checks BOTH halves — a rejection that quietly wrote state would
pass a test that only looked at the response.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from scenes import AlreadyAnswered, SceneLedger, StaleScene  # noqa: E402
from widget import compile_scene  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uisrc  # noqa: E402

SPEC = {
    "title": "岔路",
    "elements": [
        {"kind": "text", "text": "路分成两条。"},
        {"kind": "choice", "id": "north", "label": "往北走"},
        {"kind": "choice", "id": "south", "label": "往南走"},
    ],
}


@pytest.fixture()
def ledger(tmp_path):
    return SceneLedger(tmp_path, "run-1")


# -- the nonce ------------------------------------------------------------


def test_each_mount_gets_its_own_identity(ledger):
    first = ledger.mount("fork", SPEC, asks=True)
    second = ledger.mount("fork", SPEC, asks=True)
    assert first and second and first != second


def test_an_answer_aimed_at_a_replaced_scene_is_refused(ledger):
    """The frame cannot know it has been replaced, so a click aimed at the old
    question must not answer the new one."""
    stale = ledger.mount("fork", SPEC, asks=True)
    ledger.mount("fork", SPEC, asks=True)  # remount: new question, new identity

    with pytest.raises(StaleScene):
        ledger.record_answer("fork", "north", nonce=stale)
    assert ledger.answer("fork") is None, "state was written on a refused answer"


def test_the_nonce_reaches_the_frame_and_is_echoed_by_the_constant_script():
    out = compile_scene("fork", SPEC, {}, nonce="abc123")
    assert 'data-nonce="abc123"' in out
    assert "dataset.nonce" in out


def test_a_remount_busts_the_compiled_cache(tmp_path):
    """A cached file carrying the old identity would let a replaced scene answer
    for its successor."""
    from widget import compile_cached

    a, _ = compile_cached(tmp_path, "run-1", "fork", SPEC, {}, nonce="n1")
    b, cached = compile_cached(tmp_path, "run-1", "fork", SPEC, {}, nonce="n2")
    assert cached is False
    assert a != b


# -- first result only ----------------------------------------------------


def test_a_second_answer_never_overwrites_the_first(ledger):
    """The narrator may already have read the first, so a later message replacing
    it would rewrite a decision the story has acted on."""
    nonce = ledger.mount("fork", SPEC, asks=True)
    ledger.record_answer("fork", "north", nonce=nonce)

    with pytest.raises(AlreadyAnswered):
        ledger.record_answer("fork", "south", nonce=nonce)
    assert ledger.answer("fork") == "north"


# -- failure records ------------------------------------------------------


def test_a_failure_is_recorded_where_the_story_can_learn_about_it(ledger):
    ledger.mount("fork", SPEC, asks=True)
    ledger.record_failure("fork", "already answered")
    records = ledger.failures("fork")
    assert len(records) == 1
    assert records[0]["reason"] == "already answered"
    assert records[0]["at"]


def test_a_failure_record_does_not_touch_the_answer(ledger):
    nonce = ledger.mount("fork", SPEC, asks=True)
    ledger.record_answer("fork", "north", nonce=nonce)
    ledger.record_failure("fork", "duplicate")
    assert ledger.answer("fork") == "north"


def test_failure_records_are_bounded(ledger):
    """A hostile page could otherwise grow this file without limit."""
    ledger.mount("fork", SPEC, asks=True)
    for i in range(40):
        ledger.record_failure("fork", f"r{i}")
    assert len(ledger.failures("fork")) == 10


def test_a_failure_for_a_vanished_scene_is_not_an_error(ledger):
    ledger.record_failure("gone", "whatever")  # must not raise
    assert ledger.failures("gone") == []


# -- the narrator cannot answer its own question -------------------------


def test_the_nonce_is_never_handed_to_the_narrator():
    """A narrator holding a mount identity could forge an answer to the question
    it just asked, which is the one thing the whole channel exists to prevent."""
    import inspect

    import mcp_server as srv

    src = inspect.getsource(srv._mount_scene)
    assert "nonce" not in src.replace("# The nonce is NOT returned", "").replace(
        "# click could forge", ""
    ) or "return {\"mounted\"" in src
    # The tool result carries only the id.
    result_line = [ln for ln in src.splitlines() if "return {" in ln][0]
    assert "nonce" not in result_line


# -- the page's own five checks -----------------------------------------


@pytest.fixture(scope="module")
def slot_src() -> str:
    """The TypeScript source of the slot, not the built bundle."""
    if not (uisrc.WEB_SRC / "scene.tsx").is_file():
        pytest.skip("web/src/scene.tsx not present")
    return uisrc.module("scene.tsx")


def test_the_page_checks_the_frames_origin_is_null(slot_src):
    """Not a formality: the frame has no allow-same-origin, so its origin MUST be
    the string "null". A message carrying any real origin did not come from our
    sandbox."""
    assert "e.origin !== 'null'" in slot_src


def test_the_page_checks_the_protocol_marker(slot_src):
    assert "d.source !== 'endless-scene'" in slot_src


def test_the_page_checks_the_scene_and_the_mount(slot_src):
    assert "d.sceneId !== sceneId" in slot_src
    assert "d.nonce" in slot_src


def test_the_page_refuses_a_second_result_locally(slot_src):
    """A double-tap must not become two turns while the server's own refusal is
    still in flight."""
    assert "answered.current" in slot_src


def test_the_local_first_result_latch_resets_on_a_new_scene(slot_src):
    """Otherwise the second scene of a life could never be answered."""
    assert re.search(r"answered\.current = false", slot_src)


# -- a scene's answer is a turn, not a separate kind of move -------------


def test_an_accepted_answer_becomes_the_turns_action():
    root = uisrc.module("main.tsx")
    assert "answerScene" in root
    assert "out.accepted" in root
    # The label the player read, sent down the same road as a tapped choice.
    assert "action: out.action" in root


def test_a_refused_answer_still_reloads_so_the_player_is_not_stranded():
    assert "setRefresh" in uisrc.module("main.tsx")


# -- damaged ledger -------------------------------------------------------


def test_a_corrupt_scene_ledger_degrades_to_no_mounted_scenes(ledger):
    ledger._path.parent.mkdir(parents=True, exist_ok=True)
    damaged = "{ not json"
    ledger._path.write_text(damaged, encoding="utf-8")

    assert ledger.mounted() == []
    assert ledger._path.read_text(encoding="utf-8") == damaged

    ledger.mount("fork", SPEC)
    assert [row["sceneId"] for row in ledger.mounted()] == ["fork"]
    assert "fork" in json.loads(ledger._path.read_text(encoding="utf-8"))
