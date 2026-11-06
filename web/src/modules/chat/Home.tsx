// Chat tab home: the built-in assistant as a card with its latest chats, then the user's assistants.

import { useEffect, useRef, useState } from 'preact/hooks'
import { chatVersion, moduleSessions, toastError } from '../../lib/store'
import { navigate } from '../../lib/router'
import { Spark } from '../../components/crab'
import { Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../../components/ui'
import { IconChat, IconEdit, IconPlus, IconTrash } from '../../components/icons'
import { haptic, relTime } from '../../lib/util'
import { DEFAULT_ASSISTANT, chatApi, modelLabel, type Assistant, type ChatMeta, type ChatSession } from './api'
import { AssistantAvatar } from './chat/Chat'

const painted = () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 30))))
let cache: Assistant[] | null = null

/** Live state of an assistant's chats from the global feed. */
export function chatLive(assistantId: string) {
  let running = 0, unread = 0
  for (const s of Object.values(moduleSessions.value)) {
    if (s.module !== 'chat' || s.assistant_id !== assistantId) continue
    if (s.unread) unread++
    if (s.state === 'running') running++
  }
  return { running, unread }
}

/** Create a chat and open it on top of the assistant page, so Back lands on its list. */
export async function openNewChat(assistantId: string) {
  const s = await chatApi.createSession(assistantId)
  navigate({ name: 'assistant', assistantId }, { animate: false })
  await painted()
  navigate({ name: 'llm-chat', assistantId, sessionId: s.id })
}

