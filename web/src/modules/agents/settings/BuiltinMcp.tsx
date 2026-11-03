// Settings > Agents > Built-in tools: global switches for the in-process MCP server and the schedule list. Mirrors docs/builtin-mcp.md.

import { useEffect, useState } from 'preact/hooks'
import { SettingsFrame, useConfigForm } from '../../settings/Frame'
import { Segmented, Sheet, Switch, confirmDialog } from '../../../components/ui'
import { IconPlus, IconTrash } from '../../../components/icons'
import { schedulesVersion, toast, toastError } from '../../../lib/store'
import { builtinApi, type Schedule, type ScheduleInput } from '../builtinApi'

const CATS = [
  { key: 'schedules', label: 'Schedules', hint: 'Let agents create timed or recurring tasks.' },
  { key: 'history', label: 'History', hint: 'Let an agent search and read its own past conversations.' },
  { key: 'collab', label: 'Collaboration', hint: 'Let an agent hand work to other agents as subagents.' },
] as const

const BLANK: ScheduleInput = { title: '', prompt: '', cron: '0 9 * * *', at: null, target: { module: 'agents', agent_id: '_temp', session: 'new' }, model: '', effort: '', enabled: true }
const val = (e: Event) => (e.target as HTMLInputElement).value
const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString() : 'never')

export function BuiltinMcpSettings({ title }: { title: string }) {
  const { form, setForm, dirty, saving, save } = useConfigForm()
  const [list, setList] = useState<Schedule[] | null>(null)
  const [edit, setEdit] = useState<{ id?: string; s: ScheduleInput } | null>(null)
  useEffect(() => { builtinApi.schedules().then(setList).catch(toastError) }, [schedulesVersion.value])
  const b = form?.builtin_mcp
  const set = (k: string, v: boolean) => setForm((f) => f && { ...f, builtin_mcp: { ...f.builtin_mcp, [k]: v } })
  const toggle = async (s: Schedule, on: boolean) => { try { await builtinApi.updateSchedule(s.id, { enabled: on }) } catch (e) { toastError(e) } }
  return (
    <SettingsFrame title={title} dirty={dirty} saving={saving} onSave={() => form && save({ builtin_mcp: form.builtin_mcp })}>
      {!b ? <div class="skeleton" style={{ height: '200px', borderRadius: '20px' }} /> : <>
        <span class="fhint" style={{ display: 'block', padding: '0 4px' }}>Tools Claude agents can call. ACP agents never get them. Each agent can override these in its own settings.</span>
        <div class="group">
          <div class="row"><span class="label">Enable built-in tools<span class="hint">Master switch.</span></span><Switch on={b.enabled} onChange={(v) => set('enabled', v)} label="Enable built-in tools" /></div>
          {CATS.map((c) => (
            <div key={c.key} class="row"><span class="label">{c.label}<span class="hint">{c.hint}</span></span>
              <Switch on={b[c.key]} disabled={!b.enabled} onChange={(v) => set(c.key, v)} label={c.label} /></div>
          ))}
        </div>
      </>}
      <div class="group-title">Schedules</div>
      <div class="group">
        {(list || []).map((s) => (
          <div key={s.id} class="row">
            <button type="button" class="label" style={{ textAlign: 'left', background: 'none', flex: 1 }} onClick={() => setEdit({ id: s.id, s: { ...s } })}>
              {s.title || s.prompt.slice(0, 40)}
              <span class="hint">{s.cron || s.at} · next {when(s.next_run)}{s.last_result?.error ? ` · ${s.last_result.error}` : ''}</span>
            </button>
            <Switch on={s.enabled} onChange={(v) => toggle(s, v)} label={`${s.title || s.id} enabled`} />
          </div>
        ))}
        <button class="row press" onClick={() => setEdit({ s: { ...BLANK } })}><span class="label"><IconPlus width={16} height={16} /> Add schedule</span></button>
      </div>
      <ScheduleSheet v={edit} onChange={(s) => setEdit(edit && { ...edit, s })} onClose={() => setEdit(null)} />
    </SettingsFrame>
  )
}

