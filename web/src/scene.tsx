import { useEffect, useRef, useState } from 'react'

import { api } from './api'
import { t } from './strings'

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
  runId, sceneId, onChoice,
}: {
  runId: string | null
  sceneId: string
  onChoice: (sceneId: string, choice: string, nonce: string) => void
}) {
  const [everNeeded, setEverNeeded] = useState(false)
  const [html, setHtml] = useState('')
  const [full, setFull] = useState(false)
  const [failed, setFailed] = useState(false)

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
  }, [sceneId, html])

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
      answered.current = true
      onChoice(sceneId, d.choice, d.nonce)
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [sceneId, onChoice, everNeeded])

  // Escape leaves fullscreen — a scene blown up to fill the panel needs a keyboard
  // way back out, not only the zoom button.
  useEffect(() => {
    if (!full) return undefined
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setFull(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [full])

  const on = !!(html && sceneId)
  // A scene that has been asked for but whose picture has not arrived yet: say so,
  // rather than leaving a blank slot that reads as broken.
  const loading = !!sceneId && !html && !failed

  return (
    <div className="ew-slot-wrap" style={on ? undefined : { margin: 0 }}>
      {failed && sceneId ? <div className="ew-note">{t('play.sceneFailed')}</div> : null}
      {loading ? (
        <div className="ew-note" role="status" aria-live="polite">{t('play.sceneLoading')}</div>
      ) : null}

      {/* Once it exists it is never removed, never re-keyed and never moved — hidden
          with display instead. Before the first scene there is nothing to protect,
          so it is not created at all.

          The sandbox values are the dashboard's own host values for server-compiled
          content, and allow-same-origin is never granted: with it, srcdoc content
          shares the dashboard's origin and the sandbox stops being one. */}
      {everNeeded ? (
        <iframe
          title={t('play.sceneTitle')}
          className={`ew-slot${full ? ' ew-slot-full' : on ? ' ew-slot-on' : ''}`}
          sandbox="allow-scripts allow-forms"
          srcDoc={html}
          allow=""
          referrerPolicy="no-referrer"
        />
      ) : null}

      {on ? (
        <div className={`ew-slot-bar${full ? ' ew-slot-bar-full' : ''}`}>
          <button className="ew-slot-btn" type="button" onClick={() => setFull((f) => !f)}>
            {full ? t('play.zoomOut') : t('play.zoomIn')}
          </button>
        </div>
      ) : null}
    </div>
  )
}
