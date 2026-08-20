/** Creating a world from pasted text.
 *
 * The player pastes any text; a background "worldsmith" agent cleans out whatever
 * this framework cannot play and compiles the rest into a world. The job mirrors
 * life-creation: it runs on the server, so the player can leave and come back to a
 * draft still being worked, then review and install it. This file holds the four
 * surfaces — the shelf entry, the in-progress/ready card, the paste screen, and the
 * review — while main.tsx owns the view switching and the shelf poll.
 */

import { useEffect, useRef, useState } from 'react'

import type { WorldDraftDetail, WorldDraftRow } from './api'
import { api } from './api'
import { t } from './strings'
import { Chip } from './ui'

/** Where the half-typed paste is kept, so closing the screen does not lose it.
 *  Prefixed because this app shares the dashboard's localStorage. */
const CREATE_DRAFT_KEY = 'endless-worlds:create-draft'

/** How often a generating draft is re-checked while the player watches. Matches
 *  the play page's GENERATING_POLL_MS. */
export const DRAFT_POLL_MS = 3000


/** The always-present entry at the top of the worlds shelf. */
export function CreateWorldCard({ onClick }: { onClick: () => void }) {
  return (
    <button className="ew-card ew-card-create" type="button" onClick={onClick}>
      <span className="ew-create-plus" aria-hidden="true">+</span>
      <span className="ew-create-text">
        <span className="ew-create-title">{t('create.title')}</span>
        <span className="ew-create-sub">{t('create.subtitle')}</span>
      </span>
    </button>
  )
}


function draftWhere(d: WorldDraftRow): string {
  if (d.status === 'ready') return t('worldDraft.ready')
  if (d.status === 'failed') return d.problem || t('worldDraft.failed')
  // generating: name the coarse stage, and count steps so it visibly advances.
  const stage = d.stage === 'writing' ? t('worldDraft.writing') : t('worldDraft.reading')
  return d.steps > 0 ? `${stage} · ${t('worldDraft.steps', { n: d.steps })}` : stage
}


/** A world being built (or one that finished and is waiting to be reviewed). */
export function WorldDraftCard({
  draft, onOpen, onDiscard,
}: {
  draft: WorldDraftRow
  onOpen: (draftId: string) => void
  onDiscard: (draftId: string) => void
}) {
  const generating = draft.status === 'generating'
  const pct = Math.min(12 + draft.steps * 16, 92)
  return (
    <div className={`ew-card ew-card-draft ew-card-draft-${draft.status}`}>
      <button
        className="ew-card-open"
        type="button"
        disabled={generating}
        onClick={() => onOpen(draft.draftId)}
      >
        <div className="ew-titlerow">
          <span className="ew-title">{draft.title || t('worldDraft.untitled')}</span>
          {draft.status === 'ready' ? <Chip accent>{t('worldDraft.readyChip')}</Chip> : null}
        </div>
        <div className="ew-meta">{draftWhere(draft)}</div>
        {generating ? (
          <div className="ew-progress" role="status" aria-live="polite">
            <div className="ew-progress-track">
              <div className="ew-progress-fill" style={{ width: `${pct}%` }} />
            </div>
          </div>
        ) : null}
      </button>
      {/* Discarding is allowed at any stage — a generating draft you no longer want
          should not be stuck on the shelf until it times out. */}
      <div className="ew-life-actions">
        <button
          className="ew-btn ew-btn-quiet ew-card-drop"
          type="button"
          aria-label={t('worldDraft.discardAria', { title: draft.title || '' })}
          onClick={() => onDiscard(draft.draftId)}
        >
          {t('worldDraft.discard')}
        </button>
      </div>
    </div>
  )
}


