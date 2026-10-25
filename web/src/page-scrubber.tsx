import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'

import { loadPageIndex } from './page-picker'
import { useScrubPreview, type ScrubStore } from './scrub-store'
import { t } from './strings'

/** Holding an arrow: the first extra page comes after this long… */
export const HOLD_START_MS = 300
/** …and the wait between pages shrinks the longer the arrow is held. */
export function holdInterval(heldMs: number): number {
  if (heldMs < 1200) return 300
  if (heldMs < 2400) return 120
  return 50
}
/** Wheel and keys have no release, so they load once the reader stops for this long. */
export const SCRUB_SETTLE_MS = 350
/** Wheel distance for one page. A notch is one page however far it reports. */
export const WHEEL_STEP_PX = 50

export function clampPage(n: number, latest: number): number {
  return Math.min(latest, Math.max(1, Math.round(n)))
}

/** The page under a pointer at `x` on a rail spanning `left`..`left + width`. */
export function pageAt(x: number, left: number, width: number, latest: number): number {
  if (latest <= 1 || width <= 0) return 1
  return clampPage(1 + ((x - left) / width) * (latest - 1), latest)
}

/** The slider's keys (ARIA slider pattern): arrows ±1, PageUp/PageDown ±10,
 *  Home/End the first and the newest page. `null` for any other key. */
export function scrubKey(key: string, cur: number, latest: number): number | null {
  const step: Record<string, number> = {
    ArrowLeft: -1,
    ArrowDown: -1,
    ArrowRight: 1,
    ArrowUp: 1,
    PageDown: -10,
    PageUp: 10,
  }
  if (key === 'Home') return 1
  if (key === 'End') return latest
  const d = step[key]
  return d === undefined ? null : clampPage(cur + d, latest)
}

/** Fold a wheel delta into the running total: at most one page per event, so a
 *  notch is one page, while a trackpad's small deltas add up to one. */
export function wheelSteps(acc: number): { steps: number; rest: number } {
  if (acc >= WHEEL_STEP_PX) return { steps: 1, rest: 0 }
  if (acc <= -WHEEL_STEP_PX) return { steps: -1, rest: 0 }
  return { steps: 0, rest: acc }
}

/** The pitch, in px, of the page lines drawn on the fore-edge rail: a short life is
 *  a thin book with open lines, a long one a thick book with tight lines. */
export function edgeGap(latest: number): number {
  if (latest < 24) return 6
  if (latest < 72) return 4
  if (latest < 200) return 3
  return 2
}

/** Where on the rail page `n` sits, 0..1. */
function railFrac(n: number, latest: number): number {
  return latest > 1 ? (n - 1) / (latest - 1) : 1
}

/**
 * The scrubber: a slim track with one position per page, drawn as a book's fore-edge
 * with a ribbon bookmark for the thumb and a folio slip for the label. Press and drag
 * and the ribbon, the page indicator and the slip follow the pointer; release loads that
 * one page. Nothing is fetched while dragging — the flipping number lives in the
 * scrub store, which only the thumb, the label and the indicator read, so the story
 * does not re-render per step. The wheel and the keys flip the same way and load
 * once the reader stops.
 */
