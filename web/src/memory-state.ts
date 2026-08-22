/** Shared state for the life star map's three lenses (design §8.3.3).
 *
 * One payload, three layouts: everything a lens needs beyond geometry lives
 * here so that switching views preserves the selected node, the filters and
 * the detail panel — the §12.4 consistency bar. Layouts receive this state and
 * render; they never own it.
 *
 * Strings are module-local rather than in the app's shared string tables only
 * because those JSON files are concurrently owned by other in-flight work; the
 * shape mirrors the shared tables so a later merge is a cut-and-paste.
 */

import type { StarEdge, StarNode, StarPayload } from './api'

export type Lens = 'life' | 'people' | 'keepsakes'

/** Node-kind filters shared by every lens; hiding is a view act, never a data act. */
export interface StarFilters {
  characters: boolean
  places: boolean
  groups: boolean
  objects: boolean
  threads: boolean
}

export const ALL_FILTERS: StarFilters = {
  characters: true, places: true, groups: true, objects: true, threads: true,
}

const KIND_TO_FILTER: Record<string, keyof StarFilters> = {
  character: 'characters', place: 'places', group: 'groups',
  object: 'objects', thread: 'threads',
}

export function nodeVisible(node: StarNode, filters: StarFilters): boolean {
  if (node.kind === 'event') return true
  const key = KIND_TO_FILTER[node.kind]
  return key ? filters[key] : true
}

/** The nodes adjacent to `id`, for the detail panel's one-hop expansion. */
export function neighbours(payload: StarPayload, id: string): StarNode[] {
  const wanted = new Set<string>()
  for (const e of payload.edges) {
    if (e.from === id) wanted.add(e.to)
    if (e.to === id) wanted.add(e.from)
  }
  return payload.nodes.filter((n) => wanted.has(n.id))
}

export function nodeById(payload: StarPayload, id: string): StarNode | undefined {
  return payload.nodes.find((n) => n.id === id)
}

/** A node's display name, whatever its kind. */
export function nodeLabel(node: StarNode): string {
  return node.kind === 'event' ? (node.title ?? node.id) : (node.name ?? node.id)
}

/** Echo edges touching `id` — the lines every lens draws emphasised. */
export function echoEdges(payload: StarPayload): StarEdge[] {
  return payload.edges.filter((e) => e.type === 'echoes')
}

// ── module-local strings (zh complete, en complete, en is the fallback) ──

