// Settings > Chat: model providers, chat defaults and MCP servers. All stored in data/config/chat.toml.

import { useEffect, useState } from 'preact/hooks'
import { chatVersion, toast, toastError } from '../../lib/store'
import { SecretInput, Segmented, Sheet, Switch, confirmDialog, promptDialog } from '../../components/ui'
import { IconPlus, IconTrash, IconBolt, IconRefresh } from '../../components/icons'
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
    try { load(await chatApi.saveConfig(patch)); chatVersion.value++; toast('Settings saved'); return true } catch (e) { toastError(e); return false } finally { setSaving(false) }
  }
  return { cfg, setCfg, dirty: cfg !== null && JSON.stringify(cfg) !== orig, saving, save }
}

const Skeleton = () => <div class="skeleton" style={{ height: '240px', borderRadius: '20px' }} />
const val = (e: Event) => (e.target as HTMLInputElement).value
const BLANK_PROVIDER: Provider = { id: '', name: '', format: 'openai', base_url: '', api_key: '', models: [], headers: {} }

export function ChatProviders({ title }: { title: string }) {
  const { cfg, save } = useChatConfig()
  const [edit, setEdit] = useState<{ i: number | null; p: Provider } | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [tests, setTests] = useState<Record<string, { ok: boolean; error?: string }>>({})
  const list = cfg?.providers || []
  const test = async (id: string) => {
    setTesting(id)
    try { const r = await chatApi.testProvider(id); setTests((t) => ({ ...t, [id]: r })) } catch (e) { toastError(e) } finally { setTesting(null) }
  }
  // Each sheet saves on its own; the list itself has nothing to save.
  const saveOne = async (p: Provider) => {
    if (!edit) return false
    const next = edit.i === null ? [...list, p] : list.map((x, k) => k === edit.i ? p : x)
    return save({ providers: next })
  }
  const remove = async () => {
    if (edit?.i == null) return setEdit(null)
    const p = list[edit.i]
    if (!await confirmDialog({ title: `Remove ${p.name || 'provider'}?`, body: 'Assistants that use its models fall back to the default model.', confirm: 'Remove', danger: true })) return
    if (await save({ providers: list.filter((_, k) => k !== edit.i) })) setEdit(null)
  }
  return (
    <SettingsFrame title={title}>
      {!cfg ? <Skeleton /> : <>
        <span class="fhint" style={{ display: 'block', padding: '0 4px' }}>Chat only. Agents and Workflow use the Claude CLI settings.</span>
        <div class="group-title">Providers</div>
        <div class="group">
          {list.map((p, i) => {
            const t = tests[p.id]
            return (
              <div key={p.id} class="row">
                <button type="button" class="label" style={{ textAlign: 'left', background: 'none', flex: 1 }} onClick={() => setEdit({ i, p: { ...p } })}>
                  {p.name || p.id}
                  <span class="hint">{p.format === 'anthropic' ? 'Anthropic' : 'OpenAI'} · {p.models.length} model{p.models.length === 1 ? '' : 's'}{t ? (t.ok ? ' · Connected' : ` · ${t.error}`) : ''}</span>
                </button>
                <button class="icon-btn" aria-label={`Test ${p.name}`} disabled={testing === p.id} onClick={() => test(p.id)}>{testing === p.id ? <Spark size={16} /> : <IconBolt width={18} height={18} />}</button>
              </div>
            )
          })}
          <button class="row press" onClick={() => setEdit({ i: null, p: { ...BLANK_PROVIDER } })}><span class="label"><IconPlus width={16} height={16} /> Add provider</span></button>
        </div>
      </>}
      {edit && <ProviderSheet key={edit.i ?? 'new'} init={edit.p} isNew={edit.i === null} onSave={saveOne} onRemove={remove} onClose={() => setEdit(null)} />}
    </SettingsFrame>
  )
}

