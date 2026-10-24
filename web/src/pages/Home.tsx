import { useEffect, useRef, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { agents, agentsVersion, agentLive, liveSessions, sessionsVersion, meta, toast, toastError } from '../lib/store'
import { TEMP_AGENT, navigate } from '../lib/router'
import { sessionCache } from './AgentPage'
import { Avatar, Crab, Spark } from '../components/crab'
import { IconArrowUp, IconChat, IconEdit, IconFolder, IconGrip, IconMoon, IconPlus, IconSettings, IconSort, IconTag, IconTrash } from '../components/icons'
import { DirPicker } from '../components/DirPicker'
import { Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../components/ui'
import { haptic, relTime, shortPath } from '../lib/util'
import type { Agent, Session } from '../lib/types'

// Which group Home opens on (per device). Absent = All.
const START_KEY = 'home-start'
const START_LAST = '\u0000last', START_UNGROUPED = '\u0000ungrouped'
// The filter picked in this page load, so coming back from an agent keeps it instead of re-applying START_KEY.
let sessionFilter: string | null | undefined
function initialFilter(): string | null {
  if (sessionFilter !== undefined) return sessionFilter
  const start = localStorage.getItem(START_KEY)
  if (start === null) return null
  return start === START_LAST ? localStorage.getItem('home-group') : start === START_UNGROUPED ? '' : start
}

// Groups survive remounts (and reloads) so Home's first frame already has its sections; otherwise
// going back flashes the flat ungrouped grid until /api/groups answers.
let groupsCache: string[] = (() => { try { return JSON.parse(localStorage.getItem('home-groups') || '[]') } catch { return [] } })()

const painted = () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 30))))

