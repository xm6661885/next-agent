// Small UI helpers shared by the workflow pages: an imperative sheet host, menu rows, status badges, file helpers.

import { signal } from '@preact/signals'
import type { ComponentChildren, JSX } from 'preact'
import { useEffect, useState } from 'preact/hooks'
import { Spark } from '../../components/crab'
import { toast } from '../../lib/store'
import { STATUS_LABEL } from './api'
import { WfIcon } from './icons'

type Render = (close: (v?: any) => void, open: boolean) => JSX.Element
const current = signal<{ render: Render; resolve: (v: any) => void; id: number } | null>(null)
let n = 0

/** Show a sheet built by `render(close, open)`; resolves with the value passed to close. Pass `open` to <Sheet open>. */
export function showSheet<T = unknown>(render: Render): Promise<T | undefined> {
  return new Promise((resolve) => {
    current.value?.resolve(undefined)
    current.value = { render, resolve, id: ++n }
  })
}

export function SheetHost() {
  const c = current.value
  const [open, setOpen] = useState(true)
  useEffect(() => { setOpen(true) }, [c?.id])
  useEffect(() => () => { current.value?.resolve(undefined); current.value = null }, [])
  if (!c) return null
  const close = (v?: unknown) => {
    setOpen(false)
    c.resolve(v)
    setTimeout(() => { if (current.value?.id === c.id) current.value = null }, 280)
  }
  return c.render(close, open)
}

export function MenuItem({ icon, children, onClick, danger, sub }: { icon?: string; children: ComponentChildren; onClick: () => void; danger?: boolean; sub?: string }) {
  return (
    <button class={danger ? 'danger' : ''} onClick={onClick}>
      {icon && <WfIcon name={icon} />}
      <span style={{ flex: 1 }}>{children}</span>
      {sub && <span class="wf-menu-sub">{sub}</span>}
    </button>
  )
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span class={`wf-status ${status}`}>
      {status === 'running' ? <Spark size={13} /> : <span class={`wf-dot ${status}`} />}
      {STATUS_LABEL[status] || status}
    </span>
  )
}

export function downloadJson(name: string, obj: unknown) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name.replace(/[\\/:*?"<>|]/g, '_') + '.json'
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

export function pickFile(accept = 'application/json'): Promise<string | null> {
  return new Promise((resolve) => {
    const inp = document.createElement('input')
    inp.type = 'file'
    inp.accept = accept
    inp.onchange = async () => resolve(inp.files?.[0] ? await inp.files[0].text() : null)
    inp.click()
  })
}

export async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); toast('Copied') } catch { toast('Copy failed', 'error') }
}
