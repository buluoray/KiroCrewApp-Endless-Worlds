import { useEffect, useState } from 'react'

import { api } from './api'
import { t } from './strings'

/**
 * The app settings panel, opened from the home page. Three groups:
 *
 * - Narration: which model writes the story, at what effort, at what length.
 * - Page art: whether backdrops are drawn at all, by which model, in which
 *   styles, and how often. Everything under the master switch dims when it is
 *   off — the choices are moot, not forbidden.
 * - Choice decoration: the small emblems and motion effects on choice buttons.
 *
 * Every knob is ENFORCED server-side (the MCP gates and the choice cleaner);
 * this panel only records the player's pick. The model list comes from the
 * gateway's advertised set (never a hardcoded id); an empty pick means "keep
 * the app's default", so the app still runs on auto when the list is
 * unavailable or the player has chosen nothing.
 */

const PAINT_STYLES = ['photo', 'watercolor', 'oil', 'minimal'] as const

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [model, setModel] = useState('')
  const [effort, setEffort] = useState('')
  const [painterModel, setPainterModel] = useState('')
  const [efforts, setEfforts] = useState<string[]>([''])
  const [models, setModels] = useState<Array<{ id: string; name?: string }>>([])
  const [backdrops, setBackdrops] = useState(true)
  const [styles, setStyles] = useState<string[]>([...PAINT_STYLES])
  const [cadence, setCadence] = useState('normal')
  const [choiceArt, setChoiceArt] = useState(true)
  const [choiceEffects, setChoiceEffects] = useState(true)
  const [proseLength, setProseLength] = useState('')
  const [reducedMotion, setReducedMotion] = useState(false)
  const [artQuality, setArtQuality] = useState('standard')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    void api
      .settings()
      .then((s) => {
        if (!alive) return
        // The advertised list already carries an `auto` entry, and the default
        // option ("") also resolves to auto — so a persisted "auto" is the same
        // choice as default. Normalize it to "" so the select shows one auto row,
        // not a value with no matching option.
        setModel(s.model && s.model !== 'auto' ? s.model : '')
        setEffort(s.reasoningEffort || '')
        setPainterModel(s.painterModel && s.painterModel !== 'auto' ? s.painterModel : '')
        if (Array.isArray(s.efforts) && s.efforts.length) setEfforts(s.efforts)
        setBackdrops(s.backdrops !== false)
        if (Array.isArray(s.styles) && s.styles.length) setStyles(s.styles)
        setCadence(s.backdropCadence || 'normal')
        setChoiceArt(s.choiceArt !== false)
        setChoiceEffects(s.choiceEffects !== false)
        setProseLength(s.proseLength || '')
        setReducedMotion(s.reducedMotion === true)
        setArtQuality(s.artQuality || 'standard')
      })
      .catch(() => {})
    // `api.models()` proxies through the app's own backend route, which the app's
    // path-scoped cookie authorizes (the core /api/models route does not).
    void api
      .models()
      .then((m) => {
        if (alive) setModels(m)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  const save = async () => {
    setBusy(true)
    try {
      const out = await api.saveSettings({
        model,
        reasoningEffort: effort,
        painterModel,
        backdrops,
        styles,
        backdropCadence: cadence,
        choiceArt,
        choiceEffects,
        proseLength,
        reducedMotion,
        artQuality,
      })
      setModel(out.model || '')
      setEffort(out.reasoningEffort || '')
      setPainterModel(out.painterModel || '')
      setBackdrops(out.backdrops !== false)
      if (Array.isArray(out.styles) && out.styles.length) setStyles(out.styles)
      setCadence(out.backdropCadence || 'normal')
      setChoiceArt(out.choiceArt !== false)
      setChoiceEffects(out.choiceEffects !== false)
      setProseLength(out.proseLength || '')
      setReducedMotion(out.reducedMotion === true)
      setArtQuality(out.artQuality || 'standard')
      setSaved(true)
    } finally {
      setBusy(false)
    }
  }

  const toggleStyle = (style: string) => {
    setSaved(false)
    setStyles((prev) => {
      if (prev.includes(style)) {
        // At least one style must stay enabled: an empty allowlist is not a
        // state the backend accepts (it would coerce to "all on", silently
        // undoing the click), so refuse the uncheck here where it is visible.
        if (prev.length <= 1) return prev
        return prev.filter((s) => s !== style)
      }
      return PAINT_STYLES.filter((s) => prev.includes(s) || s === style)
    })
  }

  // The saved model may not be in the advertised list (offline, or a pick from a
  // prior session); keep it selectable so saving does not silently drop it. Drop
  // the advertised `auto` id: the default option ("") already stands for auto, so
  // listing it again is a confusing duplicate row.
  const modelIds = models.map((m) => m.id).filter((id) => id && id !== 'auto')
  const label = (id: string) => models.find((m) => m.id === id)?.name || id
  const optionsFor = (current: string) =>
    (current && current !== 'auto' && !modelIds.includes(current) ? [current] : []).concat(modelIds)

  return (
    <div className="ew-settings ew-block">
      <div className="ew-settings-head">
        <div className="ew-section">{t('settings.title')}</div>
        <button className="ew-btn ew-btn-quiet" type="button" onClick={onClose}>
          {t('settings.close')}
        </button>
      </div>

      <div className="ew-settings-group">{t('settings.group.narration')}</div>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.model')}</span>
        <select
          className="ew-uilang ew-settings-select"
          value={model}
          onChange={(e) => {
            setModel(e.target.value)
            setSaved(false)
          }}
        >
          <option value="">{t('settings.modelDefault')}</option>
          {optionsFor(model).map((id) => (
            <option key={id} value={id}>
              {label(id)}
            </option>
          ))}
        </select>
      </label>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.effort')}</span>
        <select
          className="ew-uilang ew-settings-select"
          value={effort}
          onChange={(e) => {
            setEffort(e.target.value)
            setSaved(false)
          }}
        >
          {efforts.map((lvl) => (
            <option key={lvl || 'default'} value={lvl}>
              {lvl ? lvl : t('settings.effortDefault')}
            </option>
          ))}
        </select>
      </label>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.proseLength')}</span>
        <select
          className="ew-uilang ew-settings-select"
          value={proseLength}
          onChange={(e) => {
            setProseLength(e.target.value)
            setSaved(false)
          }}
        >
          <option value="">{t('settings.proseLength.default')}</option>
          <option value="short">{t('settings.proseLength.short')}</option>
          <option value="long">{t('settings.proseLength.long')}</option>
        </select>
      </label>

      <div className="ew-settings-group">{t('settings.group.art')}</div>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.backdrops')}</span>
        <input
          type="checkbox"
          checked={backdrops}
          onChange={(e) => {
            setBackdrops(e.target.checked)
            setSaved(false)
          }}
        />
        <span className="ew-settings-note">
          {backdrops ? t('settings.backdrops.on') : t('settings.backdrops.off')}
        </span>
      </label>

      <div className={backdrops ? '' : 'ew-settings-dimmed'}>
        <label className="ew-settings-row">
          <span className="ew-settings-label">{t('settings.painterModel')}</span>
          <select
            className="ew-uilang ew-settings-select"
            value={painterModel}
            disabled={!backdrops}
            onChange={(e) => {
              setPainterModel(e.target.value)
              setSaved(false)
            }}
          >
            <option value="">{t('settings.modelDefault')}</option>
            {optionsFor(painterModel).map((id) => (
              <option key={id} value={id}>
                {label(id)}
              </option>
            ))}
          </select>
        </label>

        <div className="ew-settings-row">
          <span className="ew-settings-label">{t('settings.styles')}</span>
          <div className="ew-settings-checks">
            {PAINT_STYLES.map((style) => (
              <label key={style} className="ew-settings-check">
                <input
                  type="checkbox"
                  checked={styles.includes(style)}
                  disabled={!backdrops}
                  onChange={() => toggleStyle(style)}
                />
                <span>{t(`settings.style.${style}`)}</span>
              </label>
            ))}
          </div>
        </div>

        <label className="ew-settings-row">
          <span className="ew-settings-label">{t('settings.cadence')}</span>
          <select
            className="ew-uilang ew-settings-select"
            value={cadence}
            disabled={!backdrops}
            onChange={(e) => {
              setCadence(e.target.value)
              setSaved(false)
            }}
          >
            <option value="normal">{t('settings.cadence.normal')}</option>
            <option value="sparse">{t('settings.cadence.sparse')}</option>
          </select>
        </label>

        <label className="ew-settings-row">
          <span className="ew-settings-label">{t('settings.artQuality')}</span>
          <select
            className="ew-uilang ew-settings-select"
            value={artQuality}
            disabled={!backdrops}
            onChange={(e) => {
              setArtQuality(e.target.value)
              setSaved(false)
            }}
          >
            <option value="standard">{t('settings.artQuality.standard')}</option>
            <option value="fast">{t('settings.artQuality.fast')}</option>
          </select>
        </label>
      </div>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.reducedMotion')}</span>
        <input
          type="checkbox"
          checked={reducedMotion}
          onChange={(e) => {
            setReducedMotion(e.target.checked)
            setSaved(false)
          }}
        />
        <span className="ew-settings-note">{t('settings.reducedMotion.hint')}</span>
      </label>

      <div className="ew-settings-group">{t('settings.group.choices')}</div>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.choiceArt')}</span>
        <input
          type="checkbox"
          checked={choiceArt}
          onChange={(e) => {
            setChoiceArt(e.target.checked)
            setSaved(false)
          }}
        />
        <span className="ew-settings-note">{t('settings.choiceArt.hint')}</span>
      </label>

      <label className="ew-settings-row">
        <span className="ew-settings-label">{t('settings.choiceEffects')}</span>
        <input
          type="checkbox"
          checked={choiceEffects}
          onChange={(e) => {
            setChoiceEffects(e.target.checked)
            setSaved(false)
          }}
        />
        <span className="ew-settings-note">{t('settings.choiceEffects.hint')}</span>
      </label>

      <div className="ew-settings-foot">
        <button
          className="ew-btn ew-btn-go"
          type="button"
          disabled={busy}
          onClick={() => void save()}
        >
          {t('settings.save')}
        </button>
        {saved ? <span className="ew-settings-saved">{t('settings.saved')}</span> : null}
      </div>
      <div className="ew-hint">{t('settings.note')}</div>
    </div>
  )
}
