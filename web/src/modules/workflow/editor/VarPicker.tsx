// Variable bar above the keyboard, the full variable picker and the chip editor.

import { useEffect, useState } from 'preact/hooks'
import { Sheet } from '../../../components/ui'
import { schemaMap, wfApi, type Block, type PluginSchema } from '../api'
import { blockName, findBlock, visibleFor, type Token } from '../defs'
import { WfIcon } from '../icons'
import { activeBlock, chipEdit, insertIntoActive, pickerOpen } from './MagicText'
import { definedVars } from './ParamForm'
import { def } from './state'

type Item = { label: string; token: Token }
type Group = { key: 'vars' | 'loops' | 'inputs'; items: Item[] } | { key: 'blocks'; blocks: { block: Block; schema: PluginSchema; title: string; outputs: Item[] }[] }

export function variablesFor(blockId: string): Group[] {
  const schemas = schemaMap()
  const v = visibleFor(def.value, blockId)
  const groups: Group[] = []
  const blocks = [...v.blocks].reverse().filter((b) => schemas[b.type]?.outputs?.length).map((b) => {
    const s = schemas[b.type]
    return {
      block: b, schema: s, title: blockName(b, schemas),
      outputs: s.outputs.map((o) => ({ label: o.label, token: o.name === s.default_output ? { ref: b.id } : { ref: b.id, field: o.name } })),
    }
  })
  const vars = definedVars(blockId)
  if (vars.length) groups.push({ key: 'vars', items: vars.map((n) => ({ label: n, token: { ref: '@var', field: n } })) })
  groups.push({ key: 'blocks', blocks })
  if (v.loops.length) {
    groups.push({
      key: 'loops',
      items: [...v.loops].reverse().flatMap((l) => [
        { label: `Repeat Item (${blockName(l, schemas)})`, token: { ref: '@loop', loop: l.id, field: 'item' } },
        { label: `Repeat Index (${blockName(l, schemas)})`, token: { ref: '@loop', loop: l.id, field: 'index' } },
      ]),
    })
  }
  const inputs = (def.value.inputs || []).filter((i) => i.name)
  if (inputs.length) groups.push({ key: 'inputs', items: inputs.map((i) => ({ label: i.label || i.name, token: { ref: '@input', field: i.name } })) })
  return groups
}

function Pill({ label, color, onClick }: { label: string; color?: string; onClick: () => void }) {
  return <button class="chip wf-chip wf-pill" style={{ '--chip': color || 'var(--c-gray)' }} onClick={onClick}>{label}</button>
}

/** Shortcut bar above the keyboard while a magic field has focus. */
export function VarBar() {
  const id = activeBlock.value
  const [vp, setVp] = useState<{ bottom: number; kb: boolean } | null>(null)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    // anchor to the visual viewport bottom; innerHeight on iOS can include the area under the toolbar
    const f = () => setVp({ bottom: vv.offsetTop + vv.height, kb: window.innerHeight - vv.height > 100 })
    vv.addEventListener('resize', f)
    vv.addEventListener('scroll', f)
    f()
    return () => { vv.removeEventListener('resize', f); vv.removeEventListener('scroll', f) }
  }, [])
  if (!id || pickerOpen.value) return null
  const quick: { label: string; token?: Token; color: string }[] = []
  for (const g of variablesFor(id)) {
    if (g.key === 'blocks') for (const b of g.blocks.slice(0, 6)) quick.push({ label: b.title, token: b.outputs[0]?.token, color: `var(--c-${b.schema?.color || 'gray'})` })
    else for (const it of g.items.slice(0, 4)) quick.push({ label: it.label, token: it.token, color: g.key === 'vars' ? 'var(--c-purple)' : 'var(--c-gray)' })
  }
  const keep = (e: Event) => e.preventDefault() // keep the field focused so the keyboard stays open
  const style = vp ? { top: `${vp.bottom}px`, transform: 'translateY(-100%)', paddingBottom: vp.kb ? '8px' : 'calc(8px + var(--safe-b))' } : { bottom: 0, paddingBottom: 'calc(8px + var(--safe-b))' }
  return (
    <div class="wf-varbar" style={style} onPointerDown={keep} onMouseDown={keep}>
      <div class="scroll">
        {quick.length === 0 && <span class="fhint" style={{ padding: '8px' }}>No variables available above</span>}
        {quick.filter((q) => q.token).map((q, i) => <Pill key={i} label={q.label} color={q.color} onClick={() => insertIntoActive(q.token!)} />)}
      </div>
      <button class="btn small" onClick={() => { pickerOpen.value = true }}><WfIcon name="list" size={16} /> All</button>
    </div>
  )
}

