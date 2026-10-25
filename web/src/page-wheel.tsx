import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react'

import { loadPageIndex } from './page-picker'
import { clampPage, SCRUB_SETTLE_MS, scrubKey, wheelSteps } from './page-scrubber'
import { useScrubPreview, type ScrubStore } from './scrub-store'
import { t } from './strings'

/** One page number's slot on the wheel. 44px is the touch-target floor (#105). */
export const WHEEL_ITEM_PX = 44
/** How long a flick keeps travelling: the wheel coasts as if its speed decayed with
 *  this time constant, so its resting place is known the moment the finger lifts. */
export const WHEEL_TAU_MS = 325
/** Numbers either side of the centre that are drawn shrinking and fading. */
export const WHEEL_FADE_ITEMS = 4
/** The phone layout, where the wheel replaces the fore-edge slider. */
export const PHONE_QUERY = '(max-width: 600px)'

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

/** Whether the play page is in its phone layout, followed live. */
export function usePhoneLayout(): boolean {
  const [phone, setPhone] = useState(
    () =>
      typeof window !== 'undefined' &&
      !!window.matchMedia &&
      window.matchMedia(PHONE_QUERY).matches,
  )
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined
    const mq = window.matchMedia(PHONE_QUERY)
    const on = () => setPhone(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return phone
}

/**
 * The phone's page picker: a row of page numbers on a strip of folio paper, turned
 * like a drum — the iOS time wheel laid on its side. The centre number is the page;
 * the reader swipes, the numbers follow the finger, coast and snap to the nearest
 * page, and only when the wheel comes to rest is that ONE page loaded. While it
 * turns, the page number lives in the scrub store (as for the slider), so the story
 * does not re-render; only this wheel and the page indicator do.
 *
 * Same slider semantics as the desktop scrubber — role, values, keys, one
 * announcement on settle — so a keyboard attached to a phone still works.
 */
export function PageWheel({
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
  // The drum's fractional position, in pages. State so the numbers redraw as it
  // turns; the ref is what the handlers read between renders.
  const [pos, setPosState] = useState(shown)
  const posRef = useRef(shown)
  const [width, setWidth] = useState(320)
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
  const live = useRef({ shown, latest, onCommit })
  useEffect(() => {
    live.current = { shown, latest, onCommit }
  })

  // At rest the drum shows the page on screen, including after a page lands.
  useEffect(() => {
    if (drag.current || anim.current !== undefined || store.get() !== null) return
    posRef.current = shown
    setPosState(shown)
  }, [shown, store])

  useLayoutEffect(() => {
    const el = track.current
    if (!el) return undefined
    const measure = () => setWidth(el.clientWidth || 320)
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // The line under the centre number: the same one small index read the picker and
  // the slider share. Read on mount here, because on a phone the line is always shown.
  const [hints, setHints] = useState<{ key: string; rows: Map<number, string> } | null>(null)
  const hintKey = `${runId}|${latest}`
  useEffect(() => {
    if (hints?.key === hintKey) return undefined
    let alive = true
    loadPageIndex(runId, latest)
      .then((rows) => {
        if (alive) setHints({ key: hintKey, rows })
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [hints?.key, hintKey, runId, latest])

  const place = useCallback(
    (p: number) => {
      posRef.current = p
      setPosState(p)
      store.set(clampPage(p, live.current.latest))
    },
    [store],
  )
  // The wheel came to rest: load the ONE page it rests on.
  const finish = useCallback(() => {
    window.clearTimeout(settle.current)
    settle.current = undefined
    wheelAcc.current = 0
    const n = store.get()
    if (n !== null) {
      posRef.current = n
      setPosState(n)
    }
    if (n !== null && n !== live.current.shown) live.current.onCommit(n)
    store.set(null)
  }, [store])
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
      // A tap on a neighbour turns the wheel to it; a tap on the centre is a no-op.
      const r = e.currentTarget.getBoundingClientRect()
      glideTo(
        clampPage(posRef.current + (e.clientX - (r.left + r.width / 2)) / WHEEL_ITEM_PX, last),
      )
      return
    }
    const velocity = e.type === 'pointercancel' ? 0 : flickVelocity(d.trail, performance.now())
    glideTo(wheelTarget(posRef.current, velocity, last))
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return
    const next = scrubKey(e.key, store.get() ?? shown, latest)
    if (next === null) return
    e.preventDefault()
    stopAnim()
    place(next)
    settleSoon()
  }

  // A mouse wheel or trackpad over it, for a phone-sized window on a desktop.
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
        const n = clampPage((store.get() ?? cur) + steps, last)
        posRef.current = n
        setPosState(n)
        store.set(n)
      }
      settleSoon()
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [store, settleSoon])

  const centre = clampPage(pos, latest)
  const [first, last] = visiblePages(pos, width, latest)
  const nums = []
  for (let n = first; n <= last; n++) {
    const d = n - pos
    const look = wheelLook(d)
    nums.push(
      <span
        key={n}
        className={'ew-wheel-n' + (n === centre ? ' ew-wheel-c' : '')}
        style={{
          transform: `translateX(${d * WHEEL_ITEM_PX}px) rotateY(${look.turn}deg) scale(${look.scale})`,
          opacity: look.opacity,
        }}
      >
        <span className="ew-wheel-face">{n}</span>
      </span>,
    )
  }
  const hint = hints?.key === hintKey ? (hints.rows.get(centre) ?? '') : ''
  return (
    <div className="ew-wheel">
      <div
        ref={track}
        className={'ew-wheel-track' + (active ? ' ew-wheel-on' : '')}
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
        <span className="ew-wheel-ribbon" aria-hidden="true" />
        <div className="ew-wheel-drum" aria-hidden="true">
          {nums}
        </div>
      </div>
      <div className="ew-wheel-hint" aria-hidden="true">
        {hint}
      </div>
    </div>
  )
}
