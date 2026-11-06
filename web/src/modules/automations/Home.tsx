// Automations tab root: summary, failure card, recurring / one-off lists with group filter and long-press menu.

import { useEffect, useRef, useState } from 'preact/hooks'
import { Segmented, Sheet, Switch, TopBar, confirmDialog, promptDialog, useScrolled } from '../../components/ui'
import { IconEdit, IconHistory, IconMore, IconPlus, IconTrash } from '../../components/icons'
import { navigate } from '../../lib/router'
import { automationsVersion, toastError } from '../../lib/store'
import { autoApi, type Group, type Task } from './api'
import { describeSchedule, relWhen, taskOutcome } from './format'
import { GroupPicker, MenuSheet, OutcomeBadge, attempt, deleteTask, runTask, Empty } from './ui'

type Kind = 'recurring' | 'one_off'
const lsGet = (k: string, d: string) => localStorage.getItem(k) || d

export function Automations() {
  const { scrolled, onScroll, ref } = useScrolled()
  const [tasks, setTasks] = useState<Task[] | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [failures, setFailures] = useState<Task[]>([])
  const [kind, setKind] = useState<Kind>(lsGet('auto-kind', 'recurring') as Kind)
  const [filter, setFilter] = useState(lsGet('auto-group', 'all'))
  const [menu, setMenu] = useState<Task | null>(null)
  const [moving, setMoving] = useState<Task | null>(null)
  const [failOpen, setFailOpen] = useState(false)
  const [groupsOpen, setGroupsOpen] = useState(false)
  const [, tick] = useState(0)

  const timer = useRef<number>()
  useEffect(() => {
    clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      Promise.all([autoApi.tasks(), autoApi.groups(), autoApi.failures()])
        .then(([t, g, f]) => { setTasks(t); setGroups(g); setFailures(f) })
        .catch(toastError)
    }, tasks ? 300 : 0)
    return () => clearTimeout(timer.current)
  }, [automationsVersion.value])

  // One 30 s tick keeps the relative labels fresh while the page is visible.
  useEffect(() => {
    const id = setInterval(() => { if (document.visibilityState === 'visible') tick((n) => n + 1) }, 30000)
    return () => clearInterval(id)
  }, [])

  const setK = (k: Kind) => { setKind(k); localStorage.setItem('auto-kind', k) }
  const setF = (f: string) => { setFilter(f); localStorage.setItem('auto-group', f) }

  const all = tasks || []
  const ofKind = all.filter((t) => t.task_kind === kind)
  const countFor = (f: string) => ofKind.filter((t) => f === 'all' || (f === 'none' ? t.group_id === null : String(t.group_id) === f)).length
  const effective = filter !== 'all' && filter !== 'none' && !groups.some((g) => String(g.id) === filter) ? 'all' : filter
  const list = ofKind.filter((t) => effective === 'all' || (effective === 'none' ? t.group_id === null : String(t.group_id) === effective))
  const running = all.filter((t) => t.running || t.one_off_state === 'running').length
  const hasUngrouped = ofKind.some((t) => t.group_id === null)

  const toggle = (t: Task) => attempt(() => autoApi.setEnabled(t.id, !t.enabled))
  const menuItems = (t: Task) => [
    { label: t.running ? 'Run again (force)' : t.task_kind === 'one_off' ? (t.one_off_state === 'pending' ? 'Start now' : 'Run again') : 'Run now', onClick: () => (t.running ? attempt(() => autoApi.run(t.id, { force: true }), 'Started') : runTask(t)) },
    { label: t.enabled ? 'Disable' : 'Enable', hidden: t.task_kind === 'one_off', onClick: () => toggle(t) },
    { label: 'Move to group', onClick: () => setMoving(t) },
    { label: 'Delete', danger: true, onClick: async () => { await deleteTask(t) } },
  ]

  return (
    <div class="page">
      <TopBar scrolled={scrolled}
        right={<div class="topbar-actions">
          <button class="icon-btn" aria-label="Run history" onClick={() => navigate({ name: 'automation-runs' })}><IconHistory /></button>
          <button class="icon-btn" aria-label="New task" onClick={() => navigate({ name: 'automation-new' })}><IconPlus /></button>
        </div>}>
        {scrolled && <span class="fade-in">Automations</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Automations</h1>
          <p class="subtitle rise" style={{ '--i': 1 }}>
            {tasks === null ? 'Loading' : `${all.length} task${all.length === 1 ? '' : 's'} · ${running} running · ${failures.length} failed recently`}
          </p>

          {failures.length > 0 && (
            <button class="auto-warn rise" style={{ '--i': 1 }} onClick={() => setFailOpen(true)}>
              <span class="auto-dot failed" />
              <span style={{ flex: 1, textAlign: 'left' }}>{failures.length} task{failures.length === 1 ? '' : 's'} failed recently</span>
              <span class="auto-warn-go">Review</span>
            </button>
          )}

          <div class="kind-switch rise" style={{ '--i': 2 }}>
            <Segmented value={kind} onChange={setK} options={[{ value: 'recurring', label: 'Recurring' }, { value: 'one_off', label: 'One-off' }]} />
          </div>

          {(groups.length > 0 || hasUngrouped) && (
            <div class="group-filter auto-filter rise" role="tablist" aria-label="Filter by group" style={{ '--i': 3 }}>
              {[['all', 'All'], ...groups.map((g) => [String(g.id), g.name]), ...(groups.length ? [['none', 'Ungrouped']] : [])].map(([id, label]) => (
                <button key={id} role="tab" aria-selected={effective === id} class={`chip ${effective === id ? 'pink' : ''}`} onClick={() => setF(id)}>
                  {label}<span class="chip-count">{countFor(id)}</span>
                </button>
              ))}
              <button class="chip dashed" onClick={() => setGroupsOpen(true)}>Edit</button>
            </div>
          )}
          {groups.length === 0 && tasks && tasks.length > 0 && (
            <div class="group-filter auto-filter"><button class="chip dashed" onClick={() => setGroupsOpen(true)}><IconPlus /> Group</button></div>
          )}

          {tasks === null && <div class="auto-list">{[0, 1, 2].map((i) => <div key={i} class="skeleton" style={{ height: '88px', borderRadius: '18px' }} />)}</div>}
          {tasks !== null && list.length === 0 && (
            <Empty title={ofKind.length ? 'No tasks in this group' : kind === 'recurring' ? 'No recurring tasks' : 'No one-off tasks'}>
              {ofKind.length ? 'Pick another group.' : 'Tap + to create one.'}
            </Empty>
          )}
          <div class="auto-list">
            {list.map((t, i) => <TaskCard key={t.id} t={t} i={i} onMenu={() => setMenu(t)} onToggle={() => toggle(t)} />)}
          </div>
        </div>
      </div>

      <MenuSheet open={!!menu} title={menu?.name} items={menu ? menuItems(menu) : []} onClose={() => setMenu(null)} />
      <GroupPicker open={!!moving} task={moving} groups={groups} onClose={() => setMoving(null)} />
      <FailureSheet open={failOpen} tasks={failures} onClose={() => setFailOpen(false)} />
      <GroupsSheet open={groupsOpen} groups={groups} onClose={() => setGroupsOpen(false)} />
    </div>
  )
}