function ProviderSheet({ init, isNew, onSave, onRemove, onClose }: {
  init: Provider; isNew: boolean; onSave: (p: Provider) => Promise<boolean>; onRemove: () => void; onClose: () => void
}) {
  const [p, setP] = useState(init)
  const [model, setModel] = useState('')
  const [found, setFound] = useState<string[] | null>(null)
  const [fetching, setFetching] = useState(false)
  const [saving, setSaving] = useState(false)
  const dirty = JSON.stringify(p) !== JSON.stringify(init)
  const set = <K extends keyof Provider>(k: K, v: Provider[K]) => setP((x) => ({ ...x, [k]: v }))
  const addModel = (m: string) => { m = m.trim(); if (m) setP((x) => x.models.includes(m) ? x : { ...x, models: [...x.models, m] }); setModel('') }
  const fetchModels = async () => {
    if (!p.base_url) return toast('Enter the base URL first', 'error')
    setFetching(true)
    try { const r = await chatApi.fetchModels(p); setFound(r.models); if (!r.models.length) toast('The provider returned no models') } catch (e) { toastError(e) } finally { setFetching(false) }
  }
  const submit = async () => {
    if (!p.id || !p.name || !p.base_url) return toast('Name, ID and base URL are required', 'error')
    setSaving(true)
    const ok = await onSave(p)
    setSaving(false)
    if (ok) onClose()
  }
  const close = async () => {
    if (dirty && !await confirmDialog({ title: 'Discard changes?', body: 'This provider has unsaved edits.', confirm: 'Discard', danger: true })) return
    onClose()
  }
  const rest = (found || []).filter((m) => !p.models.includes(m))
  return (
    <Sheet open onClose={close} title={isNew ? 'New provider' : p.name || 'Provider'}
      actions={<button class="btn primary small" disabled={saving || (!dirty && !isNew)} onClick={submit}>{saving ? <span class="spinner" /> : 'Save'}</button>}>
      <div class="group">
        <label class="field"><span class="flabel">Name</span><input class="input" value={p.name} placeholder="DeepSeek" onInput={(e) => set('name', val(e))} /></label>
        <label class="field"><span class="flabel">ID</span>
          <input class="input mono" value={p.id} autocapitalize="off" spellcheck={false} maxLength={40} placeholder="deepseek" disabled={!isNew} onInput={(e) => set('id', val(e).toLowerCase())} />
          {isNew && <span class="fhint">Models are saved as id/model. The ID can't be changed later.</span>}
        </label>
        <div class="field"><span class="flabel">Format</span>
          <Segmented value={p.format} onChange={(v) => set('format', v as Provider['format'])} options={[{ value: 'openai', label: 'OpenAI' }, { value: 'anthropic', label: 'Anthropic' }]} />
        </div>
        <label class="field"><span class="flabel">Base URL</span>
          <input class="input mono" value={p.base_url} autocapitalize="off" spellcheck={false} placeholder={p.format === 'anthropic' ? 'https://api.anthropic.com/v1' : 'https://api.openai.com/v1'} onInput={(e) => set('base_url', val(e).trim())} />
          <span class="fhint">Include /v1, e.g. {p.format === 'anthropic' ? 'https://api.anthropic.com/v1' : 'https://api.openai.com/v1'}</span>
        </label>
        <label class="field"><span class="flabel">API key</span>
          <SecretInput value={p.api_key} placeholder="sk-..." label="API key" onInput={(v) => set('api_key', v)} />
        </label>
      </div>
      <div class="group-title" style={{ display: 'flex', alignItems: 'center' }}>
        <span style={{ flex: 1 }}>Models</span>
        <button class="btn small ghost" disabled={fetching} onClick={fetchModels}>{fetching ? <span class="spinner" /> : <IconRefresh width={14} height={14} />} Fetch from /models</button>
      </div>
      <div class="chips" style={{ padding: '2px 2px 10px' }}>
        {p.models.map((m) => <button key={m} class="chip pink" onClick={() => set('models', p.models.filter((x) => x !== m))} aria-label={`Remove ${m}`}>{m} ×</button>)}
        {!p.models.length && <span class="fhint">No models yet.</span>}
      </div>
      {rest.length > 0 && <>
        <div class="field-row" style={{ alignItems: 'center', padding: '0 2px 6px' }}>
          <span class="fhint" style={{ flex: 1 }}>{rest.length} more offered by the provider</span>
          <button class="btn small ghost" onClick={() => setP((x) => ({ ...x, models: [...x.models, ...rest] }))}>Add all</button>
        </div>
        <div class="chips model-found">
          {rest.map((m) => <button key={m} class="chip" onClick={() => addModel(m)}>+ {m}</button>)}
        </div>
      </>}
      <div class="field-row" style={{ alignItems: 'center', gap: '8px', marginTop: '10px' }}>
        <input class="input mono" style={{ flex: 1 }} value={model} placeholder="model id" autocapitalize="off" spellcheck={false}
          onInput={(e) => setModel(val(e))} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addModel(model) } }} />
        <button class="btn small" onClick={() => addModel(model)}>Add</button>
      </div>
      {!isNew && <button class="btn danger block" style={{ marginTop: '18px' }} onClick={onRemove}><IconTrash width={18} height={18} /> Remove provider</button>}
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
        </div>
        <div class="group-title">System prompt</div>
        <div class="group">
          <label class="field"><textarea class="input" rows={6} value={d.system_prompt} placeholder="Empty sends no system prompt" onInput={(e) => set('system_prompt', (e.target as HTMLTextAreaElement).value)} /></label>
        </div>
      </>}
    </SettingsFrame>
  )
}

