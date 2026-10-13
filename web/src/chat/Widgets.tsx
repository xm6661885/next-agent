// Declarative ```genui widgets. The first line names the widget, the rest is its body:
//   ask      JSON question card; the answer is sent as the user's next message
//   chart    JSON { type: line|bar|area|pie, x, series } drawn as SVG
//   mermaid  Mermaid diagram source (flowchart, sequence, state, gantt, timeline, ...)
//   mindmap  indented Markdown list, drawn as a Mermaid mindmap
//   svg      a static SVG, sanitized and inlined
//   html     free-form HTML/CSS/JS in a sandboxed iframe (GenUI.tsx), the only kind that runs model script
// The others run no model-written script. Anything else stays a code block.

import DOMPurify from 'dompurify'
import { useEffect, useMemo, useRef, useState } from 'preact/hooks'
import { GenUIFrame, genuiHost } from './GenUI'
import { highlightCode } from './markdown'
import { copyText } from '../lib/util'
import { IconCheck, IconQuestion } from '../components/icons'

const KINDS = ['ask', 'chart', 'mermaid', 'mindmap', 'svg', 'html'] as const
type Kind = typeof KINDS[number]

export function parseWidget(code: string): { kind: Kind | null; body: string } {
  const nl = code.indexOf('\n')
  const head = (nl < 0 ? code : code.slice(0, nl)).trim().toLowerCase()
  const body = nl < 0 ? '' : code.slice(nl + 1)
  if ((KINDS as readonly string[]).includes(head)) return { kind: head as Kind, body }
  // Tolerate a bare body: JSON with options is an ask, <svg is svg.
  const t = code.trimStart()
  if (t.startsWith('<svg')) return { kind: 'svg', body: code }
  if (t.startsWith('{') && /"options"/.test(t)) return { kind: 'ask', body: code }
  if (t.startsWith('{') && /"series"/.test(t)) return { kind: 'chart', body: code }
  if (t.startsWith('<')) return { kind: 'html', body: code }  // also older transcripts with raw HTML
  return { kind: null, body: code }
}

function json(body: string): any {
  try { return JSON.parse(body) } catch { return undefined }
}

export function GenWidget({ code, done }: { code: string; done: boolean }) {
  const { kind, body } = parseWidget(code)
  if (kind === 'html') return <GenUIFrame code={body} done={done} />
  if (kind === 'mermaid') return <Mermaid src={body} raw={body} lang="mermaid" done={done} />
  if (kind === 'mindmap') return <Mermaid src={mindmapSource(body)} raw={body} lang="markdown" done={done} />
  if (kind === 'svg') return <InlineSvg src={body} />
  if (kind === 'ask' || kind === 'chart') {
    const data = done ? json(body) : undefined
    if (!done) return <div class="gw gw-pending" aria-busy="true"><span class="gw-dot" /><span>{kind === 'ask' ? 'Preparing question' : 'Drawing chart'}</span></div>
    if (data === undefined) return <Fallback code={code} error="Invalid JSON" />
    return kind === 'ask' ? <Ask data={data} /> : <Chart data={data} />
  }
  return <Fallback code={code} error={done ? 'Unknown widget' : ''} />
}

function Fallback({ code, error }: { code: string; error: string }) {
  return (
    <div class="codeblock">
      <div class="codeblock-head"><span>genui{error ? ` · ${error}` : ''}</span><button type="button" class="copy-code" data-copy>Copy</button></div>
      <pre><code class="hljs" dangerouslySetInnerHTML={{ __html: highlightCode(code, 'json') }} /></pre>
    </div>
  )
}

// ---------- ask ----------

type Opt = { label: string; description?: string }
type Q = { question: string; header?: string; options: Opt[]; multi: boolean; other: boolean }

function normQuestions(data: any): Q[] {
  const list = Array.isArray(data) ? data : Array.isArray(data?.questions) ? data.questions : [data]
  return list.filter((q: any) => q && typeof q === 'object').map((q: any) => ({
    question: String(q.question ?? q.q ?? ''),
    header: q.header ? String(q.header) : undefined,
    options: (Array.isArray(q.options) ? q.options : []).map((o: any) =>
      typeof o === 'string' ? { label: o } : { label: String(o?.label ?? ''), description: o?.description ? String(o.description) : undefined })
      .filter((o: Opt) => o.label),
    multi: !!(q.multi ?? q.multiSelect),
    other: q.other !== false,
  })).filter((q: Q) => q.question && (q.options.length || q.other))
}

