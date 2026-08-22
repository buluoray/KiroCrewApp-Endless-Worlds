/** The legacy picker — the ending page's bridge into a next life (design §9).
 *
 * Offered only when the world declares lineage and the life has ended; the
 * player chooses what crosses, sees each character's current relation reading
 * before deciding, and confirms deliberately — an inheritance is the one
 * choice that outlives the life making it. The copy is performed server-side
 * with provenance; nothing here can widen what the ending screen offered.
 */

import { useEffect, useState } from 'react'

import { api } from './api'
import { mt } from './memory-state'

type Candidate = {
  id: string
  kind: string
  name: string
  summary: string
  appearances: number
  relations?: Array<{ type: string; level: number; value: string }>
  open?: boolean
}

const GROUP_ORDER = ['characters', 'objects', 'groups', 'threads', 'places'] as const
const MAX_PICK = 12

export function LegacyPicker({
  runId,
  lang,
  onClose,
  onContinue,
}: {
  runId: string
  lang: string
  onClose: () => void
  /** Create the heir with this selection; the caller owns navigation. */
  onContinue: (selected: string[]) => Promise<void>
}) {
  const [groups, setGroups] = useState<Record<string, Candidate[]> | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    api
      .legacyCandidates(runId)
      .then((got) => {
        if (alive) setGroups(got.candidates)
      })
      .catch((e) => {
        if (alive) setError((e as Error).message)
      })
    return () => {
      alive = false
    }
  }, [runId])

  const toggle = (id: string) =>
    setPicked((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : p.length < MAX_PICK ? [...p, id] : p,
    )

  const total = groups ? GROUP_ORDER.reduce((n, g) => n + (groups[g]?.length ?? 0), 0) : 0

  return (
    <div
      className="ewl-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={mt(lang, 'legacy.title')}
    >
      <div className="ewl-head">
        <div className="ewl-title">{mt(lang, 'legacy.title')}</div>
        <button className="ews-btn" type="button" onClick={onClose}>
          {mt(lang, 'legacy.close')}
        </button>
      </div>
      <div className="ewl-hint">{mt(lang, 'legacy.hint')}</div>

      <div className="ewl-body">
        {error ? <div className="ewl-empty">{error}</div> : null}
        {groups && !total ? <div className="ewl-empty">{mt(lang, 'legacy.none')}</div> : null}
        {groups
          ? GROUP_ORDER.map((g) => {
              const rows = groups[g] ?? []
              if (!rows.length) return null
              return (
                <div key={g}>
                  <div className="ewl-group">{mt(lang, `legacy.group.${g}`)}</div>
                  {rows.map((c) => (
                    <label className="ewl-row" key={c.id}>
                      <input
                        type="checkbox"
                        checked={picked.includes(c.id)}
                        disabled={!picked.includes(c.id) && picked.length >= MAX_PICK}
                        onChange={() => toggle(c.id)}
                      />
                      <span className="ewl-name">{c.name}</span>
                      <span className="ewl-meta">
                        {c.relations?.length
                          ? c.relations
                              .map(
                                (r) =>
                                  `${r.type}${r.value ? ` ${r.value}` : r.level ? ` ${r.level > 0 ? '+' : ''}${r.level}` : ''}`,
                              )
                              .join(' · ')
                          : c.kind === 'thread'
                            ? mt(
                                lang,
                                c.open ? 'star.detail.thread.open' : 'star.detail.thread.done',
                              )
                            : c.summary}
                      </span>
                    </label>
                  ))}
                </div>
              )
            })
          : null}
      </div>

      <div className="ewl-foot">
        <span className="ewl-count">
          {mt(lang, 'legacy.picked', { n: picked.length, max: MAX_PICK })}
        </span>
        {confirming ? (
          <>
            <span className="ewl-ask">{mt(lang, 'legacy.confirmAsk')}</span>
            <button
              className="ews-btn"
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                setError('')
                try {
                  await onContinue(picked)
                } catch (e) {
                  setError((e as Error).message)
                  setBusy(false)
                  setConfirming(false)
                }
              }}
            >
              {mt(lang, 'legacy.confirmYes')}
            </button>
            <button className="ews-btn" type="button" onClick={() => setConfirming(false)}>
              {mt(lang, 'legacy.confirmNo')}
            </button>
          </>
        ) : (
          <button
            className="ews-btn"
            type="button"
            disabled={!picked.length}
            onClick={() => setConfirming(true)}
          >
            {mt(lang, 'legacy.continue')}
          </button>
        )}
      </div>
      <style>{CSS_TEXT}</style>
    </div>
  )
}

const CSS_TEXT = `
.ewl-overlay {
  position: fixed; inset: 0; z-index: 70; display: flex; flex-direction: column;
  background: var(--bg, #14151f); color: var(--fg, #e5e7eb);
}
.ewl-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; border-bottom: 1px solid var(--border, #2d2f3d);
}
.ewl-title { font-weight: 600; }
.ewl-hint {
  padding: 10px 16px 0; font-size: 13px; line-height: 1.7;
  color: var(--muted, #9ca3af);
}
.ewl-body { flex: 1; overflow: auto; padding: 10px 16px; max-width: 640px; }
.ewl-group { font-size: 12px; color: var(--muted, #9ca3af); margin: 14px 0 6px; }
.ewl-row {
  display: flex; gap: 9px; align-items: baseline; padding: 6px 0; cursor: pointer;
}
.ewl-name { font-weight: 500; flex: 0 0 auto; }
.ewl-meta { font-size: 12px; color: var(--muted, #9ca3af); }
.ewl-empty { padding: 30px 0; color: var(--muted, #9ca3af); }
.ewl-foot {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  padding: 10px 16px; border-top: 1px solid var(--border, #2d2f3d);
}
.ewl-count { font-size: 12px; color: var(--muted, #9ca3af); margin-inline-end: auto; }
.ewl-ask { font-size: 13px; }
.ews-btn {
  appearance: none; border: 1px solid var(--border, #2d2f3d); background: none;
  color: inherit; font: inherit; font-size: 13px; padding: 5px 12px;
  border-radius: 8px; cursor: pointer;
}
.ews-btn:disabled { opacity: 0.5; cursor: default; }
`
