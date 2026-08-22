/** 时间星座 — the "life" lens (design §8.3.1).
 *
 * The question it answers: "我的人生如何走到这里？" The turn axis is the
 * skeleton; entities cluster beside the events that touched them; a declared
 * echo renders as an explicit back-reference the player can follow. Vertical
 * by construction, so the phone layout IS the layout (§8.3.4) rather than a
 * shrunken canvas.
 *
 * A layout adapter, not an owner: selection, filters and the detail panel live
 * in the container's shared state (§12.4 — switching lenses keeps all three).
 */

import type { StarNode, StarPayload } from '../api'
import { mt, nodeLabel, nodeVisible, type StarFilters } from '../memory-state'

export function TimelineLens({
  payload,
  lang,
  focus,
  setFocus,
  filters,
}: {
  payload: StarPayload
  lang: string
  focus: string
  setFocus: (id: string) => void
  filters: StarFilters
}) {
  const events = payload.nodes
    .filter((n) => n.kind === 'event')
    .sort((a, b) => (a.turn ?? 0) - (b.turn ?? 0) || a.id.localeCompare(b.id))

  if (!events.length) {
    return <div className="ews-empty">{mt(lang, 'star.empty')}</div>
  }

  const byId = new Map(payload.nodes.map((n) => [n.id, n]))
  const echoOf = new Map<string, string[]>()
  for (const e of payload.edges) {
    if (e.type === 'echoes') {
      echoOf.set(e.from, [...(echoOf.get(e.from) ?? []), e.to])
    }
  }
  const attached = new Map<string, StarNode[]>()
  for (const e of payload.edges) {
    if (e.type === 'echoes') continue
    const event = e.type === 'participated_in' ? e.to : e.from
    const entity = e.type === 'participated_in' ? e.from : e.to
    const node = byId.get(entity)
    if (!node || node.kind === 'event' || !nodeVisible(node, filters)) continue
    const list = attached.get(event) ?? []
    if (!list.some((n) => n.id === node.id)) list.push(node)
    attached.set(event, list)
  }

  return (
    <div className="ews-timeline" role="list">
      {events.map((ev) => {
        const selected = ev.id === focus
        const echoes = echoOf.get(ev.id) ?? []
        return (
          <div className="ews-tl-row" role="listitem" key={ev.id}>
            <div className="ews-tl-spine" aria-hidden="true">
              <span
                className={
                  'ews-tl-dot' +
                  (ev.importance === 'major' ? ' ews-tl-dot-major' : '') +
                  (selected ? ' ews-tl-dot-sel' : '')
                }
              />
            </div>
            <div className="ews-tl-body">
              <button
                className={'ews-node' + (selected ? ' ews-node-sel' : '')}
                type="button"
                aria-pressed={selected}
                onClick={() => setFocus(ev.id)}
              >
                <span className="ews-tl-turn">
                  {mt(lang, 'star.detail.turn', { n: ev.turn ?? 0 })}
                </span>
                <span className="ews-tl-title">{ev.title}</span>
              </button>
              {echoes.map((target) => {
                const src = byId.get(target)
                return src ? (
                  <button
                    className="ews-echo-ref"
                    type="button"
                    key={target}
                    onClick={() => setFocus(target)}
                  >
                    {mt(lang, 'star.detail.echoed', { n: src.turn ?? 0 })} · {nodeLabel(src)}
                  </button>
                ) : null
              })}
              {(attached.get(ev.id) ?? []).length ? (
                <div className="ews-tl-cluster">
                  {(attached.get(ev.id) ?? []).map((n) => (
                    <button
                      className={
                        'ews-chip ews-chip-' + n.kind + (n.id === focus ? ' ews-chip-sel' : '')
                      }
                      type="button"
                      key={n.id}
                      onClick={() => setFocus(n.id)}
                    >
                      {nodeLabel(n)}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        )
      })}
    </div>
  )
}
