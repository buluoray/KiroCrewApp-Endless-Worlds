"""Guards on the turn in flight.

The symptom that started this: ask for a life's first turn, leave the page while
the narrator is writing it, come back — and the life looks like one nobody ever
asked about. The world being made was gone.

The cause was that ``advance_turn`` wrote NOTHING between reading the state and
polling for the commit. So the record of "this month is being written" lived only
in an HTTP request's poll loop and in React state, and both die when the page does.

Underneath the missing-progress wart sat a real correctness bug. Idempotence is
per ``(runId, turn)`` and only protects a turn that has LANDED; until the commit,
the store is byte-for-byte indistinguishable from never-asked. So coming back and
tapping again dispatched a SECOND narration of the same month, with two writers
racing for one commit. Fixing the display without fixing that would have left the
worse half in place.

The load-bearing invariant is an ORDERING: the record is written before the
narrator is spoken to. Reversing those two lines leaves every symptom intact —
tests pass, the UI shows progress, a normal turn behaves identically — and puts the
whole bug back, because the window being closed is precisely the one between
dispatch and commit. Hence a test that observes the store from inside dispatch.
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from narrator import APP_NAME, MEMORY_MODE  # noqa: E402
from store import RunStore  # noqa: E402
from turn import (  # noqa: E402
    PENDING_STALE_SECS,
    TURN_DEADLINE_SECS,
    advance_turn,
    generating,
)


class FakeSlot:
    def __init__(self, key):
        self.key = key
        self._app = APP_NAME
        self.memory_mode = MEMORY_MODE
        self.project = ""


class FakeState:
    def __init__(self):
        self.slots = {}

    def get_slot(self, key):
        return self.slots.get(key)

    def get_or_create_slot(self, *, name, agent="", app="", memory_mode=None, **kw):
        slot = FakeSlot(name)
        slot.memory_mode = memory_mode or "persistent"
        slot._app = app
        self.slots[name] = slot
        return slot


@pytest.fixture()
def store(tmp_path):
    from kiro_crew.apps.app_storage import AppStorage

    data = tmp_path / "data"
    data.mkdir()
    return RunStore(AppStorage(APP_NAME, data), data)


@pytest.fixture()
def run(store):
    return store.create_run(
        {"turn": 0, "worldId": "w", "status": "awaiting-opening"},
        {"worldId": "w", "title": "a life"},
    )


def _commits(store, run_id, turn=1, prose="the snow stopped"):
    """A dispatcher that behaves like a narrator who commits immediately."""

    def dispatch(state, slot, prompt):
        state_now = store.read_state(run_id)
        store.commit_state(run_id, {**state_now, "turn": turn})
        store.append_turn(run_id, {"turn": turn, "prose": prose})
        return True

    return dispatch


def _silent(calls: list):
    """A dispatcher that is spoken to and never commits — a narrator still working,
    or one that died."""

    def dispatch(state, slot, prompt):
        calls.append(prompt)
        return True

    return dispatch


async def _advance(store, run_id, dispatch, **kw):
    return await advance_turn(
        state_obj=FakeState(),
        store=store,
        run_id=run_id,
        rulebook="r",
        dispatch=dispatch,
        deadline_secs=kw.pop("deadline_secs", 0.4),
        **kw,
    )


# ── the ordering ────────────────────────────────────────────────────────────


def test_the_record_exists_before_the_narrator_is_spoken_to(store, run):
    """The invariant, observed from inside dispatch.

    Written this way and not as a source scan because the two lines can be swapped
    without changing anything else that is observable: the record still appears, the
    turn still lands, every other test still passes. The only moment that can tell
    the difference is the instant the narrator is handed the prompt.
    """
    seen: dict[str, object] = {}

    def dispatch(state, slot, prompt):
        seen["pending"] = store.read_pending(run)
        return True

    asyncio.run(_advance(store, run, dispatch))

    assert seen["pending"] is not None, (
        "the narrator was asked before anything on disk recorded the asking; a "
        "request that dies here is indistinguishable from one never made"
    )
    assert seen["pending"]["turn"] == 1


def test_the_record_names_the_slot_that_was_asked(store, run):
    """The binding. The key is derivable from the run id, so this is not a lookup
    path — it is a witness of which slot was actually spoken to, which survives the
    key scheme changing and tells a reader whether to believe the record."""
    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))

    pending = store.read_pending(run)
    assert pending is not None
    assert pending["slot"], "the record does not say which slot is writing"
    assert run in pending["slot"], "the slot must be this run's, not a shared one"


# ── what survives a dropped request ─────────────────────────────────────────


def test_a_dropped_request_leaves_the_record_standing(store, run):
    """The whole point. The narrator may still commit after the request gives up, so
    the evidence that a month is being written must outlive the request."""
    calls: list[str] = []
    out = asyncio.run(_advance(store, run, _silent(calls)))

    assert out.advanced is False
    assert out.reason == "timeout"
    assert store.read_pending(run) is not None, (
        "clearing the record on timeout throws away the only evidence the month is "
        "being written"
    )


def test_a_returning_player_is_told_the_month_is_being_written(store, run):
    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))

    live = generating(store, run)
    assert live is not None
    assert live["turn"] == 1
    assert live["slot"]


def test_generating_stage_advances_from_reading_to_writing(store, run):
    """The in-flight stage the UI shows: 'reading' until the narrator calls
    read_runtime (which stamps readAt), then 'writing' as it composes the month."""
    asyncio.run(_advance(store, run, _silent([])))
    assert generating(store, run)["stage"] == "reading"
    store.note_runtime_read(run, turn=1)
    assert generating(store, run)["stage"] == "writing"


def test_a_landed_turn_leaves_nothing_in_flight(store, run):
    out = asyncio.run(_advance(store, run, _commits(store, run)))

    assert out.advanced is True
    assert store.read_pending(run) is None
    assert generating(store, run) is None


# ── the correctness half: no second narrator ────────────────────────────────


def test_asking_twice_while_in_flight_does_not_dispatch_twice(store, run):
    """The bug under the wart. Two narrations of one month, racing for one commit,
    is the failure a progress spinner would have hidden."""
    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))
    assert len(calls) == 1

    second = asyncio.run(_advance(store, run, _silent(calls)))

    assert len(calls) == 1, f"the narrator was asked {len(calls)} times for one turn"
    assert second.advanced is False
    assert second.reason == "generating", (
        "a caller must be able to tell 'someone is writing this' from 'it timed out'"
    )


def test_a_returning_request_attaches_to_the_first_narrators_turn(store, run):
    """Not dispatching is not the same as not waiting.

    A player who comes back while the first narrator is still working should receive
    that narrator's month — the same turn, not a second one and not an error. So the
    commit has to land *during* the second request's wait, which is the only way to
    tell "attached to the work in flight" from "gave up and happened to see it
    later".
    """
    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))
    assert len(calls) == 1, "the first request must have asked"

    async def race():
        async def the_first_narrator_finishes():
            await asyncio.sleep(0.1)
            state = store.read_state(run)
            store.commit_state(run, {**state, "turn": 1})
            store.append_turn(run, {"turn": 1, "prose": "the snow stopped"})

        out, _ = await asyncio.gather(
            _advance(store, run, _silent(calls), deadline_secs=3.0),
            the_first_narrator_finishes(),
        )
        return out

    out = asyncio.run(race())

    assert out.advanced is True
    assert out.prose == "the snow stopped"
    assert len(calls) == 1, (
        f"the narrator was asked {len(calls)} times for one month; the returning "
        "request should have attached to the work already in flight"
    )
    assert store.read_pending(run) is None, "a landed turn must leave nothing behind"


# ── the record is judged, not trusted ───────────────────────────────────────


def test_a_stale_record_does_not_wedge_the_life_forever(store, run):
    """A gateway that dies between the mark and the commit leaves a record nobody
    will ever clear. A life permanently unable to take its next turn is worse than a
    duplicate prompt, so age is the escape hatch."""
    store.mark_pending(run, turn=1, slot="endless-run-x")
    stale = store.read_pending(run)
    stale["askedAt"] = time.time() - (PENDING_STALE_SECS + 60)
    store._kv.set(store._pending_key(run), stale)

    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))

    assert len(calls) == 1, "an abandoned record must not block the next attempt"


def test_the_staleness_bound_exceeds_the_request_deadline():
    """Otherwise a turn that merely ran past one request's deadline is judged
    abandoned, and the next request dispatches the second narrator this whole
    mechanism exists to prevent."""
    assert PENDING_STALE_SECS > TURN_DEADLINE_SECS * 2


def test_a_record_for_another_turn_is_ignored(store, run):
    """A leftover marker from an earlier month must not make the current one look
    busy."""
    store.mark_pending(run, turn=7, slot="endless-run-x")

    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))

    assert len(calls) == 1
    assert store.read_pending(run)["turn"] == 1, "the marker was not replaced"


def test_a_record_with_no_timestamp_is_not_believed(store, run):
    """Hand-edited or half-written records exist. An unjudgeable one is treated as
    absent rather than as authoritative, because the failure of believing it is a
    life that can never advance."""
    store._kv.set(store._pending_key(run), {"turn": 1, "slot": "s"})

    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))
    assert len(calls) == 1


# ── it must not disturb the crash story ─────────────────────────────────────


def test_marking_a_turn_in_flight_does_not_spend_the_rollback_point(store, run):
    """Why the record is its own key and not a field in the state.

    ``commit_state`` copies the outgoing state to the rollback slot. Writing
    bookkeeping through it would spend the ability to roll back to the last
    NARRATED state on a note about waiting — so a crash mid-turn would restore to
    "we were waiting" instead of to the last real month.
    """
    store.commit_state(run, {"turn": 1, "worldId": "w"})
    store.commit_state(run, {"turn": 2, "worldId": "w"})

    store.mark_pending(run, turn=3, slot="endless-run-x")

    assert store.rollback(run)["turn"] == 1, (
        "the in-flight record moved the rollback target"
    )


def test_the_record_lives_outside_the_state(store, run):
    """The narrator's commit replaces the state wholesale, carrying only
    RESERVED_STATE_KEYS forward. A marker inside the state would have its lifetime
    decided by the content-carry-forward rule, which is about worlds."""
    store.mark_pending(run, turn=1, slot="endless-run-x")
    assert "pending" not in store.read_state(run)

    from mcp_server import RESERVED_STATE_KEYS

    assert "pending" not in RESERVED_STATE_KEYS


def test_clearing_a_record_that_is_not_there_is_harmless(store, run):
    """Called on every successful turn, including the many where nothing was ever
    marked (a turn that landed inside the first poll)."""
    store.clear_pending(run)
    assert store.read_pending(run) is None


# ── what the page does with it ───────────────────────────────────────────────
#
# Read from the TypeScript source: the app has no JS test runner, so these check
# the code a person edits rather than the bundle Vite emits.


def test_the_page_converges_without_the_player_doing_anything():
    """Coming back mid-generation must resolve on its own.

    A page that shows "being written" and then waits for a tap has moved the
    problem rather than fixed it: the player still cannot tell whether the app is
    working or stuck, which is the state this whole change exists to end.
    """
    import uisrc

    src = uisrc.module("play.tsx")
    assert "setInterval" in src, "nothing re-reads a life that is being written"
    # The poll is gated on something being in flight — a turn being written, or a
    # freshly-created life awaiting its opening (its "generating" mark can land a
    # beat after the page loads).
    poll = re.search(r"if \(!generating[^\n]*return[^\n]*\n(.*?)\n  \}, \[", src, re.S)
    assert poll, "the poll is not gated on there being something in flight"
    assert "clearInterval" in poll.group(1), (
        "an uncleared interval outlives the view — and this app mounts into the "
        "dashboard's own document, so it outlives the page too"
    )


def test_waiting_is_not_only_a_local_boolean():
    """The bug in one line: waiting used to be React state, so it died with the page
    that owned it.

    Asserted on the PROPERTY — that the page's notion of busy is derived from the
    server's record — rather than on a spelling. An earlier version of this test
    pinned ``const busy = \\w+ || generating`` and went red when the local half
    became ``!!tapped``, which is a test noticing a refactor rather than a
    regression.
    """
    import uisrc

    src = uisrc.module("play.tsx")
    decl = re.search(r"const busy = ([^\n]+)", src)
    assert decl, "the page has no single notion of being busy"
    assert "generating" in decl.group(1), (
        "the page must treat a narrator recorded on the server as busy, not just "
        f"its own tap; found: {decl.group(1)}"
    )


def test_a_life_being_written_is_not_shown_as_one_that_stalled():
    """Ordering, and it is load-bearing: a life mid-generation is ALSO
    ``awaitingOpening``, so whichever branch comes first wins. 'not born yet' next
    to a spinner-less row is exactly the message that made the player tap again."""
    import uisrc

    for where in ("library.tsx", "rail.tsx"):
        src = uisrc.module(where)
        gen = src.index("generating")
        unborn = src.index("life.unborn")
        assert gen < unborn, (
            f"{where} checks awaitingOpening before generating, so a month being "
            "written reads as a life that never started"
        )
