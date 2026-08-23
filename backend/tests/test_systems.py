"""The systems engine: mechanics the backend runs off the narrator's gains."""

from __future__ import annotations

from types import SimpleNamespace

from systems import _get, apply_systems
from template import GAIN_FED_SYSTEM_KINDS, SYSTEM_KINDS, Condition, System


def _apply(systems, state, prev, gains):
    apply_systems(SimpleNamespace(systems=systems), state, prev, gains)
    return state


def test_accrual_adds_matched_gains_and_derives_the_tier() -> None:
    xp = System(
        id="xp",
        kind="accrual",
        into="state.hero.xp",
        tiers=[{"at": 0.0, "name": "novice"}, {"at": 100.0, "name": "veteran"}],
        tier_into="state.hero.rank",
    )
    st: dict = {}
    _apply([xp], st, {"hero": {"xp": 90}}, [{"field": "xp", "amount": "15"}])
    assert _get(st, "state.hero.xp") == 105  # 90 + 15
    assert _get(st, "state.hero.rank") == "veteran"  # crossed the 100 threshold


def test_accrual_ignores_gains_for_other_fields() -> None:
    xp = System(id="xp", kind="accrual", into="state.hero.xp")
    st: dict = {}
    _apply([xp], st, {"hero": {"xp": 10}}, [{"field": "gold", "amount": "50"}])
    assert _get(st, "state.hero.xp") == 10  # a gold gain does not feed xp


def test_resource_consumes_signed_gains_and_clamps_to_floor() -> None:
    food = System(id="food", kind="resource", into="state.base.food", floor=0, cap=10, per_turn=-1)
    st: dict = {}
    _apply([food], st, {"base": {"food": 3}}, [{"field": "food", "amount": "-5"}])
    # 3 + (-5) + (-1 perTurn) = -3, clamped to floor 0
    assert _get(st, "state.base.food") == 0


def test_decay_drifts_each_turn_within_bounds() -> None:
    fuel = System(id="fuel", kind="decay", into="state.base.fuel", floor=0, per_turn=-2)
    st: dict = {}
    _apply([fuel], st, {"base": {"fuel": 5}}, [])
    assert _get(st, "state.base.fuel") == 3


def test_unlock_is_monotonic() -> None:
    s = System(
        id="awakened",
        kind="unlock",
        into="state.magic.awakened",
        when=Condition.parse("state.trials.passed == true"),
    )
    # condition not yet met → not unlocked
    st = {"trials": {"passed": False}}
    _apply([s], st, {}, [])
    assert _get(st, "state.magic.awakened") is not True
    # condition met → unlocked
    st = {"trials": {"passed": True}}
    _apply([s], st, {}, [])
    assert _get(st, "state.magic.awakened") is True
    # stays unlocked even after the condition goes false (base from prior state)
    st = {"trials": {"passed": False}}
    _apply([s], st, {"magic": {"awakened": True}}, [])
    assert _get(st, "state.magic.awakened") is True


def test_backend_owns_the_value_over_the_narrator_declaration() -> None:
    """The narrator declared xp=999; the system recomputes from the PRIOR value plus
    this turn's gains and overwrites it — the number is the app's, not the model's."""
    xp = System(id="xp", kind="accrual", into="state.hero.xp")
    st = {"hero": {"xp": 999}}
    _apply([xp], st, {"hero": {"xp": 10}}, [{"field": "xp", "amount": "5"}])
    assert _get(st, "state.hero.xp") == 15


def test_only_the_declared_gain_fed_kinds_read_gains() -> None:
    """`template.GAIN_FED_SYSTEM_KINDS` is what `_parse_systems` uses to decide whose
    `into` segments must be unique, so it has to keep naming exactly the kinds that
    actually consume a gain. Measured rather than asserted: feed each kind a matching
    gain and see which values move."""
    responds: list[str] = []
    for kind in SYSTEM_KINDS:
        s = System(
            id="probe",
            kind=kind,
            into="state.probe.amount",
            # An unlock needs a condition; keep it false so only a gain could move it.
            when=Condition.parse("state.never == true") if kind == "unlock" else None,
        )
        without: dict = {}
        _apply([s], without, {"probe": {"amount": 5}}, [])
        with_gain: dict = {}
        _apply([s], with_gain, {"probe": {"amount": 5}}, [{"field": "amount", "amount": "3"}])
        if _get(without, "state.probe.amount") != _get(with_gain, "state.probe.amount"):
            responds.append(kind)
    assert responds == list(GAIN_FED_SYSTEM_KINDS)
