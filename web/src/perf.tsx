/** The performance page: what each committed turn of a life cost.
 *
 * A plain table, newest turn first, with inline proportional bars — no chart
 * library for a handful of columns of numbers. Every latency bar is scaled
 * against the page's own maximum so a slow turn is visibly slow *relative to
 * this life*, which is the comparison an audit actually makes.
 *
 * Tokens are labelled as tokens. When the gateway exposes real per-turn
 * billing the table grows a credits column and the note names the currency;
 * a number dressed up as money that can never be reconciled with a bill would
 * poison the audit this page exists for, so tokens alone are never dressed up.
 *
 * Two things shape the layout, and they turn out to be the same decision:
 *
 * 1. **Every row opens.** A turn's totals answer "which turn was slow" and
 *    nothing else; the question that follows is always "slow WHERE", and the
 *    answer is already recorded — the ledgers hold the narrator's read, its
 *    writing, and every step of the art lane with the model's own thinking
 *    between them. The expansion is where that lives, fetched per turn because
 *    a long life's full trace dwarfs the summary and is read one turn at a time.
 *
 * 2. **A phone shows the identifying columns and moves the rest into that same
 *    expansion.** The table is not card-stacked: cards suit lookup and this page
 *    is for comparing turns, and reflowing a table with `display` costs its
 *    semantics. Columns are dropped from their cells instead, which is only
 *    legal because the expansion is a real detail path for every one of them
 *    (dropping a column with nowhere to read it is WCAG F102). The table keeps
 *    its own scroll region so any residual overflow stays contained to the
 *    table — where Reflow exempts it — instead of pushing the page sideways.
 */

import { useEffect, useState } from 'react'

import type { PerfTurn, TurnStages } from './api'
import { api } from './api'
import { t } from './strings'

/** The columns a phone drops from their own cells, by catalog key.
 *
 * ONE list, read by both sides of the arrangement: the header cells carrying
 * `ew-perf-rest` and the expansion facts marked as duplicates. Dropping a column
 * with nowhere to read it is WCAG F102, and showing it twice where it is already
 * visible is what makes an expansion feel padded — both failures are the two
 * lists disagreeing, so there is only one.
 */
const NARROW_HIDDEN = [
  'perf.declared',
  'perf.credits',
  'perf.tokens',
  'perf.context',
  'perf.events',
] as const

function Bar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  return (
    <span className="ew-perfbar" aria-hidden="true">
      <span className="ew-perfbar-fill" style={{ width: `${pct}%` }} />
    </span>
  )
}

function ms(v: number | undefined | null): string {
  if (v === undefined || v === null) return '—'
  return v >= 10000 ? `${Math.round(v / 1000)}s` : `${(v / 1000).toFixed(1)}s`
}

function kb(bytes: number | undefined): string {
  return bytes === undefined ? '—' : `${(bytes / 1024).toFixed(1)}KB`
}

/** Explicit per-reason lookups so every catalog key appears verbatim. */
function rotationLabel(reason: string): string {
  if (reason === 'chapter') return t('perf.rotationChapter')
  if (reason === 'budget') return t('perf.rotationBudget')
  if (reason === 'install') return t('perf.rotationInstall')
  if (reason === 'closed') return t('perf.rotationClosed')
  return t('perf.rotationOther')
}

/** A recorded step's name in the reader's language, or the raw step.
 *
 * Falling back to the raw name is deliberate: the ledger is append-only and the
 * writers grow steps, so a step this page has no word for yet is still the
 * honest answer to "what happened here". Inventing a generic label for it would
 * make two different steps read identically.
 */
