// Workflow module REST client, types and the plugin catalog. Mirrors docs/protocol-workflow.md.

import { signal } from '@preact/signals'
import { request } from '../../lib/api'

export type Json = any
export type RunStatus = 'queued' | 'running' | 'waiting_input' | 'success' | 'failed' | 'cancelled'
export interface WfInput { name: string; type?: string; label?: string; default?: Json; multiline?: boolean }
export interface Block { id: string; type: string; params?: Record<string, Json>; group?: string; note?: string; disabled?: boolean
  continue_on_error?: boolean; timeout_s?: number; retries?: number; then?: Block[]; else?: Block[]; body?: Block[] }
export interface Definition { inputs: WfInput[]; blocks: Block[] }
export interface Workflow {
  id: string; name: string; group_id: string | null; sort: number; icon: string; color: string; updated_at: number
  block_count: number; inputs: WfInput[]; last_status?: RunStatus | null; last_run_at?: number | null; definition?: Definition
}
export interface WfGroup { id: string; name: string; sort: number }
export interface Run {
  id: string; workflow_id: string | null; workflow_name: string | null; status: RunStatus; inputs: Json; result: Json
  error: string | null; cost_usd: number; trigger: string; base_run_id: string | null
  created_at: number; started_at: number | null; finished_at: number | null; snapshot?: Definition
}
export interface RunEvent { run_id: string; seq: number; ts: number; block_id: string | null; type: string; data: Json }
export interface PluginInput { name: string; type: string; label: string; magic?: boolean; multiline?: boolean; required?: boolean
  placeholder?: string; description?: string; default?: Json; options?: (string | { value: string; label: string })[]; advanced?: boolean }
export interface PluginSchema {
  id: string; name: string; icon: string; color: string; category: string; description?: string
  inputs: PluginInput[]; outputs: { name: string; type: string; label: string }[]; default_output?: string
  container?: boolean; markers?: string[]; branches?: { key: string; label: string }[]; missing_env?: string[]
  /** Where the plugin was loaded from: `core/<folder>`, `extra/<folder>` or `user/<folder>`. Containers have none. */
  source?: string; version?: string; requires_env?: string[]; uses_agent_slot?: boolean
}
export interface Catalog { plugins: PluginSchema[]; containers: PluginSchema[]; markers: PluginSchema[]; errors: { folder: string; error: string; missing_deps?: boolean }[]; watching?: boolean }
export interface ConsoleSession { module: 'agents' | 'acp'; agent_id: string; session_id: string; title: string; state: string; parent: Json }
export interface WfSettings { agent_concurrency: number; run_retention: number; plugin_watch: boolean; default_cwd: string; env: Record<string, string> }
export interface RunOpts { from_block?: string; only_block?: string; stop_after?: string; base_run_id?: string | null }

const P = '/api/workflow'
const enc = encodeURIComponent
const get = <T>(p: string) => request<T>('GET', P + p)
const post = <T>(p: string, b?: unknown) => request<T>('POST', P + p, b ?? {})
const put = <T>(p: string, b: unknown) => request<T>('PUT', P + p, b)
const del = <T>(p: string) => request<T>('DELETE', P + p)

