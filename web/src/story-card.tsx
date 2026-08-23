/** The echo story card editor (design §8.4).
 *
 * One panel, two halves: the LEFT edits the draft (include/exclude events and
 * people, rename for anonymity, title/cover/thought, spoilers, wrap language);
 * the RIGHT shows the resolved preview the server returns with every edit.
 * The preview is rendered by the SAME resolver the exporters use, so what the
 * player reads here is byte-for-byte what the file will say — the §11 Phase 3
 * completion bar, surfaced as UI.
 *
 * Nothing here can ADD to a card: the server refuses ids outside the
 * allowlist, and this editor simply has no control that would try.
 */

import { useEffect, useRef, useState } from 'react'

import type { CardPreview, Keepsake, StoryCard } from './api'
import { api } from './api'
import { mt } from './memory-state'

export function StoryCardEditor({
  runId,
  keepsake,
  lang,
  onClose,
}: {
  runId: string
  keepsake: Keepsake
  lang: string
  onClose: () => void
}) {
  const [card, setCard] = useState<StoryCard | null>(null)
  const [preview, setPreview] = useState<CardPreview | null>(null)
  const [error, setError] = useState('')
  // Local text fields commit on blur, so typing does not spam PATCHes.
  const [title, setTitle] = useState('')
  const [cover, setCover] = useState('')
  const [thought, setThought] = useState('')
  const sheet = useRef<HTMLDivElement>(null)

  // Covers the app's panel rather than the window, so it has to bring itself into
  // view on open — see the note on .ewc-overlay.
  useEffect(() => {
    sheet.current?.scrollIntoView({ block: 'start' })
  }, [])

  useEffect(() => {
    let alive = true
    api
      .previewStoryCard(runId, keepsake.id)
      .then(({ card: c, preview: p }) => {
        if (!alive) return
        setCard(c)
        setPreview(p)
        setTitle(c.title)
        setCover(c.coverLine)
        setThought(c.thought)
      })
      .catch((e) => {
        if (alive) setError((e as Error).message)
      })
    return () => {
      alive = false
    }
  }, [runId, keepsake.id])

  const patch = async (body: Parameters<typeof api.editStoryCard>[2]) => {
    if (!card) return
    try {
      const { card: c, preview: p } = await api.editStoryCard(runId, card.id, body)
      setCard(c)
      setPreview(p)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const move = (id: string, dir: -1 | 1) => {
    if (!card) return
    const order = card.events.map((e) => e.id)
    const i = order.indexOf(id)
    const j = i + dir
    if (i < 0 || j < 0 || j >= order.length) return
    const next = [...order]
    const a = next[i] as string
    next[i] = next[j] as string
    next[j] = a
    void patch({ order: next })
  }

  if (error) {
    return (
      <div className="ewc-overlay" ref={sheet} role="dialog" aria-modal="true">
        <div className="ewc-head">
          <div className="ewc-title">{mt(lang, 'card.title')}</div>
          <button className="ews-btn" type="button" onClick={onClose}>
            {mt(lang, 'card.close')}
          </button>
        </div>
        <div className="ews-empty">{error}</div>
      </div>
    )
  }
  if (!card || !preview) {
    return (
      <div className="ewc-overlay" ref={sheet} role="dialog" aria-modal="true">
        <div className="ews-empty">…</div>
      </div>
    )
  }

  return (
    <div
      className="ewc-overlay"
      ref={sheet}
      role="dialog"
      aria-modal="true"
      aria-label={mt(lang, 'card.title')}
    >
      <div className="ewc-head">
        <div className="ewc-title">{mt(lang, 'card.title')}</div>
        <div className="ewc-exports">
          {(['html', 'md', 'svg'] as const).map((fmt) => (
            <a
              className="ews-btn"
              key={fmt}
              href={api.storyCardExportUrl(runId, card.id, fmt)}
              download
            >
              {mt(lang, `card.export.${fmt}`)}
            </a>
          ))}
        </div>
        <button className="ews-btn" type="button" onClick={onClose}>
          {mt(lang, 'card.close')}
        </button>
      </div>

      <div className="ewc-body">
        <div className="ewc-edit">
          <label className="ewc-field">
            <span>{mt(lang, 'card.field.title')}</span>
            <input
              value={title}
              maxLength={120}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => {
                if (title.trim() && title !== card.title) void patch({ title })
              }}
            />
          </label>
          <label className="ewc-field">
            <span>{mt(lang, 'card.field.cover')}</span>
            <input
              value={cover}
              maxLength={200}
              placeholder={mt(lang, 'card.field.coverHint')}
              onChange={(e) => setCover(e.target.value)}
              onBlur={() => {
                if (cover !== card.coverLine) void patch({ coverLine: cover })
              }}
            />
          </label>

          <div className="ewc-sect">{mt(lang, 'card.sect.events')}</div>
          {card.events.map((ev, i) => (
            <div className="ewc-row" key={ev.id}>
              <label className="ewc-check">
                <input
                  type="checkbox"
                  checked={ev.included}
                  onChange={() => void patch({ events: { [ev.id]: !ev.included } })}
                />
                <span className="ewc-row-turn">{mt(lang, 'star.detail.turn', { n: ev.turn })}</span>
                <span className="ewc-row-title">{ev.title}</span>
              </label>
              <span className="ewc-move">
                <button
                  className="ews-btn"
                  type="button"
                  disabled={i === 0}
                  aria-label={mt(lang, 'card.moveUp')}
                  onClick={() => move(ev.id, -1)}
                >
                  ↑
                </button>
                <button
                  className="ews-btn"
                  type="button"
                  disabled={i === card.events.length - 1}
                  aria-label={mt(lang, 'card.moveDown')}
                  onClick={() => move(ev.id, 1)}
                >
                  ↓
                </button>
              </span>
            </div>
          ))}

          <div className="ewc-sect">{mt(lang, 'card.sect.people')}</div>
          <div className="ewc-hint">{mt(lang, 'card.anonHint')}</div>
          {card.entities.map((ent) => (
            <div className="ewc-row" key={ent.id}>
              <label className="ewc-check">
                <input
                  type="checkbox"
                  checked={ent.included}
                  onChange={() =>
                    void patch({ entities: { [ent.id]: { included: !ent.included } } })
                  }
                />
                <span className="ewc-row-title">{ent.name}</span>
              </label>
              <input
                className="ewc-rename"
                value={ent.display}
                maxLength={120}
                aria-label={mt(lang, 'card.renameOf', { name: ent.name })}
                onChange={(e) => {
                  const display = e.target.value
                  setCard({
                    ...card,
                    entities: card.entities.map((x) => (x.id === ent.id ? { ...x, display } : x)),
                  })
                }}
                onBlur={(e) => {
                  const display = e.target.value.trim()
                  if (display && display !== ent.name) {
                    void patch({ entities: { [ent.id]: { display } } })
                  }
                }}
              />
            </div>
          ))}

          {card.endedTurn ? (
            <label className="ewc-check ewc-spoiler">
              <input
                type="checkbox"
                checked={card.showSpoilers}
                onChange={() => void patch({ showSpoilers: !card.showSpoilers })}
              />
              {mt(lang, 'card.spoilers')}
            </label>
          ) : null}

          <label className="ewc-field">
            <span>{mt(lang, 'card.field.thought')}</span>
            <textarea
              rows={2}
              value={thought}
              maxLength={1000}
              onChange={(e) => setThought(e.target.value)}
              onBlur={() => {
                if (thought !== card.thought) void patch({ thought })
              }}
            />
          </label>
          <div className="ewc-langrow">
            <span>{mt(lang, 'card.wrap')}</span>
            {(['zh', 'en'] as const).map((l) => (
              <button
                className={'ews-lens' + (card.language === l ? ' ews-lens-on' : '')}
                type="button"
                key={l}
                onClick={() => void patch({ language: l })}
              >
                {l === 'zh' ? '中文' : 'English'}
              </button>
            ))}
          </div>
        </div>

        {/* The resolved preview — exactly the export's content (§11). */}
        <div className="ewc-preview">
          <h2 className="ewc-p-title">{preview.title}</h2>
          {preview.coverLine ? <p className="ewc-p-cover">{preview.coverLine}</p> : null}
          {preview.events.map((ev) => (
            <section className="ewc-p-event" key={ev.id}>
              <div className="ewc-p-head">
                <span className="ewc-row-turn">{mt(lang, 'star.detail.turn', { n: ev.turn })}</span>
                <strong>{ev.title}</strong>
              </div>
              <p>{ev.excerpt || ev.summary}</p>
              {ev.action ? <div className="ewc-p-act">{ev.action}</div> : null}
            </section>
          ))}
          {preview.entities.length ? (
            <div className="ewc-p-cast">
              {preview.entities.map((e) => (
                <span className="ews-chip" key={e.id}>
                  {e.display}
                </span>
              ))}
            </div>
          ) : null}
          {preview.thought ? <p className="ewc-p-thought">{preview.thought}</p> : null}
        </div>
      </div>
      <style>{CSS_TEXT}</style>
    </div>
  )
}

const CSS_TEXT = `
.ewc-overlay {
  /* Absolute, NOT fixed — same reason as the legacy sheet: a fixed sheet resolves
     against the window and covers the dashboard's own chrome. This one anchors to
     the star map page it opens from, and scrolls itself into view on open. */
  position: absolute; inset: 0; min-height: 100%; z-index: 20;
  display: flex; flex-direction: column;
  background: var(--bg, #14151f); color: var(--text, #e5e7eb);
}
.ewc-head {
  display: flex; align-items: center; gap: 10px; padding: 10px 16px;
  border-bottom: 1px solid var(--border, #2d2f3d);
}
.ewc-title { font-weight: 600; }
.ewc-exports { display: flex; gap: 6px; margin-inline: auto; }
.ewc-exports a { text-decoration: none; }
.ewc-body { flex: 1; display: flex; min-height: 0; }
.ewc-edit {
  flex: 0 0 380px; overflow: auto; padding: 14px 16px;
  border-inline-end: 1px solid var(--border, #2d2f3d);
  display: flex; flex-direction: column; gap: 8px;
}
.ewc-preview { flex: 1; overflow: auto; padding: 20px 24px; max-width: 660px; }
.ewc-field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.ewc-field input, .ewc-field textarea, .ewc-rename {
  font: inherit; color: inherit; background: none;
  border: 1px solid var(--border, #2d2f3d); border-radius: 8px; padding: 6px 8px;
}
.ewc-sect { font-size: 12px; color: var(--muted, #9ca3af); margin-top: 10px; }
.ewc-hint { font-size: 12px; color: var(--muted, #6b7280); }
.ewc-row { display: flex; gap: 8px; align-items: center; }
.ewc-check { display: flex; gap: 7px; align-items: center; flex: 1; min-width: 0;
             cursor: pointer; font-size: 14px; }
.ewc-row-turn { font-size: 12px; color: var(--muted, #9ca3af); flex: 0 0 auto; }
.ewc-row-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ewc-move { display: flex; gap: 4px; }
.ewc-rename { flex: 0 0 130px; font-size: 13px; }
.ewc-spoiler { margin-top: 10px; }
.ewc-langrow { display: flex; gap: 6px; align-items: center; font-size: 13px;
               margin-top: 8px; }
.ewc-p-title { font-size: 22px; margin: 0 0 8px; }
.ewc-p-cover { font-style: italic; color: var(--muted, #a5a8b6);
  border-inline-start: 3px solid var(--accent, #7c3aed); padding-inline-start: 12px; }
.ewc-p-event { margin: 18px 0; }
.ewc-p-head { margin-bottom: 4px; }
.ewc-p-act { font-size: 13px; font-style: italic; color: var(--accent, #a78bfa); }
.ewc-p-cast { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 16px; }
.ewc-p-thought { font-style: italic; margin-top: 16px; }
@media (max-width: 860px) {
  .ewc-body { flex-direction: column; }
  .ewc-edit { flex: 0 0 auto; max-height: 52dvh;
    border-inline-end: 0; border-bottom: 1px solid var(--border, #2d2f3d); }
}
`
