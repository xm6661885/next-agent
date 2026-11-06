// Settings > More Agents: connection idle timeout and agent groups.

import { useEffect, useState } from 'preact/hooks'
import { SettingsFrame } from '../settings/Frame'
import { IconPlus, IconTrash } from '../../components/icons'
import { toast, toastError } from '../../lib/store'
import { moreAgentsApi } from './api'

type Row = { name: string; from: string }

export function MoreAgentsSettings({ title }: { title: string }) {
  const [idle, setIdle] = useState<number | null>(null)
  const [rows, setRows] = useState<Row[] | null>(null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)
  const load = async () => {
    const [s, g] = await Promise.all([moreAgentsApi.settings(), moreAgentsApi.groups()])
    const r = g.groups.map((n) => ({ name: n, from: n }))
    setIdle(s.idle_timeout_min); setRows(r); setOrig(JSON.stringify([s.idle_timeout_min, r]))
  }
  useEffect(() => { load().catch(toastError) }, [])
  const dirty = rows !== null && JSON.stringify([idle, rows]) !== orig
  const save = async () => {
    if (!rows || idle === null) return
    setSaving(true)
    try {
      const renames = Object.fromEntries(rows.filter((r) => r.from && r.from !== r.name.trim()).map((r) => [r.from, r.name.trim()]))
      await moreAgentsApi.setSettings({ idle_timeout_min: idle })
      await moreAgentsApi.setGroups(rows.map((r) => r.name.trim()).filter(Boolean), renames)
      await load(); toast('Settings saved')
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={save}>
      {rows === null || idle === null ? <div class="skeleton" style={{ height: '200px', borderRadius: '20px' }} /> : <>
        <div class="group-title">Connection</div>
        <div class="group">
          <label class="field"><span class="flabel">Close idle connections after (minutes)</span>
            <input class="input mono" type="number" min={0} value={idle} onInput={(e) => setIdle(Number((e.target as HTMLInputElement).value))} />
            <span class="fhint">0 keeps connections open. Sessions reconnect on the next message either way.</span>
          </label>
        </div>
        <div class="group-title">Groups</div>
        <div class="group">
          {rows.map((r, i) => (
            <div key={i} class="row">
              <input class="input" style={{ flex: 1 }} value={r.name} maxLength={40} placeholder="Group name"
                onInput={(e) => setRows(rows.map((x, k) => k === i ? { ...x, name: (e.target as HTMLInputElement).value } : x))} />
              <button class="icon-btn" aria-label={`Remove ${r.name}`} onClick={() => setRows(rows.filter((_, k) => k !== i))}><IconTrash width={18} height={18} /></button>
            </div>
          ))}
          <button class="row press" onClick={() => setRows([...rows, { name: '', from: '' }])}><span class="label"><IconPlus width={16} height={16} /> Add group</span></button>
        </div>
        <p class="fhint" style={{ padding: '0 4px' }}>Removing a group moves its agents to Ungrouped.</p>
      </>}
    </SettingsFrame>
  )
}
