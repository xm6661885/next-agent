// CLI-style tool call cards: Bash, Read, Edit/Write (diff), Grep/Glob, TodoWrite, Task, Web, MCP.

import { useState } from 'preact/hooks'
import type { Item, ToolItem } from '../lib/types'
import { highlightCode, langFromPath, escapeHtml } from './markdown'
import { Spark } from '../components/crab'
import { IconChevron, IconCheck, IconClose } from '../components/icons'
import { shortPath } from '../lib/util'

function short(s: unknown, n = 90): string {
  const t = typeof s === 'string' ? s : JSON.stringify(s ?? '')
  const one = t.replace(/\s+/g, ' ').trim()
  return one.length > n ? one.slice(0, n - 1) + '…' : one
}

/** One-line summary shown in the card header, like the Claude Code CLI does. */
export function toolSummary(it: ToolItem): { verb: string; arg: string } {
  const i = it.input || {}
  const n = it.name
  switch (n) {
    case 'Bash': return { verb: 'Bash', arg: short(i.command, 120) }
    case 'BashOutput': return { verb: 'Read output', arg: short(i.bash_id) }
    case 'KillShell': case 'KillBash': return { verb: 'Kill shell', arg: short(i.shell_id || i.bash_id) }
    case 'Read': return { verb: 'Read', arg: shortPath(i.file_path || '') + (i.offset ? ` (from line ${i.offset})` : '') }
    case 'Write': return { verb: 'Write', arg: shortPath(i.file_path || '') }
    case 'Edit': return { verb: 'Update', arg: shortPath(i.file_path || '') }
    case 'MultiEdit': return { verb: 'Update', arg: shortPath(i.file_path || '') }
    case 'NotebookEdit': return { verb: 'Edit notebook', arg: shortPath(i.notebook_path || '') }
    case 'Grep': return { verb: 'Search', arg: `"${short(i.pattern, 60)}"${i.path ? ` in ${shortPath(i.path)}` : ''}` }
    case 'Glob': return { verb: 'Find', arg: short(i.pattern) }
    case 'WebFetch': return { verb: 'Fetch', arg: short(i.url) }
    case 'WebSearch': return { verb: 'Web search', arg: `"${short(i.query, 70)}"` }
    case 'TodoWrite': return { verb: 'Update todos', arg: '' }
    case 'Task': case 'Agent': return { verb: i.subagent_type ? `Agent: ${i.subagent_type}` : 'Agent', arg: short(i.description || i.prompt, 80) }
    case 'AskUserQuestion': return { verb: 'Question', arg: short(i.questions?.[0]?.question, 80) }
    case 'ExitPlanMode': return { verb: 'Plan ready', arg: '' }
    case 'Skill': return { verb: 'Skill', arg: short(i.skill || i.command) }
    case 'SlashCommand': return { verb: 'Command', arg: short(i.command) }
  }
  if (n.startsWith('mcp__')) {
    const [, server, ...rest] = n.split('__')
    return { verb: `${server}: ${rest.join('__')}`, arg: short(Object.values(i)[0] ?? '', 70) }
  }
  const first = Object.values(i)[0]
  return { verb: n, arg: first !== undefined ? short(first, 80) : '' }
}

function resultLines(s: string) {
  return s.split('\n').length
}

function resultSummary(it: ToolItem): string {
  const r = it.result
  if (!r) return ''
  if (r.is_error) return short(r.content, 100) || 'Error'
  const c = r.content || ''
  switch (it.name) {
    case 'Read': return `${resultLines(c)} lines`
    case 'Grep': case 'Glob': {
      const n = c.trim() ? c.trim().split('\n').length : 0
      return n ? `${n} result${n > 1 ? 's' : ''}` : 'No matches'
    }
    case 'Edit': case 'MultiEdit': case 'Write': return 'Done'
    case 'TodoWrite': return ''
    case 'Bash': return c.trim() ? short(c.trim().split('\n').slice(-1)[0], 80) : 'No output'
  }
  return c.trim() ? short(c, 80) : 'Done'
}

