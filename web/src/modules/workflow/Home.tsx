// Workflow tab root: workflow tiles by group, with run and menu actions.

import { useEffect, useState } from 'preact/hooks'
import { Sheet, confirmDialog, promptDialog } from '../../components/ui'
import { IconSearch } from '../../components/icons'
import { navigate } from '../../lib/router'
import { toast, toastError, workflowVersion } from '../../lib/store'
import { fmtTime, groups, loadCatalog, loadHome, wfApi, workflows, type WfGroup, type Workflow } from './api'
import { AppearanceSheet } from './Editor'
import { WfIcon } from './icons'
import { startWorkflow } from './inputs'
import { TabPage } from './TabPage'
import { MenuItem, SheetHost, downloadJson, pickFile, showSheet } from './ui'

async function guard(fn: () => Promise<unknown>) {
  try { await fn(); await loadHome() } catch (e) { toastError(e) }
}

function menuSheet(title: string, items: (close: () => void) => preact.ComponentChildren) {
  showSheet((close, open) => <Sheet open={open} onClose={() => close()} title={title}><div class="menu">{items(() => close())}</div></Sheet>)
}

function workflowMenu(w: Workflow) {
  menuSheet(w.name, (close) => {
    const act = (fn: () => void) => () => { close(); fn() }
    return <>
      <MenuItem icon="edit" onClick={act(() => navigate({ name: 'wf-editor', workflowId: w.id }))}>Edit</MenuItem>
      <MenuItem icon="play" onClick={act(() => startWorkflow(w, w.inputs))}>Run</MenuItem>
      <MenuItem icon="history" onClick={act(() => navigate({ name: 'wf-runs', workflowId: w.id }))}>Run history</MenuItem>
      <MenuItem icon="sparkles" onClick={act(() => showSheet((c, o) => <AppearanceSheet open={o} close={() => c()} icon={w.icon} color={w.color} save={(p) => guard(() => wfApi.update(w.id, p))} />))}>Icon and color</MenuItem>
      <MenuItem icon="folder" onClick={act(() => moveSheet(w))}>Move to group</MenuItem>
      <MenuItem icon="text" onClick={act(async () => {
        const n = await promptDialog({ title: 'Rename', value: w.name, confirm: 'Rename' })
        if (n?.trim()) guard(() => wfApi.update(w.id, { name: n.trim() }))
      })}>Rename</MenuItem>
      <MenuItem icon="copy" onClick={act(() => guard(() => wfApi.duplicate(w.id)))}>Duplicate</MenuItem>
      <MenuItem icon="download" onClick={act(async () => { try { downloadJson(w.name, await wfApi.exportJson(w.id)) } catch (e) { toastError(e) } })}>Export JSON</MenuItem>
      <MenuItem icon="trash" danger onClick={act(async () => {
        if (await confirmDialog({ title: 'Delete workflow?', body: `"${w.name}" will be deleted.`, confirm: 'Delete', danger: true })) guard(() => wfApi.remove(w.id))
      })}>Delete</MenuItem>
    </>
  })
}

function moveSheet(w: Workflow) {
  menuSheet('Move to group', (close) => <>
    <MenuItem icon="folder" sub={!w.group_id ? 'Current' : ''} onClick={() => { close(); guard(() => wfApi.update(w.id, { clear_group: true })) }}>Ungrouped</MenuItem>
    {groups.value.map((g) => <MenuItem key={g.id} icon="folder" sub={w.group_id === g.id ? 'Current' : ''} onClick={() => { close(); guard(() => wfApi.update(w.id, { group_id: g.id })) }}>{g.name}</MenuItem>)}
  </>)
}

function groupMenu(g: WfGroup, idx: number, all: WfGroup[]) {
  const swap = (j: number) => { const ids = all.map((x) => x.id); [ids[j], ids[idx]] = [ids[idx], ids[j]]; guard(() => wfApi.reorderGroups(ids)) }
  menuSheet(g.name, (close) => <>
    <MenuItem icon="text" onClick={async () => { close(); const n = await promptDialog({ title: 'Rename group', value: g.name, confirm: 'Rename' }); if (n?.trim()) guard(() => wfApi.renameGroup(g.id, n.trim())) }}>Rename</MenuItem>
    {idx > 0 && <MenuItem icon="up" onClick={() => { close(); swap(idx - 1) }}>Move up</MenuItem>}
    {idx < all.length - 1 && <MenuItem icon="down" onClick={() => { close(); swap(idx + 1) }}>Move down</MenuItem>}
    <MenuItem icon="trash" danger onClick={async () => {
      close()
      if (await confirmDialog({ title: 'Delete group?', body: 'Its workflows move to Ungrouped. Nothing else is deleted.', confirm: 'Delete', danger: true })) guard(() => wfApi.deleteGroup(g.id))
    }}>Delete group</MenuItem>
  </>)
}

