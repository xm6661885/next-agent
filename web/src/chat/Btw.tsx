// Side question ("/btw"): tool-less replies from a throwaway fork of the session; nothing lands in the chat.
// Earlier side Q/A stays in the sheet (and is sent back as context) until cleared. The model choice is sheet-local.
import { useEffect, useRef, useState } from 'preact/hooks'
import { Sheet } from '../components/ui'
import { ModelPicker } from '../components/ModelPicker'
import { IconChevronDown, IconSend, IconTrash } from '../components/icons'
import { renderMarkdown, renderStreaming } from './markdown'

type Turn = { q: string; a: string }

export function BtwSheet({ sid, open, question, nonce, model, onClose }: {
  sid: string; open: boolean; question: string; nonce: number
  /** The session's model; the sheet starts on it and any pick only applies here. */
  model: string
  onClose: () => void
}) {
  const [q, setQ] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [loading, setLoading] = useState(false)
  const [pick, setPick] = useState('')
  const [picking, setPicking] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const used = pick || model

  const setLast = (a: string) => setTurns((t) => [...t.slice(0, -1), { ...t[t.length - 1], a }])

  const ask = async (text: string) => {
    text = text.trim()
    if (!text) return
    abort.current?.abort()
    const ac = new AbortController()
    abort.current = ac
    // An unfinished (aborted) answer is dropped from the context sent back.
    const history = turns.filter((t) => t.a)
    setTurns([...history, { q: text, a: '' }]); setQ(''); setLoading(true); setPicking(false)
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(sid)}/btw`, {
        method: 'POST', credentials: 'same-origin', signal: ac.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, history, ...(pick ? { model: pick } : {}) }),
      })
      if (!res.ok) {
        let msg = `Request failed (${res.status})`
        try { const d = await res.json(); if (typeof d.detail === 'string') msg = d.detail } catch { /* not json */ }
        setLast(`*${msg}*`)
        return
      }
      const reader = res.body!.getReader()
      const dec = new TextDecoder()
      let acc = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        acc += dec.decode(value, { stream: true })
        setLast(acc)
      }
    } catch {
      if (!ac.signal.aborted) setLast('*Network error*')
    } finally {
      if (abort.current === ac) setLoading(false)
    }
  }

  const clear = () => { abort.current?.abort(); abort.current = null; setLoading(false); setTurns([]) }

  useEffect(() => { if (open && question) ask(question) }, [open, nonce])
  useEffect(() => { if (!open) { abort.current?.abort(); abort.current = null; setLoading(false) } }, [open])
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [turns.length])

  return (
    <Sheet open={open} onClose={onClose} title="By the way"
      actions={turns.length > 0 && <button class="icon-btn" aria-label="Clear side conversation" onClick={clear}><IconTrash /></button>}>
      <div class="btw">
        <button type="button" class={`chip btw-model ${pick ? 'pink' : ''}`} aria-expanded={picking} onClick={() => setPicking(!picking)}>
          {used || 'Default model'} <IconChevronDown />
        </button>
        {picking && (
          <div class="btw-picker pop">
            <ModelPicker value={used} onChange={(m) => { setPick(m === model ? '' : m); setPicking(false) }} />
            <div class="fhint">Only for side questions in this window.</div>
          </div>
        )}
        <div class="btw-log">
          {turns.map((t, i) => (
            <>
              <div key={`q${i}`} class="btw-q">{t.q}</div>
              {t.a
                ? <div key={`a${i}`} class="md btw-a" dangerouslySetInnerHTML={{ __html: loading && i === turns.length - 1 ? renderStreaming(t.a, sid) : renderMarkdown(t.a, sid) }} />
                : <div key={`a${i}`} class="btw-a btw-wait">{loading && i === turns.length - 1 ? 'Thinking...' : 'Stopped'}</div>}
            </>
          ))}
          <div ref={end} />
        </div>
        {!turns.length && <div class="btw-hint">Ask a quick question about this conversation. No tools, and it stays out of the chat. Follow-ups remember this side thread until you clear it.</div>}
        <div class="btw-input">
          <input value={q} placeholder="Ask on the side" onInput={(e) => setQ((e.target as HTMLInputElement).value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); ask(q) } }} />
          <button class={`send-btn ${q.trim() ? 'ready' : ''}`} aria-label="Ask" disabled={!q.trim()} onClick={() => ask(q)}><IconSend /></button>
        </div>
      </div>
    </Sheet>
  )
}