function Ask({ data }: { data: any }) {
  const qs = useMemo(() => normQuestions(data), [data])
  const [sel, setSel] = useState<string[][]>(() => qs.map(() => []))
  const [other, setOther] = useState<string[]>(() => qs.map(() => ''))
  const [sent, setSent] = useState(false)
  if (!qs.length) return <Fallback code={JSON.stringify(data, null, 2)} error="No questions" />

  const answer = (k: number) => {
    const o = other[k].trim()
    return qs[k].multi ? [...sel[k], ...(o ? [o] : [])] : o ? [o] : sel[k]
  }
  const submit = (override?: string[][]) => {
    if (sent || !genuiHost.send) return
    const picks = override || qs.map((_, k) => answer(k))
    const text = qs.length === 1 ? picks[0].join(', ') : qs.map((q, k) => `${q.question}\n${picks[k].join(', ') || '(skipped)'}`).join('\n\n')
    if (!text.trim()) return
    setSent(true)
    genuiHost.send(text)
  }
  const pick = (k: number, label: string) => {
    if (sent) return
    const q = qs[k]
    const next = sel.map((s, j) => j !== k ? s : q.multi ? (s.includes(label) ? s.filter((l) => l !== label) : [...s, label]) : [label])
    setSel(next)
    if (!q.multi) setOther(other.map((o, j) => j === k ? '' : o))
    // One single-choice question: a tap is the answer.
    if (qs.length === 1 && !q.multi) submit([[label]])
  }
  const instant = qs.length === 1 && !qs[0].multi
  const complete = qs.every((_, k) => answer(k).length)

  return (
    <div class={`ask-card gw-ask ${sent ? 'answered' : ''}`}>
      {qs.map((q, k) => (
        <div class="gw-q" key={k}>
          {(q.header || k === 0) && <div class="ask-head"><IconQuestion width={18} height={18} /><span>{q.header || 'Question'}</span>
            {sent && k === 0 && <span class="q-status">Sent</span>}</div>}
          <div class="q-text">{q.question}</div>
          <div class="q-options">
            {q.options.map((o, i) => {
              const on = sel[k].includes(o.label)
              return (
                <button key={o.label} type="button" class={`q-opt rise ${on ? 'on' : ''} ${sent ? 'static' : ''}`} style={{ '--i': i }}
                  aria-pressed={on} disabled={sent && !on} onClick={() => pick(k, o.label)}>
                  <span class={`q-mark ${q.multi ? 'square' : ''}`}>{on && <IconCheck width={12} height={12} />}</span>
                  <span class="q-opt-text"><span class="q-label">{o.label}</span>{o.description && <span class="q-desc">{o.description}</span>}</span>
                </button>
              )
            })}
            {q.other && !sent && (
              <input class="input q-other" placeholder="Something else" value={other[k]} aria-label="Other answer"
                onInput={(e) => { const v = (e.target as HTMLInputElement).value; setOther(other.map((o, j) => j === k ? v : o)); if (!q.multi && v) setSel(sel.map((s, j) => j === k ? [] : s)) }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.isComposing) submit() }} />
            )}
            {sent && other[k].trim() && <div class="q-opt on static"><span class="q-mark"><IconCheck width={12} height={12} /></span><span class="q-label">{other[k]}</span></div>}
          </div>
        </div>
      ))}
      {!sent && !(instant && !other[0].trim()) && (
        <div class="ask-actions"><span style={{ flex: 1 }} />
          <button type="button" class="btn small primary" disabled={!complete || !genuiHost.send} onClick={() => submit()}>Send</button>
        </div>
      )}
    </div>
  )
}

// ---------- chart ----------

const PALETTE = ['var(--pink-deep)', '#6f9fd8', '#e0a458', '#7cb88f', '#a58bd6', '#d77c6a']

type Series = { name: string; data: number[] }

