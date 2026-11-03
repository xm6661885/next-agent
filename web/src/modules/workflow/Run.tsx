// One workflow run: live card states over SSE, agent session links, console, input requests, cancel and rerun.

import { useEffect, useMemo, useReducer, useRef, useState } from 'preact/hooks'
import { BackButton, Segmented, TopBar, confirmDialog } from '../../components/ui'
import { Spark } from '../../components/crab'
import { IconChevron, IconCopy } from '../../components/icons'
import { back, navigate } from '../../lib/router'
import { agents, liveSessions, moduleSessions, toastError } from '../../lib/store'
import { catalog, fmtSecs, loadCatalog, schemaMap, subscribeRun, wfApi, type Block, type Json, type PluginSchema, type Run as RunInfo } from './api'
import { LOOP_TYPES, branchesOf, buildTree, previewText } from './defs'
import { WfIcon } from './icons'
import { InputField } from './inputs'
import { initialRun, reduceRun, type AgentLink, type RunState } from './runState'
import { StatusBadge, copy } from './ui'

const fmtVal = (v: Json) => (v == null ? '' : typeof v === 'string' ? v : JSON.stringify(v, null, 2))

function OutBox({ text, result }: { text: string; result?: boolean }) {
  return (
    <div class="wf-out-wrap">
      <div class={result ? 'wf-result' : 'wf-out'}>{text}</div>
      <button class="icon-btn wf-copy" aria-label="Copy" onClick={(e) => { e.stopPropagation(); copy(text) }}><IconCopy width={16} height={16} /></button>
    </div>
  )
}

/** A Claude or ACP session started by an agent card; opens the normal chat page. */
function SessionLink({ s }: { s: AgentLink }) {
  const live = s.module === 'acp' ? moduleSessions.value[s.session_id] : liveSessions.value[s.session_id]
  const name = s.module === 'agents' ? (s.agent_id === '_temp' ? 'Temporary chat' : agents.value?.find((a) => a.id === s.agent_id)?.name || s.agent_id) : s.agent_id
  const running = live?.state === 'running' || live?.state === 'interrupting'
  const open = (e: Event) => {
    e.stopPropagation()
    navigate(s.module === 'acp' ? { name: 'acp-chat', agentId: s.agent_id, sessionId: s.session_id } : { name: 'chat', agentId: s.agent_id, sessionId: s.session_id })
  }
  return (
    <button class="row press wf-session" onClick={open}>
      <span class="wf-block-icon">{running ? <Spark size={16} /> : <WfIcon name={s.module === 'acp' ? 'plug' : 'agent'} size={18} />}</span>
      <span class="label">{name}<span class="hint">{s.module === 'acp' ? 'ACP session' : 'Claude session'}{live?.title ? ` · ${live.title}` : ''}{running ? ' · running' : live?.pending ? ' · needs you' : ''}</span></span>
      <IconChevron class="chev" />
    </button>
  )
}

function WaitingInput({ runId, waiting }: { runId: string; waiting: Json }) {
  const [vals, setVals] = useState<Record<string, Json>>(() => Object.fromEntries((waiting.fields || []).map((f: Json) => [f.name, f.default ?? ''])))
  const [busy, setBusy] = useState(false)
  const act = async (ok: boolean, values: Json = {}) => {
    setBusy(true)
    try { await (ok ? wfApi.input(runId, values) : wfApi.cancel(runId)) } catch (e) { toastError(e); setBusy(false) }
  }
  if (waiting.alert) {
    const a = waiting.alert
    return (
      <div class="card wf-ask" role="alertdialog" aria-label={a.title}>
        {a.title && <div class="wf-ask-title">{a.title}</div>}
        {a.message && <div class="wf-ask-msg">{a.message}</div>}
        <div style={{ display: 'flex', gap: '10px' }}>
          {a.show_cancel && <button class="btn block" disabled={busy} onClick={() => act(false)}>Cancel</button>}
          <button class="btn block primary" disabled={busy} onClick={() => act(true)}>{a.ok_text || 'OK'}</button>
        </div>
      </div>
    )
  }
  return (
    <div class="card wf-ask">
      <div class="wf-ask-title">{waiting.prompt || 'Input needed'}</div>
      <div class="group" style={{ marginBottom: '12px' }}>
        {(waiting.fields || []).map((f: Json) => <InputField key={f.name} spec={f} value={vals[f.name]} onChange={(v) => setVals({ ...vals, [f.name]: v })} />)}
      </div>
      <button class="btn block primary" disabled={busy} onClick={() => act(true, vals)}>Continue</button>
    </div>
  )
}

