// Settings > Agents > Built-in tools: global switches for the in-process MCP server. Mirrors docs/builtin-mcp.md.

import { useEffect, useState } from 'preact/hooks'
import { SettingsFrame, useConfigForm } from '../../settings/Frame'
import { Switch } from '../../../components/ui'
import { toastError } from '../../../lib/store'
import { api, request } from '../../../lib/api'

const CATS = [
  { key: 'history', label: 'History', hint: 'Let an agent search and read its own past conversations.', tools: [
    ['history_list', 'Recent conversations of the same agent.'],
    ['history_search', 'Text search over them.'],
    ['history_read', 'Read one as plain user, assistant and tool lines.'],
  ] },
  { key: 'collab', label: 'Collaboration', hint: 'Let an agent hand work to other agents as subagents.', tools: [
    ['agents_list', 'The agents below: name and description, so the model can pick one.'],
    ['task_create', 'Start a task (a new session) on one of them, optionally waiting for the answer.'],
    ['task_status', 'State and last reply of a task.'],
    ['task_send', 'Send a follow-up into the task.'],
    ['task_stop', 'Stop it.'],
    ['task_list', 'Tasks started by this conversation.'],
  ] },
] as const

export function BuiltinMcpSettings({ title }: { title: string }) {
  const { form, setForm, dirty, saving, save } = useConfigForm()
  const b = form?.builtin_mcp
  const set = (k: string, v: boolean) => setForm((f) => f && { ...f, builtin_mcp: { ...f.builtin_mcp, [k]: v } })
  const [subs, setSubs] = useState<{ module: string; id: string; name: string; description: string }[] | null>(null)
  useEffect(() => {
    Promise.all([api.agents(), request<{ id: string; name: string; description: string; as_subagent: boolean }[]>('GET', '/api/acp/agents').catch(() => [])]).then(([a, c]) => setSubs([
      ...a.filter((x) => x.as_subagent).map((x) => ({ module: 'Claude', id: x.id, name: x.name, description: x.description })),
      ...c.filter((x) => x.as_subagent).map((x) => ({ module: 'ACP', id: x.id, name: x.name, description: x.description })),
    ])).catch(toastError)
  }, [])
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => form && save({ builtin_mcp: form.builtin_mcp })}>
      {!b ? <div class="skeleton" style={{ height: '200px', borderRadius: '20px' }} /> : <>
        <span class="fhint" style={{ display: 'block', padding: '0 4px' }}>Tools Claude agents can call. ACP agents never get them. Each agent can override these in its own settings.</span>
        <div class="group">
          <div class="row"><span class="label">Enable built-in tools<span class="hint">Master switch.</span></span><Switch on={b.enabled} onChange={(v) => set('enabled', v)} label="Enable built-in tools" /></div>
          {CATS.map((c) => (
            <div key={c.key} class="row"><span class="label">{c.label}<span class="hint">{c.hint}</span></span>
              <Switch on={b[c.key]} disabled={!b.enabled} onChange={(v) => set(c.key, v)} label={c.label} /></div>
          ))}
        </div>
      </>}
      <div class="group-title">What the model gets</div>
      <span class="fhint" style={{ display: 'block', padding: '0 4px 8px' }}>One MCP server named next. Tools show up as mcp__next__&lt;name&gt; and never ask for permission. Subagent sessions don't get Collaboration, so tasks can't start more tasks.</span>
      {CATS.map((c) => (
        <div key={c.key} class="group tool-doc">
          <div class="tool-doc-head">{c.label}</div>
          {c.tools.map(([n, d]) => <div key={n} class="tool-doc-row"><code>{n}</code><span>{d}</span></div>)}
        </div>
      ))}
      <div class="group-title">Available subagents</div>
      <span class="fhint" style={{ display: 'block', padding: '0 4px 8px' }}>agents_list returns these. The description is all the model sees when it picks one, so say what each agent is good at. Turn an agent on with Available as a subagent in its settings.</span>
      <div class="group">
        {!subs ? <div class="row"><span class="spinner" /></div> : !subs.length ? <div class="row"><span class="label"><span class="hint">No agent is available as a subagent yet.</span></span></div>
          : subs.map((x) => (
            <div key={x.module + x.id} class="row"><span class="label">{x.name}<span class="hint">{x.module} · {x.description || 'No description. The model only sees the name.'}</span></span></div>
          ))}
      </div>
    </SettingsFrame>
  )
}
