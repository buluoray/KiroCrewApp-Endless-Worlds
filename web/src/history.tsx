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
  // Reading a life as a list of what happened, not pages of prose.
  const [eventsOnly, setEventsOnly] = useState(false)
  const [jump, setJump] = useState('')
  // Full-text search across the whole life. `query` is what is currently applied
  // (so paging carries it); `search` is the box the player is typing in.
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')

  const load = useCallback(async (before: number, replace = false, q = '') => {
    setBusy(true)
    setFailed(false)
    try {
      const out = await api.chronicle(runId, before, q)
      // Paging further back appends; a jump, a search, or a fresh open replaces.
      setTurns((have) => (before > 0 && !replace ? [...have, ...out.turns] : out.turns))
      setMore(out.more)
    } catch {
      setFailed(true)
    }
    setBusy(false)
  }, [runId])

  useEffect(() => { void load(0) }, [load])

  const jumpTo = () => {
    const n = parseInt(jump, 10)
    // `before` is exclusive, so n+1 lands the page ON turn n rather than just above it.
    if (Number.isFinite(n) && n > 0) void load(n + 1, true, query)
  }

  const runSearch = () => {
    const q = search.trim()
    setQuery(q)
    void load(0, true, q)
  }
  const clearSearch = () => {
    setSearch('')
    setQuery('')
    void load(0, true, '')
  }

  if (failed && !turns.length) {
    return (
      <div className="ew-meta">
        {t('history.unreadable')}
        <button
          className="ew-btn ew-btn-sm"
          type="button"
          style={{ marginInlineStart: '8px' }}
          onClick={() => void load(0)}
        >
          {t('library.retry')}
        </button>
      </div>
    )
  }
  if (!turns.length && !query) {
    return <div className="ew-meta">{busy ? t('history.reading') : t('history.none')}</div>
  }

  const oldest = turns[turns.length - 1]?.turn ?? 0
  const rows = eventsOnly ? turns.filter((p) => p.events.length) : turns

  return (
    <div className="ew-history">
      <div className="ew-history-bar">
        <button
          className="ew-btn ew-btn-sm"
          type="button"
          aria-pressed={eventsOnly}
          onClick={() => setEventsOnly((v) => !v)}
        >
          {eventsOnly ? t('history.showAll') : t('history.eventsOnly')}
        </button>
        <input
          className="ew-jump"
          inputMode="numeric"
          value={jump}
          placeholder={t('history.jumpPlaceholder')}
          onChange={(e) => setJump(e.target.value.replace(/[^0-9]/g, ''))}
          onKeyDown={(e) => { if (e.key === 'Enter') jumpTo() }}
        />
        <button className="ew-btn ew-btn-sm" type="button" onClick={jumpTo}>
          {t('history.jump')}
        </button>
        <input
          className="ew-jump ew-search"
          value={search}
          placeholder={t('history.searchPlaceholder')}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') runSearch() }}
        />
        <button className="ew-btn ew-btn-sm" type="button" onClick={runSearch}>
          {t('history.search')}
        </button>
        {query ? (
          <button className="ew-btn ew-btn-sm" type="button" onClick={clearSearch}>
            {t('history.searchClear')}
          </button>
        ) : null}
      </div>

      {query && !turns.length && !busy ? (
        <div className="ew-meta">{t('history.noMatches', { q: query })}</div>
      ) : null}

      {eventsOnly && !rows.length ? (
        <div className="ew-meta">{t('history.noEvents')}</div>
      ) : null}

      {rows.map((p) => (
        <div className="ew-past" key={p.turn}>
          <div className="ew-past-head">
            <span className="ew-past-turn">{t('play.turn', { turn: p.turn })}</span>
            {/* The fork, not only the outcome. A month re-read without the choice
                that caused it is the least useful half of the memory. */}
            {p.action ? (
              <span className="ew-past-action">{t('history.chose', { action: p.action })}</span>
            ) : null}
          </div>
          {eventsOnly ? null : <Prose text={p.prose} />}
          {p.events.length || p.gains.length ? (
            <div className="ew-marks">
              {p.events.map((ev, i) => (
                <div className="ew-mark" key={`e${i}`}>{ev}</div>
              ))}
              {p.gains.map((g, i) => (
                <div className="ew-mark ew-mark-gain" key={`g${i}`}>
                  {g.field}{g.amount ? ` ${g.amount}` : ''}
                  {g.source ? (
                    <span className="ew-sub">{t('history.via', { source: g.source })}</span>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ))}

      {more ? (
        <button
          className="ew-btn"
          type="button"
          disabled={busy}
          onClick={() => void load(oldest, false, query)}
        >
          {busy ? t('history.reading') : t('history.earlier')}
        </button>
      ) : (
        <div className="ew-meta">{t('history.beginning')}</div>
      )}
    </div>
  )
}
