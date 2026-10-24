// Chat page: transcript, live streaming, pending request cards, controls sheet, composer.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks'
import { memo } from 'preact/compat'
import { api } from '../lib/api'
import { agents, meta, toast, toastError } from '../lib/store'
import { back, navigate, parentOf, route } from '../lib/router'
import { Avatar, Spark } from '../components/crab'
import { BackButton, Sheet, Switch, TopBar, confirmDialog, promptDialog } from '../components/ui'
import { IconBrain, IconCheck, IconChevron, IconChevronDown, IconCopy, IconFork, IconMore, IconRewind, IconEdit, IconSelect, IconNewChat, IconTerminal, IconLayers, IconSteer, IconMap } from '../components/icons'
import { ChatConn } from './conn'
import { Composer } from './Composer'
import { BtwSheet } from './Btw'
import { TaskTray } from './Tasks'
import { SubagentPanel, subagentView } from './Subagent'
import { PermissionCard } from './cards'
import { ToolCard } from './tools'
import { mathVersion, renderMarkdown, renderStreaming, setCodeCards } from './markdown'
import { genuiHost, splitGenui } from './GenUI'
import { GenWidget } from './Widgets'
import { ArtifactsSheet, codeView } from './Artifacts'
import { clearFade, fadeTail, makeFollower, newFade, unwrapFade } from './fade'

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches
import { ModelPicker } from '../components/ModelPicker'
import { EffortSlider } from '../components/EffortSlider'
import { openViewer } from '../components/ImageViewer'
import { MODE_LABELS, copyText, fmtBytes, fmtCost, fmtDuration, fmtTokens, haptic, shortPath, uid } from '../lib/util'
import type { Activity, Agent, Attachment, Item, TextItem, ThinkingItem, ToolItem, UserItem } from '../lib/types'

// Claude Code's completion verbs ("Cooked for 1m 3s"), picked stably per fold.
const PAST = ['Baked', 'Brewed', 'Churned', 'Cogitated', 'Cooked', 'Crunched', 'Sautéed', 'Worked']
const pastVerb = (id: string) => { let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) | 0; return PAST[Math.abs(h) % PAST.length] }

