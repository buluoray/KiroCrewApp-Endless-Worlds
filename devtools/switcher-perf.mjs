/** Frame-time probe for the page switcher (the page wheel, on a phone and on a wide
 * screen; on an older build the wide screen's fore-edge slider), on a life stretched
 * to 120 pages.
 * Run against a seeded disposable pod, never a player's live home:
 *   EW_POD_URL=… EW_POD_SESSION=… node devtools/switcher-perf.mjs [--cpu 4] [--runs 3]
 * For each gesture it logs every animation frame's interval while the gesture runs
 * and reads Chrome's own counters (layouts, style recalcs, script time) around it.
 * Prints one JSON line per gesture: p50/p95/max frame ms, frames over 16.7ms, and the
 * counter deltas. With EW_PERF_GPU=1 each gesture is also traced once and two
 * things come from Chrome's own frame tracking (the DevTools Frames track,
 * `PipelineReporter`): each frame's production time, begin to present, as
 * frameP50/frameP95, and how many frames it DROPPED; plus the compositor's own cost
 * (raster and draw ms per frame, off the main thread; headless Chrome composites in
 * software, so this is a proxy for GPU work). Use it with EW_PERF_VSYNC=1.
 * Headless Chrome paces frames to a fixed 60Hz clock, so a frame interval there is
 * 16.7ms however much work it held. By default the frame-rate limit is lifted
 * (--disable-frame-rate-limit, --disable-gpu-vsync): each frame starts as soon as the
 * last one is done, so its interval IS what the frame cost, and "dropped" counts the
 * frames that would have missed a 60Hz display. EW_PERF_VSYNC=1 keeps the 60Hz clock.
 * Nothing on the pod is written: the life's reads are intercepted.
 */
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const url = process.env.EW_POD_URL
const session = process.env.EW_POD_SESSION
if (!url || !session) {
  console.error('EW_POD_URL and EW_POD_SESSION are required')
  process.exit(2)
}
const arg = (name, dflt) => {
  const i = process.argv.indexOf(name)
  return i > 0 ? Number(process.argv[i + 1]) : dflt
}
const CPU = arg('--cpu', 4)
const RUNS = arg('--runs', 3)
const PAGES = 120
const FRAME_MS = 1000 / 60

const { chromium } = require(process.env.PLAYWRIGHT_PKG || 'playwright')

async function openLife(browser, width) {
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
  await page.goto(url + '/apps/endless-worlds', { waitUntil: 'load' })
  const get = (path) =>
    page.evaluate(async (u) => (await fetch(u, { credentials: 'include' })).json(), url + api + path)
  const rows = await get('/runs')
  const life = rows.runs.find((r) => !r.ended && r.turn >= 2) ?? rows.runs[0]
  const id = life.runId
  const live = await get('/runs/' + id)
  const view = { ...live, turn: PAGES, ended: false, generating: null }
  const turn = (n) => ({ turn: n, prose: `Page ${n} prose.`, action: `Action of page ${n}`, events: [], gains: [], backdrop: null })
  await page.route(`**${api}/runs/${id}`, (r) => r.fulfill({ json: view }))
  await page.route(`**${api}/runs/${id}/turn`, (r) => r.abort())
  await page.route(`**${api}/runs/${id}/chronicle/index`, (r) =>
    r.fulfill({
      json: { runId: id, rows: Array.from({ length: PAGES }, (_, i) => ({ turn: i + 1, hint: `Action of page ${i + 1}` })) },
    }),
  )
  await page.route(new RegExp(`${api}/runs/${id}/chronicle(\\?.*)?$`), (r) => {
    const before = Number(new URL(r.request().url()).searchParams.get('before') || 0)
    const top = before ? before - 1 : PAGES - 1
    const turns = [top, top - 1, top - 2].filter((n) => n >= 1).map(turn)
    return r.fulfill({ json: { runId: id, turns, more: top > 3 } })
  })
  await page.locator('button:visible').filter({ hasText: life.label }).first().click()
  await page.locator('.ew-play-root [role="region"]').first().waitFor()
  if (process.env.EW_PERF_CSS) await page.addStyleTag({ content: process.env.EW_PERF_CSS })
  const track = page.locator('.ew-topbar [role="slider"]')
  await track.waitFor()
  // The page settles its own scroll once its scenes mount; bring the bar into view
  // after that, so every pointer lands where it aims.
  await page.waitForTimeout(1500)
  await page.locator('.ew-topbar').evaluate((e) => e.scrollIntoView({ block: 'start' }))
  await page.waitForTimeout(300)
  // Start mid-book, so a swipe either way passes pages instead of pressing an end.
  await track.focus()
  for (let i = 0; i < 6; i++) await page.keyboard.press('PageDown')
  await page.waitForTimeout(1500)
  const cdp = await context.newCDPSession(page)
  await cdp.send('Performance.enable')
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU })
  return { context, page, cdp, track }
}

