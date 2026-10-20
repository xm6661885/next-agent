// Artifacts: every file and code block of a conversation in one panel, plus the full-screen code viewer
// that long code cards in messages open. Files come from GET /api/sessions/{sid}/artifacts; code blocks are
// extracted from assistant text here (genui blocks excluded).

import { signal } from '@preact/signals'
import { useEffect, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { toastError, toast } from '../lib/store'
import { Segmented, Sheet } from '../components/ui'
import { IconCode, IconCopy, IconFile, IconImage } from '../components/icons'
import { copyText, fmtBytes, relTime } from '../lib/util'
import { highlightCode } from './markdown'
import { openViewer } from '../components/ImageViewer'
import type { Artifact, Item } from '../lib/types'

export interface CodeArtifact { id: string; lang: string; code: string; lines: number; ts?: string }

/** The code viewer is global so cards rendered as HTML strings can open it. */
export const codeView = signal<{ lang: string; code: string } | null>(null)

const FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)[^\n]*\n([\s\S]*?)^ {0,3}\1[ \t]*$/gm

export function extractCode(items: Item[]): CodeArtifact[] {
  const out: CodeArtifact[] = []
  for (const it of items) {
    if (it.kind !== 'text' || it.streaming) continue
    FENCE.lastIndex = 0
    let m: RegExpExecArray | null
    let n = 0
    while ((m = FENCE.exec(it.text))) {
      const lang = m[2] || ''
      if (lang === 'genui' || lang === 'math') continue
      const code = m[3].replace(/\n$/, '')
      if (!code.trim()) continue
      out.push({ id: `${it.id}:${n++}`, lang, code, lines: code.split('\n').length, ts: it.ts })
    }
  }
  return out.reverse()
}

const SOURCE: Record<Artifact['sources'][number], string> = { link: 'Shared', write: 'Created', edit: 'Edited', upload: 'Uploaded' }

/** Chat map: one line per user message and reply, tap to jump there. */
function ChatMap({ items, onJump }: { items: Item[]; onJump: (id: string) => void }) {
  const rows = items.filter((x) => !x.parent_tool_use_id && ((x.kind === 'user' && !x.queued) || (x.kind === 'text' && x.text.trim())))
  if (!rows.length) return <p class="fhint artifact-empty">Messages show up here once the chat starts.</p>
  return (
    <div class="chat-map">
      {rows.map((x) => {
        const text = (x as any).text?.replace(/```[\s\S]*?```/g, ' [code] ').replace(/\s+/g, ' ').trim() || 'Attachment'
        return (
          <button key={x.id} type="button" class={`map-row ${x.kind === 'user' ? 'me' : ''}`} onClick={() => onJump(x.id)}>
            <span class="map-bar" style={{ width: `${Math.min(100, 18 + text.length / 6)}%` }} />
            <span class="map-text">{text.slice(0, 140)}</span>
          </button>
        )
      })}
    </div>
  )
}

export function ArtifactsSheet({ open, onClose, sid, items, onJump }: { open: boolean; onClose: () => void; sid: string; items: Item[]; onJump: (id: string) => void }) {
  const [tab, setTab] = useState<'files' | 'code' | 'map'>('files')
  const [files, setFiles] = useState<Artifact[] | null>(null)
  useEffect(() => {
    if (!open) return
    api.artifacts(sid).then(setFiles).catch((e) => { toastError(e); setFiles([]) })
  }, [open, sid, items.length])
  const code = open ? extractCode(items) : []

  const openFile = (a: Artifact) => {
    if (!a.exists) return toast('This file no longer exists', 'error')
    if (a.is_image) openViewer([{ src: a.url, name: a.name, download: a.url + '&download=1' }], 0)
    else window.open(a.url, '_blank', 'noopener')
  }

  return (
    <Sheet open={open} onClose={onClose} title="Artifacts & Map">
      <Segmented value={tab} onChange={setTab}
        options={[{ value: 'files', label: `Files${files ? ` (${files.length})` : ''}` }, { value: 'code', label: `Code (${code.length})` }, { value: 'map', label: 'Map' }]} />
      <div class="artifact-list">
        {tab === 'map' ? <ChatMap items={items} onJump={(id) => { onClose(); onJump(id) }} /> : tab === 'files' ? (
          files === null ? <div class="skeleton" style={{ height: '120px', marginTop: '12px' }} />
            : files.length === 0 ? <p class="fhint artifact-empty">Files Claude creates, edits or shares, and files you upload, show up here.</p>
            : files.map((a) => (
              <button key={a.path} type="button" class={`artifact-row ${a.exists ? '' : 'missing'}`} onClick={() => openFile(a)}>
                <span class="artifact-icon">{a.is_image && a.exists ? <img src={a.url} alt="" loading="lazy" /> : a.is_image ? <IconImage /> : <IconFile />}</span>
                <span class="artifact-text">
                  <span class="artifact-name">{a.name}</span>
                  <span class="artifact-meta">{a.sources.map((s) => SOURCE[s]).join(', ')}{a.size != null ? ` · ${fmtBytes(a.size)}` : ' · missing'} · {relTime(a.last_ts)}</span>
                </span>
              </button>
            ))
        ) : code.length === 0 ? <p class="fhint artifact-empty">Code blocks from Claude's replies show up here.</p>
          : code.map((c) => (
            <button key={c.id} type="button" class="artifact-row" onClick={() => { codeView.value = { lang: c.lang, code: c.code } }}>
              <span class="artifact-icon"><IconCode /></span>
              <span class="artifact-text">
                <span class="artifact-name mono">{firstLine(c.code)}</span>
                <span class="artifact-meta">{c.lang || 'code'} · {c.lines} line{c.lines > 1 ? 's' : ''}{c.ts ? ` · ${relTime(c.ts)}` : ''}</span>
              </span>
            </button>
          ))}
      </div>
    </Sheet>
  )
}

const firstLine = (code: string) => (code.split('\n').find((l) => l.trim()) || '').trim().slice(0, 80)

export function CodeViewerHost() {
  const v = codeView.value
  return (
    <Sheet open={!!v} onClose={() => { codeView.value = null }} title={v ? `${v.lang || 'Code'} · ${v.code.split('\n').length} lines` : ''}
      actions={v && <button type="button" class="btn small" onClick={() => copyText(v.code).then(() => toast('Copied'))}><IconCopy width={16} height={16} /> Copy</button>}>
      {v && <pre class="code-viewer"><code class="hljs" dangerouslySetInnerHTML={{ __html: highlightCode(v.code, v.lang) }} /></pre>}
    </Sheet>
  )
}
