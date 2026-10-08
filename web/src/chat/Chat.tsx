// Chat page: transcript, live streaming, pending request cards, controls sheet, composer.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks'
import { memo } from 'preact/compat'
import { api } from '../lib/api'
import { agents, meta, toast, toastError } from '../lib/store'
import { back, navigate } from '../lib/router'
import { Avatar, Spark } from '../components/crab'
import { BackButton, Segmented, Sheet, Switch, TopBar, confirmDialog, promptDialog } from '../components/ui'
import { IconBrain, IconCheck, IconChevronDown, IconCopy, IconFork, IconMore, IconRewind, IconEdit, IconNewChat, IconTerminal } from '../components/icons'
import { ChatConn } from './conn'
import { Composer } from './Composer'
import { TaskTray } from './Tasks'
import { PermissionCard } from './cards'
import { ToolCard } from './tools'
import { mathVersion, renderMarkdown, renderStreaming } from './markdown'
import { ModelPicker } from '../components/ModelPicker'
import { openViewer } from '../components/ImageViewer'
import { MODE_LABELS, copyText, fmtBytes, fmtCost, fmtDuration, fmtTokens, haptic, uid } from '../lib/util'
import type { Activity, Agent, Attachment, Item, TextItem, ThinkingItem, ToolItem, UserItem } from '../lib/types'

const VERBS = ['Pondering', 'Brewing', 'Cogitating', 'Percolating', 'Mulling', 'Noodling', 'Simmering', 'Scuttling', 'Tinkering',
  'Puzzling', 'Musing', 'Ruminating', 'Conjuring', 'Crafting', 'Forging', 'Marinating', 'Whirring', 'Churning', 'Deliberating', 'Working']