export function ToolCard({ it, children }: { it: ToolItem; children?: Item[] }) {
  const [open, setOpen] = useState(false)
  const { verb, arg } = toolSummary(it)
  const running = !it.result
  const err = !!it.result?.is_error
  const isTask = it.name === 'Task' || it.name === 'Agent'

  if (it.name === 'TodoWrite') return <TodoCard it={it} />

  const autoOpenable = it.name === 'Edit' || it.name === 'MultiEdit' || it.name === 'Write'
  const expanded = open
  return (
    <div class={`tool ${running ? 'running' : ''} ${err ? 'err' : ''} ${expanded ? 'open' : ''}`}>
      <button class="tool-head" onClick={() => setOpen(!open)} aria-expanded={expanded}>
        <span class="tool-bullet">{running ? <Spark size={14} /> : err ? <IconClose width={14} height={14} /> : <span class="tool-dot" />}</span>
        <span class="tool-verb">{verb}</span>
        {arg && <span class="tool-arg">{arg}</span>}
        <IconChevron class="tool-chev" width={16} height={16} />
      </button>
      {!expanded && (
        <div class="tool-sub">
          {running
            ? <span class="tool-wait">{it.streaming ? 'Preparing' : isTask ? `Working${children?.length ? ` (${children.filter((c) => c.kind === 'tool').length} steps)` : ''}` : 'Running'}</span>
            : <span>{resultSummary(it)}</span>}
          {autoOpenable && !running && !err && <DiffStat it={it} />}
        </div>
      )}
      {!expanded && isTask && running && children && children.length > 0 && (
        <div class="subagent subagent-live">
          {children.filter((c) => c.kind === 'tool').slice(-3).map((c) => <ToolCard key={c.id} it={c as ToolItem} />)}
        </div>
      )}
      {expanded && (
        <div class="tool-body">
          <ToolDetail it={it} />
          {isTask && children && children.length > 0 && (
            <div class="subagent">
              {children.map((c) => c.kind === 'tool'
                ? <ToolCard key={c.id} it={c} />
                : c.kind === 'text' ? <div key={c.id} class="subagent-text">{short(c.text, 400)}</div> : null)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function DiffStat({ it }: { it: ToolItem }) {
  const { add, del } = diffCounts(it)
  if (!add && !del) return null
  return <span class="diffstat"><span class="add">+{add}</span> <span class="del">-{del}</span></span>
}

function editsOf(it: ToolItem): { old: string; new: string }[] {
  const i = it.input || {}
  if (it.name === 'Write') return [{ old: '', new: i.content || '' }]
  if (it.name === 'MultiEdit') return (i.edits || []).map((e: any) => ({ old: e.old_string || '', new: e.new_string || '' }))
  if (it.name === 'Edit') return [{ old: i.old_string || '', new: i.new_string || '' }]
  return []
}

function diffCounts(it: ToolItem) {
  let add = 0, del = 0
  for (const e of editsOf(it)) {
    const d = lineDiff(e.old, e.new)
    add += d.filter((l) => l.t === '+').length
    del += d.filter((l) => l.t === '-').length
  }
  return { add, del }
}

/** Small LCS line diff; good enough for tool edits (falls back to replace-all for huge inputs). */
function lineDiff(a: string, b: string): { t: ' ' | '+' | '-'; s: string }[] {
  const A = a ? a.split('\n') : []
  const B = b ? b.split('\n') : []
  if (A.length * B.length > 250000) return [...A.map((s) => ({ t: '-' as const, s })), ...B.map((s) => ({ t: '+' as const, s }))]
  const m = A.length, n = B.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) for (let j = n - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const out: { t: ' ' | '+' | '-'; s: string }[] = []
  let i = 0, j = 0
  while (i < m && j < n) {
    if (A[i] === B[j]) { out.push({ t: ' ', s: A[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: '-', s: A[i++] })
    else out.push({ t: '+', s: B[j++] })
  }
  while (i < m) out.push({ t: '-', s: A[i++] })
  while (j < n) out.push({ t: '+', s: B[j++] })
  return out
}

function Diff({ it }: { it: ToolItem }) {
  const lang = langFromPath(it.input?.file_path || '')
  return (
    <div class="diff">
      {editsOf(it).map((e, k) => (
        <div key={k} class="diff-hunk">
          {lineDiff(e.old, e.new).map((l, idx) => (
            <div key={idx} class={`dl ${l.t === '+' ? 'add' : l.t === '-' ? 'del' : ''}`}>
              <span class="dm">{l.t}</span>
              <span class="dc" dangerouslySetInnerHTML={{ __html: highlightCode(l.s, lang) || '&nbsp;' }} />
            </div>
          ))}
        </div>
      ))}
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

function ToolDetail({ it }: { it: ToolItem }) {
  const i = it.input || {}
  const r = it.result
  const resultText = r?.content || ''
  const images = r?.images || []
  const imgs = images.length > 0 && <div class="tool-images">{images.map((src) => <img src={src} alt="Tool output" />)}</div>

  if (it.streaming && it.input_partial) return <Output text={it.input_partial} />

  switch (it.name) {
    case 'Bash':
      return (
        <>
          <div class="tool-cmd"><span class="prompt">$</span><code dangerouslySetInnerHTML={{ __html: highlightCode(i.command || '', 'bash') }} /></div>
          {i.description && <div class="tool-note">{i.description}</div>}
          {r && <Output text={resultText || '(no output)'} err={r.is_error} />}
        </>
      )
    case 'Edit': case 'MultiEdit': case 'Write':
      return (
        <>
          <div class="tool-note mono">{shortPath(i.file_path || '')}</div>
          <Diff it={it} />
          {r?.is_error && <Output text={resultText} err />}
        </>
      )
    case 'Read':
      return r ? <>{imgs}<Output text={resultText} lang={langFromPath(i.file_path || '')} err={r.is_error} /></> : null
    case 'Task': case 'Agent':
      return (
        <>
          {i.prompt && <div class="tool-note prewrap">{i.prompt}</div>}
          {r && <Output text={resultText} err={r.is_error} />}
        </>
      )
    case 'ExitPlanMode':
      return <div class="tool-note prewrap">{i.plan}</div>
  }
  return (
    <>
      <Output text={JSON.stringify(i, null, 2)} lang="json" />
      {imgs}
      {r && <Output text={resultText || '(empty)'} err={r.is_error} />}
    </>
  )
}

export function TodoCard({ it }: { it: ToolItem }) {
  const todos: { content: string; status: string; activeForm?: string }[] = it.input?.todos || []
  const done = todos.filter((t) => t.status === 'completed').length
  return (
    <div class="todo-card">
      <div class="todo-head">
        <span>Tasks</span>
        <span class="todo-count">{done}/{todos.length}</span>
        <span class="todo-bar"><span style={{ width: `${todos.length ? (done / todos.length) * 100 : 0}%` }} /></span>
      </div>
      <ul>
        {todos.map((t, k) => (
          <li key={k} class={t.status}>
            <span class="todo-box">
              {t.status === 'completed' ? <IconCheck width={12} height={12} /> : t.status === 'in_progress' ? <Spark size={12} /> : null}
            </span>
            <span class="todo-text">{t.status === 'in_progress' && t.activeForm ? t.activeForm : t.content}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
