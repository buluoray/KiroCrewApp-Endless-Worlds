/** The desktop navigator: worlds and lives, always in view.
 *
 * Why a rail and not a wider column. The shelf, a world's detail, the opening
 * screen and the live turn were all one centred column, which is right on a phone
 * and wasteful on a desktop — not because 900px is too narrow to read (it is about
 * right for prose), but because *navigation* was sharing the reading axis. Opening
 * a world replaced the shelf, so switching between two lives meant going back to
 * a list, and the list itself was the same width as the story.
 *
 * The rail is therefore navigation only. It never shows prose, never grows, and
 * the reading column keeps its measure regardless of how wide the window gets.
 *
 * Below the desktop breakpoint this component renders NOTHING and the shelf works
 * exactly as it did: a phone has no room for a persistent rail, and the existing
 * narrow layout was not a compromise to be undone but the baseline to build on.
 */

import type { LifeRowData, WorldRow } from './api'
import { t } from './strings'

interface RailProps {
  worlds: WorldRow[] | null
  runs: LifeRowData[]
  /** What the main column is showing, so the rail can mark it. */
  activeRunId: string | null
  activeWorldId: string | null
  onWorld: (worldId: string) => void
  onLife: (runId: string) => void
  onHome: () => void
}

/** The same fact as the shelf's row, in the same words.
 *
 * Reusing `life.*` rather than adding `rail.*` twins is deliberate: the rail and
 * the shelf describe the same life, and two phrasings of one state is how a UI
 * starts reading as two different apps. */
function lifeWhere(run: LifeRowData): string {
  if (run.unreadable) return t('life.unreadable')
  if (run.generating) return t('life.generating')
  if (run.ended) return t('life.ended')
  if (run.awaitingOpening) return t('life.unborn')
  return t('life.turn', { turn: run.turn })
}

export function WorldRail({
  worlds, runs, activeRunId, activeWorldId, onWorld, onLife, onHome,
}: RailProps) {
  const playable = (worlds ?? []).filter((w) => w.usable)
  // Unusable worlds are counted but not offered as navigation targets: a row that
  // cannot be opened is a dead end, and the shelf already explains each one.
  const broken = (worlds ?? []).length - playable.length
  // Archived lives are folded away here as on the shelf: the rail is for the lives
  // in play, and the archived group lives on the shelf.
  const shown = runs.filter((r) => !r.archived)

  return (
    <nav className="ew-rail" aria-label={t('rail.label')}>
      <button className="ew-rail-home" type="button" onClick={onHome}>
        {t('rail.shelf')}
      </button>

      {shown.length ? (
        <div className="ew-rail-group">
          <div className="ew-rail-head">{t('library.lives')}</div>
          {shown.map((r) => (
            <button
              key={r.runId}
              type="button"
              disabled={!!r.unreadable}
              className={
                'ew-rail-row' + (r.runId === activeRunId ? ' ew-rail-row-on' : '')
              }
              onClick={() => onLife(r.runId)}
              aria-current={r.runId === activeRunId ? 'page' : undefined}
            >
              <span className="ew-rail-name">
                {r.label || r.subtitle || r.title || r.worldId}
              </span>
              <span className="ew-rail-sub">{lifeWhere(r)}</span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="ew-rail-group">
        <div className="ew-rail-head">{t('rail.worlds')}</div>
        {playable.map((w) => (
          <button
            key={w.worldId}
            type="button"
            className={
              'ew-rail-row'
              + (w.worldId === activeWorldId && !activeRunId ? ' ew-rail-row-on' : '')
            }
            onClick={() => onWorld(w.worldId)}
            aria-current={w.worldId === activeWorldId ? 'page' : undefined}
          >
            <span className="ew-rail-name">{w.title}</span>
            <span className="ew-rail-sub">
              {t('rail.styles', { n: w.styles?.length ?? 0 })}
            </span>
          </button>
        ))}
        {broken > 0 ? (
          <div className="ew-rail-note">{t('rail.broken', { n: broken })}</div>
        ) : null}
      </div>
    </nav>
  )
}
