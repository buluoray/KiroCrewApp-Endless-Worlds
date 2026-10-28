import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'

import { useScrubPreview, type ScrubStore } from './scrub-store'
import { t } from './strings'

/** Wheel and keys have no release, so they load once the reader stops for this long. */
export const SCRUB_SETTLE_MS = 350
/** Mouse-wheel distance for one page. A notch is one page however far it reports. */
export const WHEEL_STEP_PX = 50

export function clampPage(n: number, latest: number): number {
  return Math.min(latest, Math.max(1, Math.round(n)))
}

/** The wheel's keys (ARIA slider pattern): arrows ±1, PageUp/PageDown ±10,
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

/** One page number's slot on the wheel. 44px is the touch-target floor (#105). */
export const WHEEL_ITEM_PX = 44
/** How long a flick keeps travelling: the wheel coasts as if its speed decayed with
 *  this time constant, so its resting place is known the moment the finger lifts. */
export const WHEEL_TAU_MS = 325
/** How long a notch or a key slides the drum to the next page. */
export const WHEEL_SLIDE_MS = 140
/** Numbers either side of the centre that are drawn shrinking and fading. */
export const WHEEL_FADE_ITEMS = 4

/** Where a flick comes to rest: the position it would coast to, snapped to the
 *  nearest page and kept on the book. `velocity` is pages per millisecond. */
export function wheelTarget(pos: number, velocity: number, latest: number): number {
  return clampPage(pos + velocity * WHEEL_TAU_MS, latest)
}

/** The drum's speed at release, in pages per millisecond, from the finger's last
 *  ~100ms. A finger that stopped before it lifted throws nothing: it just snaps. */
export function flickVelocity(trail: { t: number; x: number }[], now: number): number {
  const a = trail[0]
  const b = trail[trail.length - 1]
  if (!a || !b || b === a || now - b.t > 80) return 0
  return -((b.x - a.x) / Math.max(1, b.t - a.t)) / WHEEL_ITEM_PX
}

/** The pages to draw for a wheel `widthPx` wide centred on `pos`: only those on
 *  screen plus one each side, so a life of 500 pages draws about ten numbers. */
export function visiblePages(pos: number, widthPx: number, latest: number): [number, number] {
  const half = Math.ceil(widthPx / 2 / WHEEL_ITEM_PX) + 1
  const c = Math.round(pos)
  return [Math.max(1, c - half), Math.min(latest, c + half)]
}

/** How many number slots a wheel `widthPx` wide keeps: the most `visiblePages` can
 *  ever ask for. The slots are made once and reused as the wheel turns, so a swipe
 *  mounts and unmounts nothing. */
export function wheelSlots(widthPx: number): number {
  return 2 * (Math.ceil(widthPx / 2 / WHEEL_ITEM_PX) + 1) + 1
}

/** The slot page `n` is drawn in: a ring, so a step of one page re-labels the one
 *  slot that wrapped around and leaves the other numbers' text alone. */
export function slotOf(n: number, count: number): number {
  return ((n % count) + count) % count
}

/** How a number `d` slots off centre looks: the centre full size and full ink, the
 *  neighbours turning away on the drum, smaller and fainter toward the edges. */
export function wheelLook(d: number): { scale: number; opacity: number; turn: number } {
  const a = Math.min(Math.abs(d), WHEEL_FADE_ITEMS)
  return {
    scale: 1 - a * 0.13,
    opacity: Math.max(0.12, 1 - a * 0.24),
    turn: Math.max(-60, Math.min(60, d * -16)),
  }
}

/** A position dragged past either end gives way, but only a little. */
function rubber(p: number, latest: number): number {
  if (p < 1) return 1 - (1 - p) * 0.3
  if (p > latest) return latest + (p - latest) * 0.3
  return p
}

function reducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    !!window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/**
 * The page picker, on every screen: a row of page numbers printed straight on the top
 * bar, no card behind them, turned like a drum — the iOS time wheel laid on its side.
 * It sits in the top row beside the back link; on a phone it takes whatever width
 * the link leaves, on a wide screen a bounded stretch at the row's end. The centre
 * number is the page; the reader swipes or drags, the numbers follow the pointer,
 * coast and snap to the nearest page, and only when the wheel comes to rest is that
 * ONE page loaded. A mouse wheel or trackpad turns it a page per notch. While it
 * turns, the page number lives in the scrub store, so the story does not re-render.
 *
 * The turning itself is not React's: the drum's position is a ref, and every frame
 * `draw` writes each number's transform and opacity straight onto a fixed set of slots
 * (`wheelSlots`, re-labelled through `slotOf`). React renders the wheel only when the
 * centred PAGE changes (its slider values), never per frame, and a swipe mounts no
 * element, so it never invalidates the page's styles.
 *
 * A tap on the centre number (or Enter) calls `onCentreTap`: the play page opens the
 * type-a-number picker, passed in as `children` and laid over that number.
 *
 * It is a slider for a keyboard and a screen reader — role, values, the slider keys,
 * one announcement on settle.
 */
export function PageWheel({
  shown,
  latest,
  store,
  onCommit,
  onCentreTap,
  children,
}: {
  shown: number
  latest: number
  store: ScrubStore
  /** Load this page; the newest one is the live page. */
  onCommit: (n: number) => void
  /** A tap on the centre number, or Enter: open the type-a-number picker. */
  onCentreTap?: () => void
  /** The picker, drawn over the centre number. */
  children?: ReactNode
}) {
  const preview = useScrubPreview(store)
  const value = preview ?? shown
  const active = preview !== null
  const track = useRef<HTMLDivElement>(null)
  // The drum's fractional position, in pages. A ref, not state: `draw` puts it on
  // screen each frame without a render.
  const posRef = useRef(shown)
  const [width, setWidth] = useState(320)
  const widthRef = useRef(320)
  const slots = useRef<(HTMLSpanElement | null)[]>([])
  const labels = useRef<number[]>([])
  const drag = useRef<{
    id: number
    x0: number
    p0: number
    moved: boolean
    trail: { t: number; x: number }[]
  } | null>(null)
  const anim = useRef<number | undefined>(undefined)
  const settle = useRef<number | undefined>(undefined)
  const wheelAcc = useRef(0)
  const slideRef = useRef<(target: number) => void>(() => {})
  const live = useRef({ shown, latest, onCommit, onCentreTap })
  useEffect(() => {
    live.current = { shown, latest, onCommit, onCentreTap }
  })

  // Put the drum at `p`: every slot's number, turn, size and ink, written directly.
  const draw = useCallback((p: number) => {
    const latest = live.current.latest
    const els = slots.current
    const count = els.length
    const centre = clampPage(p, latest)
    const [first, last] = visiblePages(p, widthRef.current, latest)
    for (let i = 0; i < count; i++) {
      const el = els[i]
      if (!el) continue
      // The page this slot holds in the window, if any: the one n in first..last
      // with slotOf(n) === i.
      const n = first + slotOf(i - first, count)
      if (n > last) {
        el.style.visibility = 'hidden'
        el.classList.remove('ew-wheel-c')
        continue
      }
      if (labels.current[i] !== n) {
        labels.current[i] = n
        // Rewrite the one text node in place: replacing it (textContent) would insert
        // a node, and an insertion re-checks the page's `:has()` rules over the
        // whole app on every page the wheel passes.
        const face = el.firstChild
        if (face) {
          if (face.firstChild) face.firstChild.nodeValue = String(n)
          else face.appendChild(document.createTextNode(String(n)))
        }
      }
      const d = n - p
      const look = wheelLook(d)
      el.style.visibility = ''
      el.style.transform = `translateX(${d * WHEEL_ITEM_PX}px) rotateY(${look.turn}deg) scale(${look.scale})`
      el.style.opacity = String(look.opacity)
      el.classList.toggle('ew-wheel-c', n === centre)
    }
  }, [])

  // At rest the drum shows the page on screen, including after a page lands.
  useLayoutEffect(() => {
    if (drag.current || anim.current !== undefined || store.get() !== null) return
    posRef.current = shown
    draw(shown)
  }, [shown, store, draw])

  useLayoutEffect(() => {
    const el = track.current
    if (!el) return undefined
    const measure = () => {
      widthRef.current = el.clientWidth || 320
      setWidth(widthRef.current)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const place = useCallback(
    (p: number) => {
      posRef.current = p
      draw(p)
      store.set(clampPage(p, live.current.latest))
    },
    [store, draw],
  )
  // The wheel came to rest: load the ONE page it rests on.
  const finish = useCallback(() => {
    window.clearTimeout(settle.current)
    settle.current = undefined
    wheelAcc.current = 0
    const n = store.get()
    if (n !== null) {
      posRef.current = n
      draw(n)
    }
    if (n !== null && n !== live.current.shown) live.current.onCommit(n)
    store.set(null)
  }, [store, draw])
  const settleSoon = useCallback(() => {
    window.clearTimeout(settle.current)
    settle.current = window.setTimeout(finish, SCRUB_SETTLE_MS)
  }, [finish])
  const stopAnim = () => {
    if (anim.current !== undefined) cancelAnimationFrame(anim.current)
    anim.current = undefined
  }
  // Coast to `target` and snap there, easing out like a drum losing speed.
  const glideTo = (target: number) => {
    stopAnim()
    const from = posRef.current
    const dur = Math.min(900, Math.max(160, Math.abs(target - from) * 60))
    if (reducedMotion() || Math.abs(target - from) < 0.001) {
      place(target)
      finish()
      return
    }
    const start = performance.now()
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / dur)
      const e = 1 - Math.pow(1 - k, 3)
      place(from + (target - from) * e)
      if (k < 1) {
        anim.current = requestAnimationFrame(step)
      } else {
        anim.current = undefined
        place(target)
        finish()
      }
    }
    anim.current = requestAnimationFrame(step)
  }
  // A notch or a key: the page is `target` at once (the slider's value, the `>|`
  // mark), and the drum slides there over a few frames instead of jumping a whole
  // number. Drawing only; the one load is still the settle's.
  const slideTo = (target: number) => {
    stopAnim()
    store.set(target)
    const from = posRef.current
    if (reducedMotion() || Math.abs(target - from) < 0.001) {
      posRef.current = target
      draw(target)
      return
    }
    const start = performance.now()
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / WHEEL_SLIDE_MS)
      const e = 1 - Math.pow(1 - k, 3)
      posRef.current = from + (target - from) * e
      draw(posRef.current)
      anim.current = k < 1 ? requestAnimationFrame(step) : undefined
    }
    anim.current = requestAnimationFrame(step)
  }
  useEffect(() => {
    slideRef.current = slideTo
  })
  useEffect(
    () => () => {
      if (anim.current !== undefined) cancelAnimationFrame(anim.current)
      window.clearTimeout(settle.current)
      store.set(null)
    },
    [store],
  )

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    // Focus taken by a press is a pointer's, not the keyboard's: the browser draws
    // this script focus as :focus-visible, so the ring is held back until a key.
    e.currentTarget.dataset.ewPointer = ''
    e.currentTarget.focus({ preventScroll: true })
    e.currentTarget.setPointerCapture(e.pointerId)
    stopAnim()
    window.clearTimeout(settle.current)
    drag.current = {
      id: e.pointerId,
      x0: e.clientX,
      p0: posRef.current,
      moved: false,
      trail: [{ t: performance.now(), x: e.clientX }],
    }
    store.set(clampPage(posRef.current, latest))
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    const dx = e.clientX - d.x0
    if (Math.abs(dx) > 6) d.moved = true
    const now = performance.now()
    d.trail.push({ t: now, x: e.clientX })
    while (d.trail.length > 2 && now - (d.trail[0]?.t ?? now) > 100) d.trail.shift()
    place(rubber(d.p0 - dx / WHEEL_ITEM_PX, live.current.latest))
  }
  const onPointerEnd = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    const last = live.current.latest
    if (!d.moved) {
      // A tap on a neighbour turns the wheel to it; a tap on the centre number opens
      // the type-a-number picker.
      const r = e.currentTarget.getBoundingClientRect()
      const off = (e.clientX - (r.left + r.width / 2)) / WHEEL_ITEM_PX
      if (Math.abs(off) < 0.5 && e.type === 'pointerup') {
        store.set(null)
        live.current.onCentreTap?.()
        return
      }
      glideTo(clampPage(posRef.current + off, last))
      return
    }
    const velocity = e.type === 'pointercancel' ? 0 : flickVelocity(d.trail, performance.now())
    glideTo(wheelTarget(posRef.current, velocity, last))
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    delete e.currentTarget.dataset.ewPointer
    if (e.altKey || e.ctrlKey || e.metaKey) return
    if (e.key === 'Enter' && onCentreTap) {
      e.preventDefault()
      onCentreTap()
      return
    }
    const next = scrubKey(e.key, store.get() ?? shown, latest)
    if (next === null) return
    e.preventDefault()
    slideTo(next)
    settleSoon()
  }

  // A mouse wheel or trackpad over it: one page per notch, loaded on a pause.
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
        slideRef.current(clampPage((store.get() ?? cur) + steps, last))
      }
      settleSoon()
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [store, settleSoon])

  // The slots, made once per width. They carry no number and no style from React:
  // `draw` owns both, so a render (a new centred page) never undoes a frame.
  const count = wheelSlots(width)
  useLayoutEffect(() => {
    slots.current.length = count
    labels.current = []
    draw(posRef.current)
  }, [count, latest, draw])
  const nums = []
  for (let i = 0; i < count; i++) {
    nums.push(
      <span
        key={i}
        className="ew-wheel-n"
        ref={(el) => {
          slots.current[i] = el
        }}
      >
        <span className="ew-wheel-face" />
      </span>,
    )
  }
  return (
    <div className="ew-wheel">
      <div
        ref={track}
        className={'ew-wheel-track' + (active ? ' ew-wheel-on' : '')}
        data-ew-pick-toggle=""
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
        onBlur={(e) => {
          delete e.currentTarget.dataset.ewPointer
        }}
      >
        <div className="ew-wheel-drum" aria-hidden="true">
          {nums}
        </div>
      </div>
      {children}
    </div>
  )
}

/**
 * The `>|` mark at the wheel's end: back to the live page.
 *
 * On the live page it has nowhere to go, so it is hidden — but it keeps its 44px
 * slot (`visibility: hidden`), so the wheel and the back link never shift. Hidden
 * also means out of the tab order and out of the accessibility tree. It reads the
 * wheel's flip preview, so it appears the moment a swipe leaves the latest page,
 * not only once the page lands. Its own subscription: the story does not re-render.
 */
export function WheelLatest({
  shown,
  latest,
  store,
  onLatest,
  children,
}: {
  shown: number
  latest: number
  store: ScrubStore
  onLatest: () => void
  children?: ReactNode
}) {
  const preview = useScrubPreview(store)
  const atLatest = (preview ?? shown) >= latest
  return (
    <button
      className="ew-wheel-latest"
      type="button"
      disabled={atLatest}
      aria-hidden={atLatest ? true : undefined}
      tabIndex={atLatest ? -1 : undefined}
      aria-label={t('play.latestTurn')}
      title={atLatest ? undefined : t('play.latestTurn')}
      onClick={onLatest}
    >
      {children}
    </button>
  )
}
