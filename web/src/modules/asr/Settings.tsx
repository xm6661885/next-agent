// Settings > Apps > Speech to text.

import { useEffect, useState } from 'preact/hooks'
import { SettingsFrame } from '../settings/Frame'
import { Switch, SecretInput } from '../../components/ui'
import { toast, toastError } from '../../lib/store'
import { asrApi, type AsrSettings as S, type TestResult } from './api'

const val = (e: Event) => (e.target as HTMLInputElement).value

export function AsrSettings({ title }: { title: string }) {
  const [s, setS] = useState<S | null>(null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [res, setRes] = useState<TestResult | null>(null)
  const load = (x: S) => { setS(x); setOrig(JSON.stringify(x)) }
  useEffect(() => { asrApi.settings().then(load).catch(toastError) }, [])
  const dirty = s !== null && JSON.stringify(s) !== orig
  const set = <K extends keyof S>(k: K, v: S[K]) => setS((x) => x && { ...x, [k]: v })

  const save = async () => {
    if (!s) return
    setSaving(true)
    try { load(await asrApi.saveSettings(s)); toast('Settings saved') } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  // The server tests the saved settings, so unsaved edits are saved first.
  const test = async () => {
    if (!s) return
    setTesting(true); setRes(null)
    try {
      if (dirty) load(await asrApi.saveSettings(s))
      setRes(await asrApi.test())
    } catch (e) { toastError(e) } finally { setTesting(false) }
  }

  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={save}>
      {!s ? <div class="skeleton" style={{ height: '260px', borderRadius: '20px' }} /> : <>
        <div class="group-title">Connection</div>
        <div class="group">
          <label class="field"><span class="flabel">API base</span>
            <input class="input mono" value={s.api_base} placeholder="https://api.openai.com/v1" autocapitalize="off" spellcheck={false} onInput={(e) => set('api_base', val(e))} />
            <span class="fhint">Include /v1 if the provider needs it.</span></label>
          <div class="field"><span class="flabel">API key</span>
            <SecretInput value={s.api_key} onInput={(v) => set('api_key', v)} placeholder="sk-..." label="API key" /></div>
          <div class="row">
            <span class="label">Test connection<span class="hint">Saves your changes, then lists the provider's models</span></span>
            <button class="btn small" onClick={test} disabled={testing}>{testing ? <span class="spinner tiny" /> : 'Test'}</button>
          </div>
          {res && (
            <div class={`test-detail ${res.ok ? 'ok' : 'err'}`}>
              {res.detail}
              {res.models.length > 0 && <div class="mono test-models">{res.models.join(', ')}</div>}
            </div>
          )}
        </div>

        <div class="group-title">Recognition</div>
        <div class="group">
          <label class="field"><span class="flabel">Model</span>
            <input class="input mono" value={s.model} placeholder="whisper-1" autocapitalize="off" spellcheck={false} onInput={(e) => set('model', val(e))} />
            <span class="fhint">Empty uses the provider default.</span></label>
          <label class="field"><span class="flabel">Language</span>
            <input class="input" value={s.language} placeholder="Auto detect (e.g. zh, en)" autocapitalize="off" spellcheck={false} onInput={(e) => set('language', val(e))} /></label>
          <label class="field"><span class="flabel">Prompt</span>
            <textarea class="textarea" value={s.prompt} placeholder="Names and terms that may appear in the audio" onInput={(e) => set('prompt', val(e))} />
            <span class="fhint">Sent with each request together with the end of the previous segment.</span></label>
        </div>

        <div class="group-title">Recording</div>
        <div class="group">
          <label class="field"><span class="flabel">Chunk length: {s.chunk_sec} s</span>
            <input class="range" type="range" min={5} max={60} step={1} value={s.chunk_sec} onInput={(e) => set('chunk_sec', Number(val(e)))} />
            <span class="fhint">Live recordings are cut into chunks of about this length (5 to 60 seconds).</span></label>
          <div class="row">
            <span class="label">Retranscribe on finish<span class="hint">Recognize the whole live recording again after it ends</span></span>
            <Switch on={s.retranscribe_on_finish} onChange={(v) => set('retranscribe_on_finish', v)} label="Retranscribe on finish" />
          </div>
        </div>
      </>}
    </SettingsFrame>
  )
}
