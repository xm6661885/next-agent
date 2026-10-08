// Message composer: autosizing textarea, attachments with upload progress, slash command
// suggestions, model chip (Shift+Tab still cycles permission modes like the CLI), send / steer / stop.

import { useEffect, useRef, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { toastError } from '../lib/store'
import type { Attachment, SessionState } from '../lib/types'
import { IconCamera, IconFile, IconImage, IconPaperclip, IconSend, IconStop, IconSteer } from '../components/icons'
import { Sheet } from '../components/ui'
import { MODE_CYCLE, MODE_LABELS, fmtBytes, haptic, uid } from '../lib/util'
import { modelShort } from '../components/ModelPicker'
import { IconChevronDown } from '../components/icons'

interface Pending { key: string; file: File; progress: number; att?: Attachment; error?: string; preview?: string }

export function Composer({ sid, state, mode, model, slash, onSend, onInterrupt, onMode, onOpenModel, disabled }: {
  sid: string
  state: SessionState
  mode: string
  model: string
  slash: string[]
  onSend: (text: string, atts: Attachment[], steerNow: boolean) => Promise<boolean>
  onInterrupt: () => void
  onMode: (m: string) => void
  onOpenModel: () => void
  disabled?: boolean
}) {
  const draftKey = `draft:${sid}`
  const [text, setText] = useState(() => localStorage.getItem(draftKey) || '')
  const [files, setFiles] = useState<Pending[]>([])
  const [attachOpen, setAttachOpen] = useState(false)
  const [slashIdx, setSlashIdx] = useState(0)
  const [focused, setFocused] = useState(false)
  const ta = useRef<HTMLTextAreaElement>(null)
  const fileIn = useRef<HTMLInputElement>(null)
  const imgIn = useRef<HTMLInputElement>(null)
  const camIn = useRef<HTMLInputElement>(null)

  const busy = state === 'running' || state === 'interrupting'
  const uploading = files.some((f) => !f.att && !f.error)
  const ready = files.filter((f) => f.att).map((f) => f.att!)
  const canSend = !disabled && !uploading && (text.trim().length > 0 || ready.length > 0)

  useEffect(() => { localStorage.setItem(draftKey, text) }, [text])
  useEffect(() => { resize() }, [text])
  useEffect(() => () => files.forEach((f) => f.preview && URL.revokeObjectURL(f.preview)), [])

  const resize = () => {
    const el = ta.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, Math.round(window.innerHeight * 0.38)) + 'px'
  }

  // Slash command suggestions while the message starts with "/".
  const slashQuery = /^\/(\S*)$/.exec(text)?.[1]
  const suggestions = slashQuery !== undefined
    ? slash.filter((c) => c.toLowerCase().startsWith(slashQuery.toLowerCase())).slice(0, 8)
    : []

  const addFiles = (list: FileList | File[] | null) => {
    if (!list) return
    const arr = Array.from(list)
    if (!arr.length) return
    const items: Pending[] = arr.map((file) => ({
      key: uid(), file, progress: 0,
      preview: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
    }))
    setFiles((cur) => [...cur, ...items])
    for (const it of items) {
      api.upload(sid, [it.file], (p) => setFiles((cur) => cur.map((f) => (f.key === it.key ? { ...f, progress: p } : f))))
        .then(([att]) => setFiles((cur) => cur.map((f) => (f.key === it.key ? { ...f, att, progress: 1 } : f))))
        .catch((e) => {
          setFiles((cur) => cur.map((f) => (f.key === it.key ? { ...f, error: e.message } : f)))
          toastError(e)
        })
    }
  }

  const removeFile = (key: string) => {
    setFiles((cur) => {
      const f = cur.find((x) => x.key === key)
      if (f?.preview) URL.revokeObjectURL(f.preview)
      return cur.filter((x) => x.key !== key)
    })
  }

  const submit = async (steerNow = false) => {
    if (!canSend) return
    haptic()
    const t = text
    const atts = ready
    setText('')
    const keep = files
    setFiles([])
    const ok = await onSend(t, atts, steerNow)
    if (!ok) {
      setText(t)
      setFiles(keep)
    } else {
      keep.forEach((f) => f.preview && URL.revokeObjectURL(f.preview))
    }
    // Keep the keyboard up on mobile after sending.
    ta.current?.focus()
  }

  const onKey = (e: KeyboardEvent) => {
    if (suggestions.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSlashIdx((slashIdx + 1) % suggestions.length); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSlashIdx((slashIdx - 1 + suggestions.length) % suggestions.length); return }
      if (e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); setText(`/${suggestions[slashIdx]} `); return }
    }
    if (e.key === 'Tab' && e.shiftKey) {
      e.preventDefault()
      const i = MODE_CYCLE.indexOf(mode)
      onMode(MODE_CYCLE[(i + 1) % MODE_CYCLE.length])
      return
    }
    if (e.key === 'Escape' && busy) { e.preventDefault(); onInterrupt(); return }
    // Plain Enter inserts a newline; Ctrl/Cmd+Enter sends (add Shift to steer right away).
    if (e.key === 'Enter' && !e.isComposing && suggestions.length && text !== `/${suggestions[slashIdx]}`) {
      e.preventDefault(); setText(`/${suggestions[slashIdx]} `); return
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.isComposing) {
      e.preventDefault()
      submit(e.shiftKey)
    }
  }

  const onPaste = (e: ClipboardEvent) => {
    const fs = e.clipboardData?.files
    if (fs && fs.length) { e.preventDefault(); addFiles(fs) }
  }

  const [drag, setDrag] = useState(false)

  return (
    <div class={`composer-wrap ${drag ? 'drag' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer?.files || null) }}>
      {suggestions.length > 0 && (
        <div class="slash-pop pop">
          {suggestions.map((c, i) => (
            <button key={c} class={i === slashIdx ? 'on' : ''} onMouseDown={(e) => { e.preventDefault(); setText(`/${c} `); ta.current?.focus() }}>
              /{c}
            </button>
          ))}
        </div>
      )}
      <div class={`composer ${focused ? 'focused' : ''} ${busy ? 'busy' : ''}`}>
        {files.length > 0 && (
          <div class="att-strip">
            {files.map((f) => (
              <div key={f.key} class={`att-chip pop ${f.error ? 'err' : ''}`}>
                {f.preview ? <img src={f.preview} alt="" /> : <span class="att-icon"><IconFile width={18} height={18} /></span>}
                <span class="att-meta">
                  <span class="att-name">{f.file.name}</span>
                  <span class="att-size">{f.error ? 'Failed' : f.att ? fmtBytes(f.file.size) : `${Math.round(f.progress * 100)}%`}</span>
                </span>
                {!f.att && !f.error && <span class="att-progress" style={{ transform: `scaleX(${f.progress})` }} />}
                <button class="att-x" aria-label="Remove" onClick={() => removeFile(f.key)}>×</button>
              </div>
            ))}
          </div>
        )}
        <textarea ref={ta} rows={1} value={text} enterkeyhint="enter"
          placeholder={busy ? 'Add a message while Claude works' : 'Message Claude'}
          onInput={(e) => setText((e.target as HTMLTextAreaElement).value)}
          onKeyDown={onKey} onPaste={onPaste}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} />
        <div class="composer-bar">
          <button class="icon-btn" aria-label="Attach" onClick={() => setAttachOpen(true)}><IconPaperclip /></button>
          <button class={`model-chip mode-${mode}`} onClick={onOpenModel} title={`Model. ${MODE_LABELS[mode] || mode}; Shift+Tab cycles modes`}
            aria-label={`Model: ${model || 'default'}. Change model`}>
            <span class={`mode-swatch mode-${mode}`} />
            <span class="model-chip-name">{model ? modelShort(model) : 'Default model'}</span>
            <IconChevronDown width={14} height={14} />
          </button>
          <span style={{ flex: 1 }} />
          {busy && canSend && (
            <button class="icon-btn steer-btn pop" aria-label="Interrupt and send now" title="Interrupt and send now"
              onClick={() => submit(true)}><IconSteer /></button>
          )}
          {busy && !canSend ? (
            <button class="send-btn stop pop" aria-label="Stop" onClick={() => { haptic(); onInterrupt() }}>
              <IconStop />
            </button>
          ) : (
            <button class={`send-btn ${canSend ? 'ready' : ''}`} aria-label={busy ? 'Send to running turn' : 'Send'}
              disabled={!canSend} onClick={() => submit(false)}>
              <IconSend />
            </button>
          )}
        </div>
      </div>
      <input ref={fileIn} type="file" multiple hidden onChange={(e) => { addFiles((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = '' }} />
      <input ref={imgIn} type="file" accept="image/*" multiple hidden onChange={(e) => { addFiles((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = '' }} />
      <input ref={camIn} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { addFiles((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = '' }} />
      <Sheet open={attachOpen} onClose={() => setAttachOpen(false)} title="Add to message">
        <div class="attach-grid">
          <button onClick={() => { setAttachOpen(false); camIn.current?.click() }}><span><IconCamera /></span>Camera</button>
          <button onClick={() => { setAttachOpen(false); imgIn.current?.click() }}><span><IconImage /></span>Photos</button>
          <button onClick={() => { setAttachOpen(false); fileIn.current?.click() }}><span><IconFile /></span>Files</button>
        </div>
      </Sheet>
    </div>
  )
}
