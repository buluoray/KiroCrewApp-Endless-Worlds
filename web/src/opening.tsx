import { useEffect, useState } from 'react'

import type { OpeningGroup, WorldDetail } from './api'
import { api } from './api'
import { t } from './strings'

const PER_PAGE = 4

/** Sentinel for "I want to type my own", never a real option value. */
const CUSTOM = '\u0000custom'

/** Where a half-finished opening is kept. Prefixed: this app shares the
 *  dashboard's localStorage. */
export const DRAFT_PREFIX = 'endless-worlds:where:draft:'

/** How long an abandoned opening draft is honoured. A draft is a convenience for
 *  coming back in a day or two, not a permanent resident of shared localStorage —
 *  after this it is ignored on read (and overwritten on the next real edit). */
const DRAFT_TTL_MS = 30 * 24 * 60 * 60 * 1000

interface Draft {
  answers?: Record<string, string>
  customs?: Record<string, string>
  style?: string
  page?: number
  run?: string | null
  /** When the draft was last written, for expiry. Absent on pre-TTL drafts, which
   *  are treated as current rather than expired. */
  savedAt?: number
}

function readDraft(key: string): Draft {
  try {
    const d = (JSON.parse(localStorage.getItem(key) ?? 'null') as Draft | null) ?? {}
    if (typeof d.savedAt === 'number' && Date.now() - d.savedAt > DRAFT_TTL_MS) return {}
    return d
  } catch {
    return {}
  }
}

/**
 * One opening group.
 *
 * A group the world reserves for itself renders as a sealed note, not a picker:
 * offering a choice the world already made would be a lie about who decided.
 */
function Group({
  group, value, custom, onPick, onCustom,
}: {
  group: OpeningGroup
  value: string | undefined
  custom: string | undefined
  onPick: (v: string) => void
  onCustom: (v: string) => void
}) {
  if (group.worldDecides) {
    return (
      <div className="ew-group">
        <div className="ew-glabel">{group.label}</div>
        <div className="ew-sealed">{t('opening.sealed')}</div>
      </div>
    )
  }

  const picking = group.kind === 'pick' && group.options.length > 0
  const isCustom = value === CUSTOM

  return (
    <div className="ew-group">
      <div className="ew-glabel">{group.label}</div>
      <div className="ew-ghint">
        {picking ? t('opening.hintPick') : t('opening.hintText')}
      </div>

      {picking ? (
        <div>
          <div className="ew-chips">
            {group.options.map((o) => (
              <button
                key={o}
                type="button"
                className={`ew-opt${value === o ? ' ew-opt-on' : ''}`}
                onClick={() => onPick(value === o ? '' : o)}
              >
                {o}
              </button>
            ))}
            {group.custom ? (
              <button
                type="button"
                className={`ew-opt${isCustom ? ' ew-opt-on' : ''}`}
                onClick={() => onPick(isCustom ? '' : CUSTOM)}
              >
                {t('opening.custom')}
              </button>
            ) : null}
          </div>
          {isCustom ? (
            <input
              className="ew-input"
              style={{ marginTop: '8px' }}
              value={custom ?? ''}
              maxLength={200}
              placeholder={t('opening.customPlaceholder')}
              onChange={(e) => onCustom(e.target.value)}
            />
          ) : null}
        </div>
      ) : (
        <input
          className="ew-input"
          type="text"
          inputMode={group.kind === 'number' ? 'numeric' : 'text'}
          value={value === CUSTOM ? '' : (value ?? '')}
          maxLength={200}
          onChange={(e) => onPick(e.target.value)}
        />
      )}
    </div>
  )
}

