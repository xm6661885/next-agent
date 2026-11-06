// REST client for /api/asr/* (docs/protocol-apps.md).

import { ApiError, request } from '../../lib/api'
import { authed } from '../../lib/store'

export type Status = 'recording' | 'processing' | 'done' | 'error'
export interface Segment { seq: number; start: number; end: number; text: string; status: 'ok' | 'error'; error?: string }
export interface Progress { done: number; total: number }
export interface Summary {
  id: string; title: string; source: 'record' | 'upload'; created_at: number; duration: number; status: Status
  size: number; starred: boolean; error: string | null; progress: Progress | null; preview: string
}
export interface Recording extends Omit<Summary, 'preview'> { segments: Segment[]; text: string; edited: boolean; live?: boolean }
export interface AsrSettings {
  api_base: string; api_key: string; model: string; language: string; prompt: string; chunk_sec: number; retranscribe_on_finish: boolean
}
export interface TestResult { ok: boolean; detail: string; models: string[] }

const R = (id: string) => `/api/asr/recordings/${encodeURIComponent(id)}`

/** Raw-body POST (WAV chunks): the server reads the stream directly, so no multipart and no JSON. */
async function postRaw<T>(path: string, body: Blob): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/octet-stream' }, body })
  } catch { throw new ApiError(0, 'Network error. Check your connection.') }
  if (res.status === 401) authed.value = false
  if (!res.ok) {
    let msg = res.statusText || `Request failed (${res.status})`
    try { const d = await res.json(); if (typeof d.detail === 'string') msg = d.detail } catch { /* not json */ }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

export const asrApi = {
  settings: () => request<AsrSettings>('GET', '/api/asr/settings'),
  saveSettings: (s: Partial<AsrSettings>) => request<AsrSettings>('PATCH', '/api/asr/settings', s),
  test: () => request<TestResult>('POST', '/api/asr/settings/test', {}),

  list: (q = '') => request<Summary[]>('GET', `/api/asr/recordings${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  get: (id: string) => request<Recording>('GET', R(id)),
  create: (title: string, live = true) => request<Recording>('POST', '/api/asr/recordings', { title, live }),
  chunk: (id: string, seq: number, start: number, end: number, wav: Blob) =>
    postRaw<Segment>(`${R(id)}/chunks?seq=${seq}&start=${start.toFixed(3)}&end=${end.toFixed(3)}`, wav),
  finish: (id: string, duration: number) => request<Recording>('POST', `${R(id)}/finish`, { duration }),
  /** XHR because fetch has no upload progress. The body is the raw file. */
  upload: (file: File, onProgress: (p: number) => void) => new Promise<Recording>((resolve, reject) => {
    const x = new XMLHttpRequest()
    x.open('POST', `/api/asr/recordings/upload?filename=${encodeURIComponent(file.name)}`)
    x.setRequestHeader('Content-Type', 'application/octet-stream')
    x.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total) }
    x.onload = () => {
      if (x.status === 401) authed.value = false
      let data: any = null
      try { data = JSON.parse(x.responseText) } catch { /* ignore */ }
      if (x.status >= 200 && x.status < 300) resolve(data)
      else reject(new ApiError(x.status, (data && typeof data.detail === 'string' && data.detail) || `Upload failed (${x.status})`))
    }
    x.onerror = () => reject(new ApiError(0, 'Network error during upload.'))
    x.send(file)
  }),
  patch: (id: string, p: { title?: string; text?: string | null; reset_text?: boolean; starred?: boolean }) => request<Recording>('PATCH', R(id), p),
  remove: (id: string) => request<{ ok: boolean }>('DELETE', R(id)),
  retranscribe: (id: string) => request<Recording>('POST', `${R(id)}/retranscribe`, {}),
  retrySegment: (id: string, seq: number) => request<Segment>('POST', `${R(id)}/segments/${seq}/retry`, {}),
  audioUrl: (id: string) => `${R(id)}/audio`,
  exportUrl: (id: string, fmt: 'txt' | 'srt') => `${R(id)}/export?fmt=${fmt}`,
}

export function clock(sec: number, tenths = false): string {
  const s = Math.max(0, sec || 0)
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = Math.floor(s % 60)
  const base = h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`
  return tenths ? `${base}.${Math.floor((s * 10) % 10)}` : base
}

export function defaultTitle(): string {
  const d = new Date(), p = (n: number) => String(n).padStart(2, '0')
  return `Recording ${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function when(ts: number): string {
  const d = new Date(ts * 1000), now = new Date()
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === now.toDateString()) return `Today ${time}`
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' })} ${time}`
}
