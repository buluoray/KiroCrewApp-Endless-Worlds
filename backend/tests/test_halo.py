"""Reach gating and anti-halo tests.

The line these hold: the app MEASURES, the narrator adjusts. A test that expected
this module to cap a number or delete a lucky break would be pinning the wrong
design — that is the narrator's job under its own rules, and a backend that did it
silently would write the story badly while the player felt the seams.

Two things are enforced rather than reported, and those are tested as enforcement:
a distant event cannot arrive as fact, and a gain with no source is marked.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import halo  # noqa: E402
from content import Content  # noqa: E402
from halo import (  # noqa: E402
    BUSY_PER_TURN,
    DEFAULT_REACH,
    REACH_TIERS,
    REPEAT_PRESSURE,
    attribution,
    compose_restraint,
    event_density,
    gate_digest,
    reach_rank,
)

#: A source name the narrator keeps crediting. English: the assertions check
#: repetition, not wording.
SOURCE = "odd jobs at the market"

LANG = "zh"
T = Content(LANG)

CATS = ["realm", "war", "church"]


# -- reach ----------------------------------------------------------------


def test_a_new_life_hears_only_what_is_near_it():
    """"local" and not "world": a newborn farmer briefed on continental
    diplomacy has been handed a protagonist's vantage point before drawing
    breath."""
    assert DEFAULT_REACH == "local"
    assert reach_rank(DEFAULT_REACH) < reach_rank("realm") < reach_rank("world")


def test_something_within_reach_is_reported_plainly():
    state = {"reach": "local", "digest": {"realm": {"text": "the village tax went up", "at": "local"}}}
    out = gate_digest(CATS, state)
    assert out == [{"category": "realm", "text": "the village tax went up", "rumour": False}]


def test_a_distant_event_arrives_as_rumour_even_when_declared_as_fact():
    """ENFORCED, not reported. Where the character is standing is not a stylistic
    choice, so a narrator that states a far-off war as established fact has it
    marked as rumour rather than obeyed."""
    state = {"reach": "local", "digest": {"war": {"text": "the empire declared war", "at": "realm"}}}
    out = gate_digest(CATS, state)
    assert out == [{"category": "war", "text": "the empire declared war", "rumour": True}]


def test_nothing_the_narrator_wrote_is_ever_dropped():
    """The correction that matters here. An earlier revision withheld anything
    more than one tier away, so a village character could never hear about the
    empire at all — wrong twice: rumour is precisely what travels further than a
    person does, and silently deleting something the narrator thought mattered is
    the one behaviour this module exists to avoid.

    The gate decides HOW news arrives, never WHETHER it survives.
    """
    state = {
        "reach": "here",
        "digest": {
            "realm": {"text": "a notice at the village gate", "at": "here"},
            "war": {"text": "another continent went to war", "at": "world"},
            "church": {"text": "the next town changed priests", "at": "regional"},
        },
    }
    out = gate_digest(CATS, state)
    assert len(out) == 3, "an entry was dropped"
    by_cat = {d["category"]: d for d in out}
    assert by_cat["realm"]["rumour"] is False
    assert by_cat["war"]["rumour"] is True
    assert by_cat["church"]["rumour"] is True


def test_reach_grows_and_the_same_event_becomes_reportable():
    """The same declaration, read from two positions — which is what makes this
    gating rather than filtering."""
    digest = {"war": {"text": "the empire declared war", "at": "realm"}}
    near = gate_digest(CATS, {"reach": "local", "digest": digest})
    far = gate_digest(CATS, {"reach": "realm", "digest": digest})
    assert near[0]["rumour"] is True
    assert far[0]["rumour"] is False


def test_a_bare_string_is_treated_as_within_reach():
    """Both shapes accepted, for the same reason the panel primitives accept
    both: refusing one would be the app telling the narrator how to write."""
    out = gate_digest(CATS, {"digest": {"church": "the temple changed its high priest"}})
    assert out == [{"category": "church", "text": "the temple changed its high priest", "rumour": False}]


def test_an_unknown_distance_degrades_to_the_default_rather_than_failing():
    """The narrator writes these; a turn must not fail because it said "far"."""
    assert reach_rank("far away") == reach_rank(DEFAULT_REACH)
    out = gate_digest(CATS, {"digest": {"realm": {"text": "t", "at": "somewhere"}}})
    assert out and out[0]["rumour"] is False


def test_the_worlds_own_rumours_stay_rumours():
    state = {"digest": {"rumours": ["they say a knight died north of here", ""]}}
    out = gate_digest(CATS, state)
    assert out == [{"category": "rumour", "text": "they say a knight died north of here", "rumour": True}]


def test_a_far_off_rumour_still_arrives_because_that_is_what_rumours_do():
    """A rumour from the other side of the world is exactly the kind of thing that
    reaches a village — garbled, late, and possibly wrong, which is what the
    rumour marking is for."""
    state = {"reach": "here", "digest": {"rumours": [{"text": "a rumour from far away", "at": "world"}]}}
    out = gate_digest(CATS, state)
    assert out == [{"category": "rumour", "text": "a rumour from far away", "rumour": True}]


def test_reports_come_in_the_worlds_order_then_rumours():
    """A world that thinks war matters more than trade reads that way."""
    state = {
        "reach": "local",
        "digest": {
            "church": "something nearby",
            "realm": "also nearby",
            "war": {"text": "something further off", "at": "regional"},
        },
    }
    cats = [d["category"] for d in gate_digest(CATS, state)]
    assert cats == ["realm", "church", "war"]


# -- event density --------------------------------------------------------


def test_density_counts_what_the_narrator_marked_not_how_much_it_wrote():
    """A long quiet month and a short catastrophic one are indistinguishable by
    character count, and inferring drama from verbosity would reward padding.

    Asserted behaviourally: an earlier version of this test scanned the source for
    the word "prose" and failed on its own docstring — it was testing prose, not
    behaviour.
    """
    verbose_and_calm = [{"turn": 1, "prose": "x" * 4000, "events": ["a"]}]
    terse_and_calm = [{"turn": 1, "prose": "he died", "events": ["a"]}]
    assert event_density(verbose_and_calm) == event_density(terse_and_calm)

    terse_and_awful = [{"turn": 1, "prose": "the village is gone", "events": ["a", "b", "c", "d"]}]
    assert event_density(terse_and_awful)["perTurn"] > event_density(verbose_and_calm)["perTurn"]


def test_a_busy_stretch_is_flagged():
    chronicle = [{"turn": i, "events": ["a", "b", "c"]} for i in range(1, 7)]
    reading = event_density(chronicle)
    assert reading["perTurn"] == 3.0
    assert reading["perTurn"] > BUSY_PER_TURN
    assert reading["busy"] is True


def test_an_ordinary_stretch_is_not_flagged():
    chronicle = [{"turn": i, "events": ["a"]} for i in range(1, 7)]
    assert event_density(chronicle)["busy"] is False


def test_a_quiet_stretch_is_reported_but_is_not_a_fault():
    """A life is allowed to be uneventful. The reading exists so the narrator can
    tell a calm stretch it chose from one it drifted into."""
    reading = event_density([{"turn": i} for i in range(1, 5)])
    assert reading["quiet"] is True
    assert reading["busy"] is False


def test_an_empty_chronicle_reads_as_nothing_rather_than_as_quiet():
    reading = event_density([])
    assert reading == {"turns": 0, "events": 0, "perTurn": 0.0, "busy": False, "quiet": False}


def test_a_count_is_accepted_where_a_list_would_do():
    assert event_density([{"turn": 1, "events": 3}])["events"] == 3
    assert event_density([{"turn": 1, "events": -5}])["events"] == 0


# -- attribution ----------------------------------------------------------


def test_a_source_credited_over_and_over_becomes_leaning():
    """R7.3 — a source credited this often has stopped being a reason and become
    a habit."""
    chronicle = [
        {"turn": i, "gains": [{"field": "wealth", "amount": "+5", "source": SOURCE}]}
        for i in range(1, REPEAT_PRESSURE + 1)
    ]
    credit = attribution(chronicle)
    assert credit["leaning"] == [{"source": SOURCE, "times": REPEAT_PRESSURE}]


def test_a_source_used_twice_is_not_yet_leaning():
    chronicle = [{"turn": i, "gains": [{"field": "f", "source": "s"}]} for i in (1, 2)]
    assert attribution(chronicle)["leaning"] == []


def test_a_gain_with_no_source_is_flagged_not_refused():
    """ENFORCED as a mark, not as a refusal: a narrator that forgot to say where
    five gold came from has still narrated a real turn."""
    chronicle = [{"turn": 4, "gains": [{"field": "wealth", "amount": "+50"}]}]
    credit = attribution(chronicle)
    assert credit["unsourced"] == [{"turn": 4, "field": "wealth", "amount": "+50"}]


def test_a_blank_source_counts_as_no_source():
    chronicle = [{"turn": 1, "gains": [{"field": "f", "source": "   "}]}]
    assert len(attribution(chronicle)["unsourced"]) == 1
    assert attribution(chronicle)["sources"] == {}


def test_leaning_is_ordered_by_pressure():
    chronicle = (
        [{"turn": i, "gains": [{"field": "f", "source": "the usual trick"}]} for i in range(1, 6)]
        + [{"turn": i, "gains": [{"field": "f", "source": "the rarer trick"}]} for i in range(6, 9)]
    )
    assert [r["source"] for r in attribution(chronicle)["leaning"]] == ["the usual trick", "the rarer trick"]


def test_a_malformed_gain_is_ignored_rather_than_crashing_the_turn():
    chronicle = [{"turn": 1, "gains": ["not an object", None, 7]}]
    credit = attribution(chronicle)
    assert credit["sources"] == {} and credit["unsourced"] == []


# -- the reading handed to the narrator ----------------------------------


def test_nothing_is_said_when_there_is_nothing_to_say():
    """A prompt that always carries a paragraph of self-criticism trains the
    narrator to skim it."""
    assert compose_restraint([], LANG) == ""
    assert compose_restraint([{"turn": i, "events": ["a"]} for i in range(1, 5)], LANG) == ""


def test_a_busy_life_is_told_so_in_the_worlds_terms():
    chronicle = [{"turn": i, "events": ["a", "b", "c"]} for i in range(1, 7)]
    out = compose_restraint(chronicle, LANG)
    assert T("restraint.busy", turns=6, events=18) in out


def test_a_repeated_source_is_named_back_to_the_narrator():
    chronicle = [
        {"turn": i, "gains": [{"field": "wealth", "source": SOURCE}]}
        for i in range(1, 5)
    ]
    out = compose_restraint(chronicle, LANG)
    assert SOURCE in out
    assert T("restraint.leaning", source=SOURCE, turns=4, times=4) in out


def test_an_unsourced_gain_is_named_back_to_the_narrator():
    out = compose_restraint([{"turn": 1, "gains": [{"field": "wealth", "amount": "+50"}]}], LANG)
    assert "wealth" in out
    assert T("restraint.unsourced", fields="wealth") in out


def test_the_reading_is_an_observation_not_an_order():
    """Phrased as observations because "be harsher" is a mood, while "you have
    handed this life three windfalls in six months" is actionable."""
    chronicle = [{"turn": i, "events": ["a", "b", "c"]} for i in range(1, 7)]
    out = compose_restraint(chronicle, LANG)
    for imperative_only in ("必须", "禁止", "不允许"):
        assert imperative_only not in out


def test_the_app_never_rewrites_narration():
    """The load-bearing invariant of this module. A backend that capped a number
    or deleted a lucky break would be writing the story, and the player would
    feel the seams without being able to name them."""
    src = inspect.getsource(halo)
    for writing in ("commit_state", "prose =", "def rewrite", "min(", "max(0, min"):
        if writing == "max(0, min":
            continue
        assert writing not in src, f"halo.py reaches for {writing!r}"


def test_the_reading_never_leaks_implementation_vocabulary():
    """R25 — this text goes into a prompt, and a narrator taught these words
    repeats them at the player."""
    chronicle = (
        [{"turn": i, "events": ["a", "b", "c"], "gains": [{"field": "wealth"}]} for i in range(1, 7)]
    )
    out = compose_restraint(chronicle, LANG)
    for word in ("state", "chronicle", "digest", "schema", "JSON"):
        assert word not in out


# -- the tiers themselves -------------------------------------------------


def test_the_tiers_are_ordered_nearest_first():
    assert REACH_TIERS[0] == "here"
    assert REACH_TIERS[-1] == "world"
    assert list(REACH_TIERS) == sorted(REACH_TIERS, key=reach_rank)
