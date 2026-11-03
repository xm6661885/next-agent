// MCP tool call cards for the chat module. Tool names are mcp__<server>__<tool>; results are text.

import { useEffect, useState } from 'preact/hooks'
import type { ToolItem } from '../../../lib/types'
import { highlightCode, escapeHtml } from './markdown'
import { Spark } from '../../../components/crab'
import { IconChevron, IconClose } from '../../../components/icons'


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

export function ToolCard({ it }: { it: ToolItem }) {
  const [open, setOpen] = useState(false)
  const { verb, arg } = toolSummary(it.name)
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
          {it.input && Object.keys(it.input).length > 0 && <Output text={JSON.stringify(it.input, null, 2)} lang="json" />}
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
