// Workflow editor: card list, autosave, undo/redo, inputs, appearance, run.

import { useEffect, useState } from 'preact/hooks'
import { BackButton, Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../../components/ui'
import { IconMore } from '../../components/icons'
import { back, navigate } from '../../lib/router'
import { toast, toastError } from '../../lib/store'
import { loadCatalog, loadHome, wfApi, workflows } from './api'
import { findInvalidRefs } from './defs'
import { COLOR_CHOICES, ICON_CHOICES, WfIcon } from './icons'
import { INPUT_TYPES, lastRunId, startWorkflow } from './inputs'
import { MenuItem, SheetHost, downloadJson, showSheet } from './ui'
import { AddSheet, BlockList, editorActions, setAllCollapsed } from './editor/Blocks'
import { ChipEditor, VarBar, VarPicker } from './editor/VarPicker'
import { def, edit, flushSave, hist, openWorkflow, redo, saveState, undo, updateMeta, wf } from './editor/state'

const SAVE_TEXT = { saved: 'Saved', dirty: 'Editing', saving: 'Saving', error: 'Save failed' }
const val = (e: Event) => (e.target as HTMLInputElement).value

function InputsSheet({ open, close }: { open: boolean; close: () => void }) {
  const inputs = def.value.inputs || []
  const setAt = (i: number, patch: object) => edit((d) => { Object.assign(d.inputs[i], patch) }, `input${i}`)
  return (
    <Sheet open={open} onClose={close} title="Workflow inputs">
      <p class="fhint" style={{ margin: '0 4px 12px' }}>Parameters this workflow needs. A form appears when you run it, and API calls pass them as inputs. Cards reference them with the Inputs variable.</p>
      {inputs.map((inp, i) => (
        <div class="group wf-input-def" key={i}>
          <div class="wf-pair">
            <input class="input" placeholder="Parameter name" value={inp.name} onInput={(e) => setAt(i, { name: val(e).replace(/\s/g, '_') })} />
            <select class="select" style={{ width: '110px', flex: 'none' }} value={inp.type || 'text'} onChange={(e) => setAt(i, { type: val(e) })}>
              {INPUT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            <button class="icon-btn" aria-label="Remove" onClick={() => edit((d) => { d.inputs.splice(i, 1) })}><WfIcon name="trash" /></button>
          </div>
          <div class="wf-pair">
            <input class="input" placeholder="Display name (optional)" value={inp.label || ''} onInput={(e) => setAt(i, { label: val(e) })} />
            <input class="input" placeholder="Default value" value={inp.default ?? ''} onInput={(e) => setAt(i, { default: val(e) })} />
          </div>
        </div>
      ))}
      <button class="btn block" style={{ marginTop: '12px' }} onClick={() => edit((d) => { (d.inputs ||= []).push({ name: `param${d.inputs.length + 1}`, type: 'text' }) })}>
        <WfIcon name="plus" size={16} /> Add parameter
      </button>
    </Sheet>
  )
}

/** Icon and color picker; `save` applies one change (the editor and the home menu share it). */
export function AppearanceSheet({ open, close, icon, color, save }: { open: boolean; close: () => void; icon: string; color: string; save: (p: { icon?: string; color?: string }) => void }) {
  const [cur, setCur] = useState({ icon, color })
  const set = (p: { icon?: string; color?: string }) => { setCur({ ...cur, ...p }); save(p) }
  return (
    <Sheet open={open} onClose={close} title="Icon and color">
      <div class="wf-wrap" style={{ marginBottom: '14px' }}>
        {COLOR_CHOICES.map((c) => <button key={c} class={`wf-swatch ${cur.color === c ? 'on' : ''}`} style={{ background: `var(--c-${c})` }} onClick={() => set({ color: c })} aria-label={c} />)}
      </div>
      <div class="wf-wrap">
        {ICON_CHOICES.map((n) => <button key={n} class={`icon-btn wf-icon-choice ${cur.icon === n ? 'on' : ''}`} onClick={() => set({ icon: n })} aria-label={n}><WfIcon name={n} /></button>)}
      </div>
    </Sheet>
  )
}

export function Editor({ id }: { id: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const [ready, setReady] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    setReady(false); setErr(null)
    Promise.all([openWorkflow(id), loadCatalog(), workflows.value.length ? null : loadHome()])
      .then(() => setReady(true)).catch((e) => setErr(e.message))
    editorActions.runTo = async (blockId) => { await flushSave(); startWorkflow(wf.value!, def.value.inputs, { stop_after: blockId }) }
    editorActions.testOne = async (blockId) => {
      await flushSave()
      startWorkflow(wf.value!, def.value.inputs, { only_block: blockId, base_run_id: await lastRunId(wf.value!.id) })
    }
    return () => { flushSave() }
  }, [id])

  const w = wf.value
  const d = def.value
  const leave = () => { flushSave(); loadHome().catch(() => {}); back({ name: 'workflows' }) }
  const bar = (title?: string, right?: preact.ComponentChildren) => (
    <TopBar scrolled={scrolled} left={<BackButton label="Workflows" onClick={leave} />} right={right}>
      {title && <button class="topbar-center wf-title-btn" onClick={rename}>{title}</button>}
    </TopBar>
  )
  const rename = async () => {
    const n = await promptDialog({ title: 'Rename', value: wf.value?.name || '', confirm: 'Rename' })
    if (n?.trim()) updateMeta({ name: n.trim() }).catch(toastError)
  }
  if (err) return <div class="page">{bar()}<div class="empty"><h3>Failed to open</h3><p>{err}</p></div></div>
  if (!ready || !w || w.id !== id) return <div class="page">{bar()}<div class="container"><div class="skeleton" style={{ height: '240px', marginTop: '20px', borderRadius: '20px' }} /></div></div>
  const invalid = findInvalidRefs(d.blocks)

  const run = async () => {
    if (invalid.length) return toast('Some variable references are broken. Fix them first', 'error')
    await flushSave()
    startWorkflow(w, d.inputs)
  }
  const openInputs = () => showSheet((c, open) => <InputsSheet open={open} close={() => c()} />)

  const menu = () => showSheet((close, open) => {
    const act = (fn: () => void) => () => { close(); fn() }
    return (
      <Sheet open={open} onClose={() => close()} title="More">
        <div class="menu">
          <MenuItem icon="edit" onClick={act(rename)}>Rename</MenuItem>
          <MenuItem icon="sparkles" onClick={act(() => showSheet((c, o) => <AppearanceSheet open={o} close={() => c()} icon={w.icon} color={w.color} save={(p) => updateMeta(p).catch(toastError)} />))}>Icon and color</MenuItem>
          <MenuItem icon="input" sub={d.inputs?.length ? `${d.inputs.length} inputs` : ''} onClick={act(openInputs)}>Workflow inputs</MenuItem>
          <MenuItem icon="up" onClick={act(() => setAllCollapsed(true))}>Collapse all cards</MenuItem>
          <MenuItem icon="down" onClick={act(() => setAllCollapsed(false))}>Expand all cards</MenuItem>
          <MenuItem icon="history" onClick={act(() => navigate({ name: 'wf-runs', workflowId: w.id }))}>Run history</MenuItem>
          <MenuItem icon="download" onClick={act(async () => { await flushSave(); downloadJson(w.name, await wfApi.exportJson(w.id)) })}>Export JSON</MenuItem>
          <MenuItem icon="trash" danger onClick={act(async () => {
            if (!await confirmDialog({ title: 'Delete workflow?', body: `"${w.name}" will be deleted. Run history is kept.`, confirm: 'Delete', danger: true })) return
            try { await wfApi.remove(w.id); await loadHome(); navigate({ name: 'workflows' }, { replace: true }) } catch (e) { toastError(e) }
          })}>Delete workflow</MenuItem>
        </div>
      </Sheet>
    )
  })

  return (
    <div class="page">
      {bar(w.name, (
        <div class="topbar-actions">
          <span class={`wf-save ${saveState.value}`}>{SAVE_TEXT[saveState.value]}</span>
          <button class="icon-btn" disabled={!hist.value.undo} onClick={undo} aria-label="Undo"><WfIcon name="undo" /></button>
          <button class="icon-btn" disabled={!hist.value.redo} onClick={redo} aria-label="Redo"><WfIcon name="redo" /></button>
          <button class="icon-btn" onClick={menu} aria-label="More"><IconMore /></button>
        </div>
      ))}
      <div class="page-scroll wf-editor-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          {invalid.length > 0 && <div class="wf-warn" style={{ marginTop: '12px' }}>{invalid.length} broken variable reference(s), pointing to cards below or deleted ones. Fix them to run.</div>}
          {d.inputs?.length > 0 && (
            <button class="card wf-inputs-btn press" onClick={openInputs}>
              <WfIcon name="input" /><span style={{ flex: 1 }}><b>Workflow inputs</b> <span class="fhint">{d.inputs.map((i) => i.label || i.name).join(', ')}</span></span>
            </button>
          )}
          <div style={{ height: '12px' }} />
          <BlockList />
          {d.blocks.length === 0 && <div class="empty" style={{ padding: '24px' }}><h3>Start with a card</h3><p>Build the workflow one card at a time.</p></div>}
        </div>
      </div>
      <button class="fab" onClick={run}><WfIcon name="play" /> Run</button>
      <AddSheet />
      <VarBar />
      <VarPicker />
      <ChipEditor />
      <SheetHost />
    </div>
  )
}
