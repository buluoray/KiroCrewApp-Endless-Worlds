/** The app's HTTP surface, and the shapes it answers with.
 *
 * The types are written from what the routes actually send. That makes drift a
 * compile error instead of a blank panel — the failure mode this app has already
 * shipped twice, once when a renamed field blanked the whole page.
 */

export const API = '/api/apps/endless-worlds'

/**
 * Fold a `/api/models` payload into the picker's `{ id, name }` rows.
 *
 * Tolerates both a bare array and a `{ models: [...] }` wrapper, and both the
 * `model_id` / `model_name` keys kiro-cli's `--list-models` emits and a plain
 * `id` / `name` — reading the kiro-cli keys FIRST. A row filtering out on a
 * missing `id` is what once left the picker showing only "Default (auto)".
 *
 * Exported so it can fold the response whether it arrives via the App SDK client
 * (`useAppApi().get`) or the bare-fetch fallback below.
 */
export function normalizeModels(raw: unknown): Array<{ id: string; name?: string }> {
  const list = Array.isArray(raw)
    ? raw
    : Array.isArray((raw as { models?: unknown })?.models)
      ? (raw as { models: unknown[] }).models
      : []
  return list
    .map((m) => {
      if (typeof m === 'string') return { id: m }
      const o = m as {
        model_id?: string; model_name?: string; id?: string; name?: string
      }
      const id = o.model_id || o.model_name || o.id || ''
      return { id, name: o.model_name || o.name || id }
    })
    .filter((m) => m && typeof m.id === 'string' && m.id)
}

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
  label: string
  always: boolean
  empty: boolean
  fields: ShapedField[]
  /** The phone system-tab this panel groups under (status/world/pack/tasks or a
   *  world's own word); empty falls into the default 系统 bucket. */
  region?: string
  // Present on a capability-pack panel (composed from primitives, not a template
  // panel). `degraded` marks a pack that could not render and fell back to a
  // labelled value list — never surfaced to the player (R5.9), kept for tooling.
  pack?: boolean
  degraded?: boolean
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
  /** The system tab this scene groups under on a phone (status/world/pack/tasks
   *  or a world's own word); empty falls into the default 系统 bucket. */
  region?: string
  /** Short tab/name the narrator gave this scene's region. */
  label?: string
}

export interface Choice {
  id: string
  label: string
  /** The narrator marks a choice that could lead to a major event or turning
   *  point; the play page gives it a distinctive, ornate look. */
  fateful?: boolean
  /** A tiny narrator-designed SVG (validated server-side), shown as an inert
   *  image behind the button label — the story agent's own special pattern for a
   *  fateful choice. */
  art?: string
}

export interface OpeningReveal {
  label: string
  value: string
}

export interface LifeRecap {
  lastAction: string
  events: string[]
  choices: string[]
}

/** One "an old thing came back" marker on the latest turn. Exists only when the
 *  narrator's structured commit declared the echo — prose that merely reminisces
 *  produces none — so `sourceTurn` is always a real page to jump back to. */
export interface EchoMarker {
  sourceId: string
  sourceTurn: number
  sourceTitle: string
  sourceSummary: string
  /** The player's own words on the source turn, when it came from one. */
  sourceAction: string
  /** The answering event's canonical id — what "collect this echo" cites
   *  alongside the source, so the keepsake holds the whole path. */
  currentId: string
  /** The current event that answers it. */
  title: string
  summary: string
}

// ── the life star map (design §8.3): one sparse payload, three lenses ──

export type StarNodeKind =
  | 'event' | 'character' | 'place' | 'group' | 'object' | 'thread'

export interface StarNode {
  id: string
  kind: StarNodeKind
  /** Events carry turn/title/summary; entities carry name/aliases. */
  turn?: number
  title?: string
  summary?: string
  importance?: string
  action?: string
  name?: string
  aliases?: string[]
  /** Threads only: still unresolved. */
  open?: boolean | null
}

export interface StarEdge {
  from: string
  type: 'participated_in' | 'occurred_at' | 'opened' | 'advanced' | 'resolved' | 'echoes'
  to: string
}

export interface StarRelation {
  from: string
  type: string
  to: string
  level: number
  value: string
  /** The events that produced the current reading — the §4.3 evidence trail. */
  sources: string[]
}