export function ChatTitles({ title }: { title: string }) {
  const { cfg, setCfg, dirty, saving, save } = useChatConfig()
  const t = cfg?.titles
  const set = <K extends keyof ChatConfig['titles']>(k: K, v: ChatConfig['titles'][K]) => setCfg((c) => c && { ...c, titles: { ...c.titles, [k]: v } })
  const models = (cfg?.providers || []).flatMap((p) => p.models.map((m) => ({ id: `${p.id}/${m}`, label: `${m} · ${p.name || p.id}` })))
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => cfg && save({ titles: cfg.titles })}>
      {!t ? <Skeleton /> : <>
        <div class="group">
          <div class="row"><span class="label">Generate titles<span class="hint">Name each new chat with a short title written by a model</span></span>
            <Switch on={t.enabled} onChange={(v) => set('enabled', v)} label="Generate titles" /></div>
        </div>
        <p class="fhint" style={{ padding: '8px 4px 0' }}>The first sentence of your message is used as the title right away. If generation fails, it stays. Renaming a chat yourself always wins.</p>
        <div class="group-title">Model</div>
        <div class="group">
          <div class="field"><span class="flabel">Title model</span>
            <select class="input" value={t.model} disabled={!t.enabled} onChange={(e) => set('model', (e.target as HTMLSelectElement).value)}>
              <option value="">Same as the conversation</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
        </div>
        <div class="group-title">Prompt</div>
        <div class="group">
          <label class="field"><textarea class="input" rows={4} disabled={!t.enabled} value={t.prompt} placeholder={TITLE_PROMPT} onInput={(e) => set('prompt', (e.target as HTMLTextAreaElement).value)} /></label>
        </div>
        <p class="fhint" style={{ padding: '8px 4px 0' }}>Empty uses the built-in instruction shown above. The first message of the chat is sent after it.</p>
      </>}
    </SettingsFrame>
  )
}

const TITLE_PROMPT = 'Write only a short title for this conversation, at most 30 characters, in the language of the message.'

export function ChatFiles({ title }: { title: string }) {
  const { cfg, setCfg, dirty, saving, save } = useChatConfig()
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => cfg && save({ files: cfg.files, memory: cfg.memory })}>
      {!cfg ? <Skeleton /> : <>
        <div class="group">
          <div class="row"><span class="label">Files<span class="hint">Assistants can keep text files and read them in chats, and chats accept text file attachments</span></span>
            <Switch on={cfg.files.enabled} onChange={(v) => setCfg({ ...cfg, files: { enabled: v } })} label="Files" /></div>
          <div class="row"><span class="label">Memory<span class="hint">Assistants can save facts and preferences and recall them in later chats</span></span>
            <Switch on={cfg.memory.enabled} onChange={(v) => setCfg({ ...cfg, memory: { enabled: v } })} label="Memory" /></div>
        </div>
        <p class="fhint" style={{ padding: '8px 4px 0' }}>These are global switches. Each assistant also has its own Files and Memory switches, and a feature is on only when both are on. Existing files and memory stay saved while a switch is off.</p>
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
