// Pixel crab (Claude Code style mascot), the starburst spark loader, and avatars.

import { useEffect } from 'preact/hooks'
import { signal } from '@preact/signals'
import { api } from '../lib/api'
import type { Agent } from '../lib/types'

export const CRAB_COLORS: Record<string, { body: string; bg: string }> = {
  pink: { body: '#d97757', bg: 'var(--pink-soft)' },
  orange: { body: '#e0884f', bg: 'color-mix(in srgb, #f0a46b 22%, var(--surface))' },
  blue: { body: '#5a8fd0', bg: 'color-mix(in srgb, #8ab8ef 24%, var(--surface))' },
  green: { body: '#5d9e6c', bg: 'color-mix(in srgb, #9ad0a5 26%, var(--surface))' },
  purple: { body: '#9572c9', bg: 'color-mix(in srgb, #c4a9ea 26%, var(--surface))' },
  gray: { body: '#857c72', bg: 'color-mix(in srgb, #bdb5aa 26%, var(--surface))' },
}

/** 18 x 10 pixel grid; same shape as scripts/gen_icons.py. */
export function Crab({ color = '#d97757', class: cls = '' }: { color?: string; class?: string }) {
  return (
    <svg class={`crab ${cls}`} viewBox="0 0 18 10" shape-rendering="crispEdges" aria-hidden="true">
      <g fill={color}>
        <rect x="3" y="0" width="12" height="8" />
        <rect class="claw-l" x="1" y="4" width="2" height="2" />
        <rect class="claw-r" x="15" y="4" width="2" height="2" />
        <g class="legs-a">
          <rect x="4" y="8" width="1" height="2" />
          <rect x="11" y="8" width="1" height="2" />
        </g>
        <g class="legs-b">
          <rect x="6" y="8" width="1" height="2" />
          <rect x="13" y="8" width="1" height="2" />
        </g>
      </g>
      <g class="eyes" fill="#2a1e1a">
        <rect x="5" y="2" width="1" height="2" />
        <rect x="12" y="2" width="1" height="2" />
      </g>
    </svg>
  )
}

export function Avatar({ agent, size = 44, busy = false }: { agent: Pick<Agent, 'id' | 'avatar' | 'order'>; size?: number; busy?: boolean }) {
  const style = { width: `${size}px`, height: `${size}px` }
  if (agent.avatar === 'file') {
    return (
      <span class={`avatar ${busy ? 'busy' : ''}`} style={style}>
        <img src={api.avatarUrl(agent as Agent)} alt="" loading="lazy" decoding="async" />
      </span>
    )
  }
  const key = agent.avatar?.startsWith('crab:') ? agent.avatar.slice(5) : 'pink'
  const c = CRAB_COLORS[key] || CRAB_COLORS.pink
  return (
    <span class={`avatar ${busy ? 'busy' : ''}`} style={{ ...style, background: c.bg }}>
      <Crab color={c.body} />
    </span>
  )
}

// Claude Code's spinner glyphs, drawn as SVG so iOS never swaps them for emoji:
// · (interpunct), ✢ (four teardrop-spoked), ✳ (eight-spoked), ✶ (six-pointed star), ✻ (teardrop-spoked), ✽ (heavy teardrop-spoked).
// The CLI plays them forward, then backward.

const tear = (len: number, w: number, a: number) => {
  const t = 12 - len
  return <path transform={`rotate(${a} 12 12)`}
    d={`M12 12C${12 - w} ${12 - len * 0.45} ${12 - w} ${t} 12 ${t}C${12 + w} ${t} ${12 + w} ${12 - len * 0.45} 12 12Z`} />
}
const star = (points: number, outer: number, inner: number) => {
  const pts: string[] = []
  for (let i = 0; i < points * 2; i++) {
    const r = i % 2 ? inner : outer
    const a = (Math.PI * i) / points - Math.PI / 2
    pts.push(`${(12 + Math.cos(a) * r).toFixed(2)},${(12 + Math.sin(a) * r).toFixed(2)}`)
  }
  return <polygon points={pts.join(' ')} />
}
const spokes = (n: number) => Array.from({ length: n }, (_, i) => i * (360 / n))

const GLYPHS = [
  <circle cx="12" cy="12" r="2.6" />,
  <g>{spokes(4).map((a) => tear(9.5, 2.6, a))}</g>,
  <g stroke="currentColor" stroke-width="2.3" stroke-linecap="round">
    {spokes(8).map((a) => <line transform={`rotate(${a} 12 12)`} x1="12" y1="12" x2="12" y2="2.8" />)}
  </g>,
  star(6, 10, 4.6),
  <g>{spokes(6).map((a) => tear(10, 2.5, a))}</g>,
  <g>{spokes(8).map((a) => tear(10.5, 3.1, a + 22.5))}</g>,
]
const FRAMES = [0, 1, 2, 3, 4, 5, 4, 3, 2, 1]

// One shared ticker for every spinner on screen.
const frame = signal(0)
let users = 0
let timer: number | undefined
function useTicker() {
  useEffect(() => {
    if (users++ === 0) timer = window.setInterval(() => { frame.value = (frame.value + 1) % FRAMES.length }, 180)
    return () => { if (--users === 0) clearInterval(timer) }
  }, [])
}

/** Claude Code style working indicator. */
export function Spark({ size = 18 }: { size?: number }) {
  useTicker()
  return (
    <span class="spark" style={{ width: `${size}px`, height: `${size}px` }} aria-label="Working" role="img">
      <svg viewBox="0 0 24 24" fill="currentColor">{GLYPHS[FRAMES[frame.value]]}</svg>
    </span>
  )
}
