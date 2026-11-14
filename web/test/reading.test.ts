// Run with `npm test` (node --test).
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  DEFAULT_READING,
  READING_KEYS,
  fontFaceCss,
  loadReading,
  saveReading,
} from '../src/reading.ts'

/** The part of `Storage` the module uses, backed by a Map. */
function memoryStorage(seed: Record<string, string> = {}) {
  const map = new Map(Object.entries(seed))
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
  }
}

test('nothing stored yields the defaults: a serif body, auto paragraphs', () => {
  assert.deepEqual(loadReading(memoryStorage()), DEFAULT_READING)
  assert.equal(DEFAULT_READING.font, 'literata')
  assert.equal(DEFAULT_READING.paragraph, 'auto')
})

test('a saved choice is what the next load reads back', () => {
  const store = memoryStorage()
  let prefs = loadReading(store)
  prefs = saveReading(store, prefs, 'font', 'kai')
  prefs = saveReading(store, prefs, 'size', 'xl')
  prefs = saveReading(store, prefs, 'leading', 'loose')
  prefs = saveReading(store, prefs, 'paragraph', 'spaced')
  saveReading(store, prefs, 'width', 'fixed')
  assert.deepEqual(loadReading(store), {
    font: 'kai',
    size: 'xl',
    leading: 'loose',
    paragraph: 'spaced',
    width: 'fixed',
  })
  assert.equal(store.map.get('endless-worlds:font'), 'kai')
})

test('the text width keeps the key it always had, so an earlier choice carries over', () => {
  assert.equal(READING_KEYS.width, 'endless-worlds:width')
  assert.equal(loadReading(memoryStorage({ 'endless-worlds:width': 'fixed' })).width, 'fixed')
})

test('an unknown stored value falls back to that setting default, not to the raw value', () => {
  const prefs = loadReading(
    memoryStorage({ 'endless-worlds:font': 'comic-sans', 'endless-worlds:text-size': '99' }),
  )
  assert.equal(prefs.font, DEFAULT_READING.font)
  assert.equal(prefs.size, DEFAULT_READING.size)
})

test('a storage that throws still yields defaults and still applies the choice', () => {
  const broken = {
    getItem: () => {
      throw new Error('denied')
    },
    setItem: () => {
      throw new Error('denied')
    },
  }
  assert.deepEqual(loadReading(broken), DEFAULT_READING)
  assert.equal(saveReading(broken, DEFAULT_READING, 'font', 'sans').font, 'sans')
  assert.deepEqual(loadReading(null), DEFAULT_READING)
})

test('the bundled faces resolve beside the bundle, never against another origin', () => {
  const css = fontFaceCss('http://localhost:9/apps/endless-worlds/ui/')
  const urls = [...css.matchAll(/url\('([^']+)'\)/g)].map((m) => m[1])
  assert.ok(urls.length >= 4)
  for (const u of urls) assert.ok(u?.startsWith('http://localhost:9/apps/endless-worlds/ui/fonts/'))
  // The ASCII-only twin is what keeps full-width CJK punctuation off the Latin face.
  assert.match(css, /'EW Literata ASCII'[^}]*unicode-range:U\+0020-007E/)
})
