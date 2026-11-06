// Small helpers for the Automations pages: menu sheet, outcome badge, group picker, task actions shared by list and task page.

import type { ComponentChildren } from 'preact'
import { Sheet, confirmDialog } from '../../components/ui'
import { Spark } from '../../components/crab'
import { toast, toastError } from '../../lib/store'
import { copyText } from '../../lib/util'
import { autoApi, type Group, type Task } from './api'
import type { Outcome } from './format'

export interface MenuEntry { label: string; onClick: () => void; danger?: boolean; sub?: string; hidden?: boolean }

/** Bottom sheet listing actions; each one closes the sheet first. */
export function MenuSheet({ open, title, items, onClose }: { open: boolean; title?: string; items: MenuEntry[]; onClose: () => void }) {
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <div class="menu">
        {items.filter((i) => !i.hidden).map((i) => (
          <button key={i.label} class={i.danger ? 'danger' : ''} onClick={() => { onClose(); i.onClick() }}>
            <span style={{ flex: 1 }}>{i.label}</span>
            {i.sub && <span class="menu-check">{i.sub}</span>}
          </button>
        ))}
      </div>
    </Sheet>
  )
}

export function OutcomeBadge({ o }: { o: Outcome }) {
  return (
    <span class={`auto-badge ${o.kind}`}>
      {o.kind === 'running' ? <Spark size={13} /> : <span class="auto-dot" />}
      {o.label}
    </span>
  )
}

export const copy = (text: string) => copyText(text).then(() => toast('Copied')).catch(toastError)

/** Run an API call, report errors as a toast, and return whether it worked. */
export async function attempt(fn: () => Promise<unknown>, ok?: string): Promise<boolean> {
  try { await fn(); if (ok) toast(ok); return true } catch (e) { toastError(e); return false }
}

export function GroupPicker({ open, task, groups, onClose }: { open: boolean; task: Task | null; groups: Group[]; onClose: () => void }) {
  const move = (gid: number | null) => { onClose(); if (task) attempt(() => autoApi.moveToGroup(gid, task.id)) }
  return (
    <MenuSheet open={open} title="Move to group" onClose={onClose}
      items={[
        { label: 'Ungrouped', sub: task && task.group_id === null ? 'Current' : '', onClick: () => move(null) },
        ...groups.map((g) => ({ label: g.name, sub: task?.group_id === g.id ? 'Current' : '', onClick: () => move(g.id) })),
      ]} />
  )
}

export async function deleteTask(t: Task): Promise<boolean> {
  if (t.running) { toast('Stop the task before deleting it', 'error'); return false }
  const yes = await confirmDialog({ title: 'Delete task?', body: `"${t.name}" and its run history are removed. Script files and logs stay on disk.`, confirm: 'Delete', danger: true })
  return yes && attempt(() => autoApi.remove(t.id))
}

export async function runTask(t: Task) {
  if (t.task_kind === 'one_off') {
    const fn = t.one_off_state === 'pending' ? autoApi.start : autoApi.runAgain
    return attempt(() => fn(t.id), 'Started')
  }
  return attempt(() => autoApi.run(t.id), 'Started')
}

export function Empty({ title, children }: { title: string; children?: ComponentChildren }) {
  return <div class="empty"><h3>{title}</h3>{children && <p>{children}</p>}</div>
}
