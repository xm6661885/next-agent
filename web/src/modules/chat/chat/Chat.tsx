// LLM chat page: a copy of the Claude chat for plain provider chats. Model, effort and MCP servers
// switch per conversation; user messages can be edited and the last reply regenerated.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks'
import { memo } from 'preact/compat'
import { toast, toastError } from '../../../lib/store'
import { back, navigate, parentOf, route } from '../../../lib/router'
import { Avatar, Spark } from '../../../components/crab'
import { BackButton, Sheet, Switch, TopBar, confirmDialog, promptDialog } from '../../../components/ui'
import { IconBrain, IconCheck, IconChevron, IconChevronDown, IconCopy, IconMore, IconEdit, IconSelect, IconNewChat, IconPlug, IconRefresh, IconTrash, IconClose } from '../../../components/icons'
import { openViewer } from '../../../components/ImageViewer'
import { copyText, fmtDuration, haptic, uid } from '../../../lib/util'
import type { Attachment, Item, TextItem, ThinkingItem, UserItem } from '../../../lib/types'
import { EFFORTS, chatApi, modelLabel, type Assistant, type ChatMeta, type Effort } from '../api'
import { ChatConn } from './conn'
import { Composer } from './Composer'
import { ToolCard } from './tools'
import { mathVersion, renderMarkdown, renderStreaming } from './markdown'
import { clearFade, fadeTail, makeFollower, newFade, unwrapFade } from './fade'

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches

type SheetKind = 'model' | 'effort' | 'mcp' | 'session' | null

