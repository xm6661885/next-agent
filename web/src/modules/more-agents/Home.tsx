// More Agents on the Agents tab (the "More" segment): cards for ACP and Codex agents, grouped.

import { useEffect, useRef, useState } from 'preact/hooks'
import { moreAgentsVersion, moduleSessions, toastError } from '../../lib/store'
import { navigate } from '../../lib/router'
import { Spark } from '../../components/crab'
import { IconPlus, IconGlobe, IconFolder, IconEdit, IconMoon, IconTrash } from '../../components/icons'
import { haptic, shortPath } from '../../lib/util'
import { moreAgentsApi, type MoreAgent, type AgentKindInfo } from './api'
import { MoreAgentAvatar } from './chat/Chat'
import { Sheet, confirmDialog, promptDialog } from '../../components/ui'
import { DirPicker } from '../../components/DirPicker'

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
  const [addSheet, setAddSheet] = useState(false)
  const [kinds, setKinds] = useState<AgentKindInfo[]>([])
  useEffect(() => {
    moreAgentsApi.agents().then((a) => { cache = a; setList(a) }).catch(toastError)
    moreAgentsApi.groups().then((g) => { groupCache = g.groups; setGroups(g.groups) }).catch(() => {})
    moreAgentsApi.kinds().then(setKinds).catch(() => {})
  }, [moreAgentsVersion.value])
  void moduleSessions.value

  if (list === null) return <div class="agent-grid">{[0, 1].map((i) => <div key={i} class="skeleton" style={{ height: '128px', borderRadius: '20px' }} />)}</div>
  if (!list.length) return (
    <div class="empty rise">
      <div class="empty-icon"><IconGlobe width={40} height={40} /></div>
      <h3 class="serif">No More Agents yet</h3>
      <p>Connect ACP endpoints or run Codex agents locally.</p>
      <button class="btn primary" style={{ marginTop: '10px' }} onClick={() => setAddSheet(true)}><IconPlus width={18} height={18} /> New agent</button>
      <Sheet open={addSheet} onClose={() => setAddSheet(false)} title="New agent">
        <div class="agent-kind-grid">
          {kinds.map((k) => (
            <button key={k.kind} class="agent-kind-card press" onClick={() => { setAddSheet(false); navigate(`/more-agents/new?kind=${k.kind}`) }}>
              <div class="agent-kind-icon"><IconGlobe width={32} height={32} /></div>
              <div class="agent-kind-name">{k.name}</div>
              <div class="agent-kind-desc">{k.description}</div>
            </button>
          ))}
        </div>
      </Sheet>
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
      <Sheet open={addSheet} onClose={() => setAddSheet(false)} title="New agent">
        <div class="agent-kind-grid">
          {kinds.map((k) => (
            <button key={k.kind} class="agent-kind-card press" onClick={() => { setAddSheet(false); navigate(`/more-agents/new?kind=${k.kind}`) }}>
              <div class="agent-kind-icon"><IconGlobe width={32} height={32} /></div>
              <div class="agent-kind-name">{k.name}</div>
              <div class="agent-kind-desc">{k.description}</div>
            </button>
          ))}
        </div>
      </Sheet>
    </>
  )
}

