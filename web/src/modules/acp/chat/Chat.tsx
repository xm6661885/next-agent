// ACP chat page: a copy of the Claude chat trimmed to what ACP supports (no steer, edit, fork, rewind,
// side questions, background tasks or generative UI). Model and other options come from the agent's configOptions.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks'
import { memo } from 'preact/compat'
import { toast, toastError } from '../../../lib/store'
import { back, navigate, parentOf, route } from '../../../lib/router'
import { Avatar, Spark } from '../../../components/crab'
import { BackButton, Sheet, TopBar, promptDialog } from '../../../components/ui'
import { IconBrain, IconCheck, IconChevron, IconChevronDown, IconCopy, IconMore, IconEdit, IconSelect, IconNewChat, IconTerminal, IconMoon } from '../../../components/icons'
import { openViewer } from '../../../components/ImageViewer'
import { copyText, fmtBytes, fmtDuration, haptic, uid } from '../../../lib/util'
import type { Attachment, Item, TextItem, ThinkingItem, UserItem } from '../../../lib/types'
import { acpApi, type AcpAgent, type ConfigOption } from '../api'
import { AcpConn } from './conn'
import { Composer } from './Composer'
import { PermissionCard } from './cards'
import { ToolCard, type AcpToolItem } from './tools'
import { mathVersion, renderMarkdown, renderStreaming } from './markdown'
import { clearFade, fadeTail, makeFollower, newFade, unwrapFade } from './fade'

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches

/** Shown in place of the user's avatar choice when the agent has none. */
export const acpAvatar = (a: AcpAgent | null) => a ? { ...a, avatar: a.avatar, id: a.id, order: a.order } : { id: '', avatar: 'crab:blue', order: 0 }

