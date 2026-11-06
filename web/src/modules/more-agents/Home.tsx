// More Agents on the Agents tab (the "More" segment): cards for ACP and Codex agents, grouped.

import { useEffect, useRef, useState } from 'preact/hooks'
import { moreAgentsVersion, moduleSessions, toastError } from '../../lib/store'
import { navigate } from '../../lib/router'
import { Spark } from '../../components/crab'
import { IconChat, IconPlus, IconGlobe } from '../../components/icons'
import { haptic, relTime } from '../../lib/util'
import { moreAgentsApi, type MoreAgent } from './api'
import { MoreAgentAvatar } from './chat/Chat'

const painted = () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 30))))
let cache: MoreAgent[] | null = null
let groupCache: string[] = []

/** Live counts for one More agent from the global feed. */
export function moreAgentLive(agentId: string) {
  let running = 0, live = 0, pending = 0, unread = 0
  for (const s of Object.values(moduleSessions.value)) {
    if (s.module !== 'more_agents' || s.agent_id !== agentId) continue
    if (s.unread) unread++
    if (s.state === 'running' || s.state === 'interrupting') running++
    if (s.state !== 'offline') live++
    pending += s.pending || 0
  }
  return { running, live, pending, unread }
}

export function MoreAgents() {
  const [list, setList] = useState<MoreAgent[] | null>(cache)
  const [groups, setGroups] = useState<string[]>(groupCache)
  const [filter, setFilter] = useState<string | null>(null)
  useEffect(() => {
    moreAgentsApi.agents().then((a) => { cache = a; setList(a) }).catch(toastError)
    moreAgentsApi.groups().then((g) => { groupCache = g.groups; setGroups(g.groups) }).catch(() => {})
  }, [moreAgentsVersion.value])
  void moduleSessions.value

  if (list === null) return <div class="agent-grid">{[0, 1].map((i) => <div key={i} class="skeleton" style={{ height: '128px', borderRadius: '20px' }} />)}</div>
  if (!list.length) return (
    <div class="empty rise">
      <div class="empty-icon"><IconGlobe width={40} height={40} /></div>
      <h3 class="serif">No More Agents yet</h3>
      <p>Connect ACP endpoints or run Codex agents locally.</p>
      <button class="btn primary" style={{ marginTop: '10px' }} onClick={() => navigate({ name: 'new-more-agent' })}><IconPlus width={18} height={18} /> New agent</button>
    </div>
  )
  const ungrouped = list.filter((a) => !a.group || !groups.includes(a.group))
  const sections = filter === null
    ? (groups.length ? [...groups.map((g) => ({ title: g, items: list.filter((a) => a.group === g) })), { title: 'Ungrouped', items: ungrouped }].filter((x) => x.items.length) : [{ title: '', items: list }])
    : [{ title: '', items: filter === '' ? ungrouped : list.filter((a) => a.group === filter) }]
  return (
    <>
      <p class="subtitle rise" style={{ '--i': 1 }}>{list.length} agent{list.length > 1 ? 's' : ''}.</p>
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
          <div class="agent-grid">{sec.items.map((a, i) => <MoreAgentCard key={a.id} agent={a} index={i} />)}</div>
        </section>
      ))}
    </>
  )
}

function MoreAgentCard({ agent, index }: { agent: MoreAgent; index: number }) {
  const live = moreAgentLive(agent.id)
  const running = live.running || agent.status?.running || 0
  const pending = live.pending || agent.status?.pending || 0
  const last = agent.status?.last_session
  const creating = useRef(false)
  const newChat = async (e: Event) => {
    e.stopPropagation()
    if (creating.current) return
    creating.current = true
    try {
      const s = await moreAgentsApi.createSession(agent.id)
      navigate({ name: 'more-agent', agentId: agent.id }, { animate: false })
      await painted()
      navigate({ name: 'more-agent-chat', agentId: agent.id, sessionId: s.id })
    } catch (err) { toastError(err) } finally { creating.current = false }
  }

  const kindTag = agent.kind === 'acp' ? 'ACP' : 'Codex'
  const detailLine = agent.kind === 'acp' ? `${agent.host}:${agent.port}` : agent.model || 'default model'

  return (
    <div class="agent-card-wrap rise" style={{ '--i': index + 2 }}>
      <button class="agent-card press" onClick={() => navigate({ name: 'more-agent', agentId: agent.id })}>
        <div class="agent-card-top">
          <MoreAgentAvatar a={agent} size={52} busy={running > 0} />
          <div class="agent-card-name">
            <div class="n">{agent.name}{live.unread > 0 && <span class="unread-dot" />}</div>
            <div class="p">{detailLine}</div>
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
          <span class="mtag">{kindTag}</span>
          {agent.kind === 'acp' && agent.info?.name && <span class="mtag">{agent.info.name}</span>}
          {agent.kind === 'codex' && agent.mode && <span class="mtag">{agent.mode}</span>}
          <span class="when">{last ? relTime(last.updated_at) : ''}</span>
        </div>
      </button>
      <button class="agent-new press" aria-label={`New chat with ${agent.name}`} onClick={newChat}>
        <IconPlus width={16} height={16} /><IconChat width={17} height={17} />
      </button>
    </div>
  )
}
