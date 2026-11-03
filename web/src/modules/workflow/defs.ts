// Pure helpers for workflow definitions (no UI). Flat control flow: opener ... [core.else] ... end marker, linked by group.

import type { Block, Definition, Json, PluginSchema } from './api'

export interface Token { ref: string; field?: string; path?: string[]; loop?: string }
type Schemas = Record<string, PluginSchema>

export const LOOP_TYPES = ['core.repeat', 'core.repeat_each']
export const OPENERS: Record<string, string> = { 'core.if': 'core.end_if', 'core.repeat': 'core.end_repeat', 'core.repeat_each': 'core.end_repeat' }
export const MARKERS = ['core.else', 'core.end_if', 'core.end_repeat']
export const isMarker = (b: Block) => MARKERS.includes(b.type)

/** Flat list -> nested tree (then/else/body); unbalanced cards close at the end. Same as backend build_tree. */
export function buildTree(blocks: Block[]): Block[] {
  if (blocks.some((b) => b.then || b.else || b.body)) return blocks
  const root: Block[] = []
  const stack: { node: Block; list: Block[] }[] = []
  const target = () => (stack.length ? stack[stack.length - 1].list : root)
  for (const b of blocks) {
    if (OPENERS[b.type]) {
      const node: Block = { ...b }
      let inner: Block[]
      if (b.type === 'core.if') { node.then = []; node.else = []; inner = node.then } else { node.body = []; inner = node.body }
      target().push(node)
      stack.push({ node, list: inner })
    } else if (isMarker(b)) {
      const top = stack[stack.length - 1]
      if (!top || top.node.id !== b.group) continue
      if (b.type === 'core.else') top.list = top.node.else!
      else stack.pop()
    } else target().push(b)
  }
  return root
}

export function checkFlow(blocks: Block[]) {
  const stack: Block[] = []
  for (const b of blocks) {
    if (OPENERS[b.type]) stack.push(b)
    else if (isMarker(b)) {
      const top = stack[stack.length - 1]
      if (!top || top.id !== b.group) return 'Control flow is out of order'
      if (b.type !== 'core.else') stack.pop()
    }
  }
  return stack.length ? 'A control-flow card is missing its End card' : ''
}

export function depths(blocks: Block[]) {
  const out: Record<string, number> = {}
  let d = 0
  for (const b of blocks) {
    if (isMarker(b)) {
      d = Math.max(0, d - 1)
      out[b.id] = d
      if (b.type === 'core.else') d++
    } else {
      out[b.id] = d
      if (OPENERS[b.type]) d++
    }
  }
  return out
}

/** [start, end] index range of an opener and its markers (inclusive). */
export function groupRange(blocks: Block[], id: string): [number, number] {
  const start = blocks.findIndex((b) => b.id === id)
  let end = start
  blocks.forEach((b, i) => { if (b.group === id) end = i })
  return [start, end]
}

export const uid = () => 'b' + Math.random().toString(36).slice(2, 8)
export const isRef = (t: unknown): t is Token => !!t && typeof t === 'object' && typeof (t as Token).ref === 'string'

export function branchesOf(block: Block): ('then' | 'else' | 'body')[] {
  if (block.type === 'core.if') return ['then', 'else']
  if (LOOP_TYPES.includes(block.type)) return ['body']
  return []
}

export function newBlocks(schema: PluginSchema): Block[] {
  const b: Block = { id: uid(), type: schema.id, params: {} }
  return [b, ...(schema.markers || []).map((t) => ({ id: uid(), type: t, group: b.id }))]
}

export function findBlock(blocks: Block[], id: string): Block | null {
  for (const b of blocks) {
    if (b.id === id) return b
    for (const br of branchesOf(b)) {
      const r = findBlock(b[br] || [], id)
      if (r) return r
    }
  }
  return null
}

/** Copy cards under new ids; refs and marker groups inside the copy are remapped. */
export function cloneBlocks(blocks: Block[]): Block[] {
  const idMap: Record<string, string> = {}
  for (const b of blocks) idMap[b.id] = uid()
  const copy: Block[] = JSON.parse(JSON.stringify(blocks))
  const remap = (o: Json) => {
    if (Array.isArray(o)) o.forEach(remap)
    else if (o && typeof o === 'object') {
      if (isRef(o) && idMap[o.ref]) o.ref = idMap[o.ref]
      if (o.loop && idMap[o.loop]) o.loop = idMap[o.loop]
      Object.values(o).forEach(remap)
    }
  }
  for (const b of copy) {
    b.id = idMap[b.id]
    if (b.group && idMap[b.group]) b.group = idMap[b.group]
    remap(b.params || {})
  }
  return copy
}

