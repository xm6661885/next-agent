// Create or edit an agent. Every config.toml field is reachable here, grouped by topic.

import { useEffect, useRef, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { agents, meta, toast, toastError } from '../lib/store'
import { back, navigate } from '../lib/router'
import { Avatar, CRAB_COLORS, Crab } from '../components/crab'
import { BackButton, Segmented, Switch, TopBar, confirmDialog, useScrolled } from '../components/ui'
import { IconTrash } from '../components/icons'
import { ModelPicker } from '../components/ModelPicker'
import { MODE_LABELS } from '../lib/util'
import type { Agent } from '../lib/types'

const BLANK: Partial<Agent> = {
  name: '', avatar: 'crab:pink', description: '', cwd: '', model: '', fallback_model: '', effort: '',
  thinking: '', thinking_budget: 0, permission_mode: 'bypassPermissions', system_prompt_mode: 'preset', system_prompt: '',
  claude_md: 'inherit', setting_sources: ['user', 'project', 'local'], tools: [], allowed_tools: [], disallowed_tools: [],
  add_dirs: [], max_turns: 0, max_budget_usd: 0, env: {}, mcp_servers: {}, agents: {}, enable_file_checkpointing: true,
  file_output: '', file_output_prompt: '', extra_args: {},
}

const EFFORTS = ['', 'low', 'medium', 'high', 'xhigh', 'max']
const lines = (v: string) => v.split('\n').map((s) => s.trim()).filter(Boolean)

export function AgentSettings({ agentId }: { agentId?: string }) {
  const isNew = !agentId
  const { scrolled, onScroll, ref: scrollRef } = useScrolled()
  const [a, setA] = useState<Partial<Agent> | null>(isNew ? { ...BLANK } : null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const [claudeMd, setClaudeMd] = useState<{ content: string; path: string; exists: boolean } | null>(null)
  const [mdDirty, setMdDirty] = useState(false)
  const [json, setJson] = useState({ env: '{}', mcp_servers: '{}', agents: '{}', extra_args: '{}' })
  const [jsonErr, setJsonErr] = useState<Record<string, string>>({})
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!meta.value) api.meta().then((m) => { meta.value = m }).catch(() => {})
    if (isNew) return
    api.agent(agentId!).then((x) => {
      setA(x)
      setOrig(JSON.stringify(x))
      setJson({
        env: JSON.stringify(x.env || {}, null, 2),
        mcp_servers: JSON.stringify(x.mcp_servers || {}, null, 2),
        agents: JSON.stringify(x.agents || {}, null, 2),
        extra_args: JSON.stringify(x.extra_args || {}, null, 2),
      })
    }).catch(toastError)
    api.getClaudeMd(agentId!).then(setClaudeMd).catch(() => setClaudeMd(null))
  }, [agentId])

  useEffect(() => {
    if (!isNew && a && orig && JSON.parse(orig).claude_md !== a.claude_md) {
      // The CLAUDE.md location depends on the mode; reload once the mode is saved.
    }
  }, [a?.claude_md])

  if (!a) {
    return (
      <div class="page">
        <TopBar left={<BackButton onClick={() => back()} />} title="Agent settings" />
        <div class="container"><div class="skeleton" style={{ height: '300px', marginTop: '20px', borderRadius: '20px' }} /></div>
      </div>
    )
  }

  const set = <K extends keyof Agent>(k: K, v: Agent[K]) => setA({ ...a, [k]: v })
  const setJsonField = (k: keyof typeof json, v: string) => {
    setJson({ ...json, [k]: v })
    try {
      const parsed = v.trim() ? JSON.parse(v) : {}
      if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) throw new Error('Must be a JSON object')
      setJsonErr({ ...jsonErr, [k]: '' })
    } catch (e: any) {
      setJsonErr({ ...jsonErr, [k]: e.message })
    }
  }

  const modes = meta.value?.permission_modes || Object.keys(MODE_LABELS)

  const save = async () => {
    if (!a.name?.trim()) return toast('Give your agent a name', 'error')
    if (!a.cwd?.trim()) return toast('Choose a working directory', 'error')
    if (Object.values(jsonErr).some(Boolean)) return toast('Fix the JSON fields first', 'error')
    const body: Partial<Agent> = { ...a }
    for (const k of ['env', 'mcp_servers', 'agents', 'extra_args'] as const) {
      body[k] = (json[k].trim() ? JSON.parse(json[k]) : {}) as any
    }
    delete body.status
    setSaving(true)
    try {
      const saved = isNew ? await api.createAgent(body) : await api.updateAgent(agentId!, body)
      if (mdDirty && claudeMd && !isNew) await api.putClaudeMd(saved.id, claudeMd.content)
      agents.value = null
      toast(isNew ? 'Agent created' : 'Saved')
      if (isNew) navigate({ name: 'agent', agentId: saved.id }, { replace: true })
      else {
        setA(saved)
        setOrig(JSON.stringify(saved))
        setMdDirty(false)
        api.getClaudeMd(saved.id).then(setClaudeMd).catch(() => {})
      }
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }

  const remove = async () => {
    const ok = await confirmDialog({
      title: `Delete ${a.name}?`,
      body: 'The agent and its conversation list are removed from next-agent. Files in its folder and Claude Code transcripts stay on disk.',
      confirm: 'Delete agent', danger: true,
    })
    if (!ok) return
    try {
      await api.deleteAgent(agentId!)
      agents.value = (agents.value || []).filter((x) => x.id !== agentId)
      toast('Agent deleted')
      navigate({ name: 'home' }, { replace: true })
    } catch (e) { toastError(e) }
  }

  const onAvatarFile = async (e: Event) => {
    const f = (e.target as HTMLInputElement).files?.[0]
    ;(e.target as HTMLInputElement).value = ''
    if (!f) return
    if (isNew) return toast('Save the agent first, then upload a picture', 'error')
    try {
      const saved = await api.uploadAvatar(agentId!, f)
      setA({ ...a, avatar: saved.avatar, order: saved.order })
      toast('Avatar updated')
    } catch (err) { toastError(err) }
  }

  const dirty = isNew || JSON.stringify({ ...a, status: undefined }) !== JSON.stringify({ ...JSON.parse(orig || '{}'), status: undefined }) || mdDirty
    || ['env', 'mcp_servers', 'agents', 'extra_args'].some((k) => {
      try { return JSON.stringify(JSON.parse((json as any)[k] || '{}')) !== JSON.stringify((JSON.parse(orig || '{}') as any)[k] || {}) } catch { return true }
    })

  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label={isNew ? 'Cancel' : 'Back'} onClick={() => back()} />}
        right={<button class="btn primary small" disabled={saving || !dirty} onClick={save}>{saving ? <span class="spinner" /> : isNew ? 'Create' : 'Save'}</button>}>
        <span class="topbar-center">{isNew ? 'New agent' : 'Agent settings'}</span>
      </TopBar>
      <div class="page-scroll" ref={scrollRef} onScroll={onScroll}>
        <div class="container settings">
          <div class="avatar-editor rise">
            <Avatar agent={{ id: agentId || 'new', avatar: a.avatar || 'crab:pink', order: a.order || 0 }} size={92} />
            <div class="crab-swatches">
              {Object.entries(CRAB_COLORS).map(([k, c]) => (
                <button key={k} type="button" class={`swatch ${a.avatar === `crab:${k}` ? 'on' : ''}`} style={{ background: c.bg }}
                  aria-label={`${k} crab`} onClick={() => set('avatar', `crab:${k}`)}>
                  <Crab color={c.body} />
                </button>
              ))}
              <button type="button" class={`swatch upload ${a.avatar === 'file' ? 'on' : ''}`} onClick={() => fileRef.current?.click()}>
                Photo
              </button>
              <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={onAvatarFile} />
            </div>
          </div>

          <div class="group-title">Identity</div>
          <div class="group">
            <label class="field"><span class="flabel">Name</span>
              <input class="input" value={a.name} placeholder="Claude" onInput={(e) => set('name', (e.target as HTMLInputElement).value)} />
            </label>
            <label class="field"><span class="flabel">Description</span>
              <input class="input" value={a.description} placeholder="What this agent is for"
                onInput={(e) => set('description', (e.target as HTMLInputElement).value)} />
            </label>
            <label class="field"><span class="flabel">Working directory</span>
              <input class="input mono" value={a.cwd} autocapitalize="off" spellcheck={false} placeholder="/home/you/project"
                onInput={(e) => set('cwd', (e.target as HTMLInputElement).value)} />
              <span class="fhint">Claude Code runs here. Project CLAUDE.md, settings and history follow this folder.</span>
            </label>
          </div>

          <div class="group-title">Model</div>
          <div class="group">
            <div class="field"><span class="flabel">Model</span>
              <ModelPicker value={a.model || ''} onChange={(m) => set('model', m)}
                defaultLabel={meta.value?.defaults.model ? `Default (${meta.value.defaults.model})` : 'Claude Code default'} />
            </div>
            <div class="field"><span class="flabel">Fallback model</span>
              <ModelPicker value={a.fallback_model || ''} onChange={(m) => set('fallback_model', m)} defaultLabel="None" />
              <span class="fhint">Used when the main model is overloaded.</span>
            </div>
            <div class="field"><span class="flabel">Effort</span>
              <Segmented value={a.effort || ''} onChange={(v) => set('effort', v)}
                options={EFFORTS.map((e) => ({ value: e, label: e || 'Default' }))} />
            </div>
            <div class="field"><span class="flabel">Extended thinking</span>
              <Segmented value={a.thinking || ''} onChange={(v) => set('thinking', v)}
                options={[{ value: '', label: 'Default' }, { value: 'adaptive', label: 'Adaptive' }, { value: 'enabled', label: 'Budget' }, { value: 'disabled', label: 'Off' }]} />
              {a.thinking === 'enabled' && (
                <input class="input" style={{ marginTop: '10px' }} type="number" min={1024} step={1024} value={a.thinking_budget || 8000}
                  onInput={(e) => set('thinking_budget', Number((e.target as HTMLInputElement).value))} />
              )}
            </div>
          </div>

          <div class="group-title">Permissions</div>
          <div class="group">
            <div class="field"><span class="flabel">Permission mode</span>
              <select class="select" value={a.permission_mode} onChange={(e) => set('permission_mode', (e.target as HTMLSelectElement).value)}>
                {modes.map((m) => <option value={m}>{MODE_LABELS[m] || m}</option>)}
              </select>
              <span class="fhint">Ask before acting shows approval cards in the chat. You can switch modes inside any conversation.</span>
            </div>
            <label class="field"><span class="flabel">Always allowed tools</span>
              <textarea class="textarea mono" rows={2} value={(a.allowed_tools || []).join('\n')} placeholder={'Read\nBash(git status:*)'}
                onInput={(e) => set('allowed_tools', lines((e.target as HTMLTextAreaElement).value))} />
            </label>
            <label class="field"><span class="flabel">Blocked tools</span>
              <textarea class="textarea mono" rows={2} value={(a.disallowed_tools || []).join('\n')} placeholder="WebFetch"
                onInput={(e) => set('disallowed_tools', lines((e.target as HTMLTextAreaElement).value))} />
            </label>
            <label class="field"><span class="flabel">Available tools</span>
              <textarea class="textarea mono" rows={2} value={(a.tools || []).join('\n')} placeholder="Empty means all built-in tools"
                onInput={(e) => set('tools', lines((e.target as HTMLTextAreaElement).value))} />
            </label>
            <label class="field"><span class="flabel">Extra directories</span>
              <textarea class="textarea mono" rows={2} value={(a.add_dirs || []).join('\n')} placeholder="/srv/shared"
                onInput={(e) => set('add_dirs', lines((e.target as HTMLTextAreaElement).value))} />
            </label>
          </div>

          <div class="group-title">Instructions</div>
          <div class="group">
            <div class="field"><span class="flabel">CLAUDE.md</span>
              <Segmented value={a.claude_md || 'inherit'} onChange={(v) => set('claude_md', v)}
                options={[{ value: 'inherit', label: 'From folder' }, { value: 'custom', label: 'Agent only' }]} />
              <span class="fhint">
                {a.claude_md === 'custom'
                  ? 'A private CLAUDE.md stored with this agent and added to its system prompt.'
                  : 'Edits the CLAUDE.md in the working directory, shared with the Claude Code CLI.'}
              </span>
              {isNew ? (
                <span class="fhint">You can edit CLAUDE.md after creating the agent.</span>
              ) : claudeMd && JSON.parse(orig || '{}').claude_md === a.claude_md ? (
                <>
                  <textarea class="textarea mono md-editor" rows={10} value={claudeMd.content} spellcheck={false}
                    placeholder="# Instructions for this agent"
                    onInput={(e) => { setClaudeMd({ ...claudeMd, content: (e.target as HTMLTextAreaElement).value }); setMdDirty(true) }} />
                  <span class="fhint mono-hint">{claudeMd.path}{claudeMd.exists ? '' : ' (will be created)'}</span>
                </>
              ) : (
                <span class="fhint">Save to switch, then edit the file here.</span>
              )}
            </div>
            <div class="field"><span class="flabel">System prompt</span>
              <Segmented value={a.system_prompt_mode || 'preset'} onChange={(v) => set('system_prompt_mode', v)}
                options={[{ value: 'preset', label: 'Claude Code + append' }, { value: 'custom', label: 'Replace' }]} />
              <textarea class="textarea" style={{ marginTop: '10px' }} rows={4} value={a.system_prompt}
                placeholder={a.system_prompt_mode === 'custom' ? 'Full system prompt' : 'Extra instructions appended to the Claude Code prompt'}
                onInput={(e) => set('system_prompt', (e.target as HTMLTextAreaElement).value)} />
            </div>
            <div class="field"><span class="flabel">Setting sources</span>
              <div class="checks">
                {['user', 'project', 'local'].map((s) => (
                  <label class="check-label">
                    <input type="checkbox" checked={(a.setting_sources || []).includes(s)}
                      onChange={(e) => {
                        const on = (e.target as HTMLInputElement).checked
                        const cur = new Set(a.setting_sources || [])
                        on ? cur.add(s) : cur.delete(s)
                        set('setting_sources', ['user', 'project', 'local'].filter((x) => cur.has(x)))
                      }} />
                    {s}
                  </label>
                ))}
              </div>
              <span class="fhint">User settings hold your API credentials, so keep them on.</span>
            </div>
          </div>

          <FileOutput a={a} set={set} />

          <div class="group-title">Limits</div>
          <div class="group">
            <label class="field"><span class="flabel">Max turns per message</span>
              <input class="input" type="number" min={0} value={a.max_turns || 0}
                onInput={(e) => set('max_turns', Number((e.target as HTMLInputElement).value))} />
              <span class="fhint">0 means no limit.</span>
            </label>
            <label class="field"><span class="flabel">Budget per run (USD)</span>
              <input class="input" type="number" min={0} step={0.5} value={a.max_budget_usd || 0}
                onInput={(e) => set('max_budget_usd', Number((e.target as HTMLInputElement).value))} />
            </label>
            <div class="row">
              <span class="label">File checkpoints<span class="hint">Lets you rewind file changes from a message.</span></span>
              <Switch on={!!a.enable_file_checkpointing} onChange={(v) => set('enable_file_checkpointing', v)} label="File checkpoints" />
            </div>
          </div>

          <div class="group-title">Advanced</div>
          <div class="group">
            {([
              ['mcp_servers', 'MCP servers', '{ "name": { "type": "stdio", "command": "npx", "args": [] } }'],
              ['agents', 'Subagents', '{ "reviewer": { "description": "...", "prompt": "...", "tools": ["Read"] } }'],
              ['env', 'Environment variables', '{ "KEY": "value" }'],
              ['extra_args', 'Extra CLI arguments', '{ "flag-name": null }'],
            ] as const).map(([k, label, ph]) => (
              <label class="field" key={k}><span class="flabel">{label}</span>
                <textarea class="textarea mono" rows={4} value={json[k]} spellcheck={false} placeholder={ph}
                  onInput={(e) => setJsonField(k, (e.target as HTMLTextAreaElement).value)} />
                {jsonErr[k] && <span class="fhint" style={{ color: 'var(--danger)' }}>{jsonErr[k]}</span>}
              </label>
            ))}
          </div>

          {!isNew && (
            <button class="btn danger block" style={{ marginTop: '28px' }} onClick={remove}>
              <IconTrash width={18} height={18} /> Delete agent
            </button>
          )}
          <div style={{ height: '40px' }} />
        </div>
      </div>
    </div>
  )
}

