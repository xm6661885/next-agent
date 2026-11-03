// ACP module REST client and types. Mirrors docs/protocol-acp.md.

import { request } from '../../lib/api'
import type { Attachment, Item } from '../../lib/types'

export interface ConfigOption { id: string; name: string; category?: string; type: 'select'; currentValue: string; options: { value: string; name: string; description?: string }[] }
export interface AcpStatus { running: number; live: number; pending: number; last_session: { id: string; title: string; updated_at: string; preview: string } | null }
export interface AcpAgent {
  id: string; kind: 'acp'; name: string; avatar: string; description: string; group: string
  host: string; port: number; token: string; token_set: boolean; cwd: string
  config_defaults: Record<string, string>; as_subagent: boolean; created_at: string; order: number
  status?: AcpStatus; info?: { name: string; title?: string; version?: string } | null
}
export type AcpState = 'offline' | 'connecting' | 'idle' | 'running' | 'interrupting'
export interface AcpSession {
  id: string; agent_id: string; remote_id: string | null; title: string; preview: string
  created_at: string; updated_at: string; turns: number; unread: boolean; origin: string
  parent: { session_id: string; module: string; task_id: string } | null
  config_options: ConfigOption[]; modes: { currentModeId: string; availableModes: { id: string; name: string }[] } | null
  commands: { name: string; description?: string }[]; state: AcpState; pending: number
}
export interface AcpPermission { id: string; session_id: string; tool_call: Record<string, any>; options: { option_id: string; name: string; kind: string }[]; created_at: string }

const enc = encodeURIComponent
const get = <T>(p: string) => request<T>('GET', p)
const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {})

export const acpApi = {
  agents: () => get<AcpAgent[]>('/api/acp/agents'),
  agent: (id: string) => get<AcpAgent>(`/api/acp/agents/${enc(id)}`),
  create: (a: Partial<AcpAgent>) => post<AcpAgent>('/api/acp/agents', a),
  update: (id: string, a: Partial<AcpAgent>) => request<AcpAgent>('PATCH', `/api/acp/agents/${enc(id)}`, a),
  remove: (id: string) => request<{ ok: boolean }>('DELETE', `/api/acp/agents/${enc(id)}`),
  reorder: (ids: string[]) => post<{ ok: boolean }>('/api/acp/agents/reorder', { ids }),
  settings: () => get<{ idle_timeout_min: number }>('/api/acp/settings'),
  setSettings: (s: { idle_timeout_min: number }) => request<{ idle_timeout_min: number }>('PATCH', '/api/acp/settings', s),
  groups: () => get<{ groups: string[] }>('/api/acp/groups'),
  setGroups: (groups: string[], renames?: Record<string, string>) => request<{ groups: string[] }>('PUT', '/api/acp/groups', { groups, renames }),
  test: (id: string) => post<{ ok: boolean; info?: AcpAgent['info']; config_options?: ConfigOption[]; error?: string }>(`/api/acp/agents/${enc(id)}/test`),
  avatarUrl: (a: Pick<AcpAgent, 'id' | 'avatar' | 'order'>) => `/api/acp/agents/${enc(a.id)}/avatar?v=${enc(a.avatar)}-${a.order}`,
  uploadAvatar: (id: string, f: File) => { const fd = new FormData(); fd.append('file', f); return request<AcpAgent>('POST', `/api/acp/agents/${enc(id)}/avatar`, fd) },
  sessions: (id: string) => get<AcpSession[]>(`/api/acp/agents/${enc(id)}/sessions`),
  createSession: (id: string, title?: string) => post<AcpSession>(`/api/acp/agents/${enc(id)}/sessions`, { title }),
  session: (sid: string) => get<AcpSession>(`/api/acp/sessions/${enc(sid)}`),
  updateSession: (sid: string, p: { title?: string }) => request<AcpSession>('PATCH', `/api/acp/sessions/${enc(sid)}`, p),
  deleteSession: (sid: string) => request<{ ok: boolean }>('DELETE', `/api/acp/sessions/${enc(sid)}`),
  markRead: (sid: string) => post<AcpSession>(`/api/acp/sessions/${enc(sid)}/read`),
  sleep: (sid: string) => post<AcpSession>(`/api/acp/sessions/${enc(sid)}/sleep`),
  items: (sid: string, before: string, limit = 200) => get<{ items: Item[]; has_more: boolean }>(`/api/acp/sessions/${enc(sid)}/items?before=${enc(before)}&limit=${limit}`),
  search: (id: string, q: string) => get<{ session: AcpSession; snippet: string }[]>(`/api/acp/agents/${enc(id)}/search?q=${enc(q)}`),
  upload: (sid: string, files: File[], onProgress?: (p: number) => void) => uploadTo(`/api/acp/sessions/${enc(sid)}/uploads`, files, onProgress),
}

/** Multipart upload with progress (XHR); shared shape with the Agents upload. */
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
