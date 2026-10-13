// Global settings: server status, form-based config (server, defaults, models, pricing, file sharing),
// raw config.toml editor as a fallback, sign out.

import { useEffect, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { authed, disconnectEvents, meta, toast, toastError } from '../lib/store'
import { back, navigate } from '../lib/router'
import { BackButton, Switch, TopBar, confirmDialog, useScrolled } from '../components/ui'
import { IconBrain, IconChevron, IconChevronDown, IconLogout, IconPlus, IconTrash } from '../components/icons'
import { Crab } from '../components/crab'
import { FileOutputFields, GenUIFields, IdleFields, ModelFields, OverrideCard, PermissionFields, SystemPromptFields } from '../components/SettingGroups'
import type { ConfigForm, Price } from '../lib/types'

const PRICE_FIELDS: [keyof Price, string][] = [['input', 'Input'], ['output', 'Output'], ['cache_write', 'Cache write'], ['cache_read', 'Cache read']]

interface PriceRow { key: string; model: string; price: Record<keyof Price, string> }

const toRows = (p: ConfigForm['pricing']): PriceRow[] =>
  Object.entries(p).map(([model, v], i) => ({
    key: `${i}-${model}`, model,
    price: Object.fromEntries(PRICE_FIELDS.map(([k]) => [k, String(v[k] ?? 0)])) as Record<keyof Price, string>,
  }))

export function Settings() {
  const { scrolled, onScroll, ref: scrollRef } = useScrolled()
  const [status, setStatus] = useState<{ live: number; max_concurrent: number; queued: number; memory_mb: number } | null>(null)
  const [form, setForm] = useState<ConfigForm | null>(null)
  const [orig, setOrig] = useState('')
  const [rows, setRows] = useState<PriceRow[]>([])
  const [newModel, setNewModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [version, setVersion] = useState('')
  const [rawOpen, setRawOpen] = useState(false)

  const load = (f: ConfigForm) => {
    setForm(f)
    const r = toRows(f.pricing)
    setRows(r)
    setOrig(JSON.stringify({ f: { ...f, pricing: undefined }, r: r.map((x) => [x.model, x.price]) }))
  }

  useEffect(() => {
    const poll = () => api.status().then(setStatus).catch(() => {})
    poll()
    const t = setInterval(poll, 5000)
    api.config().then(load).catch(toastError)
    api.meta().then((m) => { setVersion(m.version); meta.value = m }).catch(() => {})
    return () => clearInterval(t)
  }, [])

  const dirty = form !== null && JSON.stringify({ f: { ...form, pricing: undefined }, r: rows.map((x) => [x.model, x.price]) }) !== orig

  const setServer = <K extends keyof ConfigForm['server']>(k: K, v: ConfigForm['server'][K]) =>
    setForm(form && { ...form, server: { ...form.server, [k]: v } })
  const setDef = <K extends keyof ConfigForm['defaults']>(k: K, v: ConfigForm['defaults'][K]) =>
    setForm((f) => f && { ...f, defaults: { ...f.defaults, [k]: v } })

  const save = async () => {
    if (!form) return
    const pricing: ConfigForm['pricing'] = {}
    for (const r of rows) {
      const m = r.model.trim()
      if (!m) continue
      if (pricing[m]) return toast(`Pricing for ${m} is listed twice`, 'error')
      const p = {} as Price
      for (const [k, label] of PRICE_FIELDS) {
        const n = Number(r.price[k] || 0)
        if (!Number.isFinite(n) || n < 0) return toast(`${label} price for ${m} must be a number of at least 0`, 'error')
        p[k] = n
      }
      pricing[m] = p
    }
    setSaving(true)
    try {
      const { max_concurrent, cli_path, api_key, anthropic_base_url, anthropic_api_key } = form.server
      const saved = await api.updateConfig({ server: { max_concurrent, cli_path, api_key, anthropic_base_url, anthropic_api_key }, defaults: form.defaults, pricing })
      load(saved)
      api.meta().then((m) => { meta.value = m }).catch(() => {})
      toast('Settings saved')
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }

  const addCustomModel = () => {
    const m = newModel.trim()
    if (!m || !form) return
    if (!form.defaults.custom_models.includes(m)) setDef('custom_models', [...form.defaults.custom_models, m])
    setNewModel('')
  }

  const logout = async () => {
    const ok = await confirmDialog({ title: 'Sign out?', body: 'Your agents keep running on the server.', confirm: 'Sign out' })
    if (!ok) return
    try { await api.logout() } catch { /* ignore */ }
    disconnectEvents()
    authed.value = false
  }

  const d = form?.defaults

  return (
    <div class="page wide-page">
      <TopBar scrolled={scrolled} left={<BackButton label="Agents" onClick={() => back()} />}
        right={<button class="btn primary small" disabled={!dirty || saving} onClick={save}>{saving ? <span class="spinner" /> : 'Save'}</button>}>
        <span class="topbar-center">Settings</span>
      </TopBar>
      <div class="page-scroll" ref={scrollRef} onScroll={onScroll}>
        <div class="container settings">
          <div class="group-title">Server</div>
          <div class="stats card" style={{ padding: '16px' }}>
            <div><b>{status ? `${status.live}/${status.max_concurrent}` : '-'}</b><span>Live sessions</span></div>
            <div><b>{status?.queued ?? '-'}</b><span>Queued</span></div>
            <div><b>{status ? `${Math.round(status.memory_mb)} MB` : '-'}</b><span>Memory</span></div>
          </div>

          {!form || !d ? (
            <div class="skeleton" style={{ height: '320px', marginTop: '20px', borderRadius: '20px' }} />
          ) : (
            <>
              <div class="group" style={{ marginTop: '12px' }}>
                <label class="field"><span class="flabel">Max live CLI processes</span>
                  <input class="input" type="number" min={1} value={form.server.max_concurrent}
                    onInput={(e) => setServer('max_concurrent', Number((e.target as HTMLInputElement).value))} />
                  <span class="fhint">Each one uses about 200 MB. Extra conversations wait in a queue.</span>
                </label>
                <label class="field"><span class="flabel">Claude Code CLI path</span>
                  <input class="input mono" value={form.server.cli_path} placeholder="Bundled with the SDK" autocapitalize="off" spellcheck={false}
                    onInput={(e) => setServer('cli_path', (e.target as HTMLInputElement).value)} />
                </label>
                <label class="field"><span class="flabel">API base URL</span>
                  <input class="input mono" value={form.server.anthropic_base_url ?? ''} placeholder="https://api.anthropic.com" autocapitalize="off" spellcheck={false}
                    onInput={(e) => setServer('anthropic_base_url', (e.target as HTMLInputElement).value)} />
                  <span class="fhint">Passed to every agent as ANTHROPIC_BASE_URL. Empty uses the CLI default.</span>
                </label>
                <label class="field"><span class="flabel">API key</span>
                  <input class="input mono" type="password" value={form.server.anthropic_api_key ?? ''} placeholder="sk-ant-..." autocomplete="off" autocapitalize="off" spellcheck={false}
                    onInput={(e) => setServer('anthropic_api_key', (e.target as HTMLInputElement).value)} />
                  <span class="fhint">Passed as ANTHROPIC_API_KEY. Empty uses the CLI login. Agent env variables override both.</span>
                </label>
                <label class="field"><span class="flabel">External API key</span>
                  <input class="input mono" value={form.server.api_key ?? ''} placeholder="Empty disables the API" autocapitalize="off" spellcheck={false}
                    onInput={(e) => setServer('api_key', (e.target as HTMLInputElement).value)} />
                  <span class="fhint">GET /api/external/send?prompt=...&amp;agent_id=...&amp;key=... starts a new session. Messages to one agent run one at a time.</span>
                </label>
              </div>

              <span class="fhint" style={{ display: 'block', padding: '18px 4px 0' }}>Everything below is the global default. Agents follow it unless they turn on Override global for a section.</span>
              <OverrideCard title="Model"><ModelFields v={d} set={setDef} /></OverrideCard>
              <OverrideCard title="Permissions"><PermissionFields v={d} set={setDef} /></OverrideCard>
              <OverrideCard title="System prompt"><SystemPromptFields v={d} set={setDef} /></OverrideCard>
              <OverrideCard title="Sleep"><IdleFields v={d} set={setDef} /></OverrideCard>
              <OverrideCard title="Files from Claude"><FileOutputFields v={d} set={setDef} builtin={form.default_file_output_prompt} /></OverrideCard>
              <OverrideCard title="Interactive UI"><GenUIFields v={d} set={setDef} builtin={form.default_genui_prompt} /></OverrideCard>

              <div class="group-title">Chat display</div>
              <div class="group">
                <div class="row">
                  <span class="label">Artifacts<span class="hint">A panel with every file and code block of the conversation, and long code shown as tappable cards.</span></span>
                  <Switch on={d.artifacts ?? true} onChange={(v) => setDef('artifacts', v)} label="Artifacts" />
                </div>
              </div>

              <div class="group-title">Custom models</div>
              <div class="group">
                <div class="field">
                  <span class="fhint" style={{ marginTop: 0 }}>Extra model IDs shown in every model picker.</span>
                  {d.custom_models.length > 0 && (
                    <div class="model-chips" style={{ marginTop: '10px' }}>
                      {d.custom_models.map((m) => (
                        <span class="chip removable" key={m}>
                          <span class="mono">{m}</span>
                          <button type="button" aria-label={`Remove ${m}`} onClick={() => setDef('custom_models', d.custom_models.filter((x) => x !== m))}>
                            <IconTrash width={14} height={14} />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                  <form class="model-custom" onSubmit={(e) => { e.preventDefault(); addCustomModel() }}>
                    <input class="input mono" value={newModel} placeholder="claude-opus-5-5[1m]" autocapitalize="off" spellcheck={false}
                      onInput={(e) => setNewModel((e.target as HTMLInputElement).value)} />
                    <button type="submit" class="btn small" disabled={!newModel.trim()}><IconPlus width={16} height={16} /> Add</button>
                  </form>
                </div>
              </div>

              <div class="group-title">Pricing</div>
              <div class="group">
                <div class="field">
                  <span class="fhint" style={{ marginTop: 0 }}>USD per million tokens. Models listed here use these prices for the cost shown in chats;
                    other models keep the cost reported by Claude Code. Match by model ID, with or without a suffix like [1m].</span>
                  {rows.map((r) => (
                    <div class="price-row" key={r.key}>
                      <div class="price-head">
                        <input class="input mono" value={r.model} placeholder="Model ID" autocapitalize="off" spellcheck={false}
                          onInput={(e) => setRows(rows.map((x) => x.key === r.key ? { ...x, model: (e.target as HTMLInputElement).value } : x))} />
                        <button type="button" class="icon-btn" aria-label="Remove price" onClick={() => setRows(rows.filter((x) => x.key !== r.key))}>
                          <IconTrash width={18} height={18} />
                        </button>
                      </div>
                      <div class="price-grid">
                        {PRICE_FIELDS.map(([k, label]) => (
                          <label key={k}><span>{label}</span>
                            <input class="input" type="number" inputMode="decimal" min={0} step="any" value={r.price[k]}
                              onInput={(e) => setRows(rows.map((x) => x.key === r.key ? { ...x, price: { ...x.price, [k]: (e.target as HTMLInputElement).value } } : x))} />
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                  <button type="button" class="btn small" style={{ marginTop: '12px' }}
                    onClick={() => setRows([...rows, { key: `n${Date.now()}`, model: '', price: { input: '', output: '', cache_write: '', cache_read: '' } }])}>
                    <IconPlus width={16} height={16} /> Add model price
                  </button>
                </div>
              </div>

            </>
          )}

          <div class="group-title">Claude Code</div>
          <div class="group">
            <button type="button" class="row" onClick={() => navigate({ name: 'memory' })}>
              <IconBrain width={18} height={18} />
              <span class="label">Memory<span class="hint">View and edit CLAUDE.md and every project's auto-memory on this machine.</span></span>
              <IconChevron width={16} height={16} />
            </button>
          </div>

          <button type="button" class={`group-title collapser ${rawOpen ? 'open' : ''}`} onClick={() => setRawOpen(!rawOpen)}>
            Advanced: config.toml <IconChevronDown width={15} height={15} />
          </button>
          {rawOpen && <RawConfig onSaved={() => api.config().then(load).catch(() => {})} />}

          <button class="btn block" style={{ marginTop: '28px' }} onClick={logout}><IconLogout width={18} height={18} /> Sign out</button>

          <div class="about">
            <div class="crab-wave"><Crab /></div>
            <div>next-agent {version}</div>
            <div>Built on the Claude Agent SDK</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function RawConfig({ onSaved }: { onSaved: () => void }) {
  const [cfg, setCfg] = useState<string | null>(null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => { api.getRawConfig().then((r) => { setCfg(r.content); setOrig(r.content) }).catch(toastError) }, [])
  const save = async () => {
    if (cfg === null) return
    setSaving(true)
    try {
      const r = await api.putRawConfig(cfg)
      setCfg(r.content)
      setOrig(r.content)
      toast('Configuration saved')
      onSaved()
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  return (
    <div class="group">
      <div class="field">
        {cfg === null ? <div class="skeleton" style={{ height: '240px' }} /> : (
          <textarea class="textarea mono config-editor" rows={18} spellcheck={false} value={cfg}
            onInput={(e) => setCfg((e.target as HTMLTextAreaElement).value)} />
        )}
        <span class="fhint">Every agent and server option lives here. The password hash is hidden; change it with
          <code> uv run python -m server set-password</code>.</span>
        <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
          <button class="btn small" disabled={cfg === orig} onClick={() => setCfg(orig)}>Revert</button>
          <button class="btn small primary" disabled={saving || cfg === orig} onClick={save}>
            {saving ? <span class="spinner" /> : 'Save configuration'}
          </button>
        </div>
      </div>
    </div>
  )
}