/** File sharing prompt: on/off per agent and an optional agent-specific prompt, edited only after tapping Edit. */
function FileOutput({ a, set }: { a: Partial<Agent>; set: <K extends keyof Agent>(k: K, v: Agent[K]) => void }) {
  const [editing, setEditing] = useState(false)
  const globalOn = meta.value?.defaults.file_output ?? true
  const globalPrompt = meta.value?.defaults.file_output_prompt || ''
  const custom = !!a.file_output_prompt
  const enabled = a.file_output === 'on' || (!a.file_output && globalOn)
  return (
    <>
      <div class="group-title">Files from Claude</div>
      <div class="group">
        <div class="field"><span class="flabel">Share files in chat</span>
          <Segmented value={a.file_output || ''} onChange={(v) => set('file_output', v as Agent['file_output'])}
            options={[{ value: '', label: `Global (${globalOn ? 'on' : 'off'})` }, { value: 'on', label: 'On' }, { value: 'off', label: 'Off' }]} />
          <span class="fhint">Adds a short prompt that teaches Claude to link images and files with Markdown, so they show up as previews and downloads here.</span>
        </div>
        {enabled && (
          <div class="field"><span class="flabel">Prompt</span>
            {editing ? (
              <>
                <textarea class="textarea mono" rows={8} spellcheck={false} value={a.file_output_prompt || globalPrompt}
                  onInput={(e) => set('file_output_prompt', (e.target as HTMLTextAreaElement).value)} />
                <div class="inline-actions">
                  <button type="button" class="btn small ghost" onClick={() => { set('file_output_prompt', ''); setEditing(false) }}>Use global prompt</button>
                  <button type="button" class="btn small" onClick={() => setEditing(false)}>Done</button>
                </div>
              </>
            ) : (
              <>
                <div class="prompt-preview">{a.file_output_prompt || globalPrompt}</div>
                <div class="inline-actions">
                  <span class="fhint" style={{ flex: 1, margin: 0 }}>{custom ? 'This agent uses its own prompt.' : 'Using the global prompt from Settings.'}</span>
                  <button type="button" class="btn small" onClick={() => setEditing(true)}>Edit</button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </>
  )
}
