// More Agent tool call cards. More Agents send a human title, a kind (read, edit, execute, fetch, ...) and a status,
// with results as text and diffs, so the cards are simpler than the Claude ones.

import { useEffect, useState } from 'preact/hooks'
import type { ToolItem } from '../../../lib/types'
import { highlightCode, escapeHtml } from './markdown'
import { Spark } from '../../../components/crab'
import { IconChevron, IconClose } from '../../../components/icons'
import { shortPath } from '../../../lib/util'

export interface AcpToolItem extends ToolItem {
  acp_kind?: string
  status?: string
  locations?: { path: string; line?: number }[]
  result: (ToolItem['result'] & { diffs?: { path: string; old_text: string | null; new_text: string }[] }) | null
}

const KIND_VERB: Record<string, string> = {
  read: 'Read', edit: 'Edit', delete: 'Delete', move: 'Move', search: 'Search', execute: 'Run',
  think: 'Think', fetch: 'Fetch', switch_mode: 'Switch mode', other: 'Tool',
}

function short(s: unknown, n = 90): string {
  const t = typeof s === 'string' ? s : JSON.stringify(s ?? '')
  const one = t.replace(/\s+/g, ' ').trim()
  return one.length > n ? one.slice(0, n - 1) + '…' : one
}

/** One-line summary for the card head and permission card. */
export function toolSummary(it: { name: string; acp_kind?: string; input?: any; locations?: { path: string }[] }) {
  const verb = KIND_VERB[it.acp_kind || ''] || 'Tool'
  const where = it.locations?.[0]?.path
  return { verb, arg: short(it.name || (where ? shortPath(where) : ''), 110) }
}

export function ToolCard({ it }: { it: AcpToolItem }) {
  const [open, setOpen] = useState(false)
  const { verb, arg } = toolSummary(it)
  const running = !it.result && it.status !== 'completed' && it.status !== 'failed'
  const err = !!it.result?.is_error || it.status === 'failed'
  const diffs = it.result?.diffs || []
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
          {running ? <span class="tool-wait">{it.status === 'pending' ? 'Waiting' : 'Running'}<Elapsed ts={it.ts} /></span>
            : <span>{err ? short(it.result?.content, 100) || 'Failed' : diffs.length ? `${diffs.length} file${diffs.length > 1 ? 's' : ''} changed` : short(it.result?.content, 80) || 'Done'}</span>}
        </div>
      )}
      {open && (
        <div class="tool-body">
          {it.input && Object.keys(it.input).length > 0 && <Output text={JSON.stringify(it.input, null, 2)} lang="json" />}
          {diffs.map((d, k) => <Diff key={k} d={d} />)}
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

function Diff({ d }: { d: { path: string; old_text: string | null; new_text: string } }) {
  const a = (d.old_text || '').split('\n'), b = d.new_text.split('\n')
  return (
    <div class="diff">
      <div class="tool-note mono">{shortPath(d.path)}</div>
      <div class="diff-hunk">
        {d.old_text !== null && a.map((l, i) => <div key={'a' + i} class="dl del"><span class="dm">-</span><span class="dc">{l || ' '}</span></div>)}
        {b.map((l, i) => <div key={'b' + i} class="dl add"><span class="dm">+</span><span class="dc">{l || ' '}</span></div>)}
      </div>
    </div>
  )
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