/** The paste screen (view === 'create'). */
export function CreateWorldScreen({
  onCancel, onCreated,
}: {
  onCancel: () => void
  /** Called with the new draftId once the compile job is dispatched. */
  onCreated: (draftId: string) => void
}) {
  const [text, setText] = useState<string>(() => {
    try {
      return window.localStorage.getItem(CREATE_DRAFT_KEY) ?? ''
    } catch {
      return ''
    }
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Save on every change: there is no reliable "leaving" event when the dashboard
  // unmounts a page, so a debounce or an onblur would lose the last keystrokes.
  useEffect(() => {
    try {
      if (text) window.localStorage.setItem(CREATE_DRAFT_KEY, text)
      else window.localStorage.removeItem(CREATE_DRAFT_KEY)
    } catch {
      // A full or blocked localStorage is not worth failing the screen over.
    }
  }, [text])

  const submit = async () => {
    const body = text.trim()
    if (!body || busy) return
    setBusy(true)
    setError('')
    try {
      const { draftId } = await api.createWorldDraft(body)
      // Fire the compile and DON'T await it — the draft now lives on the server and
      // the shelf/review poll it to completion, so the player can leave freely.
      void api.compileWorldDraft(draftId)
      try {
        window.localStorage.removeItem(CREATE_DRAFT_KEY)
      } catch {
        /* ignore */
      }
      onCreated(draftId)
    } catch (e) {
      setBusy(false)
      setError((e as { body?: { error?: string } })?.body?.error || t('create.failed'))
    }
  }

  const count = [...text.trim()].length
  return (
    <div className="ew-create">
      <div className="ew-section">{t('create.heading')}</div>
      <textarea
        className="ew-create-ta"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t('create.placeholder')}
        autoFocus
        spellCheck={false}
      />
      <div className="ew-create-hint">{t('create.hint')}</div>
      {error ? <div className="ew-note ew-note-row">{error}</div> : null}
      <div className="ew-bar">
        <button className="ew-btn ew-btn-quiet" type="button" onClick={onCancel} disabled={busy}>
          {t('create.cancel')}
        </button>
        <button
          className="ew-btn ew-btn-go"
          type="button"
          onClick={() => void submit()}
          disabled={busy || count === 0}
        >
          {busy ? t('create.submitting') : t('create.submit')}
        </button>
        <span className="ew-create-count">{t('create.count', { n: count })}</span>
      </div>
    </div>
  )
}


/** The worldsmith agent, as registered by app.json — the agent a jump-to-chat
 *  launches so the player keeps adjusting the SAME draft (its tools act by
 *  draftId, so a fresh chat carrying the id can read and re-submit it). */
const WORLDSMITH_AGENT = 'endless-worldsmith'

/** The host App SDK, reached defensively through the window module map (an older
 *  host may not expose the chat launcher — the UI degrades to an inline hint). */
const appSdk = (window as unknown as {
  __kirocrew_modules?: Record<string, unknown>
}).__kirocrew_modules?.['@kirocrew/app-sdk'] as
  | { useChatLauncher?: () => { openChat: (opts?: { agent?: string; message?: string }) => void } }
  | undefined


/** The review screen (view === 'draft'). Polls until the worldsmith is done, then
 *  shows what the world will contain and offers accept / discard / jump-to-chat. */
export function WorldDraftReview({
  draftId, onInstalled, onDiscarded, onBack,
}: {
  draftId: string
  onInstalled: (worldId: string) => void
  onDiscarded: () => void
  onBack: () => void
}) {
  const [draft, setDraft] = useState<WorldDraftDetail | null>(null)
  const [error, setError] = useState('')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState<'' | 'installing' | 'discarding'>('')
  const [chatHint, setChatHint] = useState(false)
  const titleTouched = useRef(false)
  // One auto-kick per mount: a draft still `new` when the review opens means the
  // create screen's fire-and-forget dispatch was lost (navigation, refused slot).
  // Re-dispatching is safe — the route short-circuits `generating`/`installed` —
  // but a failing kick must not re-fire on every 3s poll.
  const kicked = useRef(false)
  // The host's chat launcher, when available. Called unconditionally (the module
  // map is fixed for the app's lifetime, so the optional-chain branch never flips).
  const launcher = appSdk?.useChatLauncher?.() ?? null

  const kickCompile = async () => {
    try {
      await api.compileWorldDraft(draftId)
    } catch {
      // The dispatch itself failed (no chat runtime, refused slot). Show the
      // failed screen with a retry instead of a progress bar that never moves.
      setDraft((d) => (d ? { ...d, status: 'failed', problem: d.problem || '' } : d))
    }
  }

  const retry = async () => {
    kicked.current = true
    setDraft((d) => (d ? { ...d, status: 'generating' } : d))
    await kickCompile()
    void load()
  }

  const load = async () => {
    try {
      const d = await api.worldDraft(draftId)
      setDraft(d)
      if (d.status === 'new' && !kicked.current) {
        kicked.current = true
        void kickCompile()
      }
      // Seed the editable title from the compiled world once, then leave the
      // player's edits alone across polls.
      if (!titleTouched.current) {
        setTitle(d.preview?.title || d.title || '')
      }
    } catch {
      setError(t('review.gone'))
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftId])

  const generating = draft?.status === 'generating' || draft?.status === 'new'
  useEffect(() => {
    if (!generating) return undefined
    const timer = window.setInterval(() => { void load() }, DRAFT_POLL_MS)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generating, draftId])

  const install = async () => {
    if (busy) return
    setBusy('installing')
    try {
      const { worldId } = await api.installWorldDraft(draftId, title.trim())
      onInstalled(worldId)
    } catch (e) {
      setBusy('')
      setError((e as { body?: { error?: string } })?.body?.error || t('review.installFailed'))
    }
  }

  const discard = async () => {
    if (busy) return
    setBusy('discarding')
    try {
      await api.discardWorldDraft(draftId)
      onDiscarded()
    } catch {
      setBusy('')
      setError(t('review.discardFailed'))
    }
  }

  /** Keep adjusting in the dashboard chat: launch the worldsmith with a message
   *  naming this draft, so it can re-read and re-submit it. Falls back to an inline
   *  hint on a host without the launcher. */
  const jumpToChat = () => {
    if (!draft) return
    if (launcher) {
      launcher.openChat({
        agent: WORLDSMITH_AGENT,
        message: t('review.jumpMessage', {
          title: draft.title || draft.preview?.title || '',
          id: draft.draftId,
        }),
      })
      return
    }
    setChatHint(true)
  }

  if (error) {
    return (
      <div className="ew-create">
        <div className="ew-note ew-note-row">{error}</div>
        <div className="ew-bar">
          <button className="ew-btn ew-btn-quiet" type="button" onClick={onBack}>
            {t('review.back')}
          </button>
        </div>
      </div>
    )
  }

  if (!draft || generating) {
    const steps = draft?.steps ?? 0
    const pct = Math.min(12 + steps * 16, 92)
    return (
      <div className="ew-create">
        <div className="ew-section">{t('worldDraft.generating')}</div>
        <div className="ew-meta">{t('review.stillWorking')}</div>
        <div className="ew-progress" role="status" aria-live="polite">
          <div className="ew-progress-track">
            <div className="ew-progress-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div className="ew-bar">
          <button className="ew-btn ew-btn-quiet" type="button" onClick={onBack}>
            {t('review.leave')}
          </button>
        </div>
      </div>
    )
  }

  if (draft.status === 'failed') {
    return (
      <div className="ew-create">
        <div className="ew-section">{t('worldDraft.failed')}</div>
        <div className="ew-note">{draft.problem || t('review.failedGeneric')}</div>
        <div className="ew-create-hint">{t('review.failedHint')}</div>
        <button
          className="ew-draft-jump"
          type="button"
          onClick={jumpToChat}
        >
          {t('review.jump')}
        </button>
        {chatHint ? <div className="ew-create-hint">{t('review.jumpHint')}</div> : null}
        <div className="ew-bar">
          <button
            className="ew-btn"
            type="button"
            onClick={() => void retry()}
            disabled={!!busy}
          >
            {t('review.retry')}
          </button>
          <button
            className="ew-btn ew-btn-quiet"
            type="button"
            onClick={() => void discard()}
            disabled={!!busy}
          >
            {t('review.discard')}
          </button>
        </div>
      </div>
    )
  }

  // status === 'ready'
  const p = draft.preview
  return (
    <div className="ew-create">
      <div className="ew-section">{t('review.heading')}</div>

      <label className="ew-create-titlelabel" htmlFor="ew-world-title">
        {t('review.titleLabel')}
      </label>
      <input
        id="ew-world-title"
        className="ew-title-edit"
        value={title}
        maxLength={80}
        onChange={(e) => { titleTouched.current = true; setTitle(e.target.value) }}
      />

      {p ? (
        <div className="ew-review">
          {p.promise ? (
            <div className="ew-kv"><span className="ew-k">{t('review.promise')}</span>
              <span>{p.promise}</span></div>
          ) : null}
          <div className="ew-kv"><span className="ew-k">{t('review.clock')}</span>
            <span>{p.clock}</span></div>
          {p.styles.length ? (
            <div className="ew-kv"><span className="ew-k">{t('review.styles')}</span>
              <span className="ew-chips">
                {p.styles.map((s) => <Chip key={s}>{s}</Chip>)}
              </span></div>
          ) : null}
          {p.opening.length ? (
            <div className="ew-kv"><span className="ew-k">{t('review.opening')}</span>
              <span>{p.opening.join(' · ')}</span></div>
          ) : null}
          <div className="ew-kv"><span className="ew-k">{t('review.endings')}</span>
            <span>{t('review.endingsN', { n: p.endings })}</span></div>
        </div>
      ) : null}

      {draft.dropped.length ? (
        <div className="ew-review-warn">
          <div className="ew-review-warn-h">{t('review.dropped')}</div>
          <ul className="ew-list">
            {draft.dropped.map((d, i) => <li key={i}>{d}</li>)}
          </ul>
        </div>
      ) : null}
      {draft.warnings.length ? (
        <div className="ew-review-warn">
          <div className="ew-review-warn-h">{t('review.warnings')}</div>
          <ul className="ew-list">
            {draft.warnings.map((wn, i) => <li key={i}>{wn}</li>)}
          </ul>
        </div>
      ) : null}

      <button
        className="ew-draft-jump"
        type="button"
        onClick={jumpToChat}
      >
        {t('review.jump')}
      </button>
      {chatHint ? <div className="ew-create-hint">{t('review.jumpHint')}</div> : null}

      <div className="ew-bar">
        <button
          className="ew-btn ew-btn-quiet"
          type="button"
          onClick={() => void discard()}
          disabled={!!busy}
        >
          {t('review.discard')}
        </button>
        <button
          className="ew-btn ew-btn-go ew-review-accept"
          type="button"
          onClick={() => void install()}
          disabled={!!busy}
        >
          {busy === 'installing' ? t('review.installing') : t('review.accept')}
        </button>
      </div>
    </div>
  )
}