export function PageScrubber({
  runId,
  shown,
  latest,
  store,
  onCommit,
}: {
  runId: string
  shown: number
  latest: number
  store: ScrubStore
  /** Load this page; the newest one is the live page. */
  onCommit: (n: number) => void
}) {
  const preview = useScrubPreview(store)
  const value = preview ?? shown
  const active = preview !== null
  const track = useRef<HTMLDivElement>(null)
  const rail = useRef<HTMLDivElement>(null)
  const dragId = useRef<number | null>(null)
  const settle = useRef<number | undefined>(undefined)
  const wheelAcc = useRef(0)
  const live = useRef({ shown, latest, onCommit })
  useEffect(() => {
    live.current = { shown, latest, onCommit }
  })

  // The label's few words: the same one small index read the picker makes, made the
  // first time the reader flips, and shared with it.
  const [hints, setHints] = useState<{ key: string; rows: Map<number, string> } | null>(null)
  const hintKey = `${runId}|${latest}`
  useEffect(() => {
    if (!active || hints?.key === hintKey) return undefined
    let alive = true
    loadPageIndex(runId, latest)
      .then((rows) => {
        if (alive) setHints({ key: hintKey, rows })
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [active, hints?.key, hintKey, runId, latest])

  // Release, or the reader stopped: load the ONE page they landed on.
  const finish = useCallback(() => {
    window.clearTimeout(settle.current)
    settle.current = undefined
    wheelAcc.current = 0
    const n = store.get()
    if (n !== null && n !== live.current.shown) live.current.onCommit(n)
    store.set(null)
  }, [store])
  const settleSoon = useCallback(() => {
    window.clearTimeout(settle.current)
    settle.current = window.setTimeout(finish, SCRUB_SETTLE_MS)
  }, [finish])
  useEffect(
    () => () => {
      window.clearTimeout(settle.current)
      store.set(null)
    },
    [store],
  )

  const pointPage = (x: number) => {
    const r = rail.current?.getBoundingClientRect()
    return r ? pageAt(x, r.left, r.width, live.current.latest) : live.current.shown
  }
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    // No text selection, no page scroll; focus stays on the slider for its keys.
    e.preventDefault()
    e.currentTarget.focus({ preventScroll: true })
    e.currentTarget.setPointerCapture(e.pointerId)
    dragId.current = e.pointerId
    window.clearTimeout(settle.current)
    store.set(pointPage(e.clientX))
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (dragId.current !== e.pointerId) return
    store.set(pointPage(e.clientX))
  }
  const onPointerEnd = (e: PointerEvent<HTMLDivElement>) => {
    if (dragId.current !== e.pointerId) return
    dragId.current = null
    finish()
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return
    const next = scrubKey(e.key, store.get() ?? shown, latest)
    if (next === null) return
    // Claimed, so the play page's own Left/Right/Home/End paging stays out of it.
    e.preventDefault()
    store.set(next)
    settleSoon()
  }

  // The wheel needs a non-passive listener to keep the page from scrolling under it.
  useEffect(() => {
    const el = track.current
    if (!el) return undefined
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1
      const d = (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) * unit
      const { steps, rest } = wheelSteps(wheelAcc.current + d)
      wheelAcc.current = rest
      if (steps) {
        const { shown: cur, latest: last } = live.current
        store.set(clampPage((store.get() ?? cur) + steps, last))
      }
      settleSoon()
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [store, settleSoon])

  const frac = railFrac(value, latest)
  const at = `calc(8px + (100% - 16px) * ${frac})`
  const hint = hints?.key === hintKey ? (hints.rows.get(value) ?? '') : ''
  return (
    <div className="ew-scrub">
      <div
        ref={track}
        className={'ew-scrub-track' + (active ? ' ew-scrub-on' : '')}
        role="slider"
        tabIndex={0}
        aria-label={t('play.scrubLabel')}
        aria-orientation="horizontal"
        aria-valuemin={1}
        aria-valuemax={latest}
        aria-valuenow={value}
        aria-valuetext={t('play.scrubValue', { n: value, total: latest })}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onLostPointerCapture={onPointerEnd}
        onKeyDown={onKeyDown}
      >
        <div
          ref={rail}
          className="ew-scrub-rail"
          aria-hidden="true"
          style={{ '--ew-edge-gap': `${edgeGap(latest)}px` } as CSSProperties}
        >
          <div className="ew-scrub-fill" style={{ width: `${frac * 100}%` }} />
        </div>
        {/* The ribbon bookmark: drawing only. The slider's role, values and focus
            stay on the track around it. */}
        <div className="ew-scrub-thumb" aria-hidden="true" style={{ left: at }}>
          <span className="ew-scrub-ribbon" />
        </div>
      </div>
      {active ? (
        <div
          className="ew-scrub-tip"
          aria-hidden="true"
          style={{ left: at, transform: `translateX(${-frac * 100}%)` }}
        >
          <span className="ew-scrub-tip-n">
            {t('play.pageOf', { n: value, total: latest })}
            {value === latest ? ` · ${t('play.jumpNow')}` : null}
          </span>
          {hint ? <span className="ew-scrub-tip-hint">{hint}</span> : null}
        </div>
      ) : null}
    </div>
  )
}

/**
 * Prev/Next that keep flipping while held, faster the longer the hold. A click (or
 * Enter) is still one page. While held, only the scrub store moves — the indicator
 * and the scrubber follow it — and release loads the one page it stopped on.
 */
export function HoldArrow({
  dir,
  shown,
  latest,
  store,
  onCommit,
  disabled,
  label,
  children,
}: {
  dir: -1 | 1
  shown: number
  latest: number
  store: ScrubStore
  onCommit: (n: number) => void
  disabled: boolean
  label: string
  children: ReactNode
}) {
  const timer = useRef<number | undefined>(undefined)
  const held = useRef<{ start: number; n: number } | null>(null)
  const swallowClick = useRef(false)
  const live = useRef({ shown, latest, onCommit })
  useEffect(() => {
    live.current = { shown, latest, onCommit }
  })

  const stop = () => {
    window.clearTimeout(timer.current)
    timer.current = undefined
    const h = held.current
    held.current = null
    if (!h || store.get() === null) return
    // It flipped: this release is the jump, and the click that follows is not.
    swallowClick.current = true
    window.setTimeout(() => {
      swallowClick.current = false
    }, 0)
    if (h.n !== live.current.shown) live.current.onCommit(h.n)
    store.set(null)
  }
  const tick = () => {
    const h = held.current
    if (!h) return
    const next = clampPage(h.n + dir, live.current.latest)
    if (next !== h.n) {
      h.n = next
      store.set(next)
    }
    timer.current = window.setTimeout(tick, holdInterval(performance.now() - h.start))
  }
  useEffect(
    () => () => {
      window.clearTimeout(timer.current)
      if (held.current) store.set(null)
    },
    [store],
  )

  return (
    <button
      className="ew-pager-arw ew-pager-hold"
      type="button"
      disabled={disabled}
      aria-label={label}
      onPointerDown={(e) => {
        if (e.button !== 0 || disabled) return
        swallowClick.current = false
        held.current = { start: performance.now(), n: shown }
        e.currentTarget.setPointerCapture(e.pointerId)
        timer.current = window.setTimeout(tick, HOLD_START_MS)
      }}
      onPointerUp={stop}
      onPointerCancel={stop}
      onLostPointerCapture={stop}
      onContextMenu={(e) => e.preventDefault()}
      onClick={() => {
        if (swallowClick.current) {
          swallowClick.current = false
          return
        }
        onCommit(clampPage(shown + dir, latest))
      }}
    >
      {children}
    </button>
  )
}
