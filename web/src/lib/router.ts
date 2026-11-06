// Tiny history router with direction-aware page transitions.

import { signal } from '@preact/signals'

/** Agent id that owns temporary sessions. It has its own sessions page and settings, but is not in the agent list. */
export const TEMP_AGENT = '_temp'

export type Tab = 'chat' | 'agents' | 'automations' | 'workflow' | 'more'
export const TABS: Tab[] = ['chat', 'agents', 'automations', 'workflow', 'more']

export type Route =
  | { name: 'home' }
  | { name: 'agent'; agentId: string }
  | { name: 'agent-settings'; agentId: string }
  | { name: 'new-agent' }
  | { name: 'chat'; agentId: string; sessionId: string }
  | { name: 'memory' }
  | { name: 'acp'; agentId: string }
  | { name: 'acp-settings'; agentId: string }
  | { name: 'new-acp' }
  | { name: 'acp-chat'; agentId: string; sessionId: string }
  | { name: 'chats' }
  | { name: 'assistant'; assistantId: string }
  | { name: 'assistant-settings'; assistantId: string }
  | { name: 'assistant-files'; assistantId: string }
  | { name: 'assistant-memory'; assistantId: string }
  | { name: 'new-assistant' }
  | { name: 'llm-chat'; assistantId: string; sessionId: string }
  | { name: 'automations' }
  | { name: 'automation-task'; taskId: string }
  | { name: 'automation-edit'; taskId: string }
  | { name: 'automation-new' }
  | { name: 'automation-run'; runId: string }
  | { name: 'automation-runs' }
  | { name: 'workflows' }
  | { name: 'wf-editor'; workflowId: string }
  | { name: 'wf-run'; runId: string }
  | { name: 'wf-runs'; workflowId?: string }
  | { name: 'wf-console' }
  | { name: 'more' }
  | { name: 'about' }
  | { name: 'settings' }
  | { name: 'settings-module'; module: string }
  | { name: 'settings-section'; module: string; section: string }

/** Which bottom tab a route belongs to; tab roots show the tab bar. */
export function tabOf(r: Route): Tab {
  if (r.name === 'chats' || r.name.startsWith('assistant') || r.name === 'new-assistant' || r.name === 'llm-chat') return 'chat'
  if (r.name.startsWith('automation')) return 'automations'
  if (r.name.startsWith('wf') || r.name === 'workflows') return 'workflow'
  if (r.name === 'more' || r.name === 'about' || r.name.startsWith('settings') || r.name === 'memory') return 'more'
  return 'agents'
}
export const isTabRoot = (r: Route) => r.name === 'home' || r.name === 'chats' || r.name === 'automations' || r.name === 'workflows' || r.name === 'wf-console' || r.name === 'more'
export const tabRoot = (t: Tab): Route => ({ chat: { name: 'chats' }, agents: { name: 'home' }, automations: { name: 'automations' }, workflow: { name: 'workflows' }, more: { name: 'more' } } as const)[t]

export function parse(path: string): Route {
  const [pathname, qs] = path.split('?')
  const p = pathname.replace(/\/+$/, '').split('/').filter(Boolean).map(decodeURIComponent)
  const q = new URLSearchParams(qs || '')
  if (p[0] === 'agents' && p[1] === 'new') return { name: 'new-agent' }
  if (p[0] === 'agents' && p[1] && p[2] === 'settings') return { name: 'agent-settings', agentId: p[1] }
  if (p[0] === 'agents' && p[1] && p[2] === 's' && p[3]) return { name: 'chat', agentId: p[1], sessionId: p[3] }
  if (p[0] === 'agents' && p[1]) return { name: 'agent', agentId: p[1] }
  if (p[0] === 'agents') return { name: 'home' }
  if (p[0] === 'acp' && p[1] === 'new') return { name: 'new-acp' }
  if (p[0] === 'acp' && p[1] && p[2] === 'settings') return { name: 'acp-settings', agentId: p[1] }
  if (p[0] === 'acp' && p[1] && p[2] === 's' && p[3]) return { name: 'acp-chat', agentId: p[1], sessionId: p[3] }
  if (p[0] === 'acp' && p[1]) return { name: 'acp', agentId: p[1] }
  if (p[0] === 'chat' && p[1] === 'new') return { name: 'new-assistant' }
  if (p[0] === 'chat' && p[1] && p[2] === 'settings') return { name: 'assistant-settings', assistantId: p[1] }
  if (p[0] === 'chat' && p[1] && p[2] === 'files') return { name: 'assistant-files', assistantId: p[1] }
  if (p[0] === 'chat' && p[1] && p[2] === 'memory') return { name: 'assistant-memory', assistantId: p[1] }
  if (p[0] === 'chat' && p[1] && p[2] === 's' && p[3]) return { name: 'llm-chat', assistantId: p[1], sessionId: p[3] }
  if (p[0] === 'chat' && p[1]) return { name: 'assistant', assistantId: p[1] }
  if (p[0] === 'chat') return { name: 'chats' }
  if (p[0] === 'automations' && p[1] === 'new') return { name: 'automation-new' }
  if (p[0] === 'automations' && p[1] === 'runs') return { name: 'automation-runs' }
  if (p[0] === 'automations' && p[1] === 'r' && p[2]) return { name: 'automation-run', runId: p[2] }
  if (p[0] === 'automations' && p[1] === 't' && p[2] && p[3] === 'edit') return { name: 'automation-edit', taskId: p[2] }
  if (p[0] === 'automations' && p[1] === 't' && p[2]) return { name: 'automation-task', taskId: p[2] }
  if (p[0] === 'automations') return { name: 'automations' }
  if (p[0] === 'workflow' && p[1] === 'w' && p[2]) return { name: 'wf-editor', workflowId: p[2] }
  if (p[0] === 'workflow' && p[1] === 'r' && p[2]) return { name: 'wf-run', runId: p[2] }
  if (p[0] === 'workflow' && p[1] === 'runs') return { name: 'wf-runs', workflowId: q.get('workflow') || undefined }
  if (p[0] === 'workflow' && p[1] === 'console') return { name: 'wf-console' }
  if (p[0] === 'workflow') return { name: 'workflows' }
  if (p[0] === 'more' && p[1] === 'about') return { name: 'about' }
  if (p[0] === 'more' && p[1] === 'memory') return { name: 'memory' }
  if (p[0] === 'more') return { name: 'more' }
  if (p[0] === 'settings' && p[1] && p[2]) return { name: 'settings-section', module: p[1], section: p[2] }
  if (p[0] === 'settings' && p[1]) return { name: 'settings-module', module: p[1] }
  if (p[0] === 'settings') return { name: 'settings' }
  if (p.length === 0) return tabRoot(lastTab())
  return { name: 'home' }
}

