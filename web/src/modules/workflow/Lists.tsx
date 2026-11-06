// Workflow tab: Console (what runs right now) and the run history page (finished runs, opened from the history button).

import { useEffect, useState } from 'preact/hooks'
import { BackButton, TopBar, confirmDialog, useScrolled } from '../../components/ui'
import { Spark } from '../../components/crab'
import { IconChevron, IconTrash } from '../../components/icons'
import { back, navigate } from '../../lib/router'
import { toastError, workflowVersion } from '../../lib/store'
import { fmtSecs, fmtTime, wfApi, workflows, type ConsoleSession, type Run } from './api'
import { WfIcon } from './icons'
import { TabPage } from './TabPage'
import { StatusBadge } from './ui'

function RunRow({ r, now, onDelete }: { r: Run; now?: number; onDelete?: () => void }) {
  const waiting = r.status === 'waiting_input'
  const dur = r.finished_at && r.started_at ? r.finished_at - r.started_at : now && r.started_at ? now - r.started_at : null
  return (
    <button class={`row press ${waiting ? 'wf-needs' : ''}`} onClick={() => navigate({ name: 'wf-run', runId: r.id })}>
      <span class="wf-block-icon"><WfIcon name={waiting ? 'bell' : 'workflow'} size={18} /></span>
      <span class="label">{r.workflow_name || '(deleted workflow)'}
        <span class="hint">{waiting ? 'Tap to respond' : fmtTime(r.started_at || r.created_at)}{dur != null ? ` · ${fmtSecs(dur)}` : ''}{r.cost_usd ? ` · $${r.cost_usd.toFixed(3)}` : ''}{r.trigger === 'api' ? ' · API' : ''}</span>
      </span>
      <StatusBadge status={r.status} />
      {onDelete && <span class="icon-btn" role="button" aria-label="Delete" onClick={(e) => { e.stopPropagation(); onDelete() }}><IconTrash width={18} height={18} /></span>}
    </button>
  )
}

function SessionRow({ s }: { s: ConsoleSession }) {
  const running = s.state === 'running' || s.state === 'interrupting'
  const open = () => navigate(s.module === 'acp' ? { name: 'acp-chat', agentId: s.agent_id, sessionId: s.session_id } : { name: 'chat', agentId: s.agent_id, sessionId: s.session_id })
  return (
    <button class="row press" onClick={open}>
      <span class="wf-block-icon">{running ? <Spark size={16} /> : <WfIcon name={s.module === 'acp' ? 'plug' : 'agent'} size={18} />}</span>
      <span class="label">{s.title || s.agent_id}<span class="hint">{s.agent_id === '_temp' ? 'Temporary chat' : s.agent_id} · {s.state}</span></span>
      <IconChevron class="chev" />
    </button>
  )
}

export function WorkflowConsole() {
  const [data, setData] = useState<{ runs: Run[]; sessions: ConsoleSession[] } | null>(null)
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => { wfApi.console().then(setData).catch(toastError) }, [workflowVersion.value])
  useEffect(() => {
    // the feed covers run states; this only refreshes durations and session states
    const t = setInterval(() => { setNow(Date.now() / 1000); if (!document.hidden) wfApi.console().then(setData).catch(() => {}) }, 5000)
    return () => clearInterval(t)
  }, [])
  const runs = data?.runs || []
  const sessions = data?.sessions || []
  const waiting = runs.filter((r) => r.status === 'waiting_input').length
  return (
    <TabPage section="console" subtitle="Everything running right now.">
      {!data && <div class="skeleton" style={{ height: '120px', borderRadius: '20px' }} />}
      {data && waiting > 0 && <div class="wf-warn">{waiting} run{waiting > 1 ? 's need' : ' needs'} your input</div>}
      {data && <>
        <div class="group-title">Runs</div>
        {runs.length ? <div class="group">{runs.map((r) => <RunRow key={r.id} r={r} now={now} />)}</div>
          : <p class="fhint" style={{ margin: '0 4px' }}>Nothing running. Finished runs are in the history (top right).</p>}
        <div class="group-title">Agent sessions</div>
        {sessions.length ? <div class="group">{sessions.map((s) => <SessionRow key={s.session_id} s={s} />)}</div>
          : <p class="fhint" style={{ margin: '0 4px' }}>No agent cards running.</p>}
      </>}
    </TabPage>
  )
}

export function WorkflowRuns({ workflowId }: { workflowId?: string }) {
  const [rows, setRows] = useState<Run[] | null>(null)
  const load = () => wfApi.runs({ workflow_id: workflowId, finished: true }).then(setRows).catch(toastError)
  useEffect(() => { load() }, [workflowId, workflowVersion.value])
  const remove = async (r: Run) => {
    if (!await confirmDialog({ title: 'Delete this run?', confirm: 'Delete', danger: true })) return
    try { await wfApi.deleteRun(r.id); load() } catch (e) { toastError(e) }
  }
  const wf = workflowId ? workflows.value.find((w) => w.id === workflowId) : null
  const { scrolled, onScroll, ref } = useScrolled()
  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label="Workflow" onClick={() => back({ name: 'workflows' })} />}>
        <span class="topbar-center">Run history</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <p class="subtitle rise" style={{ marginTop: '14px' }}>{workflowId ? <>Runs of {wf?.name || 'one workflow'}. <button class="link-btn" onClick={() => navigate({ name: 'wf-runs' }, { replace: true })}>Show all</button></> : 'Finished runs, newest first.'}</p>
          {rows === null && <div class="skeleton" style={{ height: '160px', borderRadius: '20px' }} />}
          {rows && rows.length === 0 && <div class="empty"><h3>No runs yet</h3></div>}
          {rows && rows.length > 0 && <div class="group">{rows.map((r) => <RunRow key={r.id} r={r} onDelete={() => remove(r)} />)}</div>}
        </div>
      </div>
    </div>
  )
}
