// Chat tab home: the built-in assistant as a card with its latest chats, then the user's assistants.

import { useEffect, useRef, useState } from 'preact/hooks'
import { chatVersion, moduleSessions, toastError } from '../../lib/store'
import { navigate } from '../../lib/router'
import { Spark } from '../../components/crab'
import { TopBar, useScrolled } from '../../components/ui'
import { IconChat, IconPlus, IconSettings } from '../../components/icons'
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
  useEffect(() => {
    chatApi.assistants().then((a) => { cache = a; setList(a) }).catch(toastError)
    chatApi.meta().then(setMeta).catch(() => {})
  }, [chatVersion.value])
  void moduleSessions.value
  const noModels = meta && !meta.models.length

  return (
    <div class="page with-tabbar">
      <TopBar scrolled={scrolled}
        right={<div class="topbar-actions"><button class="icon-btn" aria-label="Chat settings" onClick={() => navigate({ name: 'settings-section', section: 'chat-providers' })}><IconSettings /></button></div>}>
        {scrolled && <span class="fade-in">Chat</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Chat</h1>
          <p class="subtitle rise" style={{ '--i': 1 }}>{noModels ? 'Add a model provider to start chatting.' : 'Talk to a model directly.'}</p>
          {noModels && (
            <button class="btn primary rise" style={{ '--i': 1, marginBottom: '14px' }} onClick={() => navigate({ name: 'settings-section', section: 'chat-providers' })}>
              <IconPlus width={18} height={18} /> Add a provider
            </button>
          )}
          <DefaultCard meta={meta} />
          <div class="group-title">Assistants</div>
          {list === null ? (
            <div class="agent-grid">{[0, 1].map((i) => <div key={i} class="skeleton" style={{ height: '128px', borderRadius: '20px' }} />)}</div>
          ) : list.length === 0 ? (
            <p class="fhint" style={{ margin: '6px 4px' }}>Assistants keep their own prompt, model and tools. Create one with the button below.</p>
          ) : (
            <div class="agent-grid">{list.map((a, i) => <AssistantCard key={a.id} a={a} index={i} meta={meta} />)}</div>
          )}
        </div>
      </div>
      <button class="fab" onClick={() => navigate({ name: 'new-assistant' })}><IconPlus /> New assistant</button>
    </div>
  )
}

function DefaultCard({ meta }: { meta: ChatMeta | null }) {
  const [a, setA] = useState<Assistant | null>(null)
  const [list, setList] = useState<ChatSession[] | null>(null)
  const live = chatLive(DEFAULT_ASSISTANT)
  const stamp = Object.values(moduleSessions.value).filter((s) => s.module === 'chat' && s.assistant_id === DEFAULT_ASSISTANT).map((s) => `${s.id}${s.title}${s.updated_at}${s.state}`).join()
  useEffect(() => { chatApi.assistant(DEFAULT_ASSISTANT).then(setA).catch(() => {}) }, [chatVersion.value])
  useEffect(() => { chatApi.sessions(DEFAULT_ASSISTANT).then(setList).catch(() => {}) }, [stamp, chatVersion.value])
  const shown = a || { id: DEFAULT_ASSISTANT, name: 'Chat', avatar: 'crab:gray', order: 0 } as Assistant
  const model = a?.model || meta?.defaults.model || meta?.models[0]?.id || ''
  const rows = (list || []).slice(0, 5)
  const start = async () => { haptic(); try { await openNewChat(DEFAULT_ASSISTANT) } catch (e) { toastError(e) } }
  return (
    <section class="temp-section rise" style={{ '--i': 2, marginTop: 0 }}>
      <div class="temp-card">
        <button class="temp-card-top press" onClick={() => navigate({ name: 'assistant', assistantId: DEFAULT_ASSISTANT })}>
          <AssistantAvatar a={shown} size={52} busy={live.running > 0} />
          <div class="agent-card-name">
            <div class="n">{shown.name}{live.unread > 0 && <span class="unread-dot" aria-label="Unread" />}</div>
            <div class="p">{list?.length ? `${list.length} chat${list.length > 1 ? 's' : ''}` : 'Quick chats'}{model ? ` · ${modelLabel(model)}` : ''}</div>
          </div>
        </button>
        {rows.length > 0 && <div class="temp-card-list">{rows.map((s) => <SessionRow key={s.id} s={s} />)}</div>}
        <div class="temp-card-actions">
          <button class="btn small primary" disabled={!meta?.models.length} onClick={start}><IconPlus width={16} height={16} /> New chat</button>
        </div>
      </div>
    </section>
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
  const live = chatLive(a.id)
  const running = live.running || a.status?.running || 0
  const last = a.status?.last_session
  const model = a.model || meta?.defaults.model || meta?.models[0]?.id || ''
  const creating = useRef(false)
  const newChat = async (e: Event) => {
    e.stopPropagation()
    if (creating.current) return
    creating.current = true
    try { await openNewChat(a.id) } catch (err) { toastError(err) } finally { creating.current = false }
  }
  return (
    <div class="agent-card-wrap rise" style={{ '--i': index + 3 }}>
      <button class="agent-card press" onClick={() => navigate({ name: 'assistant', assistantId: a.id })}>
        <div class="agent-card-top">
          <AssistantAvatar a={a} size={52} busy={running > 0} />
          <div class="agent-card-name">
            <div class="n">{a.name}{live.unread > 0 && <span class="unread-dot" />}</div>
            <div class="p">{a.description || modelLabel(model)}</div>
          </div>
          {running > 0 && <span class="chip pink"><Spark size={13} /> Replying</span>}
        </div>
        <div class="agent-card-last">
          {last ? <><span class="lt">{last.title || 'Untitled'}</span><span class="lp">{last.preview || ' '}</span></>
            : <span class="lp">No conversations yet.</span>}
        </div>
        <div class="agent-card-foot">
          {model && <span class="mtag">{modelLabel(model)}</span>}
          {a.effort && <span class="mtag">{a.effort}</span>}
          {a.mcp.length > 0 && <span class="mtag">{a.mcp.length} MCP</span>}
          <span class="when">{last ? relTime(last.updated_at) : ''}</span>
        </div>
      </button>
      <button class="agent-new press" aria-label={`New chat with ${a.name}`} onClick={newChat}>
        <IconPlus width={16} height={16} /><IconChat width={17} height={17} />
      </button>
    </div>
  )
}
