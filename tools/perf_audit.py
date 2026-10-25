#!/usr/bin/env python3
"""Where a turn spends time and credits, measured from real play. Read-only.

Joins the three records a played life leaves behind:

* ``runs/<id>/perf.jsonl`` — the MCP server's ``commit`` row per turn
  (``storyMs``, ``readMs``, ``toolCalls``, ``tools``, ``declaredBytes``);
* ``runs/<id>/backdrop-timeline.jsonl`` — the art lane: when the brief was
  requested, when recovery dispatched an illustrator, its tool calls, and how
  each attempt ended;
* the narrator transcripts ``dashboard_endless-run-<id>.jsonl`` in the host's
  sessions dir — one ``turn_stats`` (``elapsed_ms``, ``credits``, ``ttft_ms``)
  per narrator conversation turn, plus the prompt that started it.

It never writes anything and never needs the gateway. Illustrator spawns are
silent and keep no transcript, so their credits are not measurable here; the
art lane is reported in wall-clock time only, and the report says so.

    python3 tools/perf_audit.py \
        --data-dir ~/.kiro/crew/apps/endless-worlds/data \
        --sessions-dir ~/.kiro/crew/sessions

``--json`` prints the raw numbers instead of the table.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

#: The prompt prefix ``routes._recover_backdrop`` sends the narrator when the
#: illustrators ended without art. Matched by prefix so a recovery turn is told
#: apart from a narrated one.
RECOVERY_PREFIX = "Internal page-art recovery"

#: A commit this soon after an attempt was declared timed out is a LATE commit:
#: the illustrator was already on its last call when the budget ran out.
LATE_COMMIT_SECS = 30.0


def _jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _epoch(raw: Any) -> float | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def pct(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile; ``None`` for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(q * len(ordered) + 0.5)))
    return ordered[rank - 1]


def _narrator_transcripts(sessions_dir: Path, run_id: str) -> list[Path]:
    """This life's narrator transcripts on disk, in conversation order."""
    stem = f"dashboard_endless-run-{run_id}"
    found: list[tuple[int, Path]] = []
    if (sessions_dir / f"{stem}.jsonl").is_file():
        found.append((0, sessions_dir / f"{stem}.jsonl"))
    for path in sessions_dir.glob(f"{stem}-c*.jsonl"):
        suffix = path.name[len(stem) + 2 : -len(".jsonl")]
        if suffix.isdigit():
            found.append((int(suffix), path))
    return [path for _n, path in sorted(found)]


