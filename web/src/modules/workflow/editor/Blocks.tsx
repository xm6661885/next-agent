// Flat card list with indentation for control flow, drag to reorder (sortablejs, loaded on first use), card menu and the Add card sheet.

import { computed, signal } from '@preact/signals'
import type Sortable from 'sortablejs'
import { useEffect, useRef } from 'preact/hooks'
import { Sheet, promptDialog } from '../../../components/ui'
import { toast } from '../../../lib/store'
import { catalog, schemaMap, type Block, type PluginSchema } from '../api'
import { OPENERS, blockTitle, checkFlow, cloneBlocks, depths, findInvalidRefs, groupRange, isMarker, newBlocks, previewText } from '../defs'
import { WfIcon } from '../icons'
import { MenuItem, showSheet } from '../ui'
import { ParamForm } from './ParamForm'
import { def, edit } from './state'

export const editorActions = { runTo: (_id: string) => {}, testOne: (_id: string) => {} }
// Openers: ids in the set are collapsed. Other cards: ids in the set are expanded (collapsed by default).
const collapsed = signal(new Set<string>())
export const addTarget = signal<number | null>(null) // insert index; -1 = end; null = closed
const invalidBlocks = computed(() => new Set(findInvalidRefs(def.value.blocks).map((p) => p.block_id)))

export function setAllCollapsed(c: boolean) {
  const ids = (def.value.blocks || []).filter((b) => !isMarker(b))
  collapsed.value = new Set(ids.filter((b) => (OPENERS[b.type] ? c : !c)).map((b) => b.id))
}

