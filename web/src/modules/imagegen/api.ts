// REST client for /api/imagegen/* (docs/protocol-apps.md).

import { request } from '../../lib/api'

export interface ImgFile { name: string; url: string }
export interface OutImage extends ImgFile { width: number | null; height: number | null; bytes: number }
export interface JobParams {
  n: number; size?: string; quality?: string; background?: string
  output_format?: string; output_compression?: number; moderation?: string
}
export interface Job {
  id: string; prompt: string; params: JobParams; model: string; references: ImgFile[]; mask?: ImgFile
  status: 'running' | 'done' | 'error'; error: string | null; images: OutImage[]
  created_at: number; finished_at: number | null; duration_ms: number | null; revised_prompt?: string
}
export type RefMode = 'auto' | 'edits' | 'generations'
export interface ImgSettings { api_base: string; api_key: string; models: string[]; default_model: string; reference_mode: RefMode; timeout: number }

export const imgApi = {
  settings: () => request<ImgSettings>('GET', '/api/imagegen/settings'),
  saveSettings: (s: Partial<ImgSettings>) => request<ImgSettings>('PATCH', '/api/imagegen/settings', s),
  fetchModels: () => request<{ models: string[] }>('POST', '/api/imagegen/settings/models', {}),
  test: () => request<{ ok: boolean; detail: string; models: string[] }>('POST', '/api/imagegen/settings/test', {}),
  jobs: (before = '', limit = 20) =>
    request<Job[]>('GET', `/api/imagegen/jobs?limit=${limit}${before ? `&before=${encodeURIComponent(before)}` : ''}`),
  create: (fd: FormData) => request<Job>('POST', '/api/imagegen/jobs', fd),
  retry: (id: string) => request<Job>('POST', `/api/imagegen/jobs/${encodeURIComponent(id)}/retry`, {}),
  remove: (id: string) => request<{ ok: boolean }>('DELETE', `/api/imagegen/jobs/${encodeURIComponent(id)}`),
}

/** Compose options as stored in localStorage; empty string / null means "not sent". */
export interface Opts {
  model: string; size: string; w: string; h: string; quality: string; n: number; background: string
  output_format: string; compression: number | null; moderation: string
}
export const DEFAULT_OPTS: Opts = { model: '', size: '', w: '1024', h: '1024', quality: '', n: 1, background: '', output_format: '', compression: null, moderation: '' }

/** Requested size as "W/H" for placeholders; square when auto or unknown. */
export function aspectOf(size?: string): string {
  const m = /^(\d+)x(\d+)$/.exec(size || '')
  return m ? `${m[1]} / ${m[2]}` : '1 / 1'
}
