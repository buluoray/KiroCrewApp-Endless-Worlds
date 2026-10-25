/** The phone's top row lines up: the back link, the wheel's centre number and the
 * `>|` latest mark share one vertical centre.
 * On the latest page the mark is hidden (not drawn, not focusable, aria-hidden) in
 * its own slot; one step back (mid-flip, then landed) it is shown and focusable, and
 * the link, the centre number and the mark's slot have not moved by more than 1px.
 * Run against a seeded disposable pod, never a player's live home.
 * EW_POD_URL + EW_POD_SESSION (Playwright storageState) are required; EW_SHOT_DIR,
 * when set, receives one top-row screenshot per width, theme and page.
 * The centres are measured on the INK, not the boxes: every box in the row is 44px
 * tall and centred, so a box test passes while the glyphs sit at different heights.
 * The row is screenshotted, decoded on a blank page's canvas, and each control's
 * ink rows are found by comparing against that control's own ground.
 * The life is set to N pages by intercepting its reads, so nothing on the pod is
 * written and no narrator starts.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const url = process.env.EW_POD_URL;
const session = process.env.EW_POD_SESSION;
const shots = process.env.EW_SHOT_DIR;
/** The most the three ink centres may differ, in CSS px. */
const TOLERANCE_PX = 2;
const WIDTHS = [320, 375, 480];
const THEMES = ["dark", "light"];
const PAGES = [3, 38, 120];

/** Ink centre (CSS px from the clip's top) of each named region in one PNG. */
async function inkCentres(blank, png, scale, regions) {
  return blank.evaluate(
    async ([b64, scale, regions]) => {
      const img = new Image();
      img.src = "data:image/png;base64," + b64;
      await img.decode();
      const c = document.createElement("canvas");
      c.width = img.width;
      c.height = img.height;
      const g = c.getContext("2d");
      g.drawImage(img, 0, 0);
      const out = {};
      for (const [name, r] of Object.entries(regions)) {
        const x0 = Math.round(r.x * scale);
        const y0 = Math.round(r.y * scale);
        const w = Math.round(r.width * scale);
        const h = Math.round(r.height * scale);
        const px = g.getImageData(x0, y0, w, h).data;
        // The ground is the region's most common colour; ink is whatever differs.
        const seen = new Map();
        for (let i = 0; i < px.length; i += 4) {
          const k =
            (px[i] >> 3) + "," + (px[i + 1] >> 3) + "," + (px[i + 2] >> 3);
          seen.set(k, (seen.get(k) || 0) + 1);
        }
        const [top] = [...seen.entries()].sort((a, b) => b[1] - a[1]);
        const [br, bg, bb] = top[0].split(",").map((v) => v * 8 + 4);
        let lo = -1;
        let hi = -1;
        for (let y = 0; y < h; y++) {
          for (let x = 0; x < w; x++) {
            const i = (y * w + x) * 4;
            const d = Math.max(
              Math.abs(px[i] - br),
              Math.abs(px[i + 1] - bg),
              Math.abs(px[i + 2] - bb),
            );
            if (d > 48) {
              if (lo < 0) lo = y;
              hi = y;
              break;
            }
          }
        }
        // Measured from the clip's top, so the three regions compare.
        out[name] =
          lo < 0
            ? null
            : {
                top: r.y + lo / scale,
                bottom: r.y + (hi + 1) / scale,
                mid: r.y + (lo + hi + 1) / 2 / scale,
              };
      }
      return out;
    },
    [png.toString("base64"), scale, regions],
  );
}

/** Resolve once the top row is at rest on page `n`: fonts loaded, the wheel not
 * flipping and reporting `n`, (for a past page) its prose on screen, and the bar,
 * the link, the centre number and the mark at the same place for 5 frames running.
 * Every measurement waits on this, never on a fixed delay. */
async function settled(page, n, past = false) {
  await page.waitForFunction(
    async ([n, past]) => {
      await document.fonts.ready;
      const t = document.querySelector(
        '.ew-topbar .ew-wheel-track[role="slider"]',
      );
      if (!t || t.classList.contains("ew-wheel-on")) return false;
      if (t.getAttribute("aria-valuenow") !== String(n)) return false;
      const c = document.querySelector(".ew-wheel-c");
      if (c?.textContent?.trim() !== String(n)) return false;
      const m = document.querySelector(".ew-wheel-latest");
      if (!m || m.disabled === past) return false;
      if (past && !document.body.innerText.includes(`Page ${n} prose.`))
        return false;
      const parts = [
        ".ew-topbar",
        ".ew-topbar .ew-back",
        ".ew-wheel-c",
        ".ew-wheel-latest",
      ];
      const snap = () =>
        parts
          .map((s) => {
            const r = document.querySelector(s)?.getBoundingClientRect();
            return r ? `${r.x},${r.y},${r.width},${r.height}` : "-";
          })
          .join("|");
      let prev = snap();
      for (let i = 0; i < 5; i++) {
        await new Promise((r) => requestAnimationFrame(r));
        const cur = snap();
        if (cur !== prev) return false;
        prev = cur;
      }
      return true;
    },
    [n, past],
    { polling: 50, timeout: 20000 },
  );
}