function toggleCollapsed(id: string) {
  const s = new Set(collapsed.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  collapsed.value = s
}

/** Index range a card moves as: an opener takes its whole group. */
function rangeOf(blocks: Block[], id: string): [number, number] {
  const b = blocks.find((x) => x.id === id)
  if (b && OPENERS[b.type]) return groupRange(blocks, id)
  const i = b ? blocks.indexOf(b) : -1
  return [i, i]
}

function moveCard(id: string, anchorId: string | undefined, after: boolean) {
  const blocks = def.value.blocks
  const [s, e] = rangeOf(blocks, id)
  if (s < 0 || !anchorId) return
  const rest = [...blocks.slice(0, s), ...blocks.slice(e + 1)]
  let at = rest.findIndex((b) => b.id === anchorId)
  if (at < 0) return toast('Cannot drop a card inside itself', 'error')
  if (after) at = (collapsed.value.has(anchorId) && OPENERS[rest[at].type] ? groupRange(rest, anchorId)[1] : at) + 1
  const next = [...rest.slice(0, at), ...blocks.slice(s, e + 1), ...rest.slice(at)]
  const err = checkFlow(next)
  if (err) return toast(`${err}. That move was undone`, 'error')
  edit((d) => { d.blocks = next })
}

export function BlockList() {
  const ref = useRef<HTMLDivElement>(null)
  const blocks = def.value.blocks
  const dep = depths(blocks)
  const hidden = new Set<string>()
  for (const b of blocks) {
    if (OPENERS[b.type] && collapsed.value.has(b.id)) {
      const [s, e] = groupRange(blocks, b.id)
      for (let i = s + 1; i < e; i++) hidden.add(blocks[i].id)
    }
  }
  const visible = blocks.filter((b) => !hidden.has(b.id))

  // sortablejs installs a document-level, non-passive touchmove listener when it loads, so it is imported
  // here (the first time an editor opens) and not at app start.
  useEffect(() => {
    let s: Sortable | undefined
    let gone = false
    import('sortablejs').then(({ default: SortableJs }) => {
      if (gone || !ref.current) return
      s = SortableJs.create(ref.current, {
        handle: '.drag-handle', animation: 180, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
        forceFallback: true, fallbackOnBody: true, fallbackTolerance: 3, // touch events everywhere, no native DnD on iOS
        scroll: true, scrollSensitivity: 90, scrollSpeed: 16, ghostClass: 'sortable-ghost', chosenClass: 'sortable-chosen',
        onEnd: (evt) => {
          // put the DOM back, then let state re-render, so Sortable and Preact never both edit the list
          const { item, from, oldIndex, newIndex } = evt
          item.remove()
          from.insertBefore(item, from.children[oldIndex!] ?? null)
          if (oldIndex === newIndex) return
          moveCard(item.dataset.id!, (from.children[newIndex!] as HTMLElement | undefined)?.dataset.id, newIndex! > oldIndex!)
        },
      })
    })
    return () => { gone = true; s?.destroy() }
  }, [])
  return (
    <>
      <div class="wf-list" ref={ref}>
        {visible.map((b) => <BlockCard key={b.id} block={b} depth={dep[b.id] || 0} />)}
      </div>
      <button class="wf-add-card" onClick={() => { addTarget.value = -1 }}><WfIcon name="plus" size={16} /> Add card</button>
    </>
  )
}

export function removeBlock(id: string) {
  edit((d) => {
    const b = d.blocks.find((x) => x.id === id)
    if (!b) return
    const gid = isMarker(b) ? b.group : OPENERS[b.type] ? b.id : null
    d.blocks = d.blocks.filter((x) => (gid ? x.id !== gid && x.group !== gid : x.id !== id))
  })
}

function BlockCard({ block, depth }: { block: Block; depth: number }) {
  const schemas = schemaMap()
  const schema = schemas[block.type]
  const indent = { marginLeft: `${Math.min(depth, 6) * 16}px` }
  if (!schema) {
    return (
      <div class="card wf-block c-red" data-id={block.id} style={indent}>
        <div class="wf-block-head">
          <span class="drag-handle icon-btn"><WfIcon name="grip" /></span>
          <div class="wf-block-title">Card type "{block.type}" not found<span class="sub">The plugin may have been removed or failed to load</span></div>
          <button class="icon-btn" aria-label="Delete" onClick={() => removeBlock(block.id)}><WfIcon name="trash" /></button>
        </div>
      </div>
    )
  }
  if (isMarker(block)) {
    const owner = def.value.blocks.find((b) => b.id === block.group)
    return (
      <div class={`card wf-block marker c-${(owner && schemas[owner.type]?.color) || schema.color}`} data-id={block.id} style={indent}>
        <div class="wf-block-head">
          <span class="drag-handle icon-btn" title="Drag to change what is inside"><WfIcon name="grip" /></span>
          <span class="wf-block-icon"><WfIcon name={schema.icon} size={16} /></span>
          <div class="wf-block-title">{schema.name}</div>
          <button class="icon-btn" onClick={() => openMenu(block)} aria-label="More"><WfIcon name="more" /></button>
        </div>
      </div>
    )
  }
  const isCollapsed = OPENERS[block.type] ? collapsed.value.has(block.id) : !collapsed.value.has(block.id)
  const bad = invalidBlocks.value.has(block.id)
  const first = schema.inputs.find((i) => !i.advanced)
  const preview = isCollapsed && first ? previewText(block.params?.[first.name] ?? first.default, def.value, schemas).slice(0, 80) : ''
  const sub = bad ? 'Broken variable reference' : block.disabled ? 'Disabled' + (block.note ? ` · ${block.note}` : '') : block.note || preview
  return (
    <div class={`card wf-block c-${schema.color} ${block.disabled ? 'disabled' : ''} ${bad ? 'bad' : ''} ${OPENERS[block.type] ? 'opener' : ''}`} data-id={block.id} style={indent}>
      <div class="wf-block-head">
        <span class="drag-handle icon-btn" title="Drag to reorder"><WfIcon name="grip" /></span>
        <span class="wf-block-icon"><WfIcon name={schema.icon} /></span>
        <div class="wf-block-title" onClick={() => toggleCollapsed(block.id)}>
          {blockTitle(block, schemas)}
          {sub && <span class={`sub ${block.note && !bad ? 'note' : ''} ${bad ? 'bad' : ''}`}>{sub}</span>}
        </div>
        <button class={`icon-btn wf-collapser ${isCollapsed ? '' : 'open'}`} onClick={() => toggleCollapsed(block.id)} aria-label="Collapse"><WfIcon name="down" size={18} /></button>
        <button class="icon-btn" onClick={() => openMenu(block)} aria-label="More"><WfIcon name="more" /></button>
      </div>
      {!isCollapsed && (
        <div class="wf-block-body">
          {schema.missing_env?.length ? <div class="wf-warn">Missing environment variables: {schema.missing_env.join(', ')} (add them in Workflow settings)</div> : null}
          {bad && <div class="wf-warn">A variable points to a card that does not exist or is below this one. Pick it again.</div>}
          <ParamForm block={block} schema={schema} />
        </div>
      )}
    </div>
  )
}

function openMenu(block: Block) {
  const schemas = schemaMap()
  const marker = isMarker(block)
  const owner = marker ? def.value.blocks.find((b) => b.id === block.group) || block : block
  const idx = def.value.blocks.findIndex((b) => b.id === block.id)
  const act = (close: () => void, fn: () => void) => () => { close(); fn() }
  showSheet((close, open) => (
    <Sheet open={open} onClose={() => close()} title={blockTitle(block, schemas) + (block.note ? ` · ${block.note}` : '')}>
      <div class="menu">
        {!marker && <MenuItem icon="edit" onClick={act(close, () => editNote(block))}>{block.note ? 'Edit note' : 'Add note'}</MenuItem>}
        <MenuItem icon="target" onClick={act(close, () => editorActions.runTo(owner.id))}>Run to here</MenuItem>
        {!marker && <MenuItem icon="flask" sub="Reuses upstream output" onClick={act(close, () => editorActions.testOne(block.id))}>Test this card</MenuItem>}
        <MenuItem icon="plus" onClick={act(close, () => { addTarget.value = idx + 1 })}>Add card below</MenuItem>
        {!marker && <MenuItem icon="up" onClick={act(close, () => shift(block.id, -1))}>Move up</MenuItem>}
        {!marker && <MenuItem icon="down" onClick={act(close, () => shift(block.id, 1))}>Move down</MenuItem>}
        {!marker && <MenuItem icon="copy" onClick={act(close, () => duplicate(block.id))}>Duplicate</MenuItem>}
        {!marker && <MenuItem icon="ban" onClick={act(close, () => toggleDisabled(block.id))}>{block.disabled ? 'Enable' : 'Disable'}</MenuItem>}
        <MenuItem icon="trash" danger sub={marker || OPENERS[block.type] ? 'Cards inside are kept' : ''} onClick={act(close, () => removeBlock(block.id))}>Delete</MenuItem>
      </div>
    </Sheet>
  ))
}

async function editNote(block: Block) {
  const n = await promptDialog({ title: 'Note', value: block.note || '', placeholder: 'Summarize the article', confirm: 'Save' })
  if (n == null) return
  edit((d) => {
    const b = d.blocks.find((x) => x.id === block.id)
    if (!b) return
    if (n.trim()) b.note = n.trim(); else delete b.note
  })
}

/** Move a card (or a whole group) one step, jumping over neighbouring groups. */
function shift(id: string, dir: number) {
  const blocks = def.value.blocks
  const [s, e] = rangeOf(blocks, id)
  if (dir < 0 && s > 0) {
    const prev = blocks[s - 1]
    moveCard(id, isMarker(prev) && prev.type !== 'core.else' ? prev.group : prev.id, false)
  } else if (dir > 0 && e < blocks.length - 1) moveCard(id, blocks[e + 1].id, true)
}

function duplicate(id: string) {
  edit((d) => {
    const [s, e] = rangeOf(d.blocks, id)
    if (s >= 0) d.blocks.splice(e + 1, 0, ...cloneBlocks(d.blocks.slice(s, e + 1)))
  })
}

function toggleDisabled(id: string) {
  edit((d) => {
    const b = d.blocks.find((x) => x.id === id)
    if (b) { if (b.disabled) delete b.disabled; else b.disabled = true }
  })
}

const ORDER = ['AI', 'Control flow', 'Variables', 'Output', 'Text', 'System', 'Date', 'Interaction']

/** "Add card" picker. */
export function AddSheet() {
  const at = addTarget.value
  const close = () => { addTarget.value = null }
  const all = [...catalog.value.containers, ...catalog.value.plugins]
  const cats: Record<string, PluginSchema[]> = {}
  for (const s of all) (cats[s.category] ||= []).push(s)
  const rank = (c: string) => (ORDER.indexOf(c) + 100) % 100
  const names = Object.keys(cats).sort((a, b) => rank(a) - rank(b))
  const add = (s: PluginSchema) => {
    const nb = newBlocks(s)
    if (!OPENERS[nb[0].type]) collapsed.value = new Set([...collapsed.value, nb[0].id])
    edit((d) => { d.blocks.splice(at! < 0 ? d.blocks.length : at!, 0, ...nb) })
    close()
  }
  return (
    <Sheet open={at != null} onClose={close} title="Add card">
      {names.length === 0 && <p class="fhint" style={{ padding: '8px 4px' }}>No plugins loaded.</p>}
      {names.map((c) => (
        <div key={c}>
          <div class="wf-cat">{c}</div>
          {cats[c].map((s, i) => (
            <button key={s.id} class={`wf-plugin-row c-${s.color}`} style={{ '--i': i }} onClick={() => add(s)}>
              <span class="wf-block-icon"><WfIcon name={s.icon} /></span>
              <span style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{s.name}</div>
                <div class="desc">{s.description}</div>
              </span>
            </button>
          ))}
        </div>
      ))}
    </Sheet>
  )
}
