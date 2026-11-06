// LLM chat page: a copy of the Claude chat for plain provider chats. Model, effort and MCP servers
// switch per conversation; user messages can be edited and the last reply regenerated.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks'
import { memo } from 'preact/compat'
import { toast, toastError } from '../../../lib/store'
import { back, navigate, parentOf, route } from '../../../lib/router'
import { Avatar, Spark } from '../../../components/crab'
import { BackButton, Sheet, Switch, TopBar, confirmDialog, promptDialog } from '../../../components/ui'
import { IconBrain, IconChevronDown, IconCopy, IconMore, IconEdit, IconSelect, IconNewChat, IconPlug, IconRefresh, IconTrash, IconClose, IconFile } from '../../../components/icons'
import { openViewer } from '../../../components/ImageViewer'
import { copyText, fmtBytes, fmtDuration, fmtTokens, haptic, uid } from '../../../lib/util'
import type { Attachment, Item, TextItem, UserItem as BaseUser } from '../../../lib/types'
import { EFFORTS, chatApi, modelLabel, type Assistant, type ChatMeta, type Effort } from '../api'
import { useAssistantFlags } from '../flags'
import { TextViewer } from '../TextViewer'
import { ChatConn } from './conn'
import { Composer } from './Composer'
import { ToolCard } from './tools'
import { CopyAct, Act, MsgHead, ThinkingCard, Versions } from './messages'
import { UserAvatar } from '../profile'
import { mathVersion, renderMarkdown, renderStreaming } from './markdown'
import { clearFade, fadeTail, makeFollower, newFade, unwrapFade } from './fade'

// Chat items carry version info (docs/protocol-chat.md, Versions).
type UserItem = BaseUser & { group?: string; version?: [number, number]; reply_version?: [number, number] }
type ResultItem = { id: string; kind: 'result'; duration_ms: number; usage?: { input: number; output: number }; model?: string; stop_reason?: string }

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches

type SheetKind = 'model' | 'effort' | 'mcp' | 'session' | null

