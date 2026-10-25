/** Run against a seeded disposable pod, never a player's live home.
 * EW_POD_URL + EW_POD_SESSION (Playwright storageState) are required.
 * Real reads; turn writes and the life's own reads are intercepted so this never
 * starts a narrator. Each assertion is one defect a real playtest hit.
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const url = process.env.EW_POD_URL
const session = process.env.EW_POD_SESSION
const api = '/api/apps/endless-worlds'
const LABEL = '第三天 · 井边'

async function open(width) {
  const { chromium } = require(process.env.PLAYWRIGHT_PKG || 'playwright')
  const browser = await chromium.launch()
  const context = await browser.newContext({ storageState: session, viewport: { width, height: 900 } })
  await context.addInitScript(() => {
    localStorage.setItem('mc-onboarded', '1')
    localStorage.removeItem('endless-worlds:where')
    localStorage.setItem('endless-worlds:rail', 'open')
  })
  const rows = await (await context.request.get(url + api + '/runs')).json()
  const life = rows.runs.find((r) => r.label === LABEL)
  assert.ok(life, 'seed devtools fixtures into this pod first')
  const live = await (await context.request.get(url + api + '/runs/' + life.runId)).json()
  return { browser, context, rows, life, live }
}

test('a month written while reading moves the rail and closes the entry recap', {
  skip: !url || !session,
  timeout: 120000,
}, async () => {
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(url).hostname))
  const { browser, context, rows, life, live } = await open(1440)
  try {
    const page = await context.newPage()
    // Entering a life that has a recap opens it — the precondition for the second half.
    let shown = {
      ...live,
      recap: { lastAction: 'Drew water first', events: ['The well ran clear'], choices: [] },
    }
    // The run list answers from the same state the life does, as the server would.
    await page.route(`**${api}/runs`, (r) =>
      r.fulfill({
        json: {
          ...rows,
          runs: rows.runs.map((x) =>
            x.runId === life.runId
              ? { ...x, turn: shown.turn, generating: !!shown.generating }
              : x,
          ),
        },
      }),
    )
    await page.route(`**${api}/runs/${life.runId}`, (r) => r.fulfill({ json: shown }))
    await page.route(`**${api}/runs/${life.runId}/turn`, async (r) => {
      shown = {
        ...shown,
        turn: shown.turn + 1,
        prose: 'The next page has arrived.',
        generating: null,
        recap: { lastAction: 'Go on', events: ['Something new'], choices: [] },
      }
      await r.fulfill({ json: { advanced: true } })
    })
    await page.goto(url + '/apps/endless-worlds', { waitUntil: 'load' })
    await page.locator('button:visible').filter({ hasText: LABEL }).first().click()
    await page.locator('.ew-play-root [role="region"]').first().waitFor()
    const row = page.locator('.ew-rail-row-on .ew-rail-sub')
    await row.waitFor()
    const before = await row.innerText()
    assert.match(before, new RegExp(String(live.turn)))
    await page.locator('.ew-story-moment').waitFor()

    await page.locator('.ew-choice').first().click()
    await page.locator('.ew-confirm button').first().click()
    const next = live.turn + 1
    await page.waitForFunction(
      (n) => document.querySelector('.ew-play-root [role="region"]')?.getAttribute('aria-label')?.includes(String(n)),
      next,
    )
    // The rail beside the story names the month the reader is on, not the one the
    // shelf was loaded at.
    await page.waitForFunction(
      (n) => document.querySelector('.ew-rail-row-on .ew-rail-sub')?.textContent?.includes(String(n)),
      next,
      { timeout: 8000 },
    )
    // "Where this life left off" belongs to entering it: after a month lands in
    // front of the reader it would recap that very month and push it down.
    assert.equal(await page.locator('.ew-story-moment').count(), 0, 'the entry recap must close')
  } finally {
    await browser.close()
  }
})

test('the first page hint sits under the story, not on its last line', {
  skip: !url || !session,
  timeout: 120000,
}, async () => {
  const { browser, context, life, live } = await open(375)
  try {
    const page = await context.newPage()
    const prose = Array.from({ length: 6 }, (_, i) => `Line ${i} of the very first month.`).join('\n')
    await page.route(`**${api}/runs/${life.runId}`, (r) =>
      r.fulfill({ json: { ...live, turn: 1, prose, generating: null, recap: undefined } }),
    )
    await page.goto(url + '/apps/endless-worlds', { waitUntil: 'load' })
    await page.locator('button:visible').filter({ hasText: LABEL }).first().click()
    const hint = page.locator('.ew-first-turn-hint, .ew-play-root p.ew-hint').first()
    await hint.waitFor()
    await page.waitForTimeout(500) // the page-turn animation settles
    const gap = await page.evaluate(() => {
      const story = document.querySelector('.ew-turnpage').getBoundingClientRect()
      const note = [...document.querySelectorAll('.ew-play-root p.ew-hint')].pop().getBoundingClientRect()
      return note.top - story.bottom
    })
    assert.ok(gap >= 0, `the hint overlaps the last line of prose by ${-gap}px`)
  } finally {
    await browser.close()
  }
})