export function AcpChat({ agentId, sessionId }: { agentId: string; sessionId: string }) {
  const conn = useMemo(() => new AcpConn(sessionId), [sessionId])
  const [agent, setAgent] = useState<AcpAgent | null>(null)
  const [optionsOpen, setOptionsOpen] = useState(false)
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
      const empty = s && !s.remote_id && s.turns === 0 && conn.items.value.length === 0
      conn.dispose()
      if (empty) acpApi.deleteSession(s.id).catch(() => {})
    }
  }, [conn])
  useEffect(() => { acpApi.agent(agentId).then(setAgent).catch(() => {}) }, [agentId])

  const items = conn.items.value
  const state = conn.state.value
  const session = conn.session.value
  const perms = conn.perms.value
  const busy = state === 'running' || state === 'interrupting'
  const options = session?.config_options || []
  const modelOpt = options.find((o) => o.category === 'model' || o.id === 'model')
  const modelName = modelOpt?.options.find((o) => o.value === modelOpt.currentValue)?.name || ''

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
  }, [items, perms, state])
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
      const r = await acpApi.items(sessionId, first.id)
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
    conn.addLocalUser(client_id, text, atts, busy)
    const err = await conn.send({ type: 'send', client_id, text, attachments: atts.map((a) => a.id) })
    if (err) { conn.removeLocal(client_id); toast(err, 'error'); return false }
    return true
  }
  const setOption = async (o: ConfigOption, value: string) => {
    haptic()
    const err = await conn.send({ type: 'set_config', config_id: o.id, value })
    if (err) toast(err, 'error')
    else toast(`${o.name}: ${o.options.find((x) => x.value === value)?.name || value}`)
  }
  const setMode = async (mode_id: string) => {
    const err = await conn.send({ type: 'set_mode', mode_id })
    if (err) toast(err, 'error')
  }
  const rename = async () => {
    const t = await promptDialog({ title: 'Rename conversation', value: session?.title || '', confirm: 'Rename' })
    if (!t?.trim()) return
    try { conn.session.value = await acpApi.updateSession(sessionId, { title: t.trim() }) } catch (e) { toastError(e) }
  }
  const [creating, setCreating] = useState(false)
  const newChat = async () => {
    if (creating) return
    setCreating(true)
    try {
      const s = await acpApi.createSession(agentId)
      haptic()
      navigate({ name: 'acp-chat', agentId, sessionId: s.id }, { replace: true })
    } catch (e) { toastError(e) } finally { setCreating(false) }
  }
  const sleep = async () => {
    setOptionsOpen(false)
    try { conn.session.value = await acpApi.sleep(sessionId); toast('Disconnected') } catch (e) { toastError(e) }
  }
  const openChatImage = (el: HTMLImageElement) => {
    const all = Array.from(scroller.current?.querySelectorAll<HTMLImageElement>('.msg-assistant img') || [])
    openViewer(all.map((x) => ({ src: x.src, name: x.alt })), Math.max(0, all.indexOf(el)))
  }

  // Finished turns fold their process (thinking, tools) behind one row and show only the answer, as in the Claude chat.
  const { rows, replies } = useMemo(() => {
    const top = items.filter((it) => !(it.kind === 'user' && it.pending && it.queued))
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
  const shown = acpAvatar(agent)

  return (
    <div class="page chat-page">
      <TopBar
        left={<BackButton label="" onClick={() => back(parentOf(route.value))} />}
        right={<div class="topbar-actions">
          <button class="icon-btn" aria-label="New conversation" disabled={creating} onClick={newChat}><IconNewChat /></button>
          <button class="icon-btn" aria-label="Session controls" onClick={() => setOptionsOpen(true)}><IconMore /></button>
        </div>}>
        <button class="chat-title press" onClick={() => setOptionsOpen(true)}>
          <AvatarFor a={shown} busy={busy} size={32} />
          <span class="titles">
            <span class="t1">{session?.title || 'New conversation'}</span>
            <span class="t2">{agent?.name}{state === 'connecting' ? <> · <Spark size={11} /> connecting</> : ''}</span>
          </span>
        </button>
      </TopBar>
      {status !== 'open' && conn.loaded.value && (
        <div class="conn-banner"><span class="spinner" style={{ width: '14px', height: '14px' }} /> Reconnecting. The agent keeps working.</div>
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
              <AvatarFor a={shown} size={72} />
              <h2 class="serif">How can I help?</h2>
              <p>{agent?.info?.title || agent?.info?.name || (agent ? `${agent.host}:${agent.port}` : '')}</p>
            </div>
          )}
          {rows.map((r) => {
            const one = (it: Item) => <ItemView key={it.id} it={it} reply={replies.get(it.id)} onUserMenu={setMsgMenu} onImage={openChatImage} />
            if ('it' in r) return <div key={r.it.id} style={{ display: 'contents' }}>{one(r.it)}</div>
            const open = unfolded.has(r.fold)
            const secs = r.ms > 0 ? fmtDuration(r.ms) : ''
            return (
              <div key={'fold-' + r.fold} class={`fold ${open ? 'open' : ''}`}>
                <button class="fold-head" onClick={() => toggleFold(r.fold)} aria-expanded={open}>
                  <span>Worked{secs ? ` for ${secs}` : ''}{r.tools ? ` · ${r.tools} step${r.tools > 1 ? 's' : ''}` : ''}</span>
                  <IconChevron class="fold-chev" width={14} height={14} />
                </button>
                {open && <div class="fold-body">{r.items.map(one)}</div>}
              </div>
            )
          })}
          {perms.map((p) => <PermissionCard key={p.id} req={p} conn={conn} />)}
          {busy && !streamingText && perms.length === 0 && <Working state={state} start={conn.turnStart.value} />}
          <div style={{ height: '8px' }} />
        </div>
      </div>
      {showJump && <button class="jump-btn pop" onClick={jump} aria-label="Scroll to bottom"><IconChevronDown /></button>}
      <div class="chat-bottom">
        <QueueTray items={items} conn={conn} onEdit={(text) => setFill((f) => ({ text, n: f.n + 1 }))} />
        <Composer sid={sessionId} state={state} model={modelName} slash={(session?.commands || []).map((c) => c.name)}
          images={true} onSend={send} onInterrupt={() => conn.send({ type: 'interrupt' })}
          onOpenModel={() => setOptionsOpen(true)} disabled={status === 'closed'} fill={fill.n ? fill : undefined} />
      </div>

      <Sheet open={optionsOpen} onClose={() => setOptionsOpen(false)} title="This conversation">
        <div class="controls">
          {session?.modes && session.modes.availableModes.length > 1 && <>
            <div class="group-title" style={{ marginTop: '4px' }}>Mode</div>
            <div class="mode-list">
              {session.modes.availableModes.map((m) => (
                <button key={m.id} class={`mode-opt ${m.id === session.modes!.currentModeId ? 'on' : ''}`} onClick={() => setMode(m.id)}>{m.name}</button>
              ))}
            </div>
          </>}
          {options.map((o) => (
            <div key={o.id}>
              <div class="group-title">{o.name}</div>
              <div class="chips">
                {o.options.map((v) => (
                  <button key={v.value} class={`chip ${v.value === o.currentValue ? 'pink' : ''}`} title={v.description}
                    onClick={() => v.value !== o.currentValue && setOption(o, v.value)}>{v.name}</button>
                ))}
              </div>
            </div>
          ))}
          {!options.length && <p class="fhint">Options appear after the agent connects.</p>}
          <div class="group-title">Session</div>
          <div class="menu" style={{ padding: '4px 0 0' }}>
            <button onClick={() => { setOptionsOpen(false); rename() }}><IconEdit /> Rename</button>
            {state !== 'offline' && <button disabled={busy} onClick={sleep}><IconMoon /> Disconnect</button>}
          </div>
          {agent?.info && <div class="init-info"><span>{agent.info.title || agent.info.name}{agent.info.version ? ` ${agent.info.version}` : ''}</span><span>{agent.host}:{agent.port}</span></div>}
        </div>
      </Sheet>
      <Sheet open={selectText !== null} onClose={() => setSelectText(null)} title="Select text">
        <div class="select-text selectable">{selectText}</div>
      </Sheet>
      <Sheet open={!!msgMenu} onClose={() => setMsgMenu(null)} title="Message">
        {msgMenu && (
          <div class="menu">
            <button onClick={() => { copyText(msgMenu.text); setMsgMenu(null); toast('Copied') }}><IconCopy /> Copy text</button>
            {msgMenu.text && <button onClick={() => { setSelectText(msgMenu.text); setMsgMenu(null) }}><IconSelect /> Select text</button>}
          </div>
        )}
      </Sheet>
    </div>
  )
}

function AvatarFor({ a, size, busy }: { a: { id: string; avatar: string; order: number }; size: number; busy?: boolean }) {
  // Uploaded avatars of ACP agents are served by the ACP routes, not the Claude ones.
  if (a.avatar === 'file') return (
    <span class={`avatar ${busy ? 'busy' : ''}`} style={{ width: `${size}px`, height: `${size}px` }}>
      <img src={acpApi.avatarUrl(a)} alt="" loading="lazy" decoding="async" />
    </span>
  )
  return <Avatar agent={a} size={size} busy={busy} />
}
export { AvatarFor as AcpAvatar }

function Working({ state, start }: { state: string; start: number | null }) {
  const [now, setNow] = useState(Date.now())
  const t0 = useRef(Date.now())
  useEffect(() => { const a = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(a) }, [])
  const secs = Math.max(0, Math.floor((now - (start ?? t0.current)) / 1000))
  return (
    <div class="working fade-in" aria-live="polite">
      <Spark size={18} />
      <span class="working-text">
        <span class="shimmer-text">{state === 'interrupting' ? 'Stopping' : state === 'connecting' ? 'Connecting' : 'Working'}...</span>
        {secs > 1 && <span class="working-meta"> ({secs >= 60 ? `${Math.floor(secs / 60)}m ${secs % 60}s` : `${secs}s`})</span>}
      </span>
    </div>
  )
}

/** Messages sent while the agent works; ACP sends them in order once the turn ends. */
function QueueTray({ items, conn, onEdit }: { items: Item[]; conn: AcpConn; onEdit: (text: string) => void }) {
  const queued = items.filter((x): x is UserItem => x.kind === 'user' && x.pending && !!x.queued)
  if (!queued.length) return null
  const edit = async (u: UserItem) => {
    const err = await conn.send({ type: 'cancel_queued', id: u.id })
    if (err) return toast('Already sent', 'error')
    onEdit(u.text)
  }
  return (
    <div class="queue-tray">
      {queued.map((u) => (
        <div key={u.id} class="queue-row pop">
          <span class="queue-label">Queued</span>
          <span class="queue-text">{u.text || `${u.attachments.length} file${u.attachments.length > 1 ? 's' : ''}`}</span>
          <button class="icon-btn" aria-label="Edit queued message" disabled={(u as any)._local} onClick={() => edit(u)}><IconEdit width={16} height={16} /></button>
        </div>
      ))}
    </div>
  )
}

const ItemView = memo(function ItemView({ it, reply, onUserMenu, onImage }: {
  it: Item; reply?: string; onUserMenu: (u: UserItem) => void; onImage: (el: HTMLImageElement) => void
}) {
  switch (it.kind) {
    case 'user': return <UserBubble it={it} onMenu={onUserMenu} />
    case 'text': return <AssistantText it={it} onImage={onImage} />
    case 'thinking': return <Thinking it={it} />
    case 'tool': return <ToolCard it={it as AcpToolItem} />
    case 'notice': return <div class={`notice ${it.level}`}>{it.text}</div>
    case 'result': {
      const r = it as any
      const stopped = r.stop_reason === 'cancelled', lost = r.stop_reason === 'disconnected'
      return (
        <div class={`turn-end ${lost ? 'err' : ''}`}>
          {stopped ? 'Stopped' : lost ? 'Connection lost' : r.stop_reason && r.stop_reason !== 'end_turn' ? `Ended: ${r.stop_reason.replace(/_/g, ' ')}` : 'Done'}
          {r.duration_ms ? ` in ${fmtDuration(r.duration_ms)}` : ''}
          {reply && <CopyReply text={reply} />}
        </div>
      )
    }
  }
  if ((it as any).kind === 'plan') return <Plan it={it as any} />
  return null
})

function Plan({ it }: { it: { entries: { content: string; status: string }[] } }) {
  const entries = it.entries || []
  const done = entries.filter((t) => t.status === 'completed').length
  return (
    <div class="todo-card">
      <div class="todo-head">
        <span>Plan</span>
        <span class="todo-count">{done}/{entries.length}</span>
        <span class="todo-bar"><span style={{ width: `${entries.length ? (done / entries.length) * 100 : 0}%` }} /></span>
      </div>
      <ul>
        {entries.map((t, k) => (
          <li key={k} class={t.status}>
            <span class="todo-box">{t.status === 'completed' ? <IconCheck width={12} height={12} /> : t.status === 'in_progress' ? <Spark size={12} /> : null}</span>
            <span class="todo-text">{t.content}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

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
  const files = it.attachments?.filter((a) => !a.is_image) || []
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
      {files.length > 0 && (
        <div class="msg-files">
          {files.map((a) => <a class="file-pill" href={a.url} target="_blank" rel="noopener"><IconTerminal width={14} height={14} /> {a.name} <span>{fmtBytes(a.size)}</span></a>)}
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