function stageLabel(step: string): string {
  if (step === 'requested') return t('perf.stageRequested')
  if (step === 'server-fallback-commit') return t('perf.stageServerDrew')
  if (step === 'recover:illustrator-dispatched') return t('perf.stageRetry')
  if (step === 'recover:illustrator-committed') return t('perf.stageRetryDone')
  if (step === 'recover:illustrator-timeout') return t('perf.stageRetryTimeout')
  if (step === 'tool:endless_read_runtime') return t('perf.stageRead')
  if (step === 'tool:endless_advance_turn') return t('perf.stageCommit')
  if (step === 'tool:endless_paint_backdrop') return t('perf.stageAskArt')
  if (step === 'tool:endless_trace_reference') return t('perf.stageTrace')
  if (step === 'tool:endless_select_reference') return t('perf.stagePickRef')
  if (step === 'tool:endless_submit_backdrop_draft') return t('perf.stageDraft')
  if (step === 'tool:endless_commit_backdrop') return t('perf.stagePublish')
  if (step === 'tool:endless_commit_fallback_backdrop') return t('perf.stageHandDrawn')
  return step.startsWith('tool:') ? step.slice('tool:'.length) : step
}

/** One turn's stages, opened under its row.
 *
 * Two sources, deliberately not merged into one list: the turn's own recorded
 * totals (which the phone's table does not show, so this is also their detail
 * path) and the ordered trace. The trace's `gapMs` is called out as thinking
 * time because that is what it is — the wait before a step, outside any
 * measured server call — and on a slow turn it is nearly all of it.
 */