const GROUP_TITLE = { loops: 'Repeat', vars: 'Named variables', inputs: 'Workflow inputs' }

/** Full variable picker. */
export function VarPicker() {
  const id = activeBlock.value
  const [env, setEnv] = useState<string[]>([])
  useEffect(() => { if (pickerOpen.value) wfApi.settings().then((s) => setEnv(Object.keys(s.env || {}))).catch(() => {}) }, [pickerOpen.value])
  const open = pickerOpen.value && !!id
  const close = () => { pickerOpen.value = false; activeBlock.value = null }
  const pick = (tok: Token) => { insertIntoActive(tok); close() }
  return (
    <Sheet open={open} onClose={close} title="Insert variable">
      {open && variablesFor(id!).map((g) => g.key === 'blocks' ? (
        <div key="blocks">
          <div class="wf-cat">Cards above</div>
          {g.blocks.length === 0 && <div class="fhint" style={{ padding: '6px 4px' }}>No cards above yet</div>}
          {g.blocks.map((b) => (
            <div key={b.block.id} style={{ padding: '6px 4px' }}>
              <div class="wf-var-title"><WfIcon name={b.schema?.icon} size={16} /> {b.title}</div>
              <div class="wf-wrap">
                {b.outputs.map((o) => <Pill key={o.label} label={o.label} color={`var(--c-${b.schema?.color || 'gray'})`} onClick={() => pick(o.token)} />)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div key={g.key}>
          <div class="wf-cat">{GROUP_TITLE[g.key]}</div>
          <div class="wf-wrap" style={{ padding: '4px' }}>
            {g.items.map((it) => <Pill key={it.label} label={it.label} color={g.key === 'vars' ? 'var(--c-purple)' : undefined} onClick={() => pick(it.token)} />)}
          </div>
        </div>
      ))}
      {open && env.length > 0 && (
        <div>
          <div class="wf-cat">Environment variables</div>
          <div class="wf-wrap" style={{ padding: '4px' }}>{env.map((k) => <Pill key={k} label={k} onClick={() => pick({ ref: '@env', field: k })} />)}</div>
        </div>
      )}
    </Sheet>
  )
}

/** Sheet after tapping a chip: switch output, pick a sub-field, remove. */
export function ChipEditor() {
  const ce = chipEdit.value
  const [path, setPath] = useState('')
  useEffect(() => setPath((ce?.token.path || []).join('.')), [ce])
  const close = () => { chipEdit.value = null }
  if (!ce) return <Sheet open={false} onClose={close} title="">{null}</Sheet>
  const schemas = schemaMap()
  const tok = ce.token
  const block = tok.ref.startsWith('@') ? null : findBlock(def.value.blocks, tok.ref)
  const schema = block && schemas[block.type]
  const apply = (patch: Partial<Token>) => {
    const nt: Token = { ...tok, ...patch }
    if (!nt.field) delete nt.field
    if (!nt.path || !nt.path.length) delete nt.path
    ce.change(nt)
    close()
  }
  return (
    <Sheet open onClose={close} title="Variable settings">
      <div class="group">
        {schema && schema.outputs.length > 1 && (
          <div class="field"><span class="flabel">Output to use</span>
            <select class="select" value={tok.field || schema.default_output} onChange={(e) => {
              const v = (e.target as HTMLSelectElement).value
              apply({ field: v === schema.default_output ? undefined : v })
            }}>
              {schema.outputs.map((o) => <option key={o.name} value={o.name}>{o.label}</option>)}
            </select>
          </div>
        )}
        <label class="field"><span class="flabel">Sub-field (optional)</span>
          <input class="input mono" value={path} placeholder="decision or items.0.name" autocapitalize="off" spellcheck={false}
            onInput={(e) => setPath((e.target as HTMLInputElement).value)} />
          <span class="fhint">For a JSON object or list output, dig deeper with dot-separated keys.</span>
        </label>
      </div>
      <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
        <button class="btn block danger" onClick={() => { ce.change(null); close() }}>Remove</button>
        <button class="btn block primary" onClick={() => apply({ path: path.split('.').map((s) => s.trim()).filter(Boolean) })}>Done</button>
      </div>
    </Sheet>
  )
}
