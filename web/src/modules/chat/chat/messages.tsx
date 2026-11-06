// Message pieces of the LLM chat: headers with avatar, name and time, action bars, version switchers, thinking cards.

import type { ComponentChildren } from 'preact'
import { useLayoutEffect, useRef, useState } from 'preact/hooks'
import { toast } from '../../../lib/store'
import { IconBack, IconBrain, IconCheck, IconChevron, IconChevronDown, IconCopy } from '../../../components/icons'
import { copyText, haptic } from '../../../lib/util'
import type { ThinkingItem } from '../../../lib/types'

/** Today: 14:05. This year: 11/05 14:05. Otherwise 2025/11/05 14:05. */
export function msgTime(ts?: string) {
  if (!ts) return ''
  const d = new Date(ts), now = new Date()
  if (isNaN(+d)) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  if (d.toDateString() === now.toDateString()) return hm
  const md = `${p(d.getMonth() + 1)}/${p(d.getDate())}`
  return d.getFullYear() === now.getFullYear() ? `${md} ${hm}` : `${d.getFullYear()}/${md} ${hm}`
}

export function MsgHead({ avatar, name, ts, right }: { avatar: ComponentChildren; name: string; ts?: string; right?: boolean }) {
  return (
    <div class={`msg-head ${right ? 'right' : ''}`}>
      {avatar}
      <span class="msg-name">{name}</span>
      {ts && <time class="msg-time" dateTime={ts}>{msgTime(ts)}</time>}
    </div>
  )
}

/** `‹ 2/3 ›` under a message that has several versions. */
export function Versions({ v, disabled, onSwitch }: { v?: [number, number]; disabled?: boolean; onSwitch: (i: number) => void }) {
  if (!v || v[1] < 2) return null
  const [i, n] = v
  return (
    <span class="versions">
      <button type="button" class="act" disabled={disabled || i === 0} aria-label="Previous version" onClick={() => onSwitch(i - 1)}><IconBack width={14} height={14} /></button>
      <span class="versions-n">{i + 1}/{n}</span>
      <button type="button" class="act" disabled={disabled || i === n - 1} aria-label="Next version" onClick={() => onSwitch(i + 1)}><IconChevron width={14} height={14} /></button>
    </span>
  )
}

export function Act({ label, onClick, children, disabled }: { label: string; onClick: () => void; children: ComponentChildren; disabled?: boolean }) {
  return <button type="button" class="act" aria-label={label} title={label} disabled={disabled} onClick={onClick}>{children}</button>
}

export function CopyAct({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  const copy = () => copyText(text).then(() => { haptic(); setDone(true); setTimeout(() => setDone(false), 1400) }).catch(() => toast('Copy failed', 'error'))
  return <Act label={done ? 'Copied' : 'Copy'} onClick={copy}>{done ? <IconCheck width={15} height={15} /> : <IconCopy width={15} height={15} />}</Act>
}

/** Thinking as a card: open by default, capped height with its own scroll, "Show all" lifts the cap. */
export function ThinkingCard({ it }: { it: ThinkingItem }) {
  const [open, setOpen] = useState(true)
  const [full, setFull] = useState(false)
  const [over, setOver] = useState(false)
  const body = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = body.current
    if (!el) return
    setOver(el.scrollHeight > el.clientHeight + 4)
    // Follow the stream inside the card unless the user scrolled up in it.
    if (it.streaming && el.scrollHeight - el.scrollTop - el.clientHeight < 60) el.scrollTop = el.scrollHeight
  }, [it.text, open, full])
  if (!it.text && !it.streaming) return null
  const secs = it.duration_ms ? ` · ${Math.max(1, Math.round(it.duration_ms / 1000))}s` : ''
  return (
    <div class={`think-card ${open ? 'open' : ''} ${it.streaming ? 'streaming' : ''}`}>
      <button type="button" class="think-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <IconBrain width={15} height={15} />
        <span class={it.streaming ? 'shimmer-text' : ''}>{it.streaming ? 'Thinking' : `Thought process${secs}`}</span>
        <IconChevronDown class="think-chev" width={15} height={15} />
      </button>
      {open && <>
        <div ref={body} class={`think-body ${full ? 'full' : ''}`}>{it.text}</div>
        {(over || full) && <button type="button" class="think-more" onClick={() => setFull(!full)}>{full ? 'Collapse' : 'Show all'}</button>}
      </>}
    </div>
  )
}
