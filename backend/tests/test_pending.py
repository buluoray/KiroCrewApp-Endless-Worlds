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
    BACKDROP_STALE_SECS,
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
    # A caller passing `state` models one LIVE gateway across several requests —
    # the narrator slot from the first call still exists on the second. A fresh
    # FakeState per call now models a gateway RESTART: the slot is gone, which
    # advance_turn treats as proof the writer died (fresh_slot recovery).
    state_obj = kw.pop("state", None) or FakeState()
    return await advance_turn(
        state_obj=state_obj,
        store=store,
        run_id=run_id,
        rulebook="r",
        dispatch=dispatch,
        inline_wait_secs=kw.pop("inline_wait_secs", 0.4),
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
    assert out.reason == "writing"
    assert store.read_pending(run) is not None, (
        "clearing the record on timeout throws away the only evidence the month is being written"
    )


def test_an_ask_this_request_dispatched_reports_itself_as_taken(store, run):
    """The two un-advanced reasons are not interchangeable.

    ``writing`` says: this request recorded the ask, dispatched it, and stopped
    waiting — the month is coming and must NOT be asked for again. That is what lets
    a caller spend the player's words and hand the rest to a poll. Reporting the
    ordinary handover as ``generating`` instead would keep offering to resend an ask
    already in flight, which is the double-narration the pending record exists to
    prevent.
    """
    calls: list[str] = []
    out = asyncio.run(_advance(store, run, _silent(calls)))

    assert len(calls) == 1, "the ask was dispatched by THIS request"
    assert out.reason == "writing"
    assert out.advanced is False, "nothing committed inside the request"
    assert out.turn == 0, "the life is still on the month it was on"
    pending = store.read_pending(run)
    assert pending is not None and int(pending["turn"]) == 1, (
        "the ask must be on disk, because the poll that finishes this turn reads it"
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


def test_a_request_that_never_answered_does_not_freeze_the_page():
    """The reason a committed month could still read as one that never came.

    The server finishes a turn whether or not anyone is still holding the socket, so
    a request that does not answer proves nothing — and the page must not conclude
    anything from it. Two properties make that true: the page's notion of a stalled
    ask is DERIVED (from the server's record every poll) rather than latched by a
    request, and the reload runs on every path out of the ask, including the one
    where the request threw. Without the second, the page sat with a permanent "this
    page did not come through" over a month that had in fact been written, and only
    remounting the view — leaving the life and re-entering — found it.
    """
    import uisrc

    src = uisrc.module("play.tsx")
    assert "setStalled" not in src, (
        "a latched failure flag cannot be corrected by the server; the page must "
        "derive the verdict from what the run reports"
    )
    assert re.search(r"const stalled = ", src), "the stall verdict is not derived at all"

    take = re.search(r"const take = async \(.*?\n  \}\n", src, re.S)
    assert take, "the per-turn ask is not where this test thinks it is"
    body = take.group(0)
    assert body.count("await load()") == 1, (
        "one reload, reached from every path — a second copy means one of them is a "
        "branch that can be skipped"
    )
    # At the ask's OWN indentation, which is what makes it unconditional. Nested one
    # level deeper it sits inside the try or the catch, and the path that does not
    # run it is exactly the path where the page has the least idea what happened.
    assert re.search(r"\n    await load\(\)\n", body), (
        "the reload must sit at the top level of the ask, not inside a branch a "
        "thrown or refused request can skip"
    )


def test_a_birth_is_fired_and_handed_off_never_waited_on():
    """A life's first turn is the heaviest a life ever asks for, and nothing about
    holding its request open helps: the ask is recorded before the narrator is
    spoken to, and the arranging screen polls that record. Awaiting it instead means
    a birth that outran the request's inline wait reads as one that never started."""
    import uisrc

    for name in ("play.tsx", "opening.tsx", "main.tsx"):
        src = uisrc.module(name)
        assert "await api.openRun" not in src, (
            f"{name} holds a request open for a whole birth; fire it and let the "
            "arranging screen's poll finish it"
        )


# ── the correctness half: no second narrator ────────────────────────────────


def test_asking_twice_while_in_flight_does_not_dispatch_twice(store, run):
    """The bug under the wart. Two narrations of one month, racing for one commit,
    is the failure a progress spinner would have hidden."""
    calls: list[str] = []
    gateway = FakeState()  # ONE live gateway across both requests
    asyncio.run(_advance(store, run, _silent(calls), state=gateway))
    assert len(calls) == 1

    second = asyncio.run(_advance(store, run, _silent(calls), state=gateway))

    assert len(calls) == 1, f"the narrator was asked {len(calls)} times for one turn"
    assert second.advanced is False
    assert second.reason == "generating", (
        "an ask that was NOT taken must not report itself as one that is being "
        "written: the record in flight may name a different action entirely, and a "
        "caller that reads this as accepted throws away words the player still owns"
    )
    assert second.reason != "writing", (
        "'writing' is reserved for an ask this request itself recorded"
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
    gateway = FakeState()  # ONE live gateway across both requests
    asyncio.run(_advance(store, run, _silent(calls), state=gateway))
    assert len(calls) == 1, "the first request must have asked"

    async def race():
        async def the_first_narrator_finishes():
            await asyncio.sleep(0.1)
            state = store.read_state(run)
            store.commit_state(run, {**state, "turn": 1})
            store.append_turn(run, {"turn": 1, "prose": "the snow stopped"})

        out, _ = await asyncio.gather(
            _advance(store, run, _silent(calls), inline_wait_secs=3.0, state=gateway),
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


def test_a_poll_in_the_commit_gap_returns_the_wanted_prose_not_the_previous(store, run):
    """A commit is two writes — the turn counter, then the chronicle line. A poll
    landing between them must keep waiting for the wanted turn's own entry, not
    hand back ``chronicle[-1]`` (the PREVIOUS month) as if it were this one."""
    state = store.read_state(run)
    store.commit_state(run, {**state, "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "old prose"})

    def half_committed(state_obj, slot, prompt):
        # A narrator mid-commit: the counter moves, the chronicle line has not.
        s = store.read_state(run)
        store.commit_state(run, {**s, "turn": 2})
        return True

    async def scenario():
        task = asyncio.ensure_future(_advance(store, run, half_committed, inline_wait_secs=2.5))
        # Long enough that polls land in the gap first (poll tick is 0.25s),
        # generous enough not to flake on a slow runner.
        await asyncio.sleep(0.6)
        store.append_turn(run, {"turn": 2, "prose": "new prose"})
        return await task

    out = asyncio.run(scenario())
    assert out.advanced and out.turn == 2
    assert out.prose == "new prose", (
        f"got {out.prose!r} — a poll in the counter/chronicle gap returned the "
        "previous month's text as this month's"
    )


def test_a_dead_writers_record_is_recovered_without_waiting_out_the_age_bound(store, run):
    """A gateway restart takes every narrator session with it. The retry that
    follows creates a FRESH slot — proof the recorded writer is gone — and must
    re-dispatch immediately instead of wedging the life for PENDING_STALE_SECS."""
    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))  # writer dies with its gateway
    assert len(calls) == 1
    assert store.read_pending(run) is not None, "the record the crash leaves behind"

    # A NEW FakeState models the restarted gateway: the slot must be re-created.
    retried = asyncio.run(_advance(store, run, _silent(calls)))

    assert len(calls) == 2, "the retry must re-dispatch, not attach to a corpse"
    assert retried.reason != "already", "nothing was committed; this is a fresh ask"


def test_generating_carries_the_players_action_back_to_the_page(store, run):
    """The pending record stores what the player asked for; `generating()` must
    hand it back so a page that navigated away and returned can still show WHICH
    choice is being written — not an anonymous progress bar."""
    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls), action="take up the ledger"))
    g = generating(store, run)
    assert g is not None
    assert g["action"] == "take up the ledger"


def test_generating_reports_nothing_when_the_recorded_slot_is_gone(store, run):
    """The read path: a pending record whose slot no longer exists must not show
    'a month is being written' (and block deletion) for the full age bound."""
    calls: list[str] = []
    live_gateway = FakeState()
    asyncio.run(_advance(store, run, _silent(calls), state=live_gateway))
    assert generating(store, run, live_gateway) is not None, "writer alive: report it"

    restarted_gateway = FakeState()  # no slots survive a restart
    assert generating(store, run, restarted_gateway) is None

    # Read-only: the record itself is left for the advance path to clear.
    assert store.read_pending(run) is not None


def test_generating_without_a_state_object_keeps_the_age_only_judgement(store, run):
    calls: list[str] = []
    asyncio.run(_advance(store, run, _silent(calls)))
    assert generating(store, run) is not None


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

    assert store.rollback(run)["turn"] == 1, "the in-flight record moved the rollback target"


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


def test_a_committed_page_stays_generating_while_its_requested_art_is_pending(store, run):
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "the gate closed"})
    store.request_backdrop(run, turn=1, brief="a closed red gate")

    live = generating(store, run)
    assert live is not None
    assert live["turn"] == 1
    assert live["stage"] == "painting"
    assert live["steps"] == 5, "painting must stay at the existing 92% progress cap"
    assert live["lastTool"] == "endless_paint_backdrop"


