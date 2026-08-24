import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type {
  LifeRowData,
  PanelView,
  SceneRow,
  SeedReport,
  WorldDetail,
  WorldRow,
  WorldDraftRow,
} from './api'
import { api } from './api'
import { DeleteWorldDialog } from './confirm'
import {
  CreateWorldCard,
  CreateWorldScreen,
  DRAFT_POLL_MS,
  WorldDraftCard,
  WorldDraftReview,
} from './create-world'
import { LifeRow, WorldCard, WorldDetailView } from './library'
import { PerfPage } from './perf'
import { DRAFT_PREFIX, OpeningScreen } from './opening'
import { PlayPage } from './play'
import { WorldRail, type ReadWidth } from './rail'
import { Backdrop } from './backdrop'
import { SceneSlot } from './scene'
import { SettingsPanel } from './settings'
import { READER_BAR_PIN_PX, WorldTabBar, buildTabs, useScrollHide } from './tabbar'
import styles from './styles.css?raw'
import { asLang, LanguageContext, setCurrentLanguage, t, type Lang } from './strings'
import { Glyph, PanelBox } from './ui'

/** The app version, replaced at build time from app.json (see web/vite.config.ts),
 *  shown in the shelf footer. A build-time constant keeps it from drifting. */
declare const __APP_VERSION__: string

/** Where the player was, so leaving the page does not throw them back to the
 *  shelf. Prefixed because this app mounts inside the dashboard's own document
 *  and shares its localStorage. */
const WHERE = 'endless-worlds:where'

/** The player's standing UI-language pick from the header dropdown. Prefixed and
 *  shared with the dashboard document like every other key this app keeps. */
const LANG_KEY = 'endless-worlds:lang'

/** The reader's standing choice of reading measure. A preference, not a per-world
 *  fact, so it is kept here rather than asked of the backend. */
const WIDTH_KEY = 'endless-worlds:width'
const RAIL_KEY = 'endless-worlds:rail'

/** The FIRST-RUN default UI language: follow the Crew, fall back to English.
 *
 *  KiroCrew's LanguageProvider sets `<html lang>` to the resolved dashboard
 *  language, and this app mounts into that same document, so `documentElement.lang`
 *  is the Crew's OWN UI language rather than the raw browser locale;
 *  `navigator.language` is only a standalone/dev fallback. This app ships zh + en,
 *  so any Crew language it has no table for falls to English. A remembered explicit
 *  pick and world-follow both still override this default. */
function crewLanguageDefault(): Lang {
  const code = (document.documentElement.lang || navigator.language || '').slice(0, 2).toLowerCase()
  return asLang(code) ?? 'en'
}

type View = 'library' | 'detail' | 'opening' | 'live' | 'create' | 'draft' | 'perf'

interface Where {
  view: View
  runId?: string
  worldId?: string
  /** The world-draft being reviewed (view === 'draft'). */
  draftId?: string
}

/** How the shelf orders lives. `recent` (the default) puts the life that moved
 *  most recently first, which is what a reader coming back wants; `started` keeps
 *  the order the lives were begun in, which is the one that does NOT rearrange
 *  itself under you as you play. Remembered because a reader who prefers one
 *  ordering prefers it every time. */
type ShelfOrder = 'recent' | 'started'
const ORDER_KEY = 'ew-shelf-order'

const rememberOrder = (order: ShelfOrder) => {
  try {
    localStorage.setItem(ORDER_KEY, order)
  } catch {
    /* private mode */
  }
}
const recallOrder = (): ShelfOrder => {
  try {
    return localStorage.getItem(ORDER_KEY) === 'started' ? 'started' : 'recent'
  } catch {
    return 'recent'
  }
}

/** Order a shelf group. `createdAt` is absent on rows written before it existed,
 *  so `lastPlayed` stands in — that orders such a row no worse than it was
 *  ordered before, and never drops it. */
const byOrder = (rows: LifeRowData[], order: ShelfOrder): LifeRowData[] =>
  [...rows].sort((a, b) =>
    order === 'started'
      ? (a.createdAt ?? a.lastPlayed ?? 0) - (b.createdAt ?? b.lastPlayed ?? 0)
      : (b.lastPlayed ?? 0) - (a.lastPlayed ?? 0),
  )

const remember = (where: Where) => {
  try {
    localStorage.setItem(WHERE, JSON.stringify(where))
  } catch {
    /* private mode */
  }
}
const recall = (): Where | null => {
  try {
    return JSON.parse(localStorage.getItem(WHERE) ?? 'null') as Where | null
  } catch {
    return null
  }
}
const forget = () => {
  try {
    localStorage.removeItem(WHERE)
  } catch {
    /* nothing to undo */
  }
}

