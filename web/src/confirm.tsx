/** Deleting a world — the second ask.
 *
 * The confirmation is GRADUATED, because the stakes are not uniform. A world with
 * no lives in it, backed by a seed, can be reinstalled from the install tree: the
 * honest ask there is one button, and dressing it up as irreversible teaches the
 * player to click through warnings. A world holding lives is hours of narrated
 * story that no seed can bring back, so that ask requires typing the world's name —
 * the one ritual that cannot be satisfied by a reflex.
 *
 * What the dialog must never do is guess. The life count comes from the server when
 * the dialog opens and is sent back as a precondition, so a confirmation always
 * names the number the delete will act on. If a life began in another tab in
 * between, the server refuses and this dialog re-asks with the new number rather
 * than proceeding on the old one.
 */

import { useEffect, useRef, useState } from 'react'

import type { DeletionFacts } from './api'
import { ApiError, api } from './api'
import { t } from './strings'

type Phase = 'loading' | 'asking' | 'working' | 'failed'

export function DeleteWorldDialog({
  worldId, onCancel, onDeleted,
}: {
  worldId: string
  onCancel: () => void
  onDeleted: (facts: { restorable: boolean; lives: number }) => void
}) {
  const [facts, setFacts] = useState<DeletionFacts | null>(null)
  const [phase, setPhase] = useState<Phase>('loading')
  const [problem, setProblem] = useState<string>('')
  const [typed, setTyped] = useState('')
  const panel = useRef<HTMLDivElement | null>(null)

  const look = (fresh = false) => {
    api.worldDeletion(worldId)
      .then((f) => {
        setFacts(f)
        setPhase('asking')
        // A changed count invalidates anything already typed: the sentence the
        // player agreed to is not the sentence on screen any more.
        if (fresh) setTyped('')
      })
      .catch((e: Error) => { setProblem(e.message); setPhase('failed') })
  }

  useEffect(() => {
    setPhase('loading')
    look()
    // worldId is fixed for the dialog's lifetime; the parent remounts it per world.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [worldId])

  // Escape cancels, and focus moves into the panel so the keyboard is not still
  // driving the shelf behind an open modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  const lives = facts?.liveCount ?? 0
  // Typing is required only where deletion is actually unrecoverable.
  const mustType = lives > 0
  const named = typed.trim() === (facts?.title ?? '').trim()
  const armed = phase === 'asking' && !!facts && (!mustType || named)

  const confirm = () => {
    if (!facts || !armed) return
    setPhase('working')
    setProblem('')
    api.deleteWorld(worldId, facts.liveCount)
      .then((out) => onDeleted({ restorable: out.restorable, lives: out.livesRemoved.length }))
      .catch((e: Error) => {
        const code = e instanceof ApiError ? e.code : ''
        if (code === 'lives_changed') {
          setProblem(t('delete.changed'))
          look(true)
          return
        }
        if (code === 'turn_in_flight') {
          setProblem(t('delete.inFlight'))
          look(true)
          return
        }
        setProblem(e.message)
        setPhase('failed')
      })
  }

  return (
    <div className="ew-modal-wrap" role="presentation" onClick={onCancel}>
      <div
        className="ew-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t('delete.title', { world: facts?.title ?? worldId })}
        tabIndex={-1}
        ref={panel}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ew-modal-title">
          {t('delete.title', { world: facts?.title ?? worldId })}
        </div>

        {phase === 'loading' ? (
          <div className="ew-meta">{t('delete.counting')}</div>
        ) : null}

        {facts ? (
          <>
            <div className="ew-modal-body">
              {lives === 0
                ? t('delete.noLives')
                : t('delete.withLives', { n: lives })}
            </div>

            {lives ? (
              <ul className="ew-doomed">
                {facts.lives.map((l) => (
                  <li key={l.runId}>
                    <span className="ew-doomed-name">
                      {l.subtitle || l.title || l.runId}
                    </span>
                    <span className="ew-doomed-where">
                      {l.unreadable
                        ? t('life.unreadable')
                        : l.generating
                          ? t('life.generating')
                          : l.ended
                            ? t('life.ended')
                            : t('life.turn', { turn: l.turn })}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="ew-meta ew-modal-note">
              {facts.restorable ? t('delete.restorable') : t('delete.forever')}
            </div>

            {mustType ? (
              <label className="ew-modal-gate">
                <span className="ew-meta">
                  {t('delete.typeToConfirm', { world: facts.title })}
                </span>
                <input
                  className="ew-input"
                  value={typed}
                  autoFocus
                  spellCheck={false}
                  onChange={(e) => setTyped(e.target.value)}
                  aria-label={t('delete.typeToConfirm', { world: facts.title })}
                />
              </label>
            ) : null}
          </>
        ) : null}

        {problem ? <div className="ew-modal-problem">{problem}</div> : null}

        <div className="ew-bar ew-modal-bar">
          <button className="ew-btn" type="button" onClick={onCancel}>
            {t('delete.cancel')}
          </button>
          <button
            className="ew-btn ew-btn-danger"
            type="button"
            disabled={!armed}
            onClick={confirm}
          >
            {phase === 'working'
              ? t('delete.working')
              : lives === 0
                ? t('delete.goNoLives')
                : t('delete.go', { n: lives })}
          </button>
        </div>
      </div>
    </div>
  )
}
