// Built-in MCP REST client and types. Mirrors docs/builtin-mcp.md.

import { request } from '../../lib/api'

export interface ScheduleTarget { module: 'agents' | 'acp'; agent_id: string; session: string }
export interface Schedule {
  id: string; title: string; prompt: string; cron: string | null; at: string | null
  target: ScheduleTarget; model: string; effort: string; enabled: boolean
  created_by: { module: string; agent_id: string; session_id: string } | null
  created_at: number; next_run: number | null; last_run: number | null
  last_result: { session_id: string | null; is_error: boolean; error: string | null } | null
}
export interface Task {
  task_id: string; module: 'agents' | 'acp'; agent_id: string; session_id: string; title: string
  state: string; result: { text: string; is_error: boolean; error: string | null } | null; created_at: number
}
export type ScheduleInput = Omit<Schedule, 'id' | 'created_by' | 'created_at' | 'next_run' | 'last_run' | 'last_result'>

const enc = encodeURIComponent
export const builtinApi = {
  schedules: () => request<Schedule[]>('GET', '/api/builtin/schedules'),
  createSchedule: (s: ScheduleInput) => request<Schedule>('POST', '/api/builtin/schedules', s),
  updateSchedule: (id: string, s: Partial<ScheduleInput>) => request<Schedule>('PATCH', `/api/builtin/schedules/${enc(id)}`, s),
  deleteSchedule: (id: string) => request<{ ok: true }>('DELETE', `/api/builtin/schedules/${enc(id)}`),
  runSchedule: (id: string) => request<{ session_id: string }>('POST', `/api/builtin/schedules/${enc(id)}/run`),
  tasks: (sid: string) => request<Task[]>('GET', `/api/builtin/tasks?session_id=${enc(sid)}`),
}