function Stages({ runId, row }: { runId: string; row: PerfTurn }) {
  const [trace, setTrace] = useState<TurnStages | null>(null)
  const [problem, setProblem] = useState('')

  useEffect(() => {
    let alive = true
    api
      .turnStages(runId, row.turn)
      .then((out) => {
        if (alive) setTrace(out)
      })
      .catch((e: Error) => {
        if (alive) setProblem(e.message)
      })
    return () => {
      alive = false
    }
  }, [runId, row.turn])

  // The narrator's own two halves: how long it looked before it wrote, and the
  // rest of the span up to the commit. Derived rather than recorded — one span
  // and its prefix are what the commit row holds.
  const wrote =
    row.storyMs !== undefined && row.readMs !== undefined && row.storyMs >= row.readMs
      ? row.storyMs - row.readMs
      : undefined

  /* What the narrator actually called, in order — the answer to the question
     `toolCalls` raises but cannot settle: not how many calls, but whether it
     wrote without reading first, painted twice, or never reached the commit.

     Named through the SAME lookup the art lane uses, so one event is not
     "published" two lines above and `commit_backdrop` here; the lookup's
     fallback keeps a tool this page has no word for yet literal instead of
     inventing a label that would make two steps read alike.

     Rendered as a sequence rather than in the art lane's step/duration shape,
     because no per-call timing is recorded — borrowing that shape would promise
     a number the ledger does not have. `clipped` is derived from the count
     rather than from a stored flag: the recorder caps the trail and leaves the
     count whole precisely so the difference is the truncation signal. */
  const trail = row.tools ?? []
  const clipped =
    row.toolCalls !== undefined && row.toolCalls > trail.length ? row.toolCalls - trail.length : 0

  /* Each fact names the catalog key it came from, and whether that key is one of
     the columns a phone drops (`NARROW_HIDDEN`). Derived from the one list rather
     than hand-marked, and hidden above the breakpoint by the stylesheet rather
     than by a width test here: the table hides its cells in CSS, and two
     mechanisms deciding the same breakpoint drift apart. */
  const dup = (key: string) => (NARROW_HIDDEN as readonly string[]).includes(key)
  const facts: Array<{ key: string; value: string }> = [
    {
      key: 'perf.declared',
      value: `${row.form ? t(row.form === 'patch' ? 'perf.formPatch' : 'perf.formFull') : '—'} ${kb(row.declaredBytes)}`,
    },
    {
      key: 'perf.tokens',
      value: row.usedTokens !== undefined ? row.usedTokens.toLocaleString() : '—',
    },
    { key: 'perf.context', value: row.pct !== undefined ? `${row.pct}%` : '—' },
  ]
  if (row.credits !== undefined) facts.push({ key: 'perf.credits', value: row.credits.toFixed(2) })
  if (row.toolCalls !== undefined)
    facts.push({ key: 'perf.toolCalls', value: String(row.toolCalls) })
  if (row.model) facts.push({ key: 'perf.model', value: row.model })
  if (row.rotation) facts.push({ key: 'perf.events', value: rotationLabel(row.rotation) })

  const events = trace?.events ?? []

  return (
    <div className="ew-perf-stages">
      <dl className="ew-perf-facts">
        {facts.map((f) => (
          <div className={`ew-perf-fact${dup(f.key) ? ' ew-perf-fact-dup' : ''}`} key={f.key}>
            <dt>{t(f.key)}</dt>
            <dd>{f.value}</dd>
          </div>
        ))}
      </dl>

      <div className="ew-perf-lane">
        <div className="ew-perf-lanehead">{t('perf.laneStory')}</div>
        <ul className="ew-perf-steps">
          <li>
            <span className="ew-perf-step">{t('perf.stageRead')}</span>
            <span className="ew-perf-took">{ms(row.readMs)}</span>
          </li>
          <li>
            <span className="ew-perf-step">{t('perf.stageWrote')}</span>
            <span className="ew-perf-took">{ms(wrote)}</span>
          </li>
        </ul>
        {trail.length ? (
          <div className="ew-perf-trail">
            <span className="ew-perf-traillabel">{t('perf.trail')}</span>
            <span className="ew-perf-trailseq">
              {trail.map((name) => stageLabel(`tool:${name}`)).join(' → ')}
              {clipped ? ` → ${t('perf.trailMore', { count: clipped })}` : ''}
            </span>
          </div>
        ) : null}
      </div>

      <div className="ew-perf-lane">
        <div className="ew-perf-lanehead">{t('perf.laneArt')}</div>
        {problem ? <div className="ew-modal-problem">{problem}</div> : null}
        {!problem && trace === null ? (
          <div className="ew-meta">{t('perf.stagesLoading')}</div>
        ) : null}
        {trace !== null && events.length === 0 ? (
          <div className="ew-meta">{t('perf.stagesNone')}</div>
        ) : null}
        {events.length ? (
          <ul className="ew-perf-steps">
            {events.map((e, i) => (
              <li key={`${e.step}-${e.at}-${i}`}>
                <span className="ew-perf-step">
                  {stageLabel(e.step)}
                  {e.attempt !== undefined ? ` #${e.attempt}` : ''}
                </span>
                <span className="ew-perf-took">
                  {/* The wait BEFORE this step is the interesting number, so it
                      leads; the server's own time follows only when recorded. */}
                  {e.gapMs !== undefined && e.gapMs !== null
                    ? t('perf.thought', { took: ms(e.gapMs) })
                    : ''}
                  {e.serverMs !== undefined
                    ? ` ${t('perf.onServer', { took: ms(e.serverMs) })}`
                    : ''}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  )
}

export function PerfPage({
  runId,
  name,
  onBack,
}: {
  runId: string
  name: string
  onBack: () => void
}) {
  const [turns, setTurns] = useState<PerfTurn[] | null>(null)
  const [creditNote, setCreditNote] = useState('')
  const [problem, setProblem] = useState('')
  /** Which turn is open. One at a time: two open expansions push the rows they
   *  are meant to explain off the screen, on a phone especially. */
  const [openTurn, setOpenTurn] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    api
      .perf(runId)
      .then((out) => {
        if (alive) {
          setTurns(out.turns)
          setCreditNote(out.creditNote)
        }
      })
      .catch((e: Error) => {
        if (alive) setProblem(e.message)
      })
    return () => {
      alive = false
    }
  }, [runId])

  const rows = [...(turns ?? [])].reverse()
  const maxStory = Math.max(0, ...rows.map((r) => r.storyMs ?? 0))
  const maxArt = Math.max(0, ...rows.map((r) => r.artMs ?? 0))
  const hasCredits = creditNote === 'credits'
  // The expansion spans every column, including the ones a phone has hidden —
  // `colSpan` counts cells, and a hidden cell is still a cell.
  const columns = hasCredits ? 8 : 7

  return (
    <div className="ew-perf">
      <div className="ew-perf-head">
        <button className="ew-btn ew-btn-quiet" type="button" onClick={onBack}>
          {t('perf.back')}
        </button>
        <h2 className="ew-perf-title">{t('perf.title', { name })}</h2>
      </div>
      <div className="ew-meta">{hasCredits ? t('perf.creditsNote') : t('perf.tokensNote')}</div>
      {problem ? <div className="ew-modal-problem">{problem}</div> : null}
      {turns !== null && rows.length === 0 ? (
        <div className="ew-meta">{t('perf.empty')}</div>
      ) : null}
      {rows.length ? (
        /* The exact markup a scrollable table needs to stay reachable: the region
           carries the tab stop and takes its name from the caption, and the
           overflow lives here rather than on the table — moving either onto the
           `<table>` stops it scrolling and destroys its semantics. */
        <div
          className="ew-perf-scroll"
          role="region"
          aria-labelledby="ew-perf-caption"
          tabIndex={0}
        >
          <table className="ew-perf-table">
            <caption id="ew-perf-caption" className="ew-perf-caption">
              {t('perf.caption', { name })}
            </caption>
            <thead>
              <tr>
                <th>{t('perf.turn')}</th>
                <th>{t('perf.story')}</th>
                <th>{t('perf.art')}</th>
                <th className="ew-perf-rest">{t('perf.declared')}</th>
                {hasCredits ? <th className="ew-perf-rest">{t('perf.credits')}</th> : null}
                <th className="ew-perf-rest">{t('perf.tokens')}</th>
                <th className="ew-perf-rest">{t('perf.context')}</th>
                <th className="ew-perf-rest">{t('perf.events')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const open = openTurn === r.turn
                return [
                  <tr className="ew-perf-row" key={r.turn}>
                    <td>
                      {/* A real button, not a click handler on the row: a `<tr>`
                          takes no focus and announces no state, so a keyboard or
                          screen-reader user would have no way in. */}
                      <button
                        className="ew-perf-open"
                        type="button"
                        aria-expanded={open}
                        aria-controls={`ew-perf-stages-${r.turn}`}
                        onClick={() => setOpenTurn(open ? null : r.turn)}
                      >
                        <span className="ew-perf-caret" aria-hidden="true">
                          {open ? '▾' : '▸'}
                        </span>
                        {r.turn}
                        <span className="ew-perf-openhint">{t('perf.openStages')}</span>
                      </button>
                    </td>
                    <td>
                      {ms(r.storyMs)}{' '}
                      {r.storyMs !== undefined ? <Bar value={r.storyMs} max={maxStory} /> : null}
                    </td>
                    <td>
                      {r.artMs !== undefined ? (
                        <>
                          {ms(r.artMs)} <Bar value={r.artMs} max={maxArt} />
                          {r.outcome === 'fallback' ? ` ${t('perf.fallback')}` : ''}
                        </>
                      ) : r.outcome === 'pending' ? (
                        t('perf.artPending')
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="ew-perf-rest">
                      {r.form ? t(r.form === 'patch' ? 'perf.formPatch' : 'perf.formFull') : '—'}
                      {r.declaredBytes !== undefined ? ` ${kb(r.declaredBytes)}` : ''}
                    </td>
                    {hasCredits ? (
                      <td className="ew-perf-rest">
                        {r.credits !== undefined ? r.credits.toFixed(2) : '—'}
                      </td>
                    ) : null}
                    <td className="ew-perf-rest">
                      {r.usedTokens !== undefined ? r.usedTokens.toLocaleString() : '—'}
                    </td>
                    <td className="ew-perf-rest">{r.pct !== undefined ? `${r.pct}%` : '—'}</td>
                    <td className="ew-perf-rest">{r.rotation ? rotationLabel(r.rotation) : ''}</td>
                  </tr>,
                  open ? (
                    <tr className="ew-perf-stagerow" key={`${r.turn}-stages`}>
                      <td colSpan={columns} id={`ew-perf-stages-${r.turn}`}>
                        <Stages runId={runId} row={r} />
                      </td>
                    </tr>
                  ) : null,
                ]
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
