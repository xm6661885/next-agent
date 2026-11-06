// More Agents agent detail: header, new chat, searchable conversation list.

import { useEffect, useState } from 'preact/hooks'
import { moreAgentsVersion, moduleSessions, toast, toastError } from '../../lib/store'
import { back, navigate, wide } from '../../lib/router'
import { Spark } from '../../components/crab'
import { BackButton, Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../../components/ui'
import { IconChat, IconClose, IconEdit, IconMoon, IconMore, IconPlus, IconSearch, IconSettings, IconTrash } from '../../components/icons'
import { haptic, relTime } from '../../lib/util'
import { ORIGIN } from '../agents/AgentPage'
import { moreAgentsApi, type MoreAgent, type MoreSession } from './api'
import { MoreAgentAvatar } from './chat/Chat'

export function MoreAgentPage({ agentId }: { agentId: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const [agent, setAgent] = useState<MoreAgent | null>(null)
  const [sessions, setSessions] = useState<MoreSession[] | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<{ session: MoreSession; snippet: string }[] | null>(null)
  const [menuFor, setMenuFor] = useState<MoreSession | null>(null)
  const [creating, setCreating] = useState(false)

  useEffect(() => { moreAgentsApi.agent(agentId).then(setAgent).catch((e) => { toastError(e); if (e.status === 404) back() }) }, [agentId, moreAgentsVersion.value])
  const load = () => moreAgentsApi.sessions(agentId).then(setSessions).catch(toastError)
  const live = moduleSessions.value
  // Refetch when a session of this agent changes title or time in the global feed.
  const stamp = Object.values(live).filter((s) => s.module === 'more_agents' && s.agent_id === agentId).map((s) => `${s.id}${s.title}${s.updated_at}`).join()
  useEffect(() => { load() }, [agentId, stamp])

  const q = query.trim()
  useEffect(() => {
    if (!q) { setHits(null); return }
    const t = setTimeout(() => moreAgentsApi.search(agentId, q).then(setHits).catch(toastError), 250)
    return () => clearTimeout(t)
  }, [q, agentId])

  const merged = (sessions || []).map((s) => { const l = live[s.id]; return l ? { ...s, state: l.state as MoreSession['state'], pending: l.pending, unread: !!l.unread } : s })
  const shown = q ? (hits || []).map((h) => merged.find((s) => s.id === h.session.id) || h.session) : merged
  const snippets = new Map((hits || []).map((h) => [h.session.id, h.snippet]))

  const newChat = async () => {
    if (creating) return
    setCreating(true)
    try { const s = await moreAgentsApi.createSession(agentId); navigate({ name: 'more-agent-chat', agentId, sessionId: s.id }) } catch (e) { toastError(e) } finally { setCreating(false) }
  }
  const rename = async (s: MoreSession) => {
    setMenuFor(null)
    const t = await promptDialog({ title: 'Rename conversation', value: s.title, confirm: 'Rename' })
    if (!t?.trim()) return
    try { await moreAgentsApi.updateSession(s.id, { title: t.trim() }); load() } catch (e) { toastError(e) }
  }
  const sleep = async (s: MoreSession) => {
    setMenuFor(null)
    try { await moreAgentsApi.sleep(s.id); toast('Disconnected'); load() } catch (e) { toastError(e) }
  }
  const remove = async (s: MoreSession) => {
    setMenuFor(null)
    if (!await confirmDialog({ title: 'Delete conversation?', body: 'Removed from this list with its uploads. The remote agent may keep its own copy.', confirm: 'Delete', danger: true })) return
    try { await moreAgentsApi.deleteSession(s.id); setSessions((l) => l && l.filter((x) => x.id !== s.id)) } catch (e) { toastError(e) }
  }
  const running = merged.some((s) => s.state === 'running')

  const kindTag = agent?.kind === 'acp' ? 'ACP' : agent?.kind === 'codex' ? 'Codex' : ''
  const detailLine = agent?.kind === 'acp' ? `${agent.host}:${agent.port}` : agent?.kind === 'codex' ? (agent.model || 'default model') : ''

  return (
    <div class="page">
      <TopBar scrolled={scrolled}
        left={<BackButton label="Agents" onClick={() => wide.value ? navigate({ name: 'home' }) : back({ name: 'home' })} />}
        right={<button class="icon-btn" aria-label="Agent settings" onClick={() => navigate({ name: 'more-agent-settings', agentId })}><IconSettings /></button>}>
        {scrolled && agent && <span class="topbar-center fade-in">{agent.name}</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          {agent ? (
            <div class="agent-hero rise">
              <MoreAgentAvatar a={agent} size={84} busy={running} />
              <h1 class="serif">{agent.name}</h1>
              <div class="agent-hero-path">{detailLine}</div>
              {agent.description && <p class="agent-hero-desc">{agent.description}</p>}
              <div class="agent-hero-tags">
                <span class="mtag">{kindTag}</span>
                {agent.kind === 'acp' && agent.info?.name && <span class="mtag">{agent.info.title || agent.info.name}{agent.info.version ? ` ${agent.info.version}` : ''}</span>}
                {agent.kind === 'codex' && agent.mode && <span class="mtag">{agent.mode}</span>}
                <span class="mtag">{merged.length} chats</span>
              </div>
              <div class="agent-hero-actions">
                <button class="btn primary" onClick={newChat} disabled={creating}>{creating ? <span class="spinner" /> : <IconPlus width={18} height={18} />} New chat</button>
              </div>
            </div>
          ) : <div class="agent-hero"><div class="skeleton" style={{ width: '84px', height: '84px', borderRadius: '26px' }} /></div>}

          {merged.length > 0 && (
            <div class="search-box rise" style={{ '--i': 2 }}>
              <IconSearch />
              <input type="search" placeholder="Search conversations" value={query} onInput={(e) => setQuery((e.target as HTMLInputElement).value)} />
              {query && <button class="search-clear" aria-label="Clear search" onClick={() => setQuery('')}><IconClose /></button>}
            </div>
          )}
          <div class="group-title">{q ? `${shown.length} result${shown.length === 1 ? '' : 's'}` : 'Conversations'}</div>
          {sessions === null ? (
            <div class="group">{[0, 1, 2].map((i) => <div key={i} class="row"><div class="skeleton" style={{ height: '36px', flex: 1 }} /></div>)}</div>
          ) : shown.length === 0 ? (
            <div class="empty rise" style={{ padding: '28px 20px' }}>
              <IconChat width={30} height={30} style={{ color: 'var(--text-3)' }} />
              <p style={{ margin: '8px 0 0' }}>{q ? 'Nothing matches.' : 'No conversations yet. Start one above.'}</p>
            </div>
          ) : (
            <div class="group">
              {shown.map((s, i) => {
                const busy = s.state === 'running' || s.state === 'interrupting'
                const hint = s.pending > 0 ? 'Waiting for your answer' : snippets.get(s.id) || s.preview || 'Empty'
                return (
                  <div key={s.id} class="session-row rise" style={{ '--i': Math.min(i, 12) }}>
                    <button class="row" onClick={() => navigate({ name: 'more-agent-chat', agentId, sessionId: s.id })}
                      onContextMenu={(e) => { e.preventDefault(); haptic(); setMenuFor(s) }}>
                      <span class="session-state">{s.pending > 0 ? <span class="dot waiting" /> : busy ? <Spark size={16} /> : <span class={`dot ${s.state !== 'offline' ? 'live' : ''}`} />}</span>
                      <span class="label">
                        <span class={`session-title ${s.unread ? 'unread' : ''}`}>{s.origin && s.origin !== 'ui' && <span class="origin-tag">{ORIGIN[s.origin]}</span>}{s.title || 'New conversation'}</span>
                        <span class="hint">{hint}</span>
                      </span>
                      <span class="session-meta">{s.unread && <span class="unread-dot" />}<span>{relTime(s.updated_at)}</span></span>
                    </button>
                    <button class="icon-btn session-more" aria-label="More" onClick={() => setMenuFor(s)}><IconMore /></button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
      <Sheet open={!!menuFor} onClose={() => setMenuFor(null)} title={menuFor?.title || 'Conversation'}>
        {menuFor && (
          <div class="menu">
            <button onClick={() => rename(menuFor)}><IconEdit /> Rename</button>
            {menuFor.state !== 'offline' && <button onClick={() => sleep(menuFor)}><IconMoon /> Disconnect</button>}
            <button class="danger" onClick={() => remove(menuFor)}><IconTrash /> Delete</button>
          </div>
        )}
      </Sheet>
    </div>
  )
}
