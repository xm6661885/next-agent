// Agents > Running: every working or waiting session across Claude and More Agents, from GET /api/running.

import { signal } from '@preact/signals'
import { useEffect, useRef } from 'preact/hooks'
import { api } from '../../lib/api'
import { runningVersion } from '../../lib/store'
import { navigate } from '../../lib/router'
import { Avatar, Spark } from '../../components/crab'
import { IconBolt } from '../../components/icons'
import { relTime, shortPath } from '../../lib/util'
import type { RunningRow } from '../../lib/types'
import { AcpAvatar } from '../acp/chat/Chat'

/** Last answer of /api/running. Home shows its length next to the segment label; RunningList renders it. */
export const running = signal<RunningRow[] | null>(null)

const load = () => api.running().then((r) => { running.value = r }).catch(() => {})

/** Keep `running` current while the Agents home is open: fetch on mount and after each session state change. */
export function useRunningFeed() {
  const v = runningVersion.value
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; load(); return }
    const t = setTimeout(load, 300)
    return () => clearTimeout(t)
  }, [v])
}

const rank = (r: RunningRow) => r.pending > 0 ? 0 : r.state === 'running' || r.state === 'interrupting' ? 1 : 2

export function RunningList() {
  const rows = running.value
  if (rows === null) return <div class="skeleton" style={{ height: '160px', borderRadius: '20px' }} />
  if (!rows.length) return (
    <div class="empty rise">
      <div class="empty-icon"><IconBolt width={40} height={40} /></div>
      <h3 class="serif">Nothing is running.</h3>
    </div>
  )
  // Waiting for you first, then working; the server already sorted by recency.
  const sorted = rows.slice().sort((a, b) => rank(a) - rank(b))
  return <div class="group rise" style={{ '--i': 1 }}>{sorted.map((r) => <RunningItem key={r.session_id} r={r} />)}</div>
}

function RunningItem({ r }: { r: RunningRow }) {
  const busy = r.state === 'running' || r.state === 'interrupting'
  const agent = { id: r.agent_id, avatar: r.avatar, order: 0 }
  const open = () => navigate(r.module === 'more_agents'
    ? { name: 'acp-chat', agentId: r.agent_id, sessionId: r.session_id }
    : { name: 'chat', agentId: r.agent_id, sessionId: r.session_id })
  return (
    <button class="row press" onClick={open}>
      {r.module === 'more_agents' ? <AcpAvatar a={agent} size={40} busy={busy} /> : <Avatar agent={agent} size={40} busy={busy} />}
      <span class="label">
        <span class={`session-title ${r.unread ? 'unread' : ''}`}>{r.agent_name}<span class="running-title"> · {r.title || 'New conversation'}</span></span>
        {r.cwd && <span class="hint mono-label">{shortPath(r.cwd)}</span>}
      </span>
      <span class="session-meta">
        {r.pending > 0 ? <span class="dot waiting" role="img" aria-label="Waiting for you" />
          : busy ? <Spark size={16} /> : null}
        {r.unread && <span class="unread-dot" aria-label="Unread" />}
        {relTime(r.updated_at)}
      </span>
    </button>
  )
}
