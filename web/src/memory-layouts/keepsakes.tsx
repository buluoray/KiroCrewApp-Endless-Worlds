/** 纪念地图 — the "keepsakes" lens (design §8.3.1).
 *
 * The question: "哪些时刻对我最重要？" Keepsakes are the anchors; each opens
 * into the exact events it cites. Editing here touches the MEANING layer only
 * — a rename, a thought, a deletion — and can never move a fact (§8.2: the
 * cited path is immutable, deletion of a keepsake deletes nothing the world
 * remembers).
 */

import { useState } from 'react'

import type { Keepsake, StarPayload } from '../api'
import { api } from '../api'
import { mt, nodeById } from '../memory-state'

function KeepsakeCard({
  runId, kp, lang, payload, focus, setFocus, onChanged,
}: {
  runId: string
  kp: Keepsake
  lang: string
  payload: StarPayload
  focus: string
  setFocus: (id: string) => void
  onChanged: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(kp.title)
  const [thought, setThought] = useState(kp.thought)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      await api.updateKeepsake(runId, kp.id, { title: title.trim(), thought })
      setEditing(false)
      onChanged()
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    setBusy(true)
    try {
      await api.deleteKeepsake(runId, kp.id)
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={'ews-kp' + (kp.cites.includes(focus) ? ' ews-kp-hot' : '')}>
      {editing ? (
        <input
          className="ews-kp-title-edit"
          value={title}
          maxLength={120}
          onChange={(e) => setTitle(e.target.value)}
        />
      ) : (
        <div className="ews-kp-title">{kp.title}</div>
      )}
      {kp.kind === 'excerpt' && kp.excerpt ? (
        <blockquote className="ews-kp-excerpt">
          {kp.excerpt}
          <div className="ews-kp-excerpt-src">
            {mt(lang, 'star.keeps.excerpt')} · {mt(lang, 'star.detail.turn', { n: kp.turn })}
          </div>
        </blockquote>
      ) : null}
      {editing ? (
        <textarea
          className="ews-kp-thought-edit"
          rows={2}
          value={thought}
          maxLength={1000}
          placeholder={mt(lang, 'star.keeps.thoughtPlaceholder')}
          onChange={(e) => setThought(e.target.value)}
        />
      ) : kp.thought ? (
        <div className="ews-kp-thought">{kp.thought}</div>
      ) : null}
      {kp.cites.length ? (
        <div className="ews-kp-cites">
          <span className="ews-kp-cites-label">{mt(lang, 'star.keeps.cites')}</span>
          {kp.cites.map((cid) => {
            const ev = nodeById(payload, cid)
            return ev ? (
              <button
                className={'ews-chip' + (focus === cid ? ' ews-chip-sel' : '')}
                type="button"
                key={cid}
                onClick={() => setFocus(cid)}
              >
                {mt(lang, 'star.detail.turn', { n: ev.turn ?? 0 })} · {ev.title}
              </button>
            ) : null
          })}
        </div>
      ) : null}
      <div className="ews-kp-actions">
        {editing ? (
          <button className="ews-btn" type="button" disabled={busy} onClick={() => void save()}>
            {mt(lang, 'star.keeps.save')}
          </button>
        ) : (
          <button className="ews-btn" type="button" onClick={() => setEditing(true)}>
            {mt(lang, 'star.keeps.rename')}
          </button>
        )}
        {confirming ? (
          <>
            <span className="ews-kp-ask">{mt(lang, 'star.keeps.deleteAsk')}</span>
            <button className="ews-btn ews-btn-danger" type="button" disabled={busy}
              onClick={() => void remove()}>
              {mt(lang, 'star.keeps.deleteYes')}
            </button>
            <button className="ews-btn" type="button" onClick={() => setConfirming(false)}>
              {mt(lang, 'star.keeps.deleteNo')}
            </button>
          </>
        ) : (
          <button className="ews-btn" type="button" onClick={() => setConfirming(true)}>
            {mt(lang, 'star.keeps.delete')}
          </button>
        )}
      </div>
    </div>
  )
}

export function KeepsakesLens({
  runId, payload, lang, focus, setFocus, onChanged,
}: {
  runId: string
  payload: StarPayload
  lang: string
  focus: string
  setFocus: (id: string) => void
  onChanged: () => void
}) {
  if (!payload.keepsakes.length) {
    return <div className="ews-empty">{mt(lang, 'star.keeps.none')}</div>
  }
  const rows = [...payload.keepsakes].sort((a, b) => b.createdAt - a.createdAt)
  return (
    <div className="ews-kp-map">
      {rows.map((kp) => (
        <KeepsakeCard
          key={kp.id}
          runId={runId}
          kp={kp}
          lang={lang}
          payload={payload}
          focus={focus}
          setFocus={setFocus}
          onChanged={onChanged}
        />
      ))}
    </div>
  )
}
