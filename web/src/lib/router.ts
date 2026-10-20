// Tiny history router with direction-aware page transitions.

import { signal } from '@preact/signals'

/** Agent id that owns temporary sessions. It has its own sessions page and settings, but is not in the agent list. */
export const TEMP_AGENT = '_temp'

export type Route =
  | { name: 'home' }
  | { name: 'agent'; agentId: string }
  | { name: 'agent-settings'; agentId: string }
  | { name: 'new-agent' }
  | { name: 'chat'; agentId: string; sessionId: string }
  | { name: 'settings' }
  | { name: 'memory' }

export function parse(path: string): Route {
  const p = path.replace(/\/+$/, '').split('/').filter(Boolean).map(decodeURIComponent)
  if (p[0] === 'agents' && p[1] === 'new') return { name: 'new-agent' }
  if (p[0] === 'agents' && p[1] && p[2] === 'settings') return { name: 'agent-settings', agentId: p[1] }
  if (p[0] === 'agents' && p[1] && p[2] === 's' && p[3]) return { name: 'chat', agentId: p[1], sessionId: p[3] }
  if (p[0] === 'agents' && p[1]) return { name: 'agent', agentId: p[1] }
  if (p[0] === 'settings' && p[1] === 'memory') return { name: 'memory' }
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
    case 'memory': return '/settings/memory'
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

/**
 * Installed PWA. iOS runs its own edge-swipe back there, which reloads or double-navigates, so
 * standalone never grows browser history: pages live on an in-memory stack and every move is a
 * replaceState. With nothing to go back to, the system gesture does nothing.
 */
const STANDALONE = !!(navigator as any).standalone || matchMedia('(display-mode: standalone)').matches
const stack: string[] = []

let depth = STANDALONE ? 0 : (history.state && history.state.depth) || 0
if (!history.state || STANDALONE) history.replaceState({ depth }, '')

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
    if (STANDALONE) { stack.push(location.pathname); history.replaceState({ depth }, '', url) }
    else history.pushState({ depth }, '', url)
    scrollMemory.delete(entryKey())
    direction.value = opts.animate === false ? 'none' : 'forward'
  }
  route.value = parse(url)
}

/** Where Back leads when there is no history entry to return to. */
export function parentOf(r: Route): Route {
  switch (r.name) {
    case 'chat': return { name: 'agent', agentId: r.agentId }
    case 'agent-settings': return { name: 'agent', agentId: r.agentId }
    case 'memory': return { name: 'settings' }
    default: return { name: 'home' }
  }
}

/** Go back in history if we pushed a page, otherwise to the given fallback. */
export function back(fallback: Route = { name: 'home' }) {
  if (STANDALONE) {
    const url = stack.pop()
    if (url === undefined) return navigate(fallback, { replace: true })
    depth--
    history.replaceState({ depth }, '', url)
    direction.value = 'back'
    route.value = parse(url)
    return
  }
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