function Tile({ w, i }: { w: Workflow; i: number }) {
  const open = () => navigate({ name: 'wf-editor', workflowId: w.id })
  return (
    <div class={`wf-tile c-${w.color} rise`} style={{ '--i': Math.min(i, 8) }} role="button" tabIndex={0} onClick={open} onKeyDown={(e) => e.key === 'Enter' && open()}>
      <div class="top">
        <span class="tile-ic"><WfIcon name={w.icon} /></span>
        <span class="tile-actions" onClick={(e) => e.stopPropagation()}>
          <button class="icon-btn" aria-label="Run" onClick={() => startWorkflow(w, w.inputs)}><WfIcon name="play" size={18} /></button>
          <button class="icon-btn" aria-label="More" onClick={() => workflowMenu(w)}><WfIcon name="more" size={18} /></button>
        </span>
      </div>
      <div>
        <div class="name">{w.name}</div>
        <div class="meta">
          <span>{w.block_count} card{w.block_count === 1 ? '' : 's'}</span>
          {w.last_status && <><span class={`wf-dot ${w.last_status}`} /><span>{fmtTime(w.last_run_at)}</span></>}
        </div>
      </div>
    </div>
  )
}

export function WorkflowHome() {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(!workflows.value.length)
  useEffect(() => { loadHome().catch(toastError).finally(() => setLoading(false)) }, [workflowVersion.value])
  useEffect(() => { loadCatalog().catch(() => {}) }, [])

  const list = workflows.value.filter((w) => !q || w.name.toLowerCase().includes(q.toLowerCase()))
  const byGroup = (gid: string | null) => list.filter((w) => (w.group_id || null) === gid)
  const ungrouped = byGroup(null)
  const hasGroups = groups.value.length > 0

  const create = async (group_id: string | null = null) => {
    const name = await promptDialog({ title: 'New workflow', placeholder: 'Daily news digest', confirm: 'Create' })
    if (name === null) return
    try {
      const w = await wfApi.create({ name: name.trim() || 'New workflow', group_id })
      navigate({ name: 'wf-editor', workflowId: w.id })
    } catch (e) { toastError(e) }
  }
  const newGroup = async () => {
    const name = await promptDialog({ title: 'New group', placeholder: 'Daily', confirm: 'Create' })
    if (name?.trim()) guard(() => wfApi.createGroup(name.trim()))
  }
  const importFile = async () => {
    const text = await pickFile()
    if (!text) return
    let data
    try { data = JSON.parse(text) } catch { return toast('File is not valid JSON', 'error') }
    try { const w = await wfApi.importJson(data); toast('Imported'); navigate({ name: 'wf-editor', workflowId: w.id }) } catch (e) { toastError(e) }
  }
  const plus = () => menuSheet('New', (close) => <>
    <MenuItem icon="sparkles" onClick={() => { close(); create() }}>New workflow</MenuItem>
    <MenuItem icon="folder" onClick={() => { close(); newGroup() }}>New group</MenuItem>
    <MenuItem icon="upload" onClick={() => { close(); importFile() }}>Import JSON</MenuItem>
  </>)

  return (
    <TabPage section="workflows" subtitle="Build agent workflows from cards." fab={<button class="fab" onClick={plus}><WfIcon name="plus" /> New</button>}>
      {workflows.value.length > 4 && (
        <div class="wf-search">
          <IconSearch width={18} height={18} />
          <input class="input" placeholder="Search workflows" value={q} onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
        </div>
      )}
      {loading && <div class="wf-grid">{[0, 1].map((i) => <div key={i} class="skeleton" style={{ height: '118px', borderRadius: '18px' }} />)}</div>}
      {!loading && workflows.value.length === 0 && (
        <div class="empty"><h3>No workflows yet</h3><p>Tap New to create the first one.</p></div>
      )}
      {groups.value.map((g, i, all) => {
        const items = byGroup(g.id)
        if (q && !items.length) return null
        return (
          <section key={g.id}>
            <div class="wf-group-head">
              <div class="group-title">{g.name} · {items.length}</div>
              <button class="icon-btn" onClick={() => create(g.id)} aria-label="New workflow in this group"><WfIcon name="plus" size={18} /></button>
              <button class="icon-btn" onClick={() => groupMenu(g, i, all)} aria-label="Group menu"><WfIcon name="more" size={18} /></button>
            </div>
            {items.length ? <div class="wf-grid">{items.map((w, k) => <Tile key={w.id} w={w} i={k} />)}</div> : <p class="fhint" style={{ margin: '0 4px' }}>Empty group</p>}
          </section>
        )
      })}
      {ungrouped.length > 0 && (
        <section>
          {hasGroups && <div class="group-title">Ungrouped · {ungrouped.length}</div>}
          <div class="wf-grid">{ungrouped.map((w, k) => <Tile key={w.id} w={w} i={k} />)}</div>
        </section>
      )}
      <SheetHost />
    </TabPage>
  )
}
