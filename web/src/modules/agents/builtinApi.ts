// Built-in MCP REST client and types. Mirrors docs/builtin-mcp.md.

import { request } from '../../lib/api'

export interface Task {
  task_id: string; module: 'agents' | 'more_agents'; agent_id: string; session_id: string; title: string
  state: string; result: { text: string; is_error: boolean; error: string | null } | null; created_at: number
}

const enc = encodeURIComponent
export const builtinApi = {
  tasks: (sid: string) => request<Task[]>('GET', `/api/builtin/tasks?session_id=${enc(sid)}`),
}
