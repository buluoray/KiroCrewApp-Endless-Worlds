/** The desktop navigator: worlds and lives, one click away.
 *
 * Why a rail and not a wider column. The shelf, a world's detail, the opening
 * screen and the live turn were all one centred column, which is right on a phone
 * and wasteful on a desktop — not because 900px is too narrow to read (it is about
 * right for prose), but because *navigation* was sharing the reading axis. Opening
 * a world replaced the shelf, so switching between two lives meant going back to
 * a list, and the list itself was the same width as the story.
 *
 * Why it is now a drawer rather than a permanent column. A permanent 248px of names
 * beside a story is navigation charging rent on every page: it is read once when you
 * switch lives and ignored for the hours in between. So it opens from the same
 * top-left slot the phone puts "back to the shelf" in, closes on the first thing you
 * pick, and the reading column keeps the whole width the rest of the time.
 *
 * It opens IN FLOW, pushing the story right, and is never a viewport-fixed overlay.
 * That is not a style preference: this app is mounted inside the dashboard's own
 * content region, which is itself offset right by the dashboard's sidebar, so a
 * panel positioned at `left: 0` of the VIEWPORT lands outside the area the app can
 * be seen in — drawn, but somewhere the reader cannot look.
 *
 * It never shows prose and never grows.
 *
 * Below the desktop breakpoint this component renders NOTHING and the shelf works
 * exactly as it did: a phone has no room for a rail of any kind, and the existing
 * narrow layout was not a compromise to be undone but the baseline to build on.
 */

import { useEffect } from 'react'

import type { LifeRowData, WorldRow } from './api'
import { t } from './strings'

/** How wide the story is allowed to be.
 *
 * `fixed` caps it at a reading measure regardless of the monitor; `fluid` gives it
 * the window. The cap is the better default for prose and the reason it is not the
 * only option is that it is not the reader's monitor — someone reading on a 27"
 * screen at arm's length is entitled to more words per line than the measure a
 * paperback settled on. */
export type ReadWidth = 'fluid' | 'fixed'

interface RailProps {
  worlds: WorldRow[] | null
  runs: LifeRowData[]
  /** What the main column is showing, so the rail can mark it. */
  activeRunId: string | null
  activeWorldId: string | null
  onWorld: (worldId: string) => void
  onLife: (runId: string) => void
  onHome: () => void
  /** True when the shelf itself is what the main column shows — the rail's own
   *  "home" is then a control that goes nowhere, so it is hidden. */
  atShelf: boolean
  /** Drawer state. The reader can close the shelf for more reading room and open
   *  it when they want to switch; the choice is remembered. */
  open: boolean
  onClose: () => void
  width: ReadWidth
  onWidth: (width: ReadWidth) => void
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
  worlds, runs, activeRunId, activeWorldId, onWorld, onLife, onHome, atShelf,
  open, onClose, width, onWidth,
}: RailProps) {
  // Escape closes it. A drawer that covers the story and can only be dismissed by
  // aiming at a scrim is a trap for anyone reading with the keyboard.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey) }
  }, [open, onClose])

  // Unmounted while closed, not merely hidden: a resize from desktop to phone
  // width would otherwise leave an overlay stranded over the story with its
  // opener gone.
  if (!open) return null

  const playable = (worlds ?? []).filter((w) => w.usable)
  // Unusable worlds are counted but not offered as navigation targets: a row that
  // cannot be opened is a dead end, and the shelf already explains each one.
  const broken = (worlds ?? []).length - playable.length
  // Archived lives are folded away here as on the shelf: the rail is for the lives
  // in play, and the archived group lives on the shelf.
  const shown = runs.filter((r) => !r.archived)

  return (
    <nav className="ew-rail" aria-label={t('rail.label')}>
      <div className="ew-rail-top">
        {atShelf ? <span /> : (
          <button className="ew-rail-home" type="button" onClick={onHome}>
            {t('rail.shelf')}
          </button>
        )}
        <button className="ew-rail-x" type="button" onClick={onClose}>
          {t('rail.close')}
        </button>
      </div>

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

      {/* The reading measure, set where it is reachable from every page. It lives
          here rather than in the home page's settings panel because that panel is
          the NARRATOR's settings (which model writes the story) and is reachable
          only from the shelf — a width you cannot change while reading is a width
          you cannot judge. */}
      <div className="ew-rail-group">
        <div className="ew-rail-head">{t('rail.width')}</div>
        <select
          className="ew-uilang ew-rail-width"
          aria-label={t('rail.width')}
          value={width}
          onChange={(e) => onWidth(e.target.value === 'fixed' ? 'fixed' : 'fluid')}
        >
          <option value="fluid">{t('rail.width.fluid')}</option>
          <option value="fixed">{t('rail.width.fixed')}</option>
        </select>
      </div>
    </nav>
  )
}