function fmtUsage(u?: Record<string, any>) {
  if (!u) return ''
  const input = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0)
  const output = u.output_tokens || 0
  if (!input && !output) return ''
  const k = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`
  return ` · ${k(input)} in / ${k(output)} out tokens`
}

export function Chat({ agentId, sessionId }: { agentId: string; sessionId: string }) {
  const conn = useMemo(() => new ChatConn(sessionId), [sessionId])
  const [agent, setAgent] = useState<Agent | null>(agents.value?.find((a) => a.id === agentId) || null)
  const [controls, setControls] = useState(false)
  const [msgMenu, setMsgMenu] = useState<UserItem | null>(null)
  const [editing, setEditing] = useState<UserItem | null>(null)
  const [modelOpen, setModelOpen] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const userScroll = useRef(0)
  const markUser = () => { userScroll.current = Date.now() }
  const [showJump, setShowJump] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)

  useEffect(() => {
    conn.onError = (m) => toast(m, 'error', 4000)
    return () => {
      // A new chat that was left without sending anything is discarded.
      const s = conn.session.value
      const empty = s && !s.sdk_session_id && !s.imported && !s.fork_of && s.turns === 0 && conn.items.value.length === 0
      conn.dispose()
      if (empty) api.deleteSession(s.id).catch(() => {})
    }
  }, [conn])
  useEffect(() => {
    api.agent(agentId).then(setAgent).catch(() => {})
    if (!meta.value) api.meta().then((m) => { meta.value = m }).catch(() => {})
  }, [agentId])

  const items = conn.items.value
  const state = conn.state.value
  const session = conn.session.value
  const perms = conn.perms.value
  const init = conn.init.value
  const busy = state === 'running' || state === 'interrupting'
  const mode = session?.overrides?.permission_mode || init?.permission_mode || agent?.permission_mode || 'default'
  const model = session?.overrides?.model || init?.model || agent?.model || meta.value?.defaults.model || ''
  const effort = session?.overrides?.effort || agent?.effort || meta.value?.defaults.effort || ''

  // Keep pinned to the bottom while new content streams, unless the user scrolled up.
  const onScroll = () => {
    const el = scroller.current
    if (!el) return
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight
    // Only the user's own scrolling unpins. Scroll events also fire when images or math load and
    // the browser clamps or shifts the position; those must not leave the chat stuck mid-way.
    if (dist < 80) stick.current = true
    else if (Date.now() - userScroll.current < 2500) stick.current = false
    setShowJump(dist > 400)
    if (el.scrollTop < 200 && conn.hasMore.value && !loadingOlder) loadOlder()
  }
  useLayoutEffect(() => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [items, perms, state])
  useEffect(() => {
    // Images, file previews and math finish loading after the first paint and grow the content;
    // follow them down while pinned to the bottom.
    const el = scroller.current, inner = el?.firstElementChild
    if (!el || !inner || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => { if (stick.current) el.scrollTop = el.scrollHeight })
    ro.observe(inner)
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    // Keyboard open/close on iOS changes the viewport; stay at the bottom.
    const vv = window.visualViewport
    if (!vv) return
    const h = () => { const el = scroller.current; if (el && stick.current) el.scrollTop = el.scrollHeight }
    vv.addEventListener('resize', h)
    return () => vv.removeEventListener('resize', h)
  }, [])

  const loadOlder = async () => {
    const first = conn.items.value[0]
    if (!first) return
    setLoadingOlder(true)
    const el = scroller.current
    const prevH = el?.scrollHeight || 0
    try {
      const r = await api.items(sessionId, first.id)
      conn.prependHistory(r.items, r.has_more)
      requestAnimationFrame(() => { if (el) el.scrollTop += el.scrollHeight - prevH })
    } catch (e) { toastError(e) } finally { setLoadingOlder(false) }
  }

  const jump = () => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    stick.current = true
  }

  const send = async (text: string, atts: Attachment[], steerNow: boolean) => {
    const client_id = uid()
    stick.current = true
    conn.addLocalUser(client_id, text, atts)
    if (steerNow && busy) await conn.send({ type: 'interrupt' })
    const err = await conn.send({ type: 'send', client_id, text, attachments: atts.map((a) => a.id) })
    if (err) {
      conn.removeLocal(client_id)
      toast(err, 'error')
      return false
    }
    return true
  }

  const setMode = async (m: string) => {
    haptic()
    const err = await conn.send({ type: 'set_mode', mode: m })
    if (err) toast(err, 'error')
    else toast(MODE_LABELS[m] || m)
  }

  const rename = async () => {
    const t = await promptDialog({ title: 'Rename conversation', value: session?.title || '', confirm: 'Rename' })
    if (!t?.trim()) return
    try { conn.session.value = await api.updateSession(sessionId, { title: t.trim() }) } catch (e) { toastError(e) }
  }

  const forkAt = async (it: UserItem | null) => {
    setMsgMenu(null)
    try {
      const s = await api.forkSession(sessionId, it?.uuid || null)
      toast('Forked into a new chat')
      navigate({ name: 'chat', agentId, sessionId: s.id })
    } catch (e) { toastError(e) }
  }

  const rewind = async (it: UserItem) => {
    setMsgMenu(null)
    const ok = await confirmDialog({
      title: 'Rewind files?',
      body: 'Files Claude changed after this message go back to how they were. The conversation itself is not changed.',
      confirm: 'Rewind', danger: true,
    })
    if (!ok || !it.uuid) return
    const err = await conn.send({ type: 'rewind', uuid: it.uuid })
    if (err) toast(err, 'error')
  }

  const applyModel = async (m: string) => {
    const err = await conn.send({ type: 'set_model', model: m })
    if (err) toast(err, 'error'); else toast(m ? `Model: ${m}` : 'Model reset to agent default')
  }

  const startEdit = (it: UserItem) => {
    setMsgMenu(null)
    if (busy) return toast('Wait for Claude to finish, or stop it first', 'error')
    setEditing(it)
  }

  const resend = async (it: UserItem, text: string, atts: Attachment[], rewindFiles: boolean) => {
    const client_id = uid()
    stick.current = true
    const err = await conn.send({ type: 'edit', uuid: it.uuid, client_id, text, attachments: atts.map((a) => a.id), rewind_files: rewindFiles })
    if (err) { toast(err, 'error'); return false }
    return true
  }

  // Like /clear in Claude Code: a fresh conversation with the same agent. It replaces this chat in
  // history so Back still lands on the agent's conversation list.
  const [creating, setCreating] = useState(false)
  const newChat = async () => {
    if (creating) return
    setCreating(true)
    try {
      const s = await api.createSession(agentId)
      haptic()
      navigate({ name: 'chat', agentId, sessionId: s.id }, { replace: true })
    } catch (e) { toastError(e) } finally { setCreating(false) }
  }

  // Images from Claude's replies, in transcript order, so the viewer can swipe between them.
  const openChatImage = (el: HTMLImageElement) => {
    const all = Array.from(scroller.current?.querySelectorAll<HTMLImageElement>('.msg-assistant img[data-view]') || [])
    const list = all.map((x) => {
      const path = x.dataset.file
      return { src: x.src, name: x.alt || path?.split('/').pop() || '', download: path ? api.fileUrl(sessionId, path, true) : x.src }
    })
    openViewer(list, Math.max(0, all.indexOf(el)))
  }

  // Group subagent output under its Task tool card; render top-level items in order.
  const { top, children, replies } = useMemo(() => {
    const children = new Map<string, Item[]>()
    const top: Item[] = []
    for (const it of items) {
      if (it.parent_tool_use_id) {
        const l = children.get(it.parent_tool_use_id) || []
        l.push(it)
        children.set(it.parent_tool_use_id, l)
      } else top.push(it)
    }
    // The text of each turn's replies, keyed by its result item, for the copy button.
    const replies = new Map<string, string>()
    let buf: string[] = []
    for (const it of top) {
      if (it.kind === 'user') buf = []
      else if (it.kind === 'text' && it.text.trim()) buf.push(it.text.trim())
      else if (it.kind === 'result') { if (buf.length) replies.set(it.id, buf.join('\n\n')); buf = [] }
    }
    return { top, children, replies }
  }, [items])

  const lastTop = top[top.length - 1]
  const lastThinking = !!lastTop && lastTop.kind === 'thinking' && (lastTop as ThinkingItem).streaming
  const lastIsStreamingText = top.length > 0 && top[top.length - 1].kind === 'text' && (top[top.length - 1] as TextItem).streaming
  const ctx = session?.context
  const status = conn.conn.value

  return (
    <div class="page chat-page">
      <TopBar
        left={<BackButton label="" onClick={() => back({ name: 'agent', agentId })} />}
        right={<div class="topbar-actions">
          <button class="icon-btn" aria-label="New conversation" disabled={creating} onClick={newChat}><IconNewChat /></button>
          <button class="icon-btn" aria-label="Session controls" onClick={() => setControls(true)}><IconMore /></button>
        </div>}>
        <button class="chat-title press" onClick={() => setControls(true)}>
          {agent && <Avatar agent={agent} size={32} busy={busy} />}
          <span class="titles">
            <span class="t1">{session?.title || 'New conversation'}</span>
            <span class="t2">
              {agent?.name}
              {state === 'queued' ? ' · waiting for a free slot' : state === 'starting' ? ' · waking up' : ''}
              {ctx ? ` · ${Math.round(ctx.percent)}% context` : ''}
            </span>
          </span>
        </button>
      </TopBar>
      {status !== 'open' && conn.loaded.value && (
        <div class="conn-banner"><span class="spinner" style={{ width: '14px', height: '14px' }} /> Reconnecting. Claude keeps working on the server.</div>
      )}

      <div class="chat-scroll" ref={scroller} onScroll={onScroll}
        onTouchStart={markUser} onTouchMove={markUser} onTouchEnd={markUser} onWheel={markUser} onKeyDown={markUser} onMouseDown={markUser}>
        <div class="chat-inner">
          {!conn.loaded.value && (
            <div class="chat-loading"><Spark size={28} /></div>
          )}
          {conn.hasMore.value && (
            <div class="older">{loadingOlder ? <span class="spinner" /> : <button class="btn small ghost" onClick={loadOlder}>Load earlier messages</button>}</div>
          )}
          {conn.loaded.value && top.length === 0 && (
            <div class="chat-empty rise">
              {agent && <Avatar agent={agent} size={72} />}
              <h2 class="serif">How can I help?</h2>
              <p>{agent?.cwd}</p>
            </div>
          )}
          {top.map((it) => (
            <ItemView key={it.id} it={it} sid={sessionId} children={it.kind === 'tool' ? children.get(it.id) : undefined}
              reply={it.kind === 'result' ? replies.get(it.id) : undefined} onUserMenu={setMsgMenu} onImage={openChatImage} />
          ))}
          {perms.map((p) => <PermissionCard key={p.id} req={p} conn={conn} />)}
          {busy && !lastIsStreamingText && perms.length === 0 && <Working state={state} activity={conn.activity.value} effort={effort} thinking={lastThinking} />}
          {state === 'queued' && (
            <div class="working"><span class="spinner" /> Waiting for a free slot{conn.queuePos.value ? ` (position ${conn.queuePos.value})` : ''}</div>
          )}
          {state === 'starting' && <div class="working"><Spark size={18} /> <span class="shimmer-text">Waking up Claude</span></div>}
          <div style={{ height: '8px' }} />
        </div>
      </div>

      {showJump && (
        <button class="jump-btn pop" onClick={jump} aria-label="Scroll to bottom"><IconChevronDown /></button>
      )}

      <div class="chat-bottom">
        <TaskTray conn={conn} />
        <Composer sid={sessionId} state={state} mode={mode} model={model} slash={init?.slash_commands || []}
          onSend={send} onInterrupt={() => conn.send({ type: 'interrupt' })} onMode={setMode}
          onOpenModel={() => setModelOpen(true)} disabled={status === 'closed'} />
      </div>

      <ControlsSheet open={controls} onClose={() => setControls(false)} conn={conn} agent={agent} mode={mode}
        onMode={setMode} onModel={applyModel} onRename={rename} onFork={() => { setControls(false); forkAt(null) }} />

      <Sheet open={modelOpen} onClose={() => setModelOpen(false)} title="Model">
        <ModelPicker value={session?.overrides?.model ?? ''} onChange={(m) => { applyModel(m); setModelOpen(false) }}
          defaultLabel={`Agent default${agent?.model ? ` (${agent.model})` : ''}`} />
        {init?.model && <div class="fhint" style={{ margin: '10px 4px 0' }}>Running: {init.model}</div>}
        <div class="model-sheet-mode">
          <span class={`mode-swatch mode-${mode}`} /> {MODE_LABELS[mode] || mode}
          <button class="btn small ghost" onClick={() => { setModelOpen(false); setControls(true) }}>More controls</button>
        </div>
      </Sheet>

      <EditSheet item={editing} sid={sessionId} canRewindFiles={!!agent?.enable_file_checkpointing}
        onClose={() => setEditing(null)} onSubmit={resend} />

      <Sheet open={!!msgMenu} onClose={() => setMsgMenu(null)} title="Message">
        {msgMenu && (
          <div class="menu">
            <button onClick={() => { copyText(msgMenu.text); setMsgMenu(null); toast('Copied') }}><IconCopy /> Copy text</button>
            <button disabled={!msgMenu.uuid || busy || !!msgMenu.parent_tool_use_id} onClick={() => startEdit(msgMenu)}><IconEdit /> Edit and resend</button>
            <button disabled={!msgMenu.uuid} onClick={() => forkAt(msgMenu)}><IconFork /> Fork from here</button>
            {agent?.enable_file_checkpointing && (
              <button disabled={!msgMenu.uuid || busy} onClick={() => rewind(msgMenu)}><IconRewind /> Rewind files to here</button>
            )}
          </div>
        )}
      </Sheet>
    </div>
  )
}

// Claude Code's own thinking phrases, by time spent thinking.
function thinkingPhrase(ms: number) {
  if (ms >= 45000) return 'deep in thought'
  if (ms >= 30000) return 'thinking some more'
  if (ms >= 20000) return 'thinking more'
  if (ms >= 10000) return 'still thinking'
  return 'thinking'
}

function activityNote(a: Activity | null, now: number): { text: string; warn?: boolean } | null {
  if (!a) return null
  if (a.kind === 'compacting') return { text: 'compacting conversation' }
  if (a.kind === 'retry') {
    const left = Math.max(0, Math.ceil((Date.parse(a.at) + (a.retry_delay_ms || 0) - now) / 1000))
    const attempt = a.max_retries ? ` (attempt ${a.attempt}/${a.max_retries})` : ''
    if (a.no_response) return { warn: true, text: `No response from the API after ${Math.round(a.no_response.waited_ms / 1000)}s · retrying${attempt}` }
    const what = a.error_status ? `API error ${a.error_status}${a.error && a.error !== 'unknown' ? ` ${a.error.replace(/_/g, ' ')}` : ''}`
      : a.error ? `Waiting for network (${a.error.replace(/_/g, ' ')})` : 'Waiting for network'
    return { warn: true, text: `${what} · retrying in ${left}s${attempt}` }
  }
  return null
}

function Working({ state, activity, effort, thinking }: { state: string; activity: Activity | null; effort: string; thinking: boolean }) {
  const [verb, setVerb] = useState(() => VERBS[Math.floor(Math.random() * VERBS.length)])
  const [now, setNow] = useState(Date.now())
  const t0 = useRef(Date.now())
  const thinkStart = useRef<number | null>(null)
  useEffect(() => {
    const a = setInterval(() => setNow(Date.now()), 1000)
    const b = setInterval(() => setVerb(VERBS[Math.floor(Math.random() * VERBS.length)]), 7000)
    return () => { clearInterval(a); clearInterval(b) }
  }, [])
  if (thinking) { if (thinkStart.current === null) thinkStart.current = Date.now() } else thinkStart.current = null
  const secs = Math.floor((now - t0.current) / 1000)
  const note = activityNote(activity, now)
  const tokens = activity?.kind === 'thinking_tokens' && activity.estimated_tokens ? activity.estimated_tokens : 0
  const parts: string[] = []
  if (secs > 1) parts.push(secs >= 60 ? `${Math.floor(secs / 60)}m ${secs % 60}s` : `${secs}s`)
  if (tokens) parts.push(`${fmtTokens(tokens)} tokens`)
  if (thinking) parts.push(`${thinkingPhrase(now - (thinkStart.current ?? now))}${effort ? ` with ${effort} effort` : ''}`)
  return (
    <div class="working fade-in" aria-live="polite">
      <Spark size={18} />
      <span class="working-text">
        <span class="shimmer-text">{state === 'interrupting' ? 'Stopping' : verb}...</span>
        {parts.length > 0 && <span class="working-meta"> ({parts.join(' · ')})</span>}
        {note && <span class={`working-note ${note.warn ? 'warn' : ''}`}>{note.text}</span>}
      </span>
    </div>
  )
}

const ItemView = memo(function ItemView({ it, sid, children, reply, onUserMenu, onImage }: {
  it: Item; sid: string; children?: Item[]; reply?: string; onUserMenu: (u: UserItem) => void; onImage: (el: HTMLImageElement) => void
}) {
  switch (it.kind) {
    case 'user': return <UserBubble it={it} onMenu={onUserMenu} />
    case 'text': return <AssistantText it={it} sid={sid} onImage={onImage} />
    case 'thinking': return <Thinking it={it} />
    case 'tool': return <ToolCard it={it as ToolItem} children={children} />
    case 'notice': return <div class={`notice ${it.level}`}>{it.text}</div>
    case 'result': return (
      <div class={`turn-end ${it.is_error ? 'err' : ''}`}>
        {it.is_error ? (it.terminal_reason?.startsWith('aborted') ? 'Stopped' : `Ended: ${it.subtype}`) : 'Done'}
        {it.duration_ms ? ` in ${fmtDuration(it.duration_ms)}` : ''}
        {fmtUsage(it.usage)}
        {reply && <CopyReply text={reply} />}
      </div>
    )
  }
  return null
})

function CopyReply({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  const copy = () => copyText(text).then(() => {
    haptic()
    setDone(true)
    setTimeout(() => setDone(false), 1400)
  }).catch(() => toast('Copy failed', 'error'))
  return (
    <button type="button" class={`copy-reply press ${done ? 'done' : ''}`} onClick={copy} aria-label="Copy Claude's reply">
      {done ? <IconCheck width={14} height={14} /> : <IconCopy width={14} height={14} />}
      {done ? 'Copied' : 'Copy'}
    </button>
  )
}

function UserBubble({ it, onMenu }: { it: UserItem; onMenu: (u: UserItem) => void }) {
  const images = it.attachments?.filter((a) => a.is_image) || []
  const files = it.attachments?.filter((a) => !a.is_image) || []
  // Tap opens the message actions; long-press is left to the system so the text can be selected.
  const onClick = () => {
    if (window.getSelection()?.toString()) return
    haptic()
    onMenu(it)
  }
  return (
    <div class={`msg-user ${it.pending ? 'pending' : ''}`}>
      {images.length > 0 && (
        <div class="msg-images">
          {images.map((a, i) => (
            <button type="button" key={a.id || a.url} class="msg-img press" aria-label={`View ${a.name}`}
              onClick={() => openViewer(images.map((x) => ({ src: x.url, name: x.name })), i)}>
              <img src={a.url} alt={a.name} loading="lazy" />
            </button>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <div class="msg-files">
          {files.map((a) => (
            <a class="file-pill" href={a.url} target="_blank" rel="noopener">
              <IconTerminal width={14} height={14} /> {a.name} <span>{fmtBytes(a.size)}</span>
            </a>
          ))}
        </div>
      )}
      {it.text && <div class="bubble" onClick={onClick} onContextMenu={(e) => { if (!matchMedia('(pointer: coarse)').matches) { e.preventDefault(); onMenu(it) } }}>{it.text}</div>}
      {!it.text && <button type="button" class="msg-actions-btn" onClick={() => onMenu(it)} aria-label="Message actions"><IconMore width={18} height={18} /></button>}
      {it.pending && <div class="pending-tag">Queued, Claude reads it at the next step</div>}
    </div>
  )
}

function AssistantText({ it, sid, onImage }: { it: TextItem; sid: string; onImage: (el: HTMLImageElement) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  void mathVersion.value
  const html = it.streaming ? renderStreaming(it.text, sid) : renderMarkdown(it.text, sid)
  const onClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement
    if (target.tagName === 'IMG' && target.hasAttribute('data-view')) { e.preventDefault(); onImage(target as HTMLImageElement); return }
    const btn = (e.target as HTMLElement).closest('[data-copy]') as HTMLElement | null
    if (!btn) return
    const code = btn.closest('.codeblock')?.querySelector('code')?.textContent || ''
    copyText(code).then(() => {
      btn.textContent = 'Copied'
      setTimeout(() => { btn.textContent = 'Copy' }, 1400)
    })
  }
  return (
    <div class={`msg-assistant md ${it.streaming ? 'streaming' : ''}`} ref={ref} onClick={onClick}
      dangerouslySetInnerHTML={{ __html: html }} />
  )
}

function Thinking({ it }: { it: ThinkingItem }) {
  const [open, setOpen] = useState(false)
  if (!it.text && !it.streaming) return null
  return (
    <div class={`thinking ${open ? 'open' : ''} ${it.streaming ? 'streaming' : ''}`}>
      <button class="thinking-head" onClick={() => setOpen(!open)}>
        <IconBrain width={15} height={15} />
        <span class={it.streaming ? 'shimmer-text' : ''}>{it.streaming ? 'Thinking' : 'Thought process'}</span>
        <IconChevronDown class="thinking-chev" width={15} height={15} />
      </button>
      {open && <div class="thinking-body">{it.text}</div>}
    </div>
  )
}

function ControlsSheet({ open, onClose, conn, agent, mode, onMode, onModel, onRename, onFork }: {
  open: boolean
  onClose: () => void
  conn: ChatConn
  agent: Agent | null
  mode: string
  onMode: (m: string) => void
  onModel: (m: string) => void
  onRename: () => void
  onFork: () => void
}) {
  const session = conn.session.value
  const init = conn.init.value
  const tasks = conn.tasks.value
  const [model, setModel] = useState('')
  useEffect(() => { if (open) setModel(session?.overrides?.model ?? '') }, [open])
  const effort = session?.overrides?.effort ?? ''
  const modes = meta.value?.permission_modes || Object.keys(MODE_LABELS)
  const ctx = session?.context

  const applyModel = (m: string) => { setModel(m); onModel(m) }
  const applyEffort = async (e: string) => {
    const err = await conn.send({ type: 'set_effort', effort: e })
    if (err) toast(err, 'error'); else toast(e ? `Effort: ${e}` : 'Effort reset')
  }

  return (
    <Sheet open={open} onClose={onClose} title="This conversation">
      <div class="controls">
        <div class="group-title" style={{ marginTop: '4px' }}>Permission mode</div>
        <div class="mode-list">
          {modes.map((m) => (
            <button key={m} class={`mode-opt ${m === mode ? 'on' : ''}`} onClick={() => onMode(m)}>
              <span class={`mode-swatch mode-${m}`} />
              {MODE_LABELS[m] || m}
            </button>
          ))}
        </div>

        <div class="group-title">Model</div>
        <ModelPicker value={model} onChange={applyModel} defaultLabel={`Agent default${agent?.model ? ` (${agent.model})` : ''}`} />
        {init?.model && <div class="fhint" style={{ margin: '6px 4px 0' }}>Running: {init.model}</div>}

        <div class="group-title">Effort</div>
        <Segmented value={effort} onChange={applyEffort}
          options={['', 'low', 'medium', 'high', 'xhigh', 'max'].map((e) => ({ value: e, label: e || 'Default' }))} />
        <div class="fhint" style={{ margin: '6px 4px 0' }}>Applies from the next message.</div>

        {tasks.length > 0 && (
          <>
            <div class="group-title">Background tasks</div>
            <div class="group">
              {tasks.map((t) => (
                <div key={t.task_id} class="row">
                  <span class="label">{t.description || t.task_id}<span class="hint">{t.status}</span></span>
                  {t.status !== 'completed' && t.status !== 'failed' && t.status !== 'stopped' && (
                    <button class="btn small" onClick={() => conn.send({ type: 'stop_task', task_id: t.task_id })}>Stop</button>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        <div class="group-title">Session</div>
        <div class="stats">
          <div><b>{fmtCost(session?.total_cost_usd)}</b><span>Cost</span></div>
          <div><b>{session?.turns || 0}</b><span>Turns</span></div>
          <div><b>{ctx ? `${fmtTokens(ctx.used)}` : '-'}</b><span>{ctx ? `of ${fmtTokens(ctx.max)} context` : 'Context'}</span></div>
        </div>
        {ctx && <div class="ctx-bar"><span style={{ width: `${Math.min(100, ctx.percent)}%` }} /></div>}
        <div class="menu" style={{ padding: '10px 0 0' }}>
          <button onClick={() => { onClose(); onRename() }}><IconEdit /> Rename</button>
          <button onClick={onFork}><IconFork /> Fork conversation</button>
        </div>
        {init && (
          <div class="init-info">
            {init.claude_code_version && <span>Claude Code {init.claude_code_version}</span>}
            {init.mcp_servers && init.mcp_servers.length > 0 && (
              <span>MCP: {init.mcp_servers.map((s) => `${s.name} (${s.status})`).join(', ')}</span>
            )}
            {init.tools && <span>{init.tools.length} tools available</span>}
          </div>
        )}
      </div>
    </Sheet>
  )
}

/** Edit an earlier message and continue the conversation from there (like /rewind in Claude Code). */
function EditSheet({ item, sid, canRewindFiles, onClose, onSubmit }: {
  item: UserItem | null
  sid: string
  canRewindFiles: boolean
  onClose: () => void
  onSubmit: (it: UserItem, text: string, atts: Attachment[], rewindFiles: boolean) => Promise<boolean>
}) {
  const [text, setText] = useState('')
  const [atts, setAtts] = useState<Attachment[]>([])
  const [rewindFiles, setRewindFiles] = useState(false)
  const [busy, setBusy] = useState(false)
  const ta = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (!item) return
    setText(item.text)
    setAtts((item.attachments || []).filter((a) => a.id))
    setRewindFiles(false)
    setTimeout(() => { const el = ta.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length) } }, 300)
  }, [item])
  void sid
  const submit = async () => {
    if (!item || busy || (!text.trim() && !atts.length)) return
    setBusy(true)
    const ok = await onSubmit(item, text, atts, rewindFiles)
    setBusy(false)
    if (ok) onClose()
  }
  return (
    <Sheet open={!!item} onClose={onClose} title="Edit message">
      <p class="sheet-note">Claude continues from this point with your edited message. Later messages are removed from this chat.</p>
      <textarea ref={ta} class="textarea edit-area" rows={5} value={text}
        onInput={(e) => setText((e.target as HTMLTextAreaElement).value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit() } }} />
      {atts.length > 0 && (
        <div class="att-strip" style={{ marginTop: '8px' }}>
          {atts.map((a) => (
            <div key={a.id} class="att-chip">
              {a.is_image ? <img src={a.url} alt="" /> : <span class="att-icon"><IconTerminal width={18} height={18} /></span>}
              <span class="att-meta"><span class="att-name">{a.name}</span><span class="att-size">{fmtBytes(a.size)}</span></span>
              <button class="att-x" aria-label="Remove" onClick={() => setAtts(atts.filter((x) => x.id !== a.id))}>×</button>
            </div>
          ))}
        </div>
      )}
      {canRewindFiles && (
        <div class="row" style={{ padding: '12px 4px 0' }}>
          <span class="label">Also rewind files<span class="hint">Undo file changes Claude made after this message.</span></span>
          <Switch on={rewindFiles} onChange={setRewindFiles} label="Also rewind files" />
        </div>
      )}
      <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
        <button class="btn block" onClick={onClose}>Cancel</button>
        <button class="btn block primary" disabled={busy || (!text.trim() && !atts.length)} onClick={submit}>
          {busy ? <span class="spinner" /> : <><IconRewind width={18} height={18} /> Resend</>}
        </button>
      </div>
    </Sheet>
  )
}
