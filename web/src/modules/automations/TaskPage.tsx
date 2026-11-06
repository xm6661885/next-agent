// Task page: header with enable switch, run actions, info, webhook details and paged run history.

import { useEffect, useRef, useState } from 'preact/hooks'
import { BackButton, SecretInput, Sheet, Switch, TopBar, useScrolled } from '../../components/ui'
import { IconMore } from '../../components/icons'
import { back, navigate } from '../../lib/router'
import { automationsVersion, toastError } from '../../lib/store'
import { ApiError } from '../../lib/api'
import { autoApi, webhookUrl, type AutoSettings, type Group, type Run, type Task } from './api'
import { TRIGGER_LABEL, describeSchedule, fmtDateTime, fmtSpan, relWhen, runOutcome, splitArgs, taskOutcome } from './format'
import { GroupPicker, MenuSheet, OutcomeBadge, attempt, copy, deleteTask } from './ui'

const PAGE = 20

export function TaskPage({ id }: { id: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const [t, setT] = useState<Task | null>(null)
  const [missing, setMissing] = useState(false)
  const [runs, setRuns] = useState<Run[]>([])
  const [more, setMore] = useState(false)
  const [groups, setGroups] = useState<Group[]>([])
  const [settings, setSettings] = useState<AutoSettings | null>(null)
  const [menu, setMenu] = useState(false)
  const [moving, setMoving] = useState(false)
  const [argsOpen, setArgsOpen] = useState(false)
  const timer = useRef<number>()

  useEffect(() => {
    clearTimeout(timer.current)
    timer.current = window.setTimeout(async () => {
      try {
        const task = await autoApi.task(id)
        setT(task)
        const first = await autoApi.taskRuns(task.id, 0, PAGE)
        setRuns(first); setMore(first.length === PAGE)
        autoApi.groups().then(setGroups).catch(() => {})
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) setMissing(true); else toastError(e)
      }
    }, t ? 300 : 0)
    return () => clearTimeout(timer.current)
  }, [id, automationsVersion.value])

  useEffect(() => { if (t?.schedule_type === 'webhook' && !settings) autoApi.settings().then(setSettings).catch(() => {}) }, [t?.schedule_type])

  const loadMore = async () => {
    if (!t) return
    try {
      const next = await autoApi.taskRuns(t.id, runs.length, PAGE)
      setRuns((old) => [...old, ...next]); setMore(next.length === PAGE)
    } catch (e) { toastError(e) }
  }

  if (missing) return <div class="page"><TopBar left={<BackButton label="Automations" onClick={() => back({ name: 'automations' })} />} /><div class="page-scroll"><div class="container"><div class="empty"><h3>Task not found</h3></div></div></div></div>

  const oneOff = t?.task_kind === 'one_off'
  const o = t ? taskOutcome(t) : null
  const openRun = (r: number | null | undefined) => { if (r) navigate({ name: 'automation-run', runId: String(r) }) }
  const doRun = async (opts: { force?: boolean; extra_args?: string[] } = {}) => {
    if (!t) return
    try {
      const r = oneOff ? await (t.one_off_state === 'pending' ? autoApi.start(t.id) : autoApi.runAgain(t.id)) : await autoApi.run(t.id, opts)
      navigate({ name: 'automation-run', runId: String(r.run_id) })
    } catch (e) { toastError(e) }
  }

  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label="Automations" onClick={() => back({ name: 'automations' })} />}
        right={t && <div class="topbar-actions"><button class="icon-btn" aria-label="Task menu" onClick={() => setMenu(true)}><IconMore /></button></div>}>
        {scrolled && t && <span class="fade-in">{t.name}</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          {!t ? <div class="skeleton" style={{ height: '160px', borderRadius: '20px' }} /> : <>
            <div class="auto-head rise">
              <div style={{ flex: 1, minWidth: 0 }}>
                <h1 class="large-title auto-title">{t.name}</h1>
                <div class="auto-meta">
                  {o && <OutcomeBadge o={o} />}
                  <span>{t.group_name || 'Ungrouped'}</span>
                  <span class="auto-sep">{oneOff ? 'One-off' : 'Recurring'}</span>
                </div>
              </div>
              {!oneOff && <Switch on={!!t.enabled} onChange={(v) => attempt(() => autoApi.setEnabled(t.id, v))} label="Enabled" />}
            </div>

            <div class="auto-actions rise" style={{ '--i': 1 }}>
              {t.running || t.one_off_state === 'running'
                ? <button class="btn primary" onClick={() => attempt(() => autoApi.stop(t.id), 'Stop signal sent')}>Stop</button>
                : oneOff
                  ? t.one_off_state === 'pending'
                    ? <><button class="btn primary" onClick={() => doRun()}>Start now</button><button class="btn" onClick={() => attempt(() => autoApi.cancel(t.id), 'Cancelled')}>Cancel</button></>
                    : <button class="btn primary" onClick={() => doRun()}>Run again</button>
                  : <button class="btn primary" onClick={() => doRun()}>Run now</button>}
              {!oneOff && <button class="btn" onClick={() => setArgsOpen(true)}>Run with options</button>}
            </div>

            <div class="group-title">Details</div>
            <div class="group">
              <div class="row"><span class="label">Script<span class="hint mono-label">{t.script}</span></span></div>
              {t.args_list.length > 0 && (
                <div class="row"><span class="label">Arguments<span class="hint auto-chips">{t.args_list.map((a, i) => <span key={i} class="chip">{a}</span>)}</span></span></div>
              )}
              <div class="row"><span class="label">Schedule<span class="hint">{describeSchedule(t)}{t.schedule_type === 'cron' && t.schedule_value ? ` (${t.schedule_value})` : ''}</span></span></div>
              {!oneOff && t.enabled && t.next_run_at && <div class="row"><span class="label">Next run<span class="hint">{fmtDateTime(t.next_run_at)} · {relWhen(t.next_run_at)}</span></span></div>}
              {oneOff && t.one_off_state && <div class="row"><span class="label">State<span class="hint">{t.one_off_state}</span></span></div>}
              {t.description && <div class="row"><span class="label">Description<span class="hint">{t.description}</span></span></div>}
            </div>

            {t.schedule_type === 'webhook' && <Webhook t={t} s={settings} />}

            <div class="group-title">Run history</div>
            {runs.length === 0 ? <p class="fhint" style={{ margin: '0 4px' }}>No runs yet.</p> : (
              <div class="group">
                {runs.map((r) => <RunRow key={r.id} r={r} onClick={() => openRun(r.id)} />)}
              </div>
            )}
            {more && <button class="btn block ghost" style={{ marginTop: '12px' }} onClick={loadMore}>Load more</button>}
          </>}
        </div>
      </div>

      <MenuSheet open={menu} title={t?.name} onClose={() => setMenu(false)} items={t ? [
        { label: 'Edit', onClick: () => navigate({ name: 'automation-edit', taskId: String(t.id) }) },
        { label: 'Move to group', onClick: () => setMoving(true) },
        { label: 'Delete', danger: true, onClick: async () => { if (await deleteTask(t)) back({ name: 'automations' }) } },
      ] : []} />
      <GroupPicker open={moving} task={t} groups={groups} onClose={() => setMoving(false)} />
      <RunOptions open={argsOpen} running={!!t?.running} onClose={() => setArgsOpen(false)} onRun={doRun} />
    </div>
  )
}

