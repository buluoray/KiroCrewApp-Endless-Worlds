/** The phone's bottom navigator: 书页 + the world's system regions + 星图.
 *
 * Narrow-viewport only (the desktop keeps the WorldRail). The bar is `position:
 * fixed` and rendered through a PORTAL to document.body, so it escapes any
 * transformed/containing ancestor in the dashboard shell (which in the AEA iOS
 * WKWebView captured a plain `fixed` and pinned it to the app's content box, not
 * the viewport — the bar then only appeared at the scroll bottom). Its colour is
 * the app background (a soft top fade lifts it off the story text), it hides on
 * scroll-down and returns on scroll-up, and a gold dot marks a tab whose contents
 * changed while the player was reading elsewhere.
 */

import type { JSX } from 'react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import type { PanelView, SceneRow } from './api'
import { t } from './strings'

export type TabKind = 'reading' | 'starmap' | 'region'
export interface WorldTab {
  id: string
  kind: TabKind
  label: string
  /** The scene frames this tab reveals (empty for the two built-in tabs). */
  sceneIds: string[]
}

/** Canonical system regions, in the order they take on the bar. Anything a world
 *  tags with its own word follows these, and untagged scenes fall into one bucket. */
const REGION_ORDER = ['status', 'world', 'pack', 'tasks']
const SYSTEM = 'system'
/** iOS-style ceiling: six tabs fit a phone bar; past this the tail folds into 更多. */
const MAX_VISIBLE = 6

function regionLabel(region: string, labels: string[]): string {
  // Canonical regions use their short bar label (状态/世界/背包/任务); the panel's
  // own longer name still heads its pane. A custom region falls back to whatever
  // label a scene/panel gave it.
  if (region === SYSTEM) return t('tab.system')
  if (REGION_ORDER.includes(region)) return t(`tab.${region}`)
  const named = labels.find((l) => l.trim())?.trim()
  return named || region
}

/** The full ordered tab list for a life: 书页, then the world's system regions
 *  (canonical first, then custom, then the untagged bucket), then 星图. A region
 *  is any region tagged on a PANEL (app-rendered from state) or a mounted SCENE;
 *  both feed the same tab. */
export function buildTabs(scenes: SceneRow[], panels: PanelView[] = []): WorldTab[] {
  const byRegion = new Map<string, { scenes: SceneRow[]; labels: string[] }>()
  const bucket = (key: string) => {
    const b = byRegion.get(key) ?? { scenes: [], labels: [] }
    byRegion.set(key, b)
    return b
  }
  for (const s of scenes) {
    const b = bucket((s.region ?? '').trim() || SYSTEM)
    b.scenes.push(s)
    if ((s.label ?? '').trim()) b.labels.push((s.label ?? '').trim())
  }
  for (const p of panels) {
    const region = (p.region ?? '').trim()
    if (!region) continue  // untagged panels stay in the reading drawer, not a tab
    bucket(region).labels.push(p.label ?? '')
  }
  const present = [...byRegion.keys()]
  const ordered = [
    ...REGION_ORDER.filter((r) => present.includes(r)),
    ...present.filter((r) => !REGION_ORDER.includes(r) && r !== SYSTEM),
    ...(present.includes(SYSTEM) ? [SYSTEM] : []),
  ]
  const regionTabs: WorldTab[] = ordered.map((r) => ({
    id: r,
    kind: 'region',
    label: regionLabel(r, byRegion.get(r)?.labels ?? []),
    sceneIds: (byRegion.get(r)?.scenes ?? []).map((s) => s.sceneId),
  }))
  return [
    { id: 'reading', kind: 'reading', label: t('tab.reading'), sceneIds: [] },
    ...regionTabs,
    { id: 'starmap', kind: 'starmap', label: t('tab.starmap'), sceneIds: [] },
  ]
}

/** Hide on scroll-down, show on scroll-up. Listens in the capture phase so it
 *  catches whichever element actually scrolls — the window in a standalone web
 *  view, or the dashboard's panel div when embedded. */
/** How far the story must scroll before the reading bar is allowed to move.
 *
 *  The bar's own footprint: 60px tall plus the 10px it holds above the title. Below
 *  this the reader has not yet passed the text the bar sits over, so hiding it buys
 *  nothing and only makes it flicker in and out under small swipes. */
export const READER_BAR_PIN_PX = 70

export function useScrollHide(enabled: boolean, pinUntil = 40): boolean {
  const [hidden, setHidden] = useState(false)
  useEffect(() => {
    if (!enabled) {
      setHidden(false)
      return undefined
    }
    let last = -1
    const onScroll = (e: Event) => {
      const tgt = e.target as HTMLElement | Document | null
      const el =
        tgt && tgt instanceof HTMLElement ? tgt : document.scrollingElement
      const y = el ? (el as HTMLElement).scrollTop : window.scrollY || 0
      if (last < 0) { last = y; return }
      const dy = y - last
      if (Math.abs(dy) < 8) return
      // Pinned near the top: the bar is TALLER than a small swipe, so a 40px
      // threshold let it slide away before the reader had passed the text it sits
      // over — and a swipe back down slid it in again, so it flickered in place.
      // Inside this zone it does not move at all; hiding only earns its keep once
      // the reader is genuinely past where the bar sits.
      if (y < pinUntil) setHidden(false)
      else if (dy > 0) setHidden(true)
      else setHidden(false)
      last = y
    }
    window.addEventListener('scroll', onScroll, true)
    return () => window.removeEventListener('scroll', onScroll, true)
  }, [enabled, pinUntil])
  return hidden
}

