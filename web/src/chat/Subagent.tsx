// Floating window that follows one subagent's transcript live. A docked panel on desktop, a bottom sheet on phones.
import { signal } from '@preact/signals'
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks'
import type { Item, TaskInfo, ToolItem } from '../lib/types'
import type { ChatConn } from './conn'
import { api } from '../lib/api'
import { IconTerminal } from '../components/icons'
import { ToolCard, toolSummary } from './tools'
import { renderMarkdown } from './markdown'
import { Spark } from '../components/crab'
import { IconClose } from '../components/icons'

/** tool_use_id of the Agent/Task call being watched. */
export const subagentView = signal<string | null>(null)

const DONE = new Set(['completed', 'failed', 'stopped', 'killed'])

export function SubagentPanel({ tool, items: live, task, conn }: { tool: ToolItem; items: Item[]; task?: TaskInfo; conn: ChatConn }) {
  const body = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  // Live events only cover what streamed since the CLI started; the subagent's own transcript has the rest.
  const [saved, setSaved] = useState<{ agent_id: string | null; items: Item[] } | null>(null)
  // Background agents return a tool result right away; the task status says when they really finish.
  const running = task ? !DONE.has(task.status) : !tool.result
  useEffect(() => {
    let on = true
    const load = () => api.subagent(conn.sid, tool.id).then((r) => { if (on) setSaved(r) }).catch(() => {})
    load()
    // The loaded page may not hold this call's live items (older than the first page), so poll the server copy.
    const id = running ? setInterval(load, 3000) : undefined
    return () => { on = false; clearInterval(id) }
  }, [tool.id, !!tool.result, task?.status, running])
  const items = saved && saved.items.length > live.length ? saved.items : live
  const shells = conn.tasks.value.filter((t) => t.parent_tool_use_id === tool.id)
  const { verb, arg } = toolSummary(tool)
  const steps = items.filter((c) => c.kind === 'tool').length
  const final = !running && tool.result && !tool.result.is_error ? tool.result.content : ''
  useLayoutEffect(() => {
    const el = body.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  })
  const onScroll = () => {
    const el = body.current
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
  }
  return (
    <div class="subview" role="dialog" aria-label={`${verb} ${arg}`}>
      <div class="subview-head">
        <span class="subview-icon">{running ? <Spark size={14} /> : <span class="tool-dot" />}</span>
        <div class="subview-title">
          <div class="t1">{verb}</div>
          <div class="t2">{arg}{` · ${steps} step${steps === 1 ? '' : 's'}`}{running ? ' · running' : task?.status ? ` · ${task.status}` : ' · done'}</div>
        </div>
        <button class="icon-btn" aria-label="Close" onClick={() => { subagentView.value = null }}><IconClose width={18} height={18} /></button>
      </div>
      <div class="subview-body" ref={body} onScroll={onScroll}>
        {items.length === 0 && <div class="subview-empty">{running ? 'Starting' : 'No steps recorded'}</div>}
        {items.map((c) => c.kind === 'tool' ? <ToolCard key={c.id} it={c} />
          : c.kind === 'text' && c.text.trim() ? <div key={c.id} class="md subview-text" dangerouslySetInnerHTML={{ __html: renderMarkdown(c.text) }} />
          : c.kind === 'thinking' && c.text ? <div key={c.id} class="subview-thinking">{c.text}</div>
          : c.kind === 'notice' ? <div key={c.id} class={`notice ${c.level}`}>{c.text}</div>
          : null)}
        {shells.map((t) => (
          <div key={t.task_id} class={`notice ${t.status === 'failed' ? 'warn' : 'info'} subview-shell`}>
            <IconTerminal width={14} height={14} /> {t.description || t.task_id} · {DONE.has(t.status) ? t.status : 'running'}
          </div>
        ))}
        {running && <div class="working"><Spark size={16} /> <span class="shimmer-text">Working</span></div>}
        {final && !items.some((c) => c.kind === 'text' && c.text.trim() === final.trim()) && (
          <div class="subview-final"><div class="subview-label">Result</div><div class="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(final) }} /></div>
        )}
      </div>
    </div>
  )
}
