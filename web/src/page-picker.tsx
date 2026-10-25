import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'

import type { PageIndexRow } from './api'
import { api } from './api'
import { useScrubPreview, type ScrubStore } from './scrub-store'
import { t } from './strings'

/** One row's height. Fixed so the list can place any month without measuring it,
 *  which is what lets a long life render only the rows on screen. 44px is also the
 *  touch-target floor the pager keeps (#105). */
export const PICKER_ROW_PX = 44
/** Rows visible at once; the list scrolls past that. */
const PICKER_VIEW_ROWS = 6
/** Rows drawn above and below the visible ones, so a fast scroll never shows a gap. */
const PICKER_OVERSCAN = 4

/** The rows to draw for a scroll position: only those on screen plus a margin.
 *  Exported for the source contract — a life of 500 months draws ~14 buttons. */
export function visibleRows(scrollTop: number, total: number): [number, number] {
  const first = Math.max(0, Math.floor(scrollTop / PICKER_ROW_PX) - PICKER_OVERSCAN)
  const last = Math.min(total, first + PICKER_VIEW_ROWS + PICKER_OVERSCAN * 2)
  return [first, last]
}

/** The page hints, keyed by the life and its newest month, so a month written since
 *  the last read is not missing. ONE read per key, shared by the picker and the
 *  scrubber's label; a failed read is dropped so the next open asks again. */
let indexCache: { key: string; rows: Promise<Map<number, string>> } | null = null
export function loadPageIndex(runId: string, latest: number): Promise<Map<number, string>> {
  const key = `${runId}|${latest}`
  if (indexCache?.key === key) return indexCache.rows
  const rows = api
    .chronicleIndex(runId)
    .then((r) => new Map(r.rows.map((row: PageIndexRow) => [row.turn, row.hint])))
  indexCache = { key, rows }
  rows.catch(() => {
    if (indexCache?.rows === rows) indexCache = null
  })
  return rows
}

/**
 * The page indicator, and the month picker it opens. Paging one click at a time is
 * fine for last month and hopeless for month 3 of 84, so the indicator is a button:
 * it opens a number field (type a month, Enter) over a list of every month with a
 * few words each — the player's action, else how the page began — to find a page
 * by memory.
 *
 * The hints come from ONE small read of the chronicle index, made when the picker
 * first opens and kept until a new month lands. Jumping fetches nothing here: the
 * play page fetches only the page picked.
 *
 * On a phone (`overWheel`) the indicator has no box of its own: the page wheel shows
 * the number, a tap on the wheel's centre opens the picker (`open`/`onOpenChange`,
 * held by the play page), and the button here is a transparent square laid over that
 * centre number. A finger passes through it to the wheel; a keyboard or a screen
 * reader still reaches it as the picker's own named button, with its focus ring
 * drawn round the centre number.
 */
