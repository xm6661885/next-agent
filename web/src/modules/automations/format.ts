// Display helpers: schedules in plain words, relative times, exit badges, argument splitting.

import type { Run, Task } from './api'

const pad = (n: number) => String(n).padStart(2, '0')
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const hm = (h: string, m: string) => `${pad(Number(h))}:${pad(Number(m))}`
const num = (s: string) => /^\d+$/.test(s)

/** Plain-words version of common cron patterns; unknown patterns fall back to the raw expression. */
export function describeCron(expr: string): string {
  const f = expr.trim().split(/\s+/)
  if (f.length !== 5) return `Cron ${expr.trim()}`
  const [m, h, dom, mon, dow] = f
  const step = /^\*\/(\d+)$/.exec(m)
  if (step && h === '*' && dom === '*' && mon === '*' && dow === '*') return `Every ${step[1]} min`
  if (m === '*' && h === '*' && dom === '*' && mon === '*' && dow === '*') return 'Every minute'
  if (num(m) && h === '*' && dom === '*' && mon === '*' && dow === '*') return m === '0' ? 'Every hour' : `Every hour at :${pad(Number(m))}`
  if (num(m) && num(h) && mon === '*') {
    if (dom === '*' && dow === '*') return `Every day at ${hm(h, m)}`
    if (dom === '*' && dow === '1-5') return `Weekdays at ${hm(h, m)}`
    if (dom === '*' && dow === '0,6') return `Weekends at ${hm(h, m)}`
    if (dom === '*' && /^[0-7]$/.test(dow)) return `Every ${DAYS[Number(dow) % 7]} at ${hm(h, m)}`
    if (num(dom) && dow === '*') return `Monthly on day ${dom} at ${hm(h, m)}`
  }
  return `Cron ${expr.trim()}`
}

export function describeInterval(v: string | null): string {
  const s = Number(v)
  if (!s || s < 0) return 'Interval'
  if (s % 3600 === 0) return `Every ${s / 3600} h`
  if (s % 60 === 0) return `Every ${s / 60} min`
  return `Every ${s} s`
}

export function fmtDateTime(ts: number | null | undefined): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function describeSchedule(t: Task): string {
  if (t.task_kind === 'one_off') return t.one_off_trigger === 'scheduled' && t.scheduled_at ? `Once at ${fmtDateTime(t.scheduled_at)}` : 'Run now'
  switch (t.schedule_type) {
    case 'cron': return describeCron(t.schedule_value || '')
    case 'interval': return describeInterval(t.schedule_value)
    case 'webhook': return 'Webhook'
    default: return 'Manual'
  }
}

/** Relative time in either direction: "in 5m", "3h ago". */
export function relWhen(ts: number | null | undefined): string {
  if (!ts) return ''
  const s = Math.round((ts * 1000 - Date.now()) / 1000)
  const a = Math.abs(s)
  const unit = a < 45 ? '' : a < 3300 ? `${Math.round(a / 60)}m` : a < 86400 ? `${Math.round(a / 3600)}h` : `${Math.round(a / 86400)}d`
  if (!unit) return s >= 0 ? 'in a moment' : 'just now'
  return s >= 0 ? `in ${unit}` : `${unit} ago`
}

export function fmtSpan(start: number, end: number | null): string {
  if (!end) return ''
  const s = Math.max(0, Math.round(end - start))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

export type Outcome = { kind: 'running' | 'ok' | 'failed' | 'never' | 'pending' | 'cancelled'; label: string }

export function taskOutcome(t: Task): Outcome {
  if (t.running || t.one_off_state === 'running') return { kind: 'running', label: 'Running' }
  if (t.one_off_state === 'pending') return { kind: 'pending', label: 'Pending' }
  if (t.one_off_state === 'cancelled') return { kind: 'cancelled', label: 'Cancelled' }
  if (t.last_finished_run_id === null || t.last_run_at === null) return { kind: 'never', label: 'Never run' }
  if (t.last_exit_code === 0) return { kind: 'ok', label: 'OK' }
  return { kind: 'failed', label: t.last_exit_code === null ? 'Failed' : `Failed (${t.last_exit_code})` }
}

export function runOutcome(r: Pick<Run, 'finished_at' | 'exit_code'>): Outcome {
  if (!r.finished_at) return { kind: 'running', label: 'Running' }
  if (r.exit_code === 0) return { kind: 'ok', label: 'OK' }
  return { kind: 'failed', label: r.exit_code === null ? 'Abnormal' : `Exit ${r.exit_code}` }
}

export const TRIGGER_LABEL: Record<string, string> = {
  manual: 'Manual', cron: 'Cron', interval: 'Interval', webhook: 'Webhook', once_scheduled: 'Scheduled', once_immediate: 'Immediate',
}

/** Split a line into arguments, honoring single and double quotes. */
export function splitArgs(s: string): string[] {
  const out: string[] = []
  const re = /"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(s))) out.push(m[1] !== undefined ? m[1].replace(/\\(.)/g, '$1') : m[2] !== undefined ? m[2] : m[3])
  return out
}

export const isOneOff = (t: Task) => t.task_kind === 'one_off'
