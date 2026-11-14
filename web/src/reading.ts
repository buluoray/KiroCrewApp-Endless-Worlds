/**
 * The reader's own typography: one "Aa" panel's worth of standing choices.
 *
 * Shaped after what ebook readers converged on (Kindle, Apple Books, Kobo, KOReader,
 * WeChat Read): one panel holds the font, the text size, the line spacing, the
 * measure and the paragraph style, and each is a few named steps, not a free slider.
 * A step can be named and remembered; a slider position at 0.37 cannot be told apart
 * from 0.4 by eye and invites fiddling instead of reading.
 *
 * Every choice is a preference of the READER, not a fact about a world, so it is kept
 * in localStorage beside the app's other preferences and never asked of the backend.
 * The values reach the stylesheet as `data-ew-*` attributes on the app root; the
 * stylesheet owns what each step means per script (`:lang(zh)` versus Latin).
 *
 * DOM-free apart from the `Storage` it is handed, so the load and save rules are
 * tested without a browser (`reading.test.ts`).
 */

/** How wide the story is allowed to be.
 *
 * `fixed` caps it at a reading measure regardless of the monitor; `fluid` gives it
 * the window. The cap is the better default for prose and the reason it is not the
 * only option is that it is not the reader's monitor — someone reading on a 27"
 * screen at arm's length is entitled to more words per line than the measure a
 * paperback settled on. */
export type ReadWidth = 'fluid' | 'fixed'

/** The reading faces. Each one names a Latin face AND a CJK face, because a life is
 *  read in either script and the one setting has to mean something in both:
 *
 *  - `literata`: Literata (bundled; drawn for Google Play Books) with a Song/Ming
 *    serif for CJK (Source Han Serif / Noto Serif CJK, else the system's Song).
 *  - `newsreader`: Newsreader (bundled; drawn by Production Type for long reading
 *    on screen) with the same CJK serif.
 *  - `kai`: Literata with a Kai (楷体) face for CJK, from the system.
 *  - `sans`: the system's own sans for both scripts (PingFang, Noto Sans CJK, YaHei).
 *  - `system`: the dashboard's interface face, exactly as before this setting. */
export type ReadFont = 'literata' | 'newsreader' | 'kai' | 'sans' | 'system'
export type ReadSize = 's' | 'm' | 'l' | 'xl'
export type ReadLeading = 'tight' | 'normal' | 'loose'
/** `auto` follows the life's script: a first-line indent for Chinese (首行缩进),
 *  a gap between paragraphs for English. The other two force one style. */
export type ReadParagraph = 'auto' | 'indent' | 'spaced'

export interface ReadingPrefs {
  font: ReadFont
  size: ReadSize
  leading: ReadLeading
  paragraph: ReadParagraph
  width: ReadWidth
}

export const FONTS: readonly ReadFont[] = ['literata', 'newsreader', 'kai', 'sans', 'system']
export const SIZES: readonly ReadSize[] = ['s', 'm', 'l', 'xl']
export const LEADINGS: readonly ReadLeading[] = ['tight', 'normal', 'loose']
export const PARAGRAPHS: readonly ReadParagraph[] = ['auto', 'indent', 'spaced']
export const WIDTHS: readonly ReadWidth[] = ['fixed', 'fluid']

/** A serif body by default, as every reader app ships; Literata because it was drawn
 *  for long reading on screens and its CJK partner is the Song face 微信读书 readers
 *  pick most. Width stays `fluid`, the default it had before this panel existed. */
export const DEFAULT_READING: ReadingPrefs = {
  font: 'literata',
  size: 'm',
  leading: 'normal',
  paragraph: 'auto',
  width: 'fluid',
}

/** Storage keys. `width` keeps the key it always had, so a reader's existing choice
 *  carries over into the panel. Prefixed because this app shares the dashboard's
 *  localStorage. */
export const READING_KEYS: Record<keyof ReadingPrefs, string> = {
  font: 'endless-worlds:font',
  size: 'endless-worlds:text-size',
  leading: 'endless-worlds:leading',
  paragraph: 'endless-worlds:paragraph',
  width: 'endless-worlds:width',
}

