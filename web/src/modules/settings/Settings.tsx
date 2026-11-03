// Settings home: one category per module, each opens a second-level page with that module's settings.
// Modules own their section components; this file only lists and frames them.

import type { JSX } from 'preact'
import { back, navigate } from '../../lib/router'
import { BackButton, TopBar, useScrolled } from '../../components/ui'
import { IconChevron } from '../../components/icons'
import { SECTIONS, MODULES, type Section } from './registry'

export function SettingsHome() {
  const { scrolled, onScroll, ref } = useScrolled()
  return (
    <div class="page wide-page">
      <TopBar scrolled={scrolled} left={<BackButton label="More" onClick={() => back({ name: 'more' })} />}>
        <span class="topbar-center">Settings</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">
          {MODULES.map((m) => (
            <div key={m.key}>
              <div class="group-title">{m.title}</div>
              <div class="group">
                {SECTIONS.filter((s) => s.module === m.key).map((s) => <SectionRow key={s.key} s={s} />)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SectionRow({ s }: { s: Section }) {
  const Icon = s.icon
  return (
    <button type="button" class="row" onClick={() => navigate({ name: 'settings-section', section: s.key })}>
      <span class="settings-icon"><Icon width={18} height={18} /></span>
      <span class="label">{s.title}<span class="hint">{s.hint}</span></span>
      <IconChevron class="chev" />
    </button>
  )
}

export function SettingsSection({ section }: { section: string }) {
  const s = SECTIONS.find((x) => x.key === section)
  if (!s) return <SettingsHome />
  const C = s.Component as (p: { title: string }) => JSX.Element
  return <C title={s.title} />
}
