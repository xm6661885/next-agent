// Side question ("/btw"): one tool-less reply from a throwaway fork of the session; nothing lands in the chat.
import { useEffect, useRef, useState } from 'preact/hooks'
import { Sheet } from '../components/ui'
import { IconSend } from '../components/icons'
import { renderMarkdown, renderStreaming } from './markdown'

export function BtwSheet({ sid, open, question, nonce, onClose }: { sid: string; open: boolean; question: string; nonce: number; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [asked, setAsked] = useState('')
  const [answer, setAnswer] = useState('')
  const [loading, setLoading] = useState(false)
  const abort = useRef<AbortController | null>(null)

  const ask = async (text: string) => {
    text = text.trim()
    if (!text) return
    abort.current?.abort()
    const ac = new AbortController()
    abort.current = ac
    setAsked(text); setAnswer(''); setQ(''); setLoading(true)
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(sid)}/btw`, {
        method: 'POST', credentials: 'same-origin', signal: ac.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: text }),
      })
      if (!res.ok) {
        let msg = `Request failed (${res.status})`
        try { const d = await res.json(); if (typeof d.detail === 'string') msg = d.detail } catch { /* not json */ }
        setAnswer(`*${msg}*`)
        return
      }
      const reader = res.body!.getReader()
      const dec = new TextDecoder()
      let acc = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        acc += dec.decode(value, { stream: true })
        setAnswer(acc)
      }
    } catch (e) {
      if (!ac.signal.aborted) setAnswer('*Network error*')
    } finally {
      if (abort.current === ac) setLoading(false)
    }
  }

  useEffect(() => { if (open && question) ask(question) }, [open, nonce])
  useEffect(() => { if (!open) { abort.current?.abort(); abort.current = null; setLoading(false) } }, [open])

  return (
    <Sheet open={open} onClose={onClose} title="By the way">
      <div class="btw">
        {asked && <div class="btw-q">{asked}</div>}
        {asked && (answer
          ? <div class="md btw-a" dangerouslySetInnerHTML={{ __html: loading ? renderStreaming(answer, sid) : renderMarkdown(answer, sid) }} />
          : <div class="btw-a btw-wait">Thinking...</div>)}
        {!asked && <div class="btw-hint">Ask a quick question about this conversation. No tools, one reply, and it stays out of the chat.</div>}
        <div class="btw-input">
          <input value={q} placeholder="Ask on the side" onInput={(e) => setQ((e.target as HTMLInputElement).value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); ask(q) } }} />
          <button class={`send-btn ${q.trim() ? 'ready' : ''}`} aria-label="Ask" disabled={!q.trim()} onClick={() => ask(q)}><IconSend /></button>
        </div>
      </div>
    </Sheet>
  )
}
