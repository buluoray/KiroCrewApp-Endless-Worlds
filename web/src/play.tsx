import { useCallback, useEffect, useRef, useState } from 'react'

import type { EchoMarker, PastTurn, PlayView, SceneRow } from './api'
import { api, API } from './api'

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
import { History, LifeSummary } from './history'
import { LegacyPicker } from './legacy'
import { StarMap } from './memory'
import { mt } from './memory-state'
import { PanelBox, Prose, Waiting } from './ui'
import { buildTabs, tabIcon } from './tabbar'

function Chevron({ dir }: { dir: 'l' | 'r' }) {
  const d = dir === 'l' ? 'M11 4 L6 9 L11 14' : 'M7 4 L12 9 L7 14'
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/**
 * Live feedback while a month is written. The bar advances a notch per narrator
 * tool call (`generating.steps`, ~16% each, capped at 92% until commit); the
 * label reuses the app's existing, already-tuned waiting copy rather than a
 * generic stage name, so the wording stays consistent with the rest of the wait.
 */
function TurnProgress({ g, label }: { g?: PlayView['generating']; label: string }) {
  const steps = g?.steps ?? 0
  const pct = Math.min(12 + steps * 16, 92)
  return (
    <div className="ew-progress" role="status" aria-live="polite">
      <div className="ew-progress-track">
        <div className="ew-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="ew-progress-steps">
        <span className="ew-progress-label">{label}</span>
      </div>
    </div>
  )
}

/**
 * One "an old thing came back" marker (design §8.1). Deliberately quiet: a single
 * folded line after the prose, expanding to the source moment, the player's own
 * choice back then, how this turn answers it, and a jump to the source page. No
 * celebration, no sound, no modal — the prose stays the protagonist.
 */
function EchoMark({
  e, lang, runId, onJump,
}: {
  e: EchoMarker
  lang: string
  runId: string
  onJump: (turn: number) => void
}) {
  const [open, setOpen] = useState(false)
  const [kept, setKept] = useState(false)
  const keep = async () => {
    // One tap keeps the WHOLE declared path (§8.2): the answering event and
    // the source it echoes, cited by their canonical ids.
    await api.createKeepsake(runId, {
      kind: 'echo',
      title: e.title || e.sourceTitle,
      cites: [e.sourceId, e.currentId].filter(Boolean),
    })
    setKept(true)
  }
  return (
    <div className="ew-echo">
      <button
        className="ew-echo-line"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {t('play.echoLine', { turn: e.sourceTurn })}
      </button>
      {open ? (
        <div className="ew-echo-body">
          <div className="ew-echo-row">
            <span className="ew-echo-label">{t('play.echoThen')}</span>
            <span>
              <strong>{e.sourceTitle}</strong>
              {e.sourceSummary ? ` — ${e.sourceSummary}` : ''}
            </span>
          </div>
          {e.sourceAction ? (
            <div className="ew-echo-row">
              <span className="ew-echo-label">{t('play.echoYouDid')}</span>
              <span>{e.sourceAction}</span>
            </div>
          ) : null}
          <div className="ew-echo-row">
            <span className="ew-echo-label">{t('play.echoNow')}</span>
            <span>
              <strong>{e.title}</strong>
              {e.summary ? ` — ${e.summary}` : ''}
            </span>
          </div>
          <div className="ew-echo-actions">
            <button
              className="ew-btn ew-btn-sm"
              type="button"
              onClick={() => onJump(e.sourceTurn)}
            >
              {t('play.echoJump')}
            </button>
            <button
              className="ew-btn ew-btn-sm"
              type="button"
              disabled={kept}
              onClick={() => void keep().catch(() => {})}
            >
              {mt(lang, kept ? 'star.keep.kept' : 'star.keep.this')}
            </button>
            <button
              className="ew-btn ew-btn-sm"
              type="button"
              onClick={() => setOpen(false)}
            >
              {t('play.echoClose')}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function PlayPage({
  runId, onBack, onScenes, onBackdrop, onReplay, onReplaySame, onEnterLife, refresh,
  openStar, onStarClose, onLiveTurn, narrow, onPanels, turnPending = false,
}: {
  runId: string
  onBack: () => void
  onScenes: (scenes: SceneRow[]) => void
  /** The world image behind the whole app, reported upward because it is rendered
   *  at the ROOT rather than in this column — on a desktop it spans the page, not
   *  just the story. */
  onBackdrop: (backdrop: { version: number; turn?: number } | null) => void
  onReplay: (worldId: string) => void
  onReplaySame: (fromRunId: string) => void
  /** Enter another life by id — how a legacy heir is stepped into (§9). */
  onEnterLife: (runId: string) => void
  refresh: number
  /** The 星图 tab (narrow viewport) drives the star map overlay from outside; when
   *  undefined the play page's own control owns it (desktop). */
  openStar?: boolean
  onStarClose?: () => void
  /** Report the live turn upward so the bottom bar can dot 书页 on a new month
   *  while the player is reading a system tab. */
  onLiveTurn?: (turn: number) => void
  /** Narrow viewport: the phone bottom bar owns the system panels (grouped into
   *  region tabs), so the in-column drawer and star button are suppressed here. */
  narrow?: boolean
  /** Report the world's panels upward so the bottom bar can build region tabs from
   *  the ones that carry a region. */
  onPanels?: (panels: PlayView['panels']) => void
  /** True while a SCENE answer's turn is in flight (dispatched from main, not
   *  from this page) — folded into `busy` so the choice buttons and act box
   *  cannot start a second concurrent turn in the window before the next poll
   *  reports `generating`. */
  turnPending?: boolean
}) {
  const [v, setV] = useState<PlayView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [action, setAction] = useState('')
  const [tapped, setTapped] = useState('')
  const [arm, setArm] = useState('')
  // Picked once per commit. Re-rolling during render would cycle the phrase every
  // poll while the month is being written.
  const [phrase, setPhrase] = useState('')
  // A rotating "the world is being made" line, cycled while a life is being born so
  // the arranging screen reads as generation rather than a frozen spinner.
  const [arrange, setArrange] = useState('')
  const [stalled, setStalled] = useState(false)
  // The last action that did not land, kept so a stall can be retried with the
  // exact same intent instead of making the player retype it.
  const [retry, setRetry] = useState<{ payload: { turn?: number; action?: string }; what: string } | null>(null)
  const [drawer, setDrawer] = useState(false)
  // The life star map overlay (§8.3): opened from the secondary action area,
  // never from the per-turn controls — it reads the life, it does not play it.
  const [starOpen, setStarOpen] = useState(false)
  // Desktop right-aside: which system region's panels are shown (a region id).
  const [asideTab, setAsideTab] = useState('')
  /** Per-region content signature last seen on the aside, so a region tab dots on
   *  an unseen change — the same notification affordance the phone bottom bar has. */
  const asideSeenRef = useRef<Record<string, string>>({})
  // The legacy bridge picker (§9): offered on the ending page of a lineage world.
  const [legacyOpen, setLegacyOpen] = useState(false)
  const [back, setBack] = useState(false)
  // A recap belongs to entering a life, not to every poll or newly written turn.
  // The ref distinguishes the first load of this run from subsequent refreshes.
  const loadedRun = useRef<string | null>(null)
  const [recapOpen, setRecapOpen] = useState(false)
  // The turn pager at the top of the story: which past turn is being read (null =
  // the live, latest turn), and this life's turns so an arrow can page to one.
  const [viewTurn, setViewTurn] = useState<number | null>(null)
  const [chron, setChron] = useState<PastTurn[]>([])
  useEffect(() => {
    if (!v || v.turn < 1) return undefined
    let alive = true
    // A newly written turn snaps the pager back to live, and refetches so the new
    // month is pageable.
    setViewTurn(null)
    api.chronicle(runId).then((c) => { if (alive) setChron(c.turns) }).catch(() => {})
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, v?.turn])
  // Advancing to a new turn, or paging to another one, returns to the top. Scroll
  // the app root (which starts at the "Endless Worlds" header) into view, NOT the
  // play column below it — aligning the column to the top scrolled the header out
  // of sight, which read as the page rebounding to cover the title.
  const prevTurnRef = useRef(0)
  useEffect(() => {
    document.querySelector('.ew-root')?.scrollIntoView({ block: 'start' })
    prevTurnRef.current = viewTurn ?? (v?.turn ?? 0)
  }, [viewTurn, v?.turn])

  const load = useCallback(async () => {
    try {
      const next = await api.run(runId)
      setV(next)
      // A later successful poll must clear an earlier transient failure — otherwise
      // one dropped request during generation leaves the error page up for good,
      // since the render checks `error` first. (M0.5)
      setError(null)
      if (loadedRun.current !== runId) {
        loadedRun.current = runId
        const recap = next.recap
        // choices are no longer shown here (they duplicate the bottom choice list),
        // so they no longer justify opening the recap on their own.
        setRecapOpen(next.turn > 1 && !!(recap.lastAction || recap.events.length))
      }
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
  // Also poll while a freshly-created life awaits its opening: begin() fires the
  // opening turn in the background, so its "generating" mark can land a beat after
  // this page first loads. Polling catches it and flips to the arranging screen
  // rather than stranding the player on the birth button.
  const awaiting = !!v?.awaitingOpening
  useEffect(() => {
    if (!generating && !awaiting) return undefined
    if (generating) setPhrase((p) => p || pick('play.waiting'))
    const timer = window.setInterval(() => { void load() }, GENERATING_POLL_MS)
    return () => window.clearInterval(timer)
  }, [generating, awaiting, load])

  // Either reason the player cannot act: their own tap, or a narrator already at
  // work — including one asked for by a page they have since closed.
  const busy = !!tapped || generating || turnPending

  // Cycle the arranging flavour while a life is being born.
  useEffect(() => {
    if (!(v?.awaitingOpening && generating)) return undefined
    setArrange(pick('opening.waiting'))
    const timer = window.setInterval(() => setArrange(pick('opening.waiting')), 4000)
    return () => window.clearInterval(timer)
  }, [v?.awaitingOpening, generating])

  // Cycle the mid-life waiting flavour the same way while a month is written (the
  // opening screen has its own rotation just above). Rotating rather than picking
  // once keeps the wait alive and shows off the several tuned play.waiting lines.
  useEffect(() => {
    if (!(generating && !awaiting)) return undefined
    setPhrase(pick('play.waiting'))
    const timer = window.setInterval(() => setPhrase(pick('play.waiting')), 4000)
    return () => window.clearInterval(timer)
  }, [generating, awaiting])

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

  // Drive the star map from the 星图 tab on a phone; the desktop control still owns
  // it when no external tab is wired (openStar undefined).
  useEffect(() => {
    if (openStar !== undefined) setStarOpen(openStar)
  }, [openStar])

  // Let the bottom bar mark 书页 when a new month lands while reading elsewhere.
  useEffect(() => {
    if (v && v.turn) onLiveTurn?.(v.turn)
  }, [v?.turn, onLiveTurn])

  // Report panels upward so the phone bar can build region tabs from them.
  useEffect(() => {
    onPanels?.(v?.panels ?? [])
  }, [v?.panels, onPanels])

  // Same reason as the scenes above: the backdrop is mounted by the root, so this
  // page reports which version the view is asking for rather than rendering it. It
  // follows the SHOWN page: the live turn's backdrop on the newest page, or the
  // backdrop that was effective on a past page (by `turn`) when the pager steps
  // back — so re-reading an old page restores its scene, not the latest one.
  useEffect(() => {
    if (!v) { onBackdrop(null); return }
    const latest = v.turn
    const shown = viewTurn ?? latest
    if (shown >= latest) {
      onBackdrop(v.backdrop ?? null)
    } else {
      const past = chron.find((c) => c.turn === shown)?.backdrop
      onBackdrop(past ? { version: past.version, turn: shown } : (v.backdrop ?? null))
    }
  }, [v, viewTurn, chron, onBackdrop])

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

  // Response-boundary fallbacks keep a rolling frontend/backend reload from
  // blanking the whole app while one side is still on the previous shape.
  const recap = v.recap ?? { lastAction: '', events: [], choices: [] }
  const reveals = v.reveals ?? []

  // A life that exists but has not been born yet — reached from the shelf after an
  // opening turn was interrupted. Everything the player chose is already saved, so
  // the offer is to continue, never to fill the form in again.
  if (v.awaitingOpening) {
    return (
      <div>
        <button className="ew-back" type="button" onClick={onBack}>{t('play.back')}</button>
        <h3 className="ew-detail-title">{v.title}</h3>
        {generating ? (
          // The world is being made. This state lives on the server, so leaving and
          // returning lands right back here rather than on a blank form.
          <div className="ew-arrange">
            <div className="ew-arrange-title">{t('opening.arranging')}</div>
            <TurnProgress g={v.generating} label={arrange || t('opening.arranging')} />
          </div>
        ) : (
          <>
            <div className="ew-note">
              {busy ? t('opening.arranging') : t('opening.notStarted')}
            </div>
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
          </>
        )}
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
        {legacyOpen ? (
          <LegacyPicker
            runId={runId}
            lang={v.language}
            onClose={() => setLegacyOpen(false)}
            onContinue={async (selected) => {
              // Same create→open→enter shape as "live this again", plus the
              // bridge. The heir starts a fresh opening — a new life, carrying
              // chosen things, never a save-file copy (§9).
              const created = await api.createRun({
                worldId: v.worldId,
                language: v.language,
                legacy: { fromRunId: runId, selected },
              })
              void api.openRun(created.runId)
              onEnterLife(created.runId)
            }}
          />
        ) : null}
        <button className="ew-back" type="button" onClick={onBack}>{t('play.back')}</button>
        <div className="ew-clock">{v.clock || t('play.turn', { turn: v.turn })}</div>
        <h3 className="ew-detail-title">{v.title}</h3>
        <div className="ew-note ew-note-live">{t('play.endedBadge')}</div>
        <Prose text={v.prose} />
        <div className="ew-meta">{t('play.endedMeta', { turn: v.turn })}</div>
        <LifeSummary runId={runId} />
        <div className="ew-bar">
          {v.lineage ? (
            <button
              className="ew-btn ew-btn-go"
              type="button"
              onClick={() => setLegacyOpen(true)}
            >
              {mt(v.language, 'legacy.entry')}
            </button>
          ) : null}
          <button
            className={'ew-btn' + (v.lineage ? '' : ' ew-btn-go')}
            type="button"
            onClick={() => onReplaySame(runId)}
          >
            {t('play.endedReplaySame')}
          </button>
          <button
            className="ew-btn"
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

  // The pager reads the latest turn by default; an arrow steps to a past turn,
  // whose prose comes from the chronicle. Off the latest turn the story is being
  // re-read, so the action controls step aside.
  const latest = v.turn
  const shownTurn = viewTurn ?? latest
  const isLive = shownTurn >= latest
  const shownProse = isLive
    ? v.prose
    : (chron.find((c) => c.turn === shownTurn)?.prose ?? v.prose)
  const pastAction = isLive ? '' : (chron.find((c) => c.turn === shownTurn)?.action ?? '')
  // Forward when the turn number grew (a new page or a step right), back otherwise.
  const pageDir = shownTurn >= prevTurnRef.current ? 'fwd' : 'back'
  const pager = latest >= 1 ? (
    <div className="ew-pager">
      <button
        className="ew-pager-arw"
        type="button"
        disabled={shownTurn <= 1}
        aria-label={t('play.prevTurn')}
        onClick={() => setViewTurn(Math.max(1, shownTurn - 1))}
      >
        <Chevron dir="l" />
      </button>
      <span className="ew-pager-turn">{t('play.page', { n: shownTurn })}</span>
      <button
        className="ew-pager-arw"
        type="button"
        disabled={shownTurn >= latest}
        aria-label={t('play.nextTurn')}
        onClick={() => setViewTurn(shownTurn + 1 >= latest ? null : shownTurn + 1)}
      >
        <Chevron dir="r" />
      </button>
    </div>
  ) : null

  const main = (
    <div>
      {isLive && recapOpen ? (
        <section className="ew-story-moment" aria-label={t('play.recapTitle')}>
          <div className="ew-story-moment-head">
            <div className="ew-story-moment-title">{t('play.recapTitle')}</div>
            <button
              className="ew-story-moment-close"
              type="button"
              onClick={() => setRecapOpen(false)}
            >
              {t('play.recapDismiss')}
            </button>
          </div>
          {recap.lastAction ? (
            <div className="ew-recap-line">
              <span className="ew-recap-label">{t('play.recapLastChoice')} </span>
              {recap.lastAction}
            </div>
          ) : null}
          {recap.events.length ? (
            <>
              <div className="ew-recap-label">{t('play.recapRecent')}</div>
              <ul className="ew-recap-list">
                {recap.events.map((event) => <li key={event}>{event}</li>)}
              </ul>
            </>
          ) : null}
        </section>
      ) : null}

      {isLive && v.turn === 1 && reveals.length ? (
        <section className="ew-story-moment" aria-label={t('play.birthRevealTitle')}>
          <div className="ew-story-moment-title">{t('play.birthRevealTitle')}</div>
          {reveals.map((reveal) => (
            <div className="ew-reveal-row" key={reveal.label}>
              <span className="ew-reveal-label">{reveal.label}</span>
              <span className="ew-reveal-value">{reveal.value}</span>
            </div>
          ))}
          <div className="ew-story-moment-hint">{t('play.birthRevealHint')}</div>
        </section>
      ) : null}

      {(v.unlocked ?? []).length ? (
        <div className="ew-unlocked" role="status" aria-live="polite">
          {(v.unlocked ?? []).map((h, i) => (
            <div className="ew-unlocked-row" key={`${h}-${i}`}>
              <div className="ew-unlocked-heading">{t('play.unlocked', { heading: h })}</div>
              <div className="ew-unlocked-meaning">
                {t('play.unlockedMeaning', { heading: h })}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {(v.milestonesReached ?? []).length ? (
        <div className="ew-milestone" role="status" aria-live="polite">
          {(v.milestonesReached ?? []).map((m, i) => (
            <div className="ew-milestone-row" key={`${m}-${i}`}>
              {t('play.milestone', { label: m })}
            </div>
          ))}
        </div>
      ) : null}

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

      {!isLive && pastAction ? (
        <div className="ew-hint">{t('history.chose', { action: pastAction })}</div>
      ) : null}

      <div className={`ew-turnpage ew-turnpage-${pageDir}`} key={shownTurn}>
        <Prose text={shownProse} />
      </div>

      {/* After the prose, never before it (design §8.1): the story is the
          protagonist and an echo is a footnote to it. Live turn only — a past
          page re-read through the pager already IS the past. */}
      {isLive && (v.echoes ?? []).length ? (
        <div className="ew-echoes">
          {(v.echoes ?? []).map((e, i) => (
            <EchoMark
              key={`${e.sourceId}-${i}`}
              e={e}
              lang={v.language}
              runId={runId}
              onJump={(turn) => setViewTurn(turn >= latest ? null : turn)}
            />
          ))}
        </div>
      ) : null}

      {/* Still being written: the pending record is fresh, so the narrator is
          working — show the normal waiting indicator, never the retry. `takeTurn`
          returns advanced:false the moment its wait deadline passes, but that is the
          app's deadline, NOT proof the narrator stopped. */}
      {generating ? (
        <div className="ew-note ew-note-live" role="status" aria-live="polite">
          <TurnProgress g={v.generating} label={phrase || t('play.generating')} />
        </div>
      ) : null}

      {/* The retry is shown ONLY when the narrator has truly stopped — no fresh
          pending record (`generating` is null). While it is still writing, the block
          above shows instead, so a slow month never reads as a failed one. */}
      {stalled && !generating ? (
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

      {isLive && (v.choices ?? []).length ? (
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
                    + (c.fateful || c.art ? ' ew-choice-fateful' : '')
                    + (c.art ? ' ew-choice-arted' : '')
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
                  {/* The narrator's own pattern behind the label, as an INERT
                      image (an SVG in an <img> runs no script and fetches nothing,
                      so it needs no sandbox). A fateful choice uses its OWN `art`;
                      an ordinary one falls back to the scene's shared `buttons`
                      motif, versioned with the backdrop so it swaps when the
                      backdrop does. Validated server-side. */}
                  {c.art ? (
                    <img
                      className="ew-choice-art"
                      src={`data:image/svg+xml;utf8,${encodeURIComponent(c.art)}`}
                      alt=""
                      aria-hidden="true"
                      draggable={false}
                      onError={(e) => { e.currentTarget.style.display = 'none' }}
                    />
                  ) : v.backdrop?.buttons ? (
                    <img
                      className="ew-choice-art ew-choice-art-common"
                      src={`${API}/runs/${encodeURIComponent(runId)}/backdrop?part=buttons&v=${v.backdrop.version}`}
                      alt=""
                      aria-hidden="true"
                      draggable={false}
                      onError={(e) => { e.currentTarget.style.display = 'none' }}
                    />
                  ) : null}
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

      {isLive ? (
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

        {action.length > 400 ? (
          <div className="ew-count">{`${action.length} / 500`}</div>
        ) : null}
      </div>
      ) : null}

      {/* The history drawer is hidden for now: the turn pager at the top of the
          story covers re-reading this life. Kept in the ended view, which has no
          pager. */}

      {!narrow ? (
        <button
          className="ew-drawer"
          type="button"
          aria-expanded={drawer}
          aria-controls="ew-panels-drawer"
          onClick={() => setDrawer((d) => !d)}
        >
          {drawer ? t('play.drawerClose') : t('play.drawerOpen')}
        </button>
      ) : null}
      {drawer && !narrow ? (
        <div id="ew-panels-drawer" style={{ marginTop: '10px' }}>
          {(v.panels ?? []).length ? panels : (
            <div className="ew-note">{t('play.nothingToShow')}</div>
          )}
        </div>
      ) : null}
    </div>
  )

  // Desktop right-aside tabs: the world's system regions (panels grouped by
  // region), plus an untagged bucket, plus a 星图 entry. On a phone the bottom bar
  // owns all of this instead (this aside is not rendered when `narrow`).
  const asideRegionTabs = buildTabs(v.scenes ?? [], v.panels ?? []).filter(
    (tb) => tb.kind === 'region',
  )
  const asideUntagged = (v.panels ?? []).filter((p) => !(p.region ?? '').trim())
  const asideStripTabs = [
    ...asideRegionTabs,
    ...(asideUntagged.length
      ? [{ id: '__untagged', kind: 'region' as const, label: t('tab.system'), sceneIds: [] }]
      : []),
  ]
  const activeAside = asideStripTabs.some((tb) => tb.id === asideTab)
    ? asideTab
    : (asideStripTabs[0]?.id ?? '')
  const asidePanels = activeAside === '__untagged'
    ? asideUntagged
    : (v.panels ?? []).filter((p) => (p.region ?? '').trim() === activeAside)

  // Dot a region tab whose panels changed while the reader was on another tab.
  const asideSig = (regionId: string): string => {
    const group = regionId === '__untagged'
      ? asideUntagged
      : (v.panels ?? []).filter((p) => (p.region ?? '').trim() === regionId)
    return JSON.stringify(group.map((p) => [p.id, JSON.stringify(p.fields)]))
  }
  const asideDots: Record<string, boolean> = {}
  for (const tb of asideStripTabs) {
    const sig = asideSig(tb.id)
    if (tb.id === activeAside) {
      asideSeenRef.current[tb.id] = sig  // the open tab is always current
      asideDots[tb.id] = false
      continue
    }
    if (asideSeenRef.current[tb.id] === undefined) asideSeenRef.current[tb.id] = sig
    asideDots[tb.id] = asideSeenRef.current[tb.id] !== sig
  }

  return (
    <div className="ew-play-root">
      {starOpen ? (
        <StarMap
          runId={runId}
          lang={v.language}
          backdrop={v.backdrop ?? null}
          onClose={() => { setStarOpen(false); onStarClose?.() }}
          onJumpTurn={(turn) => {
            setStarOpen(false)
            setViewTurn(turn >= latest ? null : turn)
          }}
        />
      ) : null}
      <div className="ew-topbar">
        <button className="ew-back" type="button" onClick={onBack}>{t('play.back')}</button>
        {pager}
      </div>
      <div className="ew-titleline">
        <h3 className="ew-detail-title">{v.title}</h3>
        {v.clock ? <span className="ew-clock">{v.clock}</span> : null}
      </div>
      <div className="ew-play">
        {main}
        {!narrow ? (
          <div className="ew-aside">
            <div className="ew-aside-tabs">
              {asideStripTabs.map((tb) => (
                <button
                  key={tb.id}
                  type="button"
                  className={'ew-aside-tab' + (tb.id === activeAside ? ' on' : '')}
                  aria-pressed={tb.id === activeAside}
                  onClick={() => setAsideTab(tb.id)}
                >
                  {tabIcon(tb.id === '__untagged' ? 'system' : tb.id)}
                  <span>{tb.label}</span>
                  {asideDots[tb.id] ? <i className="ew-aside-dot" /> : null}
                </button>
              ))}
              <button
                type="button"
                className="ew-aside-tab"
                onClick={() => setStarOpen(true)}
              >
                {tabIcon('starmap')}
                <span>{mt(v.language, 'star.title')}</span>
              </button>
            </div>
            {asidePanels.length ? (
              <>{asidePanels.map((p) => <PanelBox key={p.id} panel={p} />)}</>
            ) : (
              <div className="ew-note">{t('play.nothingToShow')}</div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}