export type MemoryView = 'life' | 'people' | 'keepsakes'

export interface Keepsake {
  id: string
  kind: 'event' | 'echo' | 'excerpt'
  title: string
  thought: string
  cites: string[]
  entities: string[]
  turn: number
  spoiler: boolean
  createdAt: number
  excerpt?: string
  excerptSha256?: string
}

export interface StarPayload {
  runId: string
  turn: number
  nodes: StarNode[]
  edges: StarEdge[]
  relations: StarRelation[]
  keepsakes: Keepsake[]
  /** This life's last-used lens; the smart entry only sets the INITIAL one. */
  view: MemoryView
}

// ── echo story cards (design §8.4): allowlist drafts, narrow-only edits ──

export interface CardEvent {
  id: string
  turn: number
  title: string
  summary: string
  action: string
  excerpt: string
  included: boolean
}

export interface CardEntity {
  id: string
  kind: string
  /** The real name, shown only in the editor. */
  name: string
  /** What the export prints — editing this IS anonymisation. */
  display: string
  included: boolean
}

export interface StoryCard {
  id: string
  keepsakeId: string
  title: string
  coverLine: string
  thought: string
  language: 'zh' | 'en'
  showSpoilers: boolean
  endedTurn: number
  events: CardEvent[]
  entities: CardEntity[]
  edges: StarEdge[]
  createdAt: number
  updatedAt: number
}

/** What the export will actually contain — rendered by the same resolver. */
export interface CardPreview {
  title: string
  coverLine: string
  thought: string
  language: string
  events: CardEvent[]
  entities: CardEntity[]
  edges: StarEdge[]
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
  /** This world declares continuity (§9): the ending page may offer the bridge. */
  lineage: boolean
  /** Chapter headings the world opened this month, in its own words. The play page
   *  shows them as a quiet "a new chapter opens" marker. */
  unlocked: string[]
  /** Milestones (achievement labels) reached THIS month — shown as a marker. */
  milestonesReached: string[]
  /** Every milestone reached so far, for the ending recap. */
  milestones: string[]
  /** Which declared ending this life reached, or the narrator's own marker. Empty
   *  while the life continues. The play page shows a terminal screen when set. */
  endingId: string
  /** Values the world, rather than the player, settled for this life at birth. */
  reveals: OpeningReveal[]
  /** Declared echoes on the latest turn — each traceable to a real past page. */
  echoes: EchoMarker[]
  /** Existing chronicle facts used to restore a returning player's place. */
  recap: LifeRecap
  /** Set while a narrator is writing this month — recorded on the server before it
   *  is asked, so it survives the page that asked. Null when nothing is in flight. */
  generating: {
    turn: number
    slot: string
    askedAt: number
    /** When the narrator called endless_read_runtime (0 if not yet). */
    readAt?: number
    /** Coarse in-flight stage: 'reading' the life, then 'writing' the month. */
    stage?: 'reading' | 'writing'
    /** How many tool calls the narrator has made this turn (advances per call). */
    steps?: number
    /** The narrator's most recent tool call, for a per-step label. */
    lastTool?: string
  } | null
  /** The WORLD's language, so the play view speaks the language its rulebook is
   *  written in. Declared here because the route sends it; it was previously read
   *  through a type assertion, which compiled while the field did not exist. */
  language: string
  awaitingOpening: boolean
  choices: Choice[]
  digest: DigestRow[]
  panels: PanelView[]
  scenes: SceneRow[]
  /** The narrator-set background for this life, or null. `buttons` is true when a
   *  common choice-button motif was set with it (loaded via ?part=buttons). */
  backdrop: { version: number; buttons?: boolean } | null
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
  /** A world-authored reason to imagine a life here, shown on the shelf. */
  cardPromise?: string
  /** Concrete lives or consequences this world invites the player to imagine. */
  cardPossibilities?: string[]
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
    label: string
    always: boolean
    when: string | null
    fields: Array<{ id: string; label: string; primitive: Primitive }>
  }>
  digest: string[]
  endings: string[]
  save: string[]
  /** The world's setting as structure — public entries (no reveal gate), for the
   *  reader's setting view. Grouped by `category`; `relations` are edges by id. */
  lore: LoreEntry[]
  /** Starting archetypes the world offers; picking one presets the opening and
   *  seeds initial state from its grants (grants stay server-side). */
  roles: RoleRow[]
  prose?: string
}

