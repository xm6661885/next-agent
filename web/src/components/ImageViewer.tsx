// Full-screen image viewer: pinch / wheel / double-tap zoom, pan, swipe between images,
// swipe down to close, download button. Opened from anywhere with openViewer().

import { signal } from '@preact/signals'
import { useEffect, useRef, useState } from 'preact/hooks'
import { createPortal } from 'preact/compat'
import { IconBack, IconChevron, IconClose, IconImport } from './icons'

export interface ViewImage { src: string; name?: string; download?: string }

const state = signal<{ images: ViewImage[]; index: number } | null>(null)

export function openViewer(images: ViewImage[], index = 0) {
  if (images.length) state.value = { images, index: Math.max(0, Math.min(index, images.length - 1)) }
}

const MAX = 6

export function ImageViewerHost() {
  const s = state.value
  if (!s) return null
  return createPortal(<Viewer images={s.images} start={s.index} onClose={() => { state.value = null }} />, document.body)
}

function Viewer({ images, start, onClose }: { images: ViewImage[]; start: number; onClose: () => void }) {
  const [index, setIndex] = useState(start)
  const [closing, setClosing] = useState(false)
  const [chrome, setChrome] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const stage = useRef<HTMLDivElement>(null)
  const img = useRef<HTMLImageElement>(null)
  const back = useRef<HTMLDivElement>(null)
  // Transform state lives in a ref so gestures do not re-render.
  const t = useRef({ scale: 1, x: 0, y: 0, dismiss: 0, swipe: 0 })
  const cur = images[index]

  const apply = (animate = false) => {
    const el = img.current
    if (!el) return
    const { scale, x, y, dismiss, swipe } = t.current
    el.style.transition = animate ? 'transform 0.3s cubic-bezier(0.22,1,0.36,1)' : 'none'
    const shrink = 1 - Math.min(Math.abs(dismiss) / 1200, 0.25)
    el.style.transform = `translate3d(${x + swipe}px, ${y + dismiss}px, 0) scale(${scale * shrink})`
    if (back.current) back.current.style.opacity = String(1 - Math.min(Math.abs(dismiss) / 400, 0.7))
  }
  const reset = (animate = true) => { t.current = { scale: 1, x: 0, y: 0, dismiss: 0, swipe: 0 }; apply(animate) }

  const close = () => {
    setClosing(true)
    setTimeout(onClose, 200)
  }
  const go = (d: number) => {
    const n = index + d
    if (n < 0 || n >= images.length) { reset(); return }
    setLoaded(false)
    setIndex(n)
  }

  useEffect(() => { reset(false) }, [index])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      else if (e.key === 'ArrowLeft') go(-1)
      else if (e.key === 'ArrowRight') go(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index])

  // Keep the pan inside the image bounds for the current scale.
  const clamp = () => {
    const el = img.current, st = stage.current
    if (!el || !st) return
    const { scale } = t.current
    const mx = Math.max(0, (el.offsetWidth * scale - st.clientWidth) / 2)
    const my = Math.max(0, (el.offsetHeight * scale - st.clientHeight) / 2)
    t.current.x = Math.max(-mx, Math.min(mx, t.current.x))
    t.current.y = Math.max(-my, Math.min(my, t.current.y))
  }

  const zoomAt = (cx: number, cy: number, next: number) => {
    const st = stage.current
    if (!st) return
    const r = st.getBoundingClientRect()
    const ox = cx - r.left - r.width / 2, oy = cy - r.top - r.height / 2
    const k = next / t.current.scale
    t.current.x = ox - (ox - t.current.x) * k
    t.current.y = oy - (oy - t.current.y) * k
    t.current.scale = next
    if (next <= 1) { t.current.x = 0; t.current.y = 0 }
    clamp()
  }

  // ---------- touch gestures ----------
  const g = useRef<any>({})
  const onTouchStart = (e: TouchEvent) => {
    const ts = e.touches
    if (ts.length === 2) {
      const d = Math.hypot(ts[0].clientX - ts[1].clientX, ts[0].clientY - ts[1].clientY)
      g.current = { mode: 'pinch', d, scale: t.current.scale, cx: (ts[0].clientX + ts[1].clientX) / 2, cy: (ts[0].clientY + ts[1].clientY) / 2 }
    } else if (ts.length === 1) {
      g.current = { mode: 'pending', sx: ts[0].clientX, sy: ts[0].clientY, x: t.current.x, y: t.current.y, at: Date.now(), moved: false }
    }
  }
  const onTouchMove = (e: TouchEvent) => {
    const s = g.current
    const ts = e.touches
    if (s.mode === 'pinch' && ts.length === 2) {
      e.preventDefault()
      const d = Math.hypot(ts[0].clientX - ts[1].clientX, ts[0].clientY - ts[1].clientY)
      const next = Math.max(0.6, Math.min(MAX, s.scale * (d / s.d)))
      zoomAt(s.cx, s.cy, next)
      apply()
      return
    }
    if (ts.length !== 1 || !s.mode) return
    const dx = ts[0].clientX - s.sx, dy = ts[0].clientY - s.sy
    if (Math.abs(dx) > 6 || Math.abs(dy) > 6) s.moved = true
    if (s.mode === 'pending' && s.moved) {
      s.mode = t.current.scale > 1.02 ? 'pan' : Math.abs(dy) > Math.abs(dx) ? 'dismiss' : 'swipe'
    }
    if (s.mode === 'pending') return
    e.preventDefault()
    if (s.mode === 'pan') { t.current.x = s.x + dx; t.current.y = s.y + dy; clamp() }
    else if (s.mode === 'dismiss') t.current.dismiss = dy
    else if (s.mode === 'swipe') {
      const edge = (index === 0 && dx > 0) || (index === images.length - 1 && dx < 0)
      t.current.swipe = edge ? dx / 3 : dx
    }
    apply()
  }
  const lastTap = useRef({ at: 0, x: 0, y: 0 })
  const onTouchEnd = (e: TouchEvent) => {
    const s = g.current
    if (e.touches.length > 0) {
      // Pinch ended with one finger still down: continue as pan.
      if (s.mode === 'pinch') g.current = { mode: 'pan', sx: e.touches[0].clientX, sy: e.touches[0].clientY, x: t.current.x, y: t.current.y, moved: true }
      return
    }
    g.current = {}
    if (s.mode === 'pinch') {
      if (t.current.scale < 1) reset()
      else { clamp(); apply(true) }
      return
    }
    if (s.mode === 'dismiss') {
      if (Math.abs(t.current.dismiss) > 110) { close(); return }
      t.current.dismiss = 0
      apply(true)
      return
    }
    if (s.mode === 'swipe') {
      const w = stage.current?.clientWidth || 1
      if (t.current.swipe < -w * 0.18) go(1)
      else if (t.current.swipe > w * 0.18) go(-1)
      else { t.current.swipe = 0; apply(true) }
      return
    }
    if (s.mode === 'pending' && !s.moved) {
      const p = (e.changedTouches || [])[0]
      const now = Date.now()
      if (p && now - lastTap.current.at < 300 && Math.hypot(p.clientX - lastTap.current.x, p.clientY - lastTap.current.y) < 30) {
        lastTap.current.at = 0
        clearTimeout(tapTimer.current)
        zoomAt(p.clientX, p.clientY, t.current.scale > 1.02 ? 1 : 2.5)
        apply(true)
      } else if (p) {
        lastTap.current = { at: now, x: p.clientX, y: p.clientY }
        tapTimer.current = window.setTimeout(() => setChrome((c) => !c), 300)
      }
    }
  }
  const tapTimer = useRef<number | undefined>()

  // ---------- mouse / trackpad ----------
  const onWheel = (e: WheelEvent) => {
    e.preventDefault()
    const next = Math.max(1, Math.min(MAX, t.current.scale * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.002))))
    zoomAt(e.clientX, e.clientY, next)
    apply()
  }
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; moved: boolean } | null>(null)
  const onMouseDown = (e: MouseEvent) => {
    if (e.button !== 0) return
    drag.current = { x: e.clientX, y: e.clientY, ox: t.current.x, oy: t.current.y, moved: false }
  }
  const onMouseMove = (e: MouseEvent) => {
    const d = drag.current
    if (!d) return
    if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 4) d.moved = true
    if (t.current.scale > 1.02 && d.moved) {
      t.current.x = d.ox + e.clientX - d.x
      t.current.y = d.oy + e.clientY - d.y
      clamp()
      apply()
    }
  }
  const onMouseUp = (e: MouseEvent) => {
    const d = drag.current
    drag.current = null
    if (!d || d.moved) return
    // A click on the backdrop closes; a click on the image toggles zoom.
    if (e.target === img.current) {
      zoomAt(e.clientX, e.clientY, t.current.scale > 1.02 ? 1 : 2.5)
      apply(true)
    } else close()
  }

  useEffect(() => {
    const st = stage.current
    if (!st) return
    // Non-passive listeners so pinch and wheel do not scroll or zoom the page.
    st.addEventListener('touchmove', onTouchMove, { passive: false })
    st.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      st.removeEventListener('touchmove', onTouchMove)
      st.removeEventListener('wheel', onWheel)
    }
  })

  return (
    <div class={`viewer ${closing ? 'closing' : ''} ${chrome ? '' : 'bare'}`} role="dialog" aria-modal="true" aria-label="Image viewer">
      <div class="viewer-back" ref={back} />
      <div class="viewer-stage" ref={stage}
        onTouchStart={onTouchStart} onTouchEnd={onTouchEnd} onTouchCancel={onTouchEnd}
        onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={() => { drag.current = null }}>
        {!loaded && <span class="spinner viewer-spin" />}
        <img key={cur.src} ref={img} src={cur.src} alt={cur.name || ''} draggable={false}
          class={loaded ? 'in' : ''} onLoad={() => setLoaded(true)} onError={() => setLoaded(true)} />
      </div>
      <div class="viewer-top">
        <button class="viewer-btn" aria-label="Close" onClick={close}><IconClose /></button>
        <span class="viewer-title">
          {cur.name && <span class="n">{cur.name}</span>}
          {images.length > 1 && <span class="c">{index + 1} / {images.length}</span>}
        </span>
        <a class="viewer-btn" aria-label="Download" href={cur.download || cur.src} download={cur.name || ''}>
          <IconImport />
        </a>
      </div>
      {images.length > 1 && (
        <>
          <button class="viewer-nav prev" aria-label="Previous image" disabled={index === 0} onClick={() => go(-1)}><IconBack /></button>
          <button class="viewer-nav next" aria-label="Next image" disabled={index === images.length - 1} onClick={() => go(1)}><IconChevron /></button>
        </>
      )}
    </div>
  )
}