// Claude Code's spinner verbs (CLI 2.1.293).
const VERBS = ('Accomplishing Actioning Actualizing Architecting Baking Beaming Beboppin\' Befuddling Billowing Blanching Bloviating ' +
  'Boogieing Boondoggling Booping Bootstrapping Brewing Bunning Burrowing Calculating Canoodling Caramelizing Cascading Catapulting ' +
  'Cerebrating Channeling Choreographing Churning Clauding Coalescing Cogitating Combobulating Composing Computing Concocting ' +
  'Considering Contemplating Cooking Crafting Creating Crunching Crystallizing Cultivating Deciphering Deliberating Determining ' +
  'Dilly-dallying Discombobulating Doing Doodling Drizzling Ebbing Effecting Elucidating Embellishing Enchanting Envisioning ' +
  'Fermenting Fiddle-faddling Finagling Flambéing Flibbertigibbeting Flowing Flummoxing Fluttering Forging Forming Frolicking ' +
  'Frosting Gallivanting Galloping Garnishing Generating Gesticulating Germinating Gitifying Grooving Gusting Harmonizing Hashing ' +
  'Hatching Herding Honking Hullaballooing Hyperspacing Ideating Imagining Improvising Incubating Inferring Infusing Ionizing ' +
  'Jitterbugging Julienning Kerfuffling Kneading Leavening Levitating Lollygagging Manifesting Marinating Meandering Metamorphosing ' +
  'Misting Moonwalking Moseying Mulling Mustering Musing Nebulizing Nesting Newspapering Noodling Nucleating Onioning Orbiting ' +
  'Orchestrating Osmosing Perambulating Percolating Perusing Philosophizing Photosynthesizing Polishing Pollinating Pondering ' +
  'Pontificating Pouncing Precipitating Prestidigitating Processing Proofing Propagating Puttering Puzzling Quantumizing ' +
  'Razzle-dazzling Razzmatazzing Recombobulating Reticulating Roosting Ruminating Sautéing Scampering Schlepping Scurrying Seasoning ' +
  'Shenaniganing Shimmying Simmering Skedaddling Sketching Slithering Smooshing Sock-hopping Spelunking Spinning Sprouting Stewing ' +
  'Sublimating Swirling Swooping Symbioting Synthesizing Tempering Thinking Thundering Tinkering Tomfoolering Topsy-turvying ' +
  'Transfiguring Transmogrifying Transmuting Twisting Undulating Unfurling Unraveling Vibing Waddling Wandering Warping ' +
  'Whatchamacalliting Whirlpooling Whirring Whisking Wibbling Working Wrangling Zesting Zigzagging').split(' ')

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
  const [artifacts, setArtifacts] = useState(false)
  const artifactsOn = meta.value?.defaults.artifacts ?? true
  setCodeCards(artifactsOn)
  const [msgMenu, setMsgMenu] = useState<UserItem | null>(null)
  const [selectText, setSelectText] = useState<string | null>(null)
  const [editing, setEditing] = useState<UserItem | null>(null)
  const [modelOpen, setModelOpen] = useState(false)
  // Model sheet edits are drafts; they are sent only when the sheet closes.
  const [draft, setDraft] = useState<{ model?: string; effort?: string }>({})
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

  const applyEffort = async (e: string) => {
    const err = await conn.send({ type: 'set_effort', effort: e })
    if (err) toast(err, 'error'); else toast(`Effort: ${e}`)
  }

  const items = conn.items.value
  const state = conn.state.value
  const session = conn.session.value
  const perms = conn.perms.value
  const init = conn.init.value
  const busy = state === 'running' || state === 'interrupting'
  const steered = useRef(new Set<string>())
  const [btw, setBtw] = useState({ open: false, q: '', n: 0 })
  const [fill, setFill] = useState({ text: '', n: 0 })
  const mode = session?.overrides?.permission_mode || init?.permission_mode || (agent?.effective?.permission_mode ?? agent?.permission_mode) || 'default'
  const agentModel = agent?.effective?.model || meta.value?.defaults.model || ''
  const model = session?.overrides?.model || init?.model || (agent?.effective?.model ?? agent?.model) || meta.value?.defaults.model || ''
  const effort = session?.overrides?.effort || (agent?.effective?.effort ?? agent?.effort) || meta.value?.defaults.effort || ''

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
  const follower = useMemo(() => makeFollower(() => scroller.current), [])
  const firstPaint = useRef(true)
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el || !stick.current) return
    // Glide while content streams in; jump on first paint or when far away.
    if (firstPaint.current || reduceMotion || el.scrollHeight - el.scrollTop - el.clientHeight > 1500) { follower.jump(); firstPaint.current = false }
    else follower.follow()
  }, [items, perms, state])
  useEffect(() => {
    // Images, file previews and math finish loading after the first paint and grow the content;
    // follow them down while pinned to the bottom.
    const el = scroller.current, inner = el?.firstElementChild
    if (!el || !inner || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => { if (stick.current) follower.follow() })
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

  // Chat map: scroll to an item; folded or unrendered items fall back to the closest earlier one on screen.
  const jumpTo = (id: string) => {
    const el = scroller.current
    if (!el) return
    const idx = items.findIndex((x) => x.id === id)
    for (let i = idx; i >= 0; i--) {
      const box = el.querySelector(`[data-item="${CSS.escape(items[i].id)}"]`)?.firstElementChild as HTMLElement | null
      if (!box) continue
      stick.current = false
      markUser()
      setTimeout(() => {
        box.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' })
        box.classList.add('map-flash')
        setTimeout(() => box.classList.remove('map-flash'), 1200)
      }, 250)
      return
    }
  }

  const jump = () => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    stick.current = true
  }

  const send = async (text: string, atts: Attachment[], steerNow: boolean) => {
    const client_id = uid()
    // Only messages sent into a running turn are steers; the rest start a turn and need no "Queued" tag.
    if (busy && !steerNow) steered.current.add(client_id)
    stick.current = true
    conn.addLocalUser(client_id, text, atts, busy)
    if (steerNow && busy) await conn.send({ type: 'interrupt' })
    const err = await conn.send({ type: 'send', client_id, text, attachments: atts.map((a) => a.id) })
    if (err) {
      conn.removeLocal(client_id)
      toast(err, 'error')
      return false
    }
    return true
  }
  genuiHost.send = (text) => { send(text, [], false) }
  useEffect(() => () => { genuiHost.send = null }, [])

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

  const openModel = () => { setDraft({}); setModelOpen(true) }
  const closeModel = (d = draft) => {
    setModelOpen(false)
    setDraft({})
    if (d.model !== undefined && d.model !== (session?.overrides?.model || agentModel)) applyModel(d.model)
    if (d.effort !== undefined && d.effort !== effort) applyEffort(d.effort)
  }

  const applyModel = async (m: string) => {
    const err = await conn.send({ type: 'set_model', model: m })
    if (err) toast(err, 'error'); else toast(`Model: ${m}`)
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
      const s = session?.cwd ? await api.createTempSession(session.cwd) : await api.createSession(agentId)
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
  const { top, children, replies, rows } = useMemo(() => {
    const children = new Map<string, Item[]>()
    const top: Item[] = []
    for (const it of items) {
      // Messages waiting in the CLI queue live in the queue tray until Claude takes them in.
      if (it.kind === 'user' && it.pending && it.queued) continue
      if (it.parent_tool_use_id) {
        const l = children.get(it.parent_tool_use_id) || []
        l.push(it)
        children.set(it.parent_tool_use_id, l)
      } else top.push(it)
    }
    // The text of each turn's replies, keyed by its result item, for the copy button.
    // History loaded from disk has no result items, so those turns get it on their last text item.
    const replies = new Map<string, string>()
    let buf: string[] = []
    let lastText: string | null = null
    const flush = () => { if (buf.length && lastText) replies.set(lastText, buf.join('\n\n')); buf = []; lastText = null }
    for (const it of top) {
      if (it.kind === 'user') flush()
      else if (it.kind === 'text' && it.text.trim()) { buf.push(it.text.trim()); lastText = it.id }
      else if (it.kind === 'result') { if (buf.length) replies.set(it.id, buf.join('\n\n')); buf = []; lastText = null }
    }
    if (!busy) flush()
    // Finished turns fold their process (thinking, tools, interim text) behind one row and show only the final answer.
    type Row = { it: Item } | { fold: string; items: Item[]; tools: number; ms: number }
    const rows: Row[] = []
    // A steer (sent into a running turn) splits segments but not the turn: the segments above it stay live until the turn ends.
    // After a reload the steered set is empty, so a user message that lands right after a tool or thinking item counts as a steer too.
    const turns: Item[][] = [[]]
    const group: number[] = [0]
    let g = 0
    for (const it of top) {
      if (it.kind === 'user') {
        const prev = turns[turns.length - 1].at(-1)
        const steer = (!!it.client_id && steered.current.has(it.client_id)) || prev?.kind === 'tool' || prev?.kind === 'thinking'
        if (!steer) g++
        turns.push([it], []); group.push(g, g)
      } else turns[turns.length - 1].push(it)
    }
    turns.forEach((turn, ti) => {
      const folded = (group[ti] !== g || !busy) && !(turn[0]?.kind === 'user')
      if (!folded) { for (const it of turn) rows.push({ it }); return }
      // Each run of thinking/tool items folds on its own; text between them stays visible.
      let run: Item[] = []
      const close = (next?: Item) => {
        if (!run.length) return
        const t0 = Date.parse(run[0].ts || ''), t1 = Date.parse(next?.ts || run.at(-1)!.ts || '')
        rows.push({ fold: run[0].id, items: run, tools: run.filter((x) => x.kind === 'tool').length, ms: t1 - t0 })
        run = []
      }
      for (const it of turn) {
        // Blank text (it renders nothing) must not split a run, or every tool call gets its own fold.
        if (it.kind === 'text' && !it.text.trim() && !it.streaming) { if (run.length) run.push(it); continue }
        if (it.kind === 'tool' || it.kind === 'thinking') run.push(it)
        else { close(it); rows.push({ it }) }
      }
      close()
    })
    return { top, children, replies, rows }
  }, [items, busy])
  const [unfolded, setUnfolded] = useState<Set<string>>(new Set())
  const toggleFold = (id: string) => {
    // Keep the toggle row where it is; following the bottom would yank the expanded content away.
    stick.current = false
    markUser()
    setUnfolded((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  useEffect(() => () => { subagentView.value = null }, [sessionId])
  const watchedTask = subagentView.value ? conn.tasks.value.find((t) => t.tool_use_id === subagentView.value) : undefined
  // The Agent call can sit before the loaded page (e.g. after coming back to a long chat); stand in a stub from its task.
  const watched = !subagentView.value ? undefined
    : (items.find((x) => x.kind === 'tool' && x.id === subagentView.value) as ToolItem | undefined)
      || (watchedTask ? { kind: 'tool', id: watchedTask.tool_use_id!, tool_use_id: watchedTask.tool_use_id!, name: 'Agent', streaming: false, result: null,
        input: { description: watchedTask.description, subagent_type: watchedTask.subagent_type } } as unknown as ToolItem : undefined)

  const lastTop = top[top.length - 1]
  const lastThinking = !!lastTop && lastTop.kind === 'thinking' && (lastTop as ThinkingItem).streaming
  // Only show the loading row when a sent message is waiting on the CLI, not while it just warms up.
  const waiting = top.some((it) => it.kind === 'user' && it.pending)
  const lastIsStreamingText = top.length > 0 && top[top.length - 1].kind === 'text' && (top[top.length - 1] as TextItem).streaming
  // Like Claude Code, an in-progress todo's activeForm replaces the spinner verb.
  const lastTodo = [...top].reverse().find((x) => x.kind === 'tool' && x.name === 'TodoWrite') as ToolItem | undefined
  const todoForm: string = (lastTodo?.input?.todos || []).find((t: any) => t.status === 'in_progress')?.activeForm || ''
  const background = conn.tasks.value.filter((t) => t.kind !== 'cron' && t.status === 'running').length
  const ctx = session?.context
  const status = conn.conn.value

  return (
    <div class="page chat-page">
      <TopBar
        left={<BackButton label="" onClick={() => back(parentOf(route.value))} />}
        right={<div class="topbar-actions">
          <button class="icon-btn" aria-label="Artifacts and chat map" onClick={() => setArtifacts(true)}>{artifactsOn ? <IconLayers /> : <IconMap />}</button>
          <button class="icon-btn" aria-label="New conversation" disabled={creating} onClick={newChat}><IconNewChat /></button>
          <button class="icon-btn" aria-label="Session controls" onClick={() => setControls(true)}><IconMore /></button>
        </div>}>
        <button class="chat-title press" onClick={() => setControls(true)}>
          {agent && <Avatar agent={agent} size={32} busy={busy} />}
          <span class="titles">
            <span class="t1">{session?.title || 'New conversation'}</span>
            <span class="t2">
              {session?.cwd ? shortPath(session.cwd) : agent?.name}
              {state === 'queued' ? ' · waiting for a free slot' : state === 'starting' ? <> · <Spark size={11} /> loading</> : ''}
              {ctx ? ` · ${Math.round(ctx.percent)}% context` : ''}
            </span>
          </span>
        </button>
      </TopBar>
      {status !== 'open' && conn.loaded.value && (
        <div class="conn-banner"><span class="spinner" style={{ width: '14px', height: '14px' }} /> Reconnecting. Claude keeps working on the server.</div>
      )}

      {watched && <SubagentPanel conn={conn} tool={watched} items={children.get(watched.id) || []}
        task={watchedTask} />}
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
              <p>{session?.cwd || agent?.cwd}</p>
            </div>
          )}
          {rows.map((r) => {
            const one = (it: Item) => <ItemView key={it.id} it={it} sid={sessionId} children={it.kind === 'tool' ? children.get(it.id) : undefined}
              reply={replies.get(it.id)} onUserMenu={setMsgMenu} onImage={openChatImage}
              steering={busy && it.kind === 'user' && !!it.client_id && steered.current.has(it.client_id)} />
            if ('it' in r) return <div key={r.it.id} data-item={r.it.id} style={{ display: 'contents' }}>{one(r.it)}</div>
            const open = unfolded.has(r.fold)
            const secs = r.ms > 0 ? fmtDuration(r.ms) : ''
            return (
              <div key={'fold-' + r.fold} class={`fold ${open ? 'open' : ''}`}>
                <button class="fold-head" onClick={() => toggleFold(r.fold)} aria-expanded={open}>
                  <span>{pastVerb(r.fold)}{secs ? ` for ${secs}` : ''}{r.tools ? ` · ${r.tools} step${r.tools > 1 ? 's' : ''}` : ''}</span>
                  <IconChevron class="fold-chev" width={14} height={14} />
                </button>
                {open && <div class="fold-body">{r.items.map(one)}</div>}
              </div>
            )
          })}
          {perms.map((p) => <PermissionCard key={p.id} req={p} conn={conn} />)}
          {busy && !lastIsStreamingText && perms.length === 0 && <Working state={state} start={conn.turnStart.value} activity={conn.activity.value} effort={effort} thinking={lastThinking} thinkingAt={lastThinking ? (lastTop as ThinkingItem).started_at : undefined} todo={todoForm} background={background} />}
          {state === 'queued' && (
            <div class="working"><span class="spinner" /> Waiting for a free slot{conn.queuePos.value ? ` (position ${conn.queuePos.value})` : ''}</div>
          )}
          {state === 'starting' && waiting && <div class="working"><Spark size={18} /> <span class="shimmer-text">Loading Claude</span></div>}
          <div style={{ height: '8px' }} />
        </div>
      </div>

      {showJump && (
        <button class="jump-btn pop" onClick={jump} aria-label="Scroll to bottom"><IconChevronDown /></button>
      )}

      <div class="chat-bottom">
        <TaskTray conn={conn} />
        <QueueTray items={items} conn={conn} onEdit={(text) => setFill((f) => ({ text, n: f.n + 1 }))} />
        <Composer sid={sessionId} state={state} mode={mode} model={model} slash={init?.slash_commands || []}
          onSend={send} onInterrupt={() => conn.send({ type: 'interrupt' })} onMode={setMode}
          onOpenModel={openModel} disabled={status === 'closed'} fill={fill.n ? fill : undefined}
          onBtw={(q) => setBtw((b) => ({ open: true, q, n: b.n + 1 }))} />
      </div>
      <BtwSheet sid={sessionId} model={model} open={btw.open} question={btw.q} nonce={btw.n} onClose={() => setBtw((b) => ({ ...b, open: false }))} />

      <ControlsSheet open={controls} onClose={() => setControls(false)} conn={conn} agent={agent} mode={mode}
        onMode={setMode} onModel={applyModel} onRename={rename} onFork={() => { setControls(false); forkAt(null) }} />

      {<ArtifactsSheet open={artifacts} onClose={() => setArtifacts(false)} sid={sessionId} items={items} onJump={jumpTo} />}
      <Sheet open={modelOpen} onClose={() => closeModel()} title="Model">
        <ModelPicker value={draft.model ?? (session?.overrides?.model || agentModel)} onChange={(m) => closeModel({ ...draft, model: m })} />
        {init?.model && <div class="fhint" style={{ margin: '10px 4px 0' }}>Running: {init.model}</div>}
        <div class="group-title">Effort</div>
        <EffortSlider value={draft.effort ?? effort} onChange={(e) => setDraft({ ...draft, effort: e })} />
        <div class="model-sheet-mode">
          <span class={`mode-swatch mode-${mode}`} /> {MODE_LABELS[mode] || mode}
          <button class="btn small ghost" onClick={() => { closeModel(); setControls(true) }}>More controls</button>
        </div>
      </Sheet>

      <Sheet open={selectText !== null} onClose={() => setSelectText(null)} title="Select text">
        <div class="select-text selectable">{selectText}</div>
      </Sheet>

      <EditSheet item={editing} sid={sessionId} canRewindFiles={!!agent?.enable_file_checkpointing}
        onClose={() => setEditing(null)} onSubmit={resend} />

      <Sheet open={!!msgMenu} onClose={() => setMsgMenu(null)} title="Message">
        {msgMenu && (
          <div class="menu">
            <button onClick={() => { copyText(msgMenu.text); setMsgMenu(null); toast('Copied') }}><IconCopy /> Copy text</button>
            {msgMenu.text && <button onClick={() => { setSelectText(msgMenu.text); setMsgMenu(null) }}><IconSelect /> Select text</button>}
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

// Set when the user presses Compact, so the indicator can tell manual from auto compaction.
const fmtSecs = (s: number) => s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.max(0, s)}s`

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

function Working({ state, start, activity, effort, thinking, thinkingAt, todo, background }: {
  state: string; start: number | null; activity: Activity | null; effort: string; thinking: boolean; thinkingAt?: number; todo: string; background: number
}) {
  // Like the CLI, the verb is picked once per turn and does not rotate.
  const [verb] = useState(() => VERBS[Math.floor(Math.random() * VERBS.length)])
  const [now, setNow] = useState(Date.now())
  const t0 = useRef(Date.now())
  const thinkStart = useRef<number | null>(null)
  useEffect(() => {
    const a = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(a)
  }, [])
  if (thinking) { if (thinkStart.current === null) thinkStart.current = Math.min(thinkingAt ?? Date.now(), Date.now()) } else thinkStart.current = null
  // The server times the turn, so leaving and reopening the chat keeps counting.
  const secs = Math.max(0, Math.floor((now - (start ?? t0.current)) / 1000))
  if (activity?.kind === 'compacting') {
    const auto = !activity.manual
    return (
      <div class="working compacting fade-in" aria-live="polite">
        <Spark size={18} />
        <span class="working-text">
          <span class="shimmer-text">{auto ? 'Auto-compacting conversation' : 'Compacting conversation'}...</span>
          <span class="working-meta"> ({fmtSecs(Math.floor((now - Date.parse(activity.at)) / 1000))})</span>
          <span class="compact-bar" role="progressbar" aria-label="Compacting"><span /></span>
        </span>
      </div>
    )
  }
  const note = activityNote(activity, now)
  const tokens = activity?.kind === 'thinking_tokens' && activity.estimated_tokens ? activity.estimated_tokens : 0
  const parts: string[] = []
  if (secs > 1) parts.push(secs >= 60 ? `${Math.floor(secs / 60)}m ${secs % 60}s` : `${secs}s`)
  if (tokens) parts.push(`${fmtTokens(tokens)} tokens`)
  if (thinking) parts.push(`${thinkingPhrase(now - (thinkStart.current ?? now))}${effort ? ` with ${effort} effort` : ''}`)
  if (background) parts.push(`${background} in background`)
  return (
    <div class="working fade-in" aria-live="polite">
      <Spark size={18} />
      <span class="working-text">
        <span class="shimmer-text">{state === 'interrupting' ? 'Stopping' : todo || verb}...</span>
        {parts.length > 0 && <span class="working-meta"> ({parts.join(' · ')})</span>}
        {note && <span class={`working-note ${note.warn ? 'warn' : ''}`}>{note.text}</span>}
      </span>
    </div>
  )
}

/** Messages sent while Claude works wait here until the CLI takes them in at its next step. */
function QueueTray({ items, conn, onEdit }: { items: Item[]; conn: ChatConn; onEdit: (text: string) => void }) {
  const queued = items.filter((x): x is UserItem => x.kind === 'user' && x.pending && !!x.queued && !x.parent_tool_use_id)
  if (!queued.length) return null
  const local = (u: UserItem) => (u as any)._local
  const edit = async (u: UserItem) => {
    const err = await conn.send({ type: 'cancel_queued', id: u.id })
    if (err) return toast('Claude already read this message', 'error')
    onEdit(u.text)
  }
  const now = async (u: UserItem) => {
    haptic()
    const err = await conn.send({ type: 'send_now', id: u.id })
    if (err) toast(err, 'error')
  }
  return (
    <div class="queue-tray">
      {queued.map((u) => (
        <div key={u.id} class="queue-row pop">
          <span class="queue-label">Queued</span>
          <span class="queue-text">{u.text || (u.attachments.length ? `${u.attachments.length} file${u.attachments.length > 1 ? 's' : ''}` : '')}</span>
          <button class="icon-btn" aria-label="Edit queued message" title="Edit" disabled={local(u)} onClick={() => edit(u)}><IconEdit width={16} height={16} /></button>
          <button class="icon-btn steer-btn" aria-label="Interrupt and send now" title="Interrupt and send now" disabled={local(u)} onClick={() => now(u)}><IconSteer /></button>
        </div>
      ))}
    </div>
  )
}

const ItemView = memo(function ItemView({ it, sid, children, reply, onUserMenu, onImage, steering }: {
  it: Item; sid: string; steering?: boolean; children?: Item[]; reply?: string; onUserMenu: (u: UserItem) => void; onImage: (el: HTMLImageElement) => void
}) {
  switch (it.kind) {
    case 'user': return <UserBubble it={it} onMenu={onUserMenu} steering={steering} />
    case 'text': return reply ? (
      <>
        <AssistantText it={it} sid={sid} onImage={onImage} />
        <div class="turn-end bare"><CopyReply text={reply} /></div>
      </>
    ) : <AssistantText it={it} sid={sid} onImage={onImage} />
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

function UserBubble({ it, onMenu, steering }: { it: UserItem; onMenu: (u: UserItem) => void; steering?: boolean }) {
  const images = it.attachments?.filter((a) => a.is_image) || []
  const files = it.attachments?.filter((a) => !a.is_image) || []
  // Long press (right click on desktop) opens the message actions. The bubble is not selectable;
  // "Select text" in the menu shows the text in a selectable sheet.
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
      {it.text && <div class="bubble" onContextMenu={(e) => { e.preventDefault(); onMenu(it) }}
        onTouchStart={startPress} onTouchMove={movePress} onTouchEnd={endPress} onTouchCancel={endPress}>{it.text}</div>}
      {!it.text && <button type="button" class="msg-actions-btn" onClick={() => onMenu(it)} aria-label="Message actions"><IconMore width={18} height={18} /></button>}
      {it.pending && steering && <div class="pending-tag">Queued, Claude reads it at the next step</div>}
    </div>
  )
}

function AssistantText({ it, sid, onImage }: { it: TextItem; sid: string; onImage: (el: HTMLImageElement) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const fade = useRef(newFade())
  void mathVersion.value
  const segs = splitGenui(it.text)
  useLayoutEffect(() => {
    if (!it.streaming || reduceMotion || !ref.current) { fade.current = newFade(); if (ref.current) clearFade(ref.current); return }
    const el = ref.current
    const last = el.classList.contains('md') ? el : el.lastElementChild
    if (last instanceof HTMLElement && last.classList.contains('md')) fadeTail(last, fade.current)
    else fade.current = newFade()
  })
  const onAnimEnd = (e: AnimationEvent) => unwrapFade(e.target as Element)
  const onClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement
    if (target.tagName === 'IMG' && target.hasAttribute('data-view')) { e.preventDefault(); onImage(target as HTMLImageElement); return }
    const btn = (e.target as HTMLElement).closest('[data-copy]') as HTMLElement | null
    const card = target.closest('[data-card]') as HTMLElement | null
    if (card && !btn) {
      codeView.value = { lang: card.dataset.lang === 'code' ? '' : card.dataset.lang || '', code: card.querySelector('code')?.textContent || '' }
      return
    }
    if (!btn) return
    const code = btn.closest('.codeblock')?.querySelector('code')?.textContent || ''
    copyText(code).then(() => {
      btn.textContent = 'Copied'
      setTimeout(() => { btn.textContent = 'Copy' }, 1400)
    })
  }
  const md = (text: string, last: boolean) => it.streaming && last ? renderStreaming(text, sid) : renderMarkdown(text, sid)
  if (segs.length === 1 && segs[0].kind === 'md') return (
    <div class={`msg-assistant md ${it.streaming ? 'streaming' : ''}`} ref={ref} onClick={onClick} onAnimationEnd={onAnimEnd}
      dangerouslySetInnerHTML={{ __html: md(it.text, true) }} />
  )
  return (
    <div class={`msg-assistant ${it.streaming ? 'streaming' : ''}`} ref={ref} onClick={onClick} onAnimationEnd={onAnimEnd}>
      {segs.map((g, i) => g.kind === 'md'
        ? <div key={i} class="md" dangerouslySetInnerHTML={{ __html: md(g.text, i === segs.length - 1) }} />
        : <GenWidget key={i} code={g.code} done={g.done} />)}
    </div>
  )
}

function Thinking({ it }: { it: ThinkingItem }) {
  const [open, setOpen] = useState(false)
  if (!it.text && !it.streaming) return null
  // Claude Code echoes "thought for Ns" once thinking ends; history from disk has no timing.
  const secs = Math.round((it.duration_ms || 0) / 1000)
  const label = it.streaming ? 'Thinking' : secs > 0 ? `Thought for ${secs}s` : 'Thought process'
  return (
    <div class={`thinking ${open ? 'open' : ''} ${it.streaming ? 'streaming' : ''}`}>
      <button class="thinking-head" onClick={() => setOpen(!open)}>
        <IconBrain width={15} height={15} />
        <span class={it.streaming ? 'shimmer-text' : ''}>{label}</span>
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
  const agentModel = agent?.effective?.model || meta.value?.defaults.model || ''
  useEffect(() => { if (open) setModel(session?.overrides?.model || agentModel) }, [open])
  const effort = session?.overrides?.effort || agent?.effective?.effort || meta.value?.defaults.effort || ''
  const modes = meta.value?.permission_modes || Object.keys(MODE_LABELS)
  const ctx = session?.context

  // Model and effort are drafts here too; they are sent when the sheet closes.
  const [draftEffort, setDraftEffort] = useState<string | null>(null)
  useEffect(() => { if (open) setDraftEffort(null) }, [open])
  const close = () => {
    onClose()
    if (model && model !== (session?.overrides?.model || agentModel)) onModel(model)
    if (draftEffort !== null && draftEffort !== effort) applyEffort(draftEffort)
  }
  const applyEffort = async (e: string) => {
    const err = await conn.send({ type: 'set_effort', effort: e })
    if (err) toast(err, 'error'); else toast(`Effort: ${e}`)
  }

  return (
    <Sheet open={open} onClose={close} title="This conversation">
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
        <ModelPicker value={model} onChange={setModel} />
        {init?.model && <div class="fhint" style={{ margin: '6px 4px 0' }}>Running: {init.model}</div>}

        <div class="group-title">Effort</div>
        <EffortSlider value={draftEffort ?? effort} onChange={setDraftEffort} />
        <div class="fhint" style={{ margin: '6px 4px 0' }}>Applies when this sheet closes, from the next message.</div>

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
          <button onClick={() => { close(); onRename() }}><IconEdit /> Rename</button>
          <button onClick={onFork}><IconFork /> Fork conversation</button>
          <button disabled={!session?.sdk_session_id} onClick={async () => {
            close()
            const err = await conn.send({ type: 'send', client_id: crypto.randomUUID(), text: '/compact', attachments: [] })
            if (err) toast(err, 'error')
          }}><IconLayers /> Compact context</button>
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