export interface RoleRow {
  id: string
  name: string
  summary: string
}

export interface LoreEntry {
  id: string
  name: string
  summary: string
  category: string
  text: string
  relations: Array<{ to: string; label?: string }>
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
  /** The life's narrator backdrop version, so the shelf card can show the same
   *  background the play page does. Null/absent = plain card. */
  backdrop?: { version: number } | null
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
  /** The backdrop that was effective on this page, so re-reading it restores the
   *  scene it had. Null when the page had no background. */
  backdrop?: { version: number } | null
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
/** A world being built from pasted text — a row on the shelf while it compiles. */
export type WorldDraftStatus = 'new' | 'generating' | 'ready' | 'failed' | 'installed'

export interface WorldDraftRow {
  draftId: string
  title: string
  status: WorldDraftStatus
  steps: number
  lastTool: string
  stage: string
  problem: string
}

/** What the compiled world will contain — the review payload, in the world's own
 *  words (mirrors backend compile.preview). */
export interface WorldPreview {
  title: string
  promise: string
  possibilities: string[]
  language: string
  clock: string
  lineage: boolean
  styles: string[]
  chapters: Array<{ heading: string; brief: boolean; when: string }>
  opening: string[]
  panels: Array<{ label: string; always: boolean; fields: string[] }>
  digest: string[]
  endings: number
}

export interface WorldDraftDetail {
  draftId: string
  title: string
  status: WorldDraftStatus
  steps: number
  stage: string
  lastTool: string
  problem: string
  field: string
  worldId: string
  preview: WorldPreview | null
  warnings: string[]
  /** What the worldsmith removed as unplayable, so the review can show it. */
  dropped: string[]
  /** The worldsmith's chat-slot key, so the UI can offer a jump-to-chat. */
  slotKey: string
}

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

function send<T>(method: 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T> {
  return json<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export const api = {
  worlds: (language?: string) =>
    json<{ worlds: WorldRow[]; seeds: SeedReport }>(
      `/worlds${language ? `?language=${encodeURIComponent(language)}` : ''}`,
    ),
  settings: () =>
    json<{ model: string; reasoningEffort: string; efforts: string[] }>('/settings'),
  saveSettings: (body: { model: string; reasoningEffort: string }) =>
    json<{ model: string; reasoningEffort: string }>('/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  /** The gateway's advertised model list. `/api/models` is a CORE dashboard
   *  route (not under the app base), so the app's path-scoped session cookie does
   *  NOT authorize it — the App SDK client (`useAppApi().get`) is the authorized
   *  path (it injects an app token and gates on the declared `permissions.api`).
   *  This bare-fetch helper is the fallback for a host too old to expose the SDK;
   *  it returns [] rather than throwing when the list is unavailable, so the
   *  picker degrades to "keep default". */
  models: async (): Promise<Array<{ id: string; name?: string }>> => {
    try {
      const res = await fetch('/api/models')
      if (!res.ok) return []
      return normalizeModels(await res.json())
    } catch {
      return []
    }
  },
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

  // ── world drafts: paste → worldsmith cleans+compiles → review → install ──
  worldDrafts: () => json<{ drafts: WorldDraftRow[] }>('/world-drafts'),
  worldDraft: (id: string) =>
    json<WorldDraftDetail>(`/world-drafts/${encodeURIComponent(id)}`),
  createWorldDraft: (text: string, title = '') =>
    post<{ draftId: string }>('/world-drafts', { text, title }),
  compileWorldDraft: (id: string) =>
    post<{ dispatched: boolean; reason?: string }>(
      `/world-drafts/${encodeURIComponent(id)}/compile`, {},
    ),
  /** Optional `title` renames the world's display title before installing it. */
  installWorldDraft: (id: string, title = '') =>
    post<{ worldId: string }>(
      `/world-drafts/${encodeURIComponent(id)}/install`, title ? { title } : {},
    ),
  discardWorldDraft: (id: string) =>
    send<{ deleted: boolean }>('DELETE', `/world-drafts/${encodeURIComponent(id)}`),
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
      /** A chosen starting archetype (`WorldDetail.roles[].id`); presets the
       *  opening and seeds initial state from its grants, server-side. */
      role?: string
      /** Which language to live this life in — one of the world's `languages`.
       *  Binds the run to that language's rulebook and UI for its whole life. */
      language?: string
      /** Copy a prior life's opening picks as the starting point. */
      fromRunId?: string
      /** The legacy bridge (§9): carry a finished life's chosen inheritance in.
       *  Refused unless the world declares lineage and the source life ended. */
      legacy?: { fromRunId: string; selected: string[] }
    },
  ) => post<{ runId: string }>('/runs', body),

  /** What a finished life may pass on, grouped by category (§9 step 1). */
  legacyCandidates: (runId: string) =>
    json<{
      runId: string
      worldId: string
      candidates: Record<string, Array<{
        id: string
        kind: string
        name: string
        summary: string
        appearances: number
        relations?: Array<{ type: string; level: number; value: string }>
        open?: boolean
      }>>
    }>(`/runs/${encodeURIComponent(runId)}/legacy/candidates`),

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

  /** The compiled background HTML for a life, as text for a sandbox frame's
   *  srcdoc. Throws on any non-2xx (incl. 404 = no backdrop) so the caller
   *  simply shows no background. */
  backdrop: async (runId: string): Promise<string> => {
    const res = await fetch(`${API}/runs/${encodeURIComponent(runId)}/backdrop`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.text()
  },

  answerScene: (runId: string, sceneId: string, body: { choice: string; nonce: string }) =>
    post<{ accepted: boolean; action?: string; reason?: string }>(
      `/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}/answer`, body,
    ),

  /** The sparse graph all three star-map lenses share — one request per open. */
  star: (runId: string) =>
    json<StarPayload>(`/runs/${encodeURIComponent(runId)}/memory/star`),

  /** Remember this life's last-used lens. Fire-and-forget metadata. */
  setMemoryView: (runId: string, view: MemoryView) =>
    send<{ runId: string; view: MemoryView }>(
      'PATCH', `/runs/${encodeURIComponent(runId)}/preferences/memory-view`, { view },
    ),

  createKeepsake: (
    runId: string,
    body: {
      kind: Keepsake['kind']
      title: string
      cites?: string[]
      entities?: string[]
      thought?: string
      excerpt?: string
      turn?: number
      spoiler?: boolean
    },
  ) => post<Keepsake>(`/runs/${encodeURIComponent(runId)}/keepsakes`, body),

  updateKeepsake: (
    runId: string,
    keepsakeId: string,
    body: { title?: string; thought?: string; spoiler?: boolean },
  ) =>
    send<Keepsake>(
      'PATCH',
      `/runs/${encodeURIComponent(runId)}/keepsakes/${encodeURIComponent(keepsakeId)}`,
      body,
    ),

  deleteKeepsake: (runId: string, keepsakeId: string) =>
    send<{ deleted: string }>(
      'DELETE',
      `/runs/${encodeURIComponent(runId)}/keepsakes/${encodeURIComponent(keepsakeId)}`,
    ),

  /** Turn a keepsake into an editable story-card draft (allowlist fixed here). */
  previewStoryCard: (runId: string, keepsakeId: string) =>
    post<{ card: StoryCard; preview: CardPreview }>(
      `/runs/${encodeURIComponent(runId)}/story-cards/preview`, { keepsakeId },
    ),

  /** Narrow, relabel, reorder — the server refuses anything additive. */
  editStoryCard: (
    runId: string,
    cardId: string,
    body: {
      title?: string
      coverLine?: string
      thought?: string
      showSpoilers?: boolean
      language?: 'zh' | 'en'
      order?: string[]
      events?: Record<string, boolean>
      entities?: Record<string, { included?: boolean; display?: string }>
    },
  ) =>
    send<{ card: StoryCard; preview: CardPreview }>(
      'PATCH',
      `/runs/${encodeURIComponent(runId)}/story-cards/${encodeURIComponent(cardId)}`,
      body,
    ),

  /** The browser downloads this URL directly; auth rides on the cookie. */
  storyCardExportUrl: (runId: string, cardId: string, format: 'html' | 'md' | 'svg') =>
    `${API}/runs/${encodeURIComponent(runId)}/story-cards/${encodeURIComponent(cardId)}/export?format=${format}`,
}
