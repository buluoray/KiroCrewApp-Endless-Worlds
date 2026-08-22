"""Opening tests — the world's call vs the player's, and what a blank means."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from opening import (  # noqa: E402
    WORLD_DECIDES,
    OpeningError,
    build_initial_state,
    compose_opening_prompt,
    roll,
    world_rolled_groups,
)
from world import read_world  # noqa: E402

FLAGSHIP = _BACKEND.parent / "seeds" / "age-of-sword-and-flame.md"


@pytest.fixture(scope="module")
def tpl():
    if not FLAGSHIP.is_file():
        pytest.skip("flagship seed not present")
    return read_world(FLAGSHIP.read_text(encoding="utf-8")).template


# -- the world's call -----------------------------------------------------


def test_the_flagship_reserves_magic_aptitude_for_the_world(tpl):
    """The rulebook is explicit that magic aptitude is rolled, not chosen. It is
    the anti-halo rule at its most concrete: the one thing a player would most
    like to pick is the one thing they cannot."""
    assert world_rolled_groups(tpl) == ["aptitude"]


def test_a_player_supplied_value_for_a_world_rolled_group_is_refused(tpl):
    with pytest.raises(OpeningError) as exc:
        build_initial_state(tpl, {"aptitude": "传奇"})
    assert exc.value.field == "answers.aptitude"
    assert "world" in exc.value.expected


def test_a_world_rolled_group_is_rolled_from_the_worlds_own_options(tpl):
    state = build_initial_state(tpl, {}, rng=random.Random(7))
    picked = state["opening"]["aptitude"]
    options = next(g.options for g in tpl.opening if g.id == "aptitude")
    assert picked in options


def test_rolling_is_not_the_same_as_choosing(tpl):
    """Across many seeds a rolled group must actually vary — a "roll" that always
    returns the same value would be a default wearing a costume."""
    seen = {
        build_initial_state(tpl, {}, rng=random.Random(s))["opening"]["aptitude"]
        for s in range(60)
    }
    assert len(seen) > 1


# -- a blank means "the world decides" -----------------------------------


def test_an_unanswered_group_is_left_to_the_world_not_rejected(tpl):
    state = build_initial_state(tpl, {"name": "艾琳"})
    assert state["opening"]["name"] == "艾琳"
    assert state["opening"]["goal"] is WORLD_DECIDES
    assert state["opening"]["birthplace"] is WORLD_DECIDES


def test_every_group_the_world_asks_appears_in_the_state(tpl):
    """Stored rather than omitted, so the narrator can tell "left to me" from
    "this world never asks it"."""
    state = build_initial_state(tpl, {})
    assert set(state["opening"]) == {g.id for g in tpl.opening}


def test_a_text_group_cannot_be_rolled_into_a_fabricated_value(tpl):
    """There is no list of plausible names in a rulebook. Inventing one here
    would put the app's imagination where the narrator's belongs."""
    assert roll(tpl, "name") is WORLD_DECIDES
    assert roll(tpl, "era") in next(g.options for g in tpl.opening if g.id == "era")


# -- picks ----------------------------------------------------------------


def test_a_pick_outside_the_offered_options_is_refused_when_custom_is_off(tpl):
    with pytest.raises(OpeningError) as exc:
        build_initial_state(tpl, {"aptitude_x": "x"})
    assert exc.value.field == "answers.aptitude_x"


def test_a_custom_answer_is_kept_verbatim_where_the_world_allows_it(tpl):
    state = build_initial_state(tpl, {"race": "半龙人（自创）"})
    assert state["opening"]["race"] == "半龙人（自创）"


def test_an_offered_option_is_accepted(tpl):
    options = next(g.options for g in tpl.opening if g.id == "era")
    state = build_initial_state(tpl, {"era": options[2]})
    assert state["opening"]["era"] == options[2]


def test_an_unknown_group_is_named_not_ignored(tpl):
    with pytest.raises(OpeningError) as exc:
        build_initial_state(tpl, {"bloodline": "龙裔"})
    assert exc.value.field == "answers.bloodline"


def test_a_number_group_takes_a_number(tpl):
    assert build_initial_state(tpl, {"age": "15"})["opening"]["age"] == 15
    assert build_initial_state(tpl, {"age": 15})["opening"]["age"] == 15
    with pytest.raises(OpeningError) as exc:
        build_initial_state(tpl, {"age": "很小"})
    assert exc.value.field == "answers.age"


def test_true_is_not_a_number(tpl):
    with pytest.raises(OpeningError):
        build_initial_state(tpl, {"age": True})


def test_an_overlong_answer_is_refused(tpl):
    with pytest.raises(OpeningError) as exc:
        build_initial_state(tpl, {"name": "名" * 201})
    assert "200" in exc.value.expected


def test_nothing_is_built_when_one_answer_is_bad(tpl):
    """Validated whole, so a run never starts with a first turn that contradicts
    what the player chose."""
    with pytest.raises(OpeningError):
        build_initial_state(tpl, {"name": "艾琳", "age": "很小"})


# -- style and language ---------------------------------------------------


def test_the_style_comes_from_the_worlds_own_levels(tpl):
    ids = {s.id for s in tpl.styles}
    assert build_initial_state(tpl, {}, style=sorted(ids)[0])["style"] in ids


def test_an_unknown_style_falls_back_to_the_worlds_default(tpl):
    default = next(s.id for s in tpl.styles if s.default)
    assert build_initial_state(tpl, {}, style="nonsense")["style"] == default
    assert build_initial_state(tpl, {})["style"] == default


def test_the_language_defaults_to_the_worlds_own(tpl):
    assert build_initial_state(tpl, {})["language"] == tpl.language == "zh"


# -- a run exists before its first turn ----------------------------------


def test_a_new_run_starts_awaiting_its_opening_turn(tpl):
    """R2.9 — a failed opening turn must leave something to retry, not a
    half-created life."""
    state = build_initial_state(tpl, {})
    assert state["status"] == "awaiting-opening"
    assert state["turn"] == 0
    assert state["worldId"] == tpl.id


# -- the prompt -----------------------------------------------------------


def test_the_opening_prompt_carries_no_setup_only_a_pull(tpl):
    """The opening push is the run id and an instruction to pull. The world's rules
    and the player's own answers are served by endless_read_runtime, so the
    narrator's visible session is not a wall of setup."""
    state = build_initial_state(tpl, {"name": "艾琳", "era": tpl.opening[0].options[0]})
    prompt = compose_opening_prompt(template=tpl, run_id="run-1")
    assert "endless_read_runtime" in prompt, "nothing tells it to pull the world"
    assert "艾琳" not in prompt, "the player's answers are pulled from state, not pushed"


