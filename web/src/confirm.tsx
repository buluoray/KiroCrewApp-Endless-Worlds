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

import type { DeletionFacts, LifeDeletionFacts } from './api'
import { ApiError, api } from './api'
import { t } from './strings'

type Phase = 'loading' | 'asking' | 'working' | 'failed'

/**
 * Ending ONE life.
 *
 * Always requires typing, unlike a world with no lives in it. A world can be
 * reinstalled from its seed; a life cannot be reconstructed from anything — the
 * months behind it exist only in its own chronicle. So there is no cheap tier here,
 * and the ask names the month it is ending.
 */
export function DeleteLifeDialog({
  runId, onCancel, onDeleted,
}: {
  runId: string
  onCancel: () => void
  onDeleted: (turn: number) => void
}) {
  const [facts, setFacts] = useState<LifeDeletionFacts | null>(null)
  const [phase, setPhase] = useState<Phase>('loading')
  const [problem, setProblem] = useState('')
  const [typed, setTyped] = useState('')
  const panel = useRef<HTMLDivElement | null>(null)

  const look = (fresh = false) => {
    api.lifeDeletion(runId)
      .then((f) => { setFacts(f); setPhase('asking'); if (fresh) setTyped('') })
      .catch((e: Error) => { setProblem(e.message); setPhase('failed') })
  }

  useEffect(() => {
    setPhase('loading')
    look()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  // What the player types. Its own name, which for a life is the opening answers
  // that tell it apart — falling back to the world's title when it has none yet,
  // and to the id for a life too damaged to have either.
  const name = (facts?.subtitle || facts?.title || facts?.runId || '').trim()
  const armed = phase === 'asking' && !!facts && typed.trim() === name && !!name

  const confirm = () => {
    if (!facts || !armed) return
    setPhase('working')
    setProblem('')
    api.deleteLife(runId, facts.turn)
      .then((out) => onDeleted(out.turn))
      .catch((e: Error) => {
        const code = e instanceof ApiError ? e.code : ''
        if (code === 'turn_changed') { setProblem(t('life.delete.changed')); look(true); return }
        if (code === 'turn_in_flight') { setProblem(t('life.delete.inFlight')); look(true); return }
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
        aria-label={t('life.delete.title')}
        tabIndex={-1}
        ref={panel}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ew-modal-title">{t('life.delete.title')}</div>

        {phase === 'loading' ? (
          <div className="ew-meta">{t('life.delete.reading')}</div>
        ) : null}

        {facts ? (
          <>
            <div className="ew-modal-body">
              {facts.unreadable
                ? t('life.delete.unreadable')
                : facts.turn > 0
                  ? t('life.delete.months', { name, n: facts.turn })
                  : t('life.delete.unborn', { name })}
            </div>
            <div className="ew-meta ew-modal-note">{t('life.delete.forever')}</div>

            <label className="ew-modal-gate">
              <span className="ew-meta">{t('life.delete.typeToConfirm', { name })}</span>
              <input
                className="ew-input"
                value={typed}
                autoFocus
                spellCheck={false}
                onChange={(e) => setTyped(e.target.value)}
                aria-label={t('life.delete.typeToConfirm', { name })}
              />
            </label>
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
            {phase === 'working' ? t('delete.working') : t('life.delete.go')}
          </button>
        </div>
      </div>
    </div>
  )
}

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
