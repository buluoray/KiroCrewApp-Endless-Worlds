import { useEffect, useState } from 'react'

import type { LifeRowData, OpeningGroup, WorldDetail, WorldRow } from './api'
import { api } from './api'
import { t } from './strings'
import { Chip, Prose } from './ui'

const TURN_UNITS: Record<string, string> = {
  month: 'unit.month', year: 'unit.year', day: 'unit.day',
  week: 'unit.week', season: 'unit.season',
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

  return (
    <button className="ew-card" type="button" onClick={() => onOpen(world.worldId)}>
      <div className="ew-titlerow">
        <span className="ew-title">{world.title}</span>
        {world.lineage ? <Chip accent>{t('world.lineage')}</Chip> : null}
        {world.stale ? <Chip>{t('world.stale')}</Chip> : null}
      </div>
      <div className="ew-chips" style={{ marginBottom: '8px' }}>
        {(world.styles ?? []).map((s) => <Chip key={s}>{s}</Chip>)}
      </div>
      <div className="ew-meta">
        {t('world.summary', {
          groups: world.openingGroups ?? 0,
          panels: world.panelCount ?? 0,
          turn: turnPhrase(world.clockUnit),
        })}
        {world.stalenessNote ? <div style={{ marginTop: '4px' }}>{world.stalenessNote}</div> : null}
        {plays > 0 ? <div style={{ marginTop: '4px' }}>{t('world.plays', { n: plays })}</div> : null}
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
      {onRename ? (
        <button
          className="ew-btn ew-btn-quiet ew-card-drop"
          type="button"
          onClick={() => { setDraft(run.label || ''); setEditing(true) }}
          aria-label={t('life.rename.aria', { name })}
        >
          {t('life.rename.short')}
        </button>
      ) : null}
      {onArchive ? (
        <button
          className="ew-btn ew-btn-quiet ew-card-drop"
          type="button"
          onClick={() => onArchive(run.runId, !run.archived)}
        >
          {run.archived ? t('life.unarchive') : t('life.archive')}
        </button>
      ) : null}
      {onDelete ? (
        <button
          className="ew-btn ew-btn-quiet ew-card-drop"
          type="button"
          onClick={() => onDelete(run.runId)}
          aria-label={t('life.delete.aria', { name })}
        >
          {t('life.delete.short')}
        </button>
      ) : null}
    </div>
  )
}

export function WorldDetailView({
  worldId, onBack, onPlay, onDelete,
}: {
  worldId: string
  onBack: () => void
  onPlay: (world: WorldDetail) => void
  /** Opening the confirmation is the parent's job: the dialog belongs above this
   *  view so it is not unmounted by the very reload that follows a deletion. */
  onDelete: (worldId: string) => void
}) {
  const [world, setWorld] = useState<WorldDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const [lore, setLore] = useState(false)

  useEffect(() => {
    let alive = true
    setWorld(null)
    setError(null)
    // Ask for the world's own prose too, so the detail page can offer its lore.
    api.world(worldId, true)
      .then((w) => { if (alive) setWorld(w) })
      .catch((e: Error) => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [worldId, nonce])

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

      <div className="ew-section">{t('world.opening')}</div>
      <div className="ew-chips ew-block">
        {groups.map((g) => (
          <Chip key={g.id} accent={g.worldDecides}>{g.label}</Chip>
        ))}
      </div>

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