def test_the_opening_prompt_tells_the_narrator_not_to_name_the_settings(tpl):
    """R25 — the player is living in a world, not filling in a form. Carried in the
    pull instruction now, not a separate line."""
    prompt = compose_opening_prompt(template=tpl, run_id="run-1")
    assert "不要提到任何设定项的名字" in prompt


def test_the_opening_prompt_names_the_run(tpl):
    """The named regression: the first live opening failed because the prompt never
    named the run and the narrator invented an id its commit was then refused for."""
    prompt = compose_opening_prompt(template=tpl, run_id="9856fa638614440fbc7171ba8fe896c5")
    assert "9856fa638614440fbc7171ba8fe896c5" in prompt


def test_the_opening_prompt_nudges_the_first_backdrop_toward_a_scene(tpl):
    """The first page is the slowest wait in the app: a hand-drawn LANE: motif is
    two illustrator attempts of up to three minutes. The opening prompt biases the
    FIRST backdrop toward a traced LANE: scene so the player opens on a real place
    faster — while still leaving motif as the fallback for a non-photographable
    opening. This lever lives only in the opening prompt, not the per-turn one."""
    prompt = compose_opening_prompt(template=tpl, run_id="run-1")
    assert "LANE: scene" in prompt
    # The fallback must survive, or a purely fantastical opening is forced onto a
    # blank procedural base instead of a hand-drawn motif.
    assert "LANE: motif" in prompt


# -- roles preset the opening and land grants -----------------------------

ZOMBIE = _BACKEND.parent / "seeds" / "last-echoes-zombie-sim.md"


def test_a_role_presets_matching_opening_groups_and_records_the_choice() -> None:
    from template import parse_template

    t = parse_template(ZOMBIE.read_text(encoding="utf-8"))
    st = build_initial_state(t, {}, role="medic")
    assert st["role"] == "medic"
    # the medic grant fills the matching opening groups the player left blank
    assert st["opening"]["occupation"] == "医生"
    assert st["opening"]["start-skills"]  # granted, non-empty


def test_a_player_answer_wins_over_a_role_grant() -> None:
    from template import parse_template

    t = parse_template(ZOMBIE.read_text(encoding="utf-8"))
    st = build_initial_state(t, {"occupation": "程序员"}, role="medic")
    assert st["opening"]["occupation"] == "程序员"


def test_an_unknown_role_is_refused() -> None:
    import pytest

    from template import parse_template

    t = parse_template(ZOMBIE.read_text(encoding="utf-8"))
    with pytest.raises(OpeningError):
        build_initial_state(t, {}, role="does-not-exist")
