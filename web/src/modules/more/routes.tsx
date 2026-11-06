// More tab: entry cards (Settings, Claude Code Memory, About) and room for future tools.

import { useEffect, useState } from 'preact/hooks'
import type { Route } from '../../lib/router'
import { navigate, back } from '../../lib/router'
import { api } from '../../lib/api'
import { meta } from '../../lib/store'
import { Crab } from '../../components/crab'
import { BackButton, TopBar, useScrolled } from '../../components/ui'
import { IconChevron, IconSettings, IconBrain } from '../../components/icons'
import { SettingsHome, SettingsModulePage, SettingsSection } from '../settings/Settings'

export function MoreRoute(r: Route) {
  switch (r.name) {
    case 'more': return <More />
    case 'about': return <About />
    case 'settings': return <SettingsHome />
    case 'settings-module': return <SettingsModulePage module={r.module} />
    case 'settings-section': return <SettingsSection module={r.module} section={r.section} />
  }
  return null
}

function useVersion() {
  const [v, setV] = useState(meta.value?.version || '')
  useEffect(() => { if (!v) api.meta().then((m) => { meta.value = m; setV(m.version) }).catch(() => {}) }, [])
  return v
}

function More() {
  const { scrolled, onScroll, ref } = useScrolled()
  const version = useVersion()
  return (
    <div class="page">
      <TopBar scrolled={scrolled}>{scrolled && <span class="fade-in">More</span>}</TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">More</h1>
          <div class="more-grid">
            <button class="more-card press rise" style={{ '--i': 1 }} onClick={() => navigate({ name: 'settings' })}>
              <span class="more-icon"><IconSettings /></span>
              <span class="more-text"><span class="n">Settings</span><span class="p">Chat, Agents, Workflow and server</span></span>
              <IconChevron class="more-chev" />
            </button>
            <button class="more-card press rise" style={{ '--i': 2 }} onClick={() => navigate({ name: 'memory' })}>
              <span class="more-icon"><IconBrain /></span>
              <span class="more-text"><span class="n">Claude Code Memory</span><span class="p">Memory files of Claude Code agents</span></span>
              <IconChevron class="more-chev" />
            </button>
            <button class="more-card about-card press rise" style={{ '--i': 3 }} onClick={() => navigate({ name: 'about' })}>
              <span class="about-crab crab-wave"><Crab /></span>
              <span class="more-text"><span class="n">next-agent</span><span class="p">{version ? `Version ${version}` : 'About'}</span></span>
              <IconChevron class="more-chev" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function About() {
  const version = useVersion()
  return (
    <div class="page">
      <TopBar left={<BackButton onClick={() => back({ name: 'more' })} />} title="About" />
      <div class="page-scroll">
        <div class="container about">
          <div class="about-hero rise">
            <div class="about-clawd crab-walk"><Crab /></div>
            <h1 class="serif">next-agent</h1>
            <p class="about-version">{version ? `Version ${version}` : ' '}</p>
          </div>
          <div class="group rise" style={{ '--i': 1 }}>
            <div class="row"><span class="label">Chat<span class="hint">LLM chats with your own model APIs</span></span></div>
            <div class="row"><span class="label">Agents<span class="hint">Claude Code and ACP agents</span></span></div>
            <div class="row"><span class="label">Workflow<span class="hint">Card-based automations</span></span></div>
          </div>
          <p class="about-made rise" style={{ '--i': 2 }}>Made by Claude Opus 5.5</p>
        </div>
      </div>
    </div>
  )
}
