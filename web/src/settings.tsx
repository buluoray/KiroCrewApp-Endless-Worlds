import { useEffect, useState } from 'react'

import { api } from './api'
import { t } from './strings'

/**
 * Narrator settings, opened from the home page: which model writes the story and
 * at what reasoning effort. Both apply to every life's narrator at its next turn.
 *
 * The model list comes from the gateway's advertised set (never a hardcoded id);
 * an empty pick means "keep the app's default", so the app still narrates on auto
 * when the list is unavailable or the player has chosen nothing.
 */
export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [model, setModel] = useState('')
  const [effort, setEffort] = useState('')
  const [efforts, setEfforts] = useState<string[]>([''])
  const [models, setModels] = useState<Array<{ id: string; name?: string }>>([])
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    void api.settings().then((s) => {
      if (!alive) return
      // The advertised list already carries an `auto` entry, and the default
      // option ("") also resolves to auto — so a persisted "auto" is the same
      // choice as default. Normalize it to "" so the select shows one auto row,
      // not a value with no matching option.
      setModel(s.model && s.model !== 'auto' ? s.model : '')
      setEffort(s.reasoningEffort || '')
      if (Array.isArray(s.efforts) && s.efforts.length) setEfforts(s.efforts)
    }).catch(() => {})
    // `api.models()` proxies through the app's own backend route, which the app's
    // path-scoped cookie authorizes (the core /api/models route does not).
    void api.models().then((m) => { if (alive) setModels(m) }).catch(() => {})
    return () => { alive = false }
  }, [])

  const save = async () => {
    setBusy(true)
    try {
      const out = await api.saveSettings({ model, reasoningEffort: effort })
      setModel(out.model || '')
      setEffort(out.reasoningEffort || '')
      setSaved(true)
    } finally {
      setBusy(false)
    }
  }

  // The saved model may not be in the advertised list (offline, or a pick from a
  // prior session); keep it selectable so saving does not silently drop it. Drop
  // the advertised `auto` id: the default option ("") already stands for auto, so
  // listing it again is a confusing duplicate row.
  const modelIds = models.map((m) => m.id).filter((id) => id && id !== 'auto')
  const extra = model && model !== 'auto' && !modelIds.includes(model) ? [model] : []

  return (
    <div className="ew-settings ew-block">
      <div className="ew-settings-head">
        <div className="ew-section">{t('settings.title')}</div>
        <button className="ew-btn ew-btn-quiet" type="button" onClick={onClose}>
          {t('settings.close')}
        </button>
      </div>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.model')}</span>
        <select
          className="ew-uilang ew-settings-select"
          value={model}
          onChange={(e) => { setModel(e.target.value); setSaved(false) }}
        >
          <option value="">{t('settings.modelDefault')}</option>
          {[...extra, ...modelIds].map((id) => (
            <option key={id} value={id}>
              {models.find((m) => m.id === id)?.name || id}
            </option>
          ))}
        </select>
      </label>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.effort')}</span>
        <select
          className="ew-uilang ew-settings-select"
          value={effort}
          onChange={(e) => { setEffort(e.target.value); setSaved(false) }}
        >
          {efforts.map((lvl) => (
            <option key={lvl || 'default'} value={lvl}>
              {lvl ? lvl : t('settings.effortDefault')}
            </option>
          ))}
        </select>
      </label>

      <div className="ew-settings-foot">
        <button className="ew-btn ew-btn-go" type="button" disabled={busy} onClick={() => void save()}>
          {t('settings.save')}
        </button>
        {saved ? <span className="ew-settings-saved">{t('settings.saved')}</span> : null}
      </div>
      <div className="ew-hint">{t('settings.note')}</div>
    </div>
  )
}
