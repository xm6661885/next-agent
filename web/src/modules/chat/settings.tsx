// Settings > Chat: model providers, chat defaults and MCP servers. All stored in data/config/chat.toml.

import { useEffect, useState } from 'preact/hooks'
import { chatVersion, toast, toastError } from '../../lib/store'
import { Segmented, Sheet, Switch, confirmDialog, promptDialog } from '../../components/ui'
import { IconPlus, IconTrash, IconBolt } from '../../components/icons'
import { Spark } from '../../components/crab'
import { SettingsFrame } from '../settings/Frame'
import { EFFORTS, chatApi, modelLabel, type ChatConfig, type McpServer, type Provider } from './api'

/** Load chat.toml as a form, edit a draft, PATCH the changed part. */
function useChatConfig() {
  const [cfg, setCfg] = useState<ChatConfig | null>(null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const load = (c: ChatConfig) => { setCfg(c); setOrig(JSON.stringify(c)) }
  useEffect(() => { chatApi.config().then(load).catch(toastError) }, [])
  const save = async (patch: Partial<ChatConfig>) => {
    setSaving(true)
    try { load(await chatApi.saveConfig(patch)); chatVersion.value++; toast('Settings saved') } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  return { cfg, setCfg, dirty: cfg !== null && JSON.stringify(cfg) !== orig, saving, save }
}

const Skeleton = () => <div class="skeleton" style={{ height: '240px', borderRadius: '20px' }} />
const val = (e: Event) => (e.target as HTMLInputElement).value
const BLANK_PROVIDER: Provider = { id: '', name: '', format: 'openai', base_url: '', api_key: '', models: [], headers: {} }

export function ChatProviders({ title }: { title: string }) {
  const { cfg, setCfg, dirty, saving, save } = useChatConfig()
  const [edit, setEdit] = useState<number | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [tests, setTests] = useState<Record<string, { ok: boolean; error?: string; models?: string[] }>>({})
  const list = cfg?.providers || []
  const setList = (l: Provider[]) => setCfg((c) => c && { ...c, providers: l })
  const test = async (id: string) => {
    if (dirty) return toast('Save first, then test', 'error')
    setTesting(id)
    try { const r = await chatApi.testProvider(id); setTests((t) => ({ ...t, [id]: r })) } catch (e) { toastError(e) } finally { setTesting(null) }
  }
  const add = () => { setList([...list, { ...BLANK_PROVIDER }]); setEdit(list.length) }
  const remove = async (i: number) => {
    if (!await confirmDialog({ title: `Remove ${list[i].name || 'provider'}?`, body: 'Assistants that use its models fall back to the default model.', confirm: 'Remove', danger: true })) return
    setEdit(null); setList(list.filter((_, k) => k !== i))
  }
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => cfg && save({ providers: cfg.providers })}>
      {!cfg ? <Skeleton /> : <>
        <span class="fhint" style={{ display: 'block', padding: '0 4px' }}>Chat only. Agents and Workflow use the Claude CLI settings.</span>
        <div class="group-title">Providers</div>
        <div class="group">
          {list.map((p, i) => {
            const t = tests[p.id]
            return (
              <div key={i} class="row">
                <button type="button" class="label" style={{ textAlign: 'left', background: 'none', flex: 1 }} onClick={() => setEdit(i)}>
                  {p.name || p.id || 'New provider'}
                  <span class="hint">{p.format === 'anthropic' ? 'Anthropic' : 'OpenAI'} · {p.models.length} model{p.models.length === 1 ? '' : 's'}{t ? (t.ok ? ' · Connected' : ` · ${t.error}`) : ''}</span>
                </button>
                {p.id && <button class="icon-btn" aria-label={`Test ${p.name}`} disabled={testing === p.id} onClick={() => test(p.id)}>{testing === p.id ? <Spark size={16} /> : <IconBolt width={18} height={18} />}</button>}
              </div>
            )
          })}
          <button class="row press" onClick={add}><span class="label"><IconPlus width={16} height={16} /> Add provider</span></button>
        </div>
      </>}
      <ProviderSheet p={edit !== null ? list[edit] : null} found={edit !== null ? tests[list[edit]?.id]?.models : undefined}
        onChange={(p) => setList(list.map((x, k) => k === edit ? p : x))} onRemove={() => edit !== null && remove(edit)} onClose={() => setEdit(null)} />
    </SettingsFrame>
  )
}

