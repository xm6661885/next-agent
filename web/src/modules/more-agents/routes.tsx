// More Agents routes. They live on the Agents tab.

import type { Route } from '../../lib/router'
import { MoreAgentPage } from './AgentPage'
import { MoreAgentSettings } from './AgentSettings'
import { MoreAgentChat } from './chat/Chat'

export function MoreAgentsRoute(r: Route) {
  switch (r.name) {
    case 'more-agent': return <MoreAgentPage agentId={r.agentId} />
    case 'more-agent-settings': return <MoreAgentSettings agentId={r.agentId} />
    case 'new-more-agent': return <MoreAgentSettings />
    case 'more-agent-chat': return <MoreAgentChat agentId={r.agentId} sessionId={r.sessionId} />
  }
  return null
}

export function moreAgentsSplit(r: Route) {
  if (r.name !== 'more-agent' && r.name !== 'more-agent-chat' && r.name !== 'more-agent-settings') return null
  return (
    <div class="split">
      <div class="split-side" key={`side:${r.agentId}`}><MoreAgentPage agentId={r.agentId} /></div>
      <div class="split-main">
        {r.name === 'more-agent-chat'
          ? <div key={r.sessionId} class="route enter-fade"><MoreAgentChat agentId={r.agentId} sessionId={r.sessionId} /></div>
          : r.name === 'more-agent-settings'
            ? <div key="settings" class="route enter-fade"><MoreAgentSettings agentId={r.agentId} /></div>
            : <div class="split-empty">Pick a conversation</div>}
      </div>
    </div>
  )
}
