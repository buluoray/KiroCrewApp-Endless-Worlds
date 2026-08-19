/** The app's HTTP surface, and the shapes it answers with.
 *
 * The types are written from what the routes actually send. That makes drift a
 * compile error instead of a blank panel — the failure mode this app has already
 * shipped twice, once when a renamed field blanked the whole page.
 */

export const API = '/api/apps/endless-worlds'

export type Primitive =
  | 'field' | 'stat' | 'rank' | 'people' | 'trend' | 'resource' | 'inventory' | 'threads'

export interface ShapedField {
  id: string
  label: string
  primitive: Primitive
  options: Record<string, unknown>
  kind: 'gap' | 'lines' | Primitive
  value?: unknown
  max?: number | null
  pct?: number | null
  note?: string
  /** A rank's tier name. Called `tier` and deliberately NOT `label`: the shaped
   *  values are spread over the field's own declared `label`, so that name does not
   *  add a label, it deletes the one the world gave the field. */
  tier?: string
  direction?: string
  /** People/threads rows. People rows may carry declared attribute columns under
   *  `cols`; threads rows use text/status. */
  entries?: Array<{
    name?: string; note?: string; text?: string; status?: string
    cols?: Record<string, string>
  }>
  /** The attribute column names a `people` field declared, in order. */
  columns?: string[]
  /** Inventory items with the count and note the narrator wrote. */
  items?: Array<{ name: string; count?: string; note?: string }>
  /** Readable lines for a scalar field the narrator handed a structured value. */
  lines?: string[]
}

export interface PanelView {
  id: string
  always: boolean
  empty: boolean
  fields: ShapedField[]
}

export interface DigestRow {
  category: string
  text: string
  rumour: boolean
}

export interface SceneRow {
  sceneId: string
  asks: boolean
  answered: boolean
}

export interface Choice {
  id: string
  label: string
}

export interface PlayView {
  runId: string
  worldId: string
  title: string
  turn: number
  clock: string
  prose: string
  style: string
  ended: boolean
  /** Chapter headings the world opened this month, in its own words. The play page
   *  shows them as a quiet "a new chapter opens" marker. */
  unlocked: string[]
  /** Which declared ending this life reached, or the narrator's own marker. Empty
   *  while the life continues. The play page shows a terminal screen when set. */
  endingId: string
  /** Set while a narrator is writing this month — recorded on the server before it
   *  is asked, so it survives the page that asked. Null when nothing is in flight. */
  generating: { turn: number; slot: string; askedAt: number } | null
  /** The WORLD's language, so the play view speaks the language its rulebook is
   *  written in. Declared here because the route sends it; it was previously read
   *  through a type assertion, which compiled while the field did not exist. */
  language: string
  awaitingOpening: boolean
  choices: Choice[]
  digest: DigestRow[]
  panels: PanelView[]
  scenes: SceneRow[]
}

export interface OpeningGroup {
  id: string
  label: string
  kind: 'pick' | 'text' | 'number'
  options: string[]
  custom: boolean
  /** A rule of the world, not a convenience: the UI must not offer a picker. */
  worldDecides: boolean
}

export interface StyleRow {
  id: string
  label: string
  default: boolean
}

export interface WorldRow {
  worldId: string
  title: string
  usable: boolean
  lineage?: boolean
  stale?: boolean
  stalenessNote?: string
  clockUnit?: string
  styles?: string[]
  panelCount?: number
  openingGroups?: number
  language?: string
  /** Every language this world can be played in, its primary first. A world with
   *  more than one lets the player pick before living a life in it. */
  languages?: string[]
  problem?: string
  needsCore?: number
  localCore?: number
  field?: string
}

export interface WorldDetail extends WorldRow {
  opening: OpeningGroup[]
  /** Objects, distinct from `WorldRow.styles` which is the labels only. */
  styleRows: StyleRow[]
  panels: Array<{
    id: string
    always: boolean
    when: string | null
    fields: Array<{ id: string; label: string; primitive: Primitive }>
  }>
  digest: string[]
  endings: string[]
  save: string[]
  prose?: string
}

