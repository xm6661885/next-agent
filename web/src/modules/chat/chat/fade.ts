// Fade-in for streamed text. Streaming Markdown is re-rendered as a whole on every delta, so after each render
// the text that arrived in the last FADE ms is wrapped in spans whose negative animation-delay continues the fade
// where the previous render left it.

const FADE = 420

export interface FadeState { total: number; chunks: { start: number; t: number }[] }

export const newFade = (): FadeState => ({ total: -1, chunks: [] })

export function fadeTail(root: HTMLElement, st: FadeState) {
  const now = performance.now()
  const total = root.textContent?.length || 0
  if (st.total < 0) { st.total = total; return }  // first render (history or reconnect): no fade
  if (total > st.total) st.chunks.push({ start: st.total, t: now })
  st.total = total
  st.chunks = st.chunks.filter((c) => now - c.t < FADE)
  if (!st.chunks.length) return
  const from = st.chunks[0].start
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes: [Text, number][] = []
  let pos = 0
  for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
    const len = n.data.length
    if (pos + len > from) nodes.push([n, pos])
    pos += len
  }
  for (const [node, start] of nodes) {
    // Split this text node at chunk boundaries, newest last.
    let cur: Text = node, curStart = start
    for (let i = 0; i < st.chunks.length; i++) {
      const c = st.chunks[i], end = st.chunks[i + 1]?.start ?? Infinity
      if (end <= curStart) continue
      const a = Math.max(0, c.start - curStart)
      if (a >= cur.data.length) break
      if (a > 0) { cur = cur.splitText(a); curStart += a }
      const take = Math.min(cur.data.length, end - curStart)
      const rest = take < cur.data.length ? cur.splitText(take) : null
      if (cur.data.trim() && cur.parentElement && !cur.parentElement.closest('.katex')) {
        const span = document.createElement('span')
        span.className = 'fade-chunk'
        span.style.animationDelay = `${-(now - c.t)}ms`
        cur.replaceWith(span)
        span.appendChild(cur)
      }
      if (!rest) break
      cur = rest; curStart += take
    }
  }
}

/** Replace fade spans with their plain text so no element is left with a stale blur layer. */
export function unwrapFade(el: Element) {
  const span = el as HTMLElement
  if (!span.classList?.contains('fade-chunk') || !span.parentNode) return
  const parent = span.parentNode
  while (span.firstChild) parent.insertBefore(span.firstChild, span)
  span.remove()
  parent.normalize()
}

export function clearFade(root: HTMLElement) {
  root.querySelectorAll('.fade-chunk').forEach(unwrapFade)
}

/** Ease the scroller toward its bottom instead of jumping, so new lines glide in. */
export function makeFollower(get: () => HTMLElement | null) {
  let raf = 0
  const step = () => {
    const el = get()
    if (!el) { raf = 0; return }
    const target = el.scrollHeight - el.clientHeight
    const d = target - el.scrollTop
    if (d <= 1 || d > 2000) { el.scrollTop = target; raf = 0; return }
    el.scrollTop += Math.max(1, d * 0.22)
    raf = requestAnimationFrame(step)
  }
  return {
    follow() { if (!raf) raf = requestAnimationFrame(step) },
    jump() { cancelAnimationFrame(raf); raf = 0; const el = get(); if (el) el.scrollTop = el.scrollHeight },
  }
}
