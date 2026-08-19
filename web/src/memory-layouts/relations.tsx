/** 关系轨道 — the "people" lens (design §8.3.1).
 *
 * The question: "我与这个人为什么变成现在这样？" A chosen centre (the player by
 * default), relation partners on an inner orbit, everything else the filters
 * admit on an outer one. Every relation line can OPEN into the events that
 * produced the current reading — the §4.3 rule that the projection never
 * replaces its history.
 *
 * Two modes on narrow screens (§8.3.4): the canvas, and a list rendering the
 * SAME nodes and edges — a different geometry, never a different dataset.
 */

import type { StarPayload, StarRelation } from '../api'
import { mt, nodeById, nodeLabel, nodeVisible, type StarFilters } from '../memory-state'

const SIZE = 620
const CX = SIZE / 2

function ring(index: number, count: number, radius: number): { x: number; y: number } {
  const angle = (index / Math.max(count, 1)) * Math.PI * 2 - Math.PI / 2
  return { x: CX + radius * Math.cos(angle), y: CX + radius * Math.sin(angle) }
}

export function RelationsLens({
  payload, lang, focus, setFocus, filters, centre, setCentre, mode,
}: {
  payload: StarPayload
  lang: string
  focus: string
  setFocus: (id: string) => void
  filters: StarFilters
  /** Whose orbits these are — the player, or the character an entry named. */
  centre: string
  setCentre: (id: string) => void
  mode: 'canvas' | 'list'
}) {
  const characters = payload.nodes.filter(
    (n) => n.kind === 'character' && nodeVisible(n, filters),
  )
  const relations = payload.relations.filter(
    (r) => r.from === centre || r.to === centre,
  )
  if (!characters.length && !relations.length) {
    return <div className="ews-empty">{mt(lang, 'star.people.none')}</div>
  }

  const partners = new Map<string, StarRelation[]>()
  for (const r of relations) {
    const other = r.from === centre ? r.to : r.from
    partners.set(other, [...(partners.get(other) ?? []), r])
  }
  const inner = [...partners.keys()]
    .map((id) => nodeById(payload, id))
    .filter((n): n is NonNullable<typeof n> => !!n && nodeVisible(n, filters))
    .sort((a, b) => a.id.localeCompare(b.id))
  const outer = payload.nodes
    .filter(
      (n) => n.kind !== 'event' && n.id !== centre && !partners.has(n.id)
        && nodeVisible(n, filters),
    )
    .sort((a, b) => a.id.localeCompare(b.id))

  const centreLabel =
    centre === 'player' ? mt(lang, 'star.lens.life') : nodeLabel(nodeById(payload, centre) ?? { id: centre, kind: 'character', name: centre })

  const picker = (
    <div className="ews-centre-row">
      <span className="ews-centre-label">{mt(lang, 'star.people.centre')}</span>
      <button
        className={'ews-chip' + (centre === 'player' ? ' ews-chip-sel' : '')}
        type="button"
        onClick={() => setCentre('player')}
      >
        {lang === 'zh' ? '我' : 'Me'}
      </button>
      {characters.map((c) => (
        <button
          className={'ews-chip ews-chip-character' + (centre === c.id ? ' ews-chip-sel' : '')}
          type="button"
          key={c.id}
          onClick={() => setCentre(c.id)}
        >
          {nodeLabel(c)}
        </button>
      ))}
    </div>
  )

  if (mode === 'list') {
    return (
      <div>
        {picker}
        <div className="ews-rel-list">
          {relations.map((r, i) => {
            const other = r.from === centre ? r.to : r.from
            const node = nodeById(payload, other)
            return (
              <div className="ews-rel-row" key={`${r.from}-${r.type}-${r.to}-${i}`}>
                <button
                  className={'ews-node' + (focus === other ? ' ews-node-sel' : '')}
                  type="button"
                  onClick={() => setFocus(other)}
                >
                  {node ? nodeLabel(node) : other}
                </button>
                <span className="ews-rel-kind">
                  {r.type}{r.value ? ` · ${r.value}` : r.level ? ` · ${r.level > 0 ? '+' : ''}${r.level}` : ''}
                </span>
                {r.sources.length ? (
                  <span className="ews-rel-srcs">
                    {mt(lang, 'star.rel.evidence')}:{' '}
                    {r.sources.map((s) => {
                      const ev = nodeById(payload, s)
                      return ev ? (
                        <button
                          className="ews-echo-ref"
                          type="button"
                          key={s}
                          onClick={() => setFocus(s)}
                        >
                          {mt(lang, 'star.detail.turn', { n: ev.turn ?? 0 })}
                        </button>
                      ) : null
                    })}
                  </span>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div>
      {picker}
      <svg
        className="ews-canvas"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={mt(lang, 'star.lens.people')}
      >
        <circle cx={CX} cy={CX} r={150} className="ews-orbit" />
        <circle cx={CX} cy={CX} r={265} className="ews-orbit" />
        {inner.map((n, i) => {
          const p = ring(i, inner.length, 150)
          return (
            <line
              key={`l-${n.id}`} x1={CX} y1={CX} x2={p.x} y2={p.y}
              className="ews-rel-line"
            />
          )
        })}
        <g
          className="ews-star ews-star-centre"
          onClick={() => setFocus(centre)}
          role="button"
          tabIndex={0}
        >
          <circle cx={CX} cy={CX} r={26} />
          <text x={CX} y={CX + 4} textAnchor="middle">{centreLabel}</text>
        </g>
        {inner.map((n, i) => {
          const p = ring(i, inner.length, 150)
          return (
            <g
              className={'ews-star ews-star-' + n.kind + (focus === n.id ? ' ews-star-sel' : '')}
              key={n.id}
              onClick={() => setFocus(n.id)}
              role="button"
              tabIndex={0}
            >
              <circle cx={p.x} cy={p.y} r={20} />
              <text x={p.x} y={p.y + 34} textAnchor="middle">{nodeLabel(n)}</text>
            </g>
          )
        })}
        {outer.map((n, i) => {
          const p = ring(i, outer.length, 265)
          return (
            <g
              className={'ews-star ews-star-' + n.kind + (focus === n.id ? ' ews-star-sel' : '')}
              key={n.id}
              onClick={() => setFocus(n.id)}
              role="button"
              tabIndex={0}
            >
              <circle cx={p.x} cy={p.y} r={14} />
              <text x={p.x} y={p.y + 28} textAnchor="middle">{nodeLabel(n)}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