def test_art_that_will_never_arrive_stops_holding_the_page_hostage(store, run):
    """The freeze this ceiling exists for.

    The request record is cleared ONLY by an exact-turn commit, so a recovery task
    that died with its gateway leaves one nobody will ever clear. Unbounded, the
    waiting state never ended: the play view disables every choice while
    generating, so the reader sat on a page it had already been shown with every
    control dead, no retry, and delete refusing with ``turn_in_flight``.
    """
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "the gate closed"})
    store.request_backdrop(run, turn=1, brief="a closed red gate")
    store.update_backdrop_request(run, askedAt=time.time() - (BACKDROP_STALE_SECS + 1))

    assert generating(store, run) is None, (
        "a backdrop request past the ceiling still reports the page as generating, "
        "which disables every choice on a page the player can already read"
    )


def test_a_backdrop_request_inside_the_ceiling_still_reports_painting(store, run):
    """The other side of the boundary — the ceiling must not cancel ordinary waits."""
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "the gate closed"})
    store.request_backdrop(run, turn=1, brief="a closed red gate")
    store.update_backdrop_request(run, askedAt=time.time() - (BACKDROP_STALE_SECS - 30))

    live = generating(store, run)
    assert live is not None and live["stage"] == "painting"


def test_a_backdrop_request_with_no_timestamp_is_not_believed(store, run):
    """A record with no readable ``askedAt`` cannot be aged, so it cannot be trusted
    to hold the page: an unagexable record is the unbounded wait by another name."""
    store.commit_state(run, {**store.read_state(run), "turn": 1})
    store.append_turn(run, {"turn": 1, "prose": "the gate closed"})
    store.request_backdrop(run, turn=1, brief="a closed red gate")
    store.update_backdrop_request(run, askedAt="not a number")

    assert generating(store, run) is None


