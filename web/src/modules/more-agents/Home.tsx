// More Agents on the Agents tab (the "More" segment): cards for ACP and Codex agents, grouped.

import { useEffect, useRef, useState } from 'preact/hooks'
import { signal } from '@preact/signals'
import { moreAgentsVersion, moduleSessions, toastError } from '../../lib/store'
import { navigate } from '../../lib/router'
import { Spark } from '../../components/crab'
import { IconPlus, IconGlobe, IconFolder, IconEdit, IconMoon, IconTrash, IconArrowUp, IconGrip, IconSort, IconTag } from '../../components/icons'
import { haptic, shortPath } from '../../lib/util'
import { moreAgentsApi, type MoreAgent, type AgentKindInfo } from './api'
import { MoreAgentAvatar } from './chat/Chat'
import { Sheet, confirmDialog, promptDialog } from '../../components/ui'
import { DirPicker } from '../../components/DirPicker'

const painted = () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 30))))
// Shared with the Agents tab top bar (MoreAgentsActions), which sits outside this component.
const listSig = signal<MoreAgent[] | null>(null)
const groupsSig = signal<string[]>([])
const filterSig = signal<string | null>(null)
const sortingSig = signal(false)
const orderSig = signal<MoreAgent[]>([])
const savingSig = signal(false)
const managingSig = signal(false)

function sectionsOf(list: MoreAgent[], groups: string[], filter: string | null) {
  const ungrouped = list.filter((a) => !a.group || !groups.includes(a.group))
  const sections = filter === null
    ? (groups.length ? [...groups.map((g) => ({ title: g, items: list.filter((a) => a.group === g) })), { title: 'Ungrouped', items: ungrouped }].filter((x) => x.items.length) : [{ title: '', items: list }])
    : [{ title: '', items: filter === '' ? ungrouped : list.filter((a) => a.group === filter) }]
  return { ungrouped, sections }
}

// Sorting works on what the current filter shows; the new order is written back into the same
// slots of the full list, so agents outside the filter keep their places.
function shownAgents() {
  const list = listSig.value || [], groups = groupsSig.value
  const f = filterSig.value
  const active = f !== null && (f === '' || groups.includes(f)) ? f : null
  return active === null ? list : sectionsOf(list, groups, active).sections.flatMap((x) => x.items)
}
const startSort = () => { orderSig.value = shownAgents(); sortingSig.value = true }
const finishSort = async () => {
  const list = listSig.value || [], order = orderSig.value
  const picked = new Set(order.map((a) => a.id))
  let k = 0
  const full = list.map((a) => picked.has(a.id) ? order[k++] : a)
  const ids = full.map((a) => a.id)
  if (ids.join() === list.map((a) => a.id).join()) { sortingSig.value = false; return }
  savingSig.value = true
  try {
    await moreAgentsApi.reorder(ids)
    listSig.value = full
    sortingSig.value = false
  } catch (e) { toastError(e) } finally { savingSig.value = false }
}

/** Top bar buttons of the More segment: groups, reorder (or Done while reordering), add. */
export function MoreAgentsActions() {
  const n = (listSig.value || []).length
  if (sortingSig.value) return <button class="btn primary small" disabled={savingSig.value} onClick={finishSort}>{savingSig.value ? <span class="spinner" /> : 'Done'}</button>
  return (
    <div class="topbar-actions">
      {n > 0 && <button class="icon-btn" aria-label="Manage groups" onClick={() => { managingSig.value = true }}><IconTag /></button>}
      {shownAgents().length > 1 && <button class="icon-btn" aria-label="Reorder agents" onClick={startSort}><IconSort /></button>}
      <button class="icon-btn" aria-label="New agent" onClick={() => navigate({ name: 'new-more-agent' })}><IconPlus /></button>
    </div>
  )
}

/** Live counts for one More agent from the global feed. */
export function moreAgentLive(agentId: string) {
  let running = 0, live = 0, pending = 0, unread = 0
  for (const s of Object.values(moduleSessions.value)) {
    if (s.module !== 'more_agents' || s.agent_id !== agentId) continue
    if (s.unread) unread++
    if (s.state === 'running' || s.state === 'interrupting') running++
    if (s.state !== 'offline') live++
    pending += s.pending || 0
  }
  return { running, live, pending, unread }
}

