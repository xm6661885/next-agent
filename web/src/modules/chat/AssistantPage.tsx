// Assistant detail: header, new chat, searchable conversation list.

import { useEffect, useState } from 'preact/hooks'
import { chatVersion, moduleSessions, toastError } from '../../lib/store'
import { back, navigate, wide } from '../../lib/router'
import { BackButton, Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../../components/ui'
import { IconBrain, IconChat, IconClose, IconEdit, IconFile, IconMore, IconPlus, IconSearch, IconSettings, IconTrash } from '../../components/icons'
import { haptic } from '../../lib/util'
import { chatApi, modelLabel, type Assistant, type ChatSession } from './api'
import { AssistantAvatar } from './chat/Chat'
import { SessionRow } from './Home'
import { useAssistantFlags } from './flags'

export function AssistantPage({ assistantId: agentId }: { assistantId: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const [agent, setAgent] = useState<Assistant | null>(null)
  const [sessions, setSessions] = useState<ChatSession[] | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<{ session: ChatSession; snippet: string }[] | null>(null)
  const [menuFor, setMenuFor] = useState<ChatSession | null>(null)
  const [creating, setCreating] = useState(false)
  const flags = useAssistantFlags(agentId)

  useEffect(() => { chatApi.assistant(agentId).then(setAgent).catch((e) => { toastError(e); if (e.status === 404) back() }) }, [agentId, chatVersion.value])
  const load = () => chatApi.sessions(agentId).then(setSessions).catch(toastError)
  const live = moduleSessions.value
  // Refetch when a session of this agent changes title or time in the global feed.
  const stamp = Object.values(live).filter((s) => s.module === 'chat' && s.assistant_id === agentId).map((s) => `${s.id}${s.title}${s.updated_at}`).join()
  useEffect(() => { load() }, [agentId, stamp])

  const q = query.trim()
  useEffect(() => {
    if (!q) { setHits(null); return }
    const t = setTimeout(() => chatApi.search(agentId, q).then(setHits).catch(toastError), 250)
    return () => clearTimeout(t)
  }, [q, agentId])

  const merged = (sessions || []).map((s) => { const l = live[s.id]; return l ? { ...s, state: l.state as ChatSession['state'], unread: !!l.unread } : s })
  const shown = q ? (hits || []).map((h) => merged.find((s) => s.id === h.session.id) || h.session) : merged
  const snippets = new Map((hits || []).map((h) => [h.session.id, h.snippet]))

  const newChat = async () => {
    if (creating) return
    setCreating(true)
    try { const s = await chatApi.createSession(agentId); navigate({ name: 'llm-chat', assistantId: agentId, sessionId: s.id }) } catch (e) { toastError(e) } finally { setCreating(false) }
  }
  const rename = async (s: ChatSession) => {
    setMenuFor(null)
    const t = await promptDialog({ title: 'Rename conversation', value: s.title, confirm: 'Rename' })
    if (!t?.trim()) return
    try { await chatApi.updateSession(s.id, { title: t.trim() }); load() } catch (e) { toastError(e) }
  }
  const remove = async (s: ChatSession) => {
    setMenuFor(null)
    if (!await confirmDialog({ title: 'Delete conversation?', body: s.title || 'New conversation', confirm: 'Delete', danger: true })) return
    try { await chatApi.deleteSession(s.id); setSessions((l) => l && l.filter((x) => x.id !== s.id)) } catch (e) { toastError(e) }
  }
  const running = merged.some((s) => s.state === 'running')

  return (
    <div class="page">
      <TopBar scrolled={scrolled}
        left={<BackButton label="Chat" onClick={() => wide.value ? navigate({ name: 'chats' }) : back({ name: 'chats' })} />}
        right={<div class="topbar-actions">
          {flags.files && <button class="icon-btn" aria-label="Files" onClick={() => navigate({ name: 'assistant-files', assistantId: agentId })}><IconFile /></button>}
          {flags.memory && <button class="icon-btn" aria-label="Memory" onClick={() => navigate({ name: 'assistant-memory', assistantId: agentId })}><IconBrain /></button>}
          <button class="icon-btn" aria-label="Assistant settings" onClick={() => navigate({ name: 'assistant-settings', assistantId: agentId })}><IconSettings /></button>
        </div>}>
        {scrolled && agent && <span class="topbar-center fade-in">{agent.name}</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          {agent ? (
            <div class="agent-hero rise">
              <AssistantAvatar a={agent} size={84} busy={running} />
              <h1 class="serif">{agent.name}</h1>
              <div class="agent-hero-path">{modelLabel(agent.model) || 'Default model'}</div>
              {agent.description && <p class="agent-hero-desc">{agent.description}</p>}
              <div class="agent-hero-tags">
                {agent.effort && <span class="mtag">{agent.effort}</span>}
                {agent.mcp.length > 0 && <span class="mtag">{agent.mcp.length} MCP</span>}
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
              {shown.map((s, i) => (
                <div key={s.id} class="session-row rise" style={{ '--i': Math.min(i, 12) }}>
                  <SessionRow s={snippets.get(s.id) ? { ...s, preview: snippets.get(s.id)! } : s} onMore={() => { haptic(); setMenuFor(s) }} />
                  <button class="icon-btn session-more" aria-label="More" onClick={() => setMenuFor(s)}><IconMore /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <Sheet open={!!menuFor} onClose={() => setMenuFor(null)} title={menuFor?.title || 'Conversation'}>
        {menuFor && (
          <div class="menu">
            <button onClick={() => rename(menuFor)}><IconEdit /> Rename</button>
            <button class="danger" onClick={() => remove(menuFor)}><IconTrash /> Delete</button>
          </div>
        )}
      </Sheet>
    </div>
  )
}
