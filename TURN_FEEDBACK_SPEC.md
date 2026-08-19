# Turn-generation feedback — specification

While the narrator writes a month, the play page must show that work is
happening and roughly how far along it is, rather than a single undifferentiated
spinner. This document specifies the mechanism end to end: what the backend
records, what the runtime view exposes, and how the frontend renders it.

## Goal

- Confirm to the player that a turn is being generated and survives leaving the
  page (the work is a fact on the server, not on the tab).
- Advance a visible progress indicator **per narrator tool call**, so a richer
  turn (reading the life, mounting a scene, awaiting a scene answer, writing the
  page) reads as steady progress.
- Keep the copy consistent with the rest of the app by reusing the existing,
  tuned waiting phrases; do not introduce a parallel set of stage strings.

Non-goal: a true percentage. The model's prose generation between tool calls
emits no signal, so the bar is deliberately capped below full until the turn
commits.

## The signal: the in-flight (pending) record

A turn's progress lives on the run's **pending** record, written to the store
before the narrator is dispatched (`store.mark_pending`) and cleared when the
turn commits (`store.clear_pending`). Its progress-bearing fields:

| Field      | Written by                          | Meaning                                                        |
|------------|-------------------------------------|----------------------------------------------------------------|
| `askedAt`  | `mark_pending` (before dispatch)    | The turn was asked for; the narrator is starting.              |
| `readAt`   | `note_runtime_read` (in `_read_runtime`) | The narrator called `endless_read_runtime`: it now holds this life's state and has moved on to composing. |
| `steps`    | `note_tool_call` (central dispatch) | Count of tool calls the narrator has made this turn.           |
| `lastTool` | `note_tool_call`                    | The narrator's most recent tool name.                          |

`note_tool_call(run_id, tool)` increments `steps` and records `lastTool`, and is
invoked centrally in the MCP server's `call_tool` for **any** tool call carrying
a `runId`, before the handler runs. It only records while a pending record
exists (a call outside a turn has no turn to advance) and never raises — progress
bookkeeping must not fail the tool it counts.

`clear_pending` runs on commit, so the last tool call (`endless_advance_turn`
itself) is counted and then discarded along with the record: the bar's job ends
when the committed page replaces it.

## Runtime contract: `generating()`

`turn.generating(store, run_id)` returns `None` when nothing is in flight, else:

```
{
  "turn":     <int>,     # the turn being written
  "slot":     <str>,
  "askedAt":  <float>,
  "readAt":   <float>,   # 0 until endless_read_runtime lands
  "stage":    "reading" | "writing",   # "writing" once readAt is set
  "steps":    <int>,     # tool calls so far
  "lastTool": <str>,
}
```

`stage` is a coarse two-phase reading derived from `readAt`; `steps`/`lastTool`
are the fine-grained per-call signal. `build_play_view` includes this object as
`view.generating`, and the run/life list views report only its presence as a
boolean `generating` flag.

## Frontend

The play page polls `GET /runs/<id>` while `generating` (or `awaitingOpening`)
so `view.generating` refreshes and the indicator advances on its own, even for a
returning player whose original request's poll loop died with the page.

**`TurnProgress`** (in `web/src/play.tsx`) renders:

- A track with a fill whose width is `min(12 + steps * 16, 92)%` — roughly one
  notch (~16%) per tool call, capped at 92% so it never looks finished before
  commit — with a `.4s` width transition.
- A moving shimmer over the track (`ew-sweep`) so the long writing phase never
  looks stalled. Suppressed under `prefers-reduced-motion`.
- A **label** that reuses the app's existing waiting copy, not a new stage
  string:
  - Opening (`awaitingOpening && generating`): the rotating `opening.waiting.*`
    phrase (`arrange` state, cycled every 4s).
  - Mid-life (`generating`): the rotating `play.waiting.*` phrase (`phrase`
    state, cycled every 4s the same way).

Placement:

- On the opening "arranging" screen, inside `.ew-arrange`.
- On every in-flight mid-life turn, in the `.ew-note-live` note — shown whenever
  `generating` is true, **including while a tapped choice sweeps**, so the whole
  wait reads as progress.

When the turn commits, `generating` becomes false, the note is removed, and the
newly written page animates in (see the turn pager / page-turn animation).

## Invariants

- Progress bookkeeping is best-effort and never fails a tool call or a turn.
- `steps` advances only while a turn is pending; it resets implicitly each turn
  because the pending record is recreated per turn.
- The bar never reaches 100% before commit; commit ends the indicator.
- Copy has a single source of truth: `play.waiting.*` / `opening.waiting.*`.
  No per-tool or per-stage label strings are introduced.

## Tests

- `backend/tests/test_pending.py::test_generating_stage_advances_from_reading_to_writing`
  pins that `stage` flips `reading` → `writing` when `note_runtime_read` stamps
  `readAt`.
- Existing pending tests continue to assert that a returning player is told a
  month is being written and that a landed turn leaves nothing in flight.
