import { useCallback, useEffect, useState } from 'react'

import type { PlayView, SceneRow } from './api'
import { api } from './api'

/** How often a life mid-generation is re-read. A month takes tens of seconds, so
 *  this is about the page converging on its own rather than about latency. */
const GENERATING_POLL_MS = 3000

/**
 * What the player has armed or committed.
 *
 * A world's choice ids come from the narrator, so no sentinel string is safe from
 * colliding with one. The prefix therefore goes on the NARRATOR's side: the two
 * fixed targets keep plain names, and anything world-supplied is namespaced. A
 * narrator that emits a choice literally called "act" cannot then hijack the
 * free-text button's state.
 */
const ACT = 'act'
const OPEN = 'open'
const choiceTarget = (id: string) => `c:${id}`
import { pick, t, useSetLanguage } from './strings'
import { History } from './history'
import { PanelBox, Prose, Waiting } from './ui'

export function PlayPage({
  runId, onBack, onScenes, onReplay, refresh,
}: {
  runId: string
  onBack: () => void
  onScenes: (scenes: SceneRow[]) => void
  onReplay: (worldId: string) => void
  refresh: number
}) {
  const [v, setV] = useState<PlayView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [action, setAction] = useState('')
  const [tapped, setTapped] = useState('')
  const [arm, setArm] = useState('')
  // Picked once per commit. Re-rolling during render would cycle the phrase every
  // poll while the month is being written.
  const [phrase, setPhrase] = useState('')
  const [stalled, setStalled] = useState(false)
  // The last action that did not land, kept so a stall can be retried with the
  // exact same intent instead of making the player retype it.
  const [retry, setRetry] = useState<{ payload: { turn?: number; action?: string }; what: string } | null>(null)
  const [drawer, setDrawer] = useState(false)
  const [back, setBack] = useState(false)

  const load = useCallback(async () => {
    try {
      setV(await api.run(runId))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [runId])

  useEffect(() => { void load() }, [load, refresh])

  /**
   * A month being written is a fact on the server, not a fact about this page.
   *
   * The bug this closes: waiting was `busy`, a React boolean, so leaving the page
   * while the world was being made and coming back showed a life that looked like
   * nobody had ever asked for it — the request's poll loop had died with the page.
   * The backend now records the asking before it speaks to the narrator, so the
   * server can be believed over local memory, and coming back converges on its own
   * instead of needing the player to guess whether to tap again.
   */
  const generating = !!v?.generating
  useEffect(() => {
    if (!generating) return
    setPhrase((p) => p || pick('play.waiting'))
    const timer = window.setInterval(() => { void load() }, GENERATING_POLL_MS)
    return () => window.clearInterval(timer)
  }, [generating, load])

  // Either reason the player cannot act: their own tap, or a narrator already at
  // work — including one asked for by a page they have since closed.
  const busy = !!tapped || generating

  // The world's own language, not the build's. Setting it at the root re-renders
  // this page already speaking it (the setter is stable; the re-render is driven by
  // the root's state).
  const setLanguage = useSetLanguage()
  useEffect(() => { setLanguage(v?.language) }, [v, setLanguage])

  // Every mounted scene is reported upward, in the order it was mounted. The app
  // root draws one persistent frame per scene: an asking scene the player answers,
  // and display-only scenes (a map, a ledger) that stay visible — including after
  // they are answered — until the narrator dismisses them. The order is never
  // re-sorted: moving a frame in the DOM reloads it.
  useEffect(() => {
    onScenes(v?.scenes ?? [])
  }, [v, onScenes])

  const take = async (payload: { turn?: number; action?: string }, what: string) => {
    setTapped(what)
    setPhrase(pick('play.waiting'))
    setStalled(false)
    try {
      const out = await api.takeTurn(runId, payload)
      // A month that actually happened — or was already written, or ended the life
      // — is the only outcome that clears what the player typed. A narrator that
      // did not answer keeps their words and offers to resend the same action.
      const settled = out.advanced || out.reason === 'already' || out.reason === 'ended'
      if (settled) {
        setAction('')
        setRetry(null)
      } else {
        setStalled(true)
        setRetry({ payload, what })
      }
      await load()
    } catch {
      setStalled(true)
      setRetry({ payload, what })
    }
    setTapped('')
  }

  if (error) {
    return (
      <div>
        <button className="ew-back" type="button" onClick={onBack}>{t('play.back')}</button>
        <div className="ew-meta">{t('world.unreadableDetail', { error })}</div>
        <div className="ew-bar">
          <button className="ew-btn" type="button" onClick={() => { setError(null); void load() }}>
            {t('play.retry')}
          </button>
        </div>
      </div>
    )
  }
  if (!v) return <div className="ew-meta">{t('play.opening')}</div>

  // A life that exists but has not been born yet — reached from the shelf after an
  // opening turn was interrupted. Everything the player chose is already saved, so
  // the offer is to continue, never to fill the form in again.
  if (v.awaitingOpening) {
    return (
      <div>
        <button className="ew-back" type="button" onClick={onBack}>{t('play.back')}</button>
        <h3 className="ew-detail-title">{v.title}</h3>
        <div className="ew-note">
          {busy ? t('opening.arranging') : t('opening.notStarted')}
        </div>
        {generating ? <div className="ew-note">{t('play.generating')}</div> : null}
        {stalled && !busy ? <div className="ew-note">{t('opening.silent')}</div> : null}
        <div className="ew-bar">
          <button
            className="ew-btn ew-btn-go"
            type="button"
            disabled={busy}
            onClick={async () => {
              setTapped(OPEN)
              setPhrase(pick('opening.waiting'))
              setStalled(false)
              try {
                const out = await api.openRun(runId)
                if (!out.advanced && out.reason !== 'already') setStalled(true)
                await load()
              } catch {
                setStalled(true)
              }
              setTapped('')
            }}
          >
            {t('opening.continueBirth')}
            {tapped === OPEN ? <Waiting label={phrase} /> : null}
          </button>
        </div>
      </div>
    )
  }

  const panels = <>{(v.panels ?? []).map((p) => <PanelBox key={p.id} panel={p} />)}</>

  // A life that has reached its ending. The action controls are gone — a closed
  // life takes no more turns — and the last narration stands as its epilogue, with
  // the way onward being another life in the same world or the shelf.
  if (v.ended) {
    return (
      <div>
        <button className="ew-back" type="button" onClick={onBack}>{t('play.back')}</button>
        <div className="ew-clock">{v.clock || t('play.turn', { turn: v.turn })}</div>
        <h3 className="ew-detail-title">{v.title}</h3>
        <div className="ew-note ew-note-live">{t('play.endedBadge')}</div>
        <Prose text={v.prose} />
        <div className="ew-meta">{t('play.endedMeta', { turn: v.turn })}</div>
        <div className="ew-bar">
          <button
            className="ew-btn ew-btn-go"
            type="button"
            onClick={() => onReplay(v.worldId)}
          >
            {t('play.endedReplay')}
          </button>
          <button className="ew-btn" type="button" onClick={onBack}>
            {t('play.endedShelf')}
          </button>
        </div>
        <button
          className="ew-drawer"
          type="button"
          aria-expanded={back}
          aria-controls="ew-history-panel-ended"
          onClick={() => setBack((b) => !b)}
        >
          {back ? t('history.close') : t('history.open')}
        </button>
        {back ? <div id="ew-history-panel-ended"><History runId={runId} /></div> : null}
      </div>
    )
  }

  const main = (
    <div>
      {(v.digest ?? []).length ? (
        <div className="ew-digest">
          {(v.digest ?? []).map((dg, i) => (
            <div
              className={`ew-drow${dg.rumour ? ' ew-drow-rumour' : ''}`}
              key={`${dg.category}-${i}`}
            >
              <div className="ew-dcat">
                {dg.category === 'rumour' ? t('play.rumour') : dg.category}
              </div>
              <div>
                {dg.text}
                {/* Marked in the player's language, not with a tooltip: an unreliable
                    report that reads exactly like a reliable one makes the reach
                    gating invisible, which is the same as not having it. */}
                {dg.rumour && dg.category !== 'rumour'
                  ? <span className="ew-sub">{t('play.rumourSuffix')}</span>
                  : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <Prose text={v.prose} />

      {stalled ? (
        <div className="ew-note" role="status" aria-live="polite">
          {t('play.stalled')}
          {retry ? (
            <button
              className="ew-btn ew-btn-sm"
              type="button"
              disabled={busy}
              style={{ marginInlineStart: '8px' }}
              onClick={() => void take(retry.payload, retry.what)}
            >
              {t('play.retry')}
            </button>
          ) : null}
        </div>
      ) : null}

      {(v.choices ?? []).length ? (
        <div className="ew-choices">
          {(v.choices ?? []).map((c) => {
            const target = choiceTarget(c.id)
            const armed = arm === target
            const sending = tapped === target
            return (
              <div className="ew-choicewrap" key={c.id}>
                <button
                  className={
                    'ew-choice'
                    + (armed ? ' ew-choice-armed' : '')
                    + (sending ? ' ew-choice-waiting' : '')
                  }
                  type="button"
                  // A choice stays tappable while another is armed: changing your
                  // mind must not require a cancel first.
                  disabled={busy}
                  aria-pressed={armed}
                  aria-busy={sending}
                  onClick={() => setArm(armed ? '' : target)}
                >
                  <span className="ew-choice-label">{c.label}</span>
                  {sending ? <Waiting label={phrase} /> : null}
                </button>

                {/* The second step. A turn is a month of a life and cannot be
                    undone, so the tap that commits it is its own deliberate act —
                    the first tap only says "this one". */}
                {armed && !busy ? (
                  <div className="ew-confirm">
                    <span className="ew-confirm-ask">{t('play.confirmAsk')}</span>
                    <button
                      className="ew-btn ew-btn-go ew-btn-sm"
                      type="button"
                      onClick={() => {
                        setArm('')
                        void take({ turn: v.turn + 1, action: c.label }, target)
                      }}
                    >
                      {t('play.confirmYes')}
                    </button>
                    <button
                      className="ew-btn ew-btn-sm"
                      type="button"
                      onClick={() => setArm('')}
                    >
                      {t('play.confirmNo')}
                    </button>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : null}

      <div>
        <div className="ew-act">
          <textarea
            value={action}
            maxLength={500}
            rows={2}
            placeholder={t('play.actionPlaceholder')}
            disabled={busy}
            onChange={(e) => { setAction(e.target.value); setArm('') }}
            onKeyDown={(e) => {
              // Cmd/Ctrl+Enter is itself the deliberate act, so it commits directly
              // rather than only arming the two-step confirm.
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && action.trim() && !busy) {
                e.preventDefault()
                setArm('')
                void take({ turn: v.turn + 1, action: action.trim() }, ACT)
              }
            }}
          />
          <button
            className="ew-btn ew-btn-go"
            type="button"
            style={{ flex: '0 0 auto', minWidth: 0, padding: '0 16px' }}
            disabled={busy || !action.trim()}
            onClick={() => setArm(arm === ACT ? '' : ACT)}
            aria-pressed={arm === ACT}
          >
            {t('play.act')}
          </button>
        </div>

        {/* Typed text gets the same second step as a tapped choice. It is the same
            irreversible month, and the reason to confirm has nothing to do with how
            the intent was expressed. */}
        {arm === ACT && !busy ? (
          <div className="ew-confirm ew-confirm-act">
            <span className="ew-confirm-ask">{t('play.confirmAct')}</span>
            <button
              className="ew-btn ew-btn-go ew-btn-sm"
              type="button"
              onClick={() => {
                setArm('')
                void take({ turn: v.turn + 1, action: action.trim() }, ACT)
              }}
            >
              {t('play.confirmYes')}
            </button>
            <button
              className="ew-btn ew-btn-sm"
              type="button"
              onClick={() => setArm('')}
            >
              {t('play.confirmNo')}
            </button>
          </div>
        ) : null}

        {tapped === ACT ? (
          <div className="ew-confirm ew-confirm-act">
            <Waiting label={phrase} />
          </div>
        ) : null}

        {/* Coming back to a page whose narrator is still working: nothing local
            remembers which option was taken, so the reassurance is turn-level. */}
        {generating && !tapped ? (
          <div className="ew-note ew-note-live">
            <Waiting label={phrase || t('play.generating')} />
          </div>
        ) : null}

        {action.length > 400 ? (
          <div className="ew-count">{`${action.length} / 500`}</div>
        ) : null}
      </div>

      <button
        className="ew-drawer"
        type="button"
        aria-expanded={back}
        aria-controls="ew-history-panel"
        onClick={() => setBack((b) => !b)}
      >
        {back ? t('history.close') : t('history.open')}
      </button>
      {back ? <div id="ew-history-panel"><History runId={runId} /></div> : null}

      <button
        className="ew-drawer"
        type="button"
        aria-expanded={drawer}
        aria-controls="ew-panels-drawer"
        onClick={() => setDrawer((d) => !d)}
      >
        {drawer ? t('play.drawerClose') : t('play.drawerOpen')}
      </button>
      {drawer ? (
        <div id="ew-panels-drawer" style={{ marginTop: '10px' }}>
          {(v.panels ?? []).length ? panels : (
            <div className="ew-note">{t('play.nothingToShow')}</div>
          )}
        </div>
      ) : null}
    </div>
  )

  return (
    <div>
      <button className="ew-back" type="button" onClick={onBack}>{t('play.back')}</button>
      <div className="ew-clock">{v.clock || t('play.turn', { turn: v.turn })}</div>
      <h3 className="ew-detail-title">{v.title}</h3>
      <div className="ew-play">
        {main}
        <div className="ew-aside">{panels}</div>
      </div>
    </div>
  )
}
