// Card parameter form generated from the plugin input schema.

import { useEffect, useState } from 'preact/hooks'
import { Switch } from '../../../components/ui'
import { api } from '../../../lib/api'
import { TEMP_AGENT } from '../../../lib/router'
import { acpApi } from '../../acp/api'
import { workflows, type Block, type Json, type PluginInput, type PluginSchema } from '../api'
import { findBlock, visibleFor } from '../defs'
import { MagicText } from './MagicText'
import { def, edit, wf } from './state'

function setParam(blockId: string, name: string, value: Json) {
  edit((d) => {
    const b = findBlock(d.blocks, blockId)
    if (b) (b.params ||= {})[name] = value
  }, `${blockId}.${name}`)
}

export function setBlockField(blockId: string, key: keyof Block, value: Json) {
  edit((d) => {
    const b = findBlock(d.blocks, blockId) as any
    if (!b) return
    if (value === undefined || value === '' || value === false) delete b[key]
    else b[key] = value
  }, `${blockId}#${key}`)
}

/** Names declared by Define variable cards above a card. */
export function definedVars(blockId: string) {
  const names: string[] = []
  for (const b of visibleFor(def.value, blockId).blocks)
    if (b.type === 'builtin.var_define' && b.params?.name && !names.includes(b.params.name)) names.push(b.params.name)
  return names
}

const optList = (o: PluginInput['options']) => (o || []).map((x) => (typeof x === 'string' ? { value: x, label: x || '(default)' } : x))
const val = (e: Event) => (e.target as HTMLInputElement).value

// Agent lists for the agent / acp_agent inputs, loaded once per editor session.
let claudeAgents: { id: string; name: string }[] | null = null
let acpAgents: { id: string; name: string }[] | null = null
function useAgents(kind: 'agent' | 'acp_agent') {
  const [list, setList] = useState(kind === 'agent' ? claudeAgents : acpAgents)
  useEffect(() => {
    if (list) return
    if (kind === 'agent') api.agents().then((a) => { claudeAgents = [{ id: TEMP_AGENT, name: 'Temporary chat' }, ...a.map((x) => ({ id: x.id, name: x.name }))]; setList(claudeAgents) }).catch(() => setList([]))
    else acpApi.agents().then((a) => { acpAgents = a.map((x) => ({ id: x.id, name: x.name })); setList(acpAgents) }).catch(() => setList([]))
  }, [kind])
  return list
}

function AgentSelect({ kind, value, set }: { kind: 'agent' | 'acp_agent'; value: string; set: (v: string) => void }) {
  const list = useAgents(kind)
  return (
    <select class="select" value={value ?? ''} onChange={(e) => set(val(e))}>
      <option value="">{list === null ? 'Loading…' : list.length ? 'Select an agent…' : kind === 'acp_agent' ? 'No ACP agents' : 'No agents'}</option>
      {value && list && !list.some((a) => a.id === value) && <option value={value}>{value} (not found)</option>}
      {(list || []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
    </select>
  )
}

function Field({ inp, block }: { inp: PluginInput; block: Block }) {
  const raw = block.params?.[inp.name]
  const v = raw === undefined ? inp.default : raw
  const set = (x: Json) => setParam(block.id, inp.name, x)
  let control
  if (inp.magic) {
    control = <MagicText blockId={block.id} value={v} onChange={set} multiline={inp.multiline}
      mono={inp.type === 'json' || inp.type === 'code' || inp.type === 'expr'} placeholder={inp.placeholder} />
  } else if (inp.type === 'bool') {
    return (
      <div class="row wf-bool">
        <span class="label">{inp.label}{inp.description && <span class="hint">{inp.description}</span>}</span>
        <Switch on={!!v} onChange={set} label={inp.label} />
      </div>
    )
  } else if (inp.type === 'select') {
    control = <select class="select" value={v ?? ''} onChange={(e) => set(val(e))}>{optList(inp.options).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
  } else if (inp.type === 'agent' || inp.type === 'acp_agent') {
    control = <AgentSelect kind={inp.type} value={v} set={set} />
  } else if (inp.type === 'varname') {
    const names = definedVars(block.id)
    control = (
      <select class="select" value={v ?? ''} onChange={(e) => set(val(e))}>
        <option value="">{names.length ? 'Select a variable…' : 'No Define variable card above'}</option>
        {v && !names.includes(v) && <option value={v}>{v} (not defined above)</option>}
        {names.map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
    )
  } else if (inp.type === 'workflow') {
    control = (
      <select class="select" value={v ?? ''} onChange={(e) => set(val(e))}>
        <option value="">Select a workflow…</option>
        {workflows.value.filter((w) => w.id !== wf.value?.id).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
    )
  } else if (inp.type === 'number') {
    control = <input class="input" type="number" inputMode="decimal" value={v ?? ''} placeholder={inp.placeholder} onInput={(e) => set(val(e) === '' ? '' : Number(val(e)))} />
  } else if (inp.multiline || inp.type === 'json' || inp.type === 'code') {
    control = <textarea class={`textarea ${inp.type !== 'text' ? 'mono' : ''}`} value={v ?? ''} placeholder={inp.placeholder} onInput={(e) => set(val(e))} />
  } else {
    control = <input class="input" value={v ?? ''} placeholder={inp.placeholder} onInput={(e) => set(val(e))} />
  }
  return (
    <div class="wf-field">
      <span class="flabel">{inp.label}{inp.required && <span class="req"> *</span>}</span>
      {control}
      {inp.description && <span class="fhint">{inp.description}</span>}
    </div>
  )
}

export function ParamForm({ block, schema }: { block: Block; schema: PluginSchema }) {
  const basic = schema.inputs.filter((i) => !i.advanced)
  const adv = schema.inputs.filter((i) => i.advanced)
  const num = (e: Event) => Number(val(e)) || undefined
  return (
    <>
      {basic.map((inp) => <Field key={inp.name} inp={inp} block={block} />)}
      <details class="wf-adv">
        <summary>Advanced{adv.length ? ` (${adv.length + 2} items)` : ''}</summary>
        <div class="wf-adv-body">
          {adv.map((inp) => <Field key={inp.name} inp={inp} block={block} />)}
          {!schema.container && (
            <div class="wf-pair">
              <div class="wf-field"><span class="flabel">Timeout (s)</span>
                <input class="input" type="number" inputMode="numeric" value={block.timeout_s ?? ''} placeholder="No limit" onInput={(e) => setBlockField(block.id, 'timeout_s', num(e))} /></div>
              <div class="wf-field"><span class="flabel">Retries</span>
                <input class="input" type="number" inputMode="numeric" value={block.retries ?? ''} placeholder="0" onInput={(e) => setBlockField(block.id, 'retries', num(e))} /></div>
            </div>
          )}
          <div class="row wf-bool">
            <span class="label">Continue on error<span class="hint">Keep going on failure; the error is in the "error" output.</span></span>
            <Switch on={!!block.continue_on_error} onChange={(x) => setBlockField(block.id, 'continue_on_error', x)} label="Continue on error" />
          </div>
        </div>
      </details>
    </>
  )
}
