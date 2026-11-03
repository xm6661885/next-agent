// ACP agents on the Agents tab (the "ACP" segment): cards grouped by ACP groups, like the Claude agent cards.

import { useEffect, useRef, useState } from 'preact/hooks'
import { acpVersion, moduleSessions, toastError } from '../../lib/store'
import { navigate } from '../../lib/router'
import { Spark } from '../../components/crab'
import { IconChat, IconPlus, IconGlobe } from '../../components/icons'
import { haptic, relTime } from '../../lib/util'
import { acpApi, type AcpAgent } from './api'
import { AcpAvatar } from './chat/Chat'

const painted = () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 30))))
let cache: AcpAgent[] | null = null
let groupCache: string[] = []

/** Live counts for one ACP agent from the global feed. */
export function acpLive(agentId: string) {
  let running = 0, live = 0, pending = 0, unread = 0
  for (const s of Object.values(moduleSessions.value)) {
    if (s.module !== 'acp' || s.agent_id !== agentId) continue
    if (s.unread) unread++
    if (s.state === 'running' || s.state === 'interrupting') running++
    if (s.state !== 'offline') live++
    pending += s.pending || 0
  }
  return { running, live, pending, unread }
}

export function AcpAgents() {
  const [list, setList] = useState<AcpAgent[] | null>(cache)
  const [groups, setGroups] = useState<string[]>(groupCache)
  const [filter, setFilter] = useState<string | null>(null)
  useEffect(() => {
    acpApi.agents().then((a) => { cache = a; setList(a) }).catch(toastError)
    acpApi.groups().then((g) => { groupCache = g.groups; setGroups(g.groups) }).catch(() => {})
  }, [acpVersion.value])
  void moduleSessions.value

  if (list === null) return <div class="agent-grid">{[0, 1].map((i) => <div key={i} class="skeleton" style={{ height: '128px', borderRadius: '20px' }} />)}</div>
  if (!list.length) return (
    <div class="empty rise">
      <div class="empty-icon"><IconGlobe width={40} height={40} /></div>
      <h3 class="serif">No ACP agents yet</h3>
      <p>Connect an external agent that speaks the Agent Client Protocol over TCP.</p>
      <button class="btn primary" style={{ marginTop: '10px' }} onClick={() => navigate({ name: 'new-acp' })}><IconPlus width={18} height={18} /> New ACP agent</button>
    </div>
  )
  const ungrouped = list.filter((a) => !a.group || !groups.includes(a.group))
  const sections = filter === null
    ? (groups.length ? [...groups.map((g) => ({ title: g, items: list.filter((a) => a.group === g) })), { title: 'Ungrouped', items: ungrouped }].filter((x) => x.items.length) : [{ title: '', items: list }])
    : [{ title: '', items: filter === '' ? ungrouped : list.filter((a) => a.group === filter) }]
  return (
    <>
      <p class="subtitle rise" style={{ '--i': 1 }}>{list.length} external agent{list.length > 1 ? 's' : ''}.</p>
      {groups.length > 0 && (
        <div class="group-filter rise" role="tablist" style={{ '--i': 1 }}>
          {[[null, 'All', list.length] as const, ...groups.map((g) => [g, g, list.filter((a) => a.group === g).length] as const),
            ...(ungrouped.length ? [['', 'Ungrouped', ungrouped.length] as const] : [])].map(([key, label, n]) => (
            <button key={label} role="tab" aria-selected={filter === key} class={`chip ${filter === key ? 'pink' : ''}`} onClick={() => { haptic(); setFilter(key) }}>
              {label}<span class="chip-count">{n}</span>
            </button>
          ))}
        </div>
      )}
      {sections.map((sec, si) => (
        <section key={sec.title || si} class="agent-section">
          {sec.title && <div class="group-title">{sec.title}</div>}
          <div class="agent-grid">{sec.items.map((a, i) => <AcpCard key={a.id} agent={a} index={i} />)}</div>
        </section>
      ))}
    </>
  )
}

function AcpCard({ agent, index }: { agent: AcpAgent; index: number }) {
  const live = acpLive(agent.id)
  const running = live.running || agent.status?.running || 0
  const pending = live.pending || agent.status?.pending || 0
  const last = agent.status?.last_session
  const creating = useRef(false)
  const newChat = async (e: Event) => {
    e.stopPropagation()
    if (creating.current) return
    creating.current = true
    try {
      const s = await acpApi.createSession(agent.id)
      navigate({ name: 'acp', agentId: agent.id }, { animate: false })
      await painted()
      navigate({ name: 'acp-chat', agentId: agent.id, sessionId: s.id })
    } catch (err) { toastError(err) } finally { creating.current = false }
  }
  return (
    <div class="agent-card-wrap rise" style={{ '--i': index + 2 }}>
      <button class="agent-card press" onClick={() => navigate({ name: 'acp', agentId: agent.id })}>
        <div class="agent-card-top">
          <AcpAvatar a={agent} size={52} busy={running > 0} />
          <div class="agent-card-name">
            <div class="n">{agent.name}{live.unread > 0 && <span class="unread-dot" />}</div>
            <div class="p">{agent.host}:{agent.port}</div>
          </div>
          {pending > 0 ? <span class="chip warn pending-chip">Needs you</span>
            : running > 0 ? <span class="chip pink"><Spark size={13} /> Working</span>
              : <span class={`dot ${live.live ? 'live' : ''}`} title={live.live ? 'Connected' : 'Disconnected'} />}
        </div>
        <div class="agent-card-last">
          {last ? <><span class="lt">{last.title || 'Untitled'}</span><span class="lp">{last.preview || ' '}</span></>
            : <span class="lp">{agent.description || 'No conversations yet.'}</span>}
        </div>
        <div class="agent-card-foot">
          <span class="mtag">ACP</span>
          {agent.info?.name && <span class="mtag">{agent.info.name}</span>}
          <span class="when">{last ? relTime(last.updated_at) : ''}</span>
        </div>
      </button>
      <button class="agent-new press" aria-label={`New chat with ${agent.name}`} onClick={newChat}>
        <IconPlus width={16} height={16} /><IconChat width={17} height={17} />
      </button>
    </div>
  )
}
