/**
 * Screenshot driver for the UI harness.
 *
 * Reads ONE job as JSON on stdin and prints ONE report as JSON on stdout, so the
 * Python side owns orchestration and this file owns only the browser.
 *
 * The report carries what a screenshot cannot: whether the step chain actually
 * reached the surface, the measured geometry of the elements the shot cares about,
 * console errors, and every non-2xx request. A frame that renders a 403 error body
 * looks like an empty box in a PNG — it is only visible as a failed request.
 *
 * Job shape:
 *   { baseUrl, token, rail, out, width, height, theme, fullPage,
 *     steps: [ {click|clickNth|wait|scrollTo|press|seconds} ], measure: [selector] }
 */
import { createRequire } from 'node:module'
import { existsSync, readFileSync } from 'node:fs'

// ESM resolution ignores NODE_PATH, so the package is required by absolute path when
// the harness is running against a Playwright it did not install itself.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_PKG || 'playwright')

const job = JSON.parse(readFileSync(0, 'utf-8'))
const report = {
  shot: job.out,
  reached: false,
  steps: [],
  measured: {},
  consoleErrors: [],
  badRequests: [],
  appRequests: [],
  pending: [],
}
/** Requests the dashboard itself makes that are expected to fail on a headless,
 *  non-desktop instance. An ignore list, not a blanket filter: anything else that
 *  fails must stay visible, since that is how a blank frame explains itself. */
const IGNORED_FAILURES = [/\/api\/instances\b/]
/** The app's own API prefix — its calls are reported in full (status included), and
 *  any that never settle are reported as pending. A surface stuck on a loading
 *  placeholder is otherwise indistinguishable from one that rendered nothing. */
const APP_API = /\/api\/apps\/[^/]+\//
const inflight = new Map()

const browser = await chromium.launch()
// A saved browser session, when there is one: the credential in the ready line has a
// SHORT click window (minutes), while the session cookie it exchanges for lasts hours.
// Without reusing that cookie, a shot run longer than the window dies half way through
// in a cascade of 403s that looks like an app bug.
const haveSession = job.session && existsSync(job.session)
const context = await browser.newContext({
  viewport: { width: job.width, height: job.height },
  deviceScaleFactor: job.width < 500 ? 2 : 1,
  locale: 'zh-CN',
  timezoneId: 'UTC',
  ...(haveSession ? { storageState: job.session } : {}),
})

// Before the SPA boots: skip the onboarding wall and pin the theme, so a run is not
// at the mercy of whatever the last run left in storage.
await context.addInitScript(
  ([theme, resetKeys]) => {
    localStorage.setItem('mc-onboarded', '1')
    localStorage.setItem('mc-theme', theme)
    // Drop the app's own "where I was" state: it makes the app resume the life the
    // PREVIOUS shot opened, so the surface a recipe asks for is not the one it gets.
    for (const key of resetKeys) localStorage.removeItem(key)
  },
  [job.theme, job.resetKeys || []],
)
const page = await context.newPage()
page.on('console', (m) => {
  if (m.type() === 'error') report.consoleErrors.push(m.text().slice(0, 300))
})
const note = (line, url) => {
  if (!IGNORED_FAILURES.some((re) => re.test(url))) report.badRequests.push(line)
}
page.on('request', (r) => {
  if (APP_API.test(r.url())) inflight.set(r, { path: r.url().replace(/\?.*/, ''), at: Date.now() })
})
page.on('requestfinished', async (r) => {
  const rec = inflight.get(r)
  if (rec === undefined) return
  inflight.delete(r)
  const res = await r.response()
  const ms = Date.now() - rec.at
  // Duration is reported because a slow first call and a hung one look identical in a
  // screenshot: the shelf's cold /worlds parse is seconds, and a reader sees a
  // placeholder for all of it.
  report.appRequests.push(`${res ? res.status() : '???'} ${ms}ms ${rec.path.slice(-64)}`)
})
page.on('response', (r) => {
  if (r.status() >= 400) note(`${r.status()} ${r.url().slice(0, 180)}`, r.url())
})
page.on('requestfailed', (r) => {
  inflight.delete(r)
  note(`FAILED ${r.failure()?.errorText} ${r.url().slice(0, 180)}`, r.url())
})

/** Return to the shelf if a life is currently open.
 *
 *  The app remembers which life you were reading, so a fresh page load can land on the
 *  play page rather than the shelf — and then the card a recipe wants to click is not
 *  on screen at all. Making "open this life" start from the shelf is what makes a shot
 *  independent of whatever the previous shot did.
 */
async function goHome() {
  if ((await page.locator('.ew-play-root').count()) === 0) return
  const back = page.locator('.ew-back').first()
  if ((await back.count()) > 0) {
    await back.click({ timeout: 10000 })
    await page.waitForSelector('.ew-play-root', { state: 'detached', timeout: 15000 })
  }
}