function ProviderSheet({ p, found, onChange, onRemove, onClose }: {
  p: Provider | null; found?: string[]; onChange: (p: Provider) => void; onRemove: () => void; onClose: () => void
}) {
  const [model, setModel] = useState('')
  if (!p) return <Sheet open={false} onClose={onClose} title="">{null}</Sheet>
  const set = <K extends keyof Provider>(k: K, v: Provider[K]) => onChange({ ...p, [k]: v })
  const addModel = (m: string) => { m = m.trim(); if (m && !p.models.includes(m)) set('models', [...p.models, m]); setModel('') }
  return (
    <Sheet open onClose={onClose} title={p.name || 'Provider'}>
      <div class="group">
        <label class="field"><span class="flabel">Name</span><input class="input" value={p.name} placeholder="DeepSeek" onInput={(e) => set('name', val(e))} /></label>
        <label class="field"><span class="flabel">ID</span>
          <input class="input mono" value={p.id} autocapitalize="off" spellcheck={false} maxLength={40} placeholder="deepseek" onInput={(e) => set('id', val(e).toLowerCase())} />
          <span class="fhint">Models are saved as id/model, so renaming it changes those references.</span>
        </label>
        <div class="field"><span class="flabel">Format</span>
          <Segmented value={p.format} onChange={(v) => set('format', v as Provider['format'])} options={[{ value: 'openai', label: 'OpenAI' }, { value: 'anthropic', label: 'Anthropic' }]} />
        </div>
        <label class="field"><span class="flabel">Base URL</span>
          <input class="input mono" value={p.base_url} autocapitalize="off" spellcheck={false} placeholder={p.format === 'anthropic' ? 'https://api.anthropic.com' : 'https://api.openai.com/v1'} onInput={(e) => set('base_url', val(e).trim())} />
        </label>
        <label class="field"><span class="flabel">API key</span>
          <input class="input mono" type="password" value={p.api_key} autocomplete="off" placeholder={p.api_key_set ? 'Saved. Type to replace' : 'sk-...'} onInput={(e) => set('api_key', val(e))} />
        </label>
      </div>
      <div class="group-title">Models</div>
      <div class="chips" style={{ padding: '2px 2px 10px' }}>
        {p.models.map((m) => <button key={m} class="chip pink" onClick={() => set('models', p.models.filter((x) => x !== m))} aria-label={`Remove ${m}`}>{m} ×</button>)}
        {(found || []).filter((m) => !p.models.includes(m)).slice(0, 40).map((m) => <button key={m} class="chip" onClick={() => addModel(m)}>+ {m}</button>)}
      </div>
      <div class="field-row">
        <input class="input mono" style={{ flex: 1 }} value={model} placeholder="model id" autocapitalize="off" spellcheck={false}
          onInput={(e) => setModel(val(e))} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addModel(model) } }} />
        <button class="btn small" onClick={() => addModel(model)}>Add</button>
      </div>
      <p class="fhint">Test the connection after saving to list the models the provider offers.</p>
      <button class="btn danger block" style={{ marginTop: '18px' }} onClick={onRemove}><IconTrash width={18} height={18} /> Remove provider</button>
    </Sheet>
  )
}

export function ChatDefaults({ title }: { title: string }) {
  const { cfg, setCfg, dirty, saving, save } = useChatConfig()
  const d = cfg?.defaults
  const set = <K extends keyof ChatConfig['defaults']>(k: K, v: ChatConfig['defaults'][K]) => setCfg((c) => c && { ...c, defaults: { ...c.defaults, [k]: v } })
  const models = (cfg?.providers || []).flatMap((p) => p.models.map((m) => ({ id: `${p.id}/${m}`, label: `${m} · ${p.name || p.id}` })))
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => cfg && save({ defaults: cfg.defaults })}>
      {!d ? <Skeleton /> : <>
        <span class="fhint" style={{ display: 'block', padding: '0 4px' }}>Assistants use these unless they set their own.</span>
        <div class="group-title">Model</div>
        <div class="group">
          <div class="field"><span class="flabel">Default model</span>
            <select class="input" value={d.model} onChange={(e) => set('model', (e.target as HTMLSelectElement).value)}>
              <option value="">First model of the first provider{models[0] ? ` (${modelLabel(models[0].id)})` : ''}</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
          <div class="field"><span class="flabel">Thinking</span>
            <div class="chips">{EFFORTS.map((e) => <button key={e} type="button" class={`chip ${d.effort === e ? 'pink' : ''}`} onClick={() => set('effort', e)}>{e}</button>)}</div>
          </div>
          <div class="field-row">
            <label class="field" style={{ flex: 1 }}><span class="flabel">Temperature</span>
              <input class="input mono" type="number" step="0.1" min={-1} max={2} value={d.temperature} onInput={(e) => set('temperature', Number(val(e)))} />
            </label>
            <label class="field" style={{ flex: 1 }}><span class="flabel">Max tokens</span>
              <input class="input mono" type="number" min={0} value={d.max_tokens} onInput={(e) => set('max_tokens', Number(val(e)))} />
            </label>
          </div>
          <span class="fhint" style={{ padding: '0 16px 12px', display: 'block' }}>-1 and 0 leave the provider default.</span>
          <div class="field"><span class="flabel">Title model</span>
            <select class="input" value={d.title_model} onChange={(e) => set('title_model', (e.target as HTMLSelectElement).value)}>
              <option value="">Same as the chat</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
        </div>
        <div class="group-title">System prompt</div>
        <div class="group">
          <label class="field"><textarea class="input" rows={6} value={d.system_prompt} placeholder="Empty sends no system prompt" onInput={(e) => set('system_prompt', (e.target as HTMLTextAreaElement).value)} /></label>
        </div>
      </>}
    </SettingsFrame>
  )
}

