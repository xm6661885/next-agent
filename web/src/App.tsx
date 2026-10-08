import { useEffect, useRef } from 'preact/hooks'
import { api } from './lib/api'
import { authed, connectEvents, disconnectEvents } from './lib/store'
import { attachSwipeBack, back, direction, parentOf, route, wide } from './lib/router'
import { Login } from './pages/Login'
import { Home } from './pages/Home'
import { AgentPage } from './pages/AgentPage'
import { AgentSettings } from './pages/AgentSettings'
import { Settings } from './pages/Settings'
import { Chat } from './chat/Chat'
import { DialogHost, Toasts } from './components/ui'
import { Crab } from './components/crab'
import { ImageViewerHost } from './components/ImageViewer'

export function App() {
  useEffect(() => {
    api.me().then(() => { authed.value = true }).catch(() => { authed.value = false })
  }, [])

  useEffect(() => {
    if (authed.value) connectEvents()
    else if (authed.value === false) disconnectEvents()
  }, [authed.value])

  if (authed.value === null) {
    return <div class="boot"><div class="crab-walk boot-crab"><Crab /></div></div>
  }
  if (!authed.value) return <><Login /><Toasts /></>

  return (
    <>
      <Routed />
      <DialogHost />
      <ImageViewerHost />
      <Toasts />
    </>
  )
}

function Routed() {
  const r = route.value
  // Desktop: conversation list on the left, chat on the right, like WeChat for the web.
  if (wide.value && (r.name === 'agent' || r.name === 'chat' || r.name === 'agent-settings')) {
    return (
      <div class="split">
        <div class="split-side" key={`side:${r.agentId}`}><AgentPage agentId={r.agentId} /></div>
        <div class="split-main">
          {r.name === 'chat'
            ? <div key={r.sessionId} class="route enter-fade"><Chat agentId={r.agentId} sessionId={r.sessionId} /></div>
            : r.name === 'agent-settings'
              ? <div key="settings" class="route enter-fade"><AgentSettings agentId={r.agentId} /></div>
              : <div class="split-empty">Pick a conversation</div>}
        </div>
      </div>
    )
  }
  return <Single />
}

function Single() {
  const r = route.value
  const key = JSON.stringify(r)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el || r.name === 'home') return
    return attachSwipeBack(el, () => back(parentOf(r)))
  }, [key])

  let page
  switch (r.name) {
    case 'home': page = <Home />; break
    case 'agent': page = <AgentPage agentId={r.agentId} />; break
    case 'agent-settings': page = <AgentSettings agentId={r.agentId} />; break
    case 'new-agent': page = <AgentSettings />; break
    case 'chat': page = <Chat agentId={r.agentId} sessionId={r.sessionId} />; break
    case 'settings': page = <Settings />; break
  }
  return (
    <div key={key} ref={ref} class={`route enter-${direction.value}`}>
      {page}
    </div>
  )
}