function TaskCard({ t, i, onMenu, onToggle }: { t: Task; i: number; onMenu: () => void; onToggle: () => void }) {
  const o = taskOutcome(t)
  const pressTimer = useRef<number>()
  const start = useRef({ x: 0, y: 0 })
  const longPressed = useRef(false)
  const cancel = () => clearTimeout(pressTimer.current)
  const open = () => navigate({ name: 'automation-task', taskId: String(t.id) })
  const oneOff = t.task_kind === 'one_off'
  const next = !oneOff && t.enabled && t.next_run_at ? `Next ${relWhen(t.next_run_at)}` : ''
  const last = t.last_run_at ? `Last ${relWhen(t.last_run_at)}` : ''
  return (
    <div class={`auto-card rise ${!oneOff && !t.enabled ? 'off' : ''}`} style={{ '--i': Math.min(i, 8) }} role="button" tabIndex={0}
      onClick={() => { if (longPressed.current) { longPressed.current = false; return } open() }}
      onKeyDown={(e) => e.key === 'Enter' && open()}
      onContextMenu={(e) => { e.preventDefault(); onMenu() }}
      onPointerDown={(e) => {
        longPressed.current = false
        start.current = { x: e.clientX, y: e.clientY }
        pressTimer.current = window.setTimeout(() => { longPressed.current = true; onMenu() }, 480)
      }}
      onPointerMove={(e) => { if (Math.abs(e.clientX - start.current.x) > 8 || Math.abs(e.clientY - start.current.y) > 8) cancel() }}
      onPointerUp={cancel} onPointerCancel={cancel} onPointerLeave={cancel}>
      <div class="auto-card-top">
        <span class="auto-name">{t.name}</span>
        <OutcomeBadge o={o} />
        <button class="icon-btn auto-more" aria-label="Task menu" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); onMenu() }}><IconMore /></button>
      </div>
      {t.description && <div class="auto-desc">{t.description}</div>}
      <div class="auto-meta">
        <span>{describeSchedule(t)}{oneOff && t.one_off_state && t.one_off_state !== 'pending' ? ` · ${t.one_off_state}` : ''}</span>
        {(next || last) && <span class="auto-sep">{next || last}</span>}
        {t.group_name && <span class="auto-sep">{t.group_name}</span>}
        {!oneOff && (
          <span class="auto-switch" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
            <Switch on={!!t.enabled} onChange={onToggle} label={`Enable ${t.name}`} />
          </span>
        )}
      </div>
    </div>
  )
}

