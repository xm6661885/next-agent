// Run events -> run page state.

import type { Json, RunEvent, RunStatus } from './api'

export interface AgentLink { module: 'agents' | 'more_agents'; agent_id: string; session_id: string }
export interface StepState {
  status?: string; label?: string; path?: string; startedAt?: number; error?: string | null; iter?: string
  fields?: Record<string, Json>; default?: string; cached?: boolean; duration?: number
  logs: string[]; stream: string; sessions: AgentLink[]
}
export interface ConsoleLine { kind: 'step' | 'log' | 'text' | 'think' | 'err'; block: string | null; text: string }
export interface RunState {
  status: RunStatus; steps: Record<string, StepState>; console: ConsoleLine[]; result: Json; error: string | null
  cost: number; waiting: (Json & { block: string | null }) | null; startedAt: number | null; finishedAt: number | null
}

export const initialRun: RunState = { status: 'queued', steps: {}, console: [], result: null, error: null, cost: 0, waiting: null, startedAt: null, finishedAt: null }
const blank = (): StepState => ({ logs: [], stream: '', sessions: [] })

export function reduceRun(s: RunState, ev: RunEvent): RunState {
  const d = ev.data || {}
  const id = ev.block_id || ''
  const cur = s.steps[id] || blank()
  const step = (patch: Partial<StepState>) => ({ ...s.steps, [id]: { ...cur, ...patch } })
  const push = (line: ConsoleLine) => {
    const last = s.console[s.console.length - 1]
    if ((line.kind === 'text' || line.kind === 'think') && last && last.kind === line.kind && last.block === line.block)
      return [...s.console.slice(0, -1), { ...last, text: last.text + line.text }]
    return [...s.console, line]
  }
  switch (ev.type) {
    case 'run_queued': return { ...s, status: 'queued' }
    case 'run_started': return { ...s, status: 'running', startedAt: ev.ts }
    case 'agent_session':
      if (cur.sessions.some((x) => x.session_id === d.session_id)) return s
      return { ...s, steps: step({ sessions: [...cur.sessions, { module: d.module, agent_id: d.agent_id, session_id: d.session_id }] }) }
    case 'step_queued': return { ...s, steps: step({ status: 'queued' }) }
    case 'step_started': return { ...s, steps: step({ status: 'running', label: d.label, path: d.path, startedAt: ev.ts, error: null }), console: push({ kind: 'step', block: id, text: d.label || '' }) }
    case 'step_skipped': return { ...s, steps: step({ status: 'skipped' }) }
    case 'loop_iteration': return { ...s, steps: step({ iter: `${d.index}/${d.total}` }) }
    case 'log': return { ...s, steps: step({ logs: [...cur.logs, d.text] }), console: push({ kind: 'log', block: id, text: d.text }) }
    case 'text_delta': {
      const think = d.kind === 'thinking'
      return { ...s, steps: think ? s.steps : step({ stream: cur.stream + d.text }), console: push({ kind: think ? 'think' : 'text', block: id, text: d.text }) }
    }
    case 'step_output': return { ...s, steps: step({ status: 'success', fields: d.fields, default: d.default, cached: !!d.cached, duration: d.duration }) }
    case 'step_failed': return { ...s, steps: step({ status: 'failed', error: d.error }), console: push({ kind: 'err', block: id, text: d.error }) }
    case 'waiting_input': return { ...s, status: 'waiting_input', waiting: { ...d, block: ev.block_id } }
    case 'input_received': return { ...s, status: 'running', waiting: null }
    case 'run_finished': {
      const steps: Record<string, StepState> = {}
      for (const [k, v] of Object.entries(s.steps))
        steps[k] = v.status === 'running' || v.status === 'queued' ? { ...v, status: d.status === 'cancelled' ? 'cancelled' : 'failed' } : v
      return { ...s, steps, status: d.status, result: d.result, error: d.error, cost: d.cost_usd || s.cost, waiting: null, finishedAt: ev.ts }
    }
    default: return s
  }
}
