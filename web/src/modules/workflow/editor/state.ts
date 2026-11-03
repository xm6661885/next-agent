// Editor state: the open workflow, its definition, undo/redo and debounced autosave.

import { signal } from '@preact/signals'
import { toast } from '../../../lib/store'
import { wfApi, type Definition, type Workflow } from '../api'
import { emptyDef } from '../defs'

export const wf = signal<Omit<Workflow, 'definition'> | null>(null)
export const def = signal<Definition>(emptyDef())
export const saveState = signal<'saved' | 'dirty' | 'saving' | 'error'>('saved')
export const hist = signal({ undo: 0, redo: 0 })

let past: Definition[] = []
let future: Definition[] = []
let lastKey: string | null = null
let lastAt = 0
let timer: number | undefined
let saving: Promise<void> | null = null

const flags = () => { hist.value = { undo: past.length, redo: future.length } }

export async function openWorkflow(id: string) {
  await flushSave()
  const { definition, ...meta } = await wfApi.workflow(id)
  past = []; future = []; lastKey = null
  def.value = { ...emptyDef(), ...definition }
  wf.value = meta
  saveState.value = 'saved'
  flags()
}

export function edit(fn: (d: Definition) => void, coalesceKey: string | null = null) {
  const next = structuredClone(def.value)
  fn(next)
  const now = Date.now()
  if (!(coalesceKey && coalesceKey === lastKey && now - lastAt < 1500)) {
    past.push(def.value)
    if (past.length > 100) past.shift()
  }
  lastKey = coalesceKey; lastAt = now
  future = []
  def.value = next
  flags()
  scheduleSave()
}

export function undo() {
  if (!past.length) return
  future.push(def.value)
  def.value = past.pop()!
  lastKey = null
  flags(); scheduleSave()
}

export function redo() {
  if (!future.length) return
  past.push(def.value)
  def.value = future.pop()!
  lastKey = null
  flags(); scheduleSave()
}

function scheduleSave() {
  saveState.value = 'dirty'
  clearTimeout(timer)
  timer = window.setTimeout(flushSave, 700)
}

export async function flushSave(): Promise<void> {
  clearTimeout(timer)
  timer = undefined
  if (saving) await saving
  if (saveState.value !== 'dirty' || !wf.value) return
  const id = wf.value.id
  const snapshot = def.value
  saveState.value = 'saving'
  saving = wfApi.update(id, { definition: snapshot })
    .then(() => { saveState.value = def.value === snapshot ? 'saved' : 'dirty' })
    .catch((e) => { saveState.value = 'error'; toast('Save failed: ' + (e?.message || e), 'error') })
    .finally(() => { saving = null })
  await saving
  if ((saveState.value as string) === 'dirty') scheduleSave()
}

export async function updateMeta(patch: Partial<Workflow> & { clear_group?: boolean }) {
  const { definition: _, ...meta } = await wfApi.update(wf.value!.id, patch)
  wf.value = meta
}

addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushSave() })
addEventListener('pagehide', () => { flushSave() })