/** The control's box now: landing a page can scroll the bar, so aim afresh. */
async function aim({ page, track }) {
  await page.locator('.ew-topbar').evaluate((e) => e.scrollIntoView({ block: 'start' }))
  return track.boundingBox()
}

const metric = async (cdp) => {
  const { metrics } = await cdp.send('Performance.getMetrics')
  return Object.fromEntries(metrics.map((m) => [m.name, m.value]))
}

async function measure(name, { page, cdp }, gesture) {
  await page.evaluate(() => {
    const w = window
    w.__ft = []
    w.__ftOn = true
    // How many pages the gesture actually passed: a gesture that missed the control
    // would otherwise read as a perfectly smooth one.
    w.__steps = 0
    const el = document.querySelector('.ew-topbar [role="slider"]')
    w.__mo?.disconnect()
    w.__mo = new MutationObserver((recs) => {
      w.__steps += recs.length
    })
    if (el) w.__mo.observe(el, { attributes: true, attributeFilter: ['aria-valuenow'] })
    let last = performance.now()
    const loop = (now) => {
      if (!w.__ftOn) return
      w.__ft.push(now - last)
      last = now
      requestAnimationFrame(loop)
    }
    requestAnimationFrame((now) => {
      last = now
      requestAnimationFrame(loop)
    })
  })
  await page.waitForTimeout(100)
  const gpu = process.env.EW_PERF_GPU === '1'
  const tracing = (process.env.EW_PERF_TRACE || gpu) && !measure.traced?.has(name)
  const traceDir = process.env.EW_PERF_TRACE || '/tmp/ew-perf-traces'
  if (tracing) (await import('node:fs')).mkdirSync(traceDir, { recursive: true })
  if (tracing) {
    measure.traced = measure.traced ?? new Set()
    measure.traced.add(name)
    await page.context().browser().startTracing(page, {
      path: `${traceDir}/${name}.json`,
      categories: gpu
        ? ['devtools.timeline', 'cc', 'viz', 'gpu', 'disabled-by-default-devtools.timeline']
        : ['devtools.timeline', 'disabled-by-default-devtools.timeline', 'blink.user_timing', 'disabled-by-default-devtools.timeline.invalidationTracking'],
    })
  }
  const m0 = await metric(cdp)
  await gesture()
  const m1 = await metric(cdp)
  let comp = null
  if (tracing) {
    await page.context().browser().stopTracing()
    if (gpu) {
      const { readFileSync } = await import('node:fs')
      const ev = JSON.parse(readFileSync(`${traceDir}/${name}.json`, 'utf8')).traceEvents
      let raster = 0
      let draw = 0
      const open = new Map()
      const made = []
      let dropped = 0
      for (const e of ev) {
        if (e.name === 'PipelineReporter') {
          const k = `${e.pid}:${JSON.stringify(e.id2 ?? e.id)}`
          if (e.ph === 'b') open.set(k, e)
          else if (e.ph === 'e' && open.has(k)) {
            const b = open.get(k)
            open.delete(k)
            const state = b.args?.frame_reporter?.state
            if (state === 'STATE_DROPPED') dropped++
            else if (state === 'STATE_PRESENTED_ALL' || state === 'STATE_PRESENTED_PARTIAL')
              made.push((e.ts - b.ts) / 1000)
          }
          continue
        }
        if (e.ph !== 'X' || !e.dur) continue
        if (e.name === 'RasterTask') raster += e.dur
        else if (e.name === 'Display::DrawAndSwap' || e.name === 'DirectRenderer::DrawFrame') draw += e.dur
      }
      made.sort((a, b) => a - b)
      const at = (q) => made[Math.min(made.length - 1, Math.floor(q * made.length))] ?? 0
      comp = {
        rasterMs: raster / 1000,
        drawMs: draw / 1000,
        frameP50: +at(0.5).toFixed(1),
        frameP95: +at(0.95).toFixed(1),
        framesDropped: dropped,
        framesPresented: made.length,
      }
    }
    if (process.env.EW_PERF_RESOLVE) {
      const { readFileSync } = await import('node:fs')
      const ev = JSON.parse(readFileSync(`${traceDir}/${name}.json`, 'utf8')).traceEvents
      const counts = new Map()
      for (const e of ev) {
        if (e.name === 'Paint' && e.ph === 'X') {
          const id = e.args?.data?.nodeId
          counts.set(id, (counts.get(id) ?? 0) + 1)
        }
      }
      await cdp.send('DOM.getDocument', { depth: 0 })
      for (const [id, c] of [...counts].sort((a, b) => b[1] - a[1]).slice(0, 6)) {
        try {
          const { nodeIds } = await cdp.send('DOM.pushNodesByBackendIdsToFrontend', { backendNodeIds: [id] })
          const { node } = await cdp.send('DOM.describeNode', { nodeId: nodeIds[0] })
          console.error('paint', name, c, node.nodeName, (node.attributes || []).join(' ').slice(0, 140))
        } catch (err) {
          console.error('paint', name, c, id, String(err).slice(0, 80))
        }
      }
    }
  }
  const ft = await page.evaluate(() => {
    window.__ftOn = false
    return window.__ft
  })
  const steps = await page.evaluate(() => window.__steps)
  // The settle and the one page load land after the gesture: let them finish so the
  // next gesture starts from rest.
  await page.waitForTimeout(900)
  const s = [...ft].sort((a, b) => a - b)
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * s.length))] ?? 0
  const d = (k) => +(m1[k] - m0[k]).toFixed(k.endsWith('Duration') ? 3 : 0)
  return {
    gesture: name,
    steps,
    frames: ft.length,
    p50: +q(0.5).toFixed(1),
    p95: +q(0.95).toFixed(1),
    max: +(s[s.length - 1] ?? 0).toFixed(1),
    dropped: ft.filter((x) => x > FRAME_MS).length,
    layouts: d('LayoutCount'),
    styleRecalcs: d('RecalcStyleCount'),
    layoutMs: +(d('LayoutDuration') * 1000).toFixed(1),
    styleMs: +(d('RecalcStyleDuration') * 1000).toFixed(1),
    scriptMs: +(d('ScriptDuration') * 1000).toFixed(1),
    taskMs: +(d('TaskDuration') * 1000).toFixed(1),
    ...(comp
      ? {
          rasterPerFrame: +(comp.rasterMs / Math.max(1, ft.length)).toFixed(2),
          drawPerFrame: +(comp.drawMs / Math.max(1, ft.length)).toFixed(2),
          frameP50: comp.frameP50,
          frameP95: comp.frameP95,
          framesDropped: comp.framesDropped,
          framesPresented: comp.framesPresented,
        }
      : {}),
  }
}

