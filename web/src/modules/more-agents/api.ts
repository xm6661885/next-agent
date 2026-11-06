// More Agents module REST client and types. Mirrors docs/protocol-more-agents.md.

import { request } from '../../lib/api'
import type { Attachment, Item } from '../../lib/types'

export interface ConfigOption { id: string; name: string; category?: string; type: 'select'; currentValue: string; options: { value: string; name: string; description?: string }[] }
export interface AgentStatus { running: number; live: number; pending: number; last_session: { id: string; title: string; updated_at: string; preview: string } | null }
export type AgentKind = 'acp' | 'codex'
export interface AgentCapabilities { images: boolean; steer: boolean; modes: boolean; local_cwd: boolean }
export interface Model { id: string; model: string; displayName: string; description: string; supportedReasoningEfforts: { reasoningEffort: string; description: string }[]; defaultReasoningEffort: string }

interface BaseAgent {
  id: string; kind: AgentKind; name: string; avatar: string; description: string; group: string
  cwd: string; as_subagent: boolean; created_at: string; order: number
  status?: AgentStatus; info?: { name: string; title?: string; version?: string } | null
  capabilities?: AgentCapabilities; recent?: MoreSession[]
}
export interface AcpAgent extends BaseAgent {
  kind: 'acp'; host: string; port: number; token: string
  config_defaults: Record<string, string>
}
export interface CodexAgent extends BaseAgent {
  kind: 'codex'; command: string; args: string[]; env: Record<string, string>
  model: string; effort: string; mode: 'full-access' | 'auto' | 'read-only'; instructions: string
}
export type MoreAgent = AcpAgent | CodexAgent
export type SessionState = 'offline' | 'connecting' | 'idle' | 'running' | 'interrupting'
export interface MoreSession {
  id: string; agent_id: string; kind: AgentKind; cwd: string; remote_id: string | null
  title: string; preview: string; created_at: string; updated_at: string; turns: number; unread: boolean; origin: string
  parent: { session_id: string; module: string; task_id: string } | null
  config_options: ConfigOption[]
  modes: { currentModeId: string; availableModes: { id: string; name: string; description?: string }[] } | null
  commands: { name: string; description?: string }[]
  usage?: { input: number; cached_input: number; output: number; reasoning: number }
  context?: { used: number; max: number }
  state: SessionState; pending: number
}
export interface Permission { id: string; session_id: string; tool_call: Record<string, any>; options: { option_id: string; name: string; kind: string }[]; created_at: string }
export interface Question { id: string; session_id: string; questions: { id: string; header: string; question: string; options: { label: string; description?: string }[]; is_other: boolean; is_secret: boolean }[]; created_at: string }
export interface AgentKindInfo { kind: AgentKind; name: string; description: string }

const enc = encodeURIComponent
const get = <T>(p: string) => request<T>('GET', p)
const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {})

export const moreAgentsApi = {
  kinds: () => get<AgentKindInfo[]>('/api/more-agents/kinds'),
  agents: () => get<MoreAgent[]>('/api/more-agents/agents'),
  agent: (id: string) => get<MoreAgent>(`/api/more-agents/agents/${enc(id)}`),
  create: (a: Partial<MoreAgent> & { kind: AgentKind; name: string }) => post<MoreAgent>('/api/more-agents/agents', a),
  update: (id: string, a: Partial<MoreAgent>) => request<MoreAgent>('PATCH', `/api/more-agents/agents/${enc(id)}`, a),
  remove: (id: string) => request<{ ok: boolean }>('DELETE', `/api/more-agents/agents/${enc(id)}`),
  reorder: (ids: string[]) => post<{ ok: boolean }>('/api/more-agents/agents/reorder', { ids }),
  settings: () => get<{ idle_timeout_min: number }>('/api/more-agents/settings'),
  setSettings: (s: { idle_timeout_min: number }) => request<{ idle_timeout_min: number }>('PATCH', '/api/more-agents/settings', s),
  groups: () => get<{ groups: string[] }>('/api/more-agents/groups'),
  setGroups: (groups: string[], renames?: Record<string, string>) => request<{ groups: string[] }>('PUT', '/api/more-agents/groups', { groups, renames }),
  test: (id: string) => post<{ ok: boolean; info?: AcpAgent['info']; config_options?: ConfigOption[]; models?: Model[]; error?: string }>(`/api/more-agents/agents/${enc(id)}/test`),
  models: (id: string) => get<Model[]>(`/api/more-agents/agents/${enc(id)}/models`),
  avatarUrl: (a: Pick<MoreAgent, 'id' | 'avatar' | 'order'>) => `/api/more-agents/agents/${enc(a.id)}/avatar?v=${enc(a.avatar)}-${a.order}`,
  uploadAvatar: (id: string, f: File) => { const fd = new FormData(); fd.append('file', f); return request<MoreAgent>('POST', `/api/more-agents/agents/${enc(id)}/avatar`, fd) },
  sessions: (id: string) => get<MoreSession[]>(`/api/more-agents/agents/${enc(id)}/sessions`),
  createSession: (id: string, cwd?: string, title?: string) => post<MoreSession>(`/api/more-agents/agents/${enc(id)}/sessions`, { cwd, title }),
  session: (sid: string) => get<MoreSession>(`/api/more-agents/sessions/${enc(sid)}`),
  updateSession: (sid: string, p: { title?: string }) => request<MoreSession>('PATCH', `/api/more-agents/sessions/${enc(sid)}`, p),
  deleteSession: (sid: string) => request<{ ok: boolean }>('DELETE', `/api/more-agents/sessions/${enc(sid)}`),
  markRead: (sid: string) => post<MoreSession>(`/api/more-agents/sessions/${enc(sid)}/read`),
  connect: (sid: string, fresh = false) => post<MoreSession>(`/api/more-agents/sessions/${enc(sid)}/connect${fresh ? '?fresh=true' : ''}`),
  sleep: (sid: string) => post<MoreSession>(`/api/more-agents/sessions/${enc(sid)}/sleep`),
  items: (sid: string, before: string, limit = 200) => get<{ items: Item[]; has_more: boolean }>(`/api/more-agents/sessions/${enc(sid)}/items?before=${enc(before)}&limit=${limit}`),
  search: (id: string, q: string) => get<{ session: MoreSession; snippet: string }[]>(`/api/more-agents/agents/${enc(id)}/search?q=${enc(q)}`),
  upload: (sid: string, files: File[], onProgress?: (p: number) => void) => uploadTo(`/api/more-agents/sessions/${enc(sid)}/uploads`, files, onProgress),
}

/** Multipart upload with progress (XHR); shared shape with the Agents and Chat upload. */
export function uploadTo(url: string, files: File[], onProgress?: (p: number) => void): Promise<Attachment[]> {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total) }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText))
      else { let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail || m } catch { /* ignore */ } reject(new Error(m)) }
    }
    xhr.onerror = () => reject(new Error('Upload failed'))
    xhr.send(fd)
  })
}

/** @deprecated Use moreAgentsApi */
export const acpApi = moreAgentsApi

/** @deprecated Use MoreSession */
export type AcpSession = MoreSession
