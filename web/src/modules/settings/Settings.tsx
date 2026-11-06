// Settings in three levels: home (profile + one row per module) > module page (its categories) > section page.
// Modules own their section components; this file only lists and frames them.

import type { JSX } from 'preact'
import { back, navigate } from '../../lib/router'
import { BackButton, TopBar, useScrolled } from '../../components/ui'
import { IconChevron } from '../../components/icons'
import { ProfileCard } from '../chat/profile'
import { SECTIONS, MODULES, type Section } from './registry'
import { moduleOf, type SettingsModule } from './modules'

export function SettingsHome() {
  const { scrolled, onScroll, ref } = useScrolled()
  return (
    <div class="page wide-page">
      <TopBar scrolled={scrolled} left={<BackButton label="More" onClick={() => back({ name: 'more' })} />}>
        <span class="topbar-center">Settings</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">
          <ProfileCard />
          <div class="group-title">Modules</div>
          <div class="group">{MODULES.map((m) => <ModuleRow key={m.key} m={m} />)}</div>
        </div>
      </div>
    </div>
  )
}

function ModuleRow({ m }: { m: SettingsModule }) {
  const Icon = m.icon
  return (
    <button type="button" class="row" onClick={() => navigate({ name: 'settings-module', module: m.key })}>
      <span class="settings-icon"><Icon width={18} height={18} /></span>
      <span class="label">{m.title}<span class="hint">{m.hint}</span></span>
      <IconChevron class="chev" />
    </button>
  )
}

/** /settings/<module>: the module's categories. A module with a single section still gets this page. */
export function SettingsModulePage({ module }: { module: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const m = moduleOf(module)
  if (!m) return <SettingsHome />
  return (
    <div class="page wide-page">
      <TopBar scrolled={scrolled} left={<BackButton label="Settings" onClick={() => back({ name: 'settings' })} />}>
        <span class="topbar-center">{m.title}</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">
          <div class="group">{SECTIONS.filter((s) => s.module === m.key).map((s) => <SectionRow key={s.key} s={s} />)}</div>
        </div>
      </div>
    </div>
  )
}

function SectionRow({ s }: { s: Section }) {
  const Icon = s.icon
  return (
    <button type="button" class="row" onClick={() => navigate({ name: 'settings-section', module: s.module, section: s.key })}>
      <span class="settings-icon"><Icon width={18} height={18} /></span>
      <span class="label">{s.title}<span class="hint">{s.hint}</span></span>
      <IconChevron class="chev" />
    </button>
  )
}

/** /settings/<module>/<section>: a leaf page, framed by SettingsFrame. */
export function SettingsSection({ module, section }: { module: string; section: string }) {
  const s = SECTIONS.find((x) => x.module === module && x.key === section)
  if (!s) return <SettingsModulePage module={module} />
  const C = s.Component as (p: { title: string }) => JSX.Element
  return <C title={s.title} />
}
