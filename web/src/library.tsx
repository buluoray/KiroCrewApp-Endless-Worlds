import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import type {
  LifeDeletionFacts,
  LifeRowData,
  LoreEntry,
  OpeningGroup,
  WorldDetail,
  WorldRow,
} from './api'
import { ApiError, api, API } from './api'
import { t } from './strings'
import { Chip, Prose } from './ui'

const TURN_UNITS: Record<string, string> = {
  month: 'unit.month',
  year: 'unit.year',
  day: 'unit.day',
  week: 'unit.week',
  season: 'unit.season',
}

/**
 * How a language reads in its own tongue. Endonyms are conventionally not
 * translated, so they carry no catalog key; an unknown tag shows its own code
 * uppercased rather than nothing.
 */
const LANGUAGE_ENDONYM: Record<string, string> = {
  en: 'English',
  zh: '中文',
  ja: '日本語',
  ko: '한국어',
  fr: 'Français',
  de: 'Deutsch',
  es: 'Español',
  'pt-br': 'Português',
  ru: 'Русский',
}

export function languageName(tag: string): string {
  return LANGUAGE_ENDONYM[tag] ?? tag.toUpperCase()
}

/** A three-bar hamburger, drawn rather than imported: this app carries no icon
 *  dependency, and an SVG keeps it crisp and theme-coloured (currentColor). */
function MenuGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <line
        x1="3"
        y1="5"
        x2="15"
        y2="5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <line
        x1="3"
        y1="9"
        x2="15"
        y2="9"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <line
        x1="3"
        y1="13"
        x2="15"
        y2="13"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}

/**
 * How a turn reads, in one place.
 *
 * The card and the detail view used to build this phrase separately, which is how
 * the detail view came to print "undefined": it read a field name the card did not
 * use.
 */
export function turnPhrase(unit: string | undefined): string {
  const key = unit ? TURN_UNITS[unit] : undefined
  return t('world.turnUnit', { unit: key ? t(key) : String(unit ?? '') })
}

/** A world on the shelf. Its own words, never the app's vocabulary. */
export function WorldCard({
  world,
  onOpen,
  plays = 0,
}: {
  world: WorldRow
  onOpen: (id: string) => void
  /** How many lives the player has lived in this world, shown as a footprint. */
  plays?: number
}) {
  if (!world.usable) {
    return (
      <div className="ew-card ew-card-broken">
        <div className="ew-title" style={{ marginBottom: '4px' }}>
          {world.title}
        </div>
        <div className="ew-meta">
          {world.needsCore
            ? t('world.needsNewerCore', {
                needed: world.needsCore,
                local: world.localCore ?? '?',
              })
            : t('world.unopenable', { problem: world.problem ?? '' })}
        </div>
      </div>
    )
  }

  const possibilities = (world.cardPossibilities ?? []).filter(Boolean).slice(0, 3)
  const promise = world.cardPromise?.trim() || t('world.cardFallback')

  return (
    <button className="ew-card ew-world-card" type="button" onClick={() => onOpen(world.worldId)}>
      <div className="ew-world-band">
        <span className="ew-world-band-title">{world.title}</span>
        {world.lineage ? <Chip accent>{t('world.lineage')}</Chip> : null}
      </div>
      <div className="ew-world-body">
        <div className="ew-world-promise">{promise}</div>
        {possibilities.length ? (
          <div className="ew-world-possibilities">
            {possibilities.map((possibility) => (
              <span className="ew-world-possibility" key={possibility}>
                {possibility}
              </span>
            ))}
          </div>
        ) : null}
        <div className="ew-world-card-footer">
          <span className="ew-meta">
            {plays > 0 ? t('world.plays', { n: plays }) : t('world.cardUntold')}
          </span>
          <span className="ew-world-enter">{t('world.cardEnter')} →</span>
        </div>
      </div>
    </button>
  )
}

/**
 * A life in progress.
 *
 * This is the load-bearing half of not losing your place: even if the app forgets
 * which screen you were on, the life itself is listed and one tap from where you
 * left it.
 */
