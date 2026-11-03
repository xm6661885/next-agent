// Contenteditable text with inline variable chips. Value is a token array: strings mixed with {ref, field, path} tokens.

import { signal } from '@preact/signals'
import { useLayoutEffect, useRef } from 'preact/hooks'
import { catalog, schemaMap, type Json } from '../api'
import { isRef, tokenColor, tokenLabel, visibleFor, type Token } from '../defs'
import { def } from './state'

/** The card whose magic field has focus (the variable bar inserts into it); null when none. */
export const activeBlock = signal<string | null>(null)
export const pickerOpen = signal(false)
export const chipEdit = signal<{ el: HTMLElement; token: Token; blockId: string; change: (t: Token | null) => void } | null>(null)
let active: { insert: (t: Token) => void } | null = null

export function insertIntoActive(tok: Token) { active?.insert(tok) }

function isBad(tok: Token, blockId: string) {
  if (tok.ref === '@input' || tok.ref === '@env' || tok.ref === '@var') return false
  const v = visibleFor(def.value, blockId)
  if (tok.ref === '@loop') return !v.loops.length || (!!tok.loop && !v.loops.some((l) => l.id === tok.loop))
  return !v.blocks.some((b) => b.id === tok.ref)
}

export function normalize(value: Json): Json[] {
  if (value == null || value === '') return []
  if (typeof value === 'string') return [value]
  if (!Array.isArray(value)) return [String(value)]
  return value
}

function makeChip(tok: Token, blockId: string) {
  const s = document.createElement('span')
  s.className = 'chip wf-chip chip-inline'
  s.contentEditable = 'false'
  refreshChip(s, tok, blockId)
  return s
}

export function refreshChip(el: HTMLElement, tok: Token, blockId: string) {
  const schemas = schemaMap()
  el.dataset.token = JSON.stringify(tok)
  el.textContent = tokenLabel(tok, def.value, schemas)
  el.style.setProperty('--chip', tokenColor(tok, def.value, schemas))
  el.classList.toggle('bad', isBad(tok, blockId))
}

const ZW = '​'

function build(el: HTMLElement, tokens: Json[], blockId: string) {
  el.textContent = ''
  tokens.forEach((t, i) => {
    if (isRef(t)) {
      el.appendChild(makeChip(t, blockId))
      if (i === tokens.length - 1) el.appendChild(document.createTextNode(ZW))
    } else el.appendChild(document.createTextNode(String(t)))
  })
  padTrailing(el)
}

function padTrailing(el: HTMLElement) {
  el.querySelectorAll('br[data-pad]').forEach((b) => b.remove())
  const last = el.lastChild
  if (last && last.nodeType === 3 && /\n$/.test(last.nodeValue || '')) {
    const br = document.createElement('br')
    br.dataset.pad = '1'
    el.appendChild(br)
  }
}

function serialize(el: HTMLElement): Json[] {
  const out: Json[] = []
  let buf = ''
  const flush = () => { if (buf) out.push(buf); buf = '' }
  const walk = (node: Node) => {
    for (const n of Array.from(node.childNodes)) {
      if (n.nodeType === 3) buf += (n.nodeValue || '').replace(/​/g, '')
      else if (n instanceof HTMLElement) {
        if (n.dataset.token) {
          flush()
          try { out.push(JSON.parse(n.dataset.token)) } catch { /* skip */ }
        } else if (n.tagName === 'BR') {
          if (!n.dataset.pad) buf += '\n'
        } else {
          if (buf && !buf.endsWith('\n')) buf += '\n'
          walk(n)
        }
      }
    }
  }
  walk(el)
  flush()
  return out
}