const TABLES: Record<'zh' | 'en', Record<string, string>> = {
  zh: {
    'star.title': '人生星图',
    'star.close': '返回故事',
    'star.lens.life': '人生',
    'star.lens.people': '人物',
    'star.lens.keepsakes': '纪念',
    'star.empty': '这段人生还没有留下可以画进星图的事。往前走，世界会记住的。',
    'star.hint': '星图不会改变故事——它只是世界记得你的方式。',
    'star.filter.characters': '人物',
    'star.filter.places': '地点',
    'star.filter.groups': '群体',
    'star.filter.objects': '物品',
    'star.filter.threads': '线索',
    'star.detail.turn': '第 {n} 页',
    'star.detail.jump': '回到那一页',
    'star.detail.action': '你当时的选择',
    'star.detail.related': '相关',
    'star.detail.echoed': '被回响于第 {n} 页',
    'star.detail.thread.open': '仍未了结',
    'star.detail.thread.done': '已了结',
    'star.keep.this': '收藏这一刻',
    'star.keep.kept': '已收藏',
    'star.people.centre': '以谁为中心',
    'star.people.me': '我',
    'star.people.none': '这段人生还没有记下与人的往来。',
    'star.rel.evidence': '因为这些事',
    'star.rel.unrecorded': '尚无关系记录',
    'star.rel.closer': '更亲近',
    'star.rel.farther': '更疏远',
    'star.rel.type.trust': '信任',
    'star.rel.type.grudge': '积怨',
    'star.rel.type.debt': '人情',
    'star.rel.type.fealty': '效忠',
    'star.rel.type.love': '爱意',
    'star.rel.type.fear': '畏惧',
    'star.rel.type.respect': '敬重',
    'star.rel.type.hostility': '敌意',
    'star.rel.type.kinship': '亲缘',
    'star.rel.type.friendship': '友谊',
    'star.rel.type.rivalry': '竞争',
    'star.mode.canvas': '画布',
    'star.mode.list': '列表',
    'star.keeps.none': '还没有纪念。在回响或星图节点上点「收藏」，把重要的时刻留在这里。',
    'star.keeps.thought': '感想',
    'star.keeps.thoughtPlaceholder': '为什么这一刻重要…',
    'star.keeps.rename': '重命名',
    'star.keeps.save': '保存',
    'star.keeps.delete': '删除',
    'star.keeps.deleteAsk': '删除这份纪念？事实不会消失，只是不再被你标记。',
    'star.keeps.deleteYes': '删除',
    'star.keeps.deleteNo': '留着',
    'star.keeps.cites': '引用的时刻',
    'star.keeps.excerpt': '摘录',
    'star.keeps.newTitle': '未命名的纪念',
    'star.keeps.makeCard': '做成故事卡',
    'card.title': '回响故事卡',
    'card.close': '返回',
    'card.export.html': '导出网页',
    'card.export.md': '导出 Markdown',
    'card.export.svg': '导出图片 (SVG)',
    'card.field.title': '标题',
    'card.field.cover': '封面句',
    'card.field.coverHint': '一句话，说明这段往事为什么值得讲',
    'card.field.thought': '结尾感想',
    'card.sect.events': '要讲哪几件事',
    'card.sect.people': '出场的他们',
    'card.anonHint': '改掉名字即可匿名；取消勾选则完全不出现。',
    'card.moveUp': '上移',
    'card.moveDown': '下移',
    'card.renameOf': '{name} 在卡片上的名字',
    'card.spoilers': '显示结局内容（含剧透）',
    'card.wrap': '界面语言',
    'legacy.title': '传承',
    'legacy.close': '返回',
    'legacy.hint': '这一生结束了。有些东西可以留给下一代——人、物、未了的心愿。被带走的只是它们在你生命里的样子；这一生本身不会被改动。',
    'legacy.none': '这一生没有留下可以传承的东西。有些人生就是这样，干干净净。',
    'legacy.group.characters': '人与羁绊',
    'legacy.group.objects': '物品',
    'legacy.group.groups': '家族与群体',
    'legacy.group.threads': '未了之事',
    'legacy.group.places': '地方',
    'legacy.picked': '已选 {n} / {max}',
    'legacy.continue': '带着这些，开启下一代',
    'legacy.confirmAsk': '传承一旦开启就不能更改。确定吗？',
    'legacy.confirmYes': '确定',
    'legacy.confirmNo': '再想想',
    'legacy.entry': '开启传承',
  },
  en: {
    'star.title': 'Life star map',
    'star.close': 'Back to the story',
    'star.lens.life': 'Life',
    'star.lens.people': 'People',
    'star.lens.keepsakes': 'Keepsakes',
    'star.empty': 'Nothing has been drawn into this map yet. Keep going — the world will remember.',
    'star.hint': 'The map never changes the story — it is only how the world remembers you.',
    'star.filter.characters': 'People',
    'star.filter.places': 'Places',
    'star.filter.groups': 'Groups',
    'star.filter.objects': 'Objects',
    'star.filter.threads': 'Threads',
    'star.detail.turn': 'Page {n}',
    'star.detail.jump': 'Back to that page',
    'star.detail.action': 'What you chose then',
    'star.detail.related': 'Related',
    'star.detail.echoed': 'Echoed on page {n}',
    'star.detail.thread.open': 'Still open',
    'star.detail.thread.done': 'Settled',
    'star.keep.this': 'Keep this moment',
    'star.keep.kept': 'Kept',
    'star.people.centre': 'Centred on',
    'star.people.me': 'Me',
    'star.people.none': 'No dealings with anyone have been recorded yet.',
    'star.rel.evidence': 'Because of',
    'star.rel.unrecorded': 'No relationship recorded yet',
    'star.rel.closer': 'Closer',
    'star.rel.farther': 'More distant',
    'star.rel.type.trust': 'Trust',
    'star.rel.type.grudge': 'Grudge',
    'star.rel.type.debt': 'Debt',
    'star.rel.type.fealty': 'Fealty',
    'star.rel.type.love': 'Love',
    'star.rel.type.fear': 'Fear',
    'star.rel.type.respect': 'Respect',
    'star.rel.type.hostility': 'Hostility',
    'star.rel.type.kinship': 'Kinship',
    'star.rel.type.friendship': 'Friendship',
    'star.rel.type.rivalry': 'Rivalry',
    'star.mode.canvas': 'Canvas',
    'star.mode.list': 'List',
    'star.keeps.none': 'No keepsakes yet. Tap "keep" on an echo or a map node to hold on to a moment.',
    'star.keeps.thought': 'Thought',
    'star.keeps.thoughtPlaceholder': 'Why this moment matters…',
    'star.keeps.rename': 'Rename',
    'star.keeps.save': 'Save',
    'star.keeps.delete': 'Delete',
    'star.keeps.deleteAsk': 'Delete this keepsake? The facts stay; only your mark on them goes.',
    'star.keeps.deleteYes': 'Delete',
    'star.keeps.deleteNo': 'Keep it',
    'star.keeps.cites': 'Cited moments',
    'star.keeps.excerpt': 'Excerpt',
    'star.keeps.newTitle': 'Untitled keepsake',
    'star.keeps.makeCard': 'Make a story card',
    'card.title': 'Echo story card',
    'card.close': 'Back',
    'card.export.html': 'Export page',
    'card.export.md': 'Export Markdown',
    'card.export.svg': 'Export image (SVG)',
    'card.field.title': 'Title',
    'card.field.cover': 'Cover line',
    'card.field.coverHint': 'One line on why this is worth telling',
    'card.field.thought': 'Closing thought',
    'card.sect.events': 'Which moments to tell',
    'card.sect.people': 'Who appears',
    'card.anonHint': 'Change a name to anonymise; untick to leave someone out entirely.',
    'card.moveUp': 'Move up',
    'card.moveDown': 'Move down',
    'card.renameOf': "{name}'s name on the card",
    'card.spoilers': 'Show ending content (spoilers)',
    'card.wrap': 'Card language',
    'legacy.title': 'Inheritance',
    'legacy.close': 'Back',
    'legacy.hint': 'This life is over. Some things can be left to the next one — people, objects, unfinished business. What crosses is how they stood in your life; the life itself is never altered.',
    'legacy.none': 'This life leaves nothing to pass on. Some lives are like that — clean.',
    'legacy.group.characters': 'People and bonds',
    'legacy.group.objects': 'Objects',
    'legacy.group.groups': 'Family and groups',
    'legacy.group.threads': 'Unfinished business',
    'legacy.group.places': 'Places',
    'legacy.picked': 'Chosen {n} / {max}',
    'legacy.continue': 'Carry these into the next life',
    'legacy.confirmAsk': 'An inheritance cannot be changed once made. Sure?',
    'legacy.confirmYes': 'Yes',
    'legacy.confirmNo': 'Let me think',
    'legacy.entry': 'Begin an inheritance',
  },
}

export function mt(
  lang: string,
  key: string,
  vars: Record<string, string | number> = {},
): string {
  const table = lang === 'zh' ? TABLES.zh : TABLES.en
  const raw = table[key] ?? TABLES.en[key] ?? key
  return raw.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  )
}