def narrator_turns(transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per narrator conversation turn that carries ``turn_stats``."""
    turns: list[dict[str, Any]] = []
    prompt: str | None = None
    tools: list[str] = []
    for msg in transcript:
        role = msg.get("role")
        if role == "user":
            prompt = str(msg.get("content") or "")
            tools = []
        elif role == "tool":
            name = str(msg.get("content") or "").rsplit("/", 1)[-1].strip()
            tools.append(name)
        elif role == "assistant":
            stats = (msg.get("meta") or {}).get("turn_stats")
            if not isinstance(stats, dict) or prompt is None:
                continue
            kind = "recovery" if prompt.startswith(RECOVERY_PREFIX) else "narrate"
            turns.append(
                {
                    "kind": kind,
                    "endedAt": _epoch(msg.get("ts")),
                    "elapsedMs": stats.get("elapsed_ms"),
                    "credits": stats.get("credits"),
                    "ttftMs": stats.get("ttft_ms"),
                    "promptBytes": len(prompt.encode("utf-8")),
                    "tools": list(tools),
                }
            )
            prompt = None
    return turns


def art_turns(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per turn whose art was requested, from the backdrop timeline.

    The narrator's own ``tool:endless_paint_backdrop`` row is stamped with the
    PREVIOUS turn (it runs before the turn commits), so tool rows are folded in
    by time order, never by their turn field, and only the turn of each
    ``requested`` row anchors a record.
    """
    events = sorted(events, key=lambda e: float(e.get("at") or 0.0))
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for ev in events:
        step = str(ev.get("step") or "")
        at = float(ev.get("at") or 0.0)
        if step == "requested":
            if current is not None and int(ev.get("turn", -1)) == current["turn"]:
                current["rerequests"] += 1
                continue
            current = {
                "turn": int(ev.get("turn", -1)),
                "requestedAt": at,
                "lane": ev.get("lane"),
                "dispatches": [],
                "timeouts": [],
                "submits": [],
                "commits": [],
                "fallbacks": [],
                "serverFallback": False,
                "rerequests": 0,
            }
            out.append(current)
            continue
        if current is None:
            continue
        if step == "recover:illustrator-dispatched":
            current["dispatches"].append(at)
        elif step == "recover:illustrator-timeout":
            current["timeouts"].append(at)
        elif step == "tool:endless_submit_backdrop_draft":
            current["submits"].append(at)
        elif step == "tool:endless_commit_backdrop":
            current["commits"].append(at)
        elif step == "tool:endless_commit_fallback_backdrop":
            current["fallbacks"].append(at)
        elif step == "server-fallback-commit":
            current["serverFallback"] = True
    for rec in out:
        terminals = rec["commits"] + rec["fallbacks"]
        rec["artMs"] = int((min(terminals) - rec["requestedAt"]) * 1000) if terminals else None
        rec["lateCommits"] = sum(
            1
            for t in rec["timeouts"]
            if any(0 <= c - t <= LATE_COMMIT_SECS for c in rec["commits"])
        )
        # Last draft submitted before an attempt's timeout: how close it was.
        rec["submitBeforeTimeoutMs"] = [
            int((t - max(s for s in rec["submits"] if s <= t)) * 1000)
            for t in rec["timeouts"]
            if any(s <= t for s in rec["submits"])
        ]
        rec["draftToCommitMs"] = [
            int((c - max(s for s in rec["submits"] if s <= c)) * 1000)
            for c in rec["commits"]
            if any(s <= c for s in rec["submits"])
        ]
    return out


def conversation_turns(perf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per committed turn, labelled by how its conversation began.

    ``fresh:<reason>`` for the turn a rotation row names (install, chapter,
    budget, idle), ``continued`` for every later turn of that conversation. The
    context meter row (``usedTokens``) is the narrator's input size at the
    commit, so grouping it by label shows what each rotation reason costs.
    """
    rotated: dict[int, str] = {}
    context: dict[int, Any] = {}
    commits: list[dict[str, Any]] = []
    for row in perf_rows:
        step = row.get("step")
        raw_turn: Any = row.get("turn")
        try:
            turn = int(raw_turn)
        except (TypeError, ValueError):
            continue
        if step == "rotation":
            rotated[turn] = str(row.get("reason") or "unknown")
        elif step == "context":
            context[turn] = row.get("usedTokens")
        elif step == "commit":
            commits.append(row)
    out = []
    for row in commits:
        turn = int(row["turn"])
        out.append(
            {
                "turn": turn,
                "label": f"fresh:{rotated[turn]}" if turn in rotated else "continued",
                "usedTokens": context.get(turn),
                "storyMs": row.get("storyMs"),
                "declaredBytes": row.get("declaredBytes"),
            }
        )
    return out


def collect(data_dir: Path, sessions_dir: Path) -> dict[str, Any]:
    runs_dir = data_dir / "runs"
    commits: list[dict[str, Any]] = []
    arts: list[dict[str, Any]] = []
    narr: list[dict[str, Any]] = []
    convo: list[dict[str, Any]] = []
    run_ids = sorted(p.name for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else []
    for run_id in run_ids:
        perf_rows = _jsonl(runs_dir / run_id / "perf.jsonl")
        for row in perf_rows:
            if row.get("step") == "commit":
                commits.append({"run": run_id, **row})
        for rec in conversation_turns(perf_rows):
            convo.append({"run": run_id, **rec})
        for rec in art_turns(_jsonl(runs_dir / run_id / "backdrop-timeline.jsonl")):
            arts.append({"run": run_id, **rec})
        # One transcript per conversation: the bare key is conversation 0, later
        # ones carry ``-c<n>``. Retired conversations' transcripts are deleted, so
        # only the conversations still on disk are read.
        for transcript in _narrator_transcripts(sessions_dir, run_id):
            for rec in narrator_turns(_jsonl(transcript)):
                narr.append({"run": run_id, **rec})
    return {
        "runs": run_ids,
        "commits": commits,
        "art": arts,
        "narrator": narr,
        "conversation": convo,
    }


def summarise(data: dict[str, Any]) -> dict[str, Any]:
    commits, arts, narr = data["commits"], data["art"], data["narrator"]

    def stat(values: list[Any]) -> dict[str, Any]:
        vals = [float(v) for v in values if isinstance(v, (int, float))]
        return {
            "n": len(vals),
            "median": statistics.median(vals) if vals else None,
            "p90": pct(vals, 0.9),
            "sum": sum(vals),
        }

    narrate = [t for t in narr if t["kind"] == "narrate"]
    recovery = [t for t in narr if t["kind"] == "recovery"]
    tool_counter: Counter[str] = Counter()
    repeated = 0
    for t in narrate:
        counts = Counter(t["tools"])
        tool_counter.update(counts)
        repeated += sum(n - 1 for n in counts.values() if n > 1)
    by_start: dict[str, list[dict[str, Any]]] = {}
    for rec in data.get("conversation", []):
        by_start.setdefault(rec["label"], []).append(rec)
    narrate_credits = sum(float(t["credits"] or 0) for t in narrate)
    recovery_credits = sum(float(t["credits"] or 0) for t in recovery)
    total_credits = narrate_credits + recovery_credits
    return {
        "runs": len(data["runs"]),
        "conversation": {
            label: {
                "usedTokens": stat([r["usedTokens"] for r in recs]),
                "storyMs": stat([r["storyMs"] for r in recs]),
                "declaredBytes": stat([r["declaredBytes"] for r in recs]),
            }
            for label, recs in sorted(by_start.items())
        },
        "story": {
            "storyMs": stat([c.get("storyMs") for c in commits]),
            "readMs": stat([c.get("readMs") for c in commits]),
            "toolCalls": stat([c.get("toolCalls") for c in commits]),
            "declaredBytes": stat([c.get("declaredBytes") for c in commits]),
        },
        "narrator": {
            "elapsedMs": stat([t["elapsedMs"] for t in narrate]),
            "ttftMs": stat([t["ttftMs"] for t in narrate]),
            "credits": stat([t["credits"] for t in narrate]),
            "promptBytes": stat([t["promptBytes"] for t in narrate]),
            "toolUse": dict(tool_counter.most_common()),
            "repeatedToolCalls": repeated,
        },
        "recovery": {
            "elapsedMs": stat([t["elapsedMs"] for t in recovery]),
            "credits": stat([t["credits"] for t in recovery]),
            "shareOfCredits": (recovery_credits / total_credits) if total_credits else None,
        },
        "art": {
            "pages": len(arts),
            "artMs": stat([a["artMs"] for a in arts]),
            "requestToDispatchMs": stat(
                [
                    int((a["dispatches"][0] - a["requestedAt"]) * 1000)
                    for a in arts
                    if a["dispatches"]
                ]
            ),
            "attempts": sum(len(a["dispatches"]) for a in arts),
            "timeouts": sum(len(a["timeouts"]) for a in arts),
            "lateCommits": sum(a["lateCommits"] for a in arts),
            "pagesNeedingNarrator": sum(1 for a in arts if a["fallbacks"]),
            "serverFallbacks": sum(1 for a in arts if a["serverFallback"]),
            "draftToCommitMs": stat([v for a in arts for v in a["draftToCommitMs"]]),
            "submitBeforeTimeoutMs": stat([v for a in arts for v in a["submitBeforeTimeoutMs"]]),
        },
    }


def _fmt(v: Any, scale: float = 1.0, unit: str = "") -> str:
    if v is None:
        return "-"
    v = float(v) / scale
    return f"{v:.1f}{unit}" if abs(v) < 100 else f"{v:.0f}{unit}"


def render(s: dict[str, Any]) -> str:
    rows = [
        ("Story write (commit row storyMs)", s["story"]["storyMs"], 1000, "s"),
        ("  of which read_runtime (readMs)", s["story"]["readMs"], 1000, "s"),
        ("Narrator turn wall-clock", s["narrator"]["elapsedMs"], 1000, "s"),
        ("Narrator time to first token", s["narrator"]["ttftMs"], 1000, "s"),
        ("Narrator credits / turn", s["narrator"]["credits"], 1, ""),
        ("Narrator prompt bytes / turn", s["narrator"]["promptBytes"], 1, ""),
        ("Narrator tool calls / turn", s["story"]["toolCalls"], 1, ""),
        ("Declared state bytes / turn", s["story"]["declaredBytes"], 1, ""),
        ("Art: request -> page has art", s["art"]["artMs"], 1000, "s"),
        ("Art: request -> illustrator dispatched", s["art"]["requestToDispatchMs"], 1000, "s"),
        ("Art: last draft -> commit", s["art"]["draftToCommitMs"], 1000, "s"),
        ("Art: last draft -> timeout fired", s["art"]["submitBeforeTimeoutMs"], 1000, "s"),
        ("Recovery narrator turn wall-clock", s["recovery"]["elapsedMs"], 1000, "s"),
        ("Recovery narrator credits", s["recovery"]["credits"], 1, ""),
    ]
    lines = [
        f"runs: {s['runs']}",
        "",
        "| metric | n | median | p90 |",
        "|---|---|---|---|",
    ]
    for label, st, scale, unit in rows:
        lines.append(
            f"| {label} | {st['n']} | {_fmt(st['median'], scale, unit)} | {_fmt(st['p90'], scale, unit)} |"
        )
    if s.get("conversation"):
        lines += [
            "",
            "| turn by conversation start | n | input tokens (median) | story (median) "
            "| declared bytes (median) |",
            "|---|---|---|---|---|",
        ]
        for label, c in s["conversation"].items():
            lines.append(
                f"| {label} | {c['storyMs']['n']} | {_fmt(c['usedTokens']['median'])} "
                f"| {_fmt(c['storyMs']['median'], 1000, 's')} "
                f"| {_fmt(c['declaredBytes']['median'])} |"
            )
    a, r = s["art"], s["recovery"]
    share = r["shareOfCredits"]
    lines += [
        "",
        f"art pages: {a['pages']}, illustrator attempts: {a['attempts']}, "
        f"timeouts: {a['timeouts']}, late commits (<= {LATE_COMMIT_SECS:.0f}s after a timeout): "
        f"{a['lateCommits']}, pages needing the narrator: {a['pagesNeedingNarrator']}, "
        f"server underlay fallbacks: {a['serverFallbacks']}",
        f"recovery narrator credits: {_fmt(r['credits']['sum'])} "
        f"({_fmt(share * 100 if share is not None else None)}% of narrator-side credits)",
        f"narrator tool use: {s['narrator']['toolUse']}, repeated calls in one turn: "
        f"{s['narrator']['repeatedToolCalls']}",
        "illustrator credits: not recorded (silent spawns keep no transcript)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    home = Path.home() / ".kiro" / "crew"
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--data-dir", type=Path, default=home / "apps" / "endless-worlds" / "data")
    parser.add_argument("--sessions-dir", type=Path, default=home / "sessions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    data = collect(args.data_dir.expanduser(), args.sessions_dir.expanduser())
    summary = summarise(data)
    if args.json:
        json.dump({"summary": summary, **data}, sys.stdout, indent=2, default=str)
        print()
    else:
        print(render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
