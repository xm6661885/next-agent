import { useEffect, useRef, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { agents, agentsVersion, agentLive, liveSessions, toastError } from '../lib/store'
import { navigate } from '../lib/router'
import { sessionCache } from './AgentPage'
import { Avatar, Crab, Spark } from '../components/crab'
import { IconChat, IconGrip, IconPlus, IconSettings, IconSort } from '../components/icons'
import { TopBar, useScrolled } from '../components/ui'
import { haptic, relTime, shortPath } from '../lib/util'
import type { Agent } from '../lib/types'

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

  useEffect(() => {
    api.agents().then((a) => { agents.value = a }).catch(toastError).finally(() => setLoading(false))
  }, [agentsVersion.value])

  // Re-read the live map so cards update as sessions change state.
  void liveSessions.value
  const list = agents.value || []

  const startSort = () => { setOrder(list); setSorting(true) }
  const finishSort = async () => {
    const ids = order.map((a) => a.id)
    if (ids.join() === list.map((a) => a.id).join()) { setSorting(false); return }
    setSaving(true)
    try {
      await api.reorderAgents(ids)
      agents.value = order
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
            {list.length > 1 && <button class="icon-btn" aria-label="Reorder agents" onClick={startSort}><IconSort /></button>}
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

          {sorting ? <SortList items={order} onChange={setOrder} /> : (
            <div class="agent-grid">
              {list.map((a, i) => <AgentCard key={a.id} agent={a} index={i} />)}
            </div>
          )}
        </div>
      </div>
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

function AgentCard({ agent, index }: { agent: Agent; index: number }) {
  const live = agentLive(agent.id)
  const running = live.running || agent.status?.running || 0
  const pending = live.pending || agent.status?.pending || 0
  const isLive = live.live || agent.status?.live || 0
  const last = agent.status?.last_session
  const model = agent.model || 'Default model'
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
      onClick={() => navigate({ name: 'agent', agentId: agent.id })}>
      <div class="agent-card-top">
        <Avatar agent={agent} size={52} busy={running > 0} />
        <div class="agent-card-name">
          <div class="n">{agent.name}</div>
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
        {agent.effort && <span class="mtag">{agent.effort}</span>}
        <span class="when">{last ? relTime(last.updated_at) : ''}</span>
      </div>
    </button>
    <button class="agent-new press" aria-label={`New chat with ${agent.name}`} onClick={newChat}>
      <IconPlus width={16} height={16} /><IconChat width={17} height={17} />
    </button>
    </div>
  )
}