export function ChatHome() {
  const { scrolled, onScroll, ref } = useScrolled()
  const [list, setList] = useState<Assistant[] | null>(cache)
  const [meta, setMeta] = useState<ChatMeta | null>(null)
  const stamp = Object.values(moduleSessions.value).filter((s) => s.module === 'chat')
    .map((s) => `${s.id}${s.title}${s.updated_at}${s.state}`).join()
  useEffect(() => {
    // Debounced: a streaming reply emits many feed events.
    const t = setTimeout(() => chatApi.assistants().then((a) => { cache = a; setList(a) }).catch(toastError), 300)
    return () => clearTimeout(t)
  }, [chatVersion.value, stamp])
  useEffect(() => { chatApi.meta().then(setMeta).catch(() => {}) }, [chatVersion.value])
  const noModels = meta && !meta.models.length

  return (
    <div class="page">
      <TopBar scrolled={scrolled}
        right={<div class="topbar-actions"><button class="icon-btn" aria-label="New assistant" onClick={() => navigate({ name: 'new-assistant' })}><IconPlus /></button></div>}>
        {scrolled && <span class="fade-in">Chat</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Chat</h1>
          <p class="subtitle rise" style={{ '--i': 1 }}>{noModels ? 'Add a model provider to start chatting.' : 'Talk to a model directly.'}</p>
          <DefaultCard meta={meta} />
          <div class="group-title">Assistants</div>
          {list === null ? (
            <div class="chat-card-list">{[0, 1].map((i) => <div key={i} class="skeleton" style={{ height: '128px', borderRadius: '20px' }} />)}</div>
          ) : list.length === 0 ? (
            <p class="fhint" style={{ margin: '6px 4px' }}>Assistants keep their own prompt, model and tools. Create one with the plus button.</p>
          ) : (
            <div class="chat-card-list">{list.map((a, i) => <AssistantCard key={a.id} a={a} index={i} meta={meta} />)}</div>
          )}
        </div>
      </div>
    </div>
  )
}

function DefaultCard({ meta }: { meta: ChatMeta | null }) {
  const [a, setA] = useState<Assistant | null>(null)
  const stamp = useStamp(DEFAULT_ASSISTANT)
  useEffect(() => {
    const t = setTimeout(() => chatApi.assistant(DEFAULT_ASSISTANT).then(setA).catch(() => {}), 300)
    return () => clearTimeout(t)
  }, [stamp, chatVersion.value])
  const shown = a || { id: DEFAULT_ASSISTANT, name: 'Temporary chat', avatar: 'crab:gray', order: 0, mcp: [] } as unknown as Assistant
  return (
    <section class="temp-section rise" style={{ '--i': 2, marginTop: 0, paddingBottom: 0 }}>
      <div class="group-title">Temporary</div>
      <ChatCard a={shown} meta={meta} loaded={!!a} subtitle="One-off chats with the defaults" />
    </section>
  )
}

/** Changes whenever a chat of this assistant changes in the global feed (title, time, state). */
function useStamp(assistantId: string) {
  return Object.values(moduleSessions.value).filter((s) => s.module === 'chat' && s.assistant_id === assistantId)
    .map((s) => `${s.id}${s.title}${s.updated_at}${s.state}`).join()
}

/** An assistant as a card: avatar and name, its latest chats, then All chats / New chat. */
function ChatCard({ a, meta, loaded, subtitle }: { a: Assistant; meta: ChatMeta | null; loaded: boolean; subtitle?: string }) {
  const live = chatLive(a.id)
  const [menuFor, setMenuFor] = useState<ChatSession | null>(null)
  const [removed, setRemoved] = useState<string[]>([])
  const [titles, setTitles] = useState<Record<string, string>>({})
  const creating = useRef(false)
  const recent = (a.recent || []).filter((s) => !removed.includes(s.id)).map((s) => titles[s.id] ? { ...s, title: titles[s.id] } : s)
  const rows = recent.slice(0, 5)
  const running = live.running || a.status?.running || 0
  const model = a.model || meta?.defaults.model || meta?.models[0]?.id || ''
  const newChat = async () => {
    if (creating.current) return
    creating.current = true
    haptic()
    try { await openNewChat(a.id) } catch (err) { toastError(err) } finally { creating.current = false }
  }
  const rename = async (s: ChatSession) => {
    setMenuFor(null)
    const t = (await promptDialog({ title: 'Rename conversation', value: s.title, confirm: 'Rename' }))?.trim()
    if (!t) return
    try { await chatApi.updateSession(s.id, { title: t }); setTitles((m) => ({ ...m, [s.id]: t })) } catch (e) { toastError(e) }
  }
  const remove = async (s: ChatSession) => {
    setMenuFor(null)
    if (!await confirmDialog({ title: 'Delete conversation?', body: s.title || 'New conversation', confirm: 'Delete', danger: true })) return
    try { await chatApi.deleteSession(s.id); setRemoved((r) => [...r, s.id]) } catch (e) { toastError(e) }
  }
  return (
    <div class="temp-card chat-card">
      <button class="temp-card-top press" onClick={() => navigate({ name: 'assistant', assistantId: a.id })}>
        <AssistantAvatar a={a} size={52} busy={running > 0} />
        <div class="agent-card-name">
          <div class="n">{a.name}{live.unread > 0 && <span class="unread-dot" aria-label="Unread" />}</div>
          <div class="p">{a.description || subtitle || modelLabel(model)}{model && (a.description || subtitle) ? ` · ${modelLabel(model)}` : ''}</div>
        </div>
        {running > 0 && <span class="chip pink"><Spark size={13} /> Replying</span>}
      </button>
      {rows.length > 0
        ? <div class="temp-card-list">{rows.map((s) => <SessionRow key={s.id} s={s} onMore={() => setMenuFor(s)} />)}</div>
        : loaded && <div class="chat-card-empty">No conversations yet.</div>}
      <div class="temp-card-actions">
        <button class="btn small" onClick={() => navigate({ name: 'assistant', assistantId: a.id })}>All chats</button>
        <button class="btn small primary" disabled={!meta?.models.length} onClick={newChat}><IconPlus width={16} height={16} /> New chat</button>
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

export function SessionRow({ s, onMore }: { s: ChatSession; onMore?: () => void }) {
  const l = moduleSessions.value[s.id]
  const state = l?.state || s.state, unread = l ? !!l.unread : s.unread
  const press = useRef<{ timer?: number; fired: boolean }>({ fired: false })
  const startPress = () => {
    if (!onMore) return
    press.current.fired = false
    press.current.timer = window.setTimeout(() => { press.current.fired = true; haptic(); onMore() }, 550)
  }
  const cancelPress = () => clearTimeout(press.current.timer)
  const click = () => {
    if (press.current.fired) { press.current.fired = false; return }
    navigate({ name: 'llm-chat', assistantId: s.assistant_id, sessionId: s.id })
  }
  return (
    <button class="row" onClick={click} onContextMenu={(e) => { if (!onMore) return; e.preventDefault(); onMore() }}
      onTouchStart={startPress} onTouchEnd={cancelPress} onTouchMove={cancelPress} onTouchCancel={cancelPress}>
      <span class="session-state">{state === 'running' ? <Spark size={16} /> : <IconChat width={16} height={16} style={{ color: 'var(--text-3)' }} />}</span>
      <span class="label">
        <span class={`session-title ${unread ? 'unread' : ''}`}>{l?.title || s.title || 'New conversation'}</span>
        <span class="hint">{l?.preview || s.preview || 'Empty'}</span>
      </span>
      <span class="session-meta">{unread && <span class="unread-dot" aria-label="Unread" />}{relTime(l?.updated_at || s.updated_at)}</span>
    </button>
  )
}

function AssistantCard({ a, index, meta }: { a: Assistant; index: number; meta: ChatMeta | null }) {
  return (
    <div class="rise" style={{ '--i': index + 3 }}>
      <ChatCard a={a} meta={meta} loaded />
    </div>
  )
}