export function LlmChat({ assistantId, sessionId }: { assistantId: string; sessionId: string }) {
  const conn = useMemo(() => new ChatConn(sessionId), [sessionId])
  const [asst, setAsst] = useState<Assistant | null>(null)
  const [meta, setMeta] = useState<ChatMeta | null>(null)
  const [sheet, setSheet] = useState<SheetKind>(null)
  const flags = useAssistantFlags(assistantId)
  const [viewFile, setViewFile] = useState<{ name: string; url: string } | null>(null)
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
  const [replyEdit, setReplyEdit] = useState<{ id: string; text: string } | null>(null)
  const switchTo = (key: string, index: number) => { stick.current = false; command({ type: 'switch', key, index }) }
  const saveReply = async () => {
    if (!replyEdit) return
    const err = await conn.send({ type: 'edit_reply', id: replyEdit.id, text: replyEdit.text })
    if (err) return toast(err, 'error')
    setReplyEdit(null)
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

  // One block per user message and one per reply (everything up to the next user message).
  const turns = useMemo(() => {
    type Turn = { user: UserItem } | { reply: Item[]; to: UserItem | null; result: ResultItem | null; text: TextItem | null; copy: string }
    const out: Turn[] = []
    let cur: Item[] | null = null, to: UserItem | null = null
    const close = () => {
      if (!cur) return
      const texts = cur.filter((x): x is TextItem => x.kind === 'text' && !!x.text.trim())
      out.push({ reply: cur, to, result: ([...cur].reverse().find((x) => x.kind === 'result') as unknown as ResultItem) || null,
        text: texts.at(-1) || null, copy: texts.map((x) => x.text.trim()).join('\n\n') })
      cur = null
    }
    for (const it of items) {
      if (it.kind === 'user') { close(); out.push({ user: it }); to = it; cur = [] }
      else (cur ||= []).push(it)
    }
    close()
    return out.filter((t) => !('reply' in t) || t.reply.length || busy)
  }, [items, busy])

  const last = items[items.length - 1]
  const streamingText = last?.kind === 'text' && (last as TextItem).streaming
  const status = conn.conn.value
  const shown = asst || { id: assistantId, avatar: 'crab:gray', order: 0, name: 'Chat' }
  const me = meta?.profile || { name: 'You', avatar: '' }

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
          {turns.map((t, ti) => {
            if ('user' in t) {
              const u = t.user
              return (
                <div key={u.id} class="turn turn-user">
                  <MsgHead right avatar={<UserAvatar p={me} size={26} />} name={me.name} ts={u.ts} />
                  <UserBubble it={u} onMenu={setMsgMenu} onFile={setViewFile} />
                  {!u.pending && <div class="msg-actions right">
                    <Versions v={u.version} disabled={busy} onSwitch={(i) => switchTo(`u:${u.group || u.id}`, i)} />
                    {u.text && <CopyAct text={u.text} />}
                    <Act label="Edit" disabled={busy} onClick={() => startEdit(u)}><IconEdit width={15} height={15} /></Act>
                  </div>}
                </div>
              )
            }
            const live = busy && ti === turns.length - 1
            const r = t.result, u = r?.usage, to = t.to
            return (
              <div key={'r-' + (t.reply[0]?.id || ti)} class="turn turn-reply">
                <MsgHead avatar={<AssistantAvatar a={shown} busy={live} size={26} />} name={shown.name} ts={t.reply[0]?.ts} />
                {t.reply.map((it) => <ItemView key={it.id} it={it} onImage={openChatImage} />)}
                {live && !streamingText && <Working start={conn.turnStart.value} />}
                {!live && <div class="msg-actions">
                  {to && <Versions v={to.reply_version} disabled={busy} onSwitch={(i) => switchTo(`r:${to.uuid || to.id}`, i)} />}
                  {t.copy && <CopyAct text={t.copy} />}
                  {to && <Act label="Retry" disabled={busy} onClick={() => command({ type: 'regenerate', uuid: to.uuid || to.id })}><IconRefresh width={15} height={15} /></Act>}
                  {t.text && <Act label="Edit reply" disabled={busy} onClick={() => setReplyEdit({ id: t.text!.id, text: t.text!.text })}><IconEdit width={15} height={15} /></Act>}
                  {r && <span class="msg-meta">
                    {r.stop_reason === 'edited' ? 'Edited' : [r.model && modelLabel(r.model), r.duration_ms ? fmtDuration(r.duration_ms) : '',
                      u && (u.input || u.output) ? `${fmtTokens(u.input)} in · ${fmtTokens(u.output)} out` : ''].filter(Boolean).join(' · ')}
                  </span>}
                </div>}
              </div>
            )
          })}
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
          files={flags.files} disabled={status === 'closed'} fill={fill.n ? fill : undefined} />
      </div>

      <TextViewer open={!!viewFile} onClose={() => setViewFile(null)} name={viewFile?.name || ''} url={viewFile?.url || ''} />

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
      <Sheet open={!!replyEdit} onClose={() => setReplyEdit(null)} title="Edit reply"
        actions={<button class="btn primary small" disabled={busy} onClick={saveReply}>Save</button>}>
        {replyEdit && <textarea class="input reply-edit" rows={12} value={replyEdit.text}
          onInput={(e) => setReplyEdit({ ...replyEdit, text: (e.target as HTMLTextAreaElement).value })} />}
        <p class="fhint">Saved as a new version of this reply. Later messages use the edited text as context.</p>
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

const ItemView = memo(function ItemView({ it, onImage }: { it: Item; onImage: (el: HTMLImageElement) => void }) {
  switch (it.kind) {
    case 'text': return <AssistantText it={it} onImage={onImage} />
    case 'thinking': return <ThinkingCard it={it} />
    case 'tool': return <ToolCard it={it} />
    case 'notice': return <div class={`notice ${it.level}`}>{it.text}</div>
  }
  return null
})

function UserBubble({ it, onMenu, onFile }: { it: UserItem; onMenu: (u: UserItem) => void; onFile: (f: { name: string; url: string }) => void }) {
  const images = it.attachments?.filter((a) => a.is_image) || []
  const texts = it.attachments?.filter((a) => !a.is_image) || []
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
      {texts.length > 0 && (
        <div class="msg-files">
          {texts.map((a) => (
            <button type="button" key={a.id || a.url} class="file-chip press" aria-label={`Open ${a.name}`} onClick={() => onFile({ name: a.name, url: a.url })}>
              <span class="att-icon"><IconFile width={18} height={18} /></span>
              <span class="att-meta"><span class="att-name">{a.name}</span><span class="att-size">{fmtBytes(a.size)}</span></span>
            </button>
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
