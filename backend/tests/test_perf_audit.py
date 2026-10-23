"""``tools/perf_audit.py`` — the read-only per-turn time and credit audit.

The audit is how a speed change is argued for, so the two numbers it exists to
produce are pinned on a hand-built life: a narrator repair turn is told apart
from a narrated one by its prompt, and an illustrator commit that lands just
after its attempt was declared timed out counts as a late commit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(_TOOLS))

import perf_audit  # noqa: E402

RUN = "0123456789abcdef0123456789abcdef"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _life(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    sessions = tmp_path / "sessions"
    run = data / "runs" / RUN
    _write(
        run / "perf.jsonl",
        [
            {"turn": 1, "step": "commit", "at": 100.0, "storyMs": 40000, "toolCalls": 3},
            {"turn": 2, "step": "commit", "at": 300.0, "storyMs": 60000, "toolCalls": 2},
        ],
    )
    _write(
        run / "backdrop-timeline.jsonl",
        [
            {"turn": 1, "step": "requested", "at": 90.0, "lane": "motif"},
            # Stamped with the previous turn by the narrator's own call.
            {"turn": 0, "step": "tool:endless_paint_backdrop", "at": 90.0},
            {"turn": 1, "step": "recover:illustrator-dispatched", "at": 100.0},
            {"turn": 1, "step": "tool:endless_submit_backdrop_draft", "at": 200.0},
            {"turn": 1, "step": "recover:illustrator-timeout", "at": 220.0},
            {"turn": 1, "step": "tool:endless_commit_fallback_backdrop", "at": 230.0},
            {"turn": 1, "step": "tool:endless_commit_backdrop", "at": 245.0},
        ],
    )
    turn_stats = {"elapsed_ms": 40000, "credits": 2.0, "ttft_ms": 5000}
    _write(
        sessions / f"dashboard_endless-run-{RUN}.jsonl",
        [
            {"_type": "metadata"},
            {"role": "user", "content": "This is turn 1."},
            {"role": "tool", "content": "x/endless_read_runtime"},
            {"role": "tool", "content": "x/endless_advance_turn"},
            {"role": "tool", "content": "x/endless_advance_turn"},
            {"role": "assistant", "content": "ok", "meta": {"turn_stats": turn_stats}},
            {"role": "user", "content": "Internal page-art recovery for runId x, turn 1."},
            {"role": "tool", "content": "x/endless_commit_fallback_backdrop"},
            {
                "role": "assistant",
                "content": "Recovered.",
                "meta": {"turn_stats": {"elapsed_ms": 10000, "credits": 1.0}},
            },
        ],
    )
    return data, sessions


def test_a_repair_turn_is_counted_apart_and_a_late_commit_is_found(tmp_path):
    data, sessions = _life(tmp_path)
    summary = perf_audit.summarise(perf_audit.collect(data, sessions))

    assert summary["narrator"]["credits"]["n"] == 1
    assert summary["recovery"]["credits"]["sum"] == 1.0
    assert summary["recovery"]["shareOfCredits"] == 1.0 / 3.0
    assert summary["narrator"]["repeatedToolCalls"] == 1

    art = summary["art"]
    assert art["pages"] == 1
    assert art["timeouts"] == 1
    assert art["lateCommits"] == 1
    assert art["pagesNeedingNarrator"] == 1
    assert art["requestToDispatchMs"]["median"] == 10000
    assert art["submitBeforeTimeoutMs"]["median"] == 20000


def test_the_report_names_its_sample_size_and_what_it_cannot_measure(tmp_path):
    data, sessions = _life(tmp_path)
    text = perf_audit.render(perf_audit.summarise(perf_audit.collect(data, sessions)))

    assert "| n |" in text
    assert "illustrator credits: not recorded" in text


def test_nothing_on_disk_is_an_empty_report_not_a_crash(tmp_path):
    summary = perf_audit.summarise(perf_audit.collect(tmp_path / "none", tmp_path / "none"))

    assert summary["runs"] == 0
    assert summary["story"]["storyMs"]["median"] is None
    assert perf_audit.render(summary)