export function MoreAgents() {
  const list = listSig.value, groups = groupsSig.value, filter = filterSig.value
  const sorting = sortingSig.value
  const [addSheet, setAddSheet] = useState(false)
  const [kinds, setKinds] = useState<AgentKindInfo[]>([])
  useEffect(() => {
    moreAgentsApi.agents().then((a) => { listSig.value = a }).catch(toastError)
    moreAgentsApi.groups().then((g) => { groupsSig.value = g.groups }).catch(() => {})
    moreAgentsApi.kinds().then(setKinds).catch(() => {})
  }, [moreAgentsVersion.value])
  useEffect(() => () => { sortingSig.value = false; managingSig.value = false }, [])
  void moduleSessions.value

  if (list === null) return <div class="agent-grid">{[0, 1].map((i) => <div key={i} class="skeleton" style={{ height: '128px', borderRadius: '20px' }} />)}</div>
  if (!list.length) return (
    <div class="empty rise">
      <div class="empty-icon"><IconGlobe width={40} height={40} /></div>
      <h3 class="serif">No More Agents yet</h3>
      <p>Connect ACP endpoints or run Codex agents locally.</p>
      <button class="btn primary" style={{ marginTop: '10px' }} onClick={() => setAddSheet(true)}><IconPlus width={18} height={18} /> New agent</button>
      <Sheet open={addSheet} onClose={() => setAddSheet(false)} title="New agent">
        <div class="agent-kind-grid">
          {kinds.map((k) => (
            <button key={k.kind} class="agent-kind-card press" onClick={() => { setAddSheet(false); navigate(`/more-agents/new?kind=${k.kind}`) }}>
              <div class="agent-kind-icon"><IconGlobe width={32} height={32} /></div>
              <div class="agent-kind-name">{k.name}</div>
              <div class="agent-kind-desc">{k.description}</div>
            </button>
          ))}
        </div>
      </Sheet>
    </div>
  )
  const { ungrouped, sections } = sectionsOf(list, groups, filter)
  return (
    <>
      <p class="subtitle rise" style={{ '--i': 1 }}>{list.length} agent{list.length > 1 ? 's' : ''}.</p>
      {!sorting && groups.length > 0 && (
        <div class="group-filter rise" role="tablist" style={{ '--i': 1 }}>
          {[[null, 'All', list.length] as const, ...groups.map((g) => [g, g, list.filter((a) => a.group === g).length] as const),
            ...(ungrouped.length ? [['', 'Ungrouped', ungrouped.length] as const] : [])].map(([key, label, n]) => (
            <button key={label} role="tab" aria-selected={filter === key} class={`chip ${filter === key ? 'pink' : ''}`} onClick={() => { haptic(); filterSig.value = key }}>
              {label}<span class="chip-count">{n}</span>
            </button>
          ))}
        </div>
      )}
      {sorting ? <SortList items={orderSig.value} onChange={(l) => { orderSig.value = l }} /> : sections.map((sec, si) => (
        <section key={sec.title || si} class="agent-section">
          {sec.title && <div class="group-title">{sec.title}</div>}
          <div class="agent-grid">{sec.items.map((a, i) => <MoreAgentCard key={a.id} agent={a} index={i} />)}</div>
        </section>
      ))}
      <GroupManager open={managingSig.value} onClose={() => { managingSig.value = false }} groups={groups}
        counts={Object.fromEntries(groups.map((g) => [g, list.filter((a) => a.group === g).length]))}
        onSaved={(g) => { groupsSig.value = g; moreAgentsVersion.value++ }} />
    </>
  )
}

/** Drag the handle (pointer or touch) or use the arrow keys on it to move an agent. */
function SortList({ items, onChange }: { items: MoreAgent[]; onChange: (l: MoreAgent[]) => void }) {
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
          <MoreAgentAvatar a={a} size={40} />
          <div class="sort-name">
            <div class="n">{a.name}</div>
            <div class="p">{a.kind === 'acp' ? a.cwd : shortPath(a.cwd)}</div>
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
      const res = await moreAgentsApi.setGroups(pending.map((r) => r.name.trim()), renames)
      onSaved(res.groups); onClose()
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Groups">
      <p class="fhint" style={{ margin: '0 4px 12px' }}>Sort More Agents into groups. Pick a group in an agent's settings to move it.</p>
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
      <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
        <button class="btn block" onClick={onClose}>Cancel</button>
        <button class="btn primary block" disabled={dup || saving} onClick={save}>{saving ? <span class="spinner" /> : 'Save'}</button>
      </div>
    </Sheet>
  )
}

