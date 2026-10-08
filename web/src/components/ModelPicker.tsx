// Model chips shared by agent settings and the in-chat controls, plus a "Custom" chip for any model ID.

import { useEffect, useRef, useState } from 'preact/hooks'
import { meta } from '../lib/store'
import { IconCheck, IconEdit } from './icons'

export function ModelPicker({ value, onChange, defaultLabel = 'Default' }: {
  value: string
  onChange: (m: string) => void
  defaultLabel?: string
}) {
  const known = (meta.value?.models || ['', 'opus', 'sonnet']).filter(Boolean)
  const list = ['', ...known]
  const isCustom = !!value && !known.includes(value)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { if (editing) setTimeout(() => input.current?.focus(), 30) }, [editing])

  const commit = () => {
    const m = draft.trim()
    setEditing(false)
    if (m && m !== value) onChange(m)
  }

  return (
    <div class="model-picker">
      <div class="model-chips">
        {list.map((m) => (
          <button type="button" key={m || 'default'} class={`chip ${value === m ? 'pink' : ''}`} onClick={() => { setEditing(false); onChange(m) }}>
            {m || defaultLabel}
          </button>
        ))}
        {isCustom && !editing && <button type="button" class="chip pink" onClick={() => { setDraft(value); setEditing(true) }}>{value}</button>}
        {!editing && (
          <button type="button" class="chip dashed" onClick={() => { setDraft(isCustom ? value : ''); setEditing(true) }}>
            <IconEdit /> Custom
          </button>
        )}
      </div>
      {editing && (
        <form class="model-custom pop" onSubmit={(e) => { e.preventDefault(); commit() }}>
          <input ref={input} class="input mono" value={draft} placeholder="Model ID, e.g. claude-opus-5-5[1m]"
            autocapitalize="off" autocomplete="off" spellcheck={false}
            onInput={(e) => setDraft((e.target as HTMLInputElement).value)}
            onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setEditing(false) } }} />
          <button type="button" class="btn small ghost" onClick={() => setEditing(false)}>Cancel</button>
          <button type="submit" class="btn small primary" disabled={!draft.trim()}><IconCheck width={16} height={16} /> Use</button>
        </form>
      )}
    </div>
  )
}

/** Short label for a model id in tight spaces (composer chip). */
export function modelShort(m: string) {
  return m.replace(/^claude-/, '').replace(/-(\d+)-(\d+)/, ' $1.$2')
}
