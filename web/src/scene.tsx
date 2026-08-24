import { useEffect, useRef, useState } from 'react'

import { API, api } from './api'
import { t } from './strings'

/** What a scene's frame posts back: an answer when the player acts, and its own
 *  content height whenever that changes. */
interface SceneMessage {
  source?: unknown
  sceneId?: unknown
  nonce?: unknown
  choice?: unknown
  height?: unknown
}

/** The band the frame is allowed to occupy, in px. Below the floor a one-line
 *  ledger reads as a rendering failure; above the ceiling a runaway spec would
 *  push the rest of the page out of reach. Between them the frame is exactly as
 *  tall as its picture — no dead band under a short scene, and no map with its
 *  last row clipped off by a frame that was one fixed height for every spec. */
const MIN_SCENE_H = 96
const MAX_SCENE_H = 1400
/** How long a frame may take to report its height before the slot calls it failed.
 *  Generous on purpose: the document is a local request and reports on load, so
 *  seconds of headroom cover a cold instance without ever making a working scene
 *  flash an error. Too short shows a false failure; too long restores the silent
 *  blank frame this exists to prevent. */
const SCENE_RENDER_DEADLINE_MS = 6000

/** A short, stable token that changes only when the scene's compiled HTML does, so
 *  the iframe `src` reloads on a real content change but NOT on a tab switch or
 *  re-render (which would otherwise reload and lose what the player was looking at). */
