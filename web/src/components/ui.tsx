// Shared UI pieces: top bar, sheets, confirm dialog, toasts, segmented control, switch.

import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks'
import type { ComponentChildren } from 'preact'
import { createPortal } from 'preact/compat'
import { IconBack, IconClose } from './icons'
import { toasts } from '../lib/store'
import { entryKey, scrollMemory } from '../lib/router'

export function TopBar({ title, subtitle, left, right, scrolled, children }: {
  title?: ComponentChildren
  subtitle?: ComponentChildren
  left?: ComponentChildren
  right?: ComponentChildren
  scrolled?: boolean
  children?: ComponentChildren
}) {
  return (
    <header class={`topbar ${scrolled ? 'scrolled' : ''}`}>
      <div class="topbar-inner">
        {left}
        <div class="topbar-title">
          {children}
          {(title || subtitle) && (
            <div class="titles">
              {title && <span class="t1">{title}</span>}
              {subtitle && <span class="t2">{subtitle}</span>}
            </div>
          )}
        </div>
        {right}
      </div>
    </header>
  )
}

export function BackButton({ onClick, label = 'Back' }: { onClick: () => void; label?: string }) {
  return (
    <button class="back-btn" onClick={onClick} aria-label={label}>
      <IconBack />
      <span class="back-label">{label}</span>
    </button>
  )
}

/**
 * Tracks whether a scroll container has scrolled (for the top bar hairline) and remembers its offset
 * per history entry. Pages remount on every route change, so without this Back lands at the top.
 * Put `ref` and `onScroll` on the page's scroll container.
 */
export function useScrolled() {
  const key = useRef(entryKey()).current
  const saved = scrollMemory.get(key) || 0
  const [scrolled, setScrolled] = useState(saved > 4)
  const ref = useRef<HTMLDivElement>(null)

  // Content may still grow after mount (cached lists, async loads), so keep applying the saved
  // offset as the content resizes until it fits, the user touches the page, or a short timeout.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !saved) return
    let done = false
    const apply = () => {
      if (done) return
      el.scrollTop = saved
      if (Math.abs(el.scrollTop - saved) < 2) stop()
    }
    const ro = new ResizeObserver(apply)
    const stop = () => {
      done = true
      ro.disconnect()
      clearTimeout(timer)
      el.removeEventListener('touchstart', stop)
      el.removeEventListener('wheel', stop)
    }
    const timer = setTimeout(stop, 2000)
    el.addEventListener('touchstart', stop, { passive: true })
    el.addEventListener('wheel', stop, { passive: true })
    if (el.firstElementChild) ro.observe(el.firstElementChild)
    apply()
    return stop
  }, [])

  const onScroll = (e: Event) => {
    const top = (e.currentTarget as HTMLElement).scrollTop
    scrollMemory.set(key, top)
    setScrolled(top > 4)
  }
  return { scrolled, onScroll, ref }
}

/**
 * Bottom sheet on phones, centered dialog on wide screens. Closing animates out first.
 * Swipe the grip area down to dismiss.
 */
export function Sheet({ open, onClose, title, children, actions }: {
  open: boolean
  onClose: () => void
  title?: ComponentChildren
  children: ComponentChildren
  actions?: ComponentChildren
}) {
  const [mounted, setMounted] = useState(open)
  const [closing, setClosing] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) { setMounted(true); setClosing(false) }
    else if (mounted) {
      setClosing(true)
      const t = setTimeout(() => { setMounted(false); setClosing(false) }, 260)
      return () => clearTimeout(t)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  // Drag-to-dismiss from the header.
  const drag = useRef({ y: 0, dy: 0, on: false })
  const onTouchStart = (e: TouchEvent) => { drag.current = { y: e.touches[0].clientY, dy: 0, on: true } }
  const onTouchMove = (e: TouchEvent) => {
    if (!drag.current.on || !ref.current) return
    const dy = Math.max(0, e.touches[0].clientY - drag.current.y)
    drag.current.dy = dy
    ref.current.style.transition = 'none'
    ref.current.style.transform = `translate3d(0, ${dy}px, 0)`
  }
  const onTouchEnd = () => {
    if (!drag.current.on || !ref.current) return
    drag.current.on = false
    ref.current.style.transition = 'transform 0.3s cubic-bezier(0.32,0.72,0,1)'
    ref.current.style.transform = ''
    if (drag.current.dy > 90) onClose()
  }

  if (!mounted) return null
  return createPortal(
    <>
      <div class={`scrim ${closing ? 'closing' : ''}`} onClick={onClose} />
      <div ref={ref} class={`sheet ${closing ? 'closing' : ''}`} role="dialog" aria-modal="true">
        <div onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}>
          <div class="sheet-grip" />
          {(title || actions) && (
            <div class="sheet-head">
              <h3>{title}</h3>
              {actions}
              <button class="icon-btn" onClick={onClose} aria-label="Close"><IconClose /></button>
            </div>
          )}
        </div>
        <div class="sheet-body">{children}</div>
      </div>
    </>,
    document.body,
  )
}

