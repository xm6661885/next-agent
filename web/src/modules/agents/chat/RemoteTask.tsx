// Live view of a task this session started on another agent through the built-in collab tools (mcp__next__task_*).
// Polls the target session's items, so it works for Claude and ACP agents alike.
import { signal } from '@preact/signals'
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks'
import type { Item, ToolItem } from '../../../lib/types'
import { api } from '../../../lib/api'
import { moreAgentsApi } from '../../more-agents/api'
import { navigate } from '../../../lib/router'
import { Spark } from '../../../components/crab'
import { IconClose } from '../../../components/icons'
import { ToolCard } from './tools'
import { renderMarkdown } from './markdown'
import type { Task } from '../builtinApi'

export const remoteTaskView = signal<Task | null>(null)

/** The Task in a task_* tool result, if the result is one. */
export function taskOf(it: ToolItem): Task | null {
  if (!it.name.startsWith('mcp__next__task_') || !it.result || it.result.is_error) return null
  try {
    const t = JSON.parse(it.result.content)
    return t && typeof t.session_id === 'string' && t.module ? t as Task : null
  } catch { return null }
}

export function RemoteTaskPanel({ task }: { task: Task }) {
  const [items, setItems] = useState<Item[]>([])
  const [running, setRunning] = useState(true)
  const body = useRef<HTMLDivElement>(null)
  // Poll every 3 s while the task runs. Self-scheduling, so requests never overlap; it skips a round while the
  // page is hidden and stops for good once the task is no longer running.
  useEffect(() => {
    let on = true
    let timer: number | undefined
    const again = () => { if (on) timer = window.setTimeout(load, 3000) }
    const load = async () => {
      if (!on) return
      if (document.hidden) return again()
      try {
        const r = task.module === 'more_agents' ? await moreAgentsApi.items(task.session_id, '', 200) : await api.items(task.session_id, '', 200)
        if (!on) return
        setItems(r.items)
        const live = task.module === 'more_agents' ? await moreAgentsApi.session(task.session_id) : await api.session(task.session_id)
        if (!on) return
        const active = live.state === 'running' || live.state === 'interrupting'
        setRunning(active)
        if (active) again()
      } catch { again() /* the session may still be starting */ }
    }
    load()
    return () => { on = false; clearTimeout(timer) }
  }, [task.session_id, task.module])
  useLayoutEffect(() => { const el = body.current; if (el) el.scrollTop = el.scrollHeight }, [items.length])
  const open = () => {
    remoteTaskView.value = null
    navigate(task.module === 'more_agents' ? { name: 'more-agent-chat', agentId: task.agent_id, sessionId: task.session_id } : { name: 'chat', agentId: task.agent_id, sessionId: task.session_id })
  }
  return (
    <div class="subview" role="dialog" aria-label={task.title || 'Task'}>
      <div class="subview-head">
        <span class="subview-icon">{running ? <Spark size={14} /> : <span class="tool-dot" />}</span>
        <button class="subview-title" style={{ background: 'none', textAlign: 'left' }} onClick={open}>
          <div class="t1">{task.title || 'Task'}</div>
          <div class="t2">{task.agent_id} · {running ? 'running' : 'idle'} · open</div>
        </button>
        <button class="icon-btn" aria-label="Close" onClick={() => { remoteTaskView.value = null }}><IconClose width={18} height={18} /></button>
      </div>
      <div class="subview-body" ref={body}>
        {items.length === 0 && <div class="subview-empty">{running ? 'Starting' : 'No steps recorded'}</div>}
        {items.map((c) => c.kind === 'tool' ? <ToolCard key={c.id} it={c} />
          : c.kind === 'text' && c.text.trim() ? <div key={c.id} class="md subview-text" dangerouslySetInnerHTML={{ __html: renderMarkdown(c.text) }} />
          : c.kind === 'user' ? <div key={c.id} class="subview-thinking">{(c as any).text}</div>
          : null)}
        {running && <div class="working"><Spark size={16} /> <span class="shimmer-text">Working</span></div>}
      </div>
    </div>
  )
}