function greeting() {
  const h = new Date().getHours()
  if (h < 5) return 'Up late'
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

export function Home() {
  const { scrolled, onScroll, ref: scrollRef } = useScrolled()
  const [loading, setLoading] = useState(agents.value === null)
  const [sorting, setSorting] = useState(false)
  const [order, setOrder] = useState<Agent[]>([])
  const [saving, setSaving] = useState(false)
  const [groups, setGroups] = useState<string[]>(groupsCache)
  const [filter, setFilter] = useState<string | null>(initialFilter)
  const [managing, setManaging] = useState(false)

  useEffect(() => {
    api.agents().then((a) => { agents.value = a }).catch(toastError).finally(() => setLoading(false))
    api.groups().then((g) => { groupsCache = g.groups; localStorage.setItem('home-groups', JSON.stringify(g.groups)); setGroups(g.groups) }).catch(() => {})
  }, [agentsVersion.value])

  // Re-read the live map so cards update as sessions change state.
  void liveSessions.value
  const list = agents.value || []
  const pick = (g: string | null) => {
    setFilter(g)
    sessionFilter = g
    if (g === null) localStorage.removeItem('home-group'); else localStorage.setItem('home-group', g)
  }
  // A stale filter (group deleted elsewhere) falls back to All.
  const active = filter !== null && (filter === '' || groups.includes(filter)) ? filter : null
  const ungrouped = list.filter((a) => !a.group || !groups.includes(a.group))
  // All: one section per group in order, ungrouped last. A single filter: one flat grid.
  const sections: { title: string; items: Agent[] }[] = active === null
    ? (groups.length
      ? [...groups.map((g) => ({ title: g, items: list.filter((a) => a.group === g) })), { title: 'Ungrouped', items: ungrouped }].filter((x) => x.items.length)
      : [{ title: '', items: list }])
    : [{ title: '', items: active === '' ? ungrouped : list.filter((a) => a.group === active) }]

  // Sorting works on what the current filter shows; the new order is written back into the same
  // slots of the full list, so agents outside the filter keep their places.
  const shown = sections.flatMap((x) => x.items)
  const startSort = () => { setOrder(active === null ? list : shown); setSorting(true) }
  const finishSort = async () => {
    const picked = new Set(order.map((a) => a.id))
    let k = 0
    const full = list.map((a) => picked.has(a.id) ? order[k++] : a)
    const ids = full.map((a) => a.id)
    if (ids.join() === list.map((a) => a.id).join()) { setSorting(false); return }
    setSaving(true)
    try {
      await api.reorderAgents(ids)
      agents.value = full
      setSorting(false)
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }

  return (
    <div class="page wide-page">
      <TopBar scrolled={scrolled}
        right={sorting ? (
          <button class="btn primary small" disabled={saving} onClick={finishSort}>{saving ? <span class="spinner" /> : 'Done'}</button>
        ) : (
          <div class="topbar-actions">
            {list.length > 0 && <button class="icon-btn" aria-label="Manage groups" onClick={() => setManaging(true)}><IconTag /></button>}
            {(active === null ? list : shown).length > 1 && <button class="icon-btn" aria-label="Reorder agents" onClick={startSort}><IconSort /></button>}
            <button class="icon-btn" aria-label="Settings" onClick={() => navigate({ name: 'settings' })}><IconSettings /></button>
          </div>
        )}>
        {scrolled && <span class="fade-in">Agents</span>}
      </TopBar>
      <div class="page-scroll" ref={scrollRef} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">{greeting()}</h1>
          <p class="subtitle rise" style={{ '--i': 1 }}>
            {list.length ? `${list.length} agent${list.length > 1 ? 's' : ''} ready to help.` : 'Let us set up your first agent.'}
          </p>

          {loading && (
            <div class="agent-grid">
              {[0, 1, 2].map((i) => <div key={i} class="skeleton" style={{ height: '128px', borderRadius: '20px' }} />)}
            </div>
          )}

          {!loading && list.length === 0 && (
            <div class="empty rise">
              <div class="empty-crab crab-wave"><Crab /></div>
              <h3 class="serif">No agents yet</h3>
              <p>Create an agent with its own folder, model and instructions.</p>
              <button class="btn primary" style={{ marginTop: '10px' }} onClick={() => navigate({ name: 'new-agent' })}>
                <IconPlus width={18} height={18} /> New agent
              </button>
            </div>
          )}

          {!sorting && !loading && groups.length > 0 && (
            <div class="group-filter rise" role="tablist" aria-label="Filter by group" style={{ '--i': 1 }}>
              {[[null, 'All', list.length] as const, ...groups.map((g) => [g, g, list.filter((a) => a.group === g).length] as const),
                ...(ungrouped.length ? [['', 'Ungrouped', ungrouped.length] as const] : [])].map(([key, label, n]) => (
                <button key={label} role="tab" aria-selected={active === key} class={`chip ${active === key ? 'pink' : ''}`}
                  onClick={() => { haptic(); pick(key) }}>
                  {label}<span class="chip-count">{n}</span>
                </button>
              ))}
            </div>
          )}

          {sorting ? <SortList items={order} onChange={setOrder} /> : sections.map((sec, si) => (
            <section key={sec.title || si} class="agent-section">
              {sec.title && <div class="group-title">{sec.title}</div>}
              {sec.items.length ? (
                <div class="agent-grid">
                  {sec.items.map((a, i) => <AgentCard key={a.id} agent={a} index={i} groups={groups} />)}
                </div>
              ) : !loading && list.length > 0 && <p class="fhint" style={{ margin: '14px 4px' }}>No agents in this group yet. Open an agent's settings to add it.</p>}
            </section>
          ))}

          {!sorting && !loading && active === null && <TempSessions />}
        </div>
      </div>
      <GroupManager open={managing} onClose={() => setManaging(false)} groups={groups}
        counts={Object.fromEntries(groups.map((g) => [g, list.filter((a) => a.group === g).length]))}
        onSaved={(g) => { setGroups(g); agentsVersion.value++ }} />
      {!sorting && <button class="fab" onClick={() => navigate({ name: 'new-agent' })}>
        <IconPlus /> New agent
      </button>}
    </div>
  )
}

/** Drag the handle (pointer or touch) or use the arrow keys on it to move an agent. */
function SortList({ items, onChange }: { items: Agent[]; onChange: (l: Agent[]) => void }) {
  const rows = useRef<(HTMLDivElement | null)[]>([])
  const drag = useRef<{ from: number; to: number; startY: number; tops: number[]; h: number } | null>(null)
  const [, force] = useState(0)

  const move = (from: number, to: number) => {
    if (from === to) return
    const l = items.slice()
    const [x] = l.splice(from, 1)
    l.splice(to, 0, x)
    onChange(l)
  }

  const onDown = (e: PointerEvent, i: number) => {
    if (e.button !== 0) return
    e.preventDefault()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    const rects = rows.current.slice(0, items.length).map((el) => el!.getBoundingClientRect())
    const h = rects.length > 1 ? rects[1].top - rects[0].top : rects[0].height
    drag.current = { from: i, to: i, startY: e.clientY, tops: rects.map((r) => r.top), h }
    haptic()
    force((n) => n + 1)
  }
  const onMove = (e: PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dy = e.clientY - d.startY
    const center = d.tops[d.from] + dy + d.h / 2
    let to = 0
    for (let k = 0; k < d.tops.length; k++) if (center > d.tops[k]) to = k
    to = Math.max(0, Math.min(items.length - 1, to))
    if (to !== d.to) haptic()
    d.to = to
    const el = rows.current[d.from]
    if (el) el.style.transform = `translate3d(0, ${dy}px, 0)`
    rows.current.forEach((r, k) => {
      if (!r || k === d.from) return
      const shift = d.from < to && k > d.from && k <= to ? -d.h : d.from > to && k < d.from && k >= to ? d.h : 0
      r.style.transform = shift ? `translate3d(0, ${shift}px, 0)` : ''
    })
  }
  const onUp = () => {
    const d = drag.current
    if (!d) return
    drag.current = null
    rows.current.forEach((r) => { if (r) { r.style.transition = 'none'; r.style.transform = '' } })
    move(d.from, d.to)
    force((n) => n + 1)
    requestAnimationFrame(() => rows.current.forEach((r) => { if (r) r.style.transition = '' }))
  }
  const onKey = (e: KeyboardEvent, i: number) => {
    const to = e.key === 'ArrowUp' ? i - 1 : e.key === 'ArrowDown' ? i + 1 : -1
    if (to < 0 || to >= items.length) return
    e.preventDefault()
    move(i, to)
    requestAnimationFrame(() => rows.current[to]?.querySelector<HTMLElement>('.sort-handle')?.focus())
  }

  const dragging = drag.current?.from
  return (
    <div class="sort-list" aria-label="Drag to reorder agents">
      <p class="fhint" style={{ margin: '0 4px 10px' }}>Drag the handle to change the order, then tap Done.</p>
      {items.map((a, i) => (
        <div key={a.id} ref={(el) => { rows.current[i] = el }} class={`sort-row ${dragging === i ? 'dragging' : ''}`}>
          <Avatar agent={a} size={40} />
          <div class="sort-name">
            <div class="n">{a.name}</div>
            <div class="p">{shortPath(a.cwd)}</div>
          </div>
          <button type="button" class="sort-handle" aria-label={`Move ${a.name}. Use the up and down arrow keys.`}
            onPointerDown={(e) => onDown(e, i)} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
            onKeyDown={(e) => onKey(e, i)}>
            <IconGrip />
          </button>
        </div>
      ))}
    </div>
  )
}

function AgentCard({ agent, index, groups }: { agent: Agent; index: number; groups: string[] }) {
  const [moving, setMoving] = useState(false)
  const press = useRef<{ timer?: number; fired: boolean }>({ fired: false })
  const startPress = () => {
    if (!groups.length) return
    press.current.fired = false
    press.current.timer = window.setTimeout(() => { press.current.fired = true; haptic(); setMoving(true) }, 550)
  }
  const cancelPress = () => clearTimeout(press.current.timer)
  const moveTo = async (g: string) => {
    setMoving(false)
    if (g === (agent.group || '')) return
    try { await api.updateAgent(agent.id, { group: g }); agentsVersion.value++ } catch (e) { toastError(e) }
  }
  const live = agentLive(agent.id)
  const running = live.running || agent.status?.running || 0
  const pending = live.pending || agent.status?.pending || 0
  const isLive = live.live || agent.status?.live || 0
  const last = agent.status?.last_session
  const model = agent.effective?.model || agent.model
  const creating = useRef(false)

  // Put the agent page under the chat so Back lands on its conversation list. It has to be painted
  // before the chat is pushed: iOS swipe-back shows a snapshot of the previous entry, and an entry
  // that never rendered has none, which makes the gesture stall and snap back.
  const newChat = async (e: Event) => {
    e.stopPropagation()
    if (creating.current) return
    creating.current = true
    try {
      const [s, list] = await Promise.all([api.createSession(agent.id), api.sessions(agent.id).catch(() => null)])
      if (list) sessionCache.set(agent.id, [s, ...list.filter((x) => x.id !== s.id)])
      navigate({ name: 'agent', agentId: agent.id }, { animate: false })
      await painted()
      navigate({ name: 'chat', agentId: agent.id, sessionId: s.id })
    } catch (err) { toastError(err) } finally { creating.current = false }
  }

  return (
    <div class="agent-card-wrap rise" style={{ '--i': index + 2 }}>
    <button class="agent-card press"
      onClick={() => { if (press.current.fired) { press.current.fired = false; return } navigate({ name: 'agent', agentId: agent.id }) }}
      onContextMenu={(e) => { if (!groups.length) return; e.preventDefault(); setMoving(true) }}
      onTouchStart={startPress} onTouchEnd={cancelPress} onTouchMove={cancelPress} onTouchCancel={cancelPress}>
      <div class="agent-card-top">
        <Avatar agent={agent} size={52} busy={running > 0} />
        <div class="agent-card-name">
          <div class="n">{agent.name}{live.unread > 0 && <span class="unread-dot" aria-label={`${live.unread} unread`} />}</div>
          <div class="p">{shortPath(agent.cwd)}</div>
        </div>
        {pending > 0 ? (
          <span class="chip warn pending-chip">Needs you</span>
        ) : running > 0 ? (
          <span class="chip pink"><Spark size={13} /> Working</span>
        ) : (
          <span class={`dot ${isLive ? 'live' : ''}`} title={isLive ? 'Connected' : 'Sleeping'} />
        )}
      </div>
      <div class="agent-card-last">
        {last ? (
          <>
            <span class="lt">{last.title || 'Untitled'}</span>
            <span class="lp">{last.preview || ' '}</span>
          </>
        ) : (
          <span class="lp">{agent.description || 'No conversations yet.'}</span>
        )}
      </div>
      <div class="agent-card-foot">
        <span class="mtag">{model}</span>
        {(agent.effective?.effort || agent.effort) && <span class="mtag">{agent.effective?.effort || agent.effort}</span>}
        <span class="when">{last ? relTime(last.updated_at) : ''}</span>
      </div>
    </button>
    <button class="agent-new press" aria-label={`New chat with ${agent.name}`} onClick={newChat}>
      <IconPlus width={16} height={16} /><IconChat width={17} height={17} />
    </button>
    <Sheet open={moving} onClose={() => setMoving(false)} title={`Move ${agent.name} to`}>
      <div class="menu">
        {[...groups, ''].map((g) => (
          <button key={g || '_none'} onClick={() => moveTo(g)} aria-pressed={(agent.group || '') === g}>
            <IconTag /> {g || 'Ungrouped'}{(agent.group || '') === g && <span class="menu-check">Current</span>}
          </button>
        ))}
      </div>
    </Sheet>
    </div>
  )
}

/** Temporary chats as an agent card: header opens its sessions page, the card lists the 5 latest chats. */
function TempSessions() {
  const [list, setList] = useState<Session[] | null>(null)
  const [agent, setAgent] = useState<Agent | null>(null)
  const [picking, setPicking] = useState(false)

  useEffect(() => { api.tempSessions().then(setList).catch(toastError) }, [sessionsVersion.value])
  useEffect(() => { api.agent(TEMP_AGENT).then(setAgent).catch(() => {}) }, [agentsVersion.value])

  const start = async (cwd: string) => {
    setPicking(false)
    try {
      const s = await api.createTempSession(cwd)
      navigate({ name: 'agent', agentId: TEMP_AGENT }, { animate: false })
      await painted()
      navigate({ name: 'chat', agentId: TEMP_AGENT, sessionId: s.id })
    } catch (e) { toastError(e) }
  }

  const [menuFor, setMenuFor] = useState<Session | null>(null)
  const reload = () => api.tempSessions().then(setList).catch(toastError)
  const rename = async (s: Session) => {
    setMenuFor(null)
    const t = await promptDialog({ title: 'Rename conversation', value: s.title, confirm: 'Rename' })
    if (t === null || !t.trim()) return
    try { await api.updateSession(s.id, { title: t.trim() }); reload() } catch (e) { toastError(e) }
  }
  const sleep = async (s: Session) => {
    setMenuFor(null)
    try { await api.sleepSession(s.id); toast('Put to sleep') } catch (e) { toastError(e) }
  }
  const remove = async (s: Session) => {
    setMenuFor(null)
    if (!await confirmDialog({ title: 'Delete conversation?', body: s.title || 'New conversation', confirm: 'Delete', danger: true })) return
    try { await api.deleteSession(s.id); setList((l) => l && l.filter((x) => x.id !== s.id)) } catch (e) { toastError(e) }
  }

  const live = liveSessions.value
  const rows = (list || []).map((s) => {
    const l = live[s.id]
    return l ? { ...s, state: l.state, pending: l.pending, unread: l.unread ?? s.unread, title: l.title ?? s.title, updated_at: l.updated_at ?? s.updated_at } : s
  })
  const running = rows.filter((s) => s.state === 'running' || s.state === 'interrupting').length
  const shown = rows.slice(0, 5)
  const shownAgent = agent || { id: TEMP_AGENT, name: 'Claude Code', avatar: 'crab:gray', order: 0 } as Agent
  const model = agent?.effective?.model || meta.value?.defaults.model || ''

  return (
    <section class="temp-section rise">
      <div class="group-title">Temporary</div>
      <div class="temp-card">
        <button class="temp-card-top press" onClick={() => navigate({ name: 'agent', agentId: TEMP_AGENT })}>
          <Avatar agent={shownAgent} size={52} busy={running > 0} />
          <div class="agent-card-name">
            <div class="n">{shownAgent.name}{rows.some((s) => s.unread) && <span class="unread-dot" aria-label="Unread" />}</div>
            <div class="p">{rows.length ? `${rows.length} chat${rows.length > 1 ? 's' : ''} · ${model}` : `One-off chats in any folder · ${model}`}</div>
          </div>
        </button>
        {shown.length > 0 && <div class="temp-card-list">{shown.map((s) => <TempRow key={s.id} s={s} onMore={() => setMenuFor(s)} />)}</div>}
        <div class="temp-card-actions">
          <button class="btn small" onClick={() => setPicking(true)}><IconFolder width={16} height={16} /> Open folder</button>
          <button class="btn small primary" onClick={() => start('~')} title="New chat in your home folder">
            <IconPlus width={16} height={16} /> New chat
          </button>
        </div>
      </div>
      <Sheet open={!!menuFor} onClose={() => setMenuFor(null)} title={menuFor?.title || 'Conversation'}>
        {menuFor && (
          <div class="menu">
            <button onClick={() => rename(menuFor)}><IconEdit /> Rename</button>
            {menuFor.state !== 'offline' && <button onClick={() => sleep(menuFor)}><IconMoon /> Put to sleep (idle)</button>}
            <button class="danger" onClick={() => remove(menuFor)}><IconTrash /> Delete</button>
          </div>
        )}
      </Sheet>
      <DirPicker open={picking} onClose={() => setPicking(false)} onPick={start} confirm="Start chat" />
    </section>
  )
}

function TempRow({ s, onMore }: { s: Session; onMore: () => void }) {
  const press = useRef<{ timer?: number; fired: boolean }>({ fired: false })
  const busy = s.state === 'running' || s.state === 'interrupting'
  // Long press (or right click) opens the menu; swallow the click that follows the long press.
  const startPress = () => {
    press.current.fired = false
    press.current.timer = window.setTimeout(() => { press.current.fired = true; haptic(); onMore() }, 550)
  }
  const cancelPress = () => clearTimeout(press.current.timer)
  const click = () => {
    if (press.current.fired) { press.current.fired = false; return }
    navigate({ name: 'chat', agentId: TEMP_AGENT, sessionId: s.id })
  }
  return (
    <button class="row" onClick={click} onContextMenu={(e) => { e.preventDefault(); onMore() }}
      onTouchStart={startPress} onTouchEnd={cancelPress} onTouchMove={cancelPress} onTouchCancel={cancelPress}>
      <span class="session-state">
        {s.pending > 0 ? <span class="dot waiting" /> : busy ? <Spark size={16} /> : <span class={`dot ${s.state !== 'offline' ? 'live' : ''}`} />}
      </span>
      <span class="label">
        <span class={`session-title ${s.unread ? 'unread' : ''}`}>{s.title || 'New conversation'}</span>
        <span class="hint mono-label">{shortPath(s.cwd || '')}</span>
      </span>
      <span class="session-meta">{s.unread && <span class="unread-dot" aria-label="Unread" />}{relTime(s.updated_at)}</span>
    </button>
  )
}

/** Create, rename, reorder and delete groups. Saved as one PUT so renames carry their agents along. */
function GroupManager({ open, onClose, groups, counts, onSaved }: {
  open: boolean; onClose: () => void; groups: string[]; counts: Record<string, number>; onSaved: (g: string[]) => void
}) {
  // Each row remembers the name it started with, so a rename can be sent as old -> new.
  const [rows, setRows] = useState<{ from: string; name: string }[]>([])
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (open) { setRows(groups.map((g) => ({ from: g, name: g }))); setDraft('') } }, [open])

  const names = rows.map((r) => r.name.trim())
  const dup = names.some((n, i) => !n || names.indexOf(n) !== i)
  const add = () => {
    const n = draft.trim()
    if (!n || names.includes(n)) return
    setRows([...rows, { from: '', name: n }]); setDraft('')
  }
  const up = (i: number) => { const l = rows.slice(); [l[i - 1], l[i]] = [l[i], l[i - 1]]; setRows(l) }
  const remove = async (i: number) => {
    const r = rows[i]
    const n = r.from ? counts[r.from] || 0 : 0
    if (n && !await confirmDialog({ title: `Delete "${r.name}"?`, body: `${n} agent${n > 1 ? 's' : ''} will become ungrouped. The agents themselves are kept.`, confirm: 'Delete', danger: true })) return
    setRows(rows.filter((_, k) => k !== i))
  }
  const save = async () => {
    const pending = draft.trim() && !names.includes(draft.trim()) ? [...rows, { from: '', name: draft.trim() }] : rows
    setSaving(true)
    try {
      const renames = Object.fromEntries(pending.filter((r) => r.from && r.from !== r.name.trim()).map((r) => [r.from, r.name.trim()]))
      const res = await api.setGroups(pending.map((r) => r.name.trim()), renames)
      onSaved(res.groups); onClose()
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Groups">
      <p class="fhint" style={{ margin: '0 4px 12px' }}>Sort agents into groups on Home. Long press an agent card to move it, or pick a group in its settings.</p>
      {rows.length > 0 && <div class="group group-editor">
        {rows.map((r, i) => (
          <div key={i} class="group-edit-row">
            <IconTag width={18} height={18} />
            <input class="input" value={r.name} maxLength={40} aria-label="Group name"
              onInput={(e) => setRows(rows.map((x, k) => k === i ? { ...x, name: (e.target as HTMLInputElement).value } : x))} />
            <span class="group-edit-count">{r.from ? counts[r.from] || 0 : 0}</span>
            <button class="icon-btn" aria-label={`Move ${r.name} up`} disabled={i === 0} onClick={() => up(i)}><IconArrowUp /></button>
            <button class="icon-btn danger" aria-label={`Delete ${r.name}`} onClick={() => remove(i)}><IconTrash /></button>
          </div>
        ))}
      </div>}
      <form class="group-add" onSubmit={(e) => { e.preventDefault(); add() }}>
        <input class="input" value={draft} maxLength={40} placeholder="New group, e.g. Work"
          onInput={(e) => setDraft((e.target as HTMLInputElement).value)} />
        <button class="btn" type="submit" disabled={!draft.trim() || names.includes(draft.trim())}><IconPlus width={16} height={16} /> Add</button>
      </form>
      {groups.length > 0 && <StartPicker groups={groups} />}
      <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
        <button class="btn block" onClick={onClose}>Cancel</button>
        <button class="btn primary block" disabled={dup || saving} onClick={save}>{saving ? <span class="spinner" /> : 'Save'}</button>
      </div>
    </Sheet>
  )
}

/** Per-device choice of the group Home opens on. Saved immediately, separate from the group list. */
function StartPicker({ groups }: { groups: string[] }) {
  const [start, setStart] = useState(() => localStorage.getItem(START_KEY))
  const choose = (v: string | null) => {
    setStart(v)
    if (v === null) localStorage.removeItem(START_KEY); else localStorage.setItem(START_KEY, v)
  }
  const options: [string | null, string][] = [[null, 'All'], ...groups.map((g) => [g, g] as [string, string]), [START_UNGROUPED, 'Ungrouped'], [START_LAST, 'Last used']]
  const current = start !== null && start !== START_LAST && start !== START_UNGROUPED && !groups.includes(start) ? null : start
  return (
    <div class="field" style={{ marginTop: '18px' }}>
      <span class="flabel">Open Home on</span>
      <div class="chips" role="radiogroup" aria-label="Open Home on">
        {options.map(([v, label]) => (
          <button key={label + String(v)} type="button" role="radio" aria-checked={current === v}
            class={`chip ${current === v ? 'pink' : ''}`} onClick={() => choose(v)}>{label}</button>
        ))}
      </div>
      <span class="fhint">Saved on this device only. Last used reopens the filter you picked most recently.</span>
    </div>
  )
}
