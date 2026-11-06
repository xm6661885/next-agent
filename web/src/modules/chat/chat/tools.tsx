// MCP tool call cards for the chat module. Tool names are mcp__<server>__<tool>; results are text.

import { useEffect, useState } from 'preact/hooks'
import type { ToolItem } from '../../../lib/types'
import { highlightCode, escapeHtml } from './markdown'
import { Spark } from '../../../components/crab'
import { IconBrain, IconChevron, IconClose } from '../../../components/icons'
import { navigate, route } from '../../../lib/router'


function short(s: unknown, n = 90): string {
  const t = typeof s === 'string' ? s : JSON.stringify(s ?? '')
  const one = t.replace(/\s+/g, ' ').trim()
  return one.length > n ? one.slice(0, n - 1) + '…' : one
}

/** "mcp__fetch__get" -> server "fetch", tool "get". */
export function toolSummary(name: string) {
  const m = /^mcp__(.+?)__(.+)$/.exec(name)
  return m ? { verb: m[2], arg: m[1] } : { verb: name, arg: '' }
}

const MEMORY_TOOLS = ['memory_add', 'memory_update', 'memory_delete']

/** Compact one-line descriptions for the local file tools. */
function fileSummary(it: ToolItem): { verb: string; arg: string } | null {
  const inp = it.input || {}
  if (it.name === 'file_read') {
    const from = Number(inp.offset) > 0 ? Number(inp.offset) : 1
    const out = (it.result?.content || '').split('\n').slice(1).filter(Boolean).length
    const to = out > 0 ? from + out - 1 : from + (Number(inp.limit) > 0 ? Number(inp.limit) : 400) - 1
    return { verb: `Read ${inp.name || 'file'}`, arg: `lines ${from}-${to}` }
  }
  if (it.name === 'file_search') return { verb: 'Searched files for', arg: short(inp.query, 60) }
  return null
}

function MemoryNote({ it }: { it: ToolItem }) {
  const inp = it.input || {}
  const text = it.name === 'memory_delete' ? `Forgot ${short(inp.id, 40)}` : it.name === 'memory_update' ? 'Updated memory' : `Saved to memory: ${short(inp.text, 120)}`
  const r = route.value
  const aid = r.name === 'llm-chat' ? r.assistantId : ''
  return (
    <div class="mem-note">
      <IconBrain width={15} height={15} />
      <span class="mem-note-text">{text}{it.name === 'memory_update' && inp.text ? `: ${short(inp.text, 100)}` : ''}</span>
      {aid && <button type="button" class="mem-note-link" onClick={() => navigate({ name: 'assistant-memory', assistantId: aid })}>Open memory</button>}
    </div>
  )
}

export function ToolCard({ it }: { it: ToolItem }) {
  const [open, setOpen] = useState(false)
  if (MEMORY_TOOLS.includes(it.name) && it.result && !it.result.is_error) return <MemoryNote it={it} />
  const fs = fileSummary(it)
  const { verb, arg } = fs || toolSummary(it.name)
  const running = !it.result
  const err = !!it.result?.is_error
  return (
    <div class={`tool ${running ? 'running' : ''} ${err ? 'err' : ''} ${open ? 'open' : ''}`}>
      <button class="tool-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span class="tool-bullet">{running ? <Spark size={14} /> : err ? <IconClose width={14} height={14} /> : <span class="tool-dot" />}</span>
        <span class="tool-verb">{verb}</span>
        {arg && <span class="tool-arg">{arg}</span>}
        <IconChevron class="tool-chev" width={16} height={16} />
      </button>
      {!open && (
        <div class="tool-sub">
          {running ? <span class="tool-wait">Running<Elapsed ts={it.ts} /></span>
            : <span>{err ? short(it.result?.content, 100) || 'Failed' : short(it.result?.content, 80) || 'Done'}</span>}
        </div>
      )}
      {open && (
        <div class="tool-body">
          {!fs && it.input && Object.keys(it.input).length > 0 && <Output text={JSON.stringify(it.input, null, 2)} lang="json" />}
          {it.result?.content && <Output text={it.result.content} err={err} />}
        </div>
      )}
    </div>
  )
}

function Elapsed({ ts }: { ts?: string }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  const s = ts ? Math.round((now - Date.parse(ts)) / 1000) : 0
  return s >= 2 ? <> for {s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`}</> : null
}

function Output({ text, lang, err }: { text: string; lang?: string; err?: boolean }) {
  const [all, setAll] = useState(false)
  const lines = text.split('\n')
  const cut = !all && lines.length > 40
  const shown = cut ? lines.slice(0, 40).join('\n') : text
  return (
    <div class={`tool-out ${err ? 'err' : ''}`}>
      <pre><code dangerouslySetInnerHTML={{ __html: lang ? highlightCode(shown, lang) : escapeHtml(shown) }} /></pre>
      {cut && <button class="show-more" onClick={() => setAll(true)}>Show all {lines.length} lines</button>}
    </div>
  )
}
