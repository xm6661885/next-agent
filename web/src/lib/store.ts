// Global app state (signals) and the /ws/events live feed.

import { computed, signal } from '@preact/signals'
import type { Agent, Meta, SessionState } from './types'

export const authed = signal<boolean | null>(null)
export const agents = signal<Agent[] | null>(null)
export const meta = signal<Meta | null>(null)

export interface LiveSession {
  id: string
  agent_id: string
  state: SessionState
  pending: number
  unread?: boolean
  title?: string
  updated_at?: string
  preview?: string
}

/** Session states pushed by /ws/events, keyed by session id. */
export const liveSessions = signal<Record<string, LiveSession>>({})
/** Live states of the other modules' sessions (ACP, Chat), keyed by session id. Same shape plus `module`. */
export const moduleSessions = signal<Record<string, LiveSession & { module: string; assistant_id?: string }>>({})
export const acpVersion = signal(0)
export const chatVersion = signal(0)
export const workflowVersion = signal(0)
export const schedulesVersion = signal(0)
export const automationsVersion = signal(0)
export const asrVersion = signal(0)
export const imagegenVersion = signal(0)
/** Id from the latest asr_changed event (empty when unknown); the detail page ignores events for other recordings. */
export const lastAsrId = signal('')
/** Bumped on every session state change in any module (and agents_changed); the Running view refetches on it. */
export const runningVersion = signal(0)

/** Per-tab count of sessions that need the user (pending requests), for the tab bar dot. */
export const attention = computed(() => {
  const out = { chat: 0, agents: 0, automations: 0, workflow: 0, more: 0 }
  for (const s of Object.values(liveSessions.value)) if (s.pending) out.agents++
  for (const s of Object.values(moduleSessions.value)) if (s.pending && s.module === 'acp') out.agents++
  return out
})

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
  let running = 0, live = 0, pending = 0, unread = 0
  for (const s of Object.values(liveSessions.value)) {
    if (s.agent_id !== agentId) continue
    if (s.unread) unread++
    if (s.state === 'running' || s.state === 'interrupting') running++
    if (s.state !== 'offline') live++
    pending += s.pending || 0
  }
  return { running, live, pending, unread }
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
      const mods: Record<string, any> = {}
      for (const s of msg.acp_sessions || []) mods[s.id] = { ...s, module: 'acp' }
      for (const s of msg.chat_sessions || []) mods[s.id] = { ...s, module: 'chat' }
      moduleSessions.value = mods
      acpVersion.value++; chatVersion.value++; workflowVersion.value++; automationsVersion.value++; asrVersion.value++; imagegenVersion.value++
      agentsVersion.value++
      sessionsVersion.value++
      runningVersion.value++
    } else if (msg.type === 'session_state' && msg.module && msg.module !== 'agents') {
      runningVersion.value++
      moduleSessions.value = { ...moduleSessions.value, [msg.session_id]: { ...moduleSessions.value[msg.session_id], ...msg, id: msg.session_id } }
    } else if (msg.type === 'acp_agents_changed') { acpVersion.value++
    } else if (msg.type === 'schedules_changed') { schedulesVersion.value++
    } else if (msg.type === 'automations_changed') { automationsVersion.value++
    } else if (msg.type === 'chat_changed') { chatVersion.value++
    } else if (msg.type === 'asr_changed') { asrVersion.value++; lastAsrId.value = msg.id || ''
    } else if (msg.type === 'imagegen_changed') { imagegenVersion.value++
    } else if (msg.type === 'workflow_changed' || msg.type === 'run_state') { workflowVersion.value++
    } else if (msg.type === 'session_state') {
      // Claude sessions (module: 'agents')
      runningVersion.value++
      const prev = liveSessions.value[msg.session_id]
      liveSessions.value = {
        ...liveSessions.value,
        [msg.session_id]: { ...prev, ...msg, id: msg.session_id },
      }
      if (!prev || prev.title !== msg.title || prev.updated_at !== msg.updated_at || !!prev.unread !== !!msg.unread) sessionsVersion.value++
    } else if (msg.type === 'agents_changed') {
      agentsVersion.value++
      runningVersion.value++
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