function Chart({ data }: { data: any }) {
  const type: string = ['line', 'bar', 'area', 'pie'].includes(data?.type) ? data.type : 'line'
  const x: string[] = (Array.isArray(data?.x) ? data.x : Array.isArray(data?.labels) ? data.labels : []).map(String)
  let series: Series[] = Array.isArray(data?.series)
    ? data.series.map((s: any, i: number) => Array.isArray(s) ? { name: `Series ${i + 1}`, data: s } : { name: String(s?.name ?? `Series ${i + 1}`), data: Array.isArray(s?.data) ? s.data : [] })
    : Array.isArray(data?.values) ? [{ name: '', data: data.values }] : []
  series = series.map((s) => ({ ...s, data: s.data.map((v) => Number(v) || 0) })).filter((s) => s.data.length)
  const [hover, setHover] = useState<number | null>(null)
  if (!series.length) return <Fallback code={JSON.stringify(data, null, 2)} error="No data" />
  const unit = data?.unit ? String(data.unit) : ''
  const fmt = (v: number) => `${Math.abs(v) >= 1e6 ? +(v / 1e6).toFixed(2) + 'M' : Math.abs(v) >= 1e4 ? +(v / 1e3).toFixed(1) + 'k' : +v.toFixed(2)}${unit}`

  return (
    <figure class="gw gw-chart">
      {data?.title && <figcaption class="gw-title">{String(data.title)}</figcaption>}
      {type === 'pie' ? <Pie labels={x} values={series[0].data} fmt={fmt} /> : <XY type={type} x={x} series={series} fmt={fmt} hover={hover} setHover={setHover} />}
      {type !== 'pie' && series.length > 1 && (
        <div class="gw-legend">{series.map((s, i) => <span key={i}><i style={{ background: PALETTE[i % PALETTE.length] }} />{s.name}</span>)}</div>
      )}
    </figure>
  )
}

function niceTicks(min: number, max: number, n = 4) {
  if (min === max) { max = min + 1 }
  const raw = (max - min) / n, mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step
  const out: number[] = []
  for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10))
  return out
}

function XY({ type, x, series, fmt, hover, setHover }: { type: string; x: string[]; series: Series[]; fmt: (v: number) => string; hover: number | null; setHover: (i: number | null) => void }) {
  const n = Math.max(x.length, ...series.map((s) => s.data.length))
  const all = series.flatMap((s) => s.data)
  const ticks = niceTicks(Math.min(0, ...all), Math.max(0, ...all))
  const lo = ticks[0], hi = ticks[ticks.length - 1]
  const W = 340, H = 200, L = 40, R = 8, T = 10, B = 26
  const pw = W - L - R, ph = H - T - B
  const bar = type === 'bar'
  const cx = (i: number) => L + (bar ? (i + 0.5) * pw / n : n === 1 ? pw / 2 : i * pw / (n - 1))
  const cy = (v: number) => T + ph - (v - lo) / (hi - lo) * ph
  const every = Math.ceil(n / 6)
  const bw = Math.min(28, pw / n * 0.8 / series.length)
  const onMove = (e: PointerEvent) => {
    const svg = e.currentTarget as SVGSVGElement, r = svg.getBoundingClientRect()
    const px = (e.clientX - r.left) / r.width * W
    const i = bar ? Math.floor((px - L) / (pw / n)) : Math.round((px - L) / (pw / Math.max(1, n - 1)))
    setHover(i >= 0 && i < n ? i : null)
  }
  return (
    <div class="gw-plot">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)}>
        {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={cy(t)} y2={cy(t)} class="gw-grid" /><text x={L - 5} y={cy(t) + 3.5} class="gw-ax" text-anchor="end">{fmt(t)}</text></g>)}
        {Array.from({ length: n }, (_, i) => i % every === 0 && <text key={i} x={cx(i)} y={H - 8} class="gw-ax" text-anchor="middle">{(x[i] ?? '').slice(0, 10)}</text>)}
        {hover !== null && !bar && <line x1={cx(hover)} x2={cx(hover)} y1={T} y2={T + ph} class="gw-cursor" />}
        {series.map((s, k) => {
          const c = PALETTE[k % PALETTE.length]
          if (bar) return <g key={k} fill={c}>{s.data.map((v, i) => {
            const x0 = cx(i) - bw * series.length / 2 + k * bw, y0 = cy(Math.max(0, v)), h = Math.abs(cy(v) - cy(0))
            return <rect key={i} x={x0 + 1} y={y0} width={bw - 2} height={Math.max(1, h)} rx={3} opacity={hover === null || hover === i ? 1 : 0.45} />
          })}</g>
          const pts = s.data.map((v, i) => `${cx(i)},${cy(v)}`).join(' ')
          return <g key={k}>
            {type === 'area' && <polygon points={`${cx(0)},${cy(0)} ${pts} ${cx(s.data.length - 1)},${cy(0)}`} fill={c} opacity={0.18} />}
            <polyline points={pts} fill="none" stroke={c} stroke-width={2.2} stroke-linejoin="round" stroke-linecap="round" />
            {s.data.length <= 24 && s.data.map((v, i) => <circle key={i} cx={cx(i)} cy={cy(v)} r={hover === i ? 4.5 : 2.6} fill={c} />)}
          </g>
        })}
      </svg>
      {hover !== null && (
        <div class="gw-tip">
          <b>{x[hover] ?? `#${hover + 1}`}</b>
          {series.map((s, k) => s.data[hover] !== undefined && <span key={k}><i style={{ background: PALETTE[k % PALETTE.length] }} />{series.length > 1 ? `${s.name} ` : ''}{fmt(s.data[hover])}</span>)}
        </div>
      )}
    </div>
  )
}