/** Mouse moves paced at ~120Hz, the rate a phone's touch screen reports at. */
async function pacedMove(page, from, to, ms) {
  const n = Math.max(2, Math.round(ms / 8))
  const t0 = Date.now()
  for (let i = 1; i <= n; i++) {
    const k = i / n
    await page.mouse.move(from.x + (to.x - from.x) * k, from.y + (to.y - from.y) * k)
    const wait = t0 + i * 8 - Date.now()
    if (wait > 0) await new Promise((r) => setTimeout(r, wait))
  }
}

async function phone(browser) {
  const h = await openLife(browser, 375)
  const out = []
  for (let r = 0; r < RUNS; r++) {
    const box = await aim(h)
    const y = box.y + box.height / 2
    const cx = box.x + box.width / 2
    // A slow drag across the wheel and back: the numbers follow the finger.
    out.push(
      await measure('phone-drag', h, async () => {
        await h.page.mouse.move(cx + 80, y)
        await h.page.mouse.down()
        await pacedMove(h.page, { x: cx + 80, y }, { x: cx - 80, y }, 700)
        await pacedMove(h.page, { x: cx - 80, y }, { x: cx + 80, y }, 700)
        await h.page.mouse.up()
        await h.page.waitForTimeout(300)
      }),
    )
    const box2 = await aim(h)
    const y2 = box2.y + box2.height / 2
    // A fling: a quick swipe and release, then the coast and snap.
    out.push(
      await measure('phone-fling', h, async () => {
        await h.page.mouse.move(cx + 90, y2)
        await h.page.mouse.down()
        await pacedMove(h.page, { x: cx + 90, y: y2 }, { x: cx - 90, y: y2 }, 120)
        await h.page.mouse.up()
        await h.page.waitForTimeout(1000)
      }),
    )
  }
  await h.context.close()
  return out
}

