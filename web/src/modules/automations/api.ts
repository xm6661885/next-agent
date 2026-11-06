// Automations REST client and types. Mirrors docs/protocol-automations.md (backend branch feat/automations).

import { request } from '../../lib/api'

export type ScheduleType = 'manual' | 'cron' | 'interval' | 'webhook' | 'once'
export type OneOffState = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export interface Task {
  id: number; name: string; description: string; script: string; args: string; args_list: string[]
  schedule_type: ScheduleType; schedule_value: string | null; enabled: number
  created_at: number; updated_at: number; last_run_at: number | null; next_run_at: number | null
  running_pid: number | null; running: boolean
  task_kind: 'recurring' | 'one_off'; scheduled_at: number | null
  one_off_trigger: 'immediate' | 'scheduled' | null; one_off_state: OneOffState | null
  group_id: number | null; group_name: string | null; failure_ack_run_id: number | null
  last_exit_code: number | null; last_finished_run_id: number | null; failure_acked: boolean
}
export interface Group { id: number; name: string; task_count: number }
export interface Run { id: number; task_id: number; started_at: number; finished_at: number | null; exit_code: number | null; trigger: string; log_path: string | null }
export interface LogChunk { text: string; offset: number; done: boolean; exit_code: number | null; finished_at: number | null }
export interface AutoSettings {
  scripts_dir: string; python_bin: string; shell_bin: string; data_dir: string; poll_interval_sec: number
  webhook_secret: string; config_path: string; timezone: string; webhook_url: string
}
export interface Scripts { recurring: string[]; one_off: string[] }
export interface TaskPayload {
  name?: string; description?: string; script?: string; create_script?: 'python' | 'shell'; args?: string[]
  task_kind?: 'recurring' | 'one_off'; schedule_type?: ScheduleType; schedule_value?: string | null; enabled?: boolean
  one_off_trigger?: 'immediate' | 'scheduled'; scheduled_at_local?: string
}

const P = '/api/automations'
const get = <T>(p: string) => request<T>('GET', P + p)
const post = <T>(p: string, b?: unknown) => request<T>('POST', P + p, b ?? {})
const patch = <T>(p: string, b: unknown) => request<T>('PATCH', P + p, b)
const del = <T>(p: string) => request<T>('DELETE', P + p)

export const autoApi = {
  tasks: () => get<Task[]>('/tasks'),
  task: (id: number | string) => get<Task>(`/tasks/${id}`),
  create: (b: TaskPayload) => post<Task>('/tasks', b),
  edit: (id: number, b: TaskPayload) => patch<Task>(`/tasks/${id}`, b),
  remove: (id: number) => del<{ ok: boolean }>(`/tasks/${id}`),
  run: (id: number, b: { force?: boolean; extra_args?: string[] } = {}) => post<{ run_id: number }>(`/tasks/${id}/run`, b),
  start: (id: number) => post<{ run_id: number }>(`/tasks/${id}/start`),
  runAgain: (id: number) => post<{ run_id: number }>(`/tasks/${id}/run-again`),
  stop: (id: number) => post<{ ok: boolean }>(`/tasks/${id}/stop`),
  setEnabled: (id: number, on: boolean) => post<Task>(`/tasks/${id}/${on ? 'enable' : 'disable'}`),
  cancel: (id: number) => post<{ ok: boolean }>(`/tasks/${id}/cancel`),
  groups: () => get<Group[]>('/groups'),
  createGroup: (name: string) => post<{ id: number; name: string }>('/groups', { name }),
  renameGroup: (id: number, name: string) => patch<{ id: number; name: string }>(`/groups/${id}`, { name }),
  deleteGroup: (id: number) => del<{ moved: number }>(`/groups/${id}`),
  moveToGroup: (gid: number | null, task: number) => gid === null ? del<{ ok: boolean }>(`/tasks/${task}/group`) : post<{ ok: boolean }>(`/groups/${gid}/tasks/${task}`),
  taskRuns: (id: number, offset = 0, limit = 20) => get<Run[]>(`/tasks/${id}/runs?limit=${limit}&offset=${offset}`),
  runs: (offset = 0, limit = 30) => get<Run[]>(`/runs?limit=${limit}&offset=${offset}`),
  runInfo: (id: number | string) => get<Run>(`/runs/${id}`),
  log: (id: number | string, offset: number) => get<LogChunk>(`/runs/${id}/log?offset=${offset}`),
  failures: () => get<Task[]>('/failures'),
  ackFailures: () => post<{ ok: boolean }>('/failures/acknowledge'),
  scripts: () => get<Scripts>('/scripts'),
  settings: () => get<AutoSettings>('/settings'),
  setSettings: (b: Partial<AutoSettings>) => patch<AutoSettings>('/settings', b),
  regenerate: () => post<AutoSettings>('/settings/regenerate'),
}

export const webhookUrl = (name: string) => `${location.origin}${P}/webhook/${encodeURIComponent(name)}`
