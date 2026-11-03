// Chat module REST client and types. Mirrors docs/protocol-chat.md.

import { request } from '../../lib/api'
import type { Item } from '../../lib/types'
import { uploadTo } from '../acp/api'

export type Effort = 'off' | 'low' | 'medium' | 'high' | 'max'
export const EFFORTS: Effort[] = ['off', 'low', 'medium', 'high', 'max']
export const DEFAULT_ASSISTANT = '_default'

export interface Provider { id: string; name: string; format: 'openai' | 'anthropic'; base_url: string; api_key: string; api_key_set?: boolean; models: string[]; headers: Record<string, string> }
export interface ChatDefaults { model: string; effort: Effort; system_prompt: string; temperature: number; max_tokens: number; mcp: string[]; title_model: string }
export type McpServer = { type?: 'stdio'; command: string; args?: string[]; env?: Record<string, string> } | { type: 'http' | 'sse'; url: string; headers?: Record<string, string> }
export interface ChatConfig { defaults: ChatDefaults; providers: Provider[]; mcp_servers: Record<string, McpServer> }
export interface ModelRef { id: string; provider: string; model: string; format: string }
export interface ChatMeta { models: ModelRef[]; efforts: Effort[]; defaults: ChatDefaults; mcp_servers: string[] }
export interface Assistant {
  id: string; name: string; avatar: string; description: string; model: string; effort: Effort | ''
  system_prompt: string; temperature: number; mcp: string[]; created_at?: string; order: number
  status?: { running: number; last_session: { id: string; title: string; updated_at: string; preview: string } | null }
}
export interface ChatSession {
  id: string; assistant_id: string; title: string; preview: string; created_at: string; updated_at: string
  overrides: { model: string | null; effort: Effort | null }; mcp: string[]; usage: { input: number; output: number }
  unread: boolean; state: 'idle' | 'running'
}

const enc = encodeURIComponent
const get = <T>(p: string) => request<T>('GET', p)
const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {})
const patch = <T>(p: string, b: unknown) => request<T>('PATCH', p, b)

export const chatApi = {
  meta: () => get<ChatMeta>('/api/chat/meta'),
  config: () => get<ChatConfig>('/api/chat/config'),
  saveConfig: (c: Partial<ChatConfig>) => patch<ChatConfig>('/api/chat/config', c),
  testProvider: (id: string) => post<{ ok: boolean; error?: string; models?: string[] }>(`/api/chat/providers/${enc(id)}/test`),
  assistants: () => get<Assistant[]>('/api/chat/assistants'),
  assistant: (id: string) => get<Assistant>(`/api/chat/assistants/${enc(id)}`),
  create: (a: Partial<Assistant>) => post<Assistant>('/api/chat/assistants', a),
  update: (id: string, a: Partial<Assistant>) => patch<Assistant>(`/api/chat/assistants/${enc(id)}`, a),
  remove: (id: string) => request<{ ok: boolean }>('DELETE', `/api/chat/assistants/${enc(id)}`),
  reorder: (ids: string[]) => post<{ ok: boolean }>('/api/chat/assistants/reorder', { ids }),
  avatarUrl: (a: Pick<Assistant, 'id' | 'avatar' | 'order'>) => `/api/chat/assistants/${enc(a.id)}/avatar?v=${enc(a.avatar)}-${a.order}`,
  uploadAvatar: (id: string, f: File) => { const fd = new FormData(); fd.append('file', f); return request<Assistant>('POST', `/api/chat/assistants/${enc(id)}/avatar`, fd) },
  sessions: (id: string) => get<ChatSession[]>(`/api/chat/assistants/${enc(id)}/sessions`),
  createSession: (id: string, title?: string) => post<ChatSession>(`/api/chat/assistants/${enc(id)}/sessions`, { title }),
  session: (sid: string) => get<ChatSession>(`/api/chat/sessions/${enc(sid)}`),
  updateSession: (sid: string, p: Partial<Pick<ChatSession, 'title' | 'overrides' | 'mcp'>>) => patch<ChatSession>(`/api/chat/sessions/${enc(sid)}`, p),
  deleteSession: (sid: string) => request<{ ok: boolean }>('DELETE', `/api/chat/sessions/${enc(sid)}`),
  markRead: (sid: string) => post<ChatSession>(`/api/chat/sessions/${enc(sid)}/read`),
  items: (sid: string, before: string, limit = 200) => get<{ items: Item[]; has_more: boolean }>(`/api/chat/sessions/${enc(sid)}/items?before=${enc(before)}&limit=${limit}`),
  search: (id: string, q: string) => get<{ session: ChatSession; snippet: string }[]>(`/api/chat/assistants/${enc(id)}/search?q=${enc(q)}`),
  upload: (sid: string, files: File[], onProgress?: (p: number) => void) => uploadTo(`/api/chat/sessions/${enc(sid)}/uploads`, files, onProgress),
}

/** "<provider>/<model>" -> the model part, for chips. */
export const modelLabel = (id: string) => id.includes('/') ? id.slice(id.indexOf('/') + 1) : id
