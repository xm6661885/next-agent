// Crop a photo before it is attached: drag the frame or its corners, then Use photo.

import { useEffect, useRef, useState } from 'preact/hooks'
import { Sheet } from './ui'

type Rect = { x: number; y: number; w: number; h: number }  // fractions of the image, 0..1
const MIN = 0.08

export function CropSheet({ file, onDone, onCancel }: { file: File | null; onDone: (f: File) => void; onCancel: () => void }) {
  const [url, setUrl] = useState('')
  const [rect, setRect] = useState<Rect>({ x: 0, y: 0, w: 1, h: 1 })
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const img = useRef<HTMLImageElement>(null)
  const drag = useRef<{ mode: string; sx: number; sy: number; start: Rect } | null>(null)

  useEffect(() => {
    if (!file) return
    const u = URL.createObjectURL(file)
    setUrl(u)
    setRect({ x: 0, y: 0, w: 1, h: 1 })
    setBusy(false)
    return () => URL.revokeObjectURL(u)
  }, [file])

  const down = (mode: string) => (e: PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    drag.current = { mode, sx: e.clientX, sy: e.clientY, start: rect }
  }
  const move = (e: PointerEvent) => {
    const d = drag.current
    if (!d || !box.current) return
    const b = box.current.getBoundingClientRect()
    const dx = (e.clientX - d.sx) / b.width, dy = (e.clientY - d.sy) / b.height
    let { x, y, w, h } = d.start
    if (d.mode === 'move') {
      x = Math.min(1 - w, Math.max(0, x + dx))
      y = Math.min(1 - h, Math.max(0, y + dy))
    } else {
      if (d.mode.includes('l')) { const nx = Math.min(x + w - MIN, Math.max(0, x + dx)); w += x - nx; x = nx }
      if (d.mode.includes('r')) w = Math.min(1 - x, Math.max(MIN, w + dx))
      if (d.mode.includes('t')) { const ny = Math.min(y + h - MIN, Math.max(0, y + dy)); h += y - ny; y = ny }
      if (d.mode.includes('b')) h = Math.min(1 - y, Math.max(MIN, h + dy))
    }
    setRect({ x, y, w, h })
  }
  const up = () => { drag.current = null }

  const full = rect.x < 0.001 && rect.y < 0.001 && rect.w > 0.999 && rect.h > 0.999
  const confirm = async () => {
    const el = img.current
    if (!file || !el) return
    if (full) { onDone(file); return }
    setBusy(true)
    const W = el.naturalWidth, H = el.naturalHeight
    const c = document.createElement('canvas')
    c.width = Math.round(rect.w * W)
    c.height = Math.round(rect.h * H)
    c.getContext('2d')!.drawImage(el, rect.x * W, rect.y * H, c.width, c.height, 0, 0, c.width, c.height)
    const type = file.type === 'image/png' ? 'image/png' : 'image/jpeg'
    c.toBlob((blob) => {
      setBusy(false)
      if (!blob) { onDone(file); return }
      const name = file.name.replace(/\.[^.]+$/, '') + (type === 'image/png' ? '.png' : '.jpg')
      onDone(new File([blob], name, { type }))
    }, type, 0.9)
  }

  const pct = (v: number) => `${v * 100}%`
  return (
    <Sheet open={!!file} onClose={onCancel} title="Crop photo"
      actions={<button class="btn primary small" disabled={busy || !url} onClick={confirm}>{busy ? <span class="spinner" /> : 'Use photo'}</button>}>
      {url && (
        <div class="crop-wrap">
          <div class="crop-box" ref={box} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
            <img ref={img} src={url} alt="Photo to crop" draggable={false} />
            <div class="crop-frame" style={{ left: pct(rect.x), top: pct(rect.y), width: pct(rect.w), height: pct(rect.h) }}
              onPointerDown={down('move')}>
              {['tl', 'tr', 'bl', 'br'].map((c) => <span key={c} class={`crop-handle ${c}`} onPointerDown={down(c)} />)}
              {['t', 'b', 'l', 'r'].map((c) => <span key={c} class={`crop-edge ${c}`} onPointerDown={down(c)} />)}
            </div>
          </div>
          <div class="crop-actions">
            <button class="btn small ghost" disabled={full} onClick={() => setRect({ x: 0, y: 0, w: 1, h: 1 })}>Reset</button>
          </div>
        </div>
      )}
    </Sheet>
  )
}
