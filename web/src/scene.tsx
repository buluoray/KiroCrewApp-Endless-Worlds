import { useEffect, useRef, useState } from 'react'

import { API, api } from './api'
import { t } from './strings'

/** A short, stable token that changes only when the scene's compiled HTML does, so
 *  the iframe `src` reloads on a real content change but NOT on a tab switch or
 *  re-render (which would otherwise reload and lose what the player was looking at). */
function sceneVersion(html: string): string {
  let h = 5381
  for (let i = 0; i < html.length; i++) h = (((h << 5) + h) + html.charCodeAt(i)) | 0
  return (h >>> 0).toString(36)
}

/** What a scene's frame posts back when the player acts. */
interface SceneMessage {
  source?: unknown
  sceneId?: unknown
  nonce?: unknown
  choice?: unknown
}

/**
 * The frame a scene is drawn in.
 *
 * Created on FIRST need and kept for the rest of the session. "Never moved once it
 * exists" is the invariant that protects a mounted scene from reloading — moving an
 * iframe in the DOM reloads it, and a React portal does not help because the
 * browser's rule is about position in the document, not about who rendered it.
 *
 * It never required the element to exist before any scene had been asked for, and
 * mounting it unconditionally put a live browsing context with allow-scripts into
 * the dashboard's own document for every player, including the majority who never
 * see a scene at all.
 */
export function SceneSlot({
  runId, sceneId, asks, visible = true, onChoice, resetSignal = 0, locked = false,
}: {
  runId: string | null
  sceneId: string
  /** Whether this scene asks the player something. An asking scene is scrolled
   *  into view when it mounts, so it is never missed at the foot of a long page. */
  asks?: boolean
  /** Whether the scene's tab is the one on screen. Hidden with display:none (never
   *  unmounted) so switching tabs does not reload the frame. Default true keeps the
   *  desktop, which shows every scene inline, unchanged. */
  visible?: boolean
  onChoice: (sceneId: string, choice: string, nonce: string) => void
  /** Bumped by the parent when a scene answer resolved WITHOUT changing this
   *  scene's html (server refusal, dropped request, or a completed turn that left
   *  the scene as-is). Without it a refused answer locks the slot on "sending…"
   *  forever, because the internal reset only watches [sceneId, html]. */
  resetSignal?: number
  /** True while ANY turn is in flight anywhere (a sibling scene's answer, the
   *  choice buttons, the act box) — taps are ignored so two mounted asking scenes
   *  cannot fire two concurrent turns. */
  locked?: boolean
}) {
  const [everNeeded, setEverNeeded] = useState(false)
  const [html, setHtml] = useState('')
  const [failed, setFailed] = useState(false)
  /** Set the instant the player acts, cleared when the scene changes — so a scene
   *  tap has immediate feedback instead of looking dead for the seconds a turn
   *  takes. (M0.4) */
  const [sending, setSending] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (sceneId) setEverNeeded(true)
  }, [sceneId])

  useEffect(() => {
    if (!runId || !sceneId) {
      setHtml('')
      setFailed(false)
      return
    }
    let alive = true
    api.scene(runId, sceneId)
      .then((text) => {
        if (alive) {
          setHtml(text)
          setFailed(false)
        }
      })
      // A scene that will not compile is not worth a broken page: the turn's words
      // are still there, and the narrator gets told which field to fix.
      .catch(() => {
        if (alive) {
          setHtml('')
          setFailed(true)
        }
      })
    return () => {
      alive = false
    }
  }, [runId, sceneId])

  // First result only, locally too: a double-tap must not become two turns while
  // the server's own refusal is still in flight.
  const answered = useRef(false)
  useEffect(() => {
    answered.current = false
    setSending(false)  // a fresh scene (or an updated one) clears the sending state
  }, [sceneId, html, resetSignal])

  // The lock must be readable inside the message handler without re-subscribing
  // the listener on every turn-state flip.
  const lockedRef = useRef(locked)
  lockedRef.current = locked

  // An asking scene that arrives at the foot of a long page is easy to miss, and
  // there was no feedback that a turn was even in progress. Bring it into view when
  // its picture lands. Display-only scenes (a map, a ledger) do not steal focus. (M0.4)
  useEffect(() => {
    if (html && sceneId && asks) {
      wrapRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [html, sceneId, asks])

  useEffect(() => {
    if (!everNeeded) return undefined
    const onMessage = (e: MessageEvent) => {
      // `origin === 'null'` is a real check, not a formality: the frame has no
      // allow-same-origin, so its origin MUST be the string "null". A message
      // carrying any real origin did not come from our sandbox.
      if (e.origin !== 'null') return
      const d = e.data as SceneMessage | null
      if (!d || d.source !== 'endless-scene') return
      if (d.sceneId !== sceneId) return
      if (typeof d.nonce !== 'string' || !d.nonce) return
      if (typeof d.choice !== 'string' || !d.choice) return
      if (answered.current) return
      if (lockedRef.current) return  // a turn is already in flight somewhere
      answered.current = true
      setSending(true)
      onChoice(sceneId, d.choice, d.nonce)
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [sceneId, onChoice, everNeeded])

  const on = !!(html && sceneId)
  // A scene that has been asked for but whose picture has not arrived yet: say so,
  // rather than leaving a blank slot that reads as broken.
  const loading = !!sceneId && !html && !failed
  // The iframe loads the scene as a real same-origin DOCUMENT via `src` (not
  // `srcdoc`, which blank-rendered on WebKit). The `v` token changes only when the
  // compiled html changes, so the frame reloads on a real content change but not on
  // a tab switch. The fetched `html` above is still what tells us loading vs failed.
  const src = on && runId
    ? `${API}/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}`
      + `?v=${sceneVersion(html)}`
    : undefined

  return (
    <div
      className="ew-slot-wrap"
      ref={wrapRef}
      style={!visible ? { display: 'none' } : on ? undefined : { margin: 0 }}
    >
      {failed && sceneId ? <div className="ew-note">{t('play.sceneFailed')}</div> : null}
      {loading ? (
        <div className="ew-note" role="status" aria-live="polite">{t('play.sceneLoading')}</div>
      ) : null}
      {sending ? (
        <div className="ew-note" role="status" aria-live="polite">{t('play.sceneSending')}</div>
      ) : null}

      {/* Once it exists it is never removed, never re-keyed and never moved — hidden
          with display instead. Before the first scene there is nothing to protect,
          so it is not created at all.

          Loaded via `src` (a real same-origin document), NOT `srcdoc`: WebKit /
          iOS WKWebView blank-render a sandboxed srcdoc frame. The sandbox is
          unchanged — allow-scripts allow-forms, and NEVER allow-same-origin, so the
          document stays null-origin (its postMessage origin is the string "null"
          the handler checks) and cannot reach the dashboard; its CSP travels in the
          document itself. */}
      {everNeeded ? (
        <iframe
          title={t('play.sceneTitle')}
          className={`ew-slot${on ? ' ew-slot-on' : ''}`}
          sandbox="allow-scripts allow-forms"
          src={src}
          allow=""
          referrerPolicy="no-referrer"
        />
      ) : null}
    </div>
  )
}
