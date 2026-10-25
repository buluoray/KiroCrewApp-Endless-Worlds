/** The page scrubber, driven with a real pointer, finger, wheel and keys.
 * Run against a seeded disposable pod, never a player's live home.
 * EW_POD_URL + EW_POD_SESSION (Playwright storageState) are required; EW_SHOT_DIR,
 * when set, receives one mid-drag screenshot per width.
 * The life is stretched to 120 pages by intercepting its reads, so nothing on the
 * pod is written and no narrator starts. Every page read is counted: a drag, a hold,
 * a wheel spin and a key run must each end in ONE read.
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const url = process.env.EW_POD_URL
const session = process.env.EW_POD_SESSION
const shots = process.env.EW_SHOT_DIR
const PAGES = 120

for (const width of [1280, 375]) {
  test(`scrubber at ${width}px`, { skip: !url || !session, timeout: 180000 }, async () => {
    assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(url).hostname))
    const { chromium } = require(process.env.PLAYWRIGHT_PKG || 'playwright')
    const browser = await chromium.launch()
    try {
      const context = await browser.newContext({
        storageState: session,
        viewport: { width, height: 900 },
        hasTouch: width < 500,
      })
      await context.addInitScript(() => {
        localStorage.setItem('mc-onboarded', '1')
        localStorage.removeItem('endless-worlds:where')
      })
      const page = await context.newPage()
      const api = '/api/apps/endless-worlds'
      const rows = await (await context.request.get(url + api + '/runs')).json()
      const life = rows.runs.find((r) => !r.ended && r.turn >= 2) ?? rows.runs[0]
      assert.ok(life, 'seed devtools fixtures into this pod first')
      const id = life.runId
      const live = await (await context.request.get(url + api + '/runs/' + id)).json()
      const view = { ...live, turn: PAGES, ended: false, generating: null }
      const turn = (n) => ({
        turn: n,
        prose: `Page ${n} prose.`,
        action: `Action of page ${n}`,
        events: [],
        gains: [],
        backdrop: null,
      })
      const reads = []
      await page.route(`**${api}/runs/${id}`, (r) => r.fulfill({ json: view }))
      await page.route(`**${api}/runs/${id}/turn`, (r) => r.abort())
      await page.route(`**${api}/runs/${id}/chronicle/index`, (r) =>
        r.fulfill({
          json: {
            runId: id,
            rows: Array.from({ length: PAGES }, (_, i) => ({ turn: i + 1, hint: `Action of page ${i + 1}` })),
          },
        }),
      )
      await page.route(new RegExp(`${api}/runs/${id}/chronicle(\\?.*)?$`), (r) => {
        const before = Number(new URL(r.request().url()).searchParams.get('before') || 0)
        if (before) reads.push(before - 1)
        const top = before ? before - 1 : PAGES - 1
        const turns = [top, top - 1, top - 2].filter((n) => n >= 1).map(turn)
        return r.fulfill({ json: { runId: id, turns, more: top > 3 } })
      })
      await page.goto(url + '/apps/endless-worlds', { waitUntil: 'load' })
      await page.locator('button:visible').filter({ hasText: life.label }).first().click()
      const region = page.locator('.ew-play-root [role="region"]').first()
      await region.waitFor()
      const track = page.locator('.ew-scrub-track')
      await track.waitFor()
      assert.equal(await track.getAttribute('role'), 'slider')
      assert.equal(await track.getAttribute('aria-valuemax'), String(PAGES))
      assert.equal(await track.getAttribute('aria-valuenow'), String(PAGES))
      const landed = (n) =>
        page.waitForFunction(
          (n) => document.querySelector('.ew-play-root [role="region"]')?.getAttribute('aria-label')?.match(/\d+/)?.[0] === String(n),
          n,
        )
      // The bar and the label under it, wherever the dashboard placed the app.
      const shotClip = async () => {
        const b = await page.locator('.ew-topbar').boundingBox()
        return { x: Math.max(0, b.x - 8), y: Math.max(0, b.y - 8), width: Math.min(width, b.width + 16), height: 260 }
      }
      const now = async () => Number(await track.getAttribute('aria-valuenow'))
      const indicator = page.locator('button.ew-pager-turn')
      // The page settles its own scroll once its scenes mount; bring the bar into
      // view after that, so every pointer below lands where it aims.
      await page.waitForTimeout(1500)
      await page.locator('.ew-topbar').evaluate((e) => e.scrollIntoView({ block: 'start' }))
      const box = await track.boundingBox()
      const y = box.y + box.height / 2
      const xOf = (n) => box.x + 8 + ((box.width - 16) * (n - 1)) / (PAGES - 1)
      // Where the bar sits: scrubbing must not scroll whatever scrolls the page.
      const barY = () => page.locator('.ew-topbar').evaluate((e) => Math.round(e.getBoundingClientRect().y))
      const scrollBefore = await barY()

      // ── drag across many pages: the label follows, nothing is read until release
      reads.length = 0
      if (width < 500) {
        // A finger, through the touch pipeline, so pointer capture and touch-action
        // are what keep the page still.
        const cdp = await context.newCDPSession(page)
        const touch = (type, x) =>
          cdp.send('Input.dispatchTouchEvent', {
            type,
            touchPoints: type === 'touchEnd' ? [] : [{ x, y }],
          })
        await touch('touchStart', xOf(110))
        for (let i = 1; i <= 25; i++) await touch('touchMove', xOf(110 - i * 4))
        await page.waitForFunction(() => document.querySelector('.ew-scrub-tip')?.textContent?.includes('page 10'))
        assert.equal(await barY(), scrollBefore, 'a finger on the scrubber does not scroll the page')
        assert.equal(reads.length, 0, 'no page read while dragging')
        assert.ok(await page.locator('.ew-scrub-tip').isVisible(), 'the label shows mid-drag')
                assert.match(await page.locator('.ew-scrub-tip').innerText(), /Action of page 10/)
        assert.match(await indicator.innerText(), /\b10\b/, 'the indicator follows')
        if (shots) await page.screenshot({ path: `${shots}/scrub-mid-drag-${width}.png`, clip: await shotClip() })
        await touch('touchEnd', xOf(10))
      } else {
        await page.mouse.move(xOf(110), y)
        await page.mouse.down()
        for (let i = 1; i <= 25; i++) await page.mouse.move(xOf(110 - i * 4), y)
        assert.equal(await barY(), scrollBefore, 'dragging does not scroll the page')
        assert.equal(reads.length, 0, 'no page read while dragging')
        assert.ok(await page.locator('.ew-scrub-tip').isVisible(), 'the label shows mid-drag')
        assert.match(await page.locator('.ew-scrub-tip').innerText(), /Page 10 of 120|第 10 \/ 120 页/)
        assert.match(await page.locator('.ew-scrub-tip').innerText(), /Action of page 10/)
        assert.match(await indicator.innerText(), /\b10\b/, 'the indicator follows')
        if (shots) await page.screenshot({ path: `${shots}/scrub-mid-drag-${width}.png`, clip: await shotClip() })
        await page.mouse.up()
      }
      await landed(10)
      assert.deepEqual(reads, [10], 'release reads exactly the one page landed on')
      assert.equal(await page.locator('.ew-scrub-tip').count(), 0, 'the label goes on release')

      // ── hold Next: keeps flipping, faster the longer, one read on release
      reads.length = 0
      const next = page.locator('.ew-pager-hold').nth(1)
      const nb = await next.boundingBox()
      await page.mouse.move(nb.x + nb.width / 2, nb.y + nb.height / 2)
      await page.mouse.down()
      await page.waitForTimeout(1100)
      const early = await now()
      await page.waitForTimeout(1500)
      const later = await now()
      await page.mouse.up()
      assert.ok(early > 10 && early <= 14, `slow at first: ${early}`)
      assert.ok(later - early > early - 10, `faster later: 10 → ${early} → ${later}`)
      // A step can land between the last look and the release: read where it stopped.
      await page.locator('.ew-scrub-tip').waitFor({ state: 'detached' })
      const held = await now()
      assert.ok(held >= later && held <= later + 1)
      await landed(held)
      assert.deepEqual(reads, [held], 'a hold reads only the final page')

      // ── one click is still one page
      reads.length = 0
      await next.click()
      await landed(held + 1)
      assert.ok(reads.length <= 1)

      // ── the wheel: one page per notch, read on settle
      const at = held + 1
      reads.length = 0
      await page.locator('.ew-topbar').evaluate((e) => e.scrollIntoView({ block: 'start' }))
      const wheelY = await barY()
      const tb = await track.boundingBox()
      await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2)
      for (let i = 0; i < 3; i++) {
        await page.mouse.wheel(0, 100)
        await page.waitForTimeout(60)
      }
      // A trackpad's small deltas add up to a page.
      for (let i = 0; i < 5; i++) await page.mouse.wheel(0, 12)
      assert.equal(reads.length, 0, 'no read mid-spin')
      assert.equal(await barY(), wheelY, 'the wheel over the scrubber does not scroll the page')
      await landed(at + 4)
      assert.deepEqual(reads, [at + 4])

      // ── the slider's keys, announced once on settle, focus kept
      reads.length = 0
      await track.focus()
      await page.keyboard.press('PageUp')
      await page.keyboard.press('ArrowRight')
      await page.keyboard.press('ArrowLeft')
      await page.keyboard.press('ArrowLeft')
      assert.equal(await now(), at + 4 + 9)
      assert.equal(reads.length, 0)
      await landed(at + 13)
      assert.deepEqual(reads, [at + 13])
      assert.ok(await track.evaluate((e) => e === document.activeElement), 'focus stays on the slider')
      assert.match(await page.locator('.ew-sr-only[role="status"]').first().innerText(), new RegExp(String(at + 13)))
      // End is the LIVE page: the newest page, no read.
      await page.keyboard.press('End')
      await landed(PAGES)
      assert.deepEqual(reads, [at + 13])
      // The bar still fits, with the scrubber's row under it.
      assert.equal(await page.locator('.ew-topbar').evaluate((e) => e.scrollWidth <= e.clientWidth), true)
    } finally {
      await browser.close()
    }
  })
}