function MoreAgentCard({ agent, index }: { agent: MoreAgent; index: number }) {
  const live = moreAgentLive(agent.id)
  const running = live.running || agent.status?.running || 0
  const creating = useRef(false)
  const [dirPicking, setDirPicking] = useState(false)
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const recent = agent.recent || []
  const press = useRef<{ timer?: number; fired: boolean }>({ fired: false })

  const newChat = async (e: Event, cwd?: string) => {
    e.stopPropagation()
    if (creating.current) return
    creating.current = true
    try {
      const s = await moreAgentsApi.createSession(agent.id, cwd)
      navigate({ name: 'more-agent', agentId: agent.id }, { animate: false })
      await painted()
      navigate({ name: 'more-agent-chat', agentId: agent.id, sessionId: s.id })
    } catch (err) { toastError(err) } finally { creating.current = false }
  }

  const openFolder = async (e: Event) => {
    e.stopPropagation()
    if (agent.kind === 'codex') {
      setDirPicking(true)
    } else {
      const cwd = await promptDialog({ title: 'Open folder', value: agent.cwd || '/', confirm: 'Start chat' })
      if (cwd?.trim()) newChat(e, cwd.trim())
    }
  }

  const renameSession = async (sid: string, title: string) => {
    const t = await promptDialog({ title: 'Rename conversation', value: title, confirm: 'Rename' })
    if (t === null || !t.trim()) return
    try {
      await moreAgentsApi.updateSession(sid, { title: t.trim() })
      moreAgentsVersion.value++
    } catch (e) { toastError(e) }
  }

  const sleepSession = async (sid: string) => {
    try {
      await moreAgentsApi.sleep(sid)
      moreAgentsVersion.value++
    } catch (e) { toastError(e) }
  }

  const deleteSession = async (sid: string, title: string) => {
    if (!await confirmDialog({ title: 'Delete conversation?', body: title || 'Untitled', confirm: 'Delete', danger: true })) return
    try {
      await moreAgentsApi.deleteSession(sid)
      moreAgentsVersion.value++
    } catch (e) { toastError(e) }
  }

  const startPress = (sid: string) => {
    press.current.fired = false
    press.current.timer = window.setTimeout(() => { press.current.fired = true; haptic(); setMenuFor(sid) }, 550)
  }
  const cancelPress = () => clearTimeout(press.current.timer)

  const kindTag = agent.kind === 'acp' ? 'ACP' : 'Codex'
  const detailLine = agent.kind === 'acp' ? agent.cwd : `${shortPath(agent.cwd)} · ${agent.model || 'default'}`

  return (
    <div class="agent-card-wrap rise" style={{ '--i': index + 2 }}>
      <button class="agent-card press" onClick={() => navigate({ name: 'more-agent', agentId: agent.id })}>
        <div class="agent-card-top">
          <MoreAgentAvatar a={agent} size={52} busy={running > 0} />
          <div class="agent-card-name">
            <div class="n">{agent.name}{live.unread > 0 && <span class="unread-dot" />}</div>
            <div class="p">{detailLine}</div>
          </div>
          <span class="mtag">{kindTag}</span>
        </div>

        {recent.length > 0 && (
          <div class="agent-card-recent" onClick={(e) => e.stopPropagation()}>
            {recent.slice(0, 5).map((s) => {
              const liveState = moduleSessions.value[s.id]
              const state = liveState?.state || s.state || 'offline'
              const unread = liveState?.unread ?? s.unread
              const sRunning = state === 'running' || state === 'interrupting'
              const sPending = liveState?.pending || 0
              const cwdDiff = s.cwd !== agent.cwd ? shortPath(s.cwd) : null
              return (
                <button key={s.id} class="recent-row press"
                  onClick={() => { if (press.current.fired) { press.current.fired = false; return } navigate({ name: 'more-agent-chat', agentId: agent.id, sessionId: s.id }) }}
                  onContextMenu={(e) => { e.preventDefault(); setMenuFor(s.id) }}
                  onTouchStart={() => startPress(s.id)} onTouchEnd={cancelPress} onTouchMove={cancelPress} onTouchCancel={cancelPress}>
                  <span class="recent-state">
                    {sPending > 0 ? <span class="dot waiting" /> : sRunning ? <Spark size={14} /> : <span class={`dot ${state !== 'offline' ? 'live' : ''}`} />}
                  </span>
                  <span class="recent-text">
                    <span class={`recent-title ${unread ? 'unread' : ''}`}>{s.title || 'Untitled'}</span>
                    {cwdDiff && <span class="hint mono-label">{cwdDiff}</span>}
                  </span>
                  {unread && <span class="unread-dot" aria-label="Unread" />}
                </button>
              )
            })}
          </div>
        )}

        <div class="agent-card-actions" onClick={(e) => e.stopPropagation()}>
          <button class="btn small" onClick={openFolder}><IconFolder width={16} height={16} /> Open folder</button>
          <button class="btn small primary" onClick={(e) => newChat(e)}><IconPlus width={16} height={16} /> New chat</button>
        </div>
      </button>

      <DirPicker open={dirPicking} onClose={() => setDirPicking(false)} onPick={(cwd) => { setDirPicking(false); newChat({ stopPropagation: () => {} } as Event, cwd) }} confirm="Start chat" />

      {recent.find((s) => s.id === menuFor) && (
        <Sheet open={!!menuFor} onClose={() => setMenuFor(null)} title={recent.find((s) => s.id === menuFor)?.title || 'Conversation'}>
          <div class="menu">
            <button onClick={() => { const s = recent.find((x) => x.id === menuFor)!; setMenuFor(null); renameSession(s.id, s.title) }}><IconEdit /> Rename</button>
            {moduleSessions.value[menuFor!]?.state !== 'offline' && (
              <button onClick={() => { const sid = menuFor!; setMenuFor(null); sleepSession(sid) }}><IconMoon /> Put to sleep</button>
            )}
            <button class="danger" onClick={() => { const s = recent.find((x) => x.id === menuFor)!; setMenuFor(null); deleteSession(s.id, s.title) }}><IconTrash /> Delete</button>
          </div>
        </Sheet>
      )}
    </div>
  )
}
