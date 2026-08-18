/** Looking back over the months already lived.
 *
 * A separate component and a separate fetch, because reading backwards and playing
 * forwards want opposite things. The play page is re-read every few seconds while a
 * month is being written and has to stay small; a life's history is a hundred turns
 * of prose and is read only when the player deliberately asks for it. Folding one
 * into the other would make every poll carry the whole life.
 *
 * Newest first, and paged from the newest end — that is the direction a life gets
 * re-read in: what just happened, then further back.
 */

import { useCallback, useEffect, useState } from 'react'

import type { PastTurn } from './api'
import { api } from './api'
import { t } from './strings'
import { Prose } from './ui'

export function History({ runId }: { runId: string }) {
  const [turns, setTurns] = useState<PastTurn[]>([])
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  const load = useCallback(async (before: number) => {
    setBusy(true)
    setFailed(false)
    try {
      const out = await api.chronicle(runId, before)
      // Appended, not replaced: paging further back must not lose what is already
      // on screen and being read.
      setTurns((have) => (before > 0 ? [...have, ...out.turns] : out.turns))
      setMore(out.more)
    } catch {
      setFailed(true)
    }
    setBusy(false)
  }, [runId])

  useEffect(() => { void load(0) }, [load])

  if (failed && !turns.length) {
    return <div className="ew-meta">{t('history.unreadable')}</div>
  }
  if (!turns.length) {
    return <div className="ew-meta">{busy ? t('history.reading') : t('history.none')}</div>
  }

  const oldest = turns[turns.length - 1]?.turn ?? 0

  return (
    <div className="ew-history">
      {turns.map((p) => (
        <div className="ew-past" key={p.turn}>
          <div className="ew-past-head">
            <span className="ew-past-turn">{t('play.turn', { turn: p.turn })}</span>
            {/* The fork, not only the outcome. A month re-read without the choice
                that caused it is the least useful half of the memory. */}
            {p.action ? (
              <span className="ew-past-action">{t('history.chose', { action: p.action })}</span>
            ) : null}
          </div>
          <Prose text={p.prose} />
        </div>
      ))}

      {more ? (
        <button
          className="ew-btn"
          type="button"
          disabled={busy}
          onClick={() => void load(oldest)}
        >
          {busy ? t('history.reading') : t('history.earlier')}
        </button>
      ) : (
        <div className="ew-meta">{t('history.beginning')}</div>
      )}
    </div>
  )
}