const ALLOWED: { [K in keyof ReadingPrefs]: readonly ReadingPrefs[K][] } = {
  font: FONTS,
  size: SIZES,
  leading: LEADINGS,
  paragraph: PARAGRAPHS,
  width: WIDTHS,
}

function pick<K extends keyof ReadingPrefs>(
  key: K,
  raw: string | null | undefined,
): ReadingPrefs[K] {
  const allowed = ALLOWED[key] as readonly string[]
  return (raw != null && allowed.includes(raw) ? raw : DEFAULT_READING[key]) as ReadingPrefs[K]
}

/** Read every choice. An unknown value (an older build's, or a hand edit) falls back
 *  to that setting's default rather than reaching the stylesheet as a step it does
 *  not style; a storage that throws (private mode) yields the defaults. */
export function loadReading(storage: Pick<Storage, 'getItem'> | null): ReadingPrefs {
  const read = (key: string): string | null => {
    try {
      return storage?.getItem(key) ?? null
    } catch {
      return null
    }
  }
  return {
    font: pick('font', read(READING_KEYS.font)),
    size: pick('size', read(READING_KEYS.size)),
    leading: pick('leading', read(READING_KEYS.leading)),
    paragraph: pick('paragraph', read(READING_KEYS.paragraph)),
    width: pick('width', read(READING_KEYS.width)),
  }
}

/** Persist one choice and return the new set. A storage that refuses the write still
 *  gets the new set back, so the choice holds for this session. */
export function saveReading<K extends keyof ReadingPrefs>(
  storage: Pick<Storage, 'setItem'> | null,
  prefs: ReadingPrefs,
  key: K,
  value: ReadingPrefs[K],
): ReadingPrefs {
  const next = { ...prefs, [key]: pick(key, value) }
  try {
    storage?.setItem(READING_KEYS[key], next[key])
  } catch {
    /* private mode: the choice still holds for this session */
  }
  return next
}

/** The bundled font files, relative to the app's own `ui/` directory. The dashboard
 *  serves that directory from its own origin, which its CSP (`font-src 'self'`)
 *  allows; a font CDN is refused there and would also tell a third party when
 *  someone opens a story. Latin subsets only: a CJK face is several megabytes per
 *  weight and cannot be subset ahead of time for text a model has not written yet,
 *  so CJK comes from the faces the system already has. */
const FACES: Array<{ family: string; file: string; style: 'normal' | 'italic' }> = [
  { family: 'EW Literata', file: 'literata-roman.woff2', style: 'normal' },
  { family: 'EW Literata', file: 'literata-italic.woff2', style: 'italic' },
  { family: 'EW Newsreader', file: 'newsreader-roman.woff2', style: 'normal' },
  { family: 'EW Newsreader', file: 'newsreader-italic.woff2', style: 'italic' },
]

/** The Latin subset the files carry, as Google Fonts cut it. */
const LATIN_RANGE =
  'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, ' +
  'U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD'

/** The same files under a second name that covers letters and digits only. A Chinese
 *  page uses this one, so its full-width quotes and dashes (U+2000-206F, shared with
 *  Latin) come from the CJK face that draws them full width, not from a Latin face
 *  that draws them narrow. */
const ASCII_RANGE = 'U+0020-007E, U+00A0-00FF'

/** `@font-face` rules for the bundled faces, resolved against `base` (the URL of the
 *  app's `ui/` directory). `font-display: swap`: the story shows at once in the
 *  fallback face and re-sets when the file lands, rather than staying blank. */
export function fontFaceCss(base: string): string {
  const rules: string[] = []
  for (const f of FACES) {
    const url = new URL(`fonts/${f.file}`, base).href
    for (const [suffix, range] of [
      ['', LATIN_RANGE],
      [' ASCII', ASCII_RANGE],
    ] as const) {
      rules.push(
        `@font-face{font-family:'${f.family}${suffix}';font-style:${f.style};` +
          `font-weight:400 700;font-display:swap;src:url('${url}') format('woff2');` +
          `unicode-range:${range};}`,
      )
    }
  }
  return rules.join('\n')
}
