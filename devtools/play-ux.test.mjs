/** Run against a seeded disposable pod, never a player's live home.
 * EW_POD_URL + EW_POD_SESSION (Playwright storageState) are required.
 * Real reads; turn writes are intercepted so this never starts a narrator.
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const url = process.env.EW_POD_URL
const session = process.env.EW_POD_SESSION

test('keyboard, page arrival, narrow layout and first life', {
  skip: !url || !session,
  timeout: 120000,
}, async () => {
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(url).hostname))
  const { chromium } = require(process.env.PLAYWRIGHT_PKG || 'playwright')
  const browser = await chromium.launch()
  try {
    const context = await browser.newContext({ storageState: session, viewport: { width: 375, height: 900 } })
    await context.addInitScript(() => {
      localStorage.setItem('mc-onboarded', '1')
      localStorage.removeItem('endless-worlds:where')
    })
    const page = await context.newPage()
    const api = '/api/apps/endless-worlds'
    const rows = await (await context.request.get(url + api + '/runs')).json()
    const life = rows.runs.find(r => r.label === '第三天 · 井边')
    assert.ok(life, 'seed devtools fixtures into this pod first')
    const live = await (await context.request.get(url + api + '/runs/' + life.runId)).json()
    let shown = live
    let sends = []
    await page.route(`**${api}/runs/${life.runId}`, r => r.fulfill({ json: shown }))
    await page.route(`**${api}/runs/${life.runId}/turn`, async r => {
      sends.push(r.request().postDataJSON())
      shown = { ...shown, turn: shown.turn + 1, prose: 'The next page has arrived.', generating: null }
      await r.fulfill({ json: { advanced: true } })
    })
    await page.goto(url + '/apps/endless-worlds', { waitUntil: 'load' })
    await page.locator('button:visible').filter({ hasText: life.label }).first().click()
    const region = page.locator('.ew-play-root [role="region"]').first()
    await region.waitFor()
    assert.match(await region.getAttribute('aria-label'), /3/)
    const choice = page.locator('.ew-choice').first()
    await choice.focus()
    await page.keyboard.press('Enter')
    assert.equal(await choice.getAttribute('aria-pressed'), 'true')
    await page.keyboard.press('Tab')
    assert.equal(await page.locator('.ew-confirm button').first().evaluate(e => e === document.activeElement), true)
    await page.keyboard.press('Escape')
    assert.equal(await choice.evaluate(e => e === document.activeElement), true)
    assert.equal(await choice.getAttribute('aria-pressed'), 'false')
    await page.keyboard.press('Enter')
    await page.keyboard.press('Tab')
    await page.keyboard.press('Enter')
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label')?.includes('4'))
    assert.equal(sends.length, 1)
    assert.equal(sends[0].action, live.choices[0].label)
    assert.match(await page.locator('.ew-sr-only').innerText(), /4/)
    const input = page.locator('#ew-free-action')
    assert.equal(await page.getByLabel('你的做法', { exact: true }).count(), 1)
    assert.equal(await input.getAttribute('aria-describedby'), 'ew-action-help')
    await input.focus()
    await page.keyboard.type('Wait at the well')
    await page.keyboard.press('Enter')
    assert.equal(sends.length, 1, 'plain Enter adds a line, never sends')
    await input.dispatchEvent('keydown', { key: 'Enter', ctrlKey: true, isComposing: true, bubbles: true })
    assert.equal(sends.length, 1, 'IME composition must never send')
    await page.keyboard.press('Control+Enter')
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label')?.includes('5'))
    assert.equal(sends.length, 2)
    assert.equal(sends[1].action, 'Wait at the well')
    assert.match(await page.locator('.ew-sr-only').innerText(), /5/)
    // Real chronicle reads exercise keyboard paging without starting a turn.
    await page.locator('.ew-pager-arw').first().focus()
    await page.keyboard.press('Enter')
    await page.locator('.ew-pager-arw').first().focus()
    await page.keyboard.press('Enter')
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label')?.includes('3'))
    for (const width of [320, 375, 480]) {
      await page.setViewportSize({ width, height: 900 })
      await page.waitForTimeout(150)
      // A scroll-hidden bar has the same geometry as a keyboard-focused one.
      await page.locator('.ew-topbar').evaluate(e => e.classList.add('ew-topbar-hidden'))
      await page.locator('.ew-pager-arw').first().focus()
      assert.equal(await page.locator('.ew-topbar').evaluate(e => getComputedStyle(e).opacity), '1')
      const fits = await page.locator('.ew-topbar').evaluate(e => e.scrollWidth <= e.clientWidth)
      assert.equal(fits, true, `pager reflows at ${width}px`)
      const box = await page.locator('.ew-pager-arw').first().boundingBox()
      assert.ok(box.width >= 44 && box.height >= 44)
    }
    // Empty lives and worlds are read fixtures, not deleted pod records.
    await page.route(`**${api}/runs`, r => r.fulfill({ json: { runs: [] } }))
    await page.goto(url + '/apps/endless-worlds', { waitUntil: 'load' })
    await page.locator('#ew-first-life').waitFor()
    await page.locator('.ew-world-card').first().focus()
    await page.keyboard.press('Enter')
    await page.locator('.ew-detail-title').waitFor()
    await page.route(`**${api}/worlds?*`, r => r.fulfill({ json: { worlds: [], seeds: {} } }))
    await page.goto(url + '/apps/endless-worlds', { waitUntil: 'load' })
    await page.getByText(/No worlds yet|还没有世界/).waitFor()
  } finally {
    await browser.close()
  }
})