async function desktop(browser) {
  const h = await openLife(browser, 1280)
  const out = []
  for (let r = 0; r < RUNS; r++) {
    let box = await aim(h)
    let y = box.y + box.height / 2
    out.push(
      await measure('desktop-drag', h, async () => {
        const a = { x: box.x + box.width * 0.9, y }
        const b = { x: box.x + box.width * 0.1, y }
        await h.page.mouse.move(a.x, a.y)
        await h.page.mouse.down()
        await pacedMove(h.page, a, b, 1000)
        await pacedMove(h.page, b, a, 1000)
        await h.page.mouse.up()
      }),
    )
    box = await aim(h)
    y = box.y + box.height / 2
    out.push(
      await measure('desktop-trackpad', h, async () => {
        await h.page.mouse.move(box.x + box.width / 2, y)
        // A trackpad: many small deltas, ~120 a second.
        for (let i = 0; i < 160; i++) {
          await h.page.mouse.wheel(0, i < 80 ? 6 : -6)
          await new Promise((res) => setTimeout(res, 8))
        }
      }),
    )
    box = await aim(h)
    y = box.y + box.height / 2
    out.push(
      await measure('desktop-mouse-wheel', h, async () => {
        await h.page.mouse.move(box.x + box.width / 2, y)
        // A mouse wheel: notches of 100px, about ten a second, down then back up.
        for (let i = 0; i < 24; i++) {
          await h.page.mouse.wheel(0, i < 12 ? 100 : -100)
          await new Promise((res) => setTimeout(res, 90))
        }
      }),
    )
  }
  await h.context.close()
  return out
}

const browser = await chromium.launch({
  args: process.env.EW_PERF_VSYNC === '1' ? [] : ['--disable-frame-rate-limit', '--disable-gpu-vsync'],
})
try {
  const rows = [...(await phone(browser)), ...(await desktop(browser))]
  const by = new Map()
  for (const r of rows) by.set(r.gesture, [...(by.get(r.gesture) ?? []), r])
  for (const [g, rs] of by) {
    const med = (k) => {
      const v = rs.map((r) => r[k]).sort((a, b) => a - b)
      return v[Math.floor(v.length / 2)]
    }
    const keys = Object.keys(rs[0]).filter((k) => k !== 'gesture' && rs.every((r) => k in r))
    console.log(JSON.stringify({ gesture: g, cpu: CPU, runs: rs.length, ...Object.fromEntries(keys.map((k) => [k, med(k)])) }))
  }
} finally {
  await browser.close()
}