export const wfApi = {
  groups: () => get<WfGroup[]>('/groups'),
  createGroup: (name: string) => post<WfGroup>('/groups', { name }),
  reorderGroups: (ids: string[]) => put('/groups/reorder', { ids }),
  renameGroup: (id: string, name: string) => put(`/groups/${enc(id)}`, { name }),
  deleteGroup: (id: string) => del(`/groups/${enc(id)}`),
  workflows: () => get<Workflow[]>('/workflows'),
  create: (b: Partial<Workflow> & { definition?: Definition }) => post<Workflow>('/workflows', b),
  importJson: (b: Json) => post<Workflow>('/workflows/import', b),
  workflow: (id: string) => get<Workflow>(`/workflows/${enc(id)}`),
  update: (id: string, b: Partial<Workflow> & { clear_group?: boolean; definition?: Definition }) => put<Workflow>(`/workflows/${enc(id)}`, b),
  remove: (id: string) => del(`/workflows/${enc(id)}`),
  duplicate: (id: string) => post<Workflow>(`/workflows/${enc(id)}/duplicate`),
  exportJson: (id: string) => get<Json>(`/workflows/${enc(id)}/export`),
  run: (id: string, b: { inputs: Json } & RunOpts) => post<{ run_id: string; status: string }>(`/workflows/${enc(id)}/run`, b),
  runs: (q: { workflow_id?: string; finished?: boolean; limit?: number }) =>
    get<Run[]>(`/runs?limit=${q.limit || 100}${q.finished ? '&finished=true' : ''}${q.workflow_id ? `&workflow_id=${enc(q.workflow_id)}` : ''}`),
  runInfo: (id: string) => get<Run>(`/runs/${enc(id)}`),
  deleteRun: (id: string) => del(`/runs/${enc(id)}`),
  cancel: (id: string) => post(`/runs/${enc(id)}/cancel`),
  input: (id: string, values: Json) => post(`/runs/${enc(id)}/input`, { values }),
  rerun: (id: string, from?: string | null) => post<{ run_id: string }>(`/runs/${enc(id)}/rerun${from ? `?from_block=${enc(from)}` : ''}`),
  plugins: () => get<Catalog>('/plugins'),
  reloadPlugins: () => post<{ count: number; errors: Catalog['errors'] }>('/plugins/reload'),
  installDeps: (folder: string) => post('/plugins/install-deps', { folder }),
  console: () => get<{ runs: Run[]; sessions: ConsoleSession[] }>('/console'),
  settings: () => get<WfSettings>('/settings'),
  setSettings: (s: Partial<WfSettings>) => request<WfSettings>('PATCH', P + '/settings', s),
}

/** SSE run events; EventSource resumes with Last-Event-ID. Returns a close function. */
export function subscribeRun(runId: string, onEvent: (ev: RunEvent) => void, onState?: (s: string) => void) {
  const es = new EventSource(`${P}/runs/${enc(runId)}/events`)
  es.onopen = () => onState?.('open')
  es.onmessage = (m) => {
    try {
      const ev = JSON.parse(m.data) as RunEvent
      onEvent(ev)
      if (ev.type === 'run_finished') { es.close(); onState?.('done') }
    } catch { /* heartbeat */ }
  }
  es.onerror = () => onState?.(es.readyState === 2 ? 'closed' : 'reconnecting')
  return () => es.close()
}

export const workflows = signal<Workflow[]>([])
export const groups = signal<WfGroup[]>([])
export const catalog = signal<Catalog>({ plugins: [], containers: [], markers: [], errors: [] })
export async function loadHome() {
  const [w, g] = await Promise.all([wfApi.workflows(), wfApi.groups()])
  workflows.value = w; groups.value = g
}
export async function loadCatalog() { catalog.value = await wfApi.plugins() }
export function schemaMap(): Record<string, PluginSchema> {
  const m: Record<string, PluginSchema> = {}
  for (const p of [...catalog.value.plugins, ...catalog.value.containers, ...(catalog.value.markers || [])]) m[p.id] = p
  return m
}

export const STATUS_LABEL: Record<string, string> = { queued: 'Queued', running: 'Running', waiting_input: 'Waiting for input', success: 'Done', failed: 'Failed', cancelled: 'Cancelled', skipped: 'Skipped' }
export function fmtTime(ts?: number | null) {
  if (!ts) return ''
  const d = new Date(ts * 1000), now = new Date()
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
  if (d.toDateString() === now.toDateString()) return `Today ${hm}`
  if (d.toDateString() === new Date(now.getTime() - 864e5).toDateString()) return `Yesterday ${hm}`
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${hm}`
}
export function fmtSecs(sec?: number | null) {
  if (sec == null) return ''
  if (sec < 60) return `${sec.toFixed(sec < 10 ? 1 : 0)} s`
  return `${Math.floor(sec / 60)} min ${Math.round(sec % 60)} s`
}
