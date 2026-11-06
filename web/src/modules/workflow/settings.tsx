// Settings > Workflow: agent card concurrency, run retention, default cwd, environment variables and plugins.

import { useEffect, useState } from 'preact/hooks'
import { SettingsFrame } from '../settings/Frame'
import { Switch } from '../../components/ui'
import { IconPlus, IconRefresh, IconTrash } from '../../components/icons'
import { toast, toastError } from '../../lib/store'
import { loadCatalog, wfApi, type Catalog, type WfSettings } from './api'

type Env = { key: string; value: string }[]
/** Loaded plugin cards are grouped by where they come from (the prefix of PluginSchema.source). */
const PLUGIN_GROUPS = [['core/', 'Built-in'], ['extra/', 'Extras'], ['user/', 'User plugins']] as const
const val = (e: Event) => (e.target as HTMLInputElement).value

export function WorkflowSettings({ title }: { title: string }) {
  const [s, setS] = useState<WfSettings | null>(null)
  const [env, setEnv] = useState<Env>([])
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const [plugins, setPlugins] = useState<Catalog | null>(null)
  const [busy, setBusy] = useState(false)
  const load = (x: WfSettings) => {
    const e = Object.entries(x.env || {}).map(([key, value]) => ({ key, value }))
    setS(x); setEnv(e); setOrig(JSON.stringify([x, e]))
  }
  useEffect(() => {
    wfApi.settings().then(load).catch(toastError)
    wfApi.plugins().then(setPlugins).catch(() => {})
  }, [])
  const dirty = s !== null && JSON.stringify([s, env]) !== orig
  const set = <K extends keyof WfSettings>(k: K, v: WfSettings[K]) => setS((x) => x && { ...x, [k]: v })
  const save = async () => {
    if (!s) return
    const keys = env.map((e) => e.key.trim()).filter(Boolean)
    if (keys.some((k) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(k))) return toast('Variable names can only use letters, digits and underscores', 'error')
    if (new Set(keys).size !== keys.length) return toast('Duplicate variable name', 'error')
    setSaving(true)
    try {
      load(await wfApi.setSettings({ ...s, env: Object.fromEntries(env.filter((e) => e.key.trim()).map((e) => [e.key.trim(), e.value])) }))
      toast('Settings saved')
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  const reload = async () => {
    setBusy(true)
    try {
      const r = await wfApi.reloadPlugins()
      toast(`Loaded ${r.count} plugins${r.errors.length ? `, ${r.errors.length} failed` : ''}`)
      setPlugins(await wfApi.plugins()); loadCatalog().catch(() => {})
    } catch (e) { toastError(e) } finally { setBusy(false) }
  }
  const installDeps = async (folder: string) => {
    setBusy(true)
    try { await wfApi.installDeps(folder); toast('Dependencies installed'); setPlugins(await wfApi.plugins()); loadCatalog().catch(() => {}) } catch (e) { toastError(e) } finally { setBusy(false) }
  }

  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={save}>
      {!s ? <div class="skeleton" style={{ height: '260px', borderRadius: '20px' }} /> : <>
        <span class="fhint" style={{ display: 'block', padding: '0 4px' }}>Agent cards run as normal Agents and ACP sessions, so the Claude CLI and model settings are the Agents ones.</span>
        <div class="group-title">Runs</div>
        <div class="group">
          <div class="field-row">
            <label class="field" style={{ flex: 1 }}><span class="flabel">Agent cards at once</span>
              <input class="input mono" type="number" min={1} max={16} value={s.agent_concurrency} onInput={(e) => set('agent_concurrency', Number(val(e)))} /></label>
            <label class="field" style={{ flex: 1 }}><span class="flabel">Runs to keep</span>
              <input class="input mono" type="number" min={0} value={s.run_retention} onInput={(e) => set('run_retention', Number(val(e)))} /></label>
          </div>
          <label class="field"><span class="flabel">Default working directory</span>
            <input class="input mono" value={s.default_cwd} placeholder="data/workflow/workspace" autocapitalize="off" spellcheck={false} onInput={(e) => set('default_cwd', val(e).trim())} />
            <span class="fhint">Shell cards and relative card directories resolve against it. Runs to keep 0 keeps everything.</span>
          </label>
        </div>
        <div class="group-title">Environment variables</div>
        <div class="group">
          {env.map((e, i) => (
            <div key={i} class="row">
              <input class="input mono" style={{ flex: 1 }} value={e.key} placeholder="NAME" autocapitalize="off" spellcheck={false}
                onInput={(ev) => setEnv(env.map((x, k) => k === i ? { ...x, key: val(ev) } : x))} />
              <input class="input mono" style={{ flex: 1.4 }} value={e.value} placeholder="value" autocapitalize="off" spellcheck={false}
                onInput={(ev) => setEnv(env.map((x, k) => k === i ? { ...x, value: val(ev) } : x))} />
              <button class="icon-btn" aria-label={`Remove ${e.key}`} onClick={() => setEnv(env.filter((_, k) => k !== i))}><IconTrash width={18} height={18} /></button>
            </div>
          ))}
          <button class="row press" onClick={() => setEnv([...env, { key: '', value: '' }])}><span class="label"><IconPlus width={16} height={16} /> Add variable</span></button>
        </div>
        <p class="fhint" style={{ padding: '0 4px' }}>Every card sees them; cards can insert them as variables. Stored in workflow.toml.</p>
        <div class="group-title">Plugins</div>
        <div class="group">
          <div class="row">
            <span class="label">Watch plugin files<span class="hint">Reload data/workflow/plugins when a file changes.</span></span>
            <Switch on={s.plugin_watch} onChange={(v) => set('plugin_watch', v)} label="Watch plugin files" />
          </div>
          <button class="row press" disabled={busy} onClick={reload}><span class="label"><IconRefresh width={16} height={16} /> Reload plugins</span></button>
          {plugins?.errors.map((e) => (
            <div key={e.folder} class="row">
              <span class="label">{e.folder}<span class="hint fhint err">{e.error}</span></span>
              {e.missing_deps && <button class="btn small" disabled={busy} onClick={() => installDeps(e.folder)}>Install deps</button>}
            </div>
          ))}
        </div>
        {plugins && <p class="fhint" style={{ padding: '0 4px' }}>{plugins.plugins.length} plugins loaded. Put user plugins in data/workflow/plugins/&lt;name&gt;/plugin.py.</p>}
        {plugins && PLUGIN_GROUPS.map(([prefix, label]) => {
          const items = plugins.plugins.filter((p) => p.source?.startsWith(prefix))
          return items.length > 0 && (
            <div key={prefix}>
              <div class="group-title">{label}</div>
              <div class="group">
                {items.map((p) => (
                  <div key={p.id} class="row">
                    <span class="label">{p.name}<span class="hint mono-label">{p.id}</span></span>
                    {p.version && <span class="value">v{p.version}</span>}
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </>}
    </SettingsFrame>
  )
}
