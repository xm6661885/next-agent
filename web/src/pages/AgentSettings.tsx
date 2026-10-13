// Create or edit an agent. Every config.toml field is reachable here, grouped by topic.

import { useEffect, useRef, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { agents, meta, toast, toastError } from '../lib/store'
import { TEMP_AGENT, back, navigate } from '../lib/router'
import { Avatar, CRAB_COLORS, Crab } from '../components/crab'
import { BackButton, Segmented, Switch, TopBar, confirmDialog, useScrolled } from '../components/ui'
import { IconChevronDown, IconTrash } from '../components/icons'
import { FileOutputFields, GenUIFields, IdleFields, ModelFields, OverrideCard, PermissionFields, SystemPromptFields } from '../components/SettingGroups'
import type { Agent, Effective, OverrideGroup } from '../lib/types'

const GROUP_FIELDS: Record<OverrideGroup, (keyof Effective)[]> = {
  model: ['model', 'effort', 'fallback_model', 'thinking', 'thinking_budget'], permissions: ['permission_mode'], system_prompt: ['system_prompt_mode', 'system_prompt'],
  file_output: ['file_output', 'file_output_prompt'], genui: ['genui', 'genui_prompt'], idle: ['idle_mode', 'idle_timeout_min', 'adaptive_keep'],
}

const BLANK: Partial<Agent> = {
  name: '', avatar: 'crab:pink', description: '', group: '', cwd: '', model: '', fallback_model: '', effort: '',
  thinking: 'adaptive', thinking_budget: 8000, permission_mode: 'bypassPermissions', system_prompt_mode: 'preset', system_prompt: '',
  claude_md: 'inherit', setting_sources: ['user', 'project', 'local'], tools: ['*'], auto_memory: true, allowed_tools: [], disallowed_tools: [],
  add_dirs: [], max_turns: 0, max_budget_usd: 0, env: {}, mcp_servers: {}, agents: {}, enable_file_checkpointing: true,
  file_output: true, file_output_prompt: '', genui: true, genui_prompt: '', idle_mode: 'timer', idle_timeout_min: 10, adaptive_keep: 1,
  override_groups: [], extra_args: {},
}

const lines = (v: string) => v.split('\n').map((s) => s.trim()).filter(Boolean)

export function AgentSettings({ agentId }: { agentId?: string }) {
  const isNew = !agentId
  const isTemp = agentId === TEMP_AGENT
  const { scrolled, onScroll, ref: scrollRef } = useScrolled()
  const [a, setA] = useState<Partial<Agent> | null>(isNew ? { ...BLANK } : null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const [claudeMd, setClaudeMd] = useState<{ content: string; path: string; exists: boolean } | null>(null)
  const [mdDirty, setMdDirty] = useState(false)
  const [rulesOpen, setRulesOpen] = useState(false)
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
    if (agentId !== TEMP_AGENT) api.getClaudeMd(agentId!).then(setClaudeMd).catch(() => setClaudeMd(null))
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

  const [groupNames, setGroupNames] = useState<string[]>([])
  useEffect(() => { api.groups().then((g) => setGroupNames(g.groups)).catch(() => {}) }, [])
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

  const groups = a.override_groups || []
  const on = (g: OverrideGroup) => groups.includes(g)
  const global = meta.value?.defaults
  /** Values a section shows: the agent's own when overridden, else the global defaults (read-only). */
  const view = (g: OverrideGroup): Effective => (on(g) ? { ...(global as any), ...a } : { ...(a as any), ...(global || {}) }) as Effective
  const toggle = (g: OverrideGroup, v: boolean) => {
    if (!v) return setA({ ...a, override_groups: groups.filter((x) => x !== g) })
    // Turning a group on that was not saved as overridden starts from the global values.
    const saved = orig && (JSON.parse(orig).override_groups || []).includes(g)
    const seed = saved || !global ? {} : Object.fromEntries(GROUP_FIELDS[g].map((f) => [f, (global as any)[f]]))
    setA({ ...a, ...seed, override_groups: [...groups, g] })
  }
  const card = (g: OverrideGroup, title: string, body: any) =>
    <OverrideCard title={title} override={on(g)} onOverride={(v) => toggle(g, v)}>{body}</OverrideCard>

  const save = async () => {
    if (!a.name?.trim()) return toast('Give your agent a name', 'error')
    if (!isTemp && !a.cwd?.trim()) return toast('Choose a working directory', 'error')
    if (isNew && a.id && !/^[a-z0-9-]{1,40}$/.test(a.id)) return toast('ID can only use a-z, 0-9 and -', 'error')
    if (Object.values(jsonErr).some(Boolean)) return toast('Fix the JSON fields first', 'error')
    const body: Partial<Agent> = { ...a }
    for (const k of ['env', 'mcp_servers', 'agents', 'extra_args'] as const) {
      body[k] = (json[k].trim() ? JSON.parse(json[k]) : {}) as any
    }
    delete body.status
    delete body.effective
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
        if (!isTemp) api.getClaudeMd(saved.id).then(setClaudeMd).catch(() => {})
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
        <span class="topbar-center">{isNew ? 'New agent' : isTemp ? 'Temporary chat settings' : 'Agent settings'}</span>
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
            {isNew && <label class="field"><span class="flabel">ID</span>
              <input class="input mono" value={a.id || ''} autocapitalize="off" spellcheck={false} maxLength={40} placeholder="derived from name"
                onInput={(e) => set('id', (e.target as HTMLInputElement).value.toLowerCase())} />
              <span class="fhint">Lowercase letters, digits and -. Used in URLs and data folders; it can't be changed later.</span>
            </label>}
            {!isNew && !isTemp && <div class="field"><span class="flabel">ID</span>
              <span class="fhint mono">{agentId}</span>
            </div>}
            <label class="field"><span class="flabel">Description</span>
              <input class="input" value={a.description} placeholder="What this agent is for"
                onInput={(e) => set('description', (e.target as HTMLInputElement).value)} />
            </label>
            {!isTemp && groupNames.length > 0 && <div class="field"><span class="flabel">Group</span>
              <div class="chips" role="radiogroup" aria-label="Group">
                {['', ...groupNames].map((g) => (
                  <button key={g || '_none'} type="button" role="radio" aria-checked={(a.group || '') === g}
                    class={`chip ${(a.group || '') === g ? 'pink' : ''}`} onClick={() => set('group', g)}>{g || 'None'}</button>
                ))}
              </div>
              <span class="fhint">Manage groups from the tag button on Home.</span>
            </div>}
            {!isTemp && <label class="field"><span class="flabel">Working directory</span>
              <input class="input mono" value={a.cwd} autocapitalize="off" spellcheck={false} placeholder="/home/you/project"
                onInput={(e) => set('cwd', (e.target as HTMLInputElement).value)} />
              <span class="fhint">Claude Code runs here. Project CLAUDE.md, settings and history follow this folder.</span>
            </label>}
          </div>

          {card('model', 'Model', <ModelFields v={view('model')} set={set as any} />)}
{card('permissions', 'Permissions', <PermissionFields v={view('permissions')} set={set as any} />)}
          <div class="group">
            <ToolField label="Available tools" hint="Built-in tools this agent can use. None selected means no built-in tools." value={a.tools || []}
              onChange={(v) => set('tools', v)} placeholder={'Read\nGrep'} all />
            <div class="row">
              <span class="label">Memory<span class="hint">Auto memory across sessions. Off sets CLAUDE_CODE_DISABLE_AUTO_MEMORY=1.</span></span>
              <Switch on={a.auto_memory !== false} onChange={(v) => set('auto_memory', v)} label="Memory" />
            </div>
            <button type="button" class={`tool-adv ${rulesOpen ? 'open' : ''}`} onClick={() => setRulesOpen(!rulesOpen)}>
              Allow and block rules{(a.allowed_tools?.length || a.disallowed_tools?.length) ? ` (${(a.allowed_tools?.length || 0) + (a.disallowed_tools?.length || 0)})` : ''} <IconChevronDown width={14} height={14} />
            </button>
            {rulesOpen && <>
              <ToolField label="Always allowed tools" hint="allowed_tools: run without asking, even in Ask before acting." value={a.allowed_tools || []}
                onChange={(v) => set('allowed_tools', v)} placeholder={'Read\nBash(git status:*)'} />
              <ToolField label="Blocked tools" hint="disallowed_tools: removed from this agent, overriding everything else." value={a.disallowed_tools || []}
                onChange={(v) => set('disallowed_tools', v)} placeholder="WebFetch" danger />
            </>}
            <label class="field"><span class="flabel">Extra directories</span>
              <textarea class="textarea mono" rows={2} value={(a.add_dirs || []).join('\n')} placeholder="/srv/shared"
                onInput={(e) => set('add_dirs', lines((e.target as HTMLTextAreaElement).value))} />
            </label>
          </div>

          <div class="group-title">Instructions</div>
          <div class="group">
            {!isTemp && <div class="field"><span class="flabel">CLAUDE.md</span>
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
            </div>}
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
            </div>
          </div>

          {card('system_prompt', 'System prompt', <SystemPromptFields v={view('system_prompt')} set={set as any} />)}
          {card('idle', 'Sleep', <IdleFields v={view('idle')} set={set as any} />)}
          {card('file_output', 'Files from Claude', <FileOutputFields v={view('file_output')} set={set as any} disabled={!on('file_output')} builtin={meta.value?.defaults.file_output_prompt || ''} />)}
          {card('genui', 'Interactive UI', <GenUIFields v={view('genui')} set={set as any} disabled={!on('genui')} builtin={meta.value?.defaults.genui_prompt || ''} />)}

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

          {!isNew && !isTemp && (
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

const BUILTIN_TOOLS = ['Read', 'Write', 'Edit', 'NotebookEdit', 'Glob', 'Grep', 'Bash', 'BashOutput', 'KillShell',
  'WebFetch', 'WebSearch', 'Agent', 'TaskStop', 'SendMessage', 'ListAgents', 'Skill', 'TodoWrite', 'AskUserQuestion',
  'EnterPlanMode', 'ExitPlanMode', 'EnterWorktree', 'ExitWorktree', 'CronCreate', 'CronDelete', 'CronList',
  'ScheduleWakeup', 'Workflow', 'ReportFindings', 'LSP']

/** Chip picker for built-in tool names, with a raw rules editor (patterns, MCP tools) behind Advanced.
 *  With `all`, the value ["*"] means every built-in tool and is shown as all chips selected. */
function ToolField({ label, hint, value, onChange, placeholder, danger, all }: {
  label: string; hint: string; value: string[]; onChange: (v: string[]) => void; placeholder: string; danger?: boolean; all?: boolean
}) {
  const star = !!all && value.includes('*')
  const custom = value.filter((t) => t !== '*' && !BUILTIN_TOOLS.includes(t))
  const [adv, setAdv] = useState(custom.length > 0)
  const isOn = (t: string) => star || value.includes(t)
  const toggle = (t: string) => {
    const cur = star ? [...BUILTIN_TOOLS, ...custom] : value
    const next = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]
    onChange(all && BUILTIN_TOOLS.every((b) => next.includes(b)) ? ['*', ...custom] : next)
  }
  return (
    <div class="field"><span class="flabel">{label}</span>
      {all && <div class="tool-chips">
        <button type="button" class={`chip ${star ? 'pink' : ''}`} aria-pressed={star} onClick={() => onChange(['*', ...custom])}>All</button>
        <button type="button" class={`chip ${!star && value.length === 0 ? 'pink' : ''}`} aria-pressed={!star && value.length === 0} onClick={() => onChange([])}>None</button>
      </div>}
      <div class="tool-chips">
        {BUILTIN_TOOLS.map((t) => {
          const on = isOn(t)
          return <button type="button" key={t} class={`chip ${on ? (danger ? 'warn' : 'pink') : ''}`} aria-pressed={on} onClick={() => toggle(t)}>{t}</button>
        })}
      </div>
      <span class="fhint">{hint}{!adv && custom.length > 0 && ` Plus ${custom.length} custom rule${custom.length > 1 ? 's' : ''}.`}</span>
      <button type="button" class={`tool-adv ${adv ? 'open' : ''}`} onClick={() => setAdv(!adv)}>
        Advanced rules <IconChevronDown width={14} height={14} />
      </button>
      {adv && (
        <>
          <textarea class="textarea mono" rows={2} value={value.join('\n')} placeholder={placeholder}
            onInput={(e) => onChange(lines((e.target as HTMLTextAreaElement).value))} />
          <span class="fhint">One per line. Supports patterns like Bash(git status:*) and MCP tools like mcp__server__tool.{all && ' * means all built-in tools.'}</span>
        </>
      )}
    </div>
  )
}