export interface LifeRowData {
  runId: string
  worldId: string
  title: string
  style: string
  turn: number
  lastPlayed: number
  awaitingOpening?: boolean
  ended?: boolean
  unreadable?: boolean
  /** What tells this life apart from another in the same world — the player's own
   *  opening answers. Empty when the life has nothing distinguishing it yet. */
  subtitle?: string
  /** A player-chosen name for this life, shown instead of the derived subtitle. */
  label?: string
  /** Folded out of the active shelf into the archived group. */
  archived?: boolean
  /** A month being written right now. The shelf marks it so a life in progress is
   *  not mistaken for one that stalled. */
  generating?: boolean
}

export interface PastTurn {
  turn: number
  prose: string
  /** The player's own words for that month, when it came from a choice or typed
   *  action. Empty for the opening, which nobody chose. */
  action: string
  /** What the month marked notable — the material of an events-only timeline. */
  events: string[]
  /** What the month credited a gain to, with its source when the narrator named one. */
  gains: Array<{ field: string; amount: string; source: string }>
}

export interface Chronicle {
  runId: string
  /** Newest first — the direction a life is re-read in. */
  turns: PastTurn[]
  more: boolean
}

export interface SeedReport {
  installed: string[]
  alreadyPresent: string[]
  newerAvailable: Array<{ worldId: string; installed: string; available: string }>
  failed: Array<{ seed: string; problem: string }>
  /** Worlds the player removed. Present so the shelf can offer the way back for a
   *  seed-backed world instead of leaving it looking lost. */
  removed: string[]
}

/**
 * What ending ONE life would cost, as the server sees it right now.
 *
 * `unreadable` is the field that matters most here: a life whose world cannot be
 * resolved answers 422 from the play page, so it is reachable ONLY from the shelf —
 * and it is exactly the life a player most wants gone.
 */
export interface LifeDeletionFacts {
  runId: string
  turn: number
  unreadable: boolean
  title?: string
  worldId?: string
  subtitle?: string
  ended?: boolean
  generating?: boolean
}

/** One life that a world's deletion would end. */
export interface DoomedLife {
  runId: string
  title: string
  turn: number
  subtitle?: string
  ended?: boolean
  unreadable?: boolean
  generating?: boolean
}

/**
 * What deleting a world would cost, as the server sees it right now.
 *
 * Fetched fresh when the dialog opens rather than derived from the shelf's rows: a
 * confirmation is only worth anything if the number it names is the number the
 * delete will actually act on.
 */
export interface DeletionFacts {
  worldId: string
  title: string
  lives: DoomedLife[]
  liveCount: number
  /** A month is being written in this world — the delete will be refused. */
  generating: boolean
  /** A seed exists, so the world (as it shipped, without edits) can come back. */
  restorable: boolean
  onShelf: boolean
}

/**
 * A failed request, with the server's own answer kept.
 *
 * The previous helper threw `new Error('HTTP 409')` and dropped the body, which is
 * fine while every failure is just "it did not work". Deletion is not: its 409s
 * carry the reason (the lives changed under you / a month is being written) and the
 * refreshed facts the dialog has to re-render. A code the UI cannot read is a
 * message the player never gets.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: Record<string, unknown>,
  ) {
    super(`HTTP ${status}`)
    this.name = 'ApiError'
  }

  /** The server's machine-readable reason, or '' when it sent none. */
  get code(): string {
    return typeof this.body.code === 'string' ? this.body.code : ''
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    let body: Record<string, unknown> = {}
    try {
      body = (await res.json()) as Record<string, unknown>
    } catch {
      // A non-JSON error body (a proxy's HTML, an empty 500) leaves the status as
      // the only fact — which is still the fact callers branch on.
    }
    throw new ApiError(res.status, body)
  }
  return (await res.json()) as T
}

function post<T>(path: string, body: unknown): Promise<T> {
  return json<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
}

