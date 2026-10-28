import { useSyncExternalStore } from 'react'

/**
 * The page the reader is flipping to, while they flip.
 *
 * Swiping, dragging or spinning the page wheel passes many pages a
 * second. Putting that number in the play page's state would re-render the whole
 * story on every step, so it lives here instead: only the parts that show it — the
 * wheel, its `>|` mark, the picker's button — subscribe. `null` means nobody is
 * flipping and the shown page is the real one. The play page reads it once, on
 * release, and loads that one page.
 */
export interface ScrubStore {
  get: () => number | null
  set: (n: number | null) => void
  subscribe: (fn: () => void) => () => void
}

export function createScrubStore(): ScrubStore {
  let value: number | null = null
  const subs = new Set<() => void>()
  return {
    get: () => value,
    set: (n) => {
      if (n === value) return
      value = n
      for (const fn of subs) fn()
    },
    subscribe: (fn) => {
      subs.add(fn)
      return () => {
        subs.delete(fn)
      }
    },
  }
}

const noSubscribe = () => () => {}
const noValue = () => null

/** The page being flipped to, or `null`. Re-renders only the caller. */
export function useScrubPreview(store: ScrubStore | undefined): number | null {
  return useSyncExternalStore(store?.subscribe ?? noSubscribe, store?.get ?? noValue)
}