function FailureSheet({ open, tasks, onClose }: { open: boolean; tasks: Task[]; onClose: () => void }) {
  const ack = async () => { if (await attempt(() => autoApi.ackFailures())) onClose() }
  return (
    <Sheet open={open} onClose={onClose} title="Failed recently" actions={<button class="btn small" onClick={ack}>Mark all as seen</button>}>
      <div class="group">
        {tasks.map((t) => (
          <button key={t.id} class="row press" onClick={() => { onClose(); navigate({ name: 'automation-task', taskId: String(t.id) }) }}>
            <span class="label">{t.name}<span class="hint">{relWhen(t.last_run_at)} · {t.last_exit_code === null ? 'abnormal exit' : `exit ${t.last_exit_code}`}</span></span>
          </button>
        ))}
        {tasks.length === 0 && <div class="row"><span class="label hint">Nothing to review.</span></div>}
      </div>
    </Sheet>
  )
}

function GroupsSheet({ open, groups, onClose }: { open: boolean; groups: Group[]; onClose: () => void }) {
  const [name, setName] = useState('')
  const add = async () => { const n = name.trim(); if (n && await attempt(() => autoApi.createGroup(n))) setName('') }
  const rename = async (g: Group) => {
    const n = await promptDialog({ title: 'Rename group', value: g.name, confirm: 'Rename' })
    if (n?.trim() && n.trim() !== g.name) attempt(() => autoApi.renameGroup(g.id, n.trim()))
  }
  const remove = async (g: Group) => {
    if (await confirmDialog({ title: 'Delete group?', body: `Its ${g.task_count} task${g.task_count === 1 ? '' : 's'} become ungrouped. Nothing else is deleted.`, confirm: 'Delete', danger: true }))
      attempt(() => autoApi.deleteGroup(g.id))
  }
  return (
    <Sheet open={open} onClose={onClose} title="Groups">
      {groups.length > 0 && (
        <div class="group group-editor">
          {groups.map((g) => (
            <div key={g.id} class="group-edit-row">
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{g.name}</span>
              <span class="group-edit-count">{g.task_count}</span>
              <button class="icon-btn" aria-label={`Rename ${g.name}`} onClick={() => rename(g)}><IconEdit width={18} height={18} /></button>
              <button class="icon-btn danger" aria-label={`Delete ${g.name}`} onClick={() => remove(g)}><IconTrash width={18} height={18} /></button>
            </div>
          ))}
        </div>
      )}
      <form class="group-add" onSubmit={(e) => { e.preventDefault(); add() }}>
        <input class="input" placeholder="New group name" value={name} onInput={(e) => setName((e.target as HTMLInputElement).value)} />
        <button class="btn primary" type="submit" disabled={!name.trim()}>Add</button>
      </form>
    </Sheet>
  )
}
