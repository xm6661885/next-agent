// Shared frame for second-level settings pages, plus a small hook for the Agents/core config form.

import type { ComponentChildren } from 'preact'
import { useEffect, useState } from 'preact/hooks'
import { back } from '../../lib/router'
import { api } from '../../lib/api'
import { meta, toast, toastError } from '../../lib/store'
import { BackButton, TopBar, useScrolled } from '../../components/ui'
import type { ConfigForm } from '../../lib/types'

export function SettingsFrame({ title, dirty, saving, onSave, children }: {
  title: string; dirty?: boolean; saving?: boolean; onSave?: () => void; children: ComponentChildren
}) {
  const { scrolled, onScroll, ref } = useScrolled()
  return (
    <div class="page wide-page">
      <TopBar scrolled={scrolled} left={<BackButton label="Settings" onClick={() => back({ name: 'settings' })} />}
        right={onSave && <button class="btn primary small" disabled={!dirty || saving} onClick={onSave}>{saving ? <span class="spinner" /> : 'Save'}</button>}>
        <span class="topbar-center">{title}</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">{children}</div>
      </div>
    </div>
  )
}

/** Load ConfigForm, edit a draft, and PATCH only the given part on save. */
export function useConfigForm() {
  const [form, setForm] = useState<ConfigForm | null>(null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const load = (f: ConfigForm) => { setForm(f); setOrig(JSON.stringify(f)) }
  useEffect(() => { api.config().then(load).catch(toastError) }, [])
  const save = async (patch: Partial<ConfigForm>) => {
    setSaving(true)
    try {
      load(await api.updateConfig(patch))
      api.meta().then((m) => { meta.value = m }).catch(() => {})
      toast('Settings saved')
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  return { form, setForm, dirty: form !== null && JSON.stringify(form) !== orig, saving, save, reload: () => api.config().then(load).catch(() => {}) }
}
