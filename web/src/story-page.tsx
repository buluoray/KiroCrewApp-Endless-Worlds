import { useEffect, useRef, useState, type ReactNode } from 'react'

import { t } from './strings'

/** A page arrival is one event, not every poll. Keep the live region mounted
 * across page changes; focus only while the reader still owns this surface. */
export function StoryPage({
  page,
  loading = false,
  className,
  children,
}: {
  page: number
  loading?: boolean
  className?: string
  children: ReactNode
}) {
  const region = useRef<HTMLDivElement>(null)
  const [announcedPage, setAnnouncedPage] = useState<number | null>(null)
  useEffect(() => {
    if (loading) return
    setAnnouncedPage(page)
    const el = region.current
    const active = document.activeElement
    const root = el?.closest('.ew-play-root')
    if (
      el &&
      el.getClientRects().length &&
      getComputedStyle(el).visibility !== 'hidden' &&
      (active === document.body || (active && root?.contains(active))) &&
      // A reader flipping with the scrubber's keys keeps it: the live region still
      // announces the page, once.
      !active?.closest('[role="slider"]')
    ) {
      el.focus({ preventScroll: true })
    }
  }, [page, loading])
  return (
    <>
      <div className="ew-sr-only" role="status" aria-live="polite" aria-atomic="true">
        {announcedPage === null ? '' : t('play.pageReady', { n: announcedPage })}
      </div>
      <div
        ref={region}
        className={className}
        role="region"
        aria-label={t('play.page', { n: page })}
        aria-busy={loading}
        tabIndex={-1}
      >
        {children}
      </div>
    </>
  )
}
