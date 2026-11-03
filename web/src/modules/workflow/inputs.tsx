// Input fields for workflow inputs (pre-run form and Ask for input cards), and starting a run.

import { useState } from 'preact/hooks'
import { Sheet, Switch } from '../../components/ui'
import { navigate } from '../../lib/router'
import { toastError } from '../../lib/store'
import { wfApi, type Json, type RunOpts, type WfInput } from './api'
import { showSheet } from './ui'

export const INPUT_TYPES = [
  { value: 'text', label: 'Text' }, { value: 'number', label: 'Number' }, { value: 'bool', label: 'Switch' }, { value: 'json', label: 'JSON' },
]

export function InputField({ spec, value, onChange }: { spec: WfInput; value: Json; onChange: (v: Json) => void }) {
  const label = spec.label || spec.name
  const t = spec.type || 'text'
  const v = (e: Event) => (e.target as HTMLInputElement).value
  if (t === 'bool') return <div class="row"><span class="label">{label}</span><Switch on={!!value} onChange={onChange} label={label} /></div>
  let control
  if (t === 'number') control = <input class="input" type="number" inputMode="decimal" value={value ?? ''} onInput={(e) => onChange(v(e) === '' ? '' : Number(v(e)))} />
  else if (t === 'json' || spec.multiline) control = <textarea class={`textarea ${t === 'json' ? 'mono' : ''}`} value={value ?? ''} onInput={(e) => onChange(v(e))} />
  else control = <input class="input" value={value ?? ''} onInput={(e) => onChange(v(e))} />
  return <label class="field"><span class="flabel">{label}</span>{control}</label>
}

const storeKey = (id: string) => `wf-inputs-${id}`
const savedInputs = (id: string): Record<string, Json> => { try { return JSON.parse(localStorage.getItem(storeKey(id)) || '{}') } catch { return {} } }

function RunInputSheet({ workflowId, title, inputs, open, close }: { workflowId: string; title: string; inputs: WfInput[]; open: boolean; close: (v?: Json) => void }) {
  const saved = savedInputs(workflowId)
  const [vals, setVals] = useState(() => Object.fromEntries(inputs.map((i) => [i.name, saved[i.name] ?? i.default ?? (i.type === 'bool' ? false : '')])))
  const go = () => {
    try { localStorage.setItem(storeKey(workflowId), JSON.stringify(vals)) } catch { /* private mode */ }
    close(vals)
  }
  return (
    <Sheet open={open} onClose={() => close(null)} title={title || 'Run inputs'}>
      <div class="group">{inputs.map((s) => <InputField key={s.name} spec={s} value={vals[s.name]} onChange={(x) => setVals({ ...vals, [s.name]: x })} />)}</div>
      <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
        <button class="btn block" onClick={() => close(null)}>Cancel</button>
        <button class="btn block primary" onClick={go}>Run</button>
      </div>
    </Sheet>
  )
}

/** Start a workflow, asking for inputs first when it declares any. Opens the Run page. */
export async function startWorkflow(w: { id: string; name: string }, inputsDef: WfInput[] | undefined, opts: RunOpts = {}) {
  try {
    let inputs: Json = {}
    if (inputsDef?.length) {
      inputs = await showSheet((close, open) => <RunInputSheet workflowId={w.id} title={w.name} inputs={inputsDef} open={open} close={close} />)
      if (inputs == null) return null
    }
    const r = await wfApi.run(w.id, { inputs, ...opts })
    navigate({ name: 'wf-run', runId: r.run_id })
    return r.run_id
  } catch (e) { toastError(e); return null }
}

export async function lastRunId(workflowId: string) {
  const rows = await wfApi.runs({ workflow_id: workflowId, limit: 1 })
  return rows[0]?.id || null
}
