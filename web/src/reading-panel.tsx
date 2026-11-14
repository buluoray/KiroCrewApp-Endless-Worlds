/** The "Aa" button and the reading-settings panel it opens.
 *
 * It sits at the end of the reading page's top bar, the corner every ebook reader
 * puts it in, so the type can be judged and changed on the page being read — on a
 * phone too, where the desktop shelf drawer (and the text-width control that used
 * to live in it) does not render at all.
 *
 * The choices themselves live at the app root (`main.tsx`), which turns them into
 * attributes the stylesheet reads; this component only shows and sets them.
 */

import { createContext, useContext, useEffect, useId, useRef, useState } from 'react'

import {
  DEFAULT_READING,
  FONTS,
  LEADINGS,
  PARAGRAPHS,
  SIZES,
  WIDTHS,
  type ReadingPrefs,
} from './reading'
import { t } from './strings'

export interface ReadingControl {
  prefs: ReadingPrefs
  set: <K extends keyof ReadingPrefs>(key: K, value: ReadingPrefs[K]) => void
}

export const ReadingContext = createContext<ReadingControl>({
  prefs: DEFAULT_READING,
  set: () => {},
})

/** One setting as a row of a few named steps. Buttons with `aria-pressed`, not a
 *  select: every step is visible at once, which is what lets a reader compare. */
function Steps<K extends keyof ReadingPrefs>({
  setting,
  values,
  label,
}: {
  setting: K
  values: readonly ReadingPrefs[K][]
  label: string
}) {
  const { prefs, set } = useContext(ReadingContext)
  return (
    <div className="ew-read-row" role="group" aria-label={label}>
      <div className="ew-read-label">{label}</div>
      <div className={`ew-read-steps ew-read-steps-${setting}`}>
        {values.map((v) => (
          <button
            key={v}
            type="button"
            className="ew-read-step"
            aria-pressed={prefs[setting] === v}
            data-value={v}
            onClick={() => set(setting, v)}
          >
            {t(`read.${setting}.${v}`)}
          </button>
        ))}
      </div>
    </div>
  )
}

export function ReadingSettings() {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  // Escape and a click outside both close it, and Escape hands focus back to the
  // button so a keyboard reader is not left on a control that just vanished.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      button.current?.focus()
    }
    const onDown = (e: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  }, [open])

  return (
    <div className="ew-read" ref={wrap}>
      <button
        ref={button}
        className="ew-read-open"
        type="button"
        aria-label={t('read.open')}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        <span aria-hidden="true">{t('read.glyph')}</span>
      </button>
      {open ? (
        <div className="ew-read-panel" id={panelId} role="dialog" aria-label={t('read.open')}>
          <Steps setting="font" values={FONTS} label={t('read.font')} />
          <Steps setting="size" values={SIZES} label={t('read.size')} />
          <Steps setting="leading" values={LEADINGS} label={t('read.leading')} />
          <Steps setting="paragraph" values={PARAGRAPHS} label={t('read.paragraph')} />
          <Steps setting="width" values={WIDTHS} label={t('read.width')} />
        </div>
      ) : null}
    </div>
  )
}
