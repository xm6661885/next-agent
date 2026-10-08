// Markdown -> sanitized HTML with lazy syntax highlighting, KaTeX math (loaded on first use),
// and file:// links from Claude turned into previews and download cards.

import { Marked, type TokenizerAndRendererExtension } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'
import { signal } from '@preact/signals'

// ---------- Math ----------

type Katex = typeof import('katex').default
let katex: Katex | null = null
let katexLoading = false
/** Bumped when KaTeX finishes loading so rendered messages refresh. */
export const mathVersion = signal(0)

function loadKatex() {
  if (katex || katexLoading) return
  katexLoading = true
  Promise.all([import('katex'), import('katex/dist/katex.min.css')]).then(([m]) => {
    katex = m.default
    cache.clear()
    mathVersion.value++
  }).catch(() => { katexLoading = false })
}

function tex(src: string, display: boolean) {
  if (!katex) {
    loadKatex()
    return `<span class="math-pending${display ? ' display' : ''}">${escapeHtml(src)}</span>`
  }
  try {
    const html = katex.renderToString(src, { displayMode: display, throwOnError: false, output: 'html', strict: 'ignore' })
    return display ? `<span class="math-display">${html}</span>` : html
  } catch {
    return `<code>${escapeHtml(src)}</code>`
  }
}