interface ConfirmOpts { title: string; body?: string; confirm?: string; danger?: boolean }
let confirmResolver: ((v: boolean) => void) | null = null
let setConfirmState: ((o: ConfirmOpts | null) => void) | null = null

export function confirmDialog(o: ConfirmOpts): Promise<boolean> {
  return new Promise((resolve) => {
    confirmResolver?.(false)
    confirmResolver = resolve
    setConfirmState?.(o)
  })
}

interface PromptOpts { title: string; value?: string; placeholder?: string; confirm?: string }
let promptResolver: ((v: string | null) => void) | null = null
let setPromptState: ((o: PromptOpts | null) => void) | null = null

export function promptDialog(o: PromptOpts): Promise<string | null> {
  return new Promise((resolve) => {
    promptResolver?.(null)
    promptResolver = resolve
    setPromptState?.(o)
  })
}

export function DialogHost() {
  const [c, setC] = useState<ConfirmOpts | null>(null)
  const [p, setP] = useState<PromptOpts | null>(null)
  const [val, setVal] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  setConfirmState = setC
  setPromptState = (o) => { setP(o); setVal(o?.value || '') }

  const closeC = (v: boolean) => { confirmResolver?.(v); confirmResolver = null; setC(null) }
  const closeP = (v: string | null) => { promptResolver?.(v); promptResolver = null; setP(null) }

  useEffect(() => { if (p) setTimeout(() => inputRef.current?.select(), 120) }, [p])

  return (
    <>
      <Sheet open={!!c} onClose={() => closeC(false)} title={c?.title}>
        {c?.body && <p style={{ margin: '0 4px 18px', color: 'var(--text-2)' }}>{c.body}</p>}
        <div style={{ display: 'flex', gap: '10px' }}>
          <button class="btn block" onClick={() => closeC(false)}>Cancel</button>
          <button class={`btn block ${c?.danger ? 'danger' : 'primary'}`} onClick={() => closeC(true)}>
            {c?.confirm || 'Confirm'}
          </button>
        </div>
      </Sheet>
      <Sheet open={!!p} onClose={() => closeP(null)} title={p?.title}>
        <form onSubmit={(e) => { e.preventDefault(); closeP(val) }}>
          <input ref={inputRef} class="input" value={val} placeholder={p?.placeholder}
            onInput={(e) => setVal((e.target as HTMLInputElement).value)} />
          <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
            <button type="button" class="btn block" onClick={() => closeP(null)}>Cancel</button>
            <button type="submit" class="btn block primary">{p?.confirm || 'Save'}</button>
          </div>
        </form>
      </Sheet>
    </>
  )
}

export function Toasts() {
  return (
    <div class="toasts" aria-live="polite">
      {toasts.value.map((t) => (
        <div key={t.id} class={`toast ${t.kind === 'error' ? 'error' : ''} ${t.leaving ? 'leaving' : ''}`}>{t.text}</div>
      ))}
    </div>
  )
}

export function Segmented<T extends string>({ value, options, onChange }: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div class="segmented" role="radiogroup">
      {options.map((o) => (
        <button type="button" role="radio" aria-checked={o.value === value} class={o.value === value ? 'on' : ''}
          onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} class={`switch ${on ? 'on' : ''}`}
      onClick={() => onChange(!on)} />
  )
}
