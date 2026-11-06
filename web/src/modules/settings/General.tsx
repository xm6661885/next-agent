// Settings > General: external API key, raw config files, sign out.

import { useEffect, useState } from 'preact/hooks'
import { api } from '../../lib/api'
import { authed, disconnectEvents, toast, toastError } from '../../lib/store'
import { SecretInput, Segmented, confirmDialog } from '../../components/ui'
import { IconLogout } from '../../components/icons'
import { SettingsFrame, useConfigForm } from './Frame'
import type { ConfigForm } from '../../lib/types'

export function GeneralSettings({ title }: { title: string }) {
  const { form, setForm, dirty, saving, save } = useConfigForm()
  const logout = async () => {
    if (!await confirmDialog({ title: 'Sign out?', body: 'Agents, chats and workflows keep running on the server.', confirm: 'Sign out' })) return
    try { await api.logout() } catch { /* ignore */ }
    disconnectEvents()
    authed.value = false
  }
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => form && save({ server: { api_key: form.server.api_key } as ConfigForm['server'] })}>
      {form && (
        <div class="group">
          <label class="field"><span class="flabel">External API key</span>
            <SecretInput value={form.server.api_key ?? ''} placeholder="Empty disables the API" label="API key"
              onInput={(v) => setForm({ ...form, server: { ...form.server, api_key: v } })} />
            <span class="fhint">GET /api/external/send?prompt=...&amp;agent_id=...&amp;key=... starts a new session. Messages to one agent run one at a time.</span>
          </label>
        </div>
      )}
      <button class="btn block" style={{ marginTop: '24px' }} onClick={logout}><IconLogout width={18} height={18} /> Sign out</button>
    </SettingsFrame>
  )
}

const FILES = ['core', 'agents', 'more_agents', 'chat', 'workflow'] as const

export function RawFiles({ title }: { title: string }) {
  const [file, setFile] = useState<string>('agents')
  const [cfg, setCfg] = useState<string | null>(null)
  const [orig, setOrig] = useState('')
  const [path, setPath] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    setCfg(null)
    api.getRawConfig(file).then((r) => { setCfg(r.content); setOrig(r.content); setPath(r.path || '') }).catch(toastError)
  }, [file])
  const save = async () => {
    if (cfg === null) return
    setSaving(true)
    try {
      const r = await api.putRawConfig(cfg, file)
      setCfg(r.content); setOrig(r.content)
      toast('Configuration saved')
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  return (
    <SettingsFrame title={title} dirty={cfg !== orig} saving={saving} onSave={save}>
      <Segmented value={file} options={FILES.map((f) => ({ value: f, label: f }))} onChange={(f) => {
        if (cfg !== orig && !confirm('Discard unsaved changes?')) return
        setFile(f)
      }} />
      <div class="group" style={{ marginTop: '12px' }}>
        <div class="field">
          {cfg === null ? <div class="skeleton" style={{ height: '240px' }} /> : (
            <textarea class="textarea mono config-editor" rows={22} spellcheck={false} value={cfg}
              onInput={(e) => setCfg((e.target as HTMLTextAreaElement).value)} />
          )}
          <span class="fhint">{path}. Changes apply right away. The password hash is hidden; change it with
            <code> uv run python -m server set-password</code>.</span>
          <button class="btn small" style={{ marginTop: '12px' }} disabled={cfg === orig} onClick={() => setCfg(orig)}>Revert</button>
        </div>
      </div>
    </SettingsFrame>
  )
}
