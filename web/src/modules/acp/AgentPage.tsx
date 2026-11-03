// ACP agent detail: header, new chat, searchable conversation list.

import { useEffect, useState } from 'preact/hooks'
import { acpVersion, moduleSessions, toast, toastError } from '../../lib/store'
import { back, navigate, wide } from '../../lib/router'
import { Spark } from '../../components/crab'
import { BackButton, Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../../components/ui'
import { IconChat, IconClose, IconEdit, IconMoon, IconMore, IconPlus, IconSearch, IconSettings, IconTrash } from '../../components/icons'
import { haptic, relTime } from '../../lib/util'
import { ORIGIN } from '../agents/AgentPage'
import { acpApi, type AcpAgent, type AcpSession } from './api'
import { AcpAvatar } from './chat/Chat'

export function AcpAgentPage({ agentId }: { agentId: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const [agent, setAgent] = useState<AcpAgent | null>(null)
  const [sessions, setSessions] = useState<AcpSession[] | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<{ session: AcpSession; snippet: string }[] | null>(null)
  const [menuFor, setMenuFor] = useState<AcpSession | null>(null)
  const [creating, setCreating] = useState(false)

  useEffect(() => { acpApi.agent(agentId).then(setAgent).catch((e) => { toastError(e); if (e.status === 404) back() }) }, [agentId, acpVersion.value])
  const load = () => acpApi.sessions(agentId).then(setSessions).catch(toastError)
  const live = moduleSessions.value
  // Refetch when a session of this agent changes title or time in the global feed.
  const stamp = Object.values(live).filter((s) => s.module === 'acp' && s.agent_id === agentId).map((s) => `${s.id}${s.title}${s.updated_at}`).join()
  useEffect(() => { load() }, [agentId, stamp])

  const q = query.trim()
  useEffect(() => {
    if (!q) { setHits(null); return }
    const t = setTimeout(() => acpApi.search(agentId, q).then(setHits).catch(toastError), 250)
    return () => clearTimeout(t)
  }, [q, agentId])

  const merged = (sessions || []).map((s) => { const l = live[s.id]; return l ? { ...s, state: l.state as AcpSession['state'], pending: l.pending, unread: !!l.unread } : s })
  const shown = q ? (hits || []).map((h) => merged.find((s) => s.id === h.session.id) || h.session) : merged
  const snippets = new Map((hits || []).map((h) => [h.session.id, h.snippet]))

  const newChat = async () => {
    if (creating) return
    setCreating(true)
    try { const s = await acpApi.createSession(agentId); navigate({ name: 'acp-chat', agentId, sessionId: s.id }) } catch (e) { toastError(e) } finally { setCreating(false) }
  }
  const rename = async (s: AcpSession) => {
    setMenuFor(null)
    const t = await promptDialog({ title: 'Rename conversation', value: s.title, confirm: 'Rename' })
    if (!t?.trim()) return
    try { await acpApi.updateSession(s.id, { title: t.trim() }); load() } catch (e) { toastError(e) }
  }
  const sleep = async (s: AcpSession) => {
    setMenuFor(null)
    try { await acpApi.sleep(s.id); toast('Disconnected'); load() } catch (e) { toastError(e) }
  }
  const remove = async (s: AcpSession) => {
    setMenuFor(null)
    if (!await confirmDialog({ title: 'Delete conversation?', body: 'Removed from this list with its uploads. The remote agent may keep its own copy.', confirm: 'Delete', danger: true })) return
    try { await acpApi.deleteSession(s.id); setSessions((l) => l && l.filter((x) => x.id !== s.id)) } catch (e) { toastError(e) }
  }
  const running = merged.some((s) => s.state === 'running')

  return (
    <div class="page">
      <TopBar scrolled={scrolled}
        left={<BackButton label="Agents" onClick={() => wide.value ? navigate({ name: 'home' }) : back({ name: 'home' })} />}
        right={<button class="icon-btn" aria-label="Agent settings" onClick={() => navigate({ name: 'acp-settings', agentId })}><IconSettings /></button>}>
        {scrolled && agent && <span class="topbar-center fade-in">{agent.name}</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          {agent ? (
            <div class="agent-hero rise">
              <AcpAvatar a={agent} size={84} busy={running} />
              <h1 class="serif">{agent.name}</h1>
              <div class="agent-hero-path">{agent.host}:{agent.port}</div>
              {agent.description && <p class="agent-hero-desc">{agent.description}</p>}
              <div class="agent-hero-tags">
                <span class="mtag">ACP</span>
                {agent.info?.name && <span class="mtag">{agent.info.title || agent.info.name}{agent.info.version ? ` ${agent.info.version}` : ''}</span>}
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
                    <button class="row" onClick={() => navigate({ name: 'acp-chat', agentId, sessionId: s.id })}
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
