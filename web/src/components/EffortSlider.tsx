// Effort picker as a wide slider with snap stops. Dragging to "max" lights the track up.

import { useEffect, useRef, useState } from 'preact/hooks'
import { haptic } from '../lib/util'

export const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']

export function EffortSlider({ value, onChange }: {
  value: string
  onChange: (v: string) => void | Promise<unknown>
}) {
  const track = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<number | null>(null)
  // Optimistic value: hold the picked stop until the server echoes it back (or fails).
  const [pending, setPending] = useState<string | null>(null)
  useEffect(() => { setPending(null) }, [value])
  const pick = (v: string) => {
    if (v === (pending ?? value ?? '')) return
    setPending(v)
    Promise.resolve(onChange(v)).catch(() => {}).finally(() => setTimeout(() => setPending(p => (p === v ? null : p)), 3000))
  }
  const cur = pending ?? value
  const idx = Math.max(0, EFFORTS.indexOf(cur || ''))
  const last = EFFORTS.length - 1
  const shown = drag ?? idx / last
  const at = Math.round(shown * last)

  const pos = (e: PointerEvent) => {
    const r = track.current!.getBoundingClientRect()
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
  }
  const onDown = (e: PointerEvent) => {
    if (e.button !== 0) return
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    setDrag(pos(e))
  }
  const onMove = (e: PointerEvent) => {
    if (drag === null) return
    const p = pos(e)
    if (Math.round(p * last) !== Math.round(drag * last)) haptic()
    setDrag(p)
  }
  const onUp = () => {
    if (drag === null) return
    const next = EFFORTS[Math.round(drag * last)]
    setDrag(null)
    pick(next)
  }
  const onKey = (e: KeyboardEvent) => {
    const d = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 0
    if (!d) return
    e.preventDefault()
    const n = Math.min(last, Math.max(0, idx + d))
    if (n !== idx) pick(EFFORTS[n])
  }
  const label = (e: string) => e
  return (
    <div class={`effort ${at === last ? 'max' : ''} ${drag !== null ? 'dragging' : ''}`}>
      <div class="effort-head">
        <span class="effort-value" key={at}>{label(EFFORTS[at])}</span>
      </div>
      <div ref={track} class="effort-track" role="slider" tabIndex={0} aria-label="Effort"
        aria-valuemin={0} aria-valuemax={last} aria-valuenow={idx} aria-valuetext={label(EFFORTS[idx])}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} onKeyDown={onKey}>
        <div class="effort-fill" style={{ width: `calc(${shown * 100}% + ${(1 - shown) * 30}px)` }} />
        {EFFORTS.map((_, k) => <span key={k} class={`effort-stop ${k <= at ? 'on' : ''}`} style={{ left: `calc(15px + ${k / last} * (100% - 30px))` }} />)}
        <div class="effort-thumb" style={{ left: `calc(${shown} * (100% - 30px))` }} />
      </div>
      <div class="effort-labels">
        {EFFORTS.map((e, k) => (
          <button key={k} type="button" class={k === at ? 'on' : ''} onClick={() => pick(e)}>{e}</button>
        ))}
      </div>
    </div>
  )
}