export const api = {
  worlds: (language?: string) =>
    json<{ worlds: WorldRow[]; seeds: SeedReport }>(
      `/worlds${language ? `?language=${encodeURIComponent(language)}` : ''}`,
    ),
  world: (id: string, prose = false, language?: string) => {
    const q = new URLSearchParams()
    if (prose) q.set('prose', '1')
    if (language) q.set('language', language)
    const qs = q.toString()
    return json<WorldDetail>(`/worlds/${encodeURIComponent(id)}${qs ? `?${qs}` : ''}`)
  },

  worldDeletion: (id: string) =>
    json<DeletionFacts>(`/worlds/${encodeURIComponent(id)}/deletion`),

  /** `lives` is a precondition, not a parameter: it must match what the dialog
   *  showed, or the server refuses with 409 rather than ending a life the player
   *  was never told about. */
  deleteWorld: (id: string, lives: number) =>
    post<{ worldId: string; livesRemoved: string[]; restorable: boolean }>(
      `/worlds/${encodeURIComponent(id)}/delete`, { confirm: id, lives },
    ),

  lifeDeletion: (runId: string) =>
    json<LifeDeletionFacts>(`/runs/${encodeURIComponent(runId)}/deletion`),

  /** `turn` is a precondition, not a parameter: it must match the month the dialog
   *  showed, or the server refuses rather than erasing more story than the player
   *  was told about. */
  deleteLife: (runId: string, turn: number) =>
    post<{ runId: string; deleted: boolean; turn: number }>(
      `/runs/${encodeURIComponent(runId)}/delete`, { confirm: runId, turn },
    ),

  /** A player's own name and shelf state for a life — metadata only, never the
   *  story. Pass `label: ""` to clear a custom name. */
  setLifeMeta: (runId: string, body: { label?: string; archived?: boolean }) =>
    post<{ runId: string; label?: string; archived?: boolean }>(
      `/runs/${encodeURIComponent(runId)}/meta`, body,
    ),

  restoreWorld: (id: string) =>
    post<{ worldId: string; restored: boolean }>(
      `/worlds/${encodeURIComponent(id)}/restore`, {},
    ),
  runs: () => json<{ runs: LifeRowData[] }>('/runs'),
  run: (id: string) => json<PlayView>(`/runs/${encodeURIComponent(id)}`),

  /** The months already lived. `before` is a turn NUMBER, not an offset: an offset
   *  would shift under a turn committed between two pages and silently skip or
   *  repeat a month. `q` filters the whole life by substring before paging. */
  chronicle: (id: string, before = 0, q = '', limit = 0) => {
    const p = new URLSearchParams()
    if (before > 0) p.set('before', String(before))
    if (q) p.set('q', q)
    if (limit > 0) p.set('limit', String(limit))
    const qs = p.toString()
    return json<Chronicle>(
      `/runs/${encodeURIComponent(id)}/chronicle${qs ? `?${qs}` : ''}`,
    )
  },

  createRun: (
    body: {
      worldId?: string
      style?: string
      answers?: Record<string, string>
      /** Which language to live this life in — one of the world's `languages`.
       *  Binds the run to that language's rulebook and UI for its whole life. */
      language?: string
      /** Copy a prior life's opening picks as the starting point. */
      fromRunId?: string
    },
  ) => post<{ runId: string }>('/runs', body),

  openRun: (id: string) =>
    post<{ advanced: boolean; reason: string; turn: number }>(
      `/runs/${encodeURIComponent(id)}/open`, {},
    ),

  takeTurn: (id: string, body: { turn?: number; action?: string }) =>
    post<{ advanced: boolean; reason: string; turn: number }>(
      `/runs/${encodeURIComponent(id)}/turn`, body,
    ),

  scene: async (runId: string, sceneId: string): Promise<string> => {
    const res = await fetch(
      `${API}/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}`,
    )
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.text()
  },

  answerScene: (runId: string, sceneId: string, body: { choice: string; nonce: string }) =>
    post<{ accepted: boolean; action?: string; reason?: string }>(
      `/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}/answer`, body,
    ),
}
