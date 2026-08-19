import type { ReactNode } from 'react'

import type { PanelView, ShapedField } from './api'
import { t } from './strings'

/**
 * The dashboard's own module map, reached through the window rather than imported.
 *
 * A static `import` of a key an older host's map lacks fails the WHOLE module, so
 * the app would not load at all rather than losing one nicety. Everything here is
 * therefore optional by construction.
 */
interface HostUi {
  MarkdownRenderer?: (props: { content: string; softBreaks?: boolean }) => ReactNode
}

export function hostUi(): HostUi | null {
  try {
    const map = (window as unknown as { __kirocrew_modules?: Record<string, unknown> })
      .__kirocrew_modules
    return (map?.['@kirocrew/ui'] as HostUi | undefined) ?? null
  } catch {
    return null
  }
}

export function Chip({ children, accent }: { children: ReactNode; accent?: boolean }) {
  return <span className={`ew-chip${accent ? ' ew-chip-accent' : ''}`}>{children}</span>
}

/**
 * Narration, rendered as the markdown the narrator writes.
 *
 * Uses the HOST's renderer, and the reason is not convenience: narration is model
 * output, and a renderer of my own would be a new, unaudited path from model bytes
 * to the DOM. The dashboard already renders model markdown in chat through this
 * component, so it is the audited one.
 */
export function Prose({ text }: { text: string }) {
  const Md = hostUi()?.MarkdownRenderer
  if (!text) {
    return <p className="ew-prose ew-prose-plain">{t('play.silent')}</p>
  }
  if (!Md) {
    // Older host: plain text with the line breaks the narrator wrote. Worse than
    // markdown, never worse than unreadable.
    return <p className="ew-prose ew-prose-plain">{text}</p>
  }
  return (
    <div className="ew-prose">
      {/* softBreaks: a line break the narrator wrote is a line break they meant.
          Narration is not documentation, so collapsing single newlines the way
          strict markdown does would run sentences together. */}
      <Md content={text} softBreaks />
    </div>
  )
}

const Bar = ({ pct }: { pct: number }) => (
  <div className="ew-bar-track">
    <div className="ew-bar-fill" style={{ width: `${Math.round(pct * 100)}%` }} />
  </div>
)

const Lines = ({
  entries, primary, secondary,
}: {
  entries: Array<Record<string, unknown>>
  primary: string
  secondary: string
}) => (
  <ul className="ew-list">
    {entries.map((e, i) => (
      <li key={`${String(e[primary] ?? '')}-${i}`}>
        {String(e[primary] ?? '')}
        {e[secondary] ? <span className="ew-sub">{` — ${String(e[secondary])}`}</span> : null}
      </li>
    ))}
  </ul>
)

/**
 * One field, drawn by its PRIMITIVE alone.
 *
 * There is deliberately no branch on a field's id anywhere below: a world gets its
 * panels by declaring them, and the first `if (f.id === 'age')` here would be the
 * first world-specific line in the app. The backend shapes the values; this draws.
 */
