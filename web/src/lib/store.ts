// Global app state (signals) and the /ws/events live feed.

import { signal } from '@preact/signals'
import type { Agent, Meta, SessionState } from './types'

export const authed = signal<boolean | null>(null)
export const agents = signal<Agent[] | null>(null)
export const meta = signal<Meta | null>(null)

export interface LiveSession {
  id: string
  agent_id: string
  state: SessionState
  pending: number
  title?: string
  updated_at?: string
  preview?: string
}

/** Session states pushed by /ws/events, keyed by session id. */
export const liveSessions = signal<Record<string, LiveSession>>({})
/** Bumped whenever the server says agent config changed; pages refetch on change. */
export const agentsVersion = signal(0)
export const sessionsVersion = signal(0)

// ---------- Toasts ----------

export interface Toast { id: number; text: string; kind: 'info' | 'error'; leaving?: boolean }
export const toasts = signal<Toast[]>([])
let toastSeq = 0

export function toast(text: string, kind: 'info' | 'error' = 'info', ms = 2600) {
  const id = ++toastSeq
  toasts.value = [...toasts.value, { id, text, kind }].slice(-3)
  setTimeout(() => {
    toasts.value = toasts.value.map((t) => (t.id === id ? { ...t, leaving: true } : t))
    setTimeout(() => { toasts.value = toasts.value.filter((t) => t.id !== id) }, 260)
  }, ms)
}

export function toastError(e: unknown) {
  toast(e instanceof Error ? e.message : String(e), 'error', 4000)
}

// ---------- Agent aggregates from live sessions ----------

export function agentLive(agentId: string) {
  let running = 0, live = 0, pending = 0
  for (const s of Object.values(liveSessions.value)) {
    if (s.agent_id !== agentId) continue
    if (s.state === 'running' || s.state === 'interrupting') running++
    if (s.state !== 'offline') live++
    pending += s.pending || 0
  }
  return { running, live, pending }
}

// ---------- /ws/events ----------

let eventsWs: WebSocket | null = null
let eventsRetry = 0
let eventsTimer: number | undefined

export function connectEvents() {
  if (eventsWs && eventsWs.readyState <= 1) return
  clearTimeout(eventsTimer)
  const ws = new WebSocket(wsUrl('/ws/events'))
  eventsWs = ws
  ws.onopen = () => { eventsRetry = 0 }
  ws.onmessage = (ev) => {
    let msg: any
    try { msg = JSON.parse(ev.data) } catch { return }
    if (msg.type === 'hello') {
      const map: Record<string, LiveSession> = {}
      for (const s of msg.sessions || []) map[s.id] = s
      liveSessions.value = map
      agentsVersion.value++
      sessionsVersion.value++
    } else if (msg.type === 'session_state') {
      const prev = liveSessions.value[msg.session_id]
      liveSessions.value = {
        ...liveSessions.value,
        [msg.session_id]: { ...prev, ...msg, id: msg.session_id },
      }
      if (!prev || prev.title !== msg.title || prev.updated_at !== msg.updated_at) sessionsVersion.value++
    } else if (msg.type === 'agents_changed') {
      agentsVersion.value++
    }
  }
  ws.onclose = (ev) => {
    if (eventsWs === ws) eventsWs = null
    if (ev.code === 4401) { authed.value = false; return }
    if (!authed.value) return
    eventsRetry = Math.min(eventsRetry + 1, 6)
    eventsTimer = window.setTimeout(connectEvents, Math.min(500 * 2 ** eventsRetry, 15000))
  }
}

export function disconnectEvents() {
  clearTimeout(eventsTimer)
  eventsWs?.close()
  eventsWs = null
}

export function wsUrl(path: string) {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`
}

// Reconnect promptly when the app comes back to the foreground (iOS suspends sockets).
if (typeof document !== 'undefined') {
  const wake = () => { if (authed.value && document.visibilityState === 'visible') connectEvents() }
  document.addEventListener('visibilitychange', wake)
  window.addEventListener('online', wake)
  window.addEventListener('pageshow', wake)
}
