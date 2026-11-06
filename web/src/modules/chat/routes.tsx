// Chat tab routes.

import type { Route } from '../../lib/router'
import { ChatHome } from './Home'
import { AssistantPage } from './AssistantPage'
import { AssistantSettings } from './AssistantSettings'
import { FilesPage } from './FilesPage'
import { MemoryPage } from './MemoryPage'
import { LlmChat } from './chat/Chat'

export function ChatRoute(r: Route) {
  switch (r.name) {
    case 'chats': return <ChatHome />
    case 'assistant': return <AssistantPage assistantId={r.assistantId} />
    case 'assistant-settings': return <AssistantSettings assistantId={r.assistantId} />
    case 'assistant-files': return <FilesPage assistantId={r.assistantId} />
    case 'assistant-memory': return <MemoryPage assistantId={r.assistantId} />
    case 'new-assistant': return <AssistantSettings />
    case 'llm-chat': return <LlmChat assistantId={r.assistantId} sessionId={r.sessionId} />
  }
  return null
}

export function chatSplit(r: Route) {
  if (r.name !== 'assistant' && r.name !== 'llm-chat' && r.name !== 'assistant-settings' && r.name !== 'assistant-files' && r.name !== 'assistant-memory') return null
  return (
    <div class="split">
      <div class="split-side" key={`side:${r.assistantId}`}><AssistantPage assistantId={r.assistantId} /></div>
      <div class="split-main">
        {r.name === 'llm-chat'
          ? <div key={r.sessionId} class="route enter-fade"><LlmChat assistantId={r.assistantId} sessionId={r.sessionId} /></div>
          : r.name === 'assistant-settings'
            ? <div key="settings" class="route enter-fade"><AssistantSettings assistantId={r.assistantId} /></div>
            : r.name === 'assistant-files'
              ? <div key="files" class="route enter-fade"><FilesPage assistantId={r.assistantId} /></div>
              : r.name === 'assistant-memory'
                ? <div key="memory" class="route enter-fade"><MemoryPage assistantId={r.assistantId} /></div>
                : <div class="split-empty">Pick a conversation</div>}
      </div>
    </div>
  )
}
