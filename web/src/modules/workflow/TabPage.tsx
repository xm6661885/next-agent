// Shared frame for the Workflow tab roots (Workflows / Console / Runs): large title, section switch, settings icon.

import type { ComponentChildren } from 'preact'
import { Segmented, TopBar, useScrolled } from '../../components/ui'
import { IconSettings } from '../../components/icons'
import { navigate } from '../../lib/router'

export type Section = 'workflows' | 'console' | 'runs'
const TITLES: Record<Section, string> = { workflows: 'Workflows', console: 'Console', runs: 'Runs' }
const ROUTES = { workflows: { name: 'workflows' }, console: { name: 'wf-console' }, runs: { name: 'wf-runs' } } as const

export function TabPage({ section, subtitle, children, fab }: { section: Section; subtitle?: ComponentChildren; children: ComponentChildren; fab?: ComponentChildren }) {
  const { scrolled, onScroll, ref } = useScrolled()
  return (
    <div class="page">
      <TopBar scrolled={scrolled}
        right={<div class="topbar-actions"><button class="icon-btn" aria-label="Workflow settings" onClick={() => navigate({ name: 'settings-section', section: 'workflow' })}><IconSettings /></button></div>}>
        {scrolled && <span class="fade-in">{TITLES[section]}</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Workflow</h1>
          {subtitle && <p class="subtitle rise" style={{ '--i': 1 }}>{subtitle}</p>}
          <div class="kind-switch wf-switch rise" style={{ '--i': 1 }}>
            <Segmented value={section} onChange={(s) => navigate(ROUTES[s], { replace: true })}
              options={[{ value: 'workflows', label: 'Workflows' }, { value: 'console', label: 'Console' }, { value: 'runs', label: 'Runs' }]} />
          </div>
          {children}
          {fab && <div style={{ height: '72px' }} />}
        </div>
      </div>
      {fab}
    </div>
  )
}
