// Generative UI. ```genui blocks are widgets (Widgets.tsx); the `html` widget renders here as a sandboxed iframe
// with a tiny host bridge. Plain ```html code blocks stay code.
// The frame has an opaque origin (no allow-same-origin), so it cannot reach the API, cookies or storage.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks'
import { copyText } from '../lib/util'
import { toast } from '../lib/store'

/** Set by the open chat so frames can post messages into the current conversation. */
export const genuiHost: { send: ((text: string) => void) | null } = { send: null }

export type Segment = { kind: 'md'; text: string } | { kind: 'ui'; code: string; done: boolean }

const OPEN = /^ {0,3}```(genui|mermaid)[ \t]*$/

/** Split assistant text into Markdown and UI segments. An unclosed block is returned with done=false.
 *  A ```mermaid block becomes a genui widget of kind mermaid. */
export function splitGenui(src: string): Segment[] {
  if (!/```(genui|mermaid)/.test(src)) return [{ kind: 'md', text: src }]
  const out: Segment[] = []
  const lines = src.split('\n')
  let md: string[] = []
  let ui: string[] | null = null
  for (const line of lines) {
    if (ui) {
      if (/^ {0,3}```[ \t]*$/.test(line)) { out.push({ kind: 'ui', code: ui.join('\n'), done: true }); ui = null }
      else ui.push(line)
    } else if (OPEN.test(line)) {
      if (md.length) out.push({ kind: 'md', text: md.join('\n') })
      const tag = OPEN.exec(line)![1]
      md = []; ui = tag === 'mermaid' ? ['mermaid'] : []
    } else md.push(line)
  }
  if (ui) out.push({ kind: 'ui', code: ui.join('\n'), done: false })
  else if (md.length) out.push({ kind: 'md', text: md.join('\n') })
  return out
}

const VARS: [string, string][] = [['--bg', '--surface'], ['--fg', '--text'], ['--muted', '--text-2'], ['--border', '--line-strong'], ['--accent', '--pink'], ['--accent-ink', '--pink-ink'], ['--code-bg', '--code-bg']]

function theme() {
  const cs = getComputedStyle(document.documentElement)
  return VARS.map(([name, from]) => `${name}:${cs.getPropertyValue(from).trim()};`).join('')
}

const CSP = "default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
  + "style-src 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; img-src data: blob: https:; font-src data: https:; media-src data: blob: https:"

