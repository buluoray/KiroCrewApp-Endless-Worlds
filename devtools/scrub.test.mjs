/** The page wheel, driven with a real finger (375px) and a real mouse (1280px):
 * drag, flick, tap, mouse wheel, trackpad and the slider keys.
 * Run against a seeded disposable pod, never a player's live home.
 * EW_POD_URL + EW_POD_SESSION (Playwright storageState) are required; EW_SHOT_DIR,
 * when set, receives one mid-drag screenshot per width.
 * The life is stretched to 120 pages by intercepting its reads, so nothing on the
 * pod is written and no narrator starts. Every page read is counted: a drag, a flick,
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
  test(`page wheel at ${width}px`, { skip: !url || !session, timeout: 180000 }, async () => {
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
      // Read through the page, not context.request: the gateway binds its session to
      // the client address, and Node's own client can reach localhost over the other
      // IP family, which the gateway refuses as an IP mismatch.
      await page.goto(url + '/apps/endless-worlds', { waitUntil: 'load' })
      const get = (path) =>
        page.evaluate(async (u) => (await fetch(u, { credentials: 'include' })).json(), url + api + path)
      const rows = await get('/runs')
      const life = rows.runs.find((r) => !r.ended && r.turn >= 2) ?? rows.runs[0]
      assert.ok(life, 'seed devtools fixtures into this pod first')
      const id = life.runId
      const live = await get('/runs/' + id)
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
      await page.locator('button:visible').filter({ hasText: life.label }).first().click()
      const region = page.locator('.ew-play-root [role="region"]').first()
      await region.waitFor()
      // The page wheel, on every screen, is a slider.
      const track = page.locator('.ew-topbar [role="slider"]')
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
      // Where the bar sits: scrubbing must not scroll whatever scrolls the page.
      const barY = () => page.locator('.ew-topbar').evaluate((e) => Math.round(e.getBoundingClientRect().y))
      const scrollBefore = await barY()

      // ── swipe or drag the page wheel: the numbers follow, nothing is read until rest
      reads.length = 0
      // The same wheel on every screen: no fore-edge slider, no pager buttons.
      assert.equal(await page.locator('.ew-wheel-track').count(), 1, 'the page wheel')
      assert.equal(await page.locator('.ew-scrub, .ew-scrub-track, .ew-scrub-tip').count(), 0, 'no slider')
      assert.equal(await page.locator('.ew-pager, .ew-pager-hold, .ew-pager-arw').count(), 0, 'no pager buttons')
      // A fixed set of number slots, sized to the wheel, never one per page.
      const drawn = await page.locator('.ew-wheel-n').count()
      assert.ok(drawn > 3 && drawn <= 2 * (Math.ceil(box.width / 88) + 1) + 1, `${drawn} slots for ${PAGES} pages`)
      // From 1100px the drawer's own "back to the shelf" is the way home, so the row's
      // back link is not drawn there; below, it shares the wheel's row.
      const back = page.locator('.ew-topbar .ew-back')
      const bb = await back.boundingBox()
      const wb = await page.locator('.ew-wheel').boundingBox()
      assert.equal(bb === null, width >= 1100, 'the back link is in the row below 1100px only')
      if (bb) {
        assert.equal(Math.round(bb.y), Math.round(wb.y), "the wheel shares the back link's row")
        assert.equal(Math.round(bb.height), 44, 'the back link is one line')
        assert.ok(await back.evaluate((e) => e.scrollWidth <= e.clientWidth), 'the back link is not clipped')
      }
      if (width >= 600) assert.ok(wb.width <= 520, `a bounded wheel on a wide screen: ${wb.width}px`)
      // No action line, and no card behind the numbers.
      assert.equal(await page.locator('.ew-wheel-hint').count(), 0, 'no action line')
      for (const sel of ['.ew-wheel', '.ew-wheel-track'])
        assert.equal(await page.locator(sel).evaluate((e) => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)', sel)
      // On the live page the way back to it is spent.
      assert.equal(await page.locator('.ew-wheel-latest').isDisabled(), true)
      // A finger through the touch pipeline on a phone (pointer capture and
      // touch-action keep the page still); a mouse press-and-drag on a wide screen.
      const cdp = width < 500 ? await context.newCDPSession(page) : null
      const touch = (type, x) =>
        cdp.send('Input.dispatchTouchEvent', {
          type,
          touchPoints: type === 'touchEnd' ? [] : [{ x, y }],
        })
      const press = async (x) => {
        if (cdp) return touch('touchStart', x)
        await page.mouse.move(x, y)
        await page.mouse.down()
      }
      const move = (x) => (cdp ? touch('touchMove', x) : page.mouse.move(x, y))
      const lift = () => (cdp ? touch('touchEnd', 0) : page.mouse.up())
      const cx = box.x + box.width / 2
      // A slow drag right by ~4 items: the numbers follow the pointer.
      await press(cx - 90)
      for (let i = 1; i <= 22; i++) await move(cx - 90 + i * 8)
      await page.waitForTimeout(150)
      const mid = await now()
      assert.ok(mid >= PAGES - 5 && mid <= PAGES - 3, `the wheel follows the pointer: ${mid}`)
      assert.equal(await barY(), scrollBefore, 'dragging the wheel does not scroll the page')
      assert.equal(reads.length, 0, 'no page read while swiping')
      assert.match(await indicator.getAttribute('aria-label'), new RegExp(`\\b${mid}\\b`), 'the indicator follows')
      assert.equal(await page.locator('.ew-wheel-c').innerText(), String(mid), 'the centred number is the page')
      if (shots) await page.screenshot({ path: `${shots}/scrub-mid-drag-${width}.png`, clip: await shotClip() })
      // Then a flick: the drum coasts past where the pointer left it, still no read.
      for (let i = 1; i <= 4; i++) await move(cx + 86 + i * 30)
      await lift()
      await page.waitForTimeout(60)
      assert.equal(reads.length, 0, 'no page read while the wheel coasts')
      await page.waitForTimeout(1200)
      const rest = await now()
      assert.ok(Number.isInteger(rest) && rest < mid - 4, `a flick coasts and snaps to a page: ${rest}`)
      const drum = await page.locator('.ew-wheel-c').innerText()
      assert.equal(drum, String(rest), 'the snapped page is the centred number')
      assert.equal(await page.locator('.ew-wheel-c').count(), 1, 'one centred number')
      await landed(rest)
      assert.deepEqual(reads, [rest], 'the wheel reads exactly the one page it rests on')
      // Aim the rest of the run at 10.
      await track.focus()
      for (let i = 0; i < Math.floor((rest - 10) / 10); i++) await page.keyboard.press('PageDown')
      while ((await now()) > 10) await page.keyboard.press('ArrowLeft')
      reads.length = 0
      await page.keyboard.press('ArrowRight')
      await page.keyboard.press('ArrowLeft')
      await landed(10)
      assert.deepEqual(reads, [10], 'a key run reads exactly the one page landed on')

      // One tap or click on the next number is one page.
      const held = 10
      reads.length = 0
      await page.locator('.ew-topbar').evaluate((e) => e.scrollIntoView({ block: 'start' }))
      const tb0 = await track.boundingBox()
      await page.mouse.click(tb0.x + tb0.width / 2 + 44, tb0.y + tb0.height / 2)
      await landed(held + 1)
      assert.deepEqual(reads, [held + 1])

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
      assert.equal(await barY(), wheelY, 'a mouse wheel over it does not scroll the page')
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
      {
        // A tap on the centre number opens the type-a-number picker; a page typed
        // there is read once; the mark at the wheel's end goes back to the live page.
        const tc = await track.boundingBox()
        await page.mouse.click(tc.x + tc.width / 2, tc.y + tc.height / 2)
        const input = page.locator('.ew-pick-input')
        await input.waitFor()
        await input.fill('7')
        await page.keyboard.press('Enter')
        await landed(7)
        assert.deepEqual(reads, [at + 13, 7])
        const toLive = page.locator('.ew-wheel-latest')
        assert.match(await toLive.getAttribute('aria-label'), /Latest|最新/)
        await toLive.click()
        await landed(PAGES)
        assert.equal(await toLive.isDisabled(), true)
        assert.deepEqual(reads, [at + 13, 7])
      }
      // Home and End: the first page, then the LIVE page with no read.
      reads.length = 0
      await track.focus()
      await page.keyboard.press('Home')
      await landed(1)
      await page.keyboard.press('End')
      await landed(PAGES)
      assert.deepEqual(reads, [1])
      // The bar still fits on one line.
      assert.equal(await page.locator('.ew-topbar').evaluate((e) => e.scrollWidth <= e.clientWidth), true)
    } finally {
      await browser.close()
    }
  })
}
