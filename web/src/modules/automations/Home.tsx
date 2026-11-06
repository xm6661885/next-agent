// Automations tab home (placeholder): scheduled scripts, webhooks and one-off tasks will live here.

import { TopBar, useScrolled } from '../../components/ui'

export function Automations() {
  const { scrolled, onScroll, ref } = useScrolled()
  return (
    <div class="page">
      <TopBar scrolled={scrolled}>{scrolled && <span class="fade-in">Automations</span>}</TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Automations</h1>
          <p class="subtitle rise" style={{ '--i': 1 }}>Scheduled scripts, webhooks and one-off tasks.</p>
        </div>
      </div>
    </div>
  )
}
