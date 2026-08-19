import { useEffect, useRef, useState } from 'react'

import type { LifeRowData, OpeningGroup, WorldDetail, WorldRow } from './api'
import { api } from './api'
import { t } from './strings'
import { Chip, Prose } from './ui'

const TURN_UNITS: Record<string, string> = {
  month: 'unit.month', year: 'unit.year', day: 'unit.day',
  week: 'unit.week', season: 'unit.season',
}

/**
 * How a language reads in its own tongue. Endonyms are conventionally not
 * translated, so they carry no catalog key; an unknown tag shows its own code
 * uppercased rather than nothing.
 */
const LANGUAGE_ENDONYM: Record<string, string> = {
  en: 'English', zh: '中文', ja: '日本語', ko: '한국어', fr: 'Français',
  de: 'Deutsch', es: 'Español', 'pt-br': 'Português', ru: 'Русский',
}

export function languageName(tag: string): string {
  return LANGUAGE_ENDONYM[tag] ?? tag.toUpperCase()
}

/** A three-bar hamburger, drawn rather than imported: this app carries no icon
 *  dependency, and an SVG keeps it crisp and theme-coloured (currentColor). */
function MenuGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <line x1="3" y1="5" x2="15" y2="5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="3" y1="9" x2="15" y2="9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="3" y1="13" x2="15" y2="13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
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
  world, onOpen, plays = 0,
}: {
  world: WorldRow
  onOpen: (id: string) => void
  /** How many lives the player has lived in this world, shown as a footprint. */
  plays?: number
}) {
  if (!world.usable) {
    return (
      <div className="ew-card ew-card-broken">
        <div className="ew-title" style={{ marginBottom: '4px' }}>{world.title}</div>
        <div className="ew-meta">
          {world.needsCore
            ? t('world.needsNewerCore', {
              needed: world.needsCore, local: world.localCore ?? '?',
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
      <div className="ew-titlerow">
        <span className="ew-title">{world.title}</span>
        {world.lineage ? <Chip accent>{t('world.lineage')}</Chip> : null}
        {world.stale ? <Chip>{t('world.stale')}</Chip> : null}
      </div>
      <div className="ew-world-promise">{promise}</div>
      {possibilities.length ? (
        <div className="ew-world-possibilities">
          <div className="ew-world-possibilities-label">{t('world.cardPossibilities')}</div>
          {possibilities.map((possibility) => (
            <div className="ew-world-possibility" key={possibility}>{possibility}</div>
          ))}
        </div>
      ) : null}
      {world.stalenessNote ? <div className="ew-meta">{world.stalenessNote}</div> : null}
      <div className="ew-world-card-footer">
        <span className="ew-meta">
          {plays > 0 ? t('world.plays', { n: plays }) : t('world.cardUntold')}
        </span>
        <span className="ew-world-enter">{t('world.cardEnter')} →</span>
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
  run, onOpen, onDelete, onArchive, onRename,
}: {
  run: LifeRowData
  onOpen: (runId: string) => void
  /** Ending this life. On the SHELF rather than only inside the life, because a
   *  life whose world cannot be resolved answers 422 when opened — so the play page
   *  can never offer a control for exactly the life most in need of one.
   *
   *  OPTIONAL, and omitted on purpose by the "continue where you left off"
   *  shortcut: that row exists to get the player back into a life in one tap, and a
   *  destructive control sitting on the resume affordance is a different job on the
   *  same surface. The managed list is where lives are managed. */
  onDelete?: (runId: string) => void
  /** Fold this life into or out of the archived group. Managed-list only. */
  onArchive?: (runId: string, archived: boolean) => void
  /** Give this life a player-chosen name. Managed-list only. */
  onRename?: (runId: string, label: string) => void
}) {
  // The name the player reads: their own label first, then the answer-derived
  // subtitle, then the world's title.
  const name = run.label || run.subtitle || run.title || run.worldId

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const commit = () => { onRename?.(run.runId, draft.trim()); setEditing(false) }

  // On a phone the three row actions wrapped into an ugly stack, so there they
  // collapse into a kebab menu (inline on desktop, unchanged). One list of actions
  // feeds both, so the two renderings can never drift apart.
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!menuOpen) return undefined
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])
  const actions: Array<{ key: string; label: string; aria?: string; onClick: () => void }> = []
  if (onRename) {
    actions.push({
      key: 'rename', label: t('life.rename.short'), aria: t('life.rename.aria', { name }),
      onClick: () => { setDraft(run.label || ''); setEditing(true) },
    })
  }
  if (onArchive) {
    actions.push({
      key: 'archive', label: run.archived ? t('life.unarchive') : t('life.archive'),
      onClick: () => onArchive(run.runId, !run.archived),
    })
  }
  if (onDelete) {
    actions.push({
      key: 'delete', label: t('life.delete.short'), aria: t('life.delete.aria', { name }),
      onClick: () => onDelete(run.runId),
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
          <div className="ew-life-menu" ref={menuRef}>
            <button
              className="ew-kebab"
              type="button"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label={t('life.actions', { name })}
              onClick={() => setMenuOpen((o) => !o)}
            >
              <MenuGlyph />
            </button>
            {menuOpen ? (
              <div className="ew-menu" role="menu">
                {actions.map((a) => (
                  <button
                    key={a.key}
                    className="ew-menu-item"
                    role="menuitem"
                    type="button"
                    aria-label={a.aria}
                    onClick={() => { setMenuOpen(false); a.onClick() }}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  )
}

export function WorldDetailView({
  worldId, onBack, onPlay, onDelete, onLanguage, initialLanguage,
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
  const [lore, setLore] = useState(false)
  // The language the player is reading this world in. Starts at the app's chosen
  // language; a pick from the toggle re-fetches the variant so labels AND lore
  // switch together, which is the whole point of the choice.
  const [language, setLanguage] = useState<string | undefined>(initialLanguage)

  useEffect(() => {
    let alive = true
    setWorld(null)
    setError(null)
    // Ask for the world's own prose too, so the detail page can offer its lore.
    api.world(worldId, true, language)
      .then((w) => { if (alive) { setWorld(w); if (w.language) onLanguage?.(w.language) } })
      .catch((e: Error) => { if (alive) setError(e.message) })
    return () => { alive = false }
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
          <Chip key={g.id} accent={g.worldDecides}>{g.label}</Chip>
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
              <span className="ew-panel-name">{p.id}</span>
              <Chip accent={p.always}>
                {p.always ? t('world.panelAlways') : t('world.panelConditional')}
              </Chip>
              <span style={{ fontSize: '11px', color: 'var(--muted, #6b7280)' }}>
                {t('world.panelFields', { count: p.fields.length })}
              </span>
            </div>
            <div className="ew-chips">
              {p.fields.map((f) => <Chip key={f.id}>{f.label}</Chip>)}
            </div>
          </div>
        ))}
      </div>

      {(world.digest ?? []).length ? (
        <>
          <div className="ew-section">{t('world.digest')}</div>
          <div className="ew-chips ew-block">
            {(world.digest ?? []).map((c) => <Chip key={c}>{c}</Chip>)}
          </div>
        </>
      ) : null}

      <div className="ew-meta">
        {t('world.endings', {
          endings: (world.endings ?? []).length,
          save: (world.save ?? []).length,
        })}
      </div>

      {world.prose ? (
        <>
          <button
            className="ew-section ew-section-toggle"
            type="button"
            style={{ marginTop: '18px' }}
            aria-expanded={lore}
            onClick={() => setLore((v) => !v)}
          >
            {lore ? t('world.loreHide') : t('world.loreShow')}
          </button>
          {lore ? <div className="ew-block"><Prose text={world.prose} /></div> : null}
        </>
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
