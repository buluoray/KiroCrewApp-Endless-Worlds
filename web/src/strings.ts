import { createContext, useContext } from 'react'

import en from './strings/en.json'
import zh from './strings/zh.json'

/**
 * Player-facing text, keyed by language.
 *
 * The text lives in JSON rather than in these modules for two reasons that point
 * the same way. It keeps the code free of any one language, and it makes the
 * language a property of the WORLD rather than of the build: a world whose header
 * says `language: en` should not be narrated to in Chinese, which is what a
 * hardcoded string guarantees.
 *
 * English is the fallback because it is the only table guaranteed to be complete —
 * a missing key surfaces as English rather than as a blank.
 */
export type Lang = 'zh' | 'en'

const TABLES: Record<Lang, Record<string, string>> = { zh, en }

/**
 * The language `t()` and `pick()` render in.
 *
 * Read from module scope so that every call site stays a plain `t('key')` with no
 * hook, but it is DRIVEN by React state at the app root (see `LanguageProvider`):
 * the root sets this synchronously during its own render, so a change to the world
 * being played re-renders the whole tree and this value is already correct on that
 * same commit rather than one render late.
 */
let current: Lang = 'zh'

/** Normalise a world's declared code; unknown codes are not a language we have. */
export function asLang(lang: string | undefined): Lang | null {
  return lang === 'zh' || lang === 'en' ? lang : null
}

/** Set the render language synchronously. Called by the root during render, never
 *  from an effect — an effect runs after the frame it should have governed. */
export function setCurrentLanguage(lang: Lang): void {
  current = lang
}

/** Delivers the language setter down the tree so a page that learns its world's
 *  language (after a fetch) can apply it without prop-drilling. The re-render is
 *  driven by the root's own state, not by this context. */
export const LanguageContext = createContext<(lang: string | undefined) => void>(() => {})

/** The function a page calls to make the app follow its world's language. */
export function useSetLanguage(): (lang: string | undefined) => void {
  return useContext(LanguageContext)
}

/**
 * One string, with `{name}` placeholders filled in.
 *
 * A missing key returns the key itself rather than an empty string: a screen
 * reading `play.turn` is obviously a bug, while a screen with a gap where a
 * sentence should be looks like a design choice.
 */
export function t(key: string, vars: Record<string, string | number> = {}): string {
  const table = TABLES[current]
  const fallback = TABLES.en
  const raw = table[key] ?? fallback[key] ?? key
  return raw.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  )
}

/**
 * One of several interchangeable phrasings, picked at random.
 *
 * How many variants exist is a property of the TABLE, not of this code: the count
 * is discovered by walking `<prefix>.0`, `<prefix>.1`, … until a key is missing, so
 * adding a seventh way to say "the years slip by" is a one-line edit to a JSON file
 * and nothing here changes.
 *
 * The caller must pick ONCE and hold the result. Calling this during render would
 * re-roll on every re-paint, and the page polls every few seconds while a month is
 * being written — the phrase would flicker through the whole set.
 */
export function pick(prefix: string, vars: Record<string, string | number> = {}): string {
  const table = TABLES[current]
  const fallback = TABLES.en
  const variants: string[] = []
  for (let i = 0; ; i += 1) {
    const key = `${prefix}.${i}`
    if (!(key in table) && !(key in fallback)) break
    variants.push(key)
  }
  if (!variants.length) return t(prefix, vars)
  const chosen = variants[Math.floor(Math.random() * variants.length)] as string
  return t(chosen, vars)
}
