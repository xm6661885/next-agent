// Settings > Automations > Tasks and webhooks: scripts directory, interpreters, poll interval, webhook secret.

import { useEffect, useState } from 'preact/hooks'
import { SettingsFrame } from '../settings/Frame'
import { SecretInput, confirmDialog } from '../../components/ui'
import { IconRefresh } from '../../components/icons'
import { toast, toastError } from '../../lib/store'
import { autoApi, type AutoSettings } from './api'

const val = (e: Event) => (e.target as HTMLInputElement).value

export function AutomationsSettings({ title }: { title: string }) {
  const [s, setS] = useState<AutoSettings | null>(null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const load = (x: AutoSettings) => { setS(x); setOrig(JSON.stringify(x)) }
  useEffect(() => { autoApi.settings().then(load).catch(toastError) }, [])
  const dirty = s !== null && JSON.stringify(s) !== orig
  const set = <K extends keyof AutoSettings>(k: K, v: AutoSettings[K]) => setS((x) => x && { ...x, [k]: v })

  const save = async () => {
    if (!s) return
    if (!(s.poll_interval_sec > 0)) return toast('Poll interval must be greater than zero', 'error')
    setSaving(true)
    try {
      const { scripts_dir, python_bin, shell_bin, poll_interval_sec, webhook_secret } = s
      load(await autoApi.setSettings({ scripts_dir, python_bin, shell_bin, poll_interval_sec, webhook_secret }))
      toast('Settings saved')
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  const regenerate = async () => {
    if (!await confirmDialog({ title: 'Regenerate webhook secret?', body: 'Every sender that uses the current secret stops working until you update it.', confirm: 'Regenerate', danger: true })) return
    try { load(await autoApi.regenerate()); toast('New secret generated') } catch (e) { toastError(e) }
  }

  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={save}>
      {!s ? <div class="skeleton" style={{ height: '260px', borderRadius: '20px' }} /> : <>
        <div class="group-title">Scripts</div>
        <div class="group">
          <label class="field"><span class="flabel">Scripts directory</span>
            <input class="input mono" value={s.scripts_dir} autocapitalize="off" spellcheck={false} onInput={(e) => set('scripts_dir', val(e).trim())} />
            <span class="fhint">Relative paths resolve against the data folder. Tasks live in cron/&lt;name&gt;/ and once/&lt;name&gt;/.</span>
          </label>
          <label class="field"><span class="flabel">Python interpreter</span>
            <input class="input mono" value={s.python_bin} autocapitalize="off" spellcheck={false} onInput={(e) => set('python_bin', val(e).trim())} /></label>
          <label class="field"><span class="flabel">Shell</span>
            <input class="input mono" value={s.shell_bin} autocapitalize="off" spellcheck={false} onInput={(e) => set('shell_bin', val(e).trim())} /></label>
        </div>
        <div class="group-title">Scheduler</div>
        <div class="group">
          <label class="field"><span class="flabel">Poll interval (seconds)</span>
            <input class="input mono" type="number" min={0.5} step={0.5} value={s.poll_interval_sec} onInput={(e) => set('poll_interval_sec', Number(val(e)))} />
            <span class="fhint">How often the scheduler checks for due tasks.</span>
          </label>
          <div class="row"><span class="label">Time zone<span class="hint">Cron and one-off times use the server zone.</span></span><span class="value">{s.timezone}</span></div>
        </div>
        <div class="group-title">Webhook</div>
        <div class="group">
          <div class="field"><span class="flabel">Shared secret</span>
            <SecretInput value={s.webhook_secret} onInput={(v) => set('webhook_secret', v.trim())} label="webhook secret" placeholder="Empty rejects every webhook call" />
            <span class="fhint">Send it as the X-AutoTask-Webhook-Secret header, a Bearer token, or ?secret=.</span>
          </div>
          <button class="row press" onClick={regenerate}><span class="label"><IconRefresh width={16} height={16} /> Regenerate</span></button>
        </div>
        <p class="fhint" style={{ padding: '0 4px' }}>Webhook URL: {s.webhook_url}. Raw TOML is under General &gt; Config files.</p>
      </>}
    </SettingsFrame>
  )
}