/** Drop a trailing unfinished tag or entity so a partial fragment parses cleanly while streaming. */
export function partialHtml(code: string): string {
  let out = code.replace(/<[^>]*$/, '').replace(/&[a-zA-Z0-9#]*$/, '')
  // Hide <style>/<script> bodies that are still being written; they would show up as text.
  out = out.replace(/<(script|style)\b[^>]*>(?![\s\S]*<\/\1>)[\s\S]*$/i, '')
  return out
}

/** The frame shell. Content arrives by postMessage: `render` swaps in partial markup (no scripts),
 *  `final` sets the whole fragment and runs its scripts in order. */
function srcdoc(id: string) {
  const bridge = `<script>(function(){var id=${JSON.stringify(id)};function post(m){m.__genui=id;parent.postMessage(m,'*')}
window.host={send:function(t){post({action:'send',text:String(t)})},copy:function(t){post({action:'copy',text:String(t)})},open:function(u){post({action:'open',url:String(u)})}};
function size(){post({action:'size',height:Math.ceil(document.documentElement.getBoundingClientRect().height)})}
new ResizeObserver(size).observe(document.documentElement);addEventListener('load',size);
addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a[href]');if(a&&/^https?:/.test(a.href)){e.preventDefault();host.open(a.href)}});
var done=false;
function runScripts(list,i){if(i>=list.length){dispatchEvent(new Event('load'));size();return}var old=list[i],s=document.createElement('script');
for(var k=0;k<old.attributes.length;k++)s.setAttribute(old.attributes[k].name,old.attributes[k].value);
if(old.src){s.onload=s.onerror=function(){runScripts(list,i+1)};s.src=old.src;old.replaceWith(s)}else{s.textContent=old.textContent;old.replaceWith(s);runScripts(list,i+1)}}
addEventListener('message',function(e){var m=e.data;if(e.source!==parent||!m||m.__genui!==id||done)return;
if(m.action==='render'){var b=document.body,n=b.getElementsByTagName('*').length;b.innerHTML=m.html;var all=b.getElementsByTagName('*');for(var j=n;j<all.length;j++)all[j].setAttribute('data-gn','');size()}
else if(m.action==='final'){done=true;document.body.innerHTML=m.html;runScripts([].slice.call(document.body.querySelectorAll('script')),0)}});
post({action:'ready'})})()</script>`
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${CSP}">`
    + `<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">`
    + `<style>:root{${theme()}color-scheme:light dark}html,body{margin:0;background:transparent;color:var(--fg);touch-action:manipulation;`
    + `font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-text-size-adjust:100%}body{padding:2px}*{box-sizing:border-box}`
    + `[data-gn]{animation:genui-in .4s ease-out both}@keyframes genui-in{from{opacity:0}to{opacity:1}}</style>`
    + `${bridge}</head><body></body></html>`
}

let seq = 0

export function GenUIFrame({ code, done }: { code: string; done: boolean }) {
  const ref = useRef<HTMLIFrameElement>(null)
  const id = useMemo(() => `g${++seq}`, [])
  const [height, setHeight] = useState(done ? 80 : 40)
  const lastSend = useRef(0)
  const ready = useRef(false)
  const latest = useRef({ code, done })
  latest.current = { code, done }
  const sent = useRef({ code: '', final: false, at: 0 })
  const timer = useRef<number>()
  // The shell never changes, so the frame is created once and keeps its state while the block streams.
  const doc = useMemo(() => srcdoc(id), [id])

  const push = () => {
    const w = ref.current?.contentWindow
    if (!w || !ready.current || sent.current.final) return
    const { code, done } = latest.current
    if (done) {
      sent.current = { code, final: true, at: Date.now() }
      w.postMessage({ __genui: id, action: 'final', html: code }, '*')
    } else {
      const html = partialHtml(code)
      if (html === sent.current.code) return
      sent.current = { code: html, final: false, at: Date.now() }
      w.postMessage({ __genui: id, action: 'render', html }, '*')
    }
  }

  // Throttle partial renders to ~8 per second; the final one goes out immediately.
  useEffect(() => {
    if (done) { clearTimeout(timer.current); push(); return }
    const wait = Math.max(0, 120 - (Date.now() - sent.current.at))
    clearTimeout(timer.current)
    timer.current = window.setTimeout(push, wait)
  }, [code, done])
  useEffect(() => () => clearTimeout(timer.current), [])

  // Layout effect: the frame can post `ready` before a deferred useEffect would attach the listener.
  useLayoutEffect(() => {
    const onMsg = (e: MessageEvent) => {
      const m = e.data
      if (!m || m.__genui !== id || e.source !== ref.current?.contentWindow) return
      // A frame that reloads (moved in the DOM, bfcache, layout switch) starts blank again, so resend from scratch.
      if (m.action === 'ready') { ready.current = true; sent.current = { code: '', final: false, at: 0 }; push() }
      else if (m.action === 'size') setHeight(Math.max(24, Math.min(4000, Number(m.height) || 0)))
      else if (m.action === 'copy') copyText(String(m.text || '')).then(() => toast('Copied'))
      else if (m.action === 'open' && /^https?:\/\//i.test(m.url || '')) window.open(m.url, '_blank', 'noopener,noreferrer')
      else if (m.action === 'send') {
        if (!latest.current.done) return
        const text = String(m.text || '').trim().slice(0, 20000)
        const now = Date.now()
        if (!text || now - lastSend.current < 1000) return  // drop empty and runaway sends
        lastSend.current = now
        if (genuiHost.send) genuiHost.send(text)
      }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [id])

  return (
    <div class={`genui ${done ? '' : 'drawing'}`}>
      <iframe ref={ref} title="Interactive content" sandbox="allow-scripts allow-forms" srcdoc={doc}
        style={{ height: `${height}px` }} />
    </div>
  )
}