function ScheduleSheet({ v, onChange, onClose }: { v: { id?: string; s: ScheduleInput } | null; onChange: (s: ScheduleInput) => void; onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  if (!v) return <Sheet open={false} onClose={onClose} title="">{null}</Sheet>
  const s = v.s
  const set = <K extends keyof ScheduleInput>(k: K, x: ScheduleInput[K]) => onChange({ ...s, [k]: x })
  const kind = s.at !== null && s.cron === null ? 'at' : 'cron'
  const run = async (fn: () => Promise<unknown>, msg: string) => { setBusy(true); try { await fn(); toast(msg); onClose() } catch (e) { toastError(e) } finally { setBusy(false) } }
  const body = (): ScheduleInput => ({ ...s, cron: kind === 'cron' ? s.cron : null, at: kind === 'at' ? s.at : null })
  const remove = async () => {
    if (!await confirmDialog({ title: 'Delete schedule?', body: s.title || s.prompt.slice(0, 40), confirm: 'Delete', danger: true })) return
    run(() => builtinApi.deleteSchedule(v.id!), 'Schedule deleted')
  }
  return (
    <Sheet open onClose={onClose} title={v.id ? 'Schedule' : 'New schedule'}>
      <div class="group">
        <label class="field"><span class="flabel">Title</span><input class="input" value={s.title} onInput={(e) => set('title', val(e))} /></label>
        <label class="field"><span class="flabel">Prompt</span><textarea class="input" rows={4} value={s.prompt} onInput={(e) => set('prompt', (e.target as HTMLTextAreaElement).value)} /></label>
        <div class="field"><span class="flabel">When</span>
          <Segmented value={kind} onChange={(k) => onChange(k === 'cron' ? { ...s, cron: '0 9 * * *', at: null } : { ...s, cron: null, at: '' })} options={[{ value: 'cron', label: 'Repeat' }, { value: 'at', label: 'Once' }]} />
        </div>
        {kind === 'cron'
          ? <label class="field"><span class="flabel">Cron</span><input class="input mono" value={s.cron || ''} autocapitalize="off" spellcheck={false} onInput={(e) => set('cron', val(e))} /><span class="fhint">Five fields, server local time.</span></label>
          : <label class="field"><span class="flabel">Date and time</span><input class="input mono" type="datetime-local" value={s.at || ''} onInput={(e) => set('at', val(e))} /></label>}
      </div>
      <div class="group-title">Target</div>
      <div class="group">
        <div class="field"><span class="flabel">Agent type</span>
          <Segmented value={s.target.module} onChange={(m) => set('target', { module: m, agent_id: m === 'agents' ? '_temp' : '', session: 'new' })} options={[{ value: 'agents', label: 'Claude' }, { value: 'acp', label: 'ACP' }]} />
        </div>
        <label class="field"><span class="flabel">Agent ID</span><input class="input mono" value={s.target.agent_id} autocapitalize="off" spellcheck={false} onInput={(e) => set('target', { ...s.target, agent_id: val(e).trim() })} /><span class="fhint">_temp is the temporary chat agent.</span></label>
        <label class="field"><span class="flabel">Session</span><input class="input mono" value={s.target.session} autocapitalize="off" spellcheck={false} onInput={(e) => set('target', { ...s.target, session: val(e).trim() || 'new' })} /><span class="fhint">new starts a fresh session each run, or enter a session ID.</span></label>
        <div class="field-row">
          <label class="field" style={{ flex: 1 }}><span class="flabel">Model</span><input class="input mono" value={s.model} placeholder="default" autocapitalize="off" spellcheck={false} onInput={(e) => set('model', val(e).trim())} /></label>
          <label class="field" style={{ flex: 1 }}><span class="flabel">Effort</span><input class="input mono" value={s.effort} placeholder="default" autocapitalize="off" spellcheck={false} onInput={(e) => set('effort', val(e).trim())} /></label>
        </div>
      </div>
      <button class="btn primary block" style={{ marginTop: '18px' }} disabled={busy || !s.prompt.trim()}
        onClick={() => run(() => v.id ? builtinApi.updateSchedule(v.id, body()) : builtinApi.createSchedule(body()), 'Schedule saved')}>Save</button>
      {v.id && <>
        <button class="btn block" style={{ marginTop: '10px' }} disabled={busy} onClick={() => run(() => builtinApi.runSchedule(v.id!), 'Started')}>Run now</button>
        <button class="btn danger block" style={{ marginTop: '10px' }} disabled={busy} onClick={remove}><IconTrash width={18} height={18} /> Delete schedule</button>
      </>}
    </Sheet>
  )
}
