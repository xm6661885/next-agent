// Bottom tab bar: Chat, Agents, Automations, Workflow, More. Shown only on tab root pages (and always on the desktop sidebar rail).

import { route, switchTab, tabOf, type Tab } from '../lib/router'
import { IconChat, IconAgents, IconAutomation, IconLayers, IconMore } from './icons'
import { haptic } from '../lib/util'
import { attention } from '../lib/store'

const ITEMS: { tab: Tab; label: string; Icon: typeof IconChat }[] = [
  { tab: 'chat', label: 'Chat', Icon: IconChat },
  { tab: 'agents', label: 'Agents', Icon: IconAgents },
  { tab: 'automations', label: 'Automations', Icon: IconAutomation },
  { tab: 'workflow', label: 'Workflow', Icon: IconLayers },
  { tab: 'more', label: 'More', Icon: IconMore },
]

export function TabBar() {
  const current = tabOf(route.value)
  const badge = attention.value
  return (
    <nav class="tabbar" aria-label="Sections">
      {ITEMS.map(({ tab, label, Icon }) => (
        <button key={tab} class={`tabbar-item ${current === tab ? 'on' : ''}`} aria-current={current === tab ? 'page' : undefined}
          onClick={() => { if (current !== tab) haptic(); switchTab(tab) }}>
          <span class="tabbar-icon"><Icon />{badge[tab] > 0 && <span class="tabbar-badge" aria-label={`${badge[tab]} need you`} />}</span>
          <span class="tabbar-label">{label}</span>
        </button>
      ))}
    </nav>
  )
}