/** Click by text, preferring the ACTIONABLE ancestor over the text node itself.
 *
 *  A shelf card is a `<button>` whose accessible name is label + world + turn, so it
 *  cannot be addressed by an exact name — but the text node inside it is often covered
 *  by the app's sticky header once scrolled into view, and Playwright then waits for
 *  actionability until it times out. Scrolling first and clicking the button solves
 *  both, and keeps the click on the thing a person would actually press.
 */
async function clickText(text, exact) {
  // `:visible` matters: this app renders desktop and phone variants of the same
  // control and hides one by width, so an invisible match is the common case at
  // 390px — and scrolling to a hidden element fails rather than falling through.
  const attempts = [
    page.locator('button:visible, [role="button"]:visible, a:visible').filter({ hasText: text }).first(),
    page.getByText(text, { exact }).locator('visible=true').first(),
  ]
  let last = null
  for (const loc of attempts) {
    try {
      await loc.scrollIntoViewIfNeeded({ timeout: 8000 })
      await loc.click({ timeout: 8000 })
      return
    } catch (err) {
      last = err
    }
  }
  throw last
}

async function run() {
  if (!haveSession) {
    // Exchange the short-lived credential for a session cookie once.
    await page.goto(`${job.baseUrl}/?token=${job.token}`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('body', { timeout: 30000 })
  }
  // Straight to the app's own dashboard route. This is `/apps/<name>`, NOT the
  // manifest's `ui.pages[].route`; the rail click below is the fallback, and it is the
  // only path at phone widths where the rail is collapsed behind a menu.
  await page.goto(`${job.baseUrl}/apps/${job.app}`, { waitUntil: 'domcontentloaded' })
  try {
    await page.waitForSelector('.ew-root', { timeout: 15000 })
  } catch {
    await page.getByText(job.rail, { exact: true }).first().click({ timeout: 20000 })
    await page.waitForSelector('.ew-root', { timeout: 20000 })
  }

  for (const step of job.steps || []) {
    const label = JSON.stringify(step)
    try {
      if (step.home) await goHome()
      else if (step.click) await clickText(step.click, step.exact !== false)
      else if (step.clickNth) await page.getByText(step.clickNth.text).nth(step.clickNth.n).click({ timeout: 15000 })
      else if (step.wait) await page.waitForSelector(step.wait, { timeout: 20000 })
      else if (step.scrollTo) await page.locator(step.scrollTo).first().scrollIntoViewIfNeeded({ timeout: 15000 })
      else if (step.press) await page.keyboard.press(step.press)
      else if (step.seconds) await page.waitForTimeout(step.seconds * 1000)
      report.steps.push(`ok ${label}`)
    } catch (err) {
      report.steps.push(`FAILED ${label}: ${String(err).split('\n')[0].slice(0, 200)}`)
      throw err
    }
  }
  report.reached = true
}

let failure = ''
try {
  await run()
} catch (err) {
  failure = String(err).split('\n')[0].slice(0, 300)
}

// Settle: fonts, and the app's own in-flight calls. Waiting on the REQUESTS rather
// than on a fixed sleep is what makes "still pending" mean something — a surface that
// is genuinely stuck stays in the list, while a merely slow one drops out of it.
await page.evaluate(() => document.fonts?.ready).catch(() => {})
const settleDeadline = Date.now() + (job.settleMs ?? 15000)
while (inflight.size > 0 && Date.now() < settleDeadline) await page.waitForTimeout(250)
await page.waitForTimeout(400)

report.measured = await page.evaluate((selectors) => {
  const out = {}
  for (const sel of selectors) {
    // The first match is not necessarily the one on screen: this app renders a desktop
    // and a phone instance of the same slot and hides one by width, so measuring
    // `querySelector` alone silently reports a hidden duplicate's zero box.
    const all = [...document.querySelectorAll(sel)]
    const el = all.find((e) => e.getClientRects().length > 0) || all[0] || null
    out[sel] = el
      ? (({ width, height, top }) => ({
          w: Math.round(width),
          h: Math.round(height),
          top: Math.round(top),
        }))(el.getBoundingClientRect())
      : null
  }
  out['#frames'] = document.querySelectorAll('iframe').length
  out['#text'] = (document.querySelector('.ew-root')?.innerText || '').replace(/\s+/g, ' ').slice(0, 240)
  return out
}, job.measure || [])

await page.screenshot({ path: job.out, fullPage: !!job.fullPage })
report.pending = [...inflight.values()].map((r) => `${Date.now() - r.at}ms ${r.path.slice(-64)}`)
if (job.session && report.reached) await context.storageState({ path: job.session })
if (failure) report.failure = failure
console.log(JSON.stringify(report, null, 2))
await browser.close()
process.exit(failure ? 1 : 0)