export function MagicText({ value, onChange, blockId, multiline = false, placeholder = '', mono = false }: {
  value: Json; onChange: (v: Json[]) => void; blockId: string; multiline?: boolean; placeholder?: string; mono?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const emitted = useRef<string | null>(null)
  const lastLabels = useRef<string | null>(null)
  const saved = useRef<Range | null>(null)
  const schemas = schemaMap()
  void catalog.value // chip names refresh once the catalog loads
  const tokens = normalize(value)
  const tokJson = JSON.stringify(tokens)
  const sigOf = (toks: Json[]) => toks.filter(isRef).map((t) => tokenLabel(t, def.value, schemas) + isBad(t, blockId)).join('|')
  const labelsSig = sigOf(tokens)

  useLayoutEffect(() => {
    if (emitted.current === tokJson && lastLabels.current === labelsSig) return
    build(ref.current!, tokens, blockId)
    emitted.current = tokJson
    lastLabels.current = labelsSig
  }, [tokJson, labelsSig])

  const emit = () => {
    const el = ref.current!
    const arr: Json[] = []
    for (const t of serialize(el)) {
      if (typeof t === 'string' && typeof arr[arr.length - 1] === 'string') arr[arr.length - 1] += t
      else arr.push(t)
    }
    if (!arr.length) el.textContent = ''
    else padTrailing(el)
    emitted.current = JSON.stringify(arr)
    lastLabels.current = sigOf(arr) // no rebuild while typing, it would lose the caret
    onChange(arr)
  }

  const currentRange = () => {
    const el = ref.current!
    const sel = getSelection()
    if (sel && sel.rangeCount) {
      const r = sel.getRangeAt(0)
      if (el.contains(r.commonAncestorContainer)) return r
    }
    if (saved.current && el.contains(saved.current.commonAncestorContainer)) return saved.current
    const r = document.createRange()
    r.selectNodeContents(el)
    r.collapse(false)
    return r
  }

  const insertNode = (node: Node, trailing?: string) => {
    const r = currentRange()
    r.deleteContents()
    r.insertNode(node)
    let end: Node = node
    if (trailing) {
      const z = document.createTextNode(trailing)
      ;(node as ChildNode).after(z)
      end = z
    }
    r.setStartAfter(end)
    r.collapse(true)
    const sel = getSelection()!
    sel.removeAllRanges()
    sel.addRange(r)
    saved.current = r.cloneRange()
    emit()
  }
  const insertText = (text: string) => insertNode(document.createTextNode(text))
  const insertToken = (tok: Token) => insertNode(makeChip(tok, blockId), ZW)

  const onFocus = () => { active = { insert: insertToken }; activeBlock.value = blockId }
  const onBlur = () => {
    const sel = getSelection()
    const r = sel?.rangeCount ? sel.getRangeAt(0) : null
    if (r && ref.current!.contains(r.commonAncestorContainer)) saved.current = r.cloneRange()
    setTimeout(() => {
      if (pickerOpen.value || chipEdit.value) return
      if ((document.activeElement as HTMLElement | null)?.classList?.contains('magic')) return
      if (activeBlock.value === blockId) activeBlock.value = null
    }, 150)
  }
  const newline = (e: Event) => {
    e.preventDefault()
    if (multiline) insertText('\n')
    else ref.current!.blur()
  }
  const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Enter') newline(e) }
  const onBeforeInput = (e: InputEvent) => { if (e.inputType === 'insertParagraph' || e.inputType === 'insertLineBreak') newline(e) }
  const onPaste = (e: ClipboardEvent) => {
    e.preventDefault()
    const t = e.clipboardData?.getData('text/plain') || ''
    insertText(multiline ? t : t.replace(/\s*\n+\s*/g, ' '))
  }
  const onClick = (e: MouseEvent) => {
    const chip = (e.target as HTMLElement).closest?.('.wf-chip') as HTMLElement | null
    if (!chip || !ref.current!.contains(chip)) return
    let tok: Token
    try { tok = JSON.parse(chip.dataset.token || '') } catch { return }
    chipEdit.value = { el: chip, token: tok, blockId, change: (nt) => { if (nt) refreshChip(chip, nt, blockId); else chip.remove(); emit() } }
  }

  return (
    <div ref={ref} class={`magic ${multiline ? 'multi' : ''} ${mono ? 'mono' : ''}`} contentEditable role="textbox"
      aria-multiline={multiline} data-placeholder={placeholder} spellcheck={false} autocapitalize="off"
      {...{ autocorrect: 'off', enterkeyhint: multiline ? 'enter' : 'done' }}
      onInput={emit} onFocus={onFocus} onBlur={onBlur} onKeyDown={onKeyDown} onBeforeInput={onBeforeInput}
      onPaste={onPaste} onClick={onClick} />
  )
}