export function LifeRow({
  run,
  onOpen,
  onDeleted,
  onArchive,
  onRename,
}: {
  run: LifeRowData
  onOpen: (runId: string) => void
  /** Ending this life. On the SHELF rather than only inside the life, because a
   *  life whose world cannot be resolved answers 422 when opened — so the play page
   *  can never be where you go to be rid of it.
   *
   *  The card runs the whole flow itself and reports only the outcome. The ask is a
   *  strip UNDER this card rather than a page-level dialog: it cannot be mistaken
   *  for a different life, it needs no scrim, and it cannot be stranded away from
   *  the thing it is about. Its presence is also what offers the action at all.
   */
  onDeleted?: (turn: number) => void
  onArchive?: (runId: string, archived: boolean) => void
  /** Give this life a player-chosen name. Managed-list only. */
  onRename?: (runId: string, label: string) => void
}) {
  // The name the player reads: their own label first, then the answer-derived
  // subtitle, then the world's title.
  const name = run.label || run.subtitle || run.title || run.worldId

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const commit = () => {
    onRename?.(run.runId, draft.trim())
    setEditing(false)
  }

  // Ending this life: `null` until asked, then the strip under the card.
  const [doom, setDoom] = useState<'asking' | 'working' | null>(null)
  const [facts, setFacts] = useState<LifeDeletionFacts | null>(null)
  const [problem, setProblem] = useState('')

  // The month comes from the SERVER, never from this row: it is sent back as a
  // precondition, and the row's copy can lag behind the life's own state. Asking
  // costs one small request and is what lets the ask name a true number.
  useEffect(() => {
    if (doom !== 'asking' || facts) return
    let alive = true
    api
      .lifeDeletion(run.runId)
      .then((f) => {
        if (alive) setFacts(f)
      })
      .catch((e: Error) => {
        if (alive) setProblem(e.message)
      })
    return () => {
      alive = false
    }
  }, [doom, facts, run.runId])

  const endThisLife = () => {
    if (!facts || doom === 'working') return
    setDoom('working')
    setProblem('')
    api
      .deleteLife(run.runId, facts.turn)
      .then((out) => onDeleted?.(out.turn))
      .catch((e: Error) => {
        const code = e instanceof ApiError ? e.code : ''
        // Both refusals mean the same thing: what we were about to describe is no
        // longer what is there. Re-ask with the server's new numbers rather than
        // retrying against the stale one.
        if (code === 'turn_changed' || code === 'turn_in_flight') {
          setProblem(t(code === 'turn_changed' ? 'life.delete.changed' : 'life.delete.inFlight'))
          setFacts(null)
          setDoom('asking')
          return
        }
        setProblem(e.message)
        setDoom('asking')
      })
  }

  // On a phone the three row actions wrapped into an ugly stack, so there they
  // collapse into a kebab menu (inline on desktop, unchanged). One list of actions
  // feeds both, so the two renderings can never drift apart.
  const [menuOpen, setMenuOpen] = useState(false)
  // "重开叙事" runs its whole flow inside the card, like delete: an ask strip under
  // the card, then the call, then a one-line outcome. Distinct state from `doom`
  // so an open delete ask and an open reset ask can never wear each other's text.
  const [resetAsk, setResetAsk] = useState<null | 'asking' | 'working' | 'done'>(null)
  const [resetProblem, setResetProblem] = useState('')
  const resetStoryteller = () => {
    if (resetAsk === 'working') return
    setResetAsk('working')
    setResetProblem('')
    api
      .resetConversation(run.runId)
      .then(() => setResetAsk('done'))
      .catch((e: Error) => {
        const code = e instanceof ApiError ? e.code : ''
        setResetProblem(code === 'turn_in_flight' ? t('life.resetChat.busy') : e.message)
        setResetAsk('asking')
      })
  }
  // The ref must be on the PORTALLED panel, not on the card's menu container: once
  // the panel moved to `document.body` it stopped being a descendant of the card, so
  // a containment test against the container answered false for the panel's own
  // items — the close handler fired on mousedown, React unmounted the item, and the
  // click that would have run the action never landed on anything. Closing looked
  // like working.
  const panelRef = useRef<HTMLDivElement>(null)
  const kebabRef = useRef<HTMLButtonElement>(null)
  // Where to put the portalled menu: measured from the kebab, because once the menu
  // leaves the card it can no longer be positioned relative to it.
  const [menuAt, setMenuAt] = useState<{ top: number; right: number } | null>(null)
  useEffect(() => {
    if (!menuOpen) return undefined
    const close = (e: MouseEvent) => {
      const inMenu = panelRef.current?.contains(e.target as Node)
      const onKebab = kebabRef.current?.contains(e.target as Node)
      if (!inMenu && !onKebab) setMenuOpen(false)
    }
    // A scroll or resize moves the kebab out from under a menu anchored to where it
    // WAS, so the menu closes rather than floating somewhere unrelated.
    const drop = () => setMenuOpen(false)
    document.addEventListener('mousedown', close)
    window.addEventListener('scroll', drop, true)
    window.addEventListener('resize', drop)
    return () => {
      document.removeEventListener('mousedown', close)
      window.removeEventListener('scroll', drop, true)
      window.removeEventListener('resize', drop)
    }
  }, [menuOpen])

  const openMenu = () => {
    const r = kebabRef.current?.getBoundingClientRect()
    if (r) setMenuAt({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) })
    setMenuOpen((o) => !o)
  }
  const actions: Array<{ key: string; label: string; aria?: string; onClick: () => void }> = []
  if (onRename) {
    actions.push({
      key: 'rename',
      label: t('life.rename.short'),
      aria: t('life.rename.aria', { name }),
      onClick: () => {
        setDraft(run.label || '')
        setEditing(true)
      },
    })
  }
  if (onArchive) {
    actions.push({
      key: 'archive',
      label: run.archived ? t('life.unarchive') : t('life.archive'),
      onClick: () => onArchive(run.runId, !run.archived),
    })
  }
  // Offered wherever archive is (the managed shelf): a life that can be archived
  // is a life whose narrator can have drifted. Unreadable lives are excluded —
  // they cannot narrate at all, so a fresh conversation buys them nothing.
  if (onArchive && !run.unreadable) {
    actions.push({
      key: 'resetChat',
      label: t('life.resetChat.short'),
      aria: t('life.resetChat.aria', { name }),
      onClick: () => {
        setResetProblem('')
        setResetAsk('asking')
      },
    })
  }
  if (onDeleted) {
    actions.push({
      key: 'delete',
      label: t('life.delete.short'),
      aria: t('life.delete.aria', { name }),
      onClick: () => {
        setProblem('')
        setFacts(null)
        setDoom('asking')
      },
    })
  }

  // Checked before the other states: a life mid-generation is also awaitingOpening,
  // and "not born yet" would read as stalled when in fact it is being written.
  const where = run.unreadable
    ? t('life.unreadable')
    : run.generating
      ? t('life.generating')
      : run.ended
        ? t('life.ended')
        : run.awaitingOpening
          ? t('life.unborn')
          : t('life.turn', { turn: run.turn })

  if (editing) {
    return (
      <div className="ew-card ew-card-row">
        <input
          className="ew-rename-input"
          value={draft}
          maxLength={60}
          autoFocus
          placeholder={t('life.rename.placeholder')}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') setEditing(false)
          }}
        />
        <button className="ew-btn ew-btn-sm ew-btn-go" type="button" onClick={commit}>
          {t('life.rename.save')}
        </button>
        <button className="ew-btn ew-btn-sm" type="button" onClick={() => setEditing(false)}>
          {t('life.rename.cancel')}
        </button>
      </div>
    )
  }

  // A div, not a button. The row carries its own controls, and a button inside a
  // button is invalid HTML — browsers recover from it unpredictably, and the inner
  // click can be swallowed by the outer one.
  return (
    <div className="ew-card ew-card-row">
      {/* The backdrop and its scrim live in their OWN clipping box rather than
          relying on the card to clip them. The card used to carry
          `overflow: hidden` for this, which also silently cut the row's action menu
          off at the card's edge — one property serving two purposes, and the menu
          lost. Clipping here is exact (the layers round themselves) and local. */}
      {run.backdrop ? (
        <div className="ew-card-bgclip" aria-hidden="true">
          <img
            className="ew-card-bg"
            src={`${API}/runs/${encodeURIComponent(run.runId)}/backdrop?v=${run.backdrop.version}`}
            alt=""
            draggable={false}
          />
          <div className="ew-card-bg-scrim" />
        </div>
      ) : null}
      {/* The row proper. Wrapped so the card can hold a SECOND row beneath it —
          the delete ask — without that strip landing beside the kebab in this
          horizontal flex. */}
      <div className="ew-card-rowmain">
        <button
          className="ew-card-open"
          type="button"
          disabled={!!run.unreadable}
          onClick={() => onOpen(run.runId)}
        >
          <div className="ew-titlerow">
            {/* The life first, the world second. Four rows reading only the world's name
                told the player nothing about which life they were choosing. */}
            <span className="ew-title">{name}</span>
            {run.awaitingOpening ? <Chip accent>{t('life.waiting')}</Chip> : null}
          </div>
          {name !== run.title ? <div className="ew-sub">{run.title}</div> : null}
          <div className="ew-meta">{where}</div>
        </button>
        {actions.length ? (
          <>
            {/* Desktop: the actions inline, as before. */}
            <div className="ew-life-actions">
              {actions.map((a) => (
                <button
                  key={a.key}
                  className="ew-btn ew-btn-quiet ew-card-drop"
                  type="button"
                  aria-label={a.aria}
                  onClick={a.onClick}
                >
                  {a.label}
                </button>
              ))}
            </div>
            {/* Mobile: one kebab that opens the same actions as a menu. */}
            <div className="ew-life-menu">
              <button
                ref={kebabRef}
                className="ew-kebab"
                type="button"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-label={t('life.actions', { name })}
                onClick={openMenu}
              >
                <MenuGlyph />
              </button>
              {menuOpen && menuAt
                ? createPortal(
                    <>
                      {/* Portalled to body, with the backdrop, for a reason no z-index could
                      solve: inside the card these sat in a stacking context the content
                      wrapper created, so the menu painted UNDER the phone's bottom bars
                      however high its own z-index went. At body level it competes with
                      them directly — and it also escapes the card's own box, which used
                      to cut it off a few rows short.

                      The backdrop absorbs a tap that lands outside the menu (and the
                      iOS ghost click after choosing an item), which would otherwise
                      fall through and open the life beneath. */}
                      <div
                        className="ew-menu-backdrop"
                        aria-hidden="true"
                        onClick={() => setMenuOpen(false)}
                      />
                      <div
                        className="ew-menu"
                        role="menu"
                        ref={panelRef}
                        style={{ top: `${menuAt.top}px`, right: `${menuAt.right}px` }}
                      >
                        {actions.map((a) => (
                          <button
                            key={a.key}
                            className="ew-menu-item"
                            role="menuitem"
                            type="button"
                            aria-label={a.aria}
                            onClick={(e) => {
                              e.stopPropagation()
                              setMenuOpen(false)
                              a.onClick()
                            }}
                            onTouchEnd={(e) => {
                              // iOS/WKWebView: a tap that unmounts this item lets the
                              // trailing synthetic click fall through to the life row's
                              // open button beneath — the "click-through" bug. preventDefault
                              // on touchend cancels that synthetic click sequence entirely
                              // (touchend is not a React passive listener), so we run the
                              // action here for touch and let onClick handle mouse.
                              e.preventDefault()
                              e.stopPropagation()
                              setMenuOpen(false)
                              a.onClick()
                            }}
                          >
                            {a.label}
                          </button>
                        ))}
                      </div>
                    </>,
                    document.body,
                  )
                : null}
            </div>
          </>
        ) : null}
      </div>
      {doom ? (
        <div className="ew-rowdoom" role="group" aria-label={t('life.delete.title')}>
          <div className="ew-rowdoom-say">
            {!facts
              ? t('life.delete.reading')
              : facts.unreadable
                ? t('life.delete.unreadable')
                : facts.turn > 0
                  ? t(facts.turn === 1 ? 'life.delete.monthsOne' : 'life.delete.months', {
                      name,
                      n: facts.turn,
                    })
                  : t('life.delete.unborn', { name })}
          </div>
          <div className="ew-meta ew-rowdoom-note">{t('life.delete.forever')}</div>
          {problem ? <div className="ew-modal-problem">{problem}</div> : null}
          <div className="ew-rowdoom-bar">
            <button
              className="ew-btn ew-btn-sm"
              type="button"
              onClick={() => {
                setDoom(null)
                setProblem('')
              }}
            >
              {t('delete.cancel')}
            </button>
            <button
              className="ew-btn ew-btn-sm ew-btn-danger"
              type="button"
              disabled={!facts || doom === 'working'}
              onClick={endThisLife}
            >
              {doom === 'working' ? t('delete.working') : t('life.delete.go')}
            </button>
          </div>
        </div>
      ) : null}
      {resetAsk ? (
        <div className="ew-rowdoom" role="group" aria-label={t('life.resetChat.short')}>
          <div className="ew-rowdoom-say">
            {resetAsk === 'done' ? t('life.resetChat.done') : t('life.resetChat.confirm')}
          </div>
          {resetProblem ? <div className="ew-modal-problem">{resetProblem}</div> : null}
          <div className="ew-rowdoom-bar">
            {resetAsk === 'done' ? (
              <button className="ew-btn ew-btn-sm" type="button" onClick={() => setResetAsk(null)}>
                {t('life.resetChat.ok')}
              </button>
            ) : (
              <>
                <button
                  className="ew-btn ew-btn-sm"
                  type="button"
                  onClick={() => {
                    setResetAsk(null)
                    setResetProblem('')
                  }}
                >
                  {t('life.resetChat.cancel')}
                </button>
                <button
                  className="ew-btn ew-btn-sm"
                  type="button"
                  disabled={resetAsk === 'working'}
                  onClick={resetStoryteller}
                >
                  {resetAsk === 'working' ? t('life.resetChat.working') : t('life.resetChat.short')}
                </button>
              </>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}

/** The world's setting as a browsable, grouped structure — the reader-facing face
 *  of the world's `lore`. Grouped by category; each entry expands to its body, and
 *  its relations to other entries are shown as a small edge list. */
function WorldSetting({ lore }: { lore: LoreEntry[] }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const names = new Map(lore.map((e) => [e.id, e.name]))
  const order: string[] = []
  const groups = new Map<string, LoreEntry[]>()
  for (const e of lore) {
    const cat = e.category || t('world.settingOther')
    if (!groups.has(cat)) {
      groups.set(cat, [])
      order.push(cat)
    }
    groups.get(cat)!.push(e)
  }
  return (
    <div className="ew-setting" style={{ marginTop: '18px' }}>
      <div className="ew-section">{t('world.setting')}</div>
      {order.map((cat) => (
        <div className="ew-setting-group" key={cat}>
          <div className="ew-glabel">{cat}</div>
          {(groups.get(cat) ?? []).map((e) => (
            <div className="ew-setting-entry" key={e.id}>
              <button
                className="ew-setting-head"
                type="button"
                aria-expanded={!!open[e.id]}
                onClick={() => setOpen((o) => ({ ...o, [e.id]: !o[e.id] }))}
              >
                <span className="ew-setting-name">{e.name}</span>
                {e.summary ? <span className="ew-setting-sum">{e.summary}</span> : null}
                <span className="ew-setting-caret" aria-hidden="true" />
              </button>
              {open[e.id] ? (
                <div className="ew-setting-body">
                  <Prose text={e.text} />
                  {e.relations.length ? (
                    <div className="ew-setting-rel">
                      {e.relations.map((r, i) => (
                        <span className="ew-chip" key={`${r.to}-${i}`}>
                          {r.label ? `${r.label} · ` : ''}
                          {names.get(r.to) ?? r.to}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

export function WorldDetailView({
  worldId,
  onBack,
  onPlay,
  onDelete,
  onLanguage,
  initialLanguage,
}: {
  worldId: string
  onBack: () => void
  onPlay: (world: WorldDetail) => void
  /** Opening the confirmation is the parent's job: the dialog belongs above this
   *  view so it is not unmounted by the very reload that follows a deletion. */
  onDelete: (worldId: string) => void
  /** Told the language of whatever variant is now shown, so the parent can keep
   *  the dashboard chrome in the same language as the world being read. */
  onLanguage?: (language: string) => void
  /** The reader's chosen UI language, used as the language this world first opens
   *  in — so a player reading the app in English lands on the English rendering
   *  when the world has one, rather than the world's authoring language. */
  initialLanguage?: string
}) {
  const [world, setWorld] = useState<WorldDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const [laws, setLaws] = useState(false)
  // The language the player is reading this world in. Starts at the app's chosen
  // language; a pick from the toggle re-fetches the variant so labels AND lore
  // switch together, which is the whole point of the choice.
  const [language, setLanguage] = useState<string | undefined>(initialLanguage)

  useEffect(() => {
    let alive = true
    setWorld(null)
    setError(null)
    // The detail page shows structured `lore` AND, as "world laws", the cleaned
    // core-rule prose — so it fetches the prose too.
    api
      .world(worldId, true, language)
      .then((w) => {
        if (alive) {
          setWorld(w)
          if (w.language) onLanguage?.(w.language)
        }
      })
      .catch((e: Error) => {
        if (alive) setError(e.message)
      })
    return () => {
      alive = false
    }
  }, [worldId, nonce, language])

  const back = (
    <button className="ew-back" type="button" onClick={onBack}>
      {t('world.back')}
    </button>
  )

  if (error) {
    return (
      <div>
        {back}
        <div className="ew-meta">{t('world.unreadableDetail', { error })}</div>
        <div className="ew-bar">
          <button className="ew-btn" type="button" onClick={() => setNonce((n) => n + 1)}>
            {t('library.retry')}
          </button>
        </div>
      </div>
    )
  }
  if (!world) {
    return (
      <div>
        {back}
        <div className="ew-meta">{t('library.preparing')}</div>
      </div>
    )
  }

  const styleRows = (world.styleRows ?? []) as Array<{ id: string; label: string }>
  const groups: OpeningGroup[] = world.opening ?? []

  return (
    <div>
      {back}
      <h3 className="ew-detail-title">{world.title}</h3>
      <div className="ew-meta" style={{ marginBottom: '18px' }}>
        {t('world.detailMeta', {
          turn: turnPhrase(world.clockUnit),
          styles: styleRows.length,
          lineage: world.lineage ? t('world.detailLineage') : '',
        })}
      </div>

      {(world.languages ?? []).length > 1 ? (
        <div className="ew-block">
          <div className="ew-section">{t('world.languagePick')}</div>
          <div className="ew-chips" role="group" aria-label={t('world.languagePick')}>
            {(world.languages ?? []).map((lg) => (
              <button
                key={lg}
                type="button"
                className="ew-lang"
                aria-pressed={world.language === lg}
                onClick={() => setLanguage(lg)}
              >
                {languageName(lg)}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="ew-section">{t('world.opening')}</div>
      <div className="ew-chips ew-block">
        {groups.map((g) => (
          <Chip key={g.id} accent={g.worldDecides}>
            {g.label}
          </Chip>
        ))}
      </div>
      {groups.some((g) => g.worldDecides) ? (
        <div className="ew-hint ew-block">{t('world.worldDecidesHint')}</div>
      ) : null}

      <div className="ew-section">{t('world.panels')}</div>
      <div className="ew-block">
        {(world.panels ?? []).map((p) => (
          <div className="ew-panel" key={p.id}>
            <div className="ew-panel-head">
              <span className="ew-panel-name">{p.label || p.id}</span>
              <Chip accent={p.always}>
                {p.always ? t('world.panelAlways') : t('world.panelConditional')}
              </Chip>
              <span style={{ fontSize: '11px', color: 'var(--muted, #6b7280)' }}>
                {t('world.panelFields', { count: p.fields.length })}
              </span>
            </div>
            <div className="ew-chips">
              {p.fields.map((f) => (
                <Chip key={f.id}>{f.label}</Chip>
              ))}
            </div>
          </div>
        ))}
      </div>

      {(world.digest ?? []).length ? (
        <>
          <div className="ew-section">{t('world.digest')}</div>
          <div className="ew-chips ew-block">
            {(world.digest ?? []).map((c) => (
              <Chip key={c}>{c}</Chip>
            ))}
          </div>
        </>
      ) : null}

      <div className="ew-meta">
        {t('world.endings', {
          endings: (world.endings ?? []).length,
          save: (world.save ?? []).length,
        })}
      </div>

      {world.lore?.length ? <WorldSetting lore={world.lore} /> : null}

      {world.roles?.length ? (
        <div className="ew-roles" style={{ marginTop: '18px' }}>
          <div className="ew-section">{t('world.roles')}</div>
          <div className="ew-block">
            {(world.roles ?? []).map((r) => (
              <div className="ew-role" key={r.id}>
                <span className="ew-role-name">{r.name}</span>
                {r.summary ? <span className="ew-role-sum">{r.summary}</span> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {world.prose ? (
        <div className="ew-setting" style={{ marginTop: '18px' }}>
          <div className="ew-setting-entry">
            <button
              className="ew-setting-head"
              type="button"
              aria-expanded={laws}
              onClick={() => setLaws((v) => !v)}
            >
              <span className="ew-setting-name">{t('world.laws')}</span>
              <span className="ew-setting-caret" aria-hidden="true" />
            </button>
            {laws ? (
              <div className="ew-setting-body">
                <Prose text={world.prose} />
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="ew-bar">
        <button className="ew-btn ew-btn-go" type="button" onClick={() => onPlay(world)}>
          {t('world.play')}
        </button>
        {/* Deliberately last and unemphasised, but not hidden behind a menu: a
            destructive action the player cannot find is why data accumulates
            forever, and the confirmation is what makes it safe to offer plainly. */}
        <button
          className="ew-btn ew-btn-quiet"
          type="button"
          onClick={() => onDelete(world.worldId)}
        >
          {t('world.delete')}
        </button>
      </div>
    </div>
  )
}
