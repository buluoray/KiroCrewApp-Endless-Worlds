/** The performance page: what each committed turn of a life cost.
 *
 * A plain table, newest month first, with inline proportional bars — no chart
 * library for four columns of numbers. Every latency bar is scaled against the
 * page's own maximum so a slow month is visibly slow *relative to this life*,
 * which is the comparison an audit actually makes.
 *
 * Tokens are labelled as tokens. The backend exposes no billing signal, and a
 * number dressed up as money that can never be reconciled with a bill would
 * poison the audit this page exists for.
 */

import { useEffect, useState } from 'react'

import type { PerfTurn } from './api'
import { api } from './api'
import { t } from './strings'

function Bar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  return (
    <span className="ew-perfbar" aria-hidden="true">
      <span className="ew-perfbar-fill" style={{ width: `${pct}%` }} />
    </span>
  )
}

function ms(v: number | undefined): string {
  if (v === undefined) return '—'
  return v >= 10000 ? `${Math.round(v / 1000)}s` : `${(v / 1000).toFixed(1)}s`
}

/** Explicit per-reason lookups so every catalog key appears verbatim. */
function rotationLabel(reason: string): string {
  if (reason === 'chapter') return t('perf.rotationChapter')
  if (reason === 'budget') return t('perf.rotationBudget')
  if (reason === 'install') return t('perf.rotationInstall')
  if (reason === 'closed') return t('perf.rotationClosed')
  return t('perf.rotationOther')
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
  const [problem, setProblem] = useState('')

  useEffect(() => {
    let alive = true
    api
      .perf(runId)
      .then((out) => {
        if (alive) setTurns(out.turns)
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

  return (
    <div className="ew-perf">
      <div className="ew-perf-head">
        <button className="ew-btn ew-btn-quiet" type="button" onClick={onBack}>
          {t('perf.back')}
        </button>
        <h2 className="ew-perf-title">{t('perf.title', { name })}</h2>
      </div>
      <div className="ew-meta">{t('perf.tokensNote')}</div>
      {problem ? <div className="ew-modal-problem">{problem}</div> : null}
      {turns !== null && rows.length === 0 ? (
        <div className="ew-meta">{t('perf.empty')}</div>
      ) : null}
      {rows.length ? (
        <table className="ew-perf-table">
          <thead>
            <tr>
              <th>{t('perf.turn')}</th>
              <th>{t('perf.story')}</th>
              <th>{t('perf.art')}</th>
              <th>{t('perf.declared')}</th>
              <th>{t('perf.tokens')}</th>
              <th>{t('perf.context')}</th>
              <th>{t('perf.events')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.turn}>
                <td>{r.turn}</td>
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
                <td>
                  {r.form ? t(r.form === 'patch' ? 'perf.formPatch' : 'perf.formFull') : '—'}
                  {r.declaredBytes !== undefined ? ` ${(r.declaredBytes / 1024).toFixed(1)}KB` : ''}
                </td>
                <td>{r.usedTokens !== undefined ? r.usedTokens.toLocaleString() : '—'}</td>
                <td>{r.pct !== undefined ? `${r.pct}%` : '—'}</td>
                <td>{r.rotation ? rotationLabel(r.rotation) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  )
}
