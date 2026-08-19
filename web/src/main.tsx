import { useCallback, useEffect, useRef, useState } from 'react'

import type { LifeRowData, SceneRow, SeedReport, WorldDetail, WorldRow } from './api'
import { api } from './api'
import { DeleteLifeDialog, DeleteWorldDialog } from './confirm'
import { LifeRow, WorldCard, WorldDetailView } from './library'
import { DRAFT_PREFIX, OpeningScreen } from './opening'
import { PlayPage } from './play'
import { WorldRail } from './rail'
import { SceneSlot } from './scene'
import { SettingsPanel } from './settings'
import styles from './styles.css?raw'
import { asLang, LanguageContext, setCurrentLanguage, t, type Lang } from './strings'
import { Glyph } from './ui'

/** Where the player was, so leaving the page does not throw them back to the
 *  shelf. Prefixed because this app mounts inside the dashboard's own document
 *  and shares its localStorage. */
const WHERE = 'endless-worlds:where'

/** The player's standing UI-language pick from the header dropdown. Prefixed and
 *  shared with the dashboard document like every other key this app keeps. */
const LANG_KEY = 'endless-worlds:lang'

type View = 'library' | 'detail' | 'opening' | 'live'

interface Where {
  view: View
  runId?: string
  worldId?: string
}

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

  const [view, setView] = useState<View>('library')
  const [showSettings, setShowSettings] = useState(false)
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
  const [refresh, setRefresh] = useState(0)
  /** Which world's deletion is being confirmed, or null. Held here rather than in
   *  the detail view because the reload that follows a deletion unmounts that
   *  view — a dialog owned by it would vanish mid-request. */
  const [doomed, setDoomed] = useState<string | null>(null)
  /** Which life's deletion is being confirmed, or null. */
  const [doomedLife, setDoomedLife] = useState<string | null>(null)
  const [note, setNote] = useState<string>('')

  // The render language is React state at the root: setting it synchronously here
  // (not in an effect) means a world of a different language re-renders the whole
  // tree already speaking it, rather than one frame late. `t()` reads this module
  // value, so no call site needs a hook.
  //
  // The initial value is the player's own remembered pick (the header dropdown),
  // so the shelf opens in the language they chose last rather than always zh.
  const [lang, setLangState] = useState<Lang>(
    () => asLang(localStorage.getItem(LANG_KEY) ?? undefined) ?? 'zh',
  )
  // Whether the player made an EXPLICIT choice (the header dropdown). Once they
  // have, it overrides world-follow: opening a world no longer flips the chrome to
  // that world's language. Until they do, the app still follows the world opened.
  const [langLocked, setLangLocked] = useState<boolean>(
    () => localStorage.getItem(LANG_KEY) != null,
  )
  setCurrentLanguage(lang)
  const applyLanguage = useCallback((code?: string) => {
    if (langLocked) return
    const next = asLang(code)
    if (next) setLangState(next)
  }, [langLocked])
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
  }, [lang])

  useEffect(() => { void load() }, [load])

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
      api.run(rid)
        .then((v) => { applyLanguage(v.language); setLive(rid); setView('live') })
        .catch(() => { forget() })
      return
    }
    if (where.view === 'detail' && where.worldId) {
      const wid = where.worldId
      api.world(wid)
        .then((w) => { applyLanguage(w.language); setSelected(wid); setView('detail') })
        .catch(() => { forget() })
      return
    }
    // The opening screen is restorable now that its answers are kept with it. Its
    // world has to be re-read, because the screen is driven by the world's own
    // declared groups and those are not the player's to cache.
    if (where.view === 'opening' && where.worldId) {
      api.world(where.worldId)
        .then((w) => { applyLanguage(w.language); setWorld(w); setView('opening') })
        .catch(() => { forget() })
    }
  }, [applyLanguage])

  const home = () => {
    forget()
    setView('library')
    setSelected(null)
    setWorld(null)
    setLive(null)
    setScenes([])
    void load()
  }

  const enterLife = (runId: string) => {
    remember({ view: 'live', runId })
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
      (out.lives ? t('delete.doneWithLives', { n: out.lives }) : t('delete.done'))
      + (out.restorable ? ' ' + t('delete.doneRestorable') : ''),
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
    setDoomedLife(null)
    setNote(turn > 0 ? t('life.delete.done', { n: turn }) : t('life.delete.doneUnborn'))
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
      try {
        const out = await api.answerScene(live, sceneId, { choice, nonce })
        if (!out.accepted) {
          setRefresh((n) => n + 1)
          return
        }
        await api.takeTurn(live, { action: out.action })
      } catch {
        // A dropped request must not strand the player: reloading shows whether the
        // answer landed.
      }
      setRefresh((n) => n + 1)
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
    (runId: string, label: string) => { void changeLifeMeta(runId, { label }) },
    [changeLifeMeta],
  )
  const archiveLife = useCallback(
    (runId: string, archived: boolean) => { void changeLifeMeta(runId, { archived }) },
    [changeLifeMeta],
  )
  const [showArchived, setShowArchived] = useState(false)

  let body: React.ReactNode
  if (view === 'live' && live) {
    body = <PlayPage runId={live} onBack={home} onScenes={setScenes} onReplay={openWorld} onReplaySame={restartSameOpening} onEnterLife={enterLife} refresh={refresh} />
  } else if (view === 'opening' && world) {
    body = <OpeningScreen world={world} onBack={home} onLive={enterLife} />
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
    const active = runs.filter((r) => !r.archived && !r.ended)
    const endedRuns = runs.filter((r) => !r.archived && r.ended)
    const archivedRuns = runs.filter((r) => r.archived)
    const newest = active.find((r) => !r.unreadable)
    const rowProps = {
      onOpen: enterLife,
      onDelete: setDoomedLife,
      onRename: renameLife,
      onArchive: archiveLife,
    }
    body = (
      <>
        {newest ? (
          <div className="ew-onlywide">
            <div className="ew-section">{t('shelf.continue')}</div>
            <LifeRow run={newest} onOpen={enterLife} />
          </div>
        ) : (
          <div className="ew-onlywide ew-meta">{t('shelf.pick')}</div>
        )}

        <div className="ew-shelflist">
          {active.length ? (
            <>
              <div className="ew-section">{t('library.lives')}</div>
              {active.map((r) => <LifeRow key={r.runId} run={r} {...rowProps} />)}
            </>
          ) : null}

          {endedRuns.length ? (
            <>
              <div className="ew-section" style={{ marginTop: '22px' }}>
                {t('shelf.ended')}
              </div>
              {endedRuns.map((r) => <LifeRow key={r.runId} run={r} {...rowProps} />)}
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

          {runs.length ? (
            <div className="ew-section" style={{ marginTop: '22px' }}>
              {t('library.otherWorlds')}
            </div>
          ) : null}

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
              world: n.worldId, installed: n.installed, available: n.available,
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

  return (
    <LanguageContext.Provider value={applyLanguage}>
    <div className="ew-root" lang={lang} ref={rootRef}>
      {/* Injected rather than imported as a stylesheet: this app mounts into the
          dashboard's document, and a <style> element goes away with the component
          instead of outliving it in the page's stylesheet list. */}
      <style>{styles}</style>

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

      {/* Two axes, not one. The rail renders nothing below 1100px, so a phone gets
          exactly the layout it had; a desktop gets navigation that does not have to
          replace what is being read. */}
      <div className="ew-shell">
        <WorldRail
          worlds={worlds}
          runs={runs}
          activeRunId={live}
          activeWorldId={world?.worldId ?? selected}
          onWorld={openWorld}
          onLife={enterLife}
          onHome={home}
          atShelf={view === 'library'}
        />
        <div className="ew-main">{body}</div>
      </div>

      {/* Outside `body` on purpose, and one frame per mounted scene: each is
          created on first need and never moved or re-keyed, because moving an
          iframe reloads it. The order is the mount order and never re-sorted, so an
          asking scene becoming answered does not shuffle a frame and reload it. */}
      {live ? scenes.map((s) => (
        <SceneSlot key={s.sceneId} runId={live} sceneId={s.sceneId} onChoice={onSceneChoice} />
      )) : null}
      {doomed ? (
        <DeleteWorldDialog
          worldId={doomed}
          onCancel={() => setDoomed(null)}
          onDeleted={afterDelete}
        />
      ) : null}

      {doomedLife ? (
        <DeleteLifeDialog
          runId={doomedLife}
          onCancel={() => setDoomedLife(null)}
          onDeleted={afterLifeDelete}
        />
      ) : null}
    </div>
    </LanguageContext.Provider>
  )
}