export function* iterTokens(obj: Json): Generator<Token> {
  if (isRef(obj)) yield obj
  else if (Array.isArray(obj)) for (const x of obj) yield* iterTokens(x)
  else if (obj && typeof obj === 'object') for (const v of Object.values(obj)) yield* iterTokens(v)
}

/** Same as backend find_invalid_refs. */
export function findInvalidRefs(blocks: Block[]) { return invalidIn(buildTree(blocks)) }
function invalidIn(blocks: Block[], visible = new Set<string>(), loops: string[] = []): { block_id: string; ref: string; reason: string }[] {
  const problems: { block_id: string; ref: string; reason: string }[] = []
  const local = new Set<string>()
  for (const b of blocks) {
    const avail = new Set([...visible, ...local])
    for (const tok of iterTokens(b.params || {})) {
      const ref = tok.ref
      if (ref === '@input' || ref === '@env' || ref === '@var') continue
      if (ref === '@loop') {
        if (!loops.length || (tok.loop && !loops.includes(tok.loop))) problems.push({ block_id: b.id, ref, reason: 'Not inside a repeat card' })
      } else if (!avail.has(ref)) problems.push({ block_id: b.id, ref, reason: 'Referenced card does not exist or is below' })
    }
    const inner = LOOP_TYPES.includes(b.type) ? [...loops, b.id] : loops
    for (const br of branchesOf(b)) problems.push(...invalidIn(b[br] || [], avail, inner))
    local.add(b.id)
  }
  return problems
}

/** What a card can see: earlier cards plus enclosing loops. */
export function visibleFor(def: Definition, blockId: string): { blocks: Block[]; loops: Block[] } {
  let result: { blocks: Block[]; loops: Block[] } | null = null
  const rec = (blocks: Block[], visible: Block[], loops: Block[]): boolean => {
    const local: Block[] = []
    for (const b of blocks) {
      if (b.id === blockId) { result = { blocks: [...visible, ...local], loops }; return true }
      for (const br of branchesOf(b)) {
        const inner = LOOP_TYPES.includes(b.type) ? [...loops, b] : loops
        if (rec(b[br] || [], [...visible, ...local], inner)) return true
      }
      local.push(b)
    }
    return false
  }
  rec(buildTree(def.blocks), [], [])
  return result || { blocks: [], loops: [] }
}

export const blockTitle = (block: Block, schemas: Schemas) => schemas[block.type]?.name || block.type
export function blockName(block: Block, schemas: Schemas) {
  const t = blockTitle(block, schemas)
  return block.note ? `${t} (${block.note})` : t
}

export function tokenLabel(tok: Token, def: Definition, schemas: Schemas) {
  const path = tok.path?.length ? '.' + tok.path.join('.') : ''
  if (tok.ref === '@input') return `Input · ${tok.field || ''}${path}`
  if (tok.ref === '@env') return `Env · ${tok.field || ''}`
  if (tok.ref === '@var') return `${tok.field || ''}${path}`
  if (tok.ref === '@loop') return (tok.field === 'index' ? 'Repeat Index' : 'Repeat Item') + path
  const b = findBlock(def.blocks, tok.ref)
  if (!b) return '(deleted card)'
  const s = schemas[b.type]
  const field = tok.field && tok.field !== s?.default_output ? s?.outputs?.find((o) => o.name === tok.field)?.label || tok.field : ''
  return blockName(b, schemas) + (field ? ` › ${field}` : '') + path
}

export function tokenColor(tok: Token, def: Definition, schemas: Schemas) {
  if (tok.ref === '@var') return 'var(--c-purple)'
  if (tok.ref.startsWith('@')) return 'var(--c-gray)'
  const b = findBlock(def.blocks, tok.ref)
  const c = b && schemas[b.type]?.color
  return c ? `var(--c-${c})` : 'var(--c-gray)'
}

export function previewText(value: Json, def: Definition, schemas: Schemas): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (!Array.isArray(value)) return JSON.stringify(value)
  return value.map((t) => (isRef(t) ? `"${tokenLabel(t, def, schemas)}"` : t)).join('')
}

export const emptyDef = (): Definition => ({ inputs: [], blocks: [] })