function Pie({ labels, values, fmt }: { labels: string[]; values: number[]; fmt: (v: number) => string }) {
  const total = values.reduce((a, v) => a + Math.max(0, v), 0) || 1
  let a0 = -Math.PI / 2
  const arcs = values.map((v, i) => {
    const a1 = a0 + Math.max(0, v) / total * Math.PI * 2
    const big = a1 - a0 > Math.PI ? 1 : 0
    const p = (a: number, r: number) => `${60 + r * Math.cos(a)},${60 + r * Math.sin(a)}`
    const d = values.length === 1 ? 'M60,8 A52,52 0 1 1 59.99,8 L60,30 A30,30 0 1 0 60.01,30 Z'
      : `M${p(a0, 52)} A52,52 0 ${big} 1 ${p(a1, 52)} L${p(a1, 30)} A30,30 0 ${big} 0 ${p(a0, 30)} Z`
    a0 = a1
    return <path key={i} d={d} fill={PALETTE[i % PALETTE.length]} />
  })
  return (
    <div class="gw-pie">
      <svg viewBox="0 0 120 120" role="img">{arcs}</svg>
      <div class="gw-legend col">{values.map((v, i) => <span key={i}><i style={{ background: PALETTE[i % PALETTE.length] }} />{labels[i] ?? `#${i + 1}`}<em>{fmt(v)} · {Math.round(Math.max(0, v) / total * 100)}%</em></span>)}</div>
    </div>
  )
}

// ---------- mermaid ----------

/** `- a\n  - b` (or plain indented lines) to Mermaid mindmap syntax. */
export function mindmapSource(body: string) {
  const lines = body.split('\n').filter((l) => l.trim())
  const out = ['mindmap']
  lines.forEach((l, i) => {
    const indent = l.match(/^\s*/)![0].replace(/\t/g, '  ').length
    let text = l.trim().replace(/^([-*+]|\d+[.)])\s+/, '').replace(/^#+\s*/, '').replace(/[()[\]{}]/g, ' ').trim()
    if (!text) return
    out.push(`${' '.repeat(2 + (i === 0 ? 0 : indent + 2))}${i === 0 ? `root((${text}))` : text}`)
  })
  return out.join('\n')
}

let mermaidLib: Promise<any> | null = null
let themeKey = ''
let renderSeq = 0

function cssVar(cs: CSSStyleDeclaration, name: string) { return cs.getPropertyValue(name).trim() }

