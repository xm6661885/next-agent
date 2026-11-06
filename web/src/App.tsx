import { useEffect, useRef } from 'preact/hooks'
import { api } from './lib/api'
import { authed, connectEvents, disconnectEvents } from './lib/store'
import { direction, isTabRoot, rememberTab, route, tabOf, wide } from './lib/router'
import { Login } from './pages/Login'
import { DialogHost, Toasts } from './components/ui'
import { Crab } from './components/crab'
import { ImageViewerHost } from './components/ImageViewer'
import { TabBar } from './components/TabBar'
import { AgentsRoute, agentsSplit } from './modules/agents/routes'
import { AcpRoute, acpSplit } from './modules/acp/routes'
import { ChatRoute, chatSplit } from './modules/chat/routes'
import { AutomationsRoute } from './modules/automations/routes'
import { WorkflowRoute } from './modules/workflow/routes'
import { MoreRoute } from './modules/more/routes'
import { CodeViewerHost } from './modules/agents/chat/Artifacts'

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
      <div class="app-shell"><Routed /></div>
      {(isTabRoot(route.value) || wide.value) && <TabBar />}
      <DialogHost />
      <ImageViewerHost /><CodeViewerHost />
      <Toasts />
    </>
  )
}

function Routed() {
  const r = route.value
  useEffect(() => { rememberTab(tabOf(r)) }, [r])
  // Desktop: conversation list on the left, chat on the right, like WeChat for the web.
  if (wide.value) {
    const split = agentsSplit(r) || acpSplit(r) || chatSplit(r)
    if (split) return split
  }
  return <Single />
}

function Single() {
  const r = route.value
  const key = JSON.stringify(r)
  const ref = useRef<HTMLDivElement>(null)
  const page = AgentsRoute(r) || AcpRoute(r) || ChatRoute(r) || AutomationsRoute(r) || WorkflowRoute(r) || MoreRoute(r)
  return (
    <div key={key} ref={ref} class={`route enter-${direction.value} ${isTabRoot(r) ? 'with-tabbar' : ''}`}>
      {page}
    </div>
  )
}
