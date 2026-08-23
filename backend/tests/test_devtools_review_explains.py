"""A red shot must say WHY, not just that something is wrong.

``review`` counts a shot as needing attention and then prints the reasons. Those were
two separately-written lists once, and they drifted: a shot whose only problem was a
failed request was counted in "N needing attention" while the printer explained only
violations and unreached shots. The run went red and named nothing — a state that costs
an artifact download to read one line, and that no existing test noticed.

So the invariant under test is not the wording of any message: it is that the SAME
predicate decides both, so every signal that can turn a run red can also explain itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "devtools"))

import uishot  # noqa: E402

#: One report per signal that ``review`` treats as needing attention. A shot that
#: reached its surface and violated nothing can still be red — an app request that
#: failed or never settled is exactly the class of defect a screenshot cannot show.
_SIGNALS = {
    "violations": {"reached": True, "violations": [".ew-slot-on: is visible but must step aside"]},
    "badRequests": {"reached": True, "badRequests": ["FAILED net::ERR_FAILED /api/apps/x/runs"]},
    "pending": {"reached": True, "pending": ["/api/apps/x/runs/a/chronicle"]},
    "unreached": {"reached": False, "failure": "locator.click timeout"},
}


def test_every_signal_that_can_turn_a_run_red_explains_itself() -> None:
    for name, rep in _SIGNALS.items():
        reasons = uishot._attention(dict(rep))
        assert reasons, (
            f"a shot flagged only by {name!r} produced no printable reason, so `review` "
            "would count it and say nothing — the log names a number and no cause"
        )


def test_a_clean_shot_is_silent() -> None:
    clean = {"reached": True, "violations": [], "badRequests": [], "pending": []}
    assert uishot._attention(clean) == [], (
        "a clean shot must produce no reasons, or every green run prints noise and the "
        "real signals stop being read"
    )


def test_the_reason_carries_the_offending_detail() -> None:
    """Naming the shot is not enough: the line has to carry what went wrong."""
    rep = {"reached": True, "badRequests": ["FAILED net::ERR_FAILED /api/apps/x/runs"]}
    text = "\n".join(uishot._attention(rep))
    assert "ERR_FAILED" in text and "/api/apps/x/runs" in text, (
        "the printed reason dropped the request that failed, which leaves the reader "
        "exactly where the missing-reason bug left them"
    )


def test_an_unreached_shot_leads_with_why_not_with_consequences() -> None:
    """The step that failed explains the empty surface; the violations are downstream."""
    rep = {
        "reached": False,
        "failure": "locator.click timeout",
        "steps": ['ok {"home":true}', 'FAILED {"click":"背包"}'],
        "violations": [".ew-slot-on: not visible"],
    }
    reasons = uishot._attention(rep)
    assert reasons[0].startswith("UNREACHED"), (
        "violations printed before the reason the surface was never reached send the "
        "reader to the wrong place"
    )
    assert any("FAILED" in line for line in reasons), "the failing step must be named"