async function loadMermaid() {
  mermaidLib ||= import('mermaid').then((m) => m.default)
  const mermaid = await mermaidLib
  const cs = getComputedStyle(document.documentElement)
  const dark = matchMedia('(prefers-color-scheme: dark)').matches
  const key = dark ? 'dark' : 'light'
  if (key !== themeKey) {
    themeKey = key
    const text = cssVar(cs, '--text'), surface = cssVar(cs, '--surface'), surface2 = cssVar(cs, '--surface-2') || surface
    mermaid.initialize({
      startOnLoad: false, securityLevel: 'strict', theme: 'base', darkMode: dark,
      fontFamily: cssVar(cs, '--font-sans'), fontSize: 14,
      themeVariables: {
        darkMode: dark, background: 'transparent', fontFamily: cssVar(cs, '--font-sans'),
        primaryColor: dark ? '#4a3a3e' : '#fde4e9', primaryTextColor: text, primaryBorderColor: cssVar(cs, '--pink-deep') || '#f19bb0',
        secondaryColor: surface2, tertiaryColor: surface, lineColor: cssVar(cs, '--text-2'), textColor: text,
        mainBkg: dark ? '#4a3a3e' : '#fde4e9', nodeBorder: cssVar(cs, '--pink-deep') || '#f19bb0', clusterBkg: surface2,
        noteBkgColor: surface2, noteTextColor: text, actorBkg: dark ? '#4a3a3e' : '#fde4e9', actorTextColor: text,
        edgeLabelBackground: surface,
      },
      flowchart: { htmlLabels: false, curve: 'basis', useMaxWidth: true },
      mindmap: { useMaxWidth: true }, sequence: { useMaxWidth: true }, gantt: { useMaxWidth: true },
    })
  }
  return mermaid
}

function Mermaid({ src, raw, lang, done }: { src: string; raw: string; lang: string; done: boolean }) {
  const [code, setCode] = useState(false)
  const [copied, setCopied] = useState(false)
  const [svg, setSvg] = useState('')
  const [error, setError] = useState('')
  const [scheme, setScheme] = useState(0)
  const timer = useRef<number>()
  useEffect(() => {
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const on = () => setScheme((n) => n + 1)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  useEffect(() => {
    let live = true
    clearTimeout(timer.current)
    // While streaming, try every ~400ms and keep the last diagram that parsed.
    timer.current = window.setTimeout(async () => {
      try {
        const mermaid = await loadMermaid()
        if (!done && !(await mermaid.parse(src, { suppressErrors: true }))) return
        const out = await mermaid.render(`gw-mmd-${++renderSeq}`, src)
        if (live) { setSvg(out.svg); setError('') }
      } catch (e) {
        if (live && done) setError(String((e as Error)?.message || e).split('\n')[0])
      } finally {
        document.querySelectorAll('body > [id^="dgw-mmd-"]').forEach((n) => n.remove())
      }
    }, done ? 0 : 400)
    return () => { live = false; clearTimeout(timer.current) }
  }, [src, done, scheme])
  if (error && !svg) return <Fallback code={src} error="Diagram error" />
  if (!svg) return <div class="gw gw-pending" aria-busy="true"><span class="gw-dot" /><span>Drawing diagram</span></div>
  const copy = () => copyText(raw).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1400) })
  return (
    <div class={`gw gw-diagram ${done ? '' : 'drawing'}`}>
      {done && (
        <div class="gw-tools">
          <button type="button" class="gw-tool" onClick={() => setCode(!code)}>{code ? 'Diagram' : 'Source'}</button>
          <button type="button" class="gw-tool" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        </div>
      )}
      {code
        ? <pre class="gw-src"><code class="hljs" dangerouslySetInnerHTML={{ __html: highlightCode(raw, lang) }} /></pre>
        : <div role="img" dangerouslySetInnerHTML={{ __html: svg }} />}
    </div>
  )
}

// ---------- svg ----------

function InlineSvg({ src }: { src: string }) {
  const html = useMemo(() => {
    const cut = src.replace(/<[^>]*$/, '')
    return DOMPurify.sanitize(cut, { USE_PROFILES: { svg: true, svgFilters: true }, FORBID_TAGS: ['foreignObject', 'script'] })
  }, [src])
  return <div class="gw gw-svg" dangerouslySetInnerHTML={{ __html: html }} />
}
