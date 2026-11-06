// Settings > Agents > Claude Code CLI: the CLI setup shared by Agents and Workflow (core.toml [server]).

import { useEffect, useState } from 'preact/hooks'
import { api } from '../../../lib/api'
import { SecretInput } from '../../../components/ui'
import { SettingsFrame, useConfigForm } from '../../settings/Frame'
import type { ConfigForm } from '../../../lib/types'

export function ClaudeCliSettings({ title }: { title: string }) {
  const { form, setForm, dirty, saving, save } = useConfigForm()
  const [status, setStatus] = useState<{ live: number; max_concurrent: number; queued: number; memory_mb: number } | null>(null)
  useEffect(() => {
    const poll = () => api.status().then(setStatus).catch(() => {})
    poll()
    const t = setInterval(poll, 5000)
    return () => clearInterval(t)
  }, [])
  const set = <K extends keyof ConfigForm['server']>(k: K, v: ConfigForm['server'][K]) => setForm(form && { ...form, server: { ...form.server, [k]: v } })
  const onSave = () => {
    if (!form) return
    const { max_concurrent, cli_path, anthropic_base_url, anthropic_api_key } = form.server
    save({ server: { max_concurrent, cli_path, anthropic_base_url, anthropic_api_key } as ConfigForm['server'] })
  }
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={onSave}>
      <div class="stats card" style={{ padding: '16px' }}>
        <div><b>{status ? `${status.live}/${status.max_concurrent}` : '-'}</b><span>Live CLIs</span></div>
        <div><b>{status?.queued ?? '-'}</b><span>Queued</span></div>
        <div><b>{status ? `${Math.round(status.memory_mb)} MB` : '-'}</b><span>Memory</span></div>
      </div>
      <p class="fhint" style={{ padding: '14px 4px 0' }}>Used by Claude agents and by Workflow agent cards; both share the same queue.</p>
      {!form ? <div class="skeleton" style={{ height: '320px', marginTop: '12px', borderRadius: '20px' }} /> : (
        <div class="group" style={{ marginTop: '12px' }}>
          <label class="field"><span class="flabel">Max live CLI processes</span>
            <input class="input" type="number" min={1} value={form.server.max_concurrent}
              onInput={(e) => set('max_concurrent', Number((e.target as HTMLInputElement).value))} />
            <span class="fhint">Each one uses about 200 MB. Extra conversations wait in a queue.</span>
          </label>
          <label class="field"><span class="flabel">Claude Code CLI path</span>
            <input class="input mono" value={form.server.cli_path} placeholder="Bundled with the SDK" autocapitalize="off" spellcheck={false}
              onInput={(e) => set('cli_path', (e.target as HTMLInputElement).value)} />
          </label>
          <label class="field"><span class="flabel">API base URL</span>
            <input class="input mono" value={form.server.anthropic_base_url ?? ''} placeholder="https://api.anthropic.com" autocapitalize="off" spellcheck={false}
              onInput={(e) => set('anthropic_base_url', (e.target as HTMLInputElement).value)} />
            <span class="fhint">Passed to every CLI as ANTHROPIC_BASE_URL. Empty uses the CLI default.</span>
          </label>
          <label class="field"><span class="flabel">API key</span>
            <SecretInput value={form.server.anthropic_api_key ?? ''} placeholder="sk-ant-..." label="API key" onInput={(v) => set('anthropic_api_key', v)} />
            <span class="fhint">Passed as ANTHROPIC_API_KEY. Empty uses the CLI login. Agent env variables override both.</span>
          </label>
        </div>
      )}
    </SettingsFrame>
  )
}