export function Value({ f }: { f: ShapedField }) {
  switch (f.kind) {
    case 'gap':
      // Quiet, not an error: the narrator has simply not mentioned this yet, which
      // in a life is normal.
      return <span className="ew-gap">—</span>

    case 'stat':
    case 'resource':
      return (
        <div>
          <span>
            {String(f.value)}
            {f.max != null ? <span className="ew-sub">{` / ${f.max}`}</span> : null}
          </span>
          {f.note ? <div className="ew-sub">{f.note}</div> : null}
          {f.pct != null ? <Bar pct={f.pct} /> : null}
        </div>
      )

    case 'trend':
      return (
        <span>
          {String(f.value ?? '')}
          {f.direction ? <span className="ew-sub">{` ${f.direction}`}</span> : null}
          {f.note ? <span className="ew-sub">{` ${f.note}`}</span> : null}
        </span>
      )

    case 'rank':
      return (
        <span>
          {/* The tier, read from the key the backend actually sends. What this
              replaces read `label_`, which nothing has ever emitted — so the chip
              rendered an empty pill, and the type assertion around it was what
              stopped the compiler from pointing that out. */}
          {f.tier ? <Chip accent>{f.tier}</Chip> : <span className="ew-gap">—</span>}
          {f.note ? <span className="ew-sub">{` ${f.note}`}</span> : null}
        </span>
      )

    case 'people':
      return (
        <ul className="ew-list">
          {(f.entries ?? []).map((e, i) => (
            <li key={`${e.name}-${i}`}>
              {e.name}
              {(f.columns ?? []).map((c) =>
                e.cols?.[c] ? (
                  <span className="ew-sub" key={c}>{` · ${c}：${e.cols[c]}`}</span>
                ) : null,
              )}
              {e.note ? <span className="ew-sub">{` — ${e.note}`}</span> : null}
            </li>
          ))}
        </ul>
      )

    case 'threads':
      return <Lines entries={f.entries ?? []} primary="text" secondary="status" />

    case 'inventory':
      return (
        <div className="ew-chips">
          {(f.items ?? []).map((it, n) => (
            <Chip key={`${it.name}-${n}`}>
              {it.name}
              {it.count ? <span className="ew-sub">{` ×${it.count}`}</span> : null}
            </Chip>
          ))}
        </div>
      )

    case 'field':
      return <span>{String(f.value ?? '')}</span>

    default:
      // A primitive this build has never heard of. Showing the raw value is better
      // than showing nothing, and it is visibly plain rather than pretending to be
      // a rendered widget.
      return <span className="ew-sub">{String(f.value ?? '')}</span>
  }
}

export function PanelBox({ panel }: { panel: PanelView }) {
  return (
    <div className={`ew-panel-box${panel.empty ? ' ew-panel-quiet' : ''}`}>
      {(panel.fields ?? []).map((f) => (
        // A label the width of a phrase and a label the width of a paragraph cannot
        // share one layout. The narrator may put its own wording in the label slot,
        // and on the live flagship it put a whole clause there — which, squeezed into
        // the 5.5em label column, wrapped to ten lines beside a single dot of value.
        // Long labels therefore stack instead of columnising. The threshold is on
        // the content because CSS cannot measure text: there is no container query
        // for "how long is this string".
        <div
          className={`ew-prow${f.label.length > LABEL_COLUMN_CHARS ? ' ew-prow-stack' : ''}`}
          key={f.id}
        >
          <div className="ew-plabel">{f.label}</div>
          <div className="ew-pval">
            <Value f={f} />
          </div>
        </div>
      ))}
    </div>
  )
}

/** Labels longer than this stop being column headings and become prose, so the row
 *  stacks. Sized to the 5.5em label column: about the point where a CJK label needs
 *  a third line beside a one-line value. */
const LABEL_COLUMN_CHARS = 10

export function Glyph({ size = 20 }: { size?: number }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--accent, #7c3aed)"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H19v18H5.5A1.5 1.5 0 0 1 4 19.5z" />
      <path d="M8 3v18" />
      <path d="M12.5 8.5 14 11l2.5.4-1.8 1.8.4 2.5-2.6-1.2-2.6 1.2.4-2.5L8.5 11l2.5-.4z" />
    </svg>
  )
}

/**
 * The narrator is working.
 *
 * Why this exists rather than only disabling the button: a greyed-out row of
 * choices says "you cannot act" but not "your choice was taken", and it throws away
 * the one thing the player most wants confirmed — WHICH one they picked. So this
 * renders next to the chosen option's own label, leaving that label on screen,
 * instead of replacing the row with a page-level spinner.
 *
 * `role="status"` with `aria-live="polite"` because the visual change is the only
 * feedback: a screen reader that is never told the turn was accepted has the same
 * problem the grey button had, one layer down. The label is the announcement; the
 * dots are decoration and are hidden from the accessibility tree.
 */
export function Waiting({ label }: { label?: string }) {
  return (
    <span className="ew-wait" role="status" aria-live="polite">
      <span className="ew-wait-dots" aria-hidden="true">
        <i className="ew-dot" />
        <i className="ew-dot" />
        <i className="ew-dot" />
      </span>
      {label ? <span className="ew-wait-label">{label}</span> : null}
    </span>
  )
}