function MoreAgentCard({ agent, index }: { agent: MoreAgent; index: number }) {
  const live = moreAgentLive(agent.id)
  const running = live.running || agent.status?.running || 0
  const creating = useRef(false)
  const [dirPicking, setDirPicking] = useState(false)
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const recent = agent.recent || []
  const press = useRef<{ timer?: number; fired: boolean }>({ fired: false })

  const newChat = async (e: Event, cwd?: string) => {
    e.stopPropagation()
    if (creating.current) return
    creating.current = true
    try {
      const s = await moreAgentsApi.createSession(agent.id, cwd)
      navigate({ name: 'more-agent', agentId: agent.id }, { animate: false })
      await painted()
      navigate({ name: 'more-agent-chat', agentId: agent.id, sessionId: s.id })
    } catch (err) { toastError(err) } finally { creating.current = false }
  }

  const openFolder = async (e: Event) => {
    e.stopPropagation()
    if (agent.kind === 'codex') {
      setDirPicking(true)
    } else {
      const cwd = await promptDialog({ title: 'Open folder', value: agent.cwd || '/', confirm: 'Start chat' })
      if (cwd?.trim()) newChat(e, cwd.trim())
    }
  }

  const renameSession = async (sid: string, title: string) => {
    const t = await promptDialog({ title: 'Rename conversation', value: title, confirm: 'Rename' })
    if (t === null || !t.trim()) return
    try {
      await moreAgentsApi.updateSession(sid, { title: t.trim() })
      moreAgentsVersion.value++
    } catch (e) { toastError(e) }
  }

  const sleepSession = async (sid: string) => {
    try {
      await moreAgentsApi.sleep(sid)
      moreAgentsVersion.value++
    } catch (e) { toastError(e) }
  }

  const deleteSession = async (sid: string, title: string) => {
    if (!await confirmDialog({ title: 'Delete conversation?', body: title || 'Untitled', confirm: 'Delete', danger: true })) return
    try {
      await moreAgentsApi.deleteSession(sid)
      moreAgentsVersion.value++
    } catch (e) { toastError(e) }
  }

  const startPress = (sid: string) => {
    press.current.fired = false
    press.current.timer = window.setTimeout(() => { press.current.fired = true; haptic(); setMenuFor(sid) }, 550)
  }
  const cancelPress = () => clearTimeout(press.current.timer)

  const kindTag = agent.kind === 'acp' ? 'ACP' : 'Codex'
  const detailLine = agent.kind === 'acp' ? agent.cwd : `${shortPath(agent.cwd)} · ${agent.model || 'default'}`

  return (
    <div class="agent-card-wrap rise" style={{ '--i': index + 2 }}>
      <button class="agent-card press" onClick={() => navigate({ name: 'more-agent', agentId: agent.id })}>
        <div class="agent-card-top">
          <MoreAgentAvatar a={agent} size={52} busy={running > 0} />
          <div class="agent-card-name">
            <div class="n">{agent.name}{live.unread > 0 && <span class="unread-dot" />}</div>
            <div class="p">{detailLine}</div>
          </div>
          <span class="mtag">{kindTag}</span>
        </div>

        {recent.length > 0 && (
          <div class="agent-card-recent" onClick={(e) => e.stopPropagation()}>
            {recent.slice(0, 5).map((s) => {
              const liveState = moduleSessions.value[s.id]
              const state = liveState?.state || s.state || 'offline'
              const unread = liveState?.unread ?? s.unread
              const sRunning = state === 'running' || state === 'interrupting'
              const sPending = liveState?.pending || 0
              const cwdDiff = s.cwd !== agent.cwd ? shortPath(s.cwd) : null
              return (
                <button key={s.id} class="recent-row press"
                  onClick={() => { if (press.current.fired) { press.current.fired = false; return } navigate({ name: 'more-agent-chat', agentId: agent.id, sessionId: s.id }) }}
                  onContextMenu={(e) => { e.preventDefault(); setMenuFor(s.id) }}
                  onTouchStart={() => startPress(s.id)} onTouchEnd={cancelPress} onTouchMove={cancelPress} onTouchCancel={cancelPress}>
                  <span class="recent-state">
                    {sPending > 0 ? <span class="dot waiting" /> : sRunning ? <Spark size={14} /> : <span class={`dot ${state !== 'offline' ? 'live' : ''}`} />}
                  </span>
                  <span class="recent-text">
                    <span class={`recent-title ${unread ? 'unread' : ''}`}>{s.title || 'Untitled'}</span>
                    {cwdDiff && <span class="hint mono-label">{cwdDiff}</span>}
                  </span>
                  {unread && <span class="unread-dot" aria-label="Unread" />}
                </button>
              )
            })}
          </div>
        )}

        <div class="agent-card-actions" onClick={(e) => e.stopPropagation()}>
          <button class="btn small" onClick={openFolder}><IconFolder width={16} height={16} /> Open folder</button>
          <button class="btn small primary" onClick={(e) => newChat(e)}><IconPlus width={16} height={16} /> New chat</button>
        </div>
      </button>

      <DirPicker open={dirPicking} onClose={() => setDirPicking(false)} onPick={(cwd) => { setDirPicking(false); newChat({ stopPropagation: () => {} } as Event, cwd) }} confirm="Start chat" />

      {recent.find((s) => s.id === menuFor) && (
        <Sheet open={!!menuFor} onClose={() => setMenuFor(null)} title={recent.find((s) => s.id === menuFor)?.title || 'Conversation'}>
          <div class="menu">
            <button onClick={() => { const s = recent.find((x) => x.id === menuFor)!; setMenuFor(null); renameSession(s.id, s.title) }}><IconEdit /> Rename</button>
            {moduleSessions.value[menuFor!]?.state !== 'offline' && (
              <button onClick={() => { const sid = menuFor!; setMenuFor(null); sleepSession(sid) }}><IconMoon /> Put to sleep</button>
            )}
            <button class="danger" onClick={() => { const s = recent.find((x) => x.id === menuFor)!; setMenuFor(null); deleteSession(s.id, s.title) }}><IconTrash /> Delete</button>
          </div>
        </Sheet>
      )}
    </div>
  )
}
