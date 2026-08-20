import { useEffect, useState } from 'react'

import { API } from './api'

/**
 * The story's background layer: the narrator-authored SVG, shown as an inert
 * `<img>` behind the story.
 *
 * Accepting the narrator's drawing (the app otherwise never accepts markup) is
 * safe because it is rendered as an IMAGE, not a live document:
 *
 *  - an SVG in an `<img>` runs in a non-scripted context — `<script>` and `on*=`
 *    handlers never execute and external loads are disabled — so the markup cannot
 *    run code or exfiltrate, with or without a sandbox (the backend also strips
 *    those as defense in depth);
 *  - it sits BEHIND the prose with `pointer-events: none` (see `.ew-backdrop` in
 *    styles.css), so a background that draws a fake control cannot be clicked or
 *    cover the real one.
 *
 * This replaced a sandboxed `<iframe srcdoc>` that iOS Safari blank-rendered
 * (showing a flat grey background on iPhone). An image renders and sizes reliably
 * everywhere, and the image context is a stronger boundary than the sandbox was.
 *
 * `version` is the cache-buster: a replaced background loads the new image.
 */
export function Backdrop(
  { runId, version, turn }: { runId: string; version: number; turn?: number },
) {
  // `?turn=` selects the backdrop effective on a PAST page (server resolves it);
  // without it the server serves the latest. `v` is only the cache-buster.
  const q = turn != null ? `?turn=${turn}&v=${version}` : `?v=${version}`
  const src = `${API}/runs/${encodeURIComponent(runId)}/backdrop${q}`

  // Double-buffered swap: the frame currently PAINTED, distinct from the `src` the
  // props are asking for. A new page's backdrop is fetched and decoded off-DOM
  // first, and only promoted here once it is fully drawn — so the current page's
  // background is never torn down for a blank/half-loaded frame while the next
  // image is still loading. The old backdrop holds until the new one is ready.
  const [shownSrc, setShownSrc] = useState<string | null>(null)

  useEffect(() => {
    if (src === shownSrc) return
    let alive = true
    // Preload into the browser cache; the DOM <img> below then paints the already
    // decoded frame with no network gap (same URL = cache hit), so the swap is
    // instant and flash-free.
    const img = new Image()
    img.onload = () => { if (alive) setShownSrc(src) }
    // Keep an already-painted backdrop on error; a first backdrop that never loads
    // just leaves the plain page (the story reads fine without one).
    img.src = src
    return () => { alive = false }
  }, [src, shownSrc])

  // Nothing painted yet: a plain page until the first backdrop finishes loading.
  if (shownSrc == null) return null
  return (
    <div className="ew-backdrop" aria-hidden="true">
      <img
        className="ew-backdrop-frame"
        src={shownSrc}
        alt=""
        draggable={false}
      />
      <div className="ew-backdrop-scrim" />
    </div>
  )
}
