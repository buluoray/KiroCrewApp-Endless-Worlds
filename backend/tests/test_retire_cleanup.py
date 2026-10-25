"""Guards on what retiring a narrator conversation removes, and when.

Two faults a real pod test found:

* A retired conversation left kiro-cli's KAS session directory behind
  (``<kiro home>/sessions/<workspace hash>/<sid>/``): only the classic
  ``sessions/cli/<sid>.json(l)`` pair was ever removed.
* A rotation asked ~2 s after a commit closed the previous conversation while its
  turn was still finishing, so core refused that turn's last history write and
  the turn never got a usage row.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import narrator  # noqa: E402
from narrator import (  # noqa: E402
    APP_NAME,
    MEMORY_MODE,
    narrator_slot_key,
    reset_narrator_conversation,
)
from store import RunStore  # noqa: E402

SID = "sess_c92712a5-ac2c-4bd0-b45c-73c17b280122"
OTHER = "sess_a76b269f-7ef0-45d6-9bc2-d7fff0250b01"


# ── the KAS layout ──────────────────────────────────────────────────────────


def _kas_home(tmp_path: Path) -> Path:
    """A kiro home holding two KAS sessions in one workspace and one in another."""
    home = tmp_path / "kiro"
    for workspace, sid in (("1962d6a3a30e7eb9", SID), ("1962d6a3a30e7eb9", OTHER)):
        d = home / "sessions" / workspace / sid
        d.mkdir(parents=True)
        (d / "messages.jsonl").write_text("{}\n")
        (d / "session.json").write_text(json.dumps({"id": sid}))
    index = home / "session-index" / "1962d6a3a30e7eb9.jsonl"
    index.parent.mkdir(parents=True)
    index.write_text(
        "".join(
            json.dumps({"op": "add", "sessionPath": f"1962d6a3a30e7eb9/{s}", "at": 1}) + "\n"
            for s in (SID, OTHER)
        )
    )
    (home / "sessions" / "cli").mkdir()
    return home


def test_a_retired_sid_loses_its_kas_directory_and_nothing_else(tmp_path):
    home = _kas_home(tmp_path)
    root = home / "sessions"

    removed = narrator._unlink_kas_session(root, SID)

    assert not (root / "1962d6a3a30e7eb9" / SID).exists(), "the retired session must go"
    assert (root / "1962d6a3a30e7eb9" / OTHER / "messages.jsonl").is_file(), (
        "another session in the same workspace must never be touched"
    )
    assert root / "1962d6a3a30e7eb9" / SID in removed
    rows = [
        json.loads(line)
        for line in (home / "session-index" / "1962d6a3a30e7eb9.jsonl").read_text().splitlines()
    ]
    assert rows[-1]["op"] == "remove"
    assert rows[-1]["sessionPath"] == f"1962d6a3a30e7eb9/{SID}"
    assert [r for r in rows if r["op"] == "remove"] == [rows[-1]], "one remove, for this sid"


def test_a_directory_holding_unknown_files_is_left_in_place(tmp_path):
    home = _kas_home(tmp_path)
    target = home / "sessions" / "1962d6a3a30e7eb9" / SID
    (target / "notes.txt").write_text("not KAS's")

    narrator._unlink_kas_session(home / "sessions", SID)

    assert (target / "notes.txt").is_file(), "only KAS's own files are removed"
    assert not (target / "messages.jsonl").exists()


@pytest.mark.parametrize("bad", ["", "..", "../x", "a/b", "sess", "*"])
def test_an_unsafe_sid_touches_nothing(tmp_path, bad):
    home = _kas_home(tmp_path)
    assert narrator._unlink_kas_session(home / "sessions", bad) == []
    assert (home / "sessions" / "1962d6a3a30e7eb9" / SID / "messages.jsonl").is_file()


def test_a_symlinked_session_directory_is_not_followed(tmp_path):
    home = _kas_home(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "messages.jsonl").write_text("keep")
    ws = home / "sessions" / "aaaa000011112222"
    ws.mkdir()
    (ws / "sess_deadbeef-0000").symlink_to(outside, target_is_directory=True)

    narrator._unlink_kas_session(home / "sessions", "sess_deadbeef-0000")

    assert (outside / "messages.jsonl").read_text() == "keep"


# ── the whole retirement, end to end ────────────────────────────────────────


class _Slot:
    def __init__(self, key):
        self.key = key
        self._app = APP_NAME
        self.memory_mode = MEMORY_MODE
        self.project = ""
        self.running = False


class _Sessions:
    def __init__(self, sid):
        self._sid = sid

    def mapped_sid(self, key):
        return self._sid

    def forget_conversation(self, key):
        sid, self._sid = self._sid, ""
        return sid


class _State:
    def __init__(self, sid=SID):
        self.slots: dict = {}
        self._slots = self.slots
        self.sessions = _Sessions(sid)

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, **_kw):
        self.slots.setdefault(name, _Slot(name))
        return self.slots[name]


@pytest.fixture()
def store(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    return RunStore(AppStorage(APP_NAME, data), data)


@pytest.fixture()
def run(store):
    return store.create_run({"turn": 3, "worldId": "w"}, {"worldId": "w", "title": "a life"})


@pytest.fixture()
def core(tmp_path, monkeypatch):
    """Core's classic helper recorded, and the KAS root pointed at a temp home."""
    unlinked: list[str] = []
    transfer = types.ModuleType("kiro_crew.dashboard.session_transfer")
    transfer._unlink_layer_b_files = unlinked.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kiro_crew.dashboard.session_transfer", transfer)
    home = _kas_home(tmp_path)
    monkeypatch.setattr(narrator, "_kas_sessions_root", lambda: home / "sessions")
    return types.SimpleNamespace(unlinked=unlinked, home=home)


