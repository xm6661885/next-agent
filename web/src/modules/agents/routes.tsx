// Agents tab routes (Claude agents). ACP agents live in ../acp and share the Agents tab.

import type { Route } from '../../lib/router'
import { Home } from './Home'
import { AgentPage } from './AgentPage'
import { AgentSettings } from './AgentSettings'
import { Memory } from './Memory'
import { Chat } from './chat/Chat'

export function AgentsRoute(r: Route) {
  switch (r.name) {
    case 'home': return <Home />
    case 'agent': return <AgentPage agentId={r.agentId} />
    case 'agent-settings': return <AgentSettings agentId={r.agentId} />
    case 'new-agent': return <AgentSettings />
    case 'chat': return <Chat agentId={r.agentId} sessionId={r.sessionId} />
    case 'memory': return <Memory />
  }
  return null
}

export function agentsSplit(r: Route) {
  if (r.name !== 'agent' && r.name !== 'chat' && r.name !== 'agent-settings') return null
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
