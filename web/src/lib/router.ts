// Tiny history router with direction-aware page transitions and swipe-back support.

import { signal } from '@preact/signals'

export type Route =
  | { name: 'home' }
  | { name: 'agent'; agentId: string }
  | { name: 'agent-settings'; agentId: string }
  | { name: 'new-agent' }
  | { name: 'chat'; agentId: string; sessionId: string }
  | { name: 'settings' }

export function parse(path: string): Route {
  const p = path.replace(/\/+$/, '').split('/').filter(Boolean).map(decodeURIComponent)
  if (p[0] === 'agents' && p[1] === 'new') return { name: 'new-agent' }
  if (p[0] === 'agents' && p[1] && p[2] === 'settings') return { name: 'agent-settings', agentId: p[1] }
  if (p[0] === 'agents' && p[1] && p[2] === 's' && p[3]) return { name: 'chat', agentId: p[1], sessionId: p[3] }
  if (p[0] === 'agents' && p[1]) return { name: 'agent', agentId: p[1] }
  if (p[0] === 'settings') return { name: 'settings' }
  return { name: 'home' }
}

export function href(r: Route): string {
  const e = encodeURIComponent
  switch (r.name) {
    case 'home': return '/'
    case 'new-agent': return '/agents/new'
    case 'agent': return `/agents/${e(r.agentId)}`
    case 'agent-settings': return `/agents/${e(r.agentId)}/settings`
    case 'chat': return `/agents/${e(r.agentId)}/s/${e(r.sessionId)}`
    case 'settings': return '/settings'
  }
}

/** Desktop split layout: wide window with a mouse. */
const WIDE = matchMedia('(min-width: 1000px) and (hover: hover)')
export const wide = signal(WIDE.matches)
WIDE.addEventListener('change', () => { wide.value = WIDE.matches })

export const route = signal<Route>(parse(location.pathname))
export const direction = signal<'forward' | 'back' | 'fade' | 'none'>('fade')

// Only a back we trigger (the top-left button) animates; system gestures and browser back already
// show the previous page, so replaying the enter animation looks like a flash.
let ownBack = false

let depth = (history.state && history.state.depth) || 0
if (!history.state) history.replaceState({ depth }, '')

/** Scroll offsets per history entry, so going back (button or swipe) lands where the user left. */
export const scrollMemory = new Map<string, number>()
export const entryKey = () => `${depth}:${location.pathname}`

export function navigate(r: Route | string, opts: { replace?: boolean; animate?: boolean } = {}) {
  const url = typeof r === 'string' ? r : href(r)
  if (url === location.pathname) return
  if (opts.replace) {
    history.replaceState({ depth }, '', url)
    scrollMemory.delete(entryKey())
    direction.value = 'fade'
  } else {
    depth++
    history.pushState({ depth }, '', url)
    scrollMemory.delete(entryKey())
    direction.value = opts.animate === false ? 'none' : 'forward'
  }
  route.value = parse(url)
}

/** Where Back leads when there is no history entry to return to. */
export function parentOf(r: Route): Route {
  switch (r.name) {
    case 'chat': case 'agent-settings': return { name: 'agent', agentId: r.agentId }
    default: return { name: 'home' }
  }
}

/** Go back in history if we pushed a page, otherwise to the given fallback. */
export function back(fallback: Route = { name: 'home' }) {
  if (depth > 0) { ownBack = true; history.back() }
  else navigate(fallback, { replace: true })
}

window.addEventListener('popstate', (e) => {
  const d = (e.state && e.state.depth) || 0
  direction.value = d < depth ? (ownBack ? 'back' : 'none') : 'forward'
  ownBack = false
  depth = d
  route.value = parse(location.pathname)
})

/**
 * Edge swipe to go back on touch devices when running standalone (Safari's own gesture
 * covers the browser case). Attach to a page root element.
 */
export function attachSwipeBack(el: HTMLElement, onBack: () => void) {
  const standalone = (navigator as any).standalone || matchMedia('(display-mode: standalone)').matches
  if (!standalone) return () => {}
  let startX = 0, startY = 0, dx = 0, active = false, decided = false, startPath = ''
  const onStart = (e: TouchEvent) => {
    const t = e.touches[0]
    if (t.clientX > 24) return
    startX = t.clientX; startY = t.clientY; dx = 0; active = true; decided = false; startPath = location.pathname
  }
  // Newer iOS versions run their own edge-swipe back in standalone apps too. When the system already
  // navigated, drop our gesture so the two do not go back twice (chat -> agent -> home).
  const onPop = () => {
    if (!active && !el.style.transform) return
    active = false
    el.style.transition = ''
    el.style.transform = ''
    el.style.boxShadow = ''
  }
  window.addEventListener('popstate', onPop)
  const onMove = (e: TouchEvent) => {
    if (!active) return
    const t = e.touches[0]
    dx = t.clientX - startX
    const dy = t.clientY - startY
    if (!decided) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return
      decided = true
      if (Math.abs(dy) > Math.abs(dx) || dx < 0) { active = false; return }
    }
    el.style.transition = 'none'
    el.style.transform = `translate3d(${Math.max(0, dx)}px,0,0)`
    el.style.boxShadow = '-12px 0 30px rgba(0,0,0,0.12)'
  }
  const onEnd = () => {
    if (!active) return
    active = false
    const w = el.clientWidth
    el.style.transition = 'transform 0.28s cubic-bezier(0.32,0.72,0,1)'
    if (location.pathname !== startPath) return
    if (dx > w * 0.33) {
      el.style.transform = `translate3d(${w}px,0,0)`
      setTimeout(() => { if (location.pathname === startPath) onBack() }, 200)
    } else {
      el.style.transform = ''
      setTimeout(() => { el.style.boxShadow = ''; el.style.transition = '' }, 300)
    }
  }
  el.addEventListener('touchstart', onStart, { passive: true })
  el.addEventListener('touchmove', onMove, { passive: true })
  el.addEventListener('touchend', onEnd)
  el.addEventListener('touchcancel', onEnd)
  return () => {
    window.removeEventListener('popstate', onPop)
    el.removeEventListener('touchstart', onStart)
    el.removeEventListener('touchmove', onMove)
    el.removeEventListener('touchend', onEnd)
    el.removeEventListener('touchcancel', onEnd)
  }
}
