"""A schema refusal says exactly how to retry.

Measured on a pod: after the host refused five commits whose `arguments` went
out as a JSON string, the narrator probed with seven calls under the run id "x".
Each was refused on the run id before anything else was looked at, taught it
nothing, and the page cost 6.37 credits. The refusal now says so.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import mcp_server as srv  # noqa: E402


def call(name, **args):
    return json.loads(srv.call_tool(name, args))


def test_a_probe_under_a_made_up_run_id_is_told_it_tests_nothing():
    out = call("endless_advance_turn", runId="x", turn=15, prose="a")
    assert out["ok"] is False and out["field"].endswith("runId")
    assert "made-up id tests nothing" in out["retry"]
    assert "32-character run id your message gives" in out["retry"]
    assert "`arguments` as a JSON object" in out["retry"]


def test_any_other_refusal_says_to_resend_the_same_whole_call():
    out = call("endless_advance_turn", runId="a" * 32, turn=0, prose="a")
    assert out["ok"] is False and out["field"].endswith("turn")
    assert out["retry"].startswith("Fix only that and resend the SAME call, whole")
    assert "made-up" not in out["retry"]
