/**
 * Compose captured shots into ONE contact sheet.
 *
 * The point is review cost. Forty PNGs is forty file reads for an agent (~8K tokens
 * each) and a scroll for a person; a single sheet with captions is one read, and the
 * per-shot numbers live in the JSON report beside it. Verdicts stay in the report —
 * a sheet is for spotting what a number cannot say ("that panel is empty", "the text
 * is white on white").
 *
 * stdin: { out, columns, tiles: [{ png, caption, bad }] }
 */
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_PKG || 'playwright')

const job = JSON.parse(readFileSync(0, 'utf-8'))
const columns = job.columns || 3
const esc = (s) => String(s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c])

const cards = job.tiles
  .map(
    // A RELATIVE src, and the page is written into the shots directory below: a page
    // served from about:blank (setContent) cannot load file:// subresources at all, and
    // silently renders every tile as a broken-image icon.
    (t) => `<figure class="${t.bad ? 'bad' : ''}">
      <img src="./${esc(basename(t.png))}" loading="eager" />
      <figcaption>${esc(t.caption)}</figcaption>
    </figure>`,
  )
  .join('\n')

const html = `<!doctype html><meta charset="utf-8"><style>
  :root { color-scheme: dark }
  body { margin: 0; padding: 20px; background: #0b0c12; color: #e2e8f0;
    font: 13px/1.45 -apple-system, "Segoe UI", "Noto Sans SC", sans-serif; }
  h1 { font-size: 15px; margin: 0 0 14px; color: #cbd5e1; font-weight: 600 }
  .grid { display: grid; grid-template-columns: repeat(${columns}, 1fr); gap: 16px; }
  figure { margin: 0; border: 1px solid #232637; border-radius: 10px; overflow: hidden;
    background: #10121a; }
  /* A failing tile is outlined, so the eye lands on it before reading a caption. */
  figure.bad { border-color: #b4472f; box-shadow: 0 0 0 1px #b4472f inset }
  img { display: block; width: 100%; height: auto; border-bottom: 1px solid #232637 }
  figcaption { padding: 8px 10px; color: #9aa3b5; white-space: pre-wrap }
  figure.bad figcaption { color: #e8a999 }
</style>
<h1>${esc(job.title || 'uishot contact sheet')}</h1>
<div class="grid">${cards}</div>`

const pagePath = join(dirname(job.out), basename(job.out).replace(/\.png$/, '') + '.html')
writeFileSync(pagePath, html, 'utf-8')

//: A reviewing agent's image API refuses a side over 2000px, so a sheet that grows
//: past it is not a big sheet — it is an unreadable one. The caller paginates to keep
//: tiles legible; this is the backstop that guarantees the file is loadable at all,
//: by re-rendering at a smaller device scale rather than cropping content away.
const CAP = 1960
const width = job.width || 1600
const browser = await chromium.launch()
let page = await browser.newPage({ viewport: { width, height: 1000 } })
await page.goto(pathToFileURL(pagePath).href, { waitUntil: 'load' })
await page.evaluate(() => Promise.all([...document.images].map((i) => i.decode().catch(() => {}))))
// A tile that failed to load is a silently useless sheet, so say so rather than
// shipping a grid of broken-image icons.
const broken = await page.evaluate(() => [...document.images].filter((i) => !i.naturalWidth).length)
const height = await page.evaluate(() => document.documentElement.scrollHeight)

const scale = Math.min(1, CAP / Math.max(width, height))
if (scale < 1) {
  await page.close()
  const ctx = await browser.newContext({
    viewport: { width, height: 1000 },
    deviceScaleFactor: scale,
  })
  page = await ctx.newPage()
  await page.goto(pathToFileURL(pagePath).href, { waitUntil: 'load' })
  await page.evaluate(() => Promise.all([...document.images].map((i) => i.decode().catch(() => {}))))
}
await page.screenshot({ path: job.out, fullPage: true })
console.log(
  JSON.stringify({
    out: job.out,
    px: [Math.round(width * scale), Math.round(height * scale)],
    scale: Number(scale.toFixed(3)),
    broken,
  }),
)
await browser.close()
process.exit(broken ? 1 : 0)
