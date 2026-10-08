// Live tray above the composer for subagents, background shells and scheduled prompts (like the CLI's "1 shell running").
import { useEffect, useState } from 'preact/hooks'
import type { TaskInfo } from '../lib/types'
import type { ChatConn } from './conn'
import { IconAgents, IconChevron, IconClock, IconTerminal } from '../components/icons'

const DONE = new Set(['completed', 'failed', 'stopped', 'killed'])
// task_type from the CLI: local_bash, local_agent, remote_agent, in_process_teammate, local_workflow, monitor_mcp, dream.
const isAgent = (t: TaskInfo) => t.task_type ? t.task_type !== 'local_bash' && t.task_type !== 'monitor_mcp' : !!t.subagent_type || !!t.usage

function elapsed(t: TaskInfo, now: number) {
  const from = t.started_at ? Date.parse(t.started_at) : NaN
  const ms = t.usage?.duration_ms ?? (isNaN(from) ? 0 : now - from)
  const s = Math.max(0, Math.round(ms / 1000))
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor(s / 60) % 60}m`
}
const tokens = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`

export function TaskTray({ conn }: { conn: ChatConn }) {
  const all = conn.tasks.value
  const [open, setOpen] = useState(false)
  const [now, setNow] = useState(Date.now())
  const live = all.filter((t) => t.kind === 'cron' || !DONE.has(t.status))
  // Show finished items for a short while so the user sees the outcome.
  const recent = all.filter((t) => t.kind !== 'cron' && DONE.has(t.status) && now - Date.parse(t.updated_at || '') < 60000)
  const shown = [...live, ...recent]
  useEffect(() => {
    if (!shown.length) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [shown.length > 0])
  if (!shown.length) return null

  const agents = live.filter((t) => t.kind !== 'cron' && isAgent(t)).length
  const shells = live.filter((t) => t.kind !== 'cron' && !isAgent(t)).length
  const crons = live.filter((t) => t.kind === 'cron').length
  const parts = [
    agents && `${agents} agent${agents > 1 ? 's' : ''} running`,
    shells && `${shells} shell${shells > 1 ? 's' : ''} running`,
    crons && `${crons} scheduled`,
  ].filter(Boolean)
  if (!parts.length) parts.push(`${recent.length} finished`)

  return (
    <div class={`task-tray ${open ? 'open' : ''}`}>
      <button class="task-pill" onClick={() => setOpen(!open)} aria-expanded={open}>
        {live.some((t) => t.kind !== 'cron') && <span class="task-pulse" />}
        <span>{parts.join(' · ')}</span>
        <IconChevron class="task-chev" width={14} height={14} />
      </button>
      {open && (
        <div class="task-list">
          {shown.map((t) => {
            const done = DONE.has(t.status)
            const cron = t.kind === 'cron'
            const Icon = cron ? IconClock : isAgent(t) ? IconAgents : IconTerminal
            const detail = cron
              ? `${t.schedule || t.cron}${t.recurring ? '' : ' · once'}`
              : done
                ? `${t.status}${t.summary ? ` · ${t.summary}` : ''}`
                : [t.last_tool_name && `Using ${t.last_tool_name}`, t.usage?.tool_uses && `${t.usage.tool_uses} steps`,
                   t.usage?.total_tokens && `${tokens(t.usage.total_tokens)} tokens`, elapsed(t, now)].filter(Boolean).join(' · ')
            return (
              <div key={t.task_id} class={`task-row ${done ? 'done' : ''} ${t.status === 'failed' ? 'err' : ''}`}>
                <Icon width={16} height={16} class="task-icon" />
                <div class="task-text">
                  <div class="task-desc">{t.subagent_type && <span class="task-kind">{t.subagent_type}</span>}{t.description || t.task_id}</div>
                  <div class="task-detail">{detail}</div>
                </div>
                {!done && !cron && (
                  <button class="btn small" onClick={() => conn.send({ type: 'stop_task', task_id: t.task_id })}>Stop</button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