export default function EndlessWorlds() {
  const [worlds, setWorlds] = useState<WorldRow[] | null>(null)
  const [seeds, setSeeds] = useState<SeedReport | null>(null)
  const [runs, setRuns] = useState<LifeRowData[]>([])
  const [error, setError] = useState<string | null>(null)

  /** World drafts being built from pasted text — shown as cards in the worlds
   *  section, polled to completion, then reviewed and installed. */
  const [drafts, setDrafts] = useState<WorldDraftRow[]>([])
  /** The draft open in the review screen (view === 'draft'). */
  const [reviewDraft, setReviewDraft] = useState<string | null>(null)

  const [view, setView] = useState<View>('library')
  /** Which life the performance page is showing (view === 'perf'). */
  const [perfRun, setPerfRun] = useState<{ runId: string; name: string } | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  /** The shelf. Remembered across loads and OPEN by default so the landing shows
   *  the lives in it; the reader can close it for more reading room (the story
   *  then owns the full width) and reopen it, and the choice sticks. */
  const [railOpen, setRailOpen] = useState(() => {
    try {
      return localStorage.getItem(RAIL_KEY) !== 'closed'
    } catch {
      return true
    }
  })
  const toggleRail = useCallback(() => {
    setRailOpen((o) => {
      const next = !o
      try {
        localStorage.setItem(RAIL_KEY, next ? 'open' : 'closed')
      } catch {
        /* private mode: the choice still holds for this session */
      }
      return next
    })
  }, [])
  const [readWidth, setReadWidth] = useState<ReadWidth>(() =>
    localStorage.getItem(WIDTH_KEY) === 'fixed' ? 'fixed' : 'fluid',
  )
  const chooseWidth = useCallback((next: ReadWidth) => {
    try {
      localStorage.setItem(WIDTH_KEY, next)
    } catch {
      /* private mode: the choice still holds for this session */
    }
    setReadWidth(next)
  }, [])
  // The app mounts inside the dashboard's own scroll container, which keeps its
  // offset across our view swaps — so moving from the shelf into a tall opening
  // form would land the player at its BOTTOM. Bring our root back into view at the
  // top on every view change.
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    rootRef.current?.scrollIntoView({ block: 'start' })
  }, [view])
  const [selected, setSelected] = useState<string | null>(null)
  const [world, setWorld] = useState<WorldDetail | null>(null)
  const [live, setLive] = useState<string | null>(null)
  const [scenes, setScenes] = useState<SceneRow[]>([])
  const [panels, setPanels] = useState<PanelView[]>([])
  const [backdrop, setBackdrop] = useState<{
    version: number
    turn?: number
    mobile?: boolean
  } | null>(null)
  // ── phone bottom tab bar ──────────────────────────────────────────────
  // Narrow-viewport only; the desktop keeps the WorldRail. `tab` is the active
  // surface within a life: 'reading', 'starmap', or a scene region id.
  const [isNarrow, setIsNarrow] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(max-width: 1100px)').matches
      : false,
  )
  const [tab, setTab] = useState('reading')
  /** Whether a sheet in the play column (star map, legacy picker) is open.
   *
   *  The mounted scene frames render HERE, outside that column, because
   *  re-parenting an iframe reloads it — so a sheet anchored to the column cannot
   *  cover them and they would otherwise stay on the page underneath it. Held as
   *  state rather than derived, since only the play column knows its own sheets. */
  const [sheetOpen, setSheetOpen] = useState(false)
  const [liveTurn, setLiveTurn] = useState(0)
  /** tabId → the content signature last seen, so a tab dots only on an UNSEEN
   *  change. A ref (not state) because it is bookkeeping, not render input. */
  const seenRef = useRef<Record<string, string>>({})
  const [refresh, setRefresh] = useState(0)
  /** ONE turn in flight at a time, across every surface that can start one — a
   *  scene answer, a choice tap, the act box. Scene answers dispatch from here
   *  (not PlayPage), so without a hoisted lock the play page's own `busy` never
   *  learns a scene already fired and a player can start two concurrent turns. */
  const [turnPending, setTurnPending] = useState(false)
  const turnPendingRef = useRef(false)
  /** Bumped whenever a scene answer resolves without changing scene html, so
   *  every SceneSlot clears its local answered/sending state (a refused answer
   *  otherwise locks its slot on "sending…" forever). */
  const [sceneEpoch, setSceneEpoch] = useState(0)
  /** Which world's deletion is being confirmed, or null. Held here rather than in
   *  the detail view because the reload that follows a deletion unmounts that
   *  view — a dialog owned by it would vanish mid-request. */
  const [doomed, setDoomed] = useState<string | null>(null)
  /** Which life's deletion is being confirmed, or null. */
  const [note, setNote] = useState<string>('')

  // The render language is React state at the root: setting it synchronously here
  // (not in an effect) means a world of a different language re-renders the whole
  // tree already speaking it, rather than one frame late. `t()` reads this module
  // value, so no call site needs a hook.
  //
  // The initial value is the player's own remembered pick (the header dropdown);
  // absent one, the app opens in the Crew's UI language and falls back to English,
  // rather than always zh. Opening a world still follows that world's language
  // until the player makes an explicit pick.
  const [lang, setLangState] = useState<Lang>(
    () => asLang(localStorage.getItem(LANG_KEY) ?? undefined) ?? crewLanguageDefault(),
  )
  // Whether the player made an EXPLICIT choice (the header dropdown). Once they
  // have, it overrides world-follow: opening a world no longer flips the chrome to
  // that world's language. Until they do, the app still follows the world opened.
  const [langLocked, setLangLocked] = useState<boolean>(
    () => localStorage.getItem(LANG_KEY) != null,
  )
  setCurrentLanguage(lang)
  const applyLanguage = useCallback(
    (code?: string) => {
      if (langLocked) return
      const next = asLang(code)
      if (next) setLangState(next)
    },
    [langLocked],
  )
  // The explicit language dropdown: unlike opening a world (which otherwise follows
  // that world's language), this is the player's standing choice, so it persists,
  // locks out world-follow, and becomes the default the app next opens in.
  const chooseLanguage = useCallback((code: string) => {
    const next = asLang(code)
    if (!next) return
    localStorage.setItem(LANG_KEY, next)
    setLangLocked(true)
    setLangState(next)
  }, [])

  const load = useCallback(async () => {
    setError(null)
    try {
      // Fetch the shelf in the reader's language so a world with a variant shows
      // its title and labels translated, not only its authoring language.
      const d = await api.worlds(lang)
      setWorlds(d.worlds)
      setSeeds(d.seeds)
    } catch (e) {
      setError((e as Error).message)
    }
    // A failed run list must not blank the shelf — the worlds are still usable.
    try {
      setRuns((await api.runs()).runs)
    } catch {
      setRuns([])
    }
    // A failed draft list must not blank the shelf either.
    try {
      setDrafts((await api.worldDrafts()).drafts)
    } catch {
      setDrafts([])
    }
  }, [lang])

  useEffect(() => {
    void load()
  }, [load])

  // A world draft being compiled converges on the server; poll the shelf while any
  // is in flight so a returning player watches it finish (main.tsx has no other
  // interval — mirrors play.tsx's generating poll).
  useEffect(() => {
    if (!drafts.some((d) => d.status === 'generating' || d.status === 'new')) {
      return undefined
    }
    const timer = window.setInterval(() => {
      void load()
    }, DRAFT_POLL_MS)
    return () => window.clearInterval(timer)
  }, [drafts, load])

  // Drafts outlive nothing they should: an opening left half-answered for a world
  // that has since been deleted is dead weight in shared localStorage, so it is
  // swept whenever the world list is known.
  useEffect(() => {
    if (!worlds) return
    const live = new Set(worlds.map((w) => w.worldId))
    try {
      for (let i = localStorage.length - 1; i >= 0; i -= 1) {
        const key = localStorage.key(i)
        if (key && key.startsWith(DRAFT_PREFIX) && !live.has(key.slice(DRAFT_PREFIX.length))) {
          localStorage.removeItem(key)
        }
      }
    } catch {
      /* private mode: nothing persisted, nothing to sweep */
    }
  }, [worlds])

  // Restore where the player was.
  useEffect(() => {
    const where = recall()
    if (!where) return
    if (where.view === 'live' && where.runId) {
      const rid = where.runId
      // Verify the life still exists: a remembered life that was since deleted must
      // clear the stale location and land on the shelf, not open a 404 page.
      api
        .run(rid)
        .then((v) => {
          applyLanguage(v.language)
          setLive(rid)
          setView('live')
        })
        .catch(() => {
          forget()
        })
      return
    }
    if (where.view === 'detail' && where.worldId) {
      const wid = where.worldId
      api
        .world(wid)
        .then((w) => {
          applyLanguage(w.language)
          setSelected(wid)
          setView('detail')
        })
        .catch(() => {
          forget()
        })
      return
    }
    // The opening screen is restorable now that its answers are kept with it. Its
    // world has to be re-read, because the screen is driven by the world's own
    // declared groups and those are not the player's to cache.
    if (where.view === 'opening' && where.worldId) {
      api
        .world(where.worldId)
        .then((w) => {
          applyLanguage(w.language)
          setWorld(w)
          setView('opening')
        })
        .catch(() => {
          forget()
        })
      return
    }
    // The paste screen has nothing to re-fetch — its text lives in its own draft.
    if (where.view === 'create') {
      setView('create')
      return
    }
    // A draft under review is re-read; a draft since discarded clears the location.
    if (where.view === 'draft' && where.draftId) {
      const did = where.draftId
      api
        .worldDraft(did)
        .then(() => {
          setReviewDraft(did)
          setView('draft')
        })
        .catch(() => {
          forget()
        })
    }
  }, [applyLanguage])

  // ── browser history: system Back returns to the shelf, not out of the app ──
  // main.tsx navigates by React state, so without this an Android Back / iOS edge
  // swipe exits the dashboard page instead of stepping back a layer (M0.3).
  const prevViewRef = useRef<View>('library')
  const homeRef = useRef<() => void>(() => {})
  useEffect(() => {
    const prev = prevViewRef.current
    prevViewRef.current = view
    // Entering a sub-view from the shelf pushes ONE entry, so Back pops to the
    // shelf. Deeper hops (detail→opening→live) don't stack more — Back from any
    // depth returns home, which is the predictable phone behaviour and avoids a
    // fragile per-hop stack the in-app buttons would fall out of sync with.
    if (prev === 'library' && view !== 'library') {
      try {
        window.history.pushState({ ew: 'subview' }, '')
      } catch {
        /* no-op */
      }
    }
  }, [view])
  useEffect(() => {
    const onPop = () => {
      homeRef.current()
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const home = () => {
    forget()
    setView('library')
    setSelected(null)
    setWorld(null)
    setLive(null)
    setScenes([])
    setReviewDraft(null)
    void load()
  }
  // Keep the popstate listener calling the LATEST home closure without re-binding.
  homeRef.current = home

  // ── creating a world from pasted text ──────────────────────────────────
  const startCreate = () => {
    remember({ view: 'create' })
    setView('create')
  }
  const openDraft = (draftId: string) => {
    remember({ view: 'draft', draftId })
    setReviewDraft(draftId)
    setView('draft')
  }
  /** After submitting the paste, go straight to the review screen — it shows the
   *  worldsmith's progress and then the result; leaving it drops back to the shelf
   *  where the draft card keeps polling. */
  const draftCreated = (draftId: string) => {
    void load()
    openDraft(draftId)
  }
  const backToShelf = () => {
    remember({ view: 'library' })
    setView('library')
    setReviewDraft(null)
    void load()
  }
  const draftInstalled = () => {
    home()
  }
  const discardDraftInline = (draftId: string) => {
    void api
      .discardWorldDraft(draftId)
      .then(() => void load())
      .catch(() => void load())
  }

  const enterLife = (runId: string) => {
    remember({ view: 'live', runId })
    // Picking is the drawer's whole job: it closes on the choice rather than
    // waiting to be dismissed off the page it just navigated away from.
    setLive(runId)
    setView('live')
  }

  // "Live this again": start a fresh life from a prior one's opening picks, then
  // enter it. The opening turn is fired without awaiting — the play page shows the
  // generating state and converges on its own.
  const restartSameOpening = async (fromRunId: string) => {
    try {
      const created = await api.createRun({ fromRunId })
      void api.openRun(created.runId)
      setScenes([])
      enterLife(created.runId)
    } catch {
      /* the ended page is still there; nothing was lost */
    }
  }

  /**
   * After a world is gone.
   *
   * Landing back on the shelf is not decoration: the detail view the player was
   * standing in now describes a world that would answer 404, and the remembered
   * screen would send them straight back to it on the next visit. `home()` clears
   * both.
   */
  const afterDelete = (out: { restorable: boolean; lives: number }) => {
    setDoomed(null)
    setNote(
      (out.lives
        ? t(out.lives === 1 ? 'delete.doneWithLivesOne' : 'delete.doneWithLives', { n: out.lives })
        : t('delete.done')) + (out.restorable ? ' ' + t('delete.doneRestorable') : ''),
    )
    home()
  }

  /**
   * After a life is gone.
   *
   * If the player was standing in it, staying would leave the play page polling a
   * life that answers 404. The shelf is the only honest landing.
   */
  const afterLifeDelete = (turn: number) => {
    setNote(
      turn > 0
        ? t(turn === 1 ? 'life.delete.doneOne' : 'life.delete.done', { n: turn })
        : t('life.delete.doneUnborn'),
    )
    home()
  }

  const restore = async (worldId: string) => {
    setNote('')
    try {
      await api.restoreWorld(worldId)
    } catch (e) {
      setNote((e as Error).message)
      return
    }
    // The seed is copied back by the next listing, not by the restore itself.
    await load()
  }

  /**
   * Opening a world from the rail.
   *
   * This is the reason the single-value `view` had to give a little ground. The
   * rail and the main column are two axes now, so "which world is selected" and
   * "what is being read" are separate facts: clicking a world while a life is open
   * must leave the rail's highlight somewhere honest, which means clearing `live`
   * rather than letting two rows read as current at once.
   */
  const openWorld = (worldId: string) => {
    setLive(null)
    setScenes([])
    setWorld(null)
    setSelected(worldId)
    setView('detail')
    remember({ view: 'detail', worldId })
  }

  /**
   * What the player did in a scene becomes the turn's action — the same road a
   * tapped choice or a typed sentence takes, so a scene is a way of asking rather
   * than a second kind of move.
   */
  const onSceneChoice = useCallback(
    async (sceneId: string, choice: string, nonce: string) => {
      if (!live) return
      // One turn at a time across every surface: the ref (not state) is the gate
      // so two taps in the same frame cannot both pass before a re-render.
      if (turnPendingRef.current) return
      turnPendingRef.current = true
      setTurnPending(true)
      try {
        const out = await api.answerScene(live, sceneId, { choice, nonce })
        if (out.accepted) {
          await api.takeTurn(live, { action: out.action })
        }
      } catch {
        // A dropped request must not strand the player: reloading shows whether the
        // answer landed.
      } finally {
        turnPendingRef.current = false
        setTurnPending(false)
        // Clear every slot's local answered/sending state: a refusal or a dropped
        // request leaves the scene html unchanged, so without this bump the tapped
        // slot would show "sending…" forever. A stale re-tap after a completed
        // turn is harmless — its nonce is spent and the server refuses it.
        setSceneEpoch((n) => n + 1)
        setRefresh((n) => n + 1)
      }
    },
    [live],
  )

  // A life's own name and shelf state. Metadata only, then reload so the list shows
  // the truth rather than an optimistic guess.
  const changeLifeMeta = useCallback(
    async (runId: string, changes: { label?: string; archived?: boolean }) => {
      try {
        await api.setLifeMeta(runId, changes)
      } catch {
        /* a dropped request changes nothing; the reload reflects the real state */
      }
      void load()
    },
    [load],
  )
  const renameLife = useCallback(
    (runId: string, label: string) => {
      void changeLifeMeta(runId, { label })
    },
    [changeLifeMeta],
  )
  const archiveLife = useCallback(
    (runId: string, archived: boolean) => {
      void changeLifeMeta(runId, { archived })
    },
    [changeLifeMeta],
  )
  const [showArchived, setShowArchived] = useState(false)
  const [order, setOrder] = useState<ShelfOrder>(recallOrder)

  // ── bottom tab bar: track viewport, reset per life, build tabs & dots ──
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined
    const mq = window.matchMedia('(max-width: 1100px)')
    const on = () => setIsNarrow(mq.matches)
    on()
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  // A new life always opens on its story, never on a stale system tab — and never
  // with the previous life's sheet still counted as open, which would leave this
  // life's scene frames hidden with nothing on top of them.
  useEffect(() => {
    setTab('reading')
    setSheetOpen(false)
  }, [live])

  const tabs = useMemo(() => buildTabs(scenes, panels), [scenes, panels])
  const narrowLive = isNarrow && view === 'live' && !!live
  const barHidden = useScrollHide(narrowLive, READER_BAR_PIN_PX)

  // A dismissed region must not leave the bar pointing at a tab that is gone.
  useEffect(() => {
    if (narrowLive && !tabs.some((tb) => tb.id === tab)) setTab('reading')
  }, [tabs, tab, narrowLive])

  const sigOf = useCallback(
    (id: string, sceneIds: string[]): string => {
      if (id === 'reading') return `r${liveTurn}`
      if (id === 'starmap') return 's' // the star map never dots
      const sc = sceneIds.map((sid) => {
        const s = scenes.find((x) => x.sceneId === sid)
        return [sid, s?.asks ?? false, s?.answered ?? false]
      })
      const pn = panels
        .filter((p) => (p.region ?? '') === id)
        .map((p) => [p.id, JSON.stringify(p.fields)])
      return JSON.stringify([sc, pn])
    },
    [scenes, panels, liveTurn],
  )

  // Compute dots each render; first sight of a tab records its signature so it
  // does not dot on load, only on a later unseen change.
  const dots: Record<string, boolean> = {}
  for (const tb of tabs) {
    const sig = sigOf(tb.id, tb.sceneIds)
    if (seenRef.current[tb.id] === undefined) seenRef.current[tb.id] = sig
    dots[tb.id] = tb.id !== tab && tb.id !== 'starmap' && seenRef.current[tb.id] !== sig
  }
  // Visiting a tab (or its content changing while it is open) clears its dot.
  useEffect(() => {
    const tb = tabs.find((x) => x.id === tab)
    if (tb) seenRef.current[tab] = sigOf(tab, tb.sceneIds)
  }, [tab, tabs, sigOf])

  const activeSceneIds = tabs.find((tb) => tb.id === tab)?.sceneIds ?? []
  // On a phone a system region hides the story column and shows its frames; the
  // desktop shows everything and never hides the body.
  const hideBody = narrowLive && tab !== 'reading' && tab !== 'starmap'
  /** Whether a scene frame is actually on screen below the shell. The phone's
   *  tab-bar clearance belongs to whatever the page ENDS with: when frames follow
   *  the region pane, padding the pane only opens a gap between the panels and the
   *  map, and leaves the last frame under the bar. */
  const scenesShown = narrowLive && activeSceneIds.length > 0

  let body: React.ReactNode
  if (view === 'perf' && perfRun) {
    body = (
      <PerfPage
        runId={perfRun.runId}
        name={perfRun.name}
        onBack={() => {
          setPerfRun(null)
          setView('library')
        }}
      />
    )
  } else if (view === 'live' && live) {
    body = (
      <PlayPage
        runId={live}
        onBack={home}
        onScenes={setScenes}
        onBackdrop={setBackdrop}
        onReplay={openWorld}
        onReplaySame={restartSameOpening}
        onEnterLife={enterLife}
        refresh={refresh}
        openStar={narrowLive ? tab === 'starmap' : undefined}
        onStarClose={() => setTab('reading')}
        onSheetOpen={setSheetOpen}
        onLiveTurn={setLiveTurn}
        narrow={narrowLive}
        readerBar={narrowLive && !hideBody}
        onPanels={setPanels}
        turnPending={turnPending}
      />
    )
  } else if (view === 'opening' && world) {
    body = <OpeningScreen world={world} onBack={home} onLive={enterLife} />
  } else if (view === 'create') {
    body = <CreateWorldScreen onCancel={backToShelf} onCreated={draftCreated} />
  } else if (view === 'draft' && reviewDraft) {
    body = (
      <WorldDraftReview
        draftId={reviewDraft}
        onInstalled={draftInstalled}
        onDiscarded={backToShelf}
        onBack={backToShelf}
      />
    )
  } else if (selected) {
    body = (
      <WorldDetailView
        worldId={selected}
        onBack={home}
        onDelete={setDoomed}
        initialLanguage={lang}
        onLanguage={applyLanguage}
        onPlay={(w) => {
          remember({ view: 'opening', worldId: w.worldId })
          applyLanguage(w.language)
          setWorld(w)
          setView('opening')
        }}
      />
    )
  } else if (error) {
    body = (
      <div className="ew-meta">
        <div style={{ marginBottom: '6px' }}>{t('library.backendSilent')}</div>
        <div>{t('library.backendHint', { path: '/worlds', error })}</div>
        <div className="ew-bar">
          <button className="ew-btn" type="button" onClick={() => void load()}>
            {t('library.retry')}
          </button>
        </div>
      </div>
    )
  } else if (!worlds) {
    body = <div className="ew-meta">{t('library.preparing')}</div>
  } else {
    // The shelf.
    //
    // On desktop the RAIL is the shelf — it lists the same lives and the same worlds,
    // permanently, in the same order. Rendering the list here as well put it on
    // screen twice side by side, which is exactly what it looked like: "你正在过的
    // 人生" over a column of four rows, and the identical four rows two inches left.
    //
    // The duplicate is therefore hidden at the rail's own width (a CSS decision,
    // because the rail's existence is one), and what stays is the part a rail of
    // names cannot carry: one affordance to continue the most recent life, and the
    // notices about worlds. Those appear nowhere else.
    // Ordered here rather than trusting the server's order, so the two orderings
    // are symmetric: the toggle changes one expression, not one code path that
    // sorts and another that accepts whatever arrived.
    const active = byOrder(
      runs.filter((r) => !r.archived && !r.ended),
      order,
    )
    const endedRuns = byOrder(
      runs.filter((r) => !r.archived && r.ended),
      order,
    )
    const archivedRuns = byOrder(
      runs.filter((r) => r.archived),
      order,
    )
    const newest = active.find((r) => !r.unreadable)
    const rowProps = {
      onOpen: enterLife,
      onDeleted: afterLifeDelete,
      onRename: renameLife,
      onArchive: archiveLife,
      onPerf: (runId: string, name: string) => {
        setPerfRun({ runId, name })
        setView('perf')
      },
    }
    body = (
      <>
        {newest ? (
          <div className="ew-onlywide ew-cont-wrap">
            <div className="ew-section">{t('shelf.continue')}</div>
            <LifeRow run={newest} onOpen={enterLife} />
          </div>
        ) : (
          <div className="ew-onlywide ew-meta">{t('shelf.pick')}</div>
        )}

        <div className="ew-shelflist ew-shelf-lives">
          {active.length ? (
            <>
              <div className="ew-section-row">
                <div className="ew-section">{t('library.lives')}</div>
                {/* One button, not a pair of radios: with exactly two orderings the
                    control that shows the one you would switch TO is smaller, needs
                    no legend, and reads the same at phone width. */}
                <button
                  className="ew-order-toggle"
                  type="button"
                  onClick={() => {
                    const next: ShelfOrder = order === 'recent' ? 'started' : 'recent'
                    setOrder(next)
                    rememberOrder(next)
                  }}
                >
                  {t(order === 'recent' ? 'shelf.orderRecent' : 'shelf.orderStarted')}
                </button>
              </div>
              {active.map((r) => (
                <LifeRow key={r.runId} run={r} {...rowProps} />
              ))}
            </>
          ) : null}

          {endedRuns.length ? (
            <>
              <div className="ew-section" style={{ marginTop: '22px' }}>
                {t('shelf.ended')}
              </div>
              {endedRuns.map((r) => (
                <LifeRow key={r.runId} run={r} {...rowProps} />
              ))}
            </>
          ) : null}

          {archivedRuns.length ? (
            <>
              <button
                className="ew-section ew-section-toggle"
                type="button"
                style={{ marginTop: '22px' }}
                onClick={() => setShowArchived((s) => !s)}
                aria-expanded={showArchived}
              >
                {t('shelf.archived', { n: archivedRuns.length })}
              </button>
              {showArchived
                ? archivedRuns.map((r) => <LifeRow key={r.runId} run={r} {...rowProps} />)
                : null}
            </>
          ) : null}
        </div>

        <div className="ew-shelflist ew-shelf-worlds">
          {runs.length ? <div className="ew-section">{t('library.otherWorlds')}</div> : null}

          {/* The way in to a player-made world — always present, above the shelf. */}
          <CreateWorldCard onClick={startCreate} />
          {drafts.map((d) => (
            <WorldDraftCard
              key={d.draftId}
              draft={d}
              onOpen={openDraft}
              onDiscard={discardDraftInline}
            />
          ))}

          {worlds.length === 0 ? (
            <div className="ew-meta">{t('library.empty')}</div>
          ) : (
            worlds.map((w) => (
              <WorldCard
                key={w.worldId}
                world={w}
                onOpen={openWorld}
                plays={runs.filter((r) => r.worldId === w.worldId).length}
              />
            ))
          )}
        </div>

        {(seeds?.newerAvailable ?? []).map((n) => (
          <div className="ew-note" key={n.worldId}>
            {t('library.newerSeed', {
              world: n.worldId,
              installed: n.installed,
              available: n.available,
            })}
          </div>
        ))}

        {/* A removed world is reported, not silently absent. Without this row the
            player has no way to tell "I deleted that" from "the app lost it", and
            no way back for one that shipped with the app. */}
        {(seeds?.removed ?? []).map((id) => (
          <div className="ew-note ew-note-row" key={'removed-' + id}>
            <span>{t('library.removed', { world: id })}</span>
            <button className="ew-btn ew-btn-quiet" type="button" onClick={() => void restore(id)}>
              {t('library.restore')}
            </button>
          </div>
        ))}
      </>
    )
  }

  // Published as separate class fragments (not one literal): the view and the
  // read measure are distinct facts the stylesheet keys off, and other state (the
  // phone's flush-top reading page) can contribute a class between them. Kept as
  // dedicated statements so each concatenation stays intact and self-documenting.
  const viewClass = 'ew-root ew-view-' + view
  const widthClass = ' ew-w-' + readWidth
  const rootClass =
    viewClass +
    (narrowLive ? ' ew-root-flushtop' : '') +
    widthClass +
    (view === 'library' ? ' ew-home' : '')

  return (
    <LanguageContext.Provider value={applyLanguage}>
      <div className={rootClass} lang={lang} ref={rootRef}>
        {/* Injected rather than imported as a stylesheet: this app mounts into the
          dashboard's document, and a <style> element goes away with the component
          instead of outliving it in the page's stylesheet list. */}
        <style>{styles}</style>

        {/* Full-app backdrop: rendered at the root (not inside the play column) so on
          desktop it spans the rail AND the play area for immersion, and on a phone
          it fills the screen. Only on a live view — the shelf stays plain. */}
        {view === 'live' && live && backdrop ? (
          <Backdrop
            runId={live}
            version={backdrop.version}
            turn={backdrop.turn}
            mobile={backdrop.mobile}
          />
        ) : null}

        {/* Inside a life on a phone the app's own name is dropped. It carries nothing a
          reader needs mid-story — the language picker and Settings live on the shelf,
          not here — and keeping it put a second, differently-coloured band above the
          reading bar, which read as two unrelated headers stacked. Without it the bar
          meets the dashboard's chrome directly and the page starts at the story. */}
        {narrowLive ? null : (
          <div className="ew-head">
            <Glyph />
            <h2>{t('app.title')}</h2>
            {view === 'library' ? (
              <div className="ew-headtools">
                <select
                  className="ew-uilang"
                  aria-label={t('app.language')}
                  value={lang}
                  onChange={(e) => chooseLanguage(e.target.value)}
                >
                  <option value="zh">中文</option>
                  <option value="en">English</option>
                </select>
                <button
                  className="ew-uilang"
                  type="button"
                  onClick={() => setShowSettings((s) => !s)}
                  aria-expanded={showSettings}
                >
                  {t('settings.open')}
                </button>
              </div>
            ) : null}
          </div>
        )}

        {view === 'library' ? <div className="ew-tagline">{t('app.tagline')}</div> : null}

        {view === 'library' && showSettings ? (
          <SettingsPanel onClose={() => setShowSettings(false)} />
        ) : null}

        {note ? (
          <div className="ew-note ew-note-row">
            <span>{note}</span>
            <button className="ew-btn ew-btn-quiet" type="button" onClick={() => setNote('')}>
              {t('note.dismiss')}
            </button>
          </div>
        ) : null}

        {/* One axis, plus a drawer that pushes rather than covers. The rail renders
          nothing below 1100px and nothing at all while closed, so a phone gets
          exactly the layout it had and a desktop gets the whole width for the story
          until it asks for the shelf. */}
        <div className={'ew-shell' + (railOpen ? ' ew-shell-open' : '')}>
          <WorldRail
            worlds={worlds}
            runs={runs}
            activeRunId={live}
            activeWorldId={world?.worldId ?? selected}
            onWorld={openWorld}
            onLife={enterLife}
            onHome={home}
            atShelf={view === 'library'}
            open={railOpen}
            onClose={toggleRail}
            width={readWidth}
            onWidth={chooseWidth}
          />
          <div className="ew-main">
            {/* The desktop's shelf opener, in the same top-left slot the phone puts
              its "back to the shelf" in — that button is hidden at this width, so
              the corner carries one control at every size, not two. */}
            <button
              className="ew-shelfbtn"
              type="button"
              aria-expanded={railOpen}
              onClick={toggleRail}
            >
              {t('rail.open')}
            </button>
            <div
              className="ew-bodywrap"
              style={{
                display: hideBody ? 'none' : undefined,
                // Only the tab bar sits at the foot now — the reading controls stick
                // to the TOP of the pane, so nothing extra is owed down here.
                paddingBottom: narrowLive ? '72px' : undefined,
              }}
            >
              {body}
            </div>
            {view === 'library' && !hideBody ? (
              <div className="ew-version">{t('app.version', { version: __APP_VERSION__ })}</div>
            ) : null}
            {/* A system region tab (phone): the story column is hidden and this
              region's panels stand alone. Its mounted scenes render below, outside
              the shell, filtered to the same region. */}
            {hideBody ? (
              <div
                className="ew-region-pane"
                style={{ paddingBottom: scenesShown ? undefined : '72px' }}
              >
                {panels
                  .filter((p) => (p.region ?? '') === tab)
                  .map((p) => (
                    <PanelBox key={p.id} panel={p} />
                  ))}
              </div>
            ) : null}
          </div>
        </div>

        {/* Outside `body` on purpose, and one frame per mounted scene: each is
          created on first need and never moved or re-keyed, because moving an
          iframe reloads it. The order is the mount order and never re-sorted, so an
          asking scene becoming answered does not shuffle a frame and reload it.

          The wrapper is stable for the whole life of the run, so the frames are
          created inside it and never move: it exists to carry the phone's tab-bar
          clearance, which the shell's own padding cannot reach out here. */}
        {live ? (
          <div className={scenesShown ? 'ew-scenes-clear' : undefined}>
            {scenes.map((s) => (
              <SceneSlot
                key={s.sceneId}
                runId={live}
                sceneId={s.sceneId}
                asks={s.asks}
                visible={!sheetOpen && (!narrowLive || activeSceneIds.includes(s.sceneId))}
                onChoice={onSceneChoice}
                resetSignal={sceneEpoch}
                locked={turnPending}
              />
            ))}
          </div>
        ) : null}
        {doomed ? (
          <DeleteWorldDialog
            worldId={doomed}
            onCancel={() => setDoomed(null)}
            onDeleted={afterDelete}
          />
        ) : null}

        {/* The phone's bottom navigator — sticky at the foot of the app's own scroll
          container (never fixed, which would escape the panel in the dashboard).
          Desktop keeps the WorldRail and never shows this. */}
        {narrowLive ? (
          <WorldTabBar tabs={tabs} active={tab} dots={dots} hidden={barHidden} onSelect={setTab} />
        ) : null}
      </div>
    </LanguageContext.Provider>
  )
}
