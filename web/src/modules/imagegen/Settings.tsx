// Settings > Apps > Image generation.

import { useEffect, useState } from 'preact/hooks'
import { SettingsFrame } from '../settings/Frame'
import { SecretInput } from '../../components/ui'
import { IconClose, IconPlus, IconRefresh } from '../../components/icons'
import { toast, toastError } from '../../lib/store'
import { imgApi, type ImgSettings as S, type RefMode } from './api'

const val = (e: Event) => (e.target as HTMLInputElement).value
const MODES: { value: RefMode; label: string; hint: string }[] = [
  { value: 'auto', label: 'Auto', hint: 'Try the edits endpoint first, fall back to generations if it fails.' },
  { value: 'edits', label: 'Edits', hint: 'Send references to /images/edits as multipart. Compression and moderation are not forwarded.' },
  { value: 'generations', label: 'Generations', hint: 'Send references to /images/generations as JSON data URLs.' },
]

export function ImagegenSettings({ title }: { title: string }) {
  const [s, setS] = useState<S | null>(null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<{ ok: boolean; detail: string; models: string[] } | null>(null)
  const [draft, setDraft] = useState('')
  const load = (x: S) => { setS(x); setOrig(JSON.stringify(x)) }
  useEffect(() => { imgApi.settings().then(load).catch(toastError) }, [])
  const dirty = s !== null && JSON.stringify(s) !== orig
  const set = <K extends keyof S>(k: K, v: S[K]) => setS((x) => x && { ...x, [k]: v })

  const addModel = (m: string) => {
    const id = m.trim()
    if (!id || !s || s.models.includes(id)) return
    setS({ ...s, models: [...s.models, id], default_model: s.default_model || id })
  }
  const removeModel = (m: string) => s && setS({ ...s, models: s.models.filter((x) => x !== m), default_model: s.default_model === m ? (s.models.find((x) => x !== m) || '') : s.default_model })

  const save = async () => {
    if (!s) return
    setSaving(true)
    try { load(await imgApi.saveSettings(s)); toast('Settings saved') } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  // The server reads the saved connection, so unsaved edits are saved first.
  const withSaved = async (fn: () => Promise<void>) => {
    if (!s) return
    setBusy(true)
    try { if (dirty) load(await imgApi.saveSettings(s)); await fn() } catch (e) { toastError(e) } finally { setBusy(false) }
  }
  const fetchModels = () => withSaved(async () => {
    const r = await imgApi.fetchModels()
    setS((x) => x && { ...x, models: [...new Set([...x.models, ...r.models])] })
    toast(`Fetched ${r.models.length} models`)
  })
  const test = () => withSaved(async () => { setRes(await imgApi.test()) })

  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={save}>
      {!s ? <div class="skeleton" style={{ height: '260px', borderRadius: '20px' }} /> : <>
        <div class="group-title">Connection</div>
        <div class="group">
          <label class="field"><span class="flabel">API base</span>
            <input class="input mono" value={s.api_base} placeholder="https://api.openai.com/v1" autocapitalize="off" spellcheck={false} onInput={(e) => set('api_base', val(e))} /></label>
          <div class="field"><span class="flabel">API key</span>
            <SecretInput value={s.api_key} onInput={(v) => set('api_key', v)} placeholder="sk-..." label="API key" /></div>
          <label class="field"><span class="flabel">Timeout (seconds)</span>
            <input class="input" type="number" min={1} value={s.timeout} onInput={(e) => set('timeout', Math.max(1, Number(val(e)) || 1))} />
            <span class="fhint">Applies to each generation, edit and download request.</span></label>
          <div class="row">
            <span class="label">Test connection<span class="hint">Saves your changes, then lists the provider's models</span></span>
            <button class="btn small" onClick={test} disabled={busy}>{busy ? <span class="spinner tiny" /> : 'Test'}</button>
          </div>
          {res && (
            <div class={`test-detail ${res.ok ? 'ok' : 'err'}`}>
              {res.detail}
              {res.models.length > 0 && <div class="mono test-models">{res.models.join(', ')}</div>}
            </div>
          )}
        </div>

        <div class="group-title">Models</div>
        <div class="group">
          <div class="field">
            <span class="flabel">Model list</span>
            <div class="chips">
              {s.models.map((m) => (
                <span key={m} class={`chip removable ${m === s.default_model ? 'pink' : ''}`}>
                  <button type="button" class="mono chip-pick" onClick={() => set('default_model', m)} aria-pressed={m === s.default_model}
                    title="Set as default" style={{ width: 'auto', borderRadius: '8px', padding: '0 6px' }}>{m}</button>
                  <button type="button" onClick={() => removeModel(m)} aria-label={`Remove ${m}`}><IconClose /></button>
                </span>
              ))}
              {s.models.length === 0 && <span class="fhint">No models yet.</span>}
            </div>
            <span class="fhint">Tap a model to make it the default (highlighted). The list only feeds the picker; any model id can be used.</span>
          </div>
          <form class="field img-add" onSubmit={(e) => { e.preventDefault(); addModel(draft); setDraft('') }}>
            <input class="input mono" value={draft} placeholder="Add a model id" autocapitalize="off" spellcheck={false} onInput={(e) => setDraft(val(e))} />
            <button type="submit" class="btn small" disabled={!draft.trim()}><IconPlus width={16} />Add</button>
            <button type="button" class="btn small" onClick={fetchModels} disabled={busy}><IconRefresh width={16} />Fetch from API</button>
          </form>
        </div>

        <div class="group-title">Reference images</div>
        <div class="group">
          <div class="field">
            <span class="flabel">Reference mode</span>
            <select class="select" value={s.reference_mode} onChange={(e) => set('reference_mode', val(e) as RefMode)}>
              {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
            <span class="fhint">{MODES.find((m) => m.value === s.reference_mode)?.hint}</span>
          </div>
        </div>
      </>}
    </SettingsFrame>
  )
}