export function href(r: Route): string {
  const e = encodeURIComponent
  switch (r.name) {
    case 'home': return '/agents'
    case 'new-agent': return '/agents/new'
    case 'agent': return `/agents/${e(r.agentId)}`
    case 'agent-settings': return `/agents/${e(r.agentId)}/settings`
    case 'chat': return `/agents/${e(r.agentId)}/s/${e(r.sessionId)}`
    case 'memory': return '/more/memory'
    case 'new-acp': return '/acp/new'
    case 'acp': return `/acp/${e(r.agentId)}`
    case 'acp-settings': return `/acp/${e(r.agentId)}/settings`
    case 'acp-chat': return `/acp/${e(r.agentId)}/s/${e(r.sessionId)}`
    case 'chats': return '/chat'
    case 'new-assistant': return '/chat/new'
    case 'assistant': return `/chat/${e(r.assistantId)}`
    case 'assistant-settings': return `/chat/${e(r.assistantId)}/settings`
    case 'assistant-files': return `/chat/${e(r.assistantId)}/files`
    case 'assistant-memory': return `/chat/${e(r.assistantId)}/memory`
    case 'llm-chat': return `/chat/${e(r.assistantId)}/s/${e(r.sessionId)}`
    case 'automations': return '/automations'
    case 'automation-new': return '/automations/new'
    case 'automation-runs': return '/automations/runs'
    case 'automation-run': return `/automations/r/${e(r.runId)}`
    case 'automation-task': return `/automations/t/${e(r.taskId)}`
    case 'automation-edit': return `/automations/t/${e(r.taskId)}/edit`
    case 'workflows': return '/workflow'
    case 'wf-editor': return `/workflow/w/${e(r.workflowId)}`
    case 'wf-run': return `/workflow/r/${e(r.runId)}`
    case 'wf-runs': return `/workflow/runs${r.workflowId ? `?workflow=${e(r.workflowId)}` : ''}`
    case 'wf-console': return '/workflow/console'
    case 'more': return '/more'
    case 'about': return '/more/about'
    case 'settings': return '/settings'
    case 'settings-module': return `/settings/${e(r.module)}`
    case 'settings-section': return `/settings/${e(r.module)}/${e(r.section)}`
  }
}

const TAB_KEY = 'last-tab'
export function lastTab(): Tab {
  const t = localStorage.getItem(TAB_KEY) as Tab | null
  return t && TABS.includes(t) ? t : 'agents'
}
export const rememberTab = (t: Tab) => localStorage.setItem(TAB_KEY, t)

/** Desktop split layout: wide window with a mouse. */
const WIDE = matchMedia('(min-width: 1000px) and (hover: hover)')
export const wide = signal(WIDE.matches)
WIDE.addEventListener('change', () => { wide.value = WIDE.matches })

export const route = signal<Route>(parse(location.pathname + location.search))
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
  if (url === location.pathname + location.search) return
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
    case 'chat': case 'agent-settings': return { name: 'agent', agentId: r.agentId }
    case 'acp-chat': case 'acp-settings': return { name: 'acp', agentId: r.agentId }
    case 'llm-chat': case 'assistant-settings': case 'assistant-files': case 'assistant-memory': return { name: 'assistant', assistantId: r.assistantId }
    case 'assistant': case 'new-assistant': return { name: 'chats' }
    case 'automation-task': case 'automation-new': case 'automation-runs': case 'automation-run': return { name: 'automations' }
    case 'automation-edit': return { name: 'automation-task', taskId: r.taskId }
    case 'wf-editor': case 'wf-run': case 'wf-runs': case 'wf-console': return { name: 'workflows' }
    case 'settings-section': return { name: 'settings-module', module: r.module }
    case 'settings-module': return { name: 'settings' }
    case 'settings': case 'about': case 'memory': return { name: 'more' }
    default: return { name: 'home' }
  }
}

/** Switch bottom tab: no history entry, no slide animation. */
export function switchTab(t: Tab) {
  rememberTab(t)
  navigate(tabRoot(t), { replace: true })
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
  route.value = parse(location.pathname + location.search)
})
