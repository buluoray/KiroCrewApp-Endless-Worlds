---
name: float-ui-in-the-dashboard-shell
description: Place a floating or pinned element (a reading bar, a sheet, a menu) in Endless Worlds without covering the KiroCrew dashboard's own chrome or vanishing behind the app's backdrop.
version: 1.0.0
tags: [skill, endless-worlds, frontend, layout, z-index, mobile]
---

# Float UI inside the dashboard shell

## When to use

Before adding, moving, or re-layering anything that floats over the app: a bar
pinned to the top or bottom, an overlay sheet, a row menu, a modal. Also read it
when such an element misbehaves — covering the host's menu, sitting under the
app's own art, drifting during a gesture, or needing an offset.

The app is mounted **directly onto the dashboard document**, not in an iframe. It
therefore shares a stacking context, a scroll container, and a viewport with
KiroCrew's own UI, and every rule below follows from that one fact.

## The rule

> **Portal to `document.body` only where NO host UI lives. Anything at the TOP of
> the screen renders in place with `position: fixed`.**

The dashboard's shell is a **stacking context**. A portalled element therefore
competes with *that whole shell*, never with anything inside it — and the app's
content and the host's chrome are both inside it. So:

- above the app **is** above the host's chrome, and
- below the host's chrome **is** below the app.

**No value lies between.** This was measured on a real device, twice, from the
two ends:

| Reading row, portalled to body | Result on device |
|---|---|
| `z-index: 30` | covered the host's top bar and its menus |
| `z-index: 2` | invisible — behind the app's own backdrop |

Rendered in place instead, the row is inside the shell: it **cannot** outrank the
chrome (structural, not a number), and a small `z-index` clears the app's own
content. `position: fixed` still resolves against the shell, which spans the
window, so a declared offset keeps meaning what it says.

The phone's bottom tab bar (`tabbar.tsx`) *is* portalled, and correctly: nothing
of the host's lives at the bottom of the screen, so it never meets this.

## The app's layer ladder

Pick the lowest layer that does the job, and read this before inventing a value.
A number copied from another element ("the tab bar uses 30") is how this went
wrong.

| Layer | What |
|---|---|
| `0` | `.ew-backdrop` — world art, `fixed` to the viewport, `pointer-events: none` |
| `1` | `.ew-root > *` content lift, above the backdrop |
| `2` | `.ew-topbar-fixed` — the phone's reading row |
| `30` | `.ew-tabbar` — the phone's bottom navigator (portalled) |
| `31` / `32` | `.ew-tabmore` backdrop / sheet |
| `40` / `41` | `.ew-menu-backdrop` / `.ew-menu` — a life row's action menu |
| `40` | `.ew-modal-wrap` — the world-delete dialog |

Host, for reference: the dashboard's top bar is `z-[45]` **inside the shell**, so
its value is not comparable with anything above unless you have portalled out.

A menu opening *over* the reading row is right; the reverse is not — which is why
the row sits below every overlay the app itself raises.

## Offsets: declare them, never measure them

`--ew-chrome-h` (in `styles.css`) is how far down the reading row starts, so the
host's menu stays reachable. It is a **declared** `42px`, measured once at 390px
width, and re-checkable in one line from the dashboard's console:

```js
document.querySelector('main').getBoundingClientRect().top
```

Measuring it at runtime was tried and is worse. A reading taken before the host's
chrome has laid out returns **0**, the row is placed at the viewport top, and it
stays there covering that chrome until something remounts the effect — in practice
that meant switching a bottom tab. A `ResizeObserver` does not save it either: the
pane's *size* never changed, only its *position*. Frames, timers and a scroll
re-read narrowed the window without closing it.

The trade is explicit and worth restating in review: this is a number the app does
not own. `.topbar` declares no height of its own — it is content-driven and its
padding varies by platform — so there is no host variable to read instead. If the
row ever overlaps the menu or leaves a gap, that value is the only thing to change.

## Who owns the scrolling

The app does **not** scroll itself. The scroll container is the dashboard's
`main#main-content` (`overflow-y-auto`, and it declares no
`overscroll-behavior`). Consequences:

- **`position: sticky` rides the pane's rubber-band.** Sticky pins an element
  inside the *scrollport*, so a pane overscrolled past its own top carries the
  element down with it, leaving it below a band of bare canvas. `fixed` does not
  move.
- **Do not switch the bounce off from the app.** Setting
  `overscroll-behavior-y: none` on the host's scroller works, and it also removed
  the bottom tab bar's only way back at the end of a page — the bar reappeared
  there as a *side effect* of the spring-back producing an upward scroll. One
  borrowed property, two regressions.
- **Never rely on a bounce side effect for anything.** See the next section.

Finding the container, if you must: walk up for the first ancestor whose computed
`overflow-y` is `auto` or `scroll`. Never hardcode `main` — a selector into the
host's DOM fails silently the day the shell changes shape, and the only symptom is
the element drifting again.

## Hide-on-scroll: pin at both ends

`useScrollHide(enabled, pinUntil)` (`tabbar.tsx`) drives both phone bars from one
signal, so one upward swipe returns every control at once.

- **Near the top**, pin until the reader has passed the element's own footprint
  (`READER_BAR_PIN_PX`, 70 = the row's 60 plus the 10 it holds above the title).
  A smaller threshold lets it leave before the reader has passed the text it
  covers, and a swipe back slides it in again — it flickers in place.
- **At the end of the page**, pin too. Hiding there uncovers no story, and it is
  exactly where paging on matters.

## Verifying a change here

Headless Chromium cannot reproduce two of the causes in this file — a
rubber-band gesture, and the host chrome's layout *timing* — so a green probe
proves less than it looks. What does work:

1. **Source guards** in `backend/tests/test_rail.py`, which scan the built
   frontend source. Assert the *relation* (`row < tabbar < menu`), not a literal
   value nobody can reason about.
2. **Mutate every guard** before trusting it. Two guards in this area were too
   weak and passed under the mutation they existed to catch: `'scroll', remeasure,
   true` also matched the *remove*Listener line, and a bare
   `requestAnimationFrame` also matched the coalescer.
3. **Then a real device.** For anything about gestures or host chrome, the last
   word is a thumb on the real page.

## Traps, in one place

| Trap | What happens |
|---|---|
| Portalling a top-of-screen element to `body` | No z-index works: high covers the host chrome, low hides behind the app's backdrop |
| Copying a z-index from another element | The row got `30` from the tab bar and outranked the whole dashboard |
| Measuring the pane's top at mount | Reads `0` before the chrome lays out; the element pins over the host's menu |
| `overflow: hidden` on a card to clip art | Also clips any menu that opens out of it — give the art its own rounded clip box |
| `z-index: 1` on a content wrapper | Creates a stacking context that traps everything inside it |
| Switching the pane's bounce off | Takes the bottom bar's only reveal at the end of a page |
| `var(--card)` / `var(--border)` for a surface | Those come from the *dashboard* theme; a light dashboard puts a white wash over the app's dark canvas. Use fixed dark values (`rgba(6, 7, 14, …)`) |