for (const width of WIDTHS) {
  test(
    `phone top row lines up at ${width}px`,
    { skip: !url || !session, timeout: 240000 },
    async () => {
      assert.ok(
        ["localhost", "127.0.0.1", "[::1]"].includes(new URL(url).hostname),
      );
      const { chromium } = require(process.env.PLAYWRIGHT_PKG || "playwright");
      const browser = await chromium.launch();
      try {
        for (const theme of THEMES) {
          for (const pages of PAGES) {
            const context = await browser.newContext({
              storageState: session,
              viewport: { width, height: 700 },
              deviceScaleFactor: 2,
              hasTouch: true,
              reducedMotion: "reduce",
            });
            await context.addInitScript((theme) => {
              localStorage.setItem("mc-onboarded", "1");
              localStorage.setItem("mc-theme", theme);
              localStorage.removeItem("endless-worlds:where");
            }, theme);
            const page = await context.newPage();
            try {
              const api = "/api/apps/endless-worlds";
              await page.goto(url + "/apps/endless-worlds", {
                waitUntil: "load",
              });
              const get = (path) =>
                page.evaluate(
                  async (u) =>
                    (await fetch(u, { credentials: "include" })).json(),
                  url + api + path,
                );
              const rows = await get("/runs");
              const life =
                rows.runs.find((r) => !r.ended && r.turn >= 2) ?? rows.runs[0];
              assert.ok(life, "seed devtools fixtures into this pod first");
              const id = life.runId;
              const live = await get("/runs/" + id);
              const view = {
                ...live,
                turn: pages,
                ended: false,
                generating: null,
              };
              const turn = (n) => ({
                turn: n,
                prose: `Page ${n} prose.`,
                action: `Action of page ${n}`,
                events: [],
                gains: [],
                backdrop: null,
              });
              await page.route(`**${api}/runs/${id}`, (r) =>
                r.fulfill({ json: view }),
              );
              await page.route(`**${api}/runs/${id}/turn`, (r) => r.abort());
              await page.route(`**${api}/runs/${id}/chronicle/index`, (r) =>
                r.fulfill({
                  json: {
                    runId: id,
                    rows: Array.from({ length: pages }, (_, i) => ({
                      turn: i + 1,
                      hint: `Action of page ${i + 1}`,
                    })),
                  },
                }),
              );
              await page.route(
                new RegExp(`${api}/runs/${id}/chronicle(\\?.*)?$`),
                (r) => {
                  const before = Number(
                    new URL(r.request().url()).searchParams.get("before") || 0,
                  );
                  const top = before ? before - 1 : pages - 1;
                  const turns = [top, top - 1, top - 2]
                    .filter((n) => n >= 1)
                    .map(turn);
                  return r.fulfill({
                    json: { runId: id, turns, more: top > 3 },
                  });
                },
              );
              await page
                .locator("button:visible")
                .filter({ hasText: life.label })
                .first()
                .click();
              const track = page.locator(
                '.ew-topbar .ew-wheel-track[role="slider"]',
              );
              await track.waitFor();
              assert.equal(
                await track.getAttribute("aria-valuenow"),
                String(pages),
              );
              await settled(page, pages);
              const blank = await context.newPage();
              const mark = page.locator(".ew-wheel-latest");
              // What a reader and a screen reader get from the `>|` mark.
              const markState = () =>
                mark.evaluate((e) => {
                  e.focus();
                  return {
                    visibility: getComputedStyle(e).visibility,
                    ariaHidden: e.getAttribute("aria-hidden"),
                    tabIndex: e.tabIndex,
                    focused: document.activeElement === e,
                  };
                });
              // One pass over the row: the boxes, the ink, and a screenshot.
              const measure = async (shown, label) => {
                await page
                  .locator(".ew-topbar")
                  .evaluate((e) => e.scrollIntoView({ block: "start" }));
                // The scroll can slide the bar; measure only once it is still.
                await settled(page, shown, shown < pages);
                const bar = await page.locator(".ew-topbar").boundingBox();
                const clip = {
                  x: 0,
                  y: Math.max(0, bar.y),
                  width,
                  height: Math.ceil(bar.height),
                };
                const rel = (b) => ({
                  x: b.x,
                  y: b.y - clip.y,
                  width: b.width,
                  height: b.height,
                });
                // The centre number's own 44px slot, not its turned neighbours.
                const centre = page.locator(".ew-wheel-c");
                assert.equal(await centre.innerText(), String(shown));
                const boxes = {
                  link: rel(
                    await page.locator(".ew-topbar .ew-back").boundingBox(),
                  ),
                  centre: rel(await centre.boundingBox()),
                  // Read off the DOM: it holds its slot even while hidden.
                  latest: rel(
                    await mark.evaluate((e) => {
                      const r = e.getBoundingClientRect();
                      return {
                        x: r.x,
                        y: r.y,
                        width: r.width,
                        height: r.height,
                      };
                    }),
                  ),
                };
                // The row stays compact: one 44px line.
                const row = await page.locator(".ew-wheel-bar").boundingBox();
                assert.equal(
                  Math.round(row.height),
                  44,
                  "the wheel row is one 44px line",
                );
                const png = await page.screenshot({ clip });
                if (shots) {
                  const where = `${shots}/row-${width}-${theme}-${pages}-${label}.png`;
                  // From the top, so the dashboard's own header shows which theme this is.
                  await page.screenshot({
                    path: where,
                    clip: {
                      x: 0,
                      y: 0,
                      width,
                      height: Math.min(700, clip.y + clip.height + 80),
                    },
                  });
                }
                const ink = await inkCentres(blank, png, 2, boxes);
                return { boxes, ink };
              };
              const where = `${width}px ${theme} page ${pages}`;
              // The latest page: the mark is spent, so it is hidden in its own slot.
              const atLatest = await markState();
              assert.equal(
                atLatest.visibility,
                "hidden",
                `mark hidden, ${where}`,
              );
              assert.equal(
                atLatest.ariaHidden,
                "true",
                `mark aria-hidden, ${where}`,
              );
              assert.equal(
                atLatest.tabIndex,
                -1,
                `mark not tabbable, ${where}`,
              );
              assert.equal(
                atLatest.focused,
                false,
                `mark not focusable, ${where}`,
              );
              const newest = await measure(pages, "latest");
              assert.equal(newest.ink.latest, null, `no mark drawn, ${where}`);
              // Mid-flip: the mark is back as soon as the wheel leaves the latest
              // page. Read in the frame the wheel reports the new value, while it
              // is still flipping (`.ew-wheel-on`), so before any page loads.
              const midFlip = await page
                .locator('.ew-topbar .ew-wheel-track[role="slider"]')
                .evaluate(async (track, n) => {
                  track.dispatchEvent(
                    new KeyboardEvent("keydown", {
                      key: "ArrowLeft",
                      bubbles: true,
                    }),
                  );
                  for (
                    let f = 0;
                    f < 120 &&
                    track.getAttribute("aria-valuenow") !== String(n);
                    f++
                  )
                    await new Promise((r) => requestAnimationFrame(r));
                  const m = document.querySelector(".ew-wheel-latest");
                  return {
                    valuenow: track.getAttribute("aria-valuenow"),
                    flipping: track.classList.contains("ew-wheel-on"),
                    visibility: getComputedStyle(m).visibility,
                  };
                }, pages - 1);
              assert.equal(midFlip.valuenow, String(pages - 1));
              assert.equal(midFlip.flipping, true, `still flipping, ${where}`);
              assert.equal(
                midFlip.visibility,
                "visible",
                `mark back mid-flip, ${where}`,
              );
              // An older page, landed (its prose is on screen and the row is
              // still): visible, focusable, named.
              await settled(page, pages - 1, true);
              const atOlder = await markState();
              assert.equal(
                atOlder.visibility,
                "visible",
                `mark shown, ${where}`,
              );
              assert.equal(
                atOlder.ariaHidden,
                null,
                `mark announced, ${where}`,
              );
              assert.equal(atOlder.focused, true, `mark focusable, ${where}`);
              await page
                .locator("body")
                .evaluate(() => document.activeElement?.blur());
              const older = await measure(pages - 1, "older");
              // Appearing moves nothing: the link and the centre number keep their place.
              for (const k of ["link", "centre", "latest"])
                for (const d of ["x", "y", "width", "height"])
                  assert.ok(
                    Math.abs(newest.boxes[k][d] - older.boxes[k][d]) <= 1,
                    `${k}.${d} moved ${newest.boxes[k][d]} -> ${older.boxes[k][d]}, ${where}`,
                  );
              for (const [label, { ink }] of [
                [
                  "latest",
                  { ink: { link: newest.ink.link, centre: newest.ink.centre } },
                ],
                ["older", older],
              ]) {
                for (const [k, v] of Object.entries(ink))
                  assert.ok(v, `${k} has ink at ${where} (${label})`);
                const mids = Object.values(ink).map((v) => v.mid);
                const spread = Math.max(...mids) - Math.min(...mids);
                const said = Object.entries(ink)
                  .map(([k, v]) => `${k}=${v.mid.toFixed(1)}`)
                  .join(" ");
                if (process.env.EW_ALIGN_VERBOSE)
                  console.log(
                    `${where} ${label}: ${said} spread=${spread.toFixed(1)}`,
                  );
                assert.ok(
                  spread <= TOLERANCE_PX,
                  `ink centres differ by ${spread.toFixed(1)}px (${said}) at ${where} (${label})`,
                );
              }
            } catch (err) {
              // Keep what the failing run saw: the whole frame, top first.
              if (shots)
                await page
                  .screenshot({
                    path: `${shots}/fail-${width}-${theme}-${pages}.png`,
                  })
                  .catch(() => {});
              throw err;
            } finally {
              await context.close();
            }
          }
        }
      } finally {
        await browser.close();
      }
    },
  );
}