export function PagePicker({
  runId,
  shown,
  latest,
  onJump,
  preview,
  open: openProp,
  onOpenChange,
  overWheel = false,
}: {
  runId: string
  shown: number
  latest: number
  /** Show this month; `null` is the live page. */
  onJump: (turn: number | null) => void
  /** The page being flipped to by the scrubber or a held arrow, shown live. */
  preview?: ScrubStore
  /** Held by the caller when something else opens the picker (the phone's wheel). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Phone: the button is laid, unseen, over the page wheel's centre number. */
  overWheel?: boolean
}) {
  const flipping = useScrubPreview(preview)
  const label = flipping ?? shown
  const [ownOpen, setOwnOpen] = useState(false)
  const open = openProp ?? ownOpen
  const setOpen = (o: boolean) => (onOpenChange ? onOpenChange(o) : setOwnOpen(o))
  const trigger = useRef<HTMLButtonElement>(null)
  const root = useRef<HTMLDivElement>(null)
  const panelId = useId()
  // The index, keyed by the life and its newest month, so a month written since
  // the last open is not missing from the list.
  const [index, setIndex] = useState<{ key: string; rows: Map<number, string> } | null>(null)
  const indexKey = `${runId}|${latest}`
  useEffect(() => {
    if (!open || index?.key === indexKey) return undefined
    let alive = true
    loadPageIndex(runId, latest)
      .then((rows) => {
        if (alive) setIndex({ key: indexKey, rows })
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [open, index?.key, indexKey, runId, latest])

  // A click anywhere outside closes the picker without moving focus. The phone
  // wheel's own tap toggles it, so a press there is not "outside".
  const setOpenLive = useRef(setOpen)
  useEffect(() => {
    setOpenLive.current = setOpen
  })
  useEffect(() => {
    if (!open) return undefined
    const away = (e: PointerEvent) => {
      const at = e.target as Element | null
      if (root.current?.contains(at) || at?.closest?.('[data-ew-pick-toggle]')) return
      setOpenLive.current(false)
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open])

  const close = (refocus: boolean) => {
    setOpen(false)
    if (refocus) trigger.current?.focus({ preventScroll: true })
  }
  const jump = (turn: number) => {
    const n = Math.min(latest, Math.max(1, Math.round(turn)))
    // The same page again changes nothing on screen, so focus would otherwise fall
    // to the page; any OTHER page is focused and announced by StoryPage once.
    close(n === shown)
    onJump(n >= latest ? null : n)
  }

  return (
    <div className={'ew-pager-pick' + (overWheel ? ' ew-pager-pick-wheel' : '')} ref={root}>
      <button
        ref={trigger}
        className="ew-pager-turn"
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={t('play.jumpOpen', { n: label, total: latest })}
        onClick={() => setOpen(!open)}
      >
        {overWheel ? null : (
          <>
            <span className="ew-pager-long">{t('play.pageOf', { n: label, total: latest })}</span>
            <span className="ew-pager-short">
              {t('play.pageShort', { n: label, total: latest })}
            </span>
          </>
        )}
      </button>
      {open ? (
        <PickerPanel
          id={panelId}
          shown={shown}
          latest={latest}
          hints={index?.key === indexKey ? index.rows : null}
          onJump={jump}
          onClose={() => close(true)}
        />
      ) : null}
    </div>
  )
}

function PickerPanel({
  id,
  shown,
  latest,
  hints,
  onJump,
  onClose,
}: {
  id: string
  shown: number
  latest: number
  hints: Map<number, string> | null
  onJump: (turn: number) => void
  onClose: () => void
}) {
  const inputId = useId()
  const [draft, setDraft] = useState(String(shown))
  const typed = Number.parseInt(draft, 10)
  const valid = Number.isFinite(typed) && typed >= 1 && typed <= latest
  const list = useRef<HTMLDivElement>(null)
  // Open on the page being read, a couple of rows from the top.
  const [scrollTop, setScrollTop] = useState(() => Math.max(0, (shown - 3) * PICKER_ROW_PX))
  useEffect(() => {
    if (list.current) list.current.scrollTop = Math.max(0, (shown - 3) * PICKER_ROW_PX)
    // Only on open: the reader scrolls the list after that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // Typing a month brings its row into view, so the hint confirms the guess.
  useEffect(() => {
    const el = list.current
    if (!el || !valid) return
    const top = (typed - 1) * PICKER_ROW_PX
    if (top < el.scrollTop || top + PICKER_ROW_PX > el.scrollTop + el.clientHeight) {
      el.scrollTop = Math.max(0, top - PICKER_ROW_PX * 2)
    }
  }, [typed, valid])

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      onClose()
    }
  }
  const [first, last] = visibleRows(scrollTop, latest)
  const rows = []
  for (let i = first; i < last; i++) {
    const n = i + 1
    const hint = hints?.get(n) ?? ''
    rows.push(
      <button
        key={n}
        className={
          'ew-pick-row' +
          (n === shown ? ' ew-pick-row-on' : '') +
          (valid && n === typed ? ' ew-pick-row-typed' : '')
        }
        type="button"
        style={{ top: i * PICKER_ROW_PX }}
        aria-current={n === shown ? 'page' : undefined}
        onClick={() => onJump(n)}
      >
        <span className="ew-pick-n">{n}</span>
        <span className="ew-pick-hint">
          {n === latest ? t('play.jumpNow') : null}
          {n === latest && hint ? ' · ' : null}
          {hint}
        </span>
      </button>,
    )
  }
  return (
    <div
      id={id}
      className="ew-pick"
      role="dialog"
      aria-label={t('play.jumpTitle')}
      onKeyDown={onKey}
    >
      <form
        className="ew-pick-go"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) onJump(typed)
        }}
      >
        <label className="ew-pick-label" htmlFor={inputId}>
          {t('play.jumpLabel', { total: latest })}
        </label>
        <input
          id={inputId}
          className="ew-pick-input"
          type="number"
          inputMode="numeric"
          min={1}
          max={latest}
          value={draft}
          aria-invalid={!valid && draft !== ''}
          autoFocus
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => setDraft(e.currentTarget.value)}
        />
        <button className="ew-pick-btn" type="submit" disabled={!valid}>
          {t('play.jumpGo')}
        </button>
      </form>
      <div
        ref={list}
        className="ew-pick-list"
        role="group"
        aria-label={t('play.jumpList')}
        style={{ height: Math.min(latest, PICKER_VIEW_ROWS) * PICKER_ROW_PX }}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        <div className="ew-pick-track" style={{ height: latest * PICKER_ROW_PX }}>
          {rows}
        </div>
      </div>
    </div>
  )
}