function StepIcon({ status }: { status: string }) {
  if (status === 'running') return <Spark size={16} />
  if (status === 'success') return <span class="wf-ok"><WfIcon name="check" size={18} /></span>
  if (status === 'failed') return <span class="wf-err"><WfIcon name="x" size={18} /></span>
  if (status === 'queued' || status === 'skipped' || status === 'cancelled') return <span class="wf-tag">{status === 'queued' ? 'Queued' : status === 'skipped' ? 'Skipped' : 'Cancelled'}</span>
  return null
}

function StepView({ block, state, schemas, snapshot, depth, runDone, runId, onRerun }: {
  block: Block; state: RunState; schemas: Record<string, PluginSchema>; snapshot: Json; depth: number; runDone: boolean; runId: string; onRerun?: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const schema = schemas[block.type]
  const st = state.steps[block.id]
  const status = st?.status || (runDone ? 'idle' : 'pending')
  const isOpen = open || status === 'failed' || (status === 'running' && !!st?.sessions.length)
  const hasDetail = !!st && !!(st.fields || st.error || st.logs.length || st.sessions.length || st.stream)
  const dim = status === 'idle' || status === 'pending' || status === 'skipped'
  const first = schema?.inputs?.[0]?.name
  const sub = st?.iter ? `Round ${st.iter}${block.note ? ` · ${block.note}` : ''}` : block.note
    || (block.type !== 'core.if' && !LOOP_TYPES.includes(block.type) && first ? previewText(block.params?.[first], snapshot || { blocks: [] }, schemas).slice(0, 60) : '')
  return (
    <div class="wf-step" style={depth ? { marginLeft: '14px' } : undefined}>
      <div class={`card wf-block c-${schema?.color || 'gray'} ${status === 'running' ? 'live' : ''}`} style={dim ? { opacity: 0.6 } : undefined}>
        <div class="wf-block-head" onClick={() => setOpen(!open)}>
          <span class="wf-block-icon"><WfIcon name={schema?.icon || 'puzzle'} /></span>
          <div class="wf-block-title">{schema?.name || block.type}{sub && <span class={`sub ${block.note && !st?.iter ? 'note' : ''}`}>{sub}</span>}</div>
          <StepIcon status={status} />
          {st?.cached && <span class="wf-tag">Reused</span>}
          {onRerun && <button class="icon-btn" title="Rerun from here" aria-label="Rerun from here" onClick={(e) => { e.stopPropagation(); onRerun(block.id) }}><WfIcon name="refresh" size={18} /></button>}
        </div>
        {isOpen && hasDetail && (
          <div class="wf-block-body wf-step-detail">
            {st.error && <div class="wf-warn">{st.error}</div>}
            {st.sessions.length > 0 && <div class="group">{st.sessions.map((s) => <SessionLink key={s.session_id} s={s} />)}</div>}
            {st.logs.length > 0 && <div class="wf-logs">{st.logs.map((l, i) => <div key={i}>{l}</div>)}</div>}
            {!st.fields && st.stream && <OutBox text={st.stream} />}
            {st.fields && Object.entries(st.fields).map(([k, v]) => {
              if (v == null || v === '') return null
              const label = schema?.outputs?.find((o) => o.name === k)?.label || k
              return <div key={k}><div class="wf-kv">{label}{k === st.default ? ' (default)' : ''}</div><OutBox text={fmtVal(v)} /></div>
            })}
            {st.duration != null && <div class="fhint">Duration {fmtSecs(st.duration)}</div>}
          </div>
        )}
        {branchesOf(block).length > 0 && (
          <div class="wf-block-body" style={{ paddingTop: 0 }}>
            {(schema?.branches || []).map((br) => ((block as any)[br.key] || []).length > 0 && (
              <div key={br.key} class="wf-branch">
                <div class="wf-branch-label">{br.label}</div>
                {((block as any)[br.key] as Block[]).map((b) => <StepView key={b.id} block={b} state={state} schemas={schemas} snapshot={snapshot} depth={depth + 1} runDone={runDone} runId={runId} />)}
              </div>
            ))}
          </div>
        )}
        {state.waiting?.block === block.id && <div class="wf-block-body"><WaitingInput runId={runId} waiting={state.waiting} /></div>}
      </div>
    </div>
  )
}

function ConsoleView({ state, names }: { state: RunState; names: Record<string, string> }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { const el = ref.current; if (el) el.scrollTop = el.scrollHeight }, [state.console.length])
  return (
    <div class="wf-console" ref={ref}>
      {state.console.length === 0 && <span class="dim">Waiting for output</span>}
      {state.console.map((l, i) => l.kind === 'step'
        ? <div key={i} class="dim">› {(l.block && names[l.block]) || l.text}</div>
        : <div key={i} class={l.kind === 'log' || l.kind === 'text' ? '' : l.kind}>{l.text}</div>)}
    </div>
  )
}

