// ACP agent routes. They live on the Agents tab (see modules/agents/Home.tsx, "ACP" segment).

import type { Route } from '../../lib/router'
import { AcpAgentPage } from './AgentPage'
import { AcpAgentSettings } from './AgentSettings'
import { AcpChat } from './chat/Chat'

export function AcpRoute(r: Route) {
  switch (r.name) {
    case 'acp': return <AcpAgentPage agentId={r.agentId} />
    case 'acp-settings': return <AcpAgentSettings agentId={r.agentId} />
    case 'new-acp': return <AcpAgentSettings />
    case 'acp-chat': return <AcpChat agentId={r.agentId} sessionId={r.sessionId} />
  }
  return null
}

export function acpSplit(r: Route) {
  if (r.name !== 'acp' && r.name !== 'acp-chat' && r.name !== 'acp-settings') return null
  return (
    <div class="split">
      <div class="split-side" key={`side:${r.agentId}`}><AcpAgentPage agentId={r.agentId} /></div>
      <div class="split-main">
        {r.name === 'acp-chat'
          ? <div key={r.sessionId} class="route enter-fade"><AcpChat agentId={r.agentId} sessionId={r.sessionId} /></div>
          : r.name === 'acp-settings'
            ? <div key="settings" class="route enter-fade"><AcpAgentSettings agentId={r.agentId} /></div>
            : <div class="split-empty">Pick a conversation</div>}
      </div>
    </div>
  )
}
