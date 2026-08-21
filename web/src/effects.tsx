/**
 * Runtime effects for choice buttons — the narrator declares a NAME from the
 * server-validated vocabulary; this module owns the pixels.
 *
 * Why declared-not-drawn: the play page lives in the dashboard DOCUMENT, not a
 * sandboxed iframe, so model-authored CSS/JS can never be mounted here. The
 * split mirrors the backdrop pipeline: the model decides semantics (which
 * effect, what tint), code owns rendering quality. `shimmer`/`aura`/`ripple`
 * are pure CSS (see styles.css); `embers` is the one canvas effect, budgeted
 * hard: ≤24 particles, rAF paused while the tab is hidden, and not mounted at
 * all under prefers-reduced-motion.
 */
import { useEffect, useRef } from 'react'

export type ChoiceEffectName = 'shimmer' | 'aura' | 'embers' | 'ripple'

const CSS_EFFECTS: ReadonlySet<string> = new Set(['shimmer', 'aura', 'ripple'])

export function reducedMotion(): boolean {
  return typeof window !== 'undefined'
    && !!window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** The class list a button gains for a declared effect ('' when none). */
export function effectClass(effect?: string): string {
  if (!effect) return ''
  if (CSS_EFFECTS.has(effect)) return ` ew-fx ew-fx-${effect}`
  if (effect === 'embers') return ' ew-fx'
  return ''
}

const MAX_EMBERS = 24

interface Ember {
  x: number; y: number; r: number; vy: number; vx: number
  life: number; ttl: number
}

/** The canvas half of the effect layer. Renders nothing for CSS effects. */
export function ChoiceEffect({ effect, tint }: { effect?: string; tint?: string }) {
  const ref = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    if (effect !== 'embers' || reducedMotion()) return
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return

    let raf = 0
    let alive = true
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const color = /^#[0-9a-fA-F]{6}$/.test(tint || '') ? (tint as string) : '#e0b64a'
    const embers: Ember[] = []

    const size = () => {
      const rect = canvas.getBoundingClientRect()
      canvas.width = Math.max(1, Math.round(rect.width * dpr))
      canvas.height = Math.max(1, Math.round(rect.height * dpr))
    }
    size()

    const spawn = (): Ember => ({
      x: Math.random() * canvas.width,
      y: canvas.height + 4 * dpr,
      r: (0.8 + Math.random() * 1.6) * dpr,
      vy: (0.12 + Math.random() * 0.25) * dpr,
      vx: (Math.random() - 0.5) * 0.08 * dpr,
      life: 0,
      ttl: 140 + Math.random() * 160,
    })

    const step = () => {
      if (!alive) return
      // Hidden tab: hold the loop without burning frames; resume on the next
      // visibilitychange tick below.
      if (document.hidden) return
      if (embers.length < MAX_EMBERS && Math.random() < 0.35) embers.push(spawn())
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      for (let i = embers.length - 1; i >= 0; i--) {
        const p = embers[i]
        if (!p) continue
        p.life += 1
        p.x += p.vx
        p.y -= p.vy
        const t = p.life / p.ttl
        if (t >= 1 || p.y < -4) { embers.splice(i, 1); continue }
        // Rise bright, fade out through the top third.
        const alpha = t < 0.2 ? t / 0.2 : 1 - (t - 0.2) / 0.8
        ctx.globalAlpha = Math.max(0, alpha * 0.85)
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      raf = requestAnimationFrame(step)
    }

    const onVisibility = () => {
      if (!document.hidden && alive) {
        cancelAnimationFrame(raf)
        raf = requestAnimationFrame(step)
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    raf = requestAnimationFrame(step)

    return () => {
      alive = false
      cancelAnimationFrame(raf)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [effect, tint])

  if (effect !== 'embers' || reducedMotion()) return null
  return <canvas ref={ref} className="ew-fx-embers-canvas" aria-hidden="true" />
}