function allBlocks(blocks: Block[], out: Record<string, Block> = {}) {
  blocks.forEach((b) => { out[b.id] = b; branchesOf(b).forEach((k) => allBlocks(b[k] || [], out)) })
  return out
}

export function RunPage({ id }: { id: string }) {
  const [run, setRun] = useState<RunInfo | null>(null)
  const [state, dispatch] = useReducer(reduceRun, initialRun)
  const [tab, setTab] = useState<'cards' | 'console'>('cards')
  const [now, setNow] = useState(Date.now() / 1000)
  const [conn, setConn] = useState('')
  void catalog.value
  const schemas = schemaMap()

  useEffect(() => {
    if (!catalog.value.plugins.length) loadCatalog().catch(() => {})
    let closed = false
    wfApi.runInfo(id).then((r) => { if (!closed) setRun(r) }).catch(toastError)
    const close = subscribeRun(id, dispatch, setConn)
    return () => { closed = true; close() }
  }, [id])

  const running = state.status === 'running' || state.status === 'queued' || state.status === 'waiting_input'
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(t)
  }, [running])
  useEffect(() => { if (!running && state.finishedAt) wfApi.runInfo(id).then(setRun).catch(() => {}) }, [running, state.finishedAt])

  const snapshot = useMemo(() => run?.snapshot && { ...run.snapshot, blocks: buildTree(run.snapshot.blocks || []) }, [run?.snapshot])
  const byId = useMemo(() => allBlocks(snapshot?.blocks || []), [snapshot])
  const names = useMemo(() => Object.fromEntries(Object.values(byId).map((b) => [b.id, (schemas[b.type]?.name || b.type) + (b.note ? ` · ${b.note}` : '')])), [byId, catalog.value])
  const elapsed = state.startedAt ? (state.finishedAt || now) - state.startedAt : 0
  const result = run?.result ?? state.result

  const cancel = async () => {
    if (!await confirmDialog({ title: 'Cancel run?', body: 'Running agent cards are interrupted.', confirm: 'Cancel run', danger: true })) return
    try { await wfApi.cancel(id) } catch (e) { toastError(e) }
  }
  const rerun = async (from?: string) => {
    try { const r = await wfApi.rerun(id, from); navigate({ name: 'wf-run', runId: r.run_id }, { replace: true }) } catch (e) { toastError(e) }
  }
  const done = !running && !!state.finishedAt

  return (
    <div class="page">
      <TopBar left={<BackButton label="Back" onClick={() => back(run?.workflow_id ? { name: 'wf-editor', workflowId: run.workflow_id } : { name: 'workflows' })} />}
        right={<div class="topbar-actions"><StatusBadge status={state.status} /></div>}>
        <span class="topbar-center">{run?.workflow_name || 'Run'}</span>
      </TopBar>
      <div class="page-scroll">
        <div class="container">
          <div class="wf-run-meta">
            {state.startedAt && <span><WfIcon name="clock" size={15} /> {fmtSecs(elapsed)}</span>}
            {state.cost > 0 && <span>${state.cost.toFixed(4)}</span>}
            {conn === 'reconnecting' && <span>Reconnecting</span>}
            <span style={{ flex: 1 }} />
            {running && <button class="btn small danger" onClick={cancel}><WfIcon name="stop" size={15} /> Cancel</button>}
            {done && <button class="btn small" onClick={() => rerun()}><WfIcon name="refresh" size={15} /> Rerun</button>}
          </div>
          <Segmented value={tab} onChange={setTab} options={[{ value: 'cards', label: 'Cards' }, { value: 'console', label: 'Console' }]} />
          <div style={{ height: '12px' }} />
          {state.error && state.status !== 'cancelled' && <div class="wf-warn">{state.error}</div>}
          {tab === 'cards' && (snapshot?.blocks || []).map((b) => (
            <StepView key={b.id} block={b} state={state} schemas={schemas} snapshot={snapshot} depth={0} runDone={!running} runId={id} onRerun={done ? rerun : undefined} />
          ))}
          {tab === 'cards' && state.waiting && !(state.waiting.block && byId[state.waiting.block]) && <WaitingInput runId={id} waiting={state.waiting} />}
          {tab === 'console' && <ConsoleView state={state} names={names} />}
          {done && result != null && result !== '' && (
            <div style={{ marginTop: '16px' }}>
              <div class="group-title" style={{ marginTop: 0 }}>Result</div>
              <OutBox text={fmtVal(result)} result />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