function icon(tab: WorldTab): JSX.Element {
  return tabIcon(tab.kind === 'region' ? tab.id : tab.kind)
}

/** The glyph for a tab/region id — shared by the phone bottom bar and the desktop
 *  right-aside tab strip so both surfaces read the same. */
export function tabIcon(id: string): JSX.Element {
  switch (id) {
    case 'reading':
      return <svg viewBox="0 0 24 24"><path d="M12 6.5C10.5 5 8 4.5 4 4.7v13c4-.2 6.5.3 8 1.8 1.5-1.5 4-2 8-1.8v-13c-4-.2-6.5.3-8 1.8Z"/><path d="M12 6.5V19"/></svg>
    case 'starmap':
      return <svg viewBox="0 0 24 24"><path d="M12 3.2l1.9 4.4 4.8.4-3.6 3.1 1.1 4.7L12 13.8 7.8 15.8l1.1-4.7L5.3 8l4.8-.4Z"/></svg>
    case 'status':
      return <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.4"/><path d="M5.5 20c.6-3.6 3.2-5.5 6.5-5.5S18.4 16.4 19 20"/></svg>
    case 'world':
      return <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.2"/><path d="M3.8 12h16.4M12 3.8c2.4 2.4 2.4 13.9 0 16.4M12 3.8c-2.4 2.4-2.4 13.9 0 16.4"/></svg>
    case 'pack':
      return <svg viewBox="0 0 24 24"><path d="M7 9V7.5A5 5 0 0 1 17 7.5V9"/><rect x="4.5" y="9" width="15" height="11" rx="2.5"/><path d="M9.5 13h5"/></svg>
    case 'tasks':
      return <svg viewBox="0 0 24 24"><rect x="4.5" y="4.5" width="15" height="15" rx="3"/><path d="M8.5 12.2l2.4 2.4 4.6-5"/></svg>
    default:
      return <svg viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/></svg>
  }
}

function moreIcon(): JSX.Element {
  return <svg viewBox="0 0 24 24"><circle cx="6" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18" cy="12" r="1.6"/></svg>
}

export function WorldTabBar({
  tabs, active, dots, hidden, onSelect,
}: {
  tabs: WorldTab[]
  active: string
  /** tabId → whether it has an unseen change. */
  dots: Record<string, boolean>
  hidden: boolean
  onSelect: (id: string) => void
}) {
  const [moreOpen, setMoreOpen] = useState(false)

  let visible = tabs
  let overflow: WorldTab[] = []
  if (tabs.length > MAX_VISIBLE) {
    visible = tabs.slice(0, MAX_VISIBLE - 1)
    overflow = tabs.slice(MAX_VISIBLE - 1)
  }
  const overflowActive = overflow.some((o) => o.id === active)
  const overflowDot = overflow.some((o) => dots[o.id])

  // Portal to document.body so `position: fixed` resolves against the viewport, not
  // a transformed ancestor in the dashboard shell.
  return createPortal(
    (
    <>
      {moreOpen && overflow.length ? (
        <>
          <button
            className="ew-tabmore-scrim"
            type="button"
            aria-label={t('play.back')}
            onClick={() => setMoreOpen(false)}
          />
          <div className="ew-tabmore" role="menu">
            {overflow.map((o) => (
              <button
                key={o.id}
                className={'ew-tabmore-item' + (o.id === active ? ' on' : '')}
                type="button"
                role="menuitem"
                onClick={() => { onSelect(o.id); setMoreOpen(false) }}
              >
                {icon(o)}<span>{o.label}</span>
                {dots[o.id] ? <i className="ew-tabdot-inline" /> : null}
              </button>
            ))}
          </div>
        </>
      ) : null}

      <nav
        className={'ew-tabbar' + (hidden && !moreOpen ? ' ew-tabbar-hidden' : '')}
        aria-label={t('tab.label')}
      >
        {visible.map((tb) => (
          <button
            key={tb.id}
            className={'ew-tab' + (tb.id === active ? ' on' : '')}
            type="button"
            aria-pressed={tb.id === active}
            onClick={() => { setMoreOpen(false); onSelect(tb.id) }}
          >
            {dots[tb.id] ? <span className="ew-tabdot" /> : null}
            {icon(tb)}
            <span className="ew-tablabel">{tb.label}</span>
          </button>
        ))}
        {overflow.length ? (
          <button
            className={'ew-tab' + (overflowActive ? ' on' : '')}
            type="button"
            aria-expanded={moreOpen}
            onClick={() => setMoreOpen((o) => !o)}
          >
            {overflowDot ? <span className="ew-tabdot" /> : null}
            {moreIcon()}
            <span className="ew-tablabel">{t('tab.more')}</span>
          </button>
        ) : null}
      </nav>
    </>
    ),
    document.body,
  )
}