export function LlmChat({ assistantId, sessionId }: { assistantId: string; sessionId: string }) {
  const conn = useMemo(() => new ChatConn(sessionId), [sessionId])
  const [asst, setAsst] = useState<Assistant | null>(null)
  const [meta, setMeta] = useState<ChatMeta | null>(null)
  const [sheet, setSheet] = useState<SheetKind>(null)
  const [editing, setEditing] = useState<UserItem | null>(null)
  const [msgMenu, setMsgMenu] = useState<UserItem | null>(null)
  const [selectText, setSelectText] = useState<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const userScroll = useRef(0)
  const markUser = () => { userScroll.current = Date.now() }
  const [showJump, setShowJump] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [fill, setFill] = useState({ text: '', n: 0 })

  useEffect(() => {
    conn.onError = (m) => toast(m, 'error', 4000)
    return () => {
      // A new chat that was left without sending anything is discarded.
      const s = conn.session.value
      const empty = s && !s.title && conn.items.value.length === 0
      conn.dispose()
      if (empty) chatApi.deleteSession(s.id).catch(() => {})
      else if (s) chatApi.markRead(s.id).catch(() => {})
    }
  }, [conn])
  useEffect(() => { chatApi.assistant(assistantId).then(setAsst).catch(() => {}) }, [assistantId])
  useEffect(() => { chatApi.meta().then(setMeta).catch(() => {}) }, [])

  const items = conn.items.value
  const state = conn.state.value
  const session = conn.session.value
  const busy = state === 'running'
  // Same resolution chain as the server: chat override, assistant, global default, first configured model.
  const model = session?.overrides.model || asst?.model || meta?.defaults.model || meta?.models[0]?.id || ''
  const effort: Effort = session?.overrides.effort || asst?.effort || meta?.defaults.effort || 'medium'
  const servers = meta?.mcp_servers || []
  const mcpOn = session?.mcp.filter((m) => servers.includes(m)) || []

  const onScroll = () => {
    const el = scroller.current
    if (!el) return
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight
    if (dist < 80) stick.current = true
    else if (Date.now() - userScroll.current < 2500) stick.current = false
    setShowJump(dist > 400)
    if (el.scrollTop < 200 && conn.hasMore.value && !loadingOlder) loadOlder()
  }
  const follower = useMemo(() => makeFollower(() => scroller.current), [])
  const firstPaint = useRef(true)
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el || !stick.current) return
    if (firstPaint.current || reduceMotion || el.scrollHeight - el.scrollTop - el.clientHeight > 1500) { follower.jump(); firstPaint.current = false }
    else follower.follow()
  }, [items, state])
  useEffect(() => {
    const el = scroller.current, inner = el?.firstElementChild
    if (!el || !inner || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => { if (stick.current) follower.follow() })
    ro.observe(inner)
    return () => ro.disconnect()
  }, [])

  const loadOlder = async () => {
    const first = conn.items.value[0]
    if (!first) return
    setLoadingOlder(true)
    const el = scroller.current
    const prevH = el?.scrollHeight || 0
    try {
      const r = await chatApi.items(sessionId, first.id)
      conn.prependHistory(r.items, r.has_more)
      requestAnimationFrame(() => { if (el) el.scrollTop += el.scrollHeight - prevH })
    } catch (e) { toastError(e) } finally { setLoadingOlder(false) }
  }
  const jump = () => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    stick.current = true
  }

  const send = async (text: string, atts: Attachment[]) => {
    const client_id = uid()
    stick.current = true
    const ed = editing
    setEditing(null)
    if (!ed) conn.addLocalUser(client_id, text, atts)
    const err = await conn.send(ed
      ? { type: 'edit', uuid: ed.uuid || ed.id, client_id, text, attachments: atts.map((a) => a.id) }
      : { type: 'send', client_id, text, attachments: atts.map((a) => a.id) })
    if (err) { conn.removeLocal(client_id); toast(err, 'error'); if (ed) setEditing(ed); return false }
    return true
  }
  const command = async (m: Record<string, any>, ok?: string) => {
    haptic()
    const err = await conn.send(m)
    if (err) toast(err, 'error')
    else if (ok) toast(ok)
  }
  const pickModel = (id: string) => { setSheet(null); command({ type: 'set_model', model: id }, modelLabel(id)) }
  const pickEffort = (e: Effort) => { setSheet(null); command({ type: 'set_effort', effort: e }, `Thinking: ${e}`) }
  const toggleMcp = (id: string) => {
    const next = mcpOn.includes(id) ? mcpOn.filter((x) => x !== id) : [...mcpOn, id]
    command({ type: 'set_mcp', mcp: next })
  }
  const startEdit = (u: UserItem) => {
    setMsgMenu(null)
    if (busy) return toast('Wait for the reply to finish', 'error')
    setEditing(u)
    setFill((f) => ({ text: u.text, n: f.n + 1 }))
  }
  const rename = async () => {
    const t = await promptDialog({ title: 'Rename conversation', value: session?.title || '', confirm: 'Rename' })
    if (!t?.trim()) return
    try { conn.session.value = await chatApi.updateSession(sessionId, { title: t.trim() }) } catch (e) { toastError(e) }
  }
  const [creating, setCreating] = useState(false)
  const newChat = async () => {
    if (creating) return
    setCreating(true)
    try {
      const s = await chatApi.createSession(assistantId)
      haptic()
      navigate({ name: 'llm-chat', assistantId, sessionId: s.id }, { replace: true })
    } catch (e) { toastError(e) } finally { setCreating(false) }
  }
  const remove = async () => {
    setSheet(null)
    if (!await confirmDialog({ title: 'Delete conversation?', body: session?.title || 'New conversation', confirm: 'Delete', danger: true })) return
    try { await chatApi.deleteSession(sessionId); back(parentOf(route.value)) } catch (e) { toastError(e) }
  }
  const openChatImage = (el: HTMLImageElement) => {
    const all = Array.from(scroller.current?.querySelectorAll<HTMLImageElement>('.msg-assistant img') || [])
    openViewer(all.map((x) => ({ src: x.src, name: x.alt })), Math.max(0, all.indexOf(el)))
  }

  // Finished turns fold their process (thinking, tools) behind one row and show only the answer, as in the Claude chat.
  const { rows, replies } = useMemo(() => {
    const top = items
    const replies = new Map<string, string>()
    let buf: string[] = []
    for (const it of top) {
      if (it.kind === 'user') buf = []
      else if (it.kind === 'text' && it.text.trim()) buf.push(it.text.trim())
      else if (it.kind === 'result') { if (buf.length) replies.set(it.id, buf.join('\n\n')); buf = [] }
    }
    type Row = { it: Item } | { fold: string; items: Item[]; tools: number; ms: number }
    const rows: Row[] = []
    const turns: Item[][] = [[]]
    for (const it of top) { if (it.kind === 'user') turns.push([it], []); else turns[turns.length - 1].push(it) }
    turns.forEach((turn, ti) => {
      const live = busy && ti === turns.length - 1
      if (live || turn[0]?.kind === 'user') { for (const it of turn) rows.push({ it }); return }
      let run: Item[] = []
      const close = (next?: Item) => {
        if (!run.length) return
        const t0 = Date.parse(run[0].ts || ''), t1 = Date.parse(next?.ts || run.at(-1)!.ts || '')
        rows.push({ fold: run[0].id, items: run, tools: run.filter((x) => x.kind === 'tool').length, ms: t1 - t0 })
        run = []
      }
      for (const it of turn) {
        if (it.kind === 'text' && !it.text.trim() && !it.streaming) { if (run.length) run.push(it); continue }
        if (it.kind === 'tool' || it.kind === 'thinking') run.push(it)
        else { close(it); rows.push({ it }) }
      }
      close()
    })
    return { rows, replies }
  }, [items, busy])
  const [unfolded, setUnfolded] = useState<Set<string>>(new Set())
  const toggleFold = (id: string) => {
    stick.current = false
    markUser()
    setUnfolded((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  const last = items[items.length - 1]
  const streamingText = last?.kind === 'text' && (last as TextItem).streaming
  const status = conn.conn.value
  const shown = asst || { id: assistantId, avatar: 'crab:gray', order: 0, name: 'Chat' }
  const lastUser = [...items].reverse().find((x): x is UserItem => x.kind === 'user')
  const canRegen = !busy && !!lastUser && last?.kind !== 'user'

  return (
    <div class="page chat-page">
      <TopBar
        left={<BackButton label="" onClick={() => back(parentOf(route.value))} />}
        right={<div class="topbar-actions">
          <button class="icon-btn" aria-label="New conversation" disabled={creating} onClick={newChat}><IconNewChat /></button>
          <button class="icon-btn" aria-label="Conversation options" onClick={() => setSheet('session')}><IconMore /></button>
        </div>}>
        <button class="chat-title press" onClick={() => setSheet('session')}>
          <AssistantAvatar a={shown} busy={busy} size={32} />
          <span class="titles">
            <span class="t1">{session?.title || 'New conversation'}</span>
            <span class="t2">{shown.name}{model ? ` · ${modelLabel(model)}` : ''}</span>
          </span>
        </button>
      </TopBar>
      {status !== 'open' && conn.loaded.value && (
        <div class="conn-banner"><span class="spinner" style={{ width: '14px', height: '14px' }} /> Reconnecting. The reply keeps going.</div>
      )}
      <div class="chat-scroll" ref={scroller} onScroll={onScroll}
        onTouchStart={markUser} onTouchMove={markUser} onTouchEnd={markUser} onWheel={markUser} onKeyDown={markUser} onMouseDown={markUser}>
        <div class="chat-inner">
          {!conn.loaded.value && <div class="chat-loading"><Spark size={28} /></div>}
          {conn.hasMore.value && (
            <div class="older">{loadingOlder ? <span class="spinner" /> : <button class="btn small ghost" onClick={loadOlder}>Load earlier messages</button>}</div>
          )}
          {conn.loaded.value && items.length === 0 && (
            <div class="chat-empty rise">
              <AssistantAvatar a={shown} size={72} />
              <h2 class="serif">How can I help?</h2>
              <p>{asst?.description || modelLabel(model)}</p>
            </div>
          )}
          {rows.map((r) => {
            const one = (it: Item) => <ItemView key={it.id} it={it} reply={replies.get(it.id)} onUserMenu={setMsgMenu} onImage={openChatImage}
              onRegen={canRegen && it.kind === 'result' && it === last ? () => command({ type: 'regenerate' }) : undefined} />
            if ('it' in r) return <div key={r.it.id} style={{ display: 'contents' }}>{one(r.it)}</div>
            const open = unfolded.has(r.fold)
            const secs = r.ms > 0 ? fmtDuration(r.ms) : ''
            return (
              <div key={'fold-' + r.fold} class={`fold ${open ? 'open' : ''}`}>
                <button class="fold-head" onClick={() => toggleFold(r.fold)} aria-expanded={open}>
                  <span>{r.tools ? 'Worked' : 'Thought'}{secs ? ` for ${secs}` : ''}{r.tools ? ` · ${r.tools} tool call${r.tools > 1 ? 's' : ''}` : ''}</span>
                  <IconChevron class="fold-chev" width={14} height={14} />
                </button>
                {open && <div class="fold-body">{r.items.map(one)}</div>}
              </div>
            )
          })}
          {busy && !streamingText && <Working start={conn.turnStart.value} />}
          <div style={{ height: '8px' }} />
        </div>
      </div>
      {showJump && <button class="jump-btn pop" onClick={jump} aria-label="Scroll to bottom"><IconChevronDown /></button>}
      <div class="chat-bottom">
        {editing && <div class="queue-tray"><div class="queue-row pop">
          <span class="queue-label">Editing</span>
          <span class="queue-text">{editing.text}</span>
          <button class="icon-btn" aria-label="Cancel edit" onClick={() => { setEditing(null); setFill((f) => ({ text: '', n: f.n + 1 })) }}><IconClose width={16} height={16} /></button>
        </div></div>}
        <Composer sid={sessionId} busy={busy} model={modelLabel(model)} effort={effort} mcpOn={servers.length ? mcpOn.length : null}
          onSend={send} onStop={() => conn.send({ type: 'stop' })}
          onOpenModel={() => setSheet('model')} onOpenEffort={() => setSheet('effort')} onOpenMcp={() => setSheet('mcp')}
          disabled={status === 'closed'} fill={fill.n ? fill : undefined} />
      </div>

      <Sheet open={sheet === 'model'} onClose={() => setSheet(null)} title="Model">
        <div class="menu">
          {(meta?.models || []).map((m) => (
            <button key={m.id} onClick={() => pickModel(m.id)} aria-pressed={m.id === model}>
              <span class="label">{m.model}<span class="hint">{m.provider}</span></span>{m.id === model && <span class="menu-check">Current</span>}
            </button>
          ))}
          {session?.overrides.model && <button onClick={() => pickModel('')}><IconRefresh /> Use the assistant default</button>}
          {meta && !meta.models.length && <p class="fhint" style={{ padding: '8px 4px' }}>No models yet. Add a provider in Settings, Chat.</p>}
        </div>
      </Sheet>
      <Sheet open={sheet === 'effort'} onClose={() => setSheet(null)} title="Thinking">
        <div class="chips" style={{ padding: '4px 2px 12px' }}>
          {EFFORTS.map((e) => <button key={e} class={`chip ${e === effort ? 'pink' : ''}`} onClick={() => pickEffort(e)}>{e}</button>)}
        </div>
        <p class="fhint">Off sends no reasoning setting. Anthropic models get a thinking budget, OpenAI-format models get reasoning_effort.</p>
      </Sheet>
      <Sheet open={sheet === 'mcp'} onClose={() => setSheet(null)} title="MCP servers in this chat">
        <div class="group">
          {servers.map((id) => (
            <div key={id} class="row">
              <span class="label"><IconPlug width={16} height={16} /> {id}</span>
              <Switch on={mcpOn.includes(id)} onChange={() => toggleMcp(id)} label={id} />
            </div>
          ))}
        </div>
      </Sheet>
      <Sheet open={sheet === 'session'} onClose={() => setSheet(null)} title="This conversation">
        <div class="menu">
          <button onClick={() => { setSheet(null); rename() }}><IconEdit /> Rename</button>
          <button onClick={() => setSheet('model')}><IconChevronDown /> Model: {modelLabel(model) || 'none'}</button>
          <button onClick={() => setSheet('effort')}><IconBrain /> Thinking: {effort}</button>
          {servers.length > 0 && <button onClick={() => setSheet('mcp')}><IconPlug /> MCP servers: {mcpOn.length} on</button>}
          <button class="danger" onClick={remove}><IconTrash /> Delete</button>
        </div>
        {session && (session.usage.input > 0 || session.usage.output > 0) &&
          <div class="init-info"><span>Tokens</span><span>{session.usage.input.toLocaleString()} in · {session.usage.output.toLocaleString()} out</span></div>}
      </Sheet>
      <Sheet open={selectText !== null} onClose={() => setSelectText(null)} title="Select text">
        <div class="select-text selectable">{selectText}</div>
      </Sheet>
      <Sheet open={!!msgMenu} onClose={() => setMsgMenu(null)} title="Message">
        {msgMenu && (
          <div class="menu">
            <button onClick={() => { copyText(msgMenu.text); setMsgMenu(null); toast('Copied') }}><IconCopy /> Copy text</button>
            {msgMenu.text && <button onClick={() => { setSelectText(msgMenu.text); setMsgMenu(null) }}><IconSelect /> Select text</button>}
            {!msgMenu.pending && <button onClick={() => startEdit(msgMenu)}><IconEdit /> Edit and resend</button>}
          </div>
        )}
      </Sheet>
    </div>
  )
}

export function AssistantAvatar({ a, size, busy }: { a: { id: string; avatar: string; order: number }; size: number; busy?: boolean }) {
  // Uploaded avatars of assistants are served by the chat routes, not the Claude ones.
  if (a.avatar === 'file') return (
    <span class={`avatar ${busy ? 'busy' : ''}`} style={{ width: `${size}px`, height: `${size}px` }}>
      <img src={chatApi.avatarUrl(a)} alt="" loading="lazy" decoding="async" />
    </span>
  )
  return <Avatar agent={a} size={size} busy={busy} />
}

function Working({ start }: { start: number | null }) {
  const [now, setNow] = useState(Date.now())
  const t0 = useRef(Date.now())
  useEffect(() => { const a = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(a) }, [])
  const secs = Math.max(0, Math.floor((now - (start ?? t0.current)) / 1000))
  return (
    <div class="working fade-in" aria-live="polite">
      <Spark size={18} />
      <span class="working-text">
        <span class="shimmer-text">Replying...</span>
        {secs > 1 && <span class="working-meta"> ({secs >= 60 ? `${Math.floor(secs / 60)}m ${secs % 60}s` : `${secs}s`})</span>}
      </span>
    </div>
  )
}

const ItemView = memo(function ItemView({ it, reply, onUserMenu, onImage, onRegen }: {
  it: Item; reply?: string; onUserMenu: (u: UserItem) => void; onImage: (el: HTMLImageElement) => void; onRegen?: () => void
}) {
  switch (it.kind) {
    case 'user': return <UserBubble it={it} onMenu={onUserMenu} />
    case 'text': return <AssistantText it={it} onImage={onImage} />
    case 'thinking': return <Thinking it={it} />
    case 'tool': return <ToolCard it={it} />
    case 'notice': return <div class={`notice ${it.level}`}>{it.text}</div>
    case 'result': {
      const r = it as any
      const u = r.usage
      return (
        <div class="turn-end">
          {r.model ? modelLabel(r.model) : 'Done'}
          {r.duration_ms ? ` · ${fmtDuration(r.duration_ms)}` : ''}
          {u && (u.input || u.output) ? ` · ${u.output} tokens` : ''}
          {reply && <CopyReply text={reply} />}
          {onRegen && <button type="button" class="copy-reply press" onClick={onRegen} aria-label="Regenerate"><IconRefresh width={14} height={14} />Retry</button>}
        </div>
      )
    }
  }
  return null
})

function CopyReply({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  const copy = () => copyText(text).then(() => { haptic(); setDone(true); setTimeout(() => setDone(false), 1400) }).catch(() => toast('Copy failed', 'error'))
  return (
    <button type="button" class={`copy-reply press ${done ? 'done' : ''}`} onClick={copy} aria-label="Copy reply">
      {done ? <IconCheck width={14} height={14} /> : <IconCopy width={14} height={14} />}{done ? 'Copied' : 'Copy'}
    </button>
  )
}

function UserBubble({ it, onMenu }: { it: UserItem; onMenu: (u: UserItem) => void }) {
  const images = it.attachments?.filter((a) => a.is_image) || []
  const press = useRef<{ timer?: number; x: number; y: number }>({ x: 0, y: 0 })
  const startPress = (e: TouchEvent) => {
    const t = e.touches[0]
    press.current = { x: t.clientX, y: t.clientY, timer: window.setTimeout(() => { haptic(); onMenu(it) }, 480) }
  }
  const movePress = (e: TouchEvent) => {
    const t = e.touches[0]
    if (Math.abs(t.clientX - press.current.x) > 8 || Math.abs(t.clientY - press.current.y) > 8) clearTimeout(press.current.timer)
  }
  const endPress = () => clearTimeout(press.current.timer)
  return (
    <div class={`msg-user ${it.pending ? 'pending' : ''}`}>
      {images.length > 0 && (
        <div class="msg-images">
          {images.map((a, i) => (
            <button type="button" key={a.id || a.url} class="msg-img press" aria-label={`View ${a.name}`}
              onClick={() => openViewer(images.map((x) => ({ src: x.url, name: x.name })), i)}><img src={a.url} alt={a.name} loading="lazy" /></button>
          ))}
        </div>
      )}
      {it.text && <div class="bubble" onContextMenu={(e) => { e.preventDefault(); onMenu(it) }}
        onTouchStart={startPress} onTouchMove={movePress} onTouchEnd={endPress} onTouchCancel={endPress}>{it.text}</div>}
    </div>
  )
}

function AssistantText({ it, onImage }: { it: TextItem; onImage: (el: HTMLImageElement) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const fade = useRef(newFade())
  void mathVersion.value
  useLayoutEffect(() => {
    if (!it.streaming || reduceMotion || !ref.current) { fade.current = newFade(); if (ref.current) clearFade(ref.current); return }
    fadeTail(ref.current, fade.current)
  })
  const onClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement
    if (target.tagName === 'IMG') { e.preventDefault(); onImage(target as HTMLImageElement); return }
    const btn = target.closest('[data-copy]') as HTMLElement | null
    if (!btn) return
    copyText(btn.closest('.codeblock')?.querySelector('code')?.textContent || '').then(() => {
      btn.textContent = 'Copied'
      setTimeout(() => { btn.textContent = 'Copy' }, 1400)
    })
  }
  return (
    <div class={`msg-assistant md ${it.streaming ? 'streaming' : ''}`} ref={ref} onClick={onClick}
      onAnimationEnd={(e) => unwrapFade(e.target as Element)}
      dangerouslySetInnerHTML={{ __html: it.streaming ? renderStreaming(it.text) : renderMarkdown(it.text) }} />
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