export function RunRow({ r, onClick, name }: { r: Run; onClick: () => void; name?: string }) {
  return (
    <button class="row press auto-run" onClick={onClick}>
      <span class="label">
        {name ? <>{name} <span class="auto-id">#{r.id}</span></> : <>#{r.id}</>}
        <span class="hint">{TRIGGER_LABEL[r.trigger] || r.trigger} · {fmtDateTime(r.started_at)}{r.finished_at ? ` · ${fmtSpan(r.started_at, r.finished_at)}` : ''}</span>
      </span>
      <OutcomeBadge o={runOutcome(r)} />
    </button>
  )
}

function RunOptions({ open, running, onClose, onRun }: { open: boolean; running: boolean; onClose: () => void; onRun: (o: { force?: boolean; extra_args?: string[] }) => void }) {
  const [line, setLine] = useState('')
  const [force, setForce] = useState(false)
  return (
    <Sheet open={open} onClose={onClose} title="Run with options">
      <div class="group">
        <label class="field"><span class="flabel">Extra arguments</span>
          <input class="input mono" value={line} placeholder='--dry-run "two words"' autocapitalize="off" spellcheck={false} onInput={(e) => setLine((e.target as HTMLInputElement).value)} />
          <span class="fhint">Appended after the saved arguments for this run only.</span>
        </label>
        <div class="row"><span class="label">Force<span class="hint">{running ? 'The task is running. Force starts a second copy.' : 'Start even if a copy is already running.'}</span></span>
          <Switch on={force} onChange={setForce} label="Force" /></div>
      </div>
      <button class="btn primary block" style={{ marginTop: '14px' }} onClick={() => { onClose(); onRun({ force, extra_args: splitArgs(line) }) }}>Run</button>
    </Sheet>
  )
}

function Webhook({ t, s }: { t: Task; s: AutoSettings | null }) {
  const url = webhookUrl(t.name)
  const secret = s?.webhook_secret || ''
  const withSecret = `${url}?secret=${encodeURIComponent(secret)}`
  const curl = `curl -X POST -H 'X-AutoTask-Webhook-Secret: ${secret}' -H 'Content-Type: application/json' -d '{}' '${url}'`
  return (
    <>
      <div class="group-title">Webhook</div>
      <div class="group">
        <div class="field"><span class="flabel">URL</span><div class="auto-url mono-label" style={{ whiteSpace: 'normal', wordBreak: 'break-all' }}>{url}</div></div>
        <div class="field"><span class="flabel">Secret</span><SecretInput value={secret} onInput={() => {}} label="webhook secret" placeholder={s ? 'Not set' : 'Loading'} /></div>
        <div class="auto-copy-row">
          <button class="btn small" onClick={() => copy(url)}>Copy URL</button>
          <button class="btn small" disabled={!secret} onClick={() => copy(withSecret)}>Copy URL with secret</button>
          <button class="btn small" disabled={!secret} onClick={() => copy(curl)}>Copy curl</button>
        </div>
      </div>
      <p class="fhint" style={{ padding: '0 4px' }}>The secret is shared by all webhook tasks. Change it in Settings &gt; Automations.</p>
    </>
  )
}
