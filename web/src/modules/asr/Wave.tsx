// Scrolling live waveform (like Voice Memos), newest level at the right edge.
// Everything runs inside requestAnimationFrame: levels are read straight from the AnalyserNode,
// kept in a fixed ring buffer, and the strip scrolls by elapsed time so motion stays smooth
// regardless of when audio callbacks arrive. No signals or re-renders per frame.
import { useEffect, useRef } from 'preact/hooks'

const STEP = 4.5        // px per bar
const BAR_MS = 60       // one new bar every 60 ms
const MAX = 512

export function LiveWave({ level, active }: { level: () => number; active: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const ring = useRef({ data: new Float32Array(MAX), n: 0, head: 0, last: 0, acc: 0 })
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const css = getComputedStyle(c)
    const col = {
      bar: css.getPropertyValue('--wave').trim() || '#f3a7b7',
      dim: css.getPropertyValue('--wave-dim').trim() || '#ccc',
      head: css.getPropertyValue('--wave-head').trim() || '#e66',
    }
    const g = c.getContext('2d')!
    let w = 0, h = 0, raf = 0
    const resize = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      w = c.clientWidth; h = c.clientHeight
      c.width = Math.round(w * dpr); c.height = Math.round(h * dpr)
      g.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(c)
    const r = ring.current
    r.last = performance.now()

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw)
      // Peak since the last bar, so short sounds still show up.
      if (active) {
        r.acc = Math.max(r.acc, level())
        while (now - r.last >= BAR_MS) {
          r.data[r.head] = r.acc
          r.head = (r.head + 1) % MAX
          r.n = Math.min(MAX, r.n + 1)
          r.acc = 0
          r.last += BAR_MS
        }
      } else r.last = now
      const frac = active ? Math.min(1, (now - r.last) / BAR_MS) : 0
      g.clearRect(0, 0, w, h)
      const visible = Math.min(r.n, Math.ceil(w / STEP) + 1)
      const right = w - 2 - frac * STEP
      const startX = right - visible * STEP
      g.fillStyle = col.dim
      for (let x = startX; x > 0; x -= STEP) g.fillRect(x, h / 2 - 1, 2.5, 2)
      g.fillStyle = col.bar
      for (let i = 0; i < visible; i++) {
        const v = r.data[(r.head - visible + i + MAX) % MAX]
        const bh = Math.max(2, v * (h - 6))
        g.fillRect(startX + i * STEP, (h - bh) / 2, 2.5, bh)
      }
      g.fillStyle = col.head
      g.fillRect(w - 1.5, 0, 1.5, h)
    }
    raf = requestAnimationFrame(draw)
    return () => { cancelAnimationFrame(raf); ro.disconnect() }
  }, [active])
  return <canvas ref={ref} class="live-wave" aria-hidden="true" />
}