export function ChatMcp({ title }: { title: string }) {
  const { cfg, setCfg, dirty, saving, save } = useChatConfig()
  const [edit, setEdit] = useState<string | null>(null)
  const servers = cfg?.mcp_servers || {}
  const ids = Object.keys(servers)
  const always = cfg?.defaults.mcp || []
  const setServer = (id: string, s: McpServer) => setCfg((c) => c && { ...c, mcp_servers: { ...c.mcp_servers, [id]: s } })
  const setAlways = (id: string, on: boolean) => setCfg((c) => c && { ...c, defaults: { ...c.defaults, mcp: on ? [...c.defaults.mcp, id] : c.defaults.mcp.filter((x) => x !== id) } })
  const add = async () => {
    const id = (await promptDialog({ title: 'MCP server name', value: '', confirm: 'Add' }))?.trim().toLowerCase()
    if (!id) return
    if (!/^[a-z0-9_-]{1,40}$/.test(id) || servers[id]) return toast('Use a new name of letters, digits, - or _', 'error')
    setServer(id, { type: 'http', url: '' })
    setEdit(id)
  }
  const remove = async (id: string) => {
    if (!await confirmDialog({ title: `Remove ${id}?`, body: 'Assistants and chats stop using it.', confirm: 'Remove', danger: true })) return
    setEdit(null)
    setCfg((c) => { if (!c) return c; const m = { ...c.mcp_servers }; delete m[id]; return { ...c, mcp_servers: m, defaults: { ...c.defaults, mcp: c.defaults.mcp.filter((x) => x !== id) } } })
  }
  const s = edit ? servers[edit] : null
  const kind = s ? (s.type || 'stdio') : 'stdio'
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => cfg && save({ mcp_servers: cfg.mcp_servers, defaults: cfg.defaults })}>
      {!cfg ? <Skeleton /> : <>
        <span class="fhint" style={{ display: 'block', padding: '0 4px' }}>Chat only. Servers marked on are enabled in every new chat; assistants can add more and each chat can switch them.</span>
        <div class="group-title">Servers</div>
        <div class="group">
          {ids.map((id) => {
            const v = servers[id]
            return (
              <div key={id} class="row">
                <button type="button" class="label" style={{ textAlign: 'left', background: 'none', flex: 1 }} onClick={() => setEdit(id)}>
                  {id}<span class="hint">{v.type === 'http' || v.type === 'sse' ? `${v.type.toUpperCase()} · ${v.url || 'no URL'}` : `stdio · ${(v as any).command || 'no command'}`}</span>
                </button>
                <Switch on={always.includes(id)} onChange={(on) => setAlways(id, on)} label={`${id} on by default`} />
              </div>
            )
          })}
          <button class="row press" onClick={add}><span class="label"><IconPlus width={16} height={16} /> Add MCP server</span></button>
        </div>
      </>}
      <Sheet open={!!s} onClose={() => setEdit(null)} title={edit || 'MCP server'}>
        {s && edit && <>
          <div class="group">
            <div class="field"><span class="flabel">Transport</span>
              <Segmented value={kind} onChange={(v) => setServer(edit, v === 'stdio' ? { type: 'stdio', command: '', args: [] } : { type: v as 'http' | 'sse', url: '' })}
                options={[{ value: 'http', label: 'HTTP' }, { value: 'sse', label: 'SSE' }, { value: 'stdio', label: 'Command' }]} />
            </div>
            {kind === 'stdio' ? <>
              <label class="field"><span class="flabel">Command</span>
                <input class="input mono" value={(s as any).command || ''} autocapitalize="off" spellcheck={false} placeholder="npx" onInput={(e) => setServer(edit, { ...(s as any), type: 'stdio', command: val(e) })} />
              </label>
              <label class="field"><span class="flabel">Arguments, one per line</span>
                <textarea class="input mono" rows={3} value={((s as any).args || []).join('\n')} onInput={(e) => setServer(edit, { ...(s as any), type: 'stdio', args: (e.target as HTMLTextAreaElement).value.split('\n').filter(Boolean) })} />
              </label>
            </> : (
              <label class="field"><span class="flabel">URL</span>
                <input class="input mono" value={(s as any).url || ''} autocapitalize="off" spellcheck={false} placeholder="https://example.com/mcp" onInput={(e) => setServer(edit, { ...(s as any), url: val(e).trim() })} />
              </label>
            )}
          </div>
          <button class="btn danger block" style={{ marginTop: '18px' }} onClick={() => remove(edit)}><IconTrash width={18} height={18} /> Remove server</button>
        </>}
      </Sheet>
    </SettingsFrame>
  )
}