function sceneVersion(html: string): string {
  let h = 5381
  for (let i = 0; i < html.length; i++) h = ((h << 5) + h + html.charCodeAt(i)) | 0
  return (h >>> 0).toString(36)
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
  runId,
  sceneId,
  asks,
  visible = true,
  onChoice,
  resetSignal = 0,
  locked = false,
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
  /** The frame's own reported content height, clamped. 0 until the first report,
   *  where the stylesheet's fallback height stands in. A later scene keeps the
   *  previous height until its own report lands, so a page turn resizes once
   *  instead of collapsing to the fallback and growing back. */
  const [fitH, setFitH] = useState(0)
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
    api
      .scene(runId, sceneId)
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
    setSending(false) // a fresh scene (or an updated one) clears the sending state
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
      // A height report is not an answer: it carries no choice, arrives whenever
      // the picture's own size changes, and is never gated on the turn lock — a
      // frame must be allowed to resize while a turn is in flight.
      if (typeof d.height === 'number' && Number.isFinite(d.height)) {
        setFitH(Math.min(MAX_SCENE_H, Math.max(MIN_SCENE_H, Math.round(d.height))))
        return
      }
      if (typeof d.choice !== 'string' || !d.choice) return
      if (answered.current) return
      if (lockedRef.current) return // a turn is already in flight somewhere
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
  // How the frame gets its document. Two mechanisms, tried in order, because each
  // one is broken on a surface the other survives and NEITHER is broken on both:
  //
  //   route src — the document is fetched from the scene route. Renders everywhere
  //               the request succeeds, and is the only form that survives a
  //               WebKit-based in-app browser (`blob:` fails its load with "invalid
  //               url or response" and takes the page down; measured on a real
  //               device). Its cost is that the picture depends on a request the app
  //               does NOT make and cannot read: the frame's own document
  //               navigation, authenticated by the browser rather than by us.
  //               Behind an SSO reverse proxy that is decided against us — the
  //               sandbox gives the frame an opaque origin, the proxy's session
  //               cookie is withheld from a request the browser scores as
  //               cross-site, and the proxy answers its own white "sign in" page
  //               instead of our document. The app's `fetch()` of the same URL is
  //               unaffected, so the app holds valid html and believes the scene is
  //               fine while the player looks at a blank sheet.
  //   `srcdoc`  — the bytes the app ALREADY fetched, handed to the frame directly.
  //               Makes no request, so no proxy, cookie policy or embedder can
  //               refuse it. Reported blank-rendering on WebKit / iOS WKWebView,
  //               which is why it is not the primary.
  //
  // So the route is tried first and `srcdoc` is the fallback, switched to by the
  // watchdog below rather than chosen up front: the app cannot detect which surface
  // it is on, but it CAN detect that the frame did not run, and that is the same
  // signal for either cause.
  //
  // The boundary is identical in both forms: the sandbox attribute omits
  // allow-same-origin, so the document keeps an opaque origin and its postMessage
  // origin is the string "null" the handler above checks, and the document's own CSP
  // travels in its `<meta>` — inside the bytes, ahead of every generated byte, so it
  // governs the `srcdoc` form exactly as it governs the served one.
  const [inline, setInline] = useState(false)
  const routeSrc =
    on && runId
      ? `${API}/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}` +
        `?v=${sceneVersion(html)}`
      : undefined
  const src = inline ? undefined : routeSrc

  // A new scene, or new bytes for this one, is a fresh chance for the cheaper form:
  // the fallback is per-document, not a latch on the component. Without this a
  // single refused navigation would keep every later scene on `srcdoc` for the rest
  // of the session, including on surfaces where only the route form renders.
  useEffect(() => {
    setInline(false)
  }, [routeSrc])

  // The watchdog. The frame's document reports its own height as soon as it runs, so
  // a frame that has not reported by the deadline did not render — a proxy's sign-in
  // page, an auth refusal, a JSON body, an embedder that refused the URL. It does not
  // matter which: the answer is the same, hand the frame the bytes we already have.
  // Only when THAT does not run either is the scene genuinely undrawable, and only
  // then does the note replace it. Reporting the first failure to the player was the
  // bug this replaces — the app had the document in hand the whole time.
  //
  // Keyed on the form as well as the deadline's other inputs, so the fallback gets
  // its own full deadline instead of inheriting the elapsed one. Cleared rather than
  // latched, because a slow first paint on a cold instance must not be reported as a
  // failure forever.
  useEffect(() => {
    if (!on || fitH) return undefined
    const timer = setTimeout(
      () => (inline ? setFailed(true) : setInline(true)),
      SCENE_RENDER_DEADLINE_MS,
    )
    return () => clearTimeout(timer)
  }, [on, routeSrc, inline, fitH])

  return (
    <div
      className="ew-slot-wrap"
      ref={wrapRef}
      style={!visible ? { display: 'none' } : on ? undefined : { margin: 0 }}
    >
      {failed && sceneId ? <div className="ew-note">{t('play.sceneFailed')}</div> : null}
      {loading ? (
        <div className="ew-note" role="status" aria-live="polite">
          {t('play.sceneLoading')}
        </div>
      ) : null}
      {sending ? (
        <div className="ew-note" role="status" aria-live="polite">
          {t('play.sceneSending')}
        </div>
      ) : null}

      {/* Once it exists it is never removed, never re-keyed and never moved — hidden
          with display instead. Before the first scene there is nothing to protect,
          so it is not created at all.

          Two document forms on ONE element (see the note on `src` above): the scene
          route first, and the already-fetched bytes as `srcdoc` when the watchdog
          finds the route form did not run. Never `blob:` — it fails the load in a
          WebKit-based in-app browser and takes the page down with it. Swapping the
          attribute rather than the element is what keeps the frame from being
          re-created, so the fallback costs a reload and nothing else.

          The sandbox is unchanged in both forms — allow-scripts allow-forms, and
          NEVER allow-same-origin, so the document stays null-origin (its postMessage
          origin is the string "null" the handler checks) and cannot reach the
          dashboard; its CSP travels in the document itself. */}
      {everNeeded ? (
        <iframe
          title={t('play.sceneTitle')}
          className={`ew-slot${on && !failed ? ' ew-slot-on' : ''}`}
          style={failed ? { display: 'none' } : on && fitH ? { height: `${fitH}px` } : undefined}
          sandbox="allow-scripts allow-forms"
          src={src}
          srcDoc={inline && on ? html : undefined}
          allow=""
          referrerPolicy="no-referrer"
        />
      ) : null}
    </div>
  )
}