export function OpeningScreen({
  world, onBack, onLive,
}: {
  world: WorldDetail
  onBack: () => void
  onLive: (runId: string) => void
}) {
  // The answers are persisted, not just the fact that you were here. An earlier
  // revision refused to restore this screen on the grounds that bringing back an
  // empty form and calling it "where you left off" would be a lie. That was right
  // about the lie and wrong about the fix: keep the answers, which are a handful of
  // strings.
  const draftKey = `${DRAFT_PREFIX}${world.worldId}`
  const [draft] = useState<Draft>(() => readDraft(draftKey))

  const styleRows = world.styleRows ?? []
  const [answers, setAnswers] = useState<Record<string, string>>(draft.answers ?? {})
  const [customs, setCustoms] = useState<Record<string, string>>(draft.customs ?? {})
  const [style, setStyle] = useState<string>(
    draft.style ?? (styleRows.find((s) => s.default) ?? styleRows[0])?.id ?? '',
  )
  const [page, setPage] = useState(draft.page ?? 0)
  const [busy, setBusy] = useState<'' | 'creating' | 'opening'>('')
  const [failed, setFailed] = useState<string | null>(null)
  const [run, setRun] = useState<string | null>(draft.run ?? null)
  // Whether this screen came back to answers the player left behind, so it can say
  // so once rather than silently pre-filling and looking like the world chose.
  const [restored, setRestored] = useState<boolean>(() =>
    Object.keys(draft.answers ?? {}).length > 0
    || Object.keys(draft.customs ?? {}).length > 0
    || !!draft.run
    || (draft.page ?? 0) > 0,
  )

  // Saved on every change rather than on leave: there is no reliable "leaving"
  // event when the dashboard unmounts a page, and a draft that only survives a
  // graceful exit does not survive the case it exists for.
  useEffect(() => {
    try {
      localStorage.setItem(
        draftKey,
        JSON.stringify({ answers, customs, style, page, run, savedAt: Date.now() }),
      )
    } catch {
      /* private mode: a draft is a convenience, not the life */
    }
  }, [draftKey, answers, customs, style, page, run])

  const clearDraft = () => {
    try {
      localStorage.removeItem(draftKey)
    } catch {
      /* nothing to undo */
    }
  }

  const defaultStyle = (styleRows.find((s) => s.default) ?? styleRows[0])?.id ?? ''
  const dirty = Object.keys(answers).length > 0 || Object.keys(customs).length > 0
  const resetAll = () => {
    setAnswers({})
    setCustoms({})
    setStyle(defaultStyle)
    setPage(0)
    setRestored(false)
  }

  const groups: OpeningGroup[] = world.opening ?? []
  const pages = Math.max(1, Math.ceil(groups.length / PER_PAGE))
  const slice = groups.slice(page * PER_PAGE, page * PER_PAGE + PER_PAGE)
  const last = page >= pages - 1
  const rollable = groups.filter((g) => !g.worldDecides && g.options.length > 0)

  const rollOne = (g: OpeningGroup) => {
    const pick = g.options[Math.floor(Math.random() * g.options.length)]
    if (pick) setAnswers((a) => ({ ...a, [g.id]: pick }))
  }

  const rollAll = () => {
    const next: Record<string, string> = {}
    // Only groups with options can be rolled here. A name has nothing to draw
    // from, so it stays blank and the world decides it — the same rule the backend
    // applies, kept identical on purpose.
    rollable.forEach((g) => {
      const pick = g.options[Math.floor(Math.random() * g.options.length)]
      if (pick) next[g.id] = pick
    })
    setAnswers((a) => ({ ...a, ...next }))
  }

  /** Blanks are omitted entirely — an omitted group means "the world decides" —
   *  and a group the world reserves is never sent, because the backend refuses it. */
  const payload = (): Record<string, string> => {
    const out: Record<string, string> = {}
    groups.forEach((g) => {
      if (g.worldDecides) return
      const v = answers[g.id]
      if (v === CUSTOM) {
        const text = (customs[g.id] ?? '').trim()
        if (text) out[g.id] = text
        return
      }
      if (typeof v === 'string' && v.trim()) out[g.id] = v.trim()
    })
    return out
  }

  // Separate from creation so a retry never produces a second life.
  const openRun = async (runId: string) => {
    setBusy('opening')
    setFailed(null)
    try {
      const out = await api.openRun(runId)
      if (out.advanced || out.reason === 'already') {
        clearDraft()
        onLive(runId)
        return
      }
      setFailed(t('opening.silent'))
    } catch {
      setFailed(t('opening.silent'))
    }
    setBusy('')
  }

  const begin = async () => {
    setBusy('creating')
    setFailed(null)
    try {
      const created = await api.createRun({ worldId: world.worldId, style, answers: payload() })
      setRun(created.runId)
      await openRun(created.runId)
    } catch (e) {
      setFailed((e as Error).message)
      setBusy('')
    }
  }

  if (busy === 'opening' && !failed) {
    return (
      <div>
        <div className="ew-detail-title">{world.title}</div>
        <div className="ew-meta">{t('opening.arranging')}</div>
      </div>
    )
  }

  // A life already exists at this point, so the offer is to retry its first turn —
  // not to fill the form in again.
  if (failed && run) {
    return (
      <div>
        <div className="ew-detail-title">{world.title}</div>
        <div className="ew-note">{`${failed}${t('opening.keptSafe')}`}</div>
        <div className="ew-bar">
          <button className="ew-btn ew-btn-go" type="button" onClick={() => openRun(run)}>
            {t('opening.retry')}
          </button>
          <button className="ew-btn" type="button" onClick={onBack}>
            {t('opening.backToShelf')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      <button className="ew-back" type="button" onClick={onBack}>{t('world.back')}</button>
      <h3 className="ew-detail-title">{world.title}</h3>
      <div className="ew-meta" style={{ marginBottom: '18px' }}>
        {t('opening.page', { page: page + 1, pages })}
      </div>

      {restored ? (
        <div className="ew-note ew-note-row">
          <span>{t('opening.restored')}</span>
          <button
            className="ew-btn ew-btn-quiet"
            type="button"
            onClick={() => setRestored(false)}
          >
            {t('note.dismiss')}
          </button>
        </div>
      ) : null}

      {slice.map((g) => (
        <Group
          key={g.id}
          group={g}
          value={answers[g.id]}
          custom={customs[g.id]}
          onPick={(v) => setAnswers((a) => ({ ...a, [g.id]: v }))}
          onCustom={(v) => setCustoms((c) => ({ ...c, [g.id]: v }))}
        />
      ))}

      {last ? (
        <div className="ew-group">
          <div className="ew-glabel">{t('opening.styleLabel')}</div>
          <div className="ew-ghint">{t('opening.styleHint')}</div>
          <div className="ew-chips">
            {styleRows.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`ew-opt${style === s.id ? ' ew-opt-on' : ''}`}
                onClick={() => setStyle(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {failed && !run ? <div className="ew-note">{failed}</div> : null}

      {/* The whole of this life's opening on one screen before it is committed —
          including, marked plainly, everything left for the world to decide. A
          life cannot be un-lived, so the last thing before it starts is a look at
          what was actually chosen. */}
      {last ? (
        <div className="ew-summary">
          <div className="ew-glabel">{t('opening.summaryTitle')}</div>
          {groups.map((g) => {
            const v = answers[g.id]
            const text = g.worldDecides
              ? ''
              : v === CUSTOM
                ? (customs[g.id] ?? '').trim()
                : (v ?? '').trim()
            return (
              <div className="ew-summary-row" key={g.id}>
                <span className="ew-summary-label">{g.label}</span>
                <span className={text ? 'ew-summary-value' : 'ew-summary-world'}>
                  {text || t('opening.summaryWorld')}
                </span>
              </div>
            )
          })}
          <div className="ew-summary-row">
            <span className="ew-summary-label">{t('opening.styleLabel')}</span>
            <span className="ew-summary-value">
              {styleRows.find((s) => s.id === style)?.label ?? style}
            </span>
          </div>
        </div>
      ) : null}

      <div className="ew-bar">
        {page > 0 ? (
          <button className="ew-btn" type="button" onClick={() => setPage((p) => p - 1)}>
            {t('opening.prev')}
          </button>
        ) : null}
        {rollable.length ? (
          <button className="ew-btn" type="button" onClick={rollAll}>
            {t('opening.rollAll')}
          </button>
        ) : null}
        {dirty ? (
          <button className="ew-btn" type="button" onClick={resetAll}>
            {t('opening.reset')}
          </button>
        ) : null}
        <div className="ew-spacer" />
        {last ? (
          <button className="ew-btn ew-btn-go" type="button" disabled={!!busy} onClick={begin}>
            {busy ? t('opening.beginning') : t('opening.begin')}
          </button>
        ) : (
          <button
            className="ew-btn ew-btn-go"
            type="button"
            onClick={() => setPage((p) => p + 1)}
          >
            {t('opening.next')}
          </button>
        )}
      </div>

      {/* Per-group rolling sits under the bar rather than beside each label: on a
          phone a button next to every label doubles the screen's height. */}
      {slice.some((g) => !g.worldDecides && g.options.length) ? (
        <div className="ew-chips" style={{ marginTop: '12px' }}>
          {slice
            .filter((g) => !g.worldDecides && g.options.length)
            .map((g) => (
              <button key={g.id} type="button" className="ew-opt" onClick={() => rollOne(g)}>
                {t('opening.rollOne', { label: g.label })}
              </button>
            ))}
        </div>
      ) : null}
    </div>
  )
}