const mathBlock: TokenizerAndRendererExtension = {
  name: 'mathBlock',
  level: 'block',
  start(src) { const i = src.search(/^ {0,3}(\$\$|\\\[)/m); return i < 0 ? undefined : i },
  tokenizer(src) {
    const m = /^ {0,3}\$\$([\s\S]+?)\$\$[ \t]*(?:\n|$)/.exec(src) || /^ {0,3}\\\[([\s\S]+?)\\\][ \t]*(?:\n|$)/.exec(src)
    if (m) return { type: 'mathBlock', raw: m[0], text: m[1].trim() }
  },
  renderer(t) { return tex(t.text, true) },
}

const mathInline: TokenizerAndRendererExtension = {
  name: 'mathInline',
  level: 'inline',
  start(src) { const i = src.search(/\$|\\[([]/); return i < 0 ? undefined : i },
  tokenizer(src) {
    let m = /^\$\$([\s\S]+?)\$\$/.exec(src)
    if (m) return { type: 'mathInline', raw: m[0], text: m[1].trim(), display: true }
    m = /^\\\[([\s\S]+?)\\\]/.exec(src)
    if (m) return { type: 'mathInline', raw: m[0], text: m[1].trim(), display: true }
    m = /^\\\(([\s\S]+?)\\\)/.exec(src)
    if (m) return { type: 'mathInline', raw: m[0], text: m[1], display: false }
    // $x$: no space just inside the dollars and no digit right after, so "$5 and $10" stays text.
    m = /^\$(?![\s$])((?:\\.|[^\\$\n])*?[^\s\\$])\$(?!\d)/.exec(src)
    if (m) return { type: 'mathInline', raw: m[0], text: m[1], display: false }
  },
  renderer(t) { return tex(t.text, !!(t as any).display) },
}

// ---------- Files from Claude ----------

let fileBase = ''

function filePath(href: string): string | null {
  if (!/^file:\/\//i.test(href)) return null
  let p = href.replace(/^file:\/\/(localhost)?/i, '')
  try { p = decodeURIComponent(p) } catch { /* keep raw */ }
  return p.startsWith('/') ? p : null
}

const fileUrl = (path: string, download = false) =>
  `${fileBase}?path=${encodeURIComponent(path)}${download ? '&download=1' : ''}`

const IMG_EXT = /\.(png|jpe?g|gif|webp|avif|bmp)$/i
const FILE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>'
const DL_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>'

function fileCard(path: string, label: string) {
  const name = path.split('/').pop() || path
  const ext = (name.includes('.') ? name.split('.').pop()! : 'file').slice(0, 5).toUpperCase()
  return `<a class="file-card" href="${escapeHtml(fileUrl(path, true))}" download="${escapeHtml(name)}" data-file="${escapeHtml(path)}">`
    + `<span class="fc-icon">${FILE_ICON}<b>${escapeHtml(ext)}</b></span>`
    + `<span class="fc-meta"><span class="fc-name">${label}</span><span class="fc-path">${escapeHtml(path)}</span></span>`
    + `<span class="fc-dl">${DL_ICON}</span></a>`
}

function fileImage(path: string, alt: string) {
  return `<span class="file-img"><img src="${escapeHtml(fileUrl(path))}" alt="${escapeHtml(alt)}" loading="lazy" data-file="${escapeHtml(path)}" data-view>`
    + `${alt ? `<span class="file-img-cap">${escapeHtml(alt)}</span>` : ''}</span>`
}

// ---------- Marked ----------

const marked = new Marked({ gfm: true, breaks: false })

marked.use({
  extensions: [mathBlock, mathInline],
  renderer: {
    code({ text, lang }) {
      const language = (lang || '').trim().split(/\s+/)[0]
      if (language === 'math' || language === 'latex' && /^\s*\\begin\{/.test(text)) return tex(text, true)
      let html: string
      try {
        html = language && hljs.getLanguage(language)
          ? hljs.highlight(text, { language, ignoreIllegals: true }).value
          : text.length < 20000 ? hljs.highlightAuto(text).value : escapeHtml(text)
      } catch {
        html = escapeHtml(text)
      }
      return `<div class="codeblock"><div class="codeblock-head"><span>${escapeHtml(language || 'code')}</span>`
        + `<button type="button" class="copy-code" data-copy>Copy</button></div>`
        + `<pre><code class="hljs">${html}</code></pre></div>`
    },
    link({ href, title, tokens }) {
      const text = this.parser.parseInline(tokens)
      const path = fileBase ? filePath(href) : null
      if (path) return fileCard(path, text)
      const t = title ? ` title="${escapeHtml(title)}"` : ''
      return `<a href="${escapeHtml(href)}"${t} target="_blank" rel="noopener noreferrer">${text}</a>`
    },
    image({ href, title, text }) {
      const path = fileBase ? filePath(href) : null
      if (path) return IMG_EXT.test(path) ? fileImage(path, text) : fileCard(path, escapeHtml(text || path.split('/').pop() || path))
      const t = title ? ` title="${escapeHtml(title)}"` : ''
      return `<img src="${escapeHtml(href)}" alt="${escapeHtml(text)}"${t} loading="lazy" data-view>`
    },
  },
})

export function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}

const PURIFY = { ADD_ATTR: ['target', 'data-copy', 'data-file', 'data-view', 'download'] }
const cache = new Map<string, string>()

function parse(src: string, sid?: string) {
  fileBase = sid ? `/api/sessions/${encodeURIComponent(sid)}/files` : ''
  try {
    return DOMPurify.sanitize(marked.parse(src, { async: false }) as string, PURIFY)
  } finally {
    fileBase = ''
  }
}

/** `sid` enables file:// previews served through that session's file route. */
export function renderMarkdown(src: string, sid?: string): string {
  const key = `${sid || ''}\u0000${src}`
  const hit = cache.get(key)
  if (hit !== undefined) return hit
  const html = parse(src, sid)
  if (cache.size > 400) cache.clear()
  cache.set(key, html)
  return html
}

/** Streaming text: same renderer, but close an unterminated code fence so the partial block renders as code. */
export function renderStreaming(src: string, sid?: string): string {
  const fences = (src.match(/^```/gm) || []).length
  return parse(fences % 2 === 1 ? src + '\n```' : src, sid)
}

export function highlightCode(code: string, language?: string): string {
  try {
    if (language && hljs.getLanguage(language)) return hljs.highlight(code, { language, ignoreIllegals: true }).value
  } catch { /* fall through */ }
  return escapeHtml(code)
}

export function langFromPath(path: string): string | undefined {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', mjs: 'javascript', py: 'python', rs: 'rust',
    go: 'go', java: 'java', kt: 'kotlin', rb: 'ruby', php: 'php', c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', cs: 'csharp',
    swift: 'swift', sh: 'bash', bash: 'bash', zsh: 'bash', json: 'json', yml: 'yaml', yaml: 'yaml', toml: 'ini', ini: 'ini',
    md: 'markdown', html: 'xml', xml: 'xml', svg: 'xml', css: 'css', scss: 'scss', sql: 'sql', lua: 'lua', conf: 'nginx',
  }
  return map[ext]
}
