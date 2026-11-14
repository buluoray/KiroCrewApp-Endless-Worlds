// Run with `npm test` (node --test). Node strips the TypeScript types itself, so the
// module under test is imported as the source the bundle is built from.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { splitParagraphs } from '../src/paragraphs.ts'

const kinds = (text: string) => splitParagraphs(text).map((p) => p.kind)
const texts = (text: string) => splitParagraphs(text).map((p) => p.text)

test('a blank line separates paragraphs', () => {
  assert.deepEqual(texts('雨停了。\n\n阿美已经起来了。\n\n\n她没有回头。'), [
    '雨停了。',
    '阿美已经起来了。',
    '她没有回头。',
  ])
})

test('a single line break between two lines of prose is a paragraph break too', () => {
  const out = splitParagraphs('The rain stopped.\nAmei was already up.\r\nShe did not look round.')
  assert.deepEqual(
    out.map((p) => p.text),
    ['The rain stopped.', 'Amei was already up.', 'She did not look round.'],
  )
  assert.deepEqual(
    out.map((p) => p.kind),
    ['text', 'text', 'text'],
  )
})

test('a typed indent is dropped so it cannot stack on the stylesheet one or become code', () => {
  assert.deepEqual(texts('　　全角缩进的一段。\n    four spaces in front.'), [
    '全角缩进的一段。',
    'four spaces in front.',
  ])
})

test('a list stays one block, and the prose around it still splits per line', () => {
  const out = splitParagraphs('You count what is left.\n- two buckets\n- one rope\nIt is enough.')
  assert.deepEqual(
    out.map((p) => p.kind),
    ['text', 'block', 'text'],
  )
  assert.equal(out[1]?.text, '- two buckets\n- one rope')
})

test('a heading stands alone and is marked as one', () => {
  assert.deepEqual(kinds('## Day Three\nThe pump ran clear.'), ['head', 'text'])
})

test('a fenced block is kept whole, blank lines and all', () => {
  const fence = '```\nline one\n\nline two\n```'
  const out = splitParagraphs(`Before.\n\n${fence}\n\nAfter.`)
  assert.deepEqual(
    out.map((p) => p.kind),
    ['text', 'block', 'text'],
  )
  assert.equal(out[1]?.text, fence)
})

test('a quote block keeps its lines together', () => {
  const out = splitParagraphs('> one\n> two')
  assert.deepEqual(out, [{ kind: 'block', text: '> one\n> two' }])
})

test('empty and whitespace-only text yields no paragraphs', () => {
  assert.deepEqual(splitParagraphs(''), [])
  assert.deepEqual(splitParagraphs('\n \n\t\n'), [])
})
