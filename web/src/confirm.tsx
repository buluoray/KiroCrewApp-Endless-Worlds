/** Deleting a world — the second ask.
 *
 * One press, and what it costs stated plainly. A world with no lives in it can be
 * reinstalled from its seed; a world holding lives is hours of narrated story no
 * seed brings back, so the ask NAMES that — the count, and every life by name and
 * month — instead of demanding the title be typed. Retyping a name on screen is a
 * ritual a reflex satisfies too, and it taxes every honest deletion to do it.
 *
 * What the dialog must never do is guess. The life count comes from the server when
 * the dialog opens and is sent back as a precondition, so a confirmation always
 * names the number the delete will act on. If a life began in another tab in
 * between, the server refuses and this dialog re-asks with the new number rather
 * than proceeding on the old one.
 */

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import type { DeletionFacts, LifeDeletionFacts } from './api'
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
  const panel = useRef<HTMLDivElement | null>(null)

  const look = () => {
    api.worldDeletion(worldId)
      .then((f) => {
        setFacts(f)
        setPhase('asking')
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
  // One deliberate press, not a typing ritual. Copying a name out proves only that
  // the player can copy a name: the reflex it is meant to interrupt just becomes a
  // longer reflex, and the cost lands on every honest deletion. What actually earns
  // the confidence is naming the exact loss — the count, and each life by name and
  // month — which the panel below already does.
  const armed = phase === 'asking' && !!facts

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
          look()
          return
        }
        if (code === 'turn_in_flight') {
          setProblem(t('delete.inFlight'))
          look()
          return
        }
        setProblem(e.message)
        setPhase('failed')
      })
  }

  // Portalled to body, and NOT because of a transformed ancestor: the app root
  // carries `.ew-root > *:not(.ew-backdrop) { position: relative; z-index: 1 }` to
  // lift its children above the page backdrop, and at (0,2,0) that beats this wrap's
  // own (0,1,0) `position: fixed`. The wrap therefore laid out as an ordinary block
  // at the END of the page — a scrim over nothing and a panel far below the fold,
  // which is exactly how it was reported. At body level the rule cannot reach it.
  return createPortal((
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
                : t(lives === 1 ? 'delete.withLivesOne' : 'delete.withLives', { n: lives })}
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
                : t(lives === 1 ? 'delete.goOne' : 'delete.go', { n: lives })}
          </button>
        </div>
      </div>
    </div>
  ), document.body)
}
