/** The life star map container (design §8.3).
 *
 * Three lenses over ONE payload: switching a lens swaps the layout adapter and
 * nothing else — the fetched graph, the selected node, the filters and the
 * detail panel all survive the switch (§12.4). The last-used lens is saved per
 * life on the server; the entry point only chooses the INITIAL lens (§8.3.2).
 *
 * Rendered as a full-screen overlay from the play page rather than a route of
 * its own, and styled by a module-scoped <style> tag: both choices keep this
 * feature's file footprint disjoint from concurrently-edited app files
 * (main.tsx, styles.css) — the container is self-contained by construction.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import type { MemoryView, StarPayload } from './api'
import { api } from './api'
import { Backdrop } from './backdrop'
import {
  ALL_FILTERS,
  mt,
  neighbours,
  nodeById,
  nodeLabel,
  nodeVisible,
  type StarFilters,
} from './memory-state'
import { TimelineLens } from './memory-layouts/timeline'
import { RelationsLens } from './memory-layouts/relations'
import { KeepsakesLens } from './memory-layouts/keepsakes'

const FILTER_KEYS: Array<keyof StarFilters> = [
  'characters',
  'places',
  'groups',
  'objects',
  'threads',
]

export function StarMap({
  runId,
  lang,
  onClose,
  onJumpTurn,
  initialFocus,
  backdrop,
}: {
  runId: string
  lang: string
  onClose: () => void
  /** Jump the play page's pager to a turn; the overlay closes with it. */
  onJumpTurn: (turn: number) => void
  initialFocus?: string
  /** The life's narrator backdrop, shown behind the star map the same way the
   *  play page shows it behind the story. Null = plain panel. */
  backdrop?: { version: number; mobile?: boolean } | null
}) {
  const [payload, setPayload] = useState<StarPayload | null>(null)
  const [lens, setLens] = useState<MemoryView | null>(null)
  const [focus, setFocus] = useState(initialFocus ?? '')
  const [filters, setFilters] = useState<StarFilters>(ALL_FILTERS)
  // Empty, not 'player': who this life is about is a fact the server resolves
  // from the graph (memory_graph.life_centre), so the initial centre must come
  // from the payload rather than be guessed here. Staying empty until the player
  // picks also means a pick is never silently overwritten when the graph reloads.
  const [centre, setCentre] = useState('')
  const [mode, setMode] = useState<'canvas' | 'list'>(() =>
    typeof window !== 'undefined' && window.matchMedia('(max-width: 860px)').matches
      ? 'list'
      : 'canvas',
  )
  const [kept, setKept] = useState<string[]>([])
  // MUST stay above the `if (!payload || !lens) return` early return below: a hook
  // declared after that guard runs only once the payload has loaded, so the render
  // count jumps from N to N+1 and React throws #310 ("rendered more hooks than
  // during the previous render"). All hooks live before the first conditional return.
  const [keepFailed, setKeepFailed] = useState(false)
  const sheet = useRef<HTMLDivElement>(null)

  // The overlay covers the app's panel, not the window, so where the reader is
  // scrolled decides whether they see it at all — and an overlay left behind by the
  // scroll is how the story used to show past its edges. Bring it to the top of the
  // viewport as it opens; that is the one thing viewport-fixed positioning did for
  // free, and the only reason it was ever reached for.
  useEffect(() => {
    sheet.current?.scrollIntoView({ block: 'start' })
  }, [])

  const load = useCallback(async () => {
    const got = await api.star(runId)
    setPayload(got)
    // The saved lens wins on a plain entry; an entry that named a focus is a
    // smart entry and may pre-select, but never lock, the lens (§8.3.2).
    setLens((cur) => cur ?? got.view)
  }, [runId])
  useEffect(() => {
    void load()
  }, [load])

  const pick = (next: MemoryView) => {
    setLens(next)
    // Fire-and-forget: remembering the lens must never block using it.
    void api.setMemoryView(runId, next).catch(() => {})
  }

  if (!payload || !lens) {
    return (
      <div className="ews-overlay" ref={sheet} role="dialog" aria-modal="true">
        <StarStyles />
        {backdrop ? (
          <Backdrop runId={runId} version={backdrop.version} mobile={backdrop.mobile} />
        ) : null}
        <div className="ews-head">
          <button className="ews-btn" type="button" onClick={onClose}>
            {mt(lang, 'star.close')}
          </button>
        </div>
      </div>
    )
  }

  const focused = focus ? nodeById(payload, focus) : undefined
  const isKept = focused
    ? kept.includes(focused.id) || payload.keepsakes.some((kp) => kp.cites.includes(focused.id))
    : false

  const keep = async () => {
    if (!focused || focused.kind !== 'event') return
    setKeepFailed(false)
    try {
      await api.createKeepsake(runId, {
        kind: 'event',
        title: focused.title ?? mt(lang, 'star.keeps.newTitle'),
        cites: [focused.id],
      })
      setKept((k) => [...k, focused.id])
      await load()
    } catch {
      // Without this the promise rejected unhandled and the tap looked inert:
      // no "kept" mark, no error. Name the failure so the button reads as
      // retryable.
      setKeepFailed(true)
    }
  }

  return (
    <div
      className="ews-overlay"
      ref={sheet}
      role="dialog"
      aria-modal="true"
      aria-label={mt(lang, 'star.title')}
    >
      <StarStyles />
      {backdrop ? (
        <Backdrop runId={runId} version={backdrop.version} mobile={backdrop.mobile} />
      ) : null}
      <div className="ews-head">
        <div className="ews-title">{mt(lang, 'star.title')}</div>
        {/* The lens switcher is always visible and never locked (§8.3.2). */}
        <div className="ews-lenses" role="tablist">
          {(['life', 'people', 'keepsakes'] as const).map((v) => (
            <button
              className={'ews-lens' + (lens === v ? ' ews-lens-on' : '')}
              type="button"
              role="tab"
              aria-selected={lens === v}
              key={v}
              onClick={() => pick(v)}
            >
              {mt(lang, `star.lens.${v}`)}
            </button>
          ))}
        </div>
        <button className="ews-btn" type="button" onClick={onClose}>
          {mt(lang, 'star.close')}
        </button>
      </div>

      <div className="ews-toolbar">
        {FILTER_KEYS.map((key) => (
          <label className="ews-filter" key={key}>
            <input
              type="checkbox"
              checked={filters[key]}
              onChange={() => setFilters((f) => ({ ...f, [key]: !f[key] }))}
            />
            {mt(lang, `star.filter.${key}`)}
          </label>
        ))}
        {lens === 'people' ? (
          <button
            className="ews-btn ews-mode"
            type="button"
            onClick={() => setMode((m) => (m === 'canvas' ? 'list' : 'canvas'))}
          >
            {mt(lang, mode === 'canvas' ? 'star.mode.list' : 'star.mode.canvas')}
          </button>
        ) : null}
      </div>

      <div className="ews-body">
        <div className="ews-lens-pane">
          {lens === 'life' ? (
            <TimelineLens
              payload={payload}
              lang={lang}
              focus={focus}
              setFocus={setFocus}
              filters={filters}
            />
          ) : lens === 'people' ? (
            <RelationsLens
              payload={payload}
              lang={lang}
              focus={focus}
              setFocus={setFocus}
              filters={filters}
              centre={centre}
              setCentre={setCentre}
              mode={mode}
            />
          ) : (
            <KeepsakesLens
              runId={runId}
              payload={payload}
              lang={lang}
              focus={focus}
              setFocus={setFocus}
              onChanged={() => void load()}
            />
          )}
        </div>

        {/* One detail panel for all three lenses (§8.3.3): the selection made
            in any layout reads identically in every other. */}
        {focused ? (
          <div className="ews-detail" role="complementary" aria-live="polite">
            <div className="ews-detail-name">{nodeLabel(focused)}</div>
            {focused.kind === 'event' ? (
              <>
                <div className="ews-detail-meta">
                  {mt(lang, 'star.detail.turn', { n: focused.turn ?? 0 })}
                  {focused.summary ? ` · ${focused.summary}` : ''}
                </div>
                {focused.action ? (
                  <div className="ews-detail-meta">
                    {mt(lang, 'star.detail.action')}: {focused.action}
                  </div>
                ) : null}
                <div className="ews-detail-actions">
                  <button
                    className="ews-btn"
                    type="button"
                    onClick={() => onJumpTurn(focused.turn ?? 1)}
                  >
                    {mt(lang, 'star.detail.jump')}
                  </button>
                  <button
                    className="ews-btn"
                    type="button"
                    disabled={isKept}
                    onClick={() => void keep()}
                  >
                    {mt(lang, isKept ? 'star.keep.kept' : 'star.keep.this')}
                  </button>
                  {keepFailed ? (
                    <span className="ews-detail-meta" role="alert">
                      {mt(lang, 'star.keep.failed')}
                    </span>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="ews-detail-meta">
                {focused.summary || (focused.aliases ?? []).join(' · ')}
                {focused.kind === 'thread'
                  ? ` · ${mt(lang, focused.open ? 'star.detail.thread.open' : 'star.detail.thread.done')}`
                  : ''}
              </div>
            )}
            <div className="ews-detail-related">
              <span className="ews-kp-cites-label">{mt(lang, 'star.detail.related')}</span>
              {neighbours(payload, focused.id)
                .filter((n) => nodeVisible(n, filters))
                .map((n) => (
                  <button
                    className={'ews-chip ews-chip-' + n.kind}
                    type="button"
                    key={n.id}
                    onClick={() => setFocus(n.id)}
                  >
                    {nodeLabel(n)}
                  </button>
                ))}
            </div>
          </div>
        ) : null}
      </div>
      <div className="ews-foot">{mt(lang, 'star.hint')}</div>
    </div>
  )
}

/** Module-scoped styles, injected with the overlay and gone with it. */
function StarStyles() {
  return <style>{CSS_TEXT}</style>
}

const CSS_TEXT = `
.ews-overlay {
  /* Absolute, NOT fixed. It is still the same overlay over the same play page —
     only its BOX changes: fixed resolved against the WINDOW, so it painted over the
     dashboard's own chrome, its left menu included. Anchored to .ew-root (the app's
     positioning box) it covers the app and nothing outside it. The open handler
     scrolls it to the top of the viewport, which is what fixed was doing for free
     and why absolute alone once let the story show past it. */
  position: absolute; inset: 0; min-height: 100%; z-index: 60;
  display: flex; flex-direction: column;
  background: var(--bg, #14151f); color: var(--text, #e2e8f0); overflow: hidden;
}
/* When a life backdrop is mounted it sits at z-index 0 inside the overlay (same
 * as .ew-backdrop at the root); lift every other child above it so the map reads
 * over the backdrop instead of under it. */
.ews-overlay > *:not(.ew-backdrop) { position: relative; z-index: 1; }
.ews-head {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px;
  border-bottom: 1px solid var(--border, #2d2f3d);
}
.ews-title { font-weight: 600; }
.ews-lenses { display: flex; gap: 4px; margin-inline: auto; }
.ews-lens {
  appearance: none; border: 1px solid var(--border, #2d2f3d); background: none;
  color: inherit; font: inherit; padding: 5px 14px; border-radius: 999px; cursor: pointer;
}
.ews-lens-on {
  border-color: var(--accent, #7c3aed);
  background: color-mix(in oklab, var(--accent, #7c3aed) 18%, transparent);
}
.ews-btn {
  appearance: none; border: 1px solid var(--border, #2d2f3d); background: none;
  color: inherit; font: inherit; font-size: 13px; padding: 5px 12px;
  border-radius: 8px; cursor: pointer;
}
.ews-btn:disabled { opacity: 0.5; cursor: default; }
.ews-btn-danger { border-color: #b91c1c; color: #f87171; }
.ews-toolbar {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  padding: 8px 16px; border-bottom: 1px solid var(--border, #2d2f3d); font-size: 13px;
}
.ews-filter { display: inline-flex; gap: 5px; align-items: center; cursor: pointer; }
/* Native checkboxes render the browser's blue check; paint them with the app's
 * accent (the same colour the lens tabs and chips use) so they match the rest of
 * the crew UI instead of clashing with a stray blue. */
.ews-filter input[type="checkbox"] { accent-color: var(--accent, #7c3aed); }
.ews-mode { margin-inline-start: auto; }
.ews-body { flex: 1; display: flex; min-height: 0; }
.ews-lens-pane { flex: 1; overflow: auto; padding: 16px; }
.ews-detail {
  flex: 0 0 300px; overflow: auto; padding: 14px 16px;
  border-inline-start: 1px solid var(--border, #2d2f3d);
}
.ews-detail-name { font-weight: 600; margin-bottom: 6px; }
.ews-detail-meta { font-size: 13px; line-height: 1.6; color: var(--muted, #9ca3af); margin-bottom: 6px; }
.ews-detail-actions { display: flex; gap: 8px; margin: 8px 0; }
.ews-detail-related { display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; }
.ews-foot {
  padding: 6px 16px 10px; font-size: 12px; color: var(--muted, #6b7280);
  border-top: 1px solid var(--border, #2d2f3d);
}
.ews-empty { padding: 40px 20px; text-align: center; color: var(--muted, #9ca3af); line-height: 1.8; }
.ews-node {
  appearance: none; border: 0; background: none; color: inherit; font: inherit;
  text-align: start; cursor: pointer; padding: 2px 4px; border-radius: 6px;
}
.ews-node-sel { background: color-mix(in oklab, var(--accent, #7c3aed) 22%, transparent); }
.ews-chip {
  appearance: none; border: 1px solid var(--border, #2d2f3d); background: none;
  color: inherit; font: inherit; font-size: 12px; padding: 2px 10px;
  border-radius: 999px; cursor: pointer;
}
.ews-chip-sel, .ews-chip:hover { border-color: var(--accent, #7c3aed); }
.ews-chip-thread { border-style: dashed; }
.ews-echo-ref {
  appearance: none; border: 0; background: none; cursor: pointer; display: block;
  font: inherit; font-size: 12px; font-style: italic; color: var(--accent, #7c3aed);
  padding: 1px 4px; text-align: start;
}
/* 时间星座 */
.ews-timeline { max-width: 640px; }
.ews-tl-row { display: flex; gap: 12px; }
.ews-tl-spine {
  flex: 0 0 14px; display: flex; justify-content: center; position: relative;
}
.ews-tl-spine::before {
  content: ""; position: absolute; top: 0; bottom: 0; width: 2px;
  background: var(--border, #2d2f3d);
}
.ews-tl-dot {
  position: relative; z-index: 1; width: 10px; height: 10px; border-radius: 50%;
  margin-top: 8px; background: var(--muted, #6b7280);
}
.ews-tl-dot-major { width: 14px; height: 14px; background: var(--accent, #7c3aed); }
.ews-tl-dot-sel { outline: 3px solid color-mix(in oklab, var(--accent, #7c3aed) 40%, transparent); }
.ews-tl-body { flex: 1; padding-bottom: 18px; min-width: 0; }
.ews-tl-turn { font-size: 12px; color: var(--muted, #9ca3af); margin-inline-end: 8px; }
.ews-tl-title { font-weight: 500; }
.ews-tl-cluster { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
/* 关系轨道 */
.ews-centre-row {
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 10px;
  font-size: 13px;
}
.ews-centre-label { color: var(--muted, #9ca3af); }
.ews-canvas { width: 100%; max-width: 640px; height: auto; display: block; margin: 0 auto; }
.ews-orbit { fill: none; stroke: var(--border, #2d2f3d); stroke-dasharray: 3 5; }
.ews-rel-line { stroke: color-mix(in oklab, var(--accent, #7c3aed) 45%, transparent); }
.ews-star { cursor: pointer; }
.ews-star circle { fill: var(--card, #1f2030); stroke: var(--border, #2d2f3d); stroke-width: 1.5; }
.ews-star-centre circle, .ews-star-sel circle { stroke: var(--accent, #7c3aed); stroke-width: 2.5; }
.ews-star text { fill: var(--text, #e5e7eb); font-size: 12px; }
.ews-rel-list { display: flex; flex-direction: column; gap: 10px; max-width: 640px; }
.ews-rel-row {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline;
  padding: 8px 10px; border: 1px solid var(--border, #2d2f3d); border-radius: 10px;
}
.ews-rel-kind { font-size: 13px; color: var(--muted, #9ca3af); }
.ews-rel-srcs { font-size: 12px; display: inline-flex; gap: 4px; align-items: baseline; }
/* 纪念地图 */
.ews-kp-map { display: flex; flex-direction: column; gap: 14px; max-width: 640px; }
.ews-kp {
  padding: 12px 14px; border: 1px solid var(--border, #2d2f3d); border-radius: 12px;
}
.ews-kp-hot { border-color: var(--accent, #7c3aed); }
.ews-kp-title { font-weight: 600; margin-bottom: 4px; }
.ews-kp-title-edit, .ews-kp-thought-edit {
  width: 100%; font: inherit; color: inherit; background: none;
  border: 1px solid var(--border, #2d2f3d); border-radius: 8px; padding: 6px 8px;
  margin-bottom: 6px;
}
.ews-kp-excerpt {
  margin: 6px 0; padding: 6px 10px; font-size: 13px; line-height: 1.7;
  border-inline-start: 3px solid var(--accent, #7c3aed);
  color: var(--muted, #c4c7d0);
}
.ews-kp-excerpt-src { font-size: 11px; margin-top: 4px; color: var(--muted, #6b7280); }
.ews-kp-thought { font-size: 13px; line-height: 1.6; margin-bottom: 6px; }
.ews-kp-cites { display: flex; flex-wrap: wrap; gap: 5px; align-items: baseline; margin: 6px 0; }
.ews-kp-cites-label { font-size: 12px; color: var(--muted, #9ca3af); }
.ews-kp-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 6px; }
.ews-kp-ask { font-size: 12px; color: var(--muted, #9ca3af); }
/* Observatory composition: the narrator's art remains the room, while controls
 * become local frosted instruments instead of an opaque application shell. The
 * horizontal shade protects labels from either a bright or dark backdrop without
 * flattening the whole image to one grey value. */
.ews-overlay:has(> .ew-backdrop) { background: transparent; }
.ews-overlay:has(> .ew-backdrop)::after {
  content: ""; position: absolute; inset: 0; z-index: 1; pointer-events: none;
  background:
    linear-gradient(90deg,
      color-mix(in srgb, var(--bg, #14151f) 68%, transparent),
      color-mix(in srgb, var(--bg, #14151f) 16%, transparent) 58%,
      color-mix(in srgb, var(--bg, #14151f) 42%, transparent)),
    linear-gradient(to bottom,
      color-mix(in srgb, var(--bg, #14151f) 12%, transparent),
      color-mix(in srgb, var(--bg, #14151f) 30%, transparent));
}
.ews-overlay > *:not(.ew-backdrop) { z-index: 2; }
.ews-head,
.ews-toolbar,
.ews-lens-pane,
.ews-detail,
.ews-foot {
  border: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 82%, transparent);
  background: color-mix(in srgb, var(--card, #1f2030) 72%, transparent);
  -webkit-backdrop-filter: blur(18px) saturate(1.08);
  backdrop-filter: blur(18px) saturate(1.08);
  box-shadow: 0 18px 48px color-mix(in srgb, var(--bg, #14151f) 28%, transparent);
}
.ews-head {
  margin: 12px 16px 0; padding: 10px 12px; border-radius: 14px;
}
.ews-title { letter-spacing: .01em; }
.ews-lenses {
  padding: 3px; border: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 76%, transparent);
  border-radius: 999px; background: color-mix(in srgb, var(--bg, #14151f) 28%, transparent);
}
.ews-lens {
  border-color: transparent; padding: 6px 16px;
  transition: color .16s ease, background .16s ease, border-color .16s ease;
}
.ews-lens-on {
  color: var(--text, #e5e7eb); border-color: color-mix(in srgb, var(--accent, #7c3aed) 46%, transparent);
  background: color-mix(in srgb, var(--accent, #7c3aed) 20%, transparent);
}
.ews-btn,
.ews-chip {
  background: color-mix(in srgb, var(--card, #1f2030) 50%, transparent);
  -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
}
.ews-btn:hover:not(:disabled),
.ews-chip:hover {
  border-color: color-mix(in srgb, var(--accent, #7c3aed) 72%, var(--border, #2d2f3d));
  background: color-mix(in srgb, var(--accent, #7c3aed) 12%, transparent);
}
.ews-toolbar {
  margin: 8px 16px 0; padding: 7px 10px; gap: 7px; border-radius: 12px;
  box-shadow: none;
}
.ews-filter {
  padding: 5px 9px; border: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 74%, transparent);
  border-radius: 999px; background: color-mix(in srgb, var(--card, #1f2030) 46%, transparent);
}
.ews-filter:has(input:checked) {
  border-color: color-mix(in srgb, var(--accent, #7c3aed) 50%, var(--border, #2d2f3d));
  background: color-mix(in srgb, var(--accent, #7c3aed) 10%, transparent);
}
.ews-body { gap: 14px; padding: 14px 16px 16px; }
.ews-lens-pane {
  padding: 16px; border-radius: 16px;
  background: color-mix(in srgb, var(--card, #1f2030) 28%, transparent);
  -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px);
  box-shadow: none;
}
.ews-detail {
  flex-basis: 300px; margin: 0; padding: 17px;
  border-inline-start: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 82%, transparent);
  border-radius: 16px;
}
.ews-detail-name { font-size: 15px; margin-bottom: 8px; }
.ews-detail-meta { color: color-mix(in srgb, var(--text, #e5e7eb) 68%, var(--muted, #9ca3af)); }
.ews-detail-actions { margin: 14px 0; }
.ews-foot {
  margin: 0 16px 10px; padding: 7px 10px; border-radius: 10px;
  color: color-mix(in srgb, var(--text, #e5e7eb) 62%, var(--muted, #6b7280));
  box-shadow: none;
}
.ews-orbit {
  stroke: color-mix(in srgb, var(--accent, #7c3aed) 42%, var(--border, #2d2f3d));
}
.ews-rel-line { stroke: color-mix(in srgb, var(--accent, #7c3aed) 62%, transparent); }
.ews-star circle {
  fill: color-mix(in srgb, var(--card, #1f2030) 78%, transparent);
  stroke: color-mix(in srgb, var(--border, #2d2f3d) 88%, transparent);
}
.ews-star-centre circle,
.ews-star-sel circle {
  filter: drop-shadow(0 0 8px color-mix(in srgb, var(--accent, #7c3aed) 65%, transparent));
}
.ews-kp,
.ews-rel-row {
  background: color-mix(in srgb, var(--card, #1f2030) 58%, transparent);
  -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px);
}
.ews-tl-dot-major {
  box-shadow: 0 0 14px color-mix(in srgb, var(--accent, #7c3aed) 65%, transparent);
}

/* The phone detail is a sheet, not the last row of a long column. Its entrance is
 * the feedback that a star tap did something; anchoring it above the portalled tab
 * bar keeps that feedback in the player's current field of view. */
@keyframes ews-detail-rise {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

/* The portalled bottom bar is rendered through 1100px, including large phones in
 * landscape. In that whole range, raise detail as a sheet and reserve the bar plus
 * the device safe area rather than letting either cover selected-star feedback. */
@media (max-width: 1100px) {
  .ews-body {
    --ews-tab-clearance: calc(74px + env(safe-area-inset-bottom, 0px));
    padding-bottom: var(--ews-tab-clearance);
  }
  .ews-detail {
    position: absolute; inset-inline: 10px; bottom: var(--ews-tab-clearance); z-index: 4;
    box-sizing: border-box; flex: 0 0 auto; max-height: 38dvh; padding: 14px;
    border-inline-start: 1px solid color-mix(in srgb, var(--border, #2d2f3d) 82%, transparent);
    border-top: 2px solid color-mix(in srgb, var(--accent, #7c3aed) 72%, var(--border, #2d2f3d));
    box-shadow: 0 -12px 40px color-mix(in srgb, var(--bg, #14151f) 55%, transparent);
    animation: ews-detail-rise .18s ease-out;
  }
  .ews-foot { display: none; }
}

/* Below 860px the controls also take their compact, single-column form. */
@media (max-width: 860px) {
  .ews-head { margin: 8px 10px 0; padding: 9px 10px; flex-wrap: wrap; gap: 8px; }
  .ews-title { flex: 1; }
  .ews-lenses { order: 3; width: 100%; margin-inline: 0; justify-content: center; }
  .ews-lens { flex: 1; padding-inline: 8px; }
  .ews-toolbar {
    margin: 7px 10px 0; padding: 6px 8px; flex-wrap: nowrap; overflow-x: auto;
    scrollbar-width: none;
  }
  .ews-toolbar::-webkit-scrollbar { display: none; }
  .ews-filter { flex: 0 0 auto; }
  .ews-body {
    flex-direction: column; gap: 8px; padding: 8px 10px var(--ews-tab-clearance);
  }
  .ews-lens-pane { padding: 12px; min-height: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .ews-detail { animation: none; }
}
`