def test_a_rotation_removes_both_provider_layouts_of_the_old_sid(store, run, core):
    state = _State()
    state.slots[narrator_slot_key(run)] = _Slot(narrator_slot_key(run))

    assert asyncio.run(reset_narrator_conversation(state, store, run))

    assert core.unlinked == [SID], "the classic layout is still removed"
    ws = core.home / "sessions" / "1962d6a3a30e7eb9"
    assert not (ws / SID).exists(), "the KAS layout must go with it"
    assert (ws / OTHER).is_dir(), "and no other session"
    assert store.stale_conversations(run) == []


# ── a conversation whose turn is still finishing ────────────────────────────


def test_a_busy_old_conversation_is_kept_until_its_turn_ends(store, run, core, monkeypatch):
    monkeypatch.setattr(narrator, "_RETIRE_POLL_SECS", 0.01)
    state = _State()
    old_key = narrator_slot_key(run)
    old = _Slot(old_key)
    old.running = True  # the month committed; the narrator is still finishing
    state.slots[old_key] = old

    async def scenario():
        await reset_narrator_conversation(state, store, run)
        # Rotated: the life is on a new key, but the old slot is not closed yet.
        assert store.conversation_number(run) == 1
        assert old_key in state.slots, "closing it now refuses its last history write"
        assert store.stale_conversations(run) == [0]
        assert (core.home / "sessions" / "1962d6a3a30e7eb9" / SID).is_dir()
        waiter = narrator._RETIRE_WAITERS.get(run)
        assert waiter is not None, "something must retire it once the turn ends"
        old.running = False
        await asyncio.wait_for(waiter, timeout=5)

    asyncio.run(scenario())
    assert old_key not in state.slots, "retired once its turn ended"
    assert store.stale_conversations(run) == []
    assert not (core.home / "sessions" / "1962d6a3a30e7eb9" / SID).exists()
    assert run not in narrator._RETIRE_WAITERS


def test_deleting_a_life_still_closes_a_busy_conversation(store, run, core):
    state = _State()
    key = narrator_slot_key(run)
    busy = _Slot(key)
    busy.running = True
    state.slots[key] = busy

    asyncio.run(narrator.retire_all_conversations(state, run, [0]))

    assert key not in state.slots, "nothing a deleted life writes is kept"