def test_the_page_release_and_the_waiting_state_read_one_ceiling():
    """Two ceilings for one transaction is the defect, not an implementation detail.

    ``routes._backdrop_is_pending`` released the committed page at 900s while
    ``turn.generating`` had no bound at all, so the page came back with its controls
    still dead. A test on the values alone would pass again the moment someone
    edits one number, so this pins the IDENTITY: routes must read the shared
    constant, not restate it.
    """
    import routes

    assert routes._BACKDROP_STALE_SECS is BACKDROP_STALE_SECS, (
        "routes restates the backdrop ceiling instead of importing it; the two can "
        "drift apart again and re-freeze a life"
    )


# ── the tool trail: which calls, in what order ──────────────────────────────
#
# ``toolCalls`` already answered "how many". It cannot answer the question a
# turn that went wrong actually raises: whether the narrator wrote without
# reading first, painted twice, or never reached advance_turn at all. The trail
# lives on the in-flight record and is folded into the turn's perf row at
# commit, because ``clear_pending`` is moments away and this is the only copy.


def test_the_tools_are_recorded_in_the_order_they_were_called(store, run):
    store.mark_pending(run, turn=1, slot="s")
    for tool in ("endless_read_runtime", "endless_paint_backdrop", "endless_advance_turn"):
        store.note_tool_call(run, tool)

    pending = store.read_pending(run)
    assert pending["tools"] == [
        "endless_read_runtime",
        "endless_paint_backdrop",
        "endless_advance_turn",
    ], "order is the whole point — a set or a count would answer a different question"
    assert pending["steps"] == 3
    assert pending["lastTool"] == "endless_advance_turn", "the play page's field is untouched"


def test_a_looping_narrator_is_capped_and_the_count_still_tells_the_truth(store, run):
    """The cap needs no companion flag: a trail shorter than the count IS the
    truncation signal, so the two fields must not be capped together."""
    from store import _MAX_TURN_TOOLS

    store.mark_pending(run, turn=1, slot="s")
    for _ in range(_MAX_TURN_TOOLS + 5):
        store.note_tool_call(run, "endless_read_runtime")

    pending = store.read_pending(run)
    assert len(pending["tools"]) == _MAX_TURN_TOOLS
    assert pending["steps"] == _MAX_TURN_TOOLS + 5, (
        "capping the count too would erase the only evidence that the trail is "
        "partial, and would understate a runaway turn"
    )


def test_a_junk_trail_on_disk_is_replaced_rather_than_trusted(store, run):
    """The record is JSON on disk. A hand-edited or half-written one must not be
    able to raise inside the tool this is counting."""
    store.mark_pending(run, turn=1, slot="s")
    store.note_tool_call(run, "endless_read_runtime")
    poisoned = store.read_pending(run)
    poisoned["tools"] = "not a list"
    store._kv.set(store._pending_key(run), poisoned)

    store.note_tool_call(run, "endless_advance_turn")
    assert store.read_pending(run)["tools"] == ["endless_advance_turn"]


def test_a_call_outside_a_turn_leaves_no_trail(store, run):
    """Unchanged from the count's own rule: no pending turn, nothing to advance."""
    store.note_tool_call(run, "endless_read_runtime")
    assert store.read_pending(run) is None
