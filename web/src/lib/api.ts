// REST helpers. All requests send the auth cookie; a 401 flips the app to the login screen.

import { authed } from './store'
import type { Agent, Attachment, ConfigForm, Importable, Meta, SearchHit, Session, Item } from './types'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', headers: {} }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError(0, 'Network error. Check your connection.')
  }
  if (res.status === 401 && path !== '/api/login') {
    authed.value = false
  }
  if (!res.ok) {
    let msg = res.statusText || `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') msg = data.detail
      else if (Array.isArray(data.detail)) msg = data.detail.map((d: any) => d.msg).join('; ')
    } catch { /* not json */ }
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const get = <T>(p: string) => request<T>('GET', p)
const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {})
const patch = <T>(p: string, b: unknown) => request<T>('PATCH', p, b)
const put = <T>(p: string, b: unknown) => request<T>('PUT', p, b)
const del = <T>(p: string) => request<T>('DELETE', p)

const enc = encodeURIComponent

export const api = {
  login: (password: string) => post<{ ok: boolean }>('/api/login', { password }),
  logout: () => post<{ ok: boolean }>('/api/logout'),
  me: () => get<{ authenticated: boolean }>('/api/me'),
  meta: () => get<Meta>('/api/meta'),

  agents: () => get<Agent[]>('/api/agents'),
  agent: (id: string) => get<Agent>(`/api/agents/${enc(id)}`),
  createAgent: (a: Partial<Agent>) => post<Agent>('/api/agents', a),
  updateAgent: (id: string, a: Partial<Agent>) => patch<Agent>(`/api/agents/${enc(id)}`, a),
  deleteAgent: (id: string) => del<{ ok: boolean }>(`/api/agents/${enc(id)}`),
  reorderAgents: (ids: string[]) => post<{ ok: boolean }>('/api/agents/reorder', { ids }),
  getClaudeMd: (id: string) => get<{ content: string; path: string; exists: boolean }>(`/api/agents/${enc(id)}/claude-md`),
  putClaudeMd: (id: string, content: string) =>
    put<{ content: string; path: string; exists: boolean }>(`/api/agents/${enc(id)}/claude-md`, { content }),
  uploadAvatar: (id: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return post<Agent>(`/api/agents/${enc(id)}/avatar`, fd)
  },
  avatarUrl: (a: Agent) => `/api/agents/${enc(a.id)}/avatar?v=${enc(a.avatar)}-${enc(String(a.order))}`,

  sessions: (agentId: string) => get<Session[]>(`/api/agents/${enc(agentId)}/sessions`),
  createSession: (agentId: string, title?: string) => post<Session>(`/api/agents/${enc(agentId)}/sessions`, { title }),
  importable: (agentId: string) => get<Importable[]>(`/api/agents/${enc(agentId)}/importable`),
  importSessions: (agentId: string, ids: string[]) =>
    post<Session[]>(`/api/agents/${enc(agentId)}/import`, { sdk_session_ids: ids }),
  searchSessions: (agentId: string, q: string) =>
    get<SearchHit[]>(`/api/agents/${enc(agentId)}/search?q=${enc(q)}`),
  deleteSessions: (ids: string[]) => post<{ ok: boolean; deleted: string[] }>('/api/sessions/delete', { ids }),
  session: (sid: string) => get<Session>(`/api/sessions/${enc(sid)}`),
  updateSession: (sid: string, p: Partial<Pick<Session, 'title' | 'overrides'>>) => patch<Session>(`/api/sessions/${enc(sid)}`, p),
  deleteSession: (sid: string, purge = false) => del<{ ok: boolean }>(`/api/sessions/${enc(sid)}${purge ? '?purge=1' : ''}`),
  sleepSession: (sid: string) => post<Session>(`/api/sessions/${enc(sid)}/sleep`, {}),
  forkSession: (sid: string, at_uuid?: string | null) => post<Session>(`/api/sessions/${enc(sid)}/fork`, { at_uuid: at_uuid ?? null }),
  items: (sid: string, before: string, limit = 200) =>
    get<{ items: Item[]; has_more: boolean }>(`/api/sessions/${enc(sid)}/items?before=${enc(before)}&limit=${limit}`),
  upload: (sid: string, files: File[], onProgress?: (p: number) => void) =>
    new Promise<Attachment[]>((resolve, reject) => {
      // XHR so we can show upload progress.
      const fd = new FormData()
      files.forEach((f) => fd.append('files', f, f.name))
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `/api/sessions/${enc(sid)}/uploads`)
      xhr.withCredentials = true
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total) }
      xhr.onload = () => {
        if (xhr.status === 401) authed.value = false
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText)) } catch { reject(new ApiError(xhr.status, 'Bad response')) }
        } else {
          let msg = `Upload failed (${xhr.status})`
          try { msg = JSON.parse(xhr.responseText).detail || msg } catch { /* ignore */ }
          reject(new ApiError(xhr.status, msg))
        }
      }
      xhr.onerror = () => reject(new ApiError(0, 'Upload failed. Check your connection.'))
      xhr.send(fd)
    }),

  status: () => get<{ live: number; max_concurrent: number; queued: number; memory_mb: number }>('/api/status'),
  config: () => get<ConfigForm>('/api/config'),
  updateConfig: (p: Partial<{ server: Partial<ConfigForm['server']>; defaults: Partial<ConfigForm['defaults']>; pricing: ConfigForm['pricing'] }>) =>
    patch<ConfigForm>('/api/config', p),
  fileUrl: (sid: string, path: string, download = false) =>
    `/api/sessions/${enc(sid)}/files?path=${enc(path)}${download ? '&download=1' : ''}`,
  getRawConfig: () => get<{ content: string }>('/api/config/raw'),
  putRawConfig: (content: string) => put<{ content: string }>('/api/config/raw', { content }),
}
