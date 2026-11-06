// Create / edit page for recurring and one-off tasks. Backend errors are shown inline above the save button.

import { useEffect, useState } from 'preact/hooks'
import { BackButton, Segmented, Sheet, Switch, TopBar, useScrolled } from '../../components/ui'
import { IconClose, IconPlus, IconSearch } from '../../components/icons'
import { back, navigate } from '../../lib/router'
import { toast, toastError } from '../../lib/store'
import { autoApi, type Group, type ScheduleType, type Scripts, type Task, type TaskPayload } from './api'
import { describeCron } from './format'

type Kind = 'recurring' | 'one_off'
const val = (e: Event) => (e.target as HTMLInputElement).value
const CRON_PRESETS: [string, string][] = [['Every 5 min', '*/5 * * * *'], ['Daily 09:00', '0 9 * * *'], ['Weekdays 08:30', '30 8 * * 1-5'], ['Monthly', '0 9 1 * *']]
const SCHED_OPTIONS: { value: ScheduleType; label: string }[] = [
  { value: 'cron', label: 'Cron' }, { value: 'interval', label: 'Interval' }, { value: 'manual', label: 'Manual' }, { value: 'webhook', label: 'Webhook' },
]

const pad = (n: number) => String(n).padStart(2, '0')
const localInput = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`

function nameError(n: string): string {
  const s = n.trim()
  if (!s) return 'Name is required'
  if (s === '.' || s === '..' || /[\\/\0]/.test(s)) return 'Name cannot be . or .. or contain / or \\'
  return ''
}

export function TaskForm({ id }: { id?: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const editing = id !== undefined
  const [loaded, setLoaded] = useState(!editing)
  const [orig, setOrig] = useState<Task | null>(null)
  const [kind, setKind] = useState<Kind>('recurring')
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [scriptMode, setScriptMode] = useState<'existing' | 'new'>(editing ? 'existing' : 'new')
  const [script, setScript] = useState('')
  const [lang, setLang] = useState<'python' | 'shell'>('python')
  const [args, setArgs] = useState<string[]>([])
  const [sched, setSched] = useState<ScheduleType>('cron')
  const [cron, setCron] = useState('0 9 * * *')
  const [every, setEvery] = useState('30')
  const [unit, setUnit] = useState<'min' | 's'>('min')
  const [enabled, setEnabled] = useState(true)
  const [when, setWhen] = useState<'now' | 'at'>('now')
  const [at, setAt] = useState(() => { const d = new Date(Date.now() + 3600e3); d.setMinutes(0, 0, 0); return localInput(d) })
  const [groupId, setGroupId] = useState('')
  const [groups, setGroups] = useState<Group[]>([])
  const [scripts, setScripts] = useState<Scripts>({ recurring: [], one_off: [] })
  const [picker, setPicker] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    autoApi.scripts().then(setScripts).catch(() => {})
    if (!editing) autoApi.groups().then(setGroups).catch(() => {})
    else autoApi.task(id!).then((t) => {
      setOrig(t); setKind(t.task_kind); setName(t.name); setDesc(t.description); setScript(t.script); setArgs(t.args_list)
      setEnabled(!!t.enabled)
      if (t.task_kind === 'recurring') {
        setSched(t.schedule_type)
        if (t.schedule_type === 'cron') setCron(t.schedule_value || '')
        if (t.schedule_type === 'interval') {
          const s = Number(t.schedule_value) || 60
          if (s % 60 === 0) { setEvery(String(s / 60)); setUnit('min') } else { setEvery(String(s)); setUnit('s') }
        }
      } else if (t.one_off_trigger === 'scheduled' && t.scheduled_at) { setWhen('at'); setAt(localInput(new Date(t.scheduled_at * 1000))) }
      setLoaded(true)
    }).catch(toastError)
  }, [id])

  const oneOff = kind === 'one_off'
  const prefix = `${oneOff ? 'once' : 'cron'}/${name.trim()}/`
  // The backend only accepts scripts inside the task's own directory, so other tasks' scripts are not offered.
  const choices = (oneOff ? scripts.one_off : scripts.recurring).filter((s) => name.trim() && s.startsWith(prefix))
  const locked = editing && oneOff && orig?.one_off_state !== 'pending'
  const cronOk = cron.trim().split(/\s+/).length === 5
  const intervalSecs = Number(every) * (unit === 'min' ? 60 : 1)

  const submit = async () => {
    setError('')
    if (!editing) { const ne = nameError(name); if (ne) return setError(ne) }
    if (scriptMode === 'existing' && !script) return setError('Pick a script or create a new one')
    if (!oneOff && sched === 'cron' && !cronOk) return setError('Cron needs five fields: minute hour day month weekday')
    if (!oneOff && sched === 'interval' && !(intervalSecs > 0)) return setError('Interval must be greater than zero')
    if (oneOff && when === 'at' && !at) return setError('Pick a date and time')
    const cleanArgs = args.map((a) => a.trim()).filter(Boolean)
    const body: TaskPayload = { description: desc.trim(), args: cleanArgs }
    if (scriptMode === 'existing') body.script = script; else body.create_script = lang
    if (oneOff) {
      body.one_off_trigger = when === 'at' ? 'scheduled' : 'immediate'
      if (when === 'at') body.scheduled_at_local = at
    } else {
      body.schedule_type = sched
      body.schedule_value = sched === 'cron' ? cron.trim() : sched === 'interval' ? String(intervalSecs) : null
    }
    setSaving(true)
    try {
      if (editing) {
        if (script === orig?.script) delete body.script
        const t = await autoApi.edit(orig!.id, body)
        toast('Saved'); navigate({ name: 'automation-task', taskId: String(t.id) }, { replace: true })
      } else {
        const t = await autoApi.create({ ...body, name: name.trim(), task_kind: kind, ...(oneOff ? {} : { enabled }) })
        if (groupId) await autoApi.moveToGroup(Number(groupId), t.id).catch(toastError)
        navigate({ name: 'automation-task', taskId: String(t.id) }, { replace: true })
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setSaving(false) }
  }

  return (
    <div class="page wide-page">
      <TopBar scrolled={scrolled} left={<BackButton label="Back" onClick={() => back(editing ? { name: 'automation-task', taskId: id! } : { name: 'automations' })} />}
        right={<button class="btn primary small" disabled={!loaded || saving || locked} onClick={submit}>{saving ? <span class="spinner" /> : editing ? 'Save' : 'Create'}</button>}>
        <span class="topbar-center">{editing ? 'Edit task' : 'New task'}</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">
          {!loaded ? <div class="skeleton" style={{ height: '260px', borderRadius: '20px' }} /> : <>
            {locked && <p class="fhint err" style={{ padding: '0 4px' }}>Only pending one-off tasks can be edited.</p>}
            {!editing && <div class="kind-switch"><Segmented value={kind} onChange={(k) => { setKind(k); setScript('') }} options={[{ value: 'recurring', label: 'Recurring' }, { value: 'one_off', label: 'One-off' }]} /></div>}

            <div class="group">
              <label class="field"><span class="flabel">Name</span>
                <input class="input" value={name} disabled={editing} placeholder="daily-report" autocapitalize="off" spellcheck={false} onInput={(e) => { setName(val(e)); setScript('') }} />
                {editing && <span class="fhint">The name cannot be changed.</span>}
              </label>
              <label class="field"><span class="flabel">Description</span>
                <input class="input" value={desc} maxLength={1000} placeholder="What it does" onInput={(e) => setDesc(val(e))} />
              </label>
              {!editing && groups.length > 0 && (
                <label class="field"><span class="flabel">Group</span>
                  <select class="select" value={groupId} onChange={(e) => setGroupId(val(e))}>
                    <option value="">Ungrouped</option>
                    {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                </label>
              )}
            </div>

            <div class="group-title">Script</div>
            <div class="group">
              {!editing && (
                <div class="field"><Segmented value={scriptMode} onChange={setScriptMode}
                  options={[{ value: 'new', label: 'Create new' }, { value: 'existing', label: 'Existing' }]} /></div>
              )}
              {scriptMode === 'new' ? (
                <div class="field"><span class="flabel">Skeleton</span>
                  <Segmented value={lang} onChange={setLang} options={[{ value: 'python', label: 'Python' }, { value: 'shell', label: 'Shell' }]} />
                  <span class="fhint">Creates {name.trim() || '<name>'}.{lang === 'python' ? 'py' : 'sh'} in scripts/{oneOff ? 'once' : 'cron'}/{name.trim() || '<name>'}/ with your description in its header.</span>
                </div>
              ) : (
                <button class="row press" disabled={editing && !choices.length && !script} onClick={() => setPicker(true)}>
                  <span class="label">{script ? <span class="mono-label">{script}</span> : 'Choose a script'}
                    {!editing && !choices.length && <span class="hint">{name.trim() ? `No scripts in ${prefix} yet.` : 'Enter the name first.'}</span>}</span>
                  <span class="value">Change</span>
                </button>
              )}
            </div>

            <div class="group-title">Arguments</div>
            <div class="group">
              {args.map((a, i) => (
                <div key={i} class="row">
                  <input class="input mono" style={{ flex: 1 }} value={a} placeholder="argument" autocapitalize="off" spellcheck={false}
                    onInput={(e) => setArgs(args.map((x, k) => (k === i ? val(e) : x)))} />
                  <button class="icon-btn" aria-label="Remove argument" onClick={() => setArgs(args.filter((_, k) => k !== i))}><IconClose width={18} height={18} /></button>
                </div>
              ))}
              <button class="row press" onClick={() => setArgs([...args, ''])}><span class="label"><IconPlus width={16} height={16} /> Add argument</span></button>
            </div>

            {!oneOff ? <>
              <div class="group-title">Schedule</div>
              <div class="group">
                <div class="field"><Segmented value={sched} onChange={setSched} options={SCHED_OPTIONS} /></div>
                {sched === 'cron' && (
                  <div class="field"><span class="flabel">Cron expression</span>
                    <input class="input mono" value={cron} placeholder="0 9 * * *" autocapitalize="off" spellcheck={false} onInput={(e) => setCron(val(e))} />
                    <div class="auto-chips" style={{ marginTop: '8px' }}>
                      {CRON_PRESETS.map(([l, v]) => <button key={v} type="button" class={`chip ${cron.trim() === v ? 'pink' : ''}`} onClick={() => setCron(v)}>{l}</button>)}
                    </div>
                    <span class={`fhint ${cronOk ? '' : 'err'}`}>{cronOk ? describeCron(cron) : 'Five fields: minute hour day month weekday'}</span>
                  </div>
                )}
                {sched === 'interval' && (
                  <div class="field"><span class="flabel">Run every</span>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input class="input mono" style={{ flex: 1 }} type="number" min={1} value={every} onInput={(e) => setEvery(val(e))} />
                      <Segmented value={unit} onChange={setUnit} options={[{ value: 'min', label: 'Minutes' }, { value: 's', label: 'Seconds' }]} />
                    </div>
                  </div>
                )}
                {sched === 'manual' && <div class="row"><span class="label hint">Runs only when you start it.</span></div>}
                {sched === 'webhook' && <div class="row"><span class="label hint">Runs when the task webhook is called. The URL appears on the task page.</span></div>}
                {!editing && <div class="row"><span class="label">Enabled</span><Switch on={enabled} onChange={setEnabled} label="Enabled" /></div>}
              </div>
            </> : <>
              <div class="group-title">When</div>
              <div class="group">
                <div class="field"><Segmented value={when} onChange={setWhen} options={[{ value: 'now', label: 'Run now' }, { value: 'at', label: 'At time' }]} /></div>
                {when === 'at' && (
                  <label class="field"><span class="flabel">Date and time</span>
                    <input class="input" type="datetime-local" value={at} min={localInput(new Date())} onInput={(e) => setAt(val(e))} />
                    <span class="fhint">Server time zone is used if it differs from this device. Must be in the future.</span>
                  </label>
                )}
              </div>
            </>}

            {error && <p class="fhint err auto-error" role="alert">{error}</p>}
          </>}
        </div>
      </div>
      <ScriptPicker open={picker} items={choices} current={script} onClose={() => setPicker(false)} onPick={(s) => { setScript(s); setPicker(false) }} />
    </div>
  )
}

function ScriptPicker({ open, items, current, onClose, onPick }: { open: boolean; items: string[]; current: string; onClose: () => void; onPick: (s: string) => void }) {
  const [q, setQ] = useState('')
  const list = items.filter((s) => s.toLowerCase().includes(q.toLowerCase()))
  return (
    <Sheet open={open} onClose={onClose} title="Scripts">
      {items.length > 6 && (
        <div class="wf-search" style={{ marginBottom: '10px' }}>
          <IconSearch width={18} height={18} />
          <input class="input" placeholder="Search" value={q} onInput={(e) => setQ(val(e))} />
        </div>
      )}
      <div class="group">
        {list.map((s) => (
          <button key={s} class="row press" onClick={() => onPick(s)}>
            <span class="label mono-label">{s}</span>{s === current && <span class="menu-check">Current</span>}
          </button>
        ))}
        {list.length === 0 && <div class="row"><span class="label hint">No scripts found.</span></div>}
      </div>
    </Sheet>
  )
}
