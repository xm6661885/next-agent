// Chat composer: textarea, image attachments, model and effort chips, send / stop.
// One reply at a time: while the model answers, the send button becomes stop.

import { useEffect, useRef, useState } from 'preact/hooks'
import { chatApi } from '../api'
import { toastError } from '../../../lib/store'
import type { Attachment } from '../../../lib/types'
import { IconBrain, IconCamera, IconFile, IconImage, IconPaperclip, IconPlug, IconSend, IconStop } from '../../../components/icons'
import { Sheet } from '../../../components/ui'
import { CropSheet } from '../../../components/CropSheet'
import { fmtBytes, haptic, uid } from '../../../lib/util'
import { IconChevronDown } from '../../../components/icons'

interface Pending { key: string; file: File; progress: number; att?: Attachment; error?: string; preview?: string }

export function Composer({ sid, busy, model, effort, mcpOn, onSend, onStop, onOpenModel, onOpenEffort, onOpenMcp, disabled, fill }: {
  sid: string
  busy: boolean
  model: string
  effort: string
  /** Number of MCP servers on in this chat, or null when none are configured. */
  mcpOn: number | null
  onSend: (text: string, atts: Attachment[]) => Promise<boolean>
  onStop: () => void
  onOpenModel: () => void
  onOpenEffort: () => void
  onOpenMcp: () => void
  disabled?: boolean
  /** Text to load into the box (editing a sent message); nonce makes repeats apply. */
  fill?: { text: string; n: number }
}) {
  const draftKey = `chat-draft:${sid}`
  const [text, setText] = useState(() => localStorage.getItem(draftKey) || '')
  // Uploaded attachments are already on the server, so the draft only keeps their metadata.
  const attKey = `chat-draft-att:${sid}`
  const [files, setFiles] = useState<Pending[]>(() => {
    try {
      const saved: Attachment[] = JSON.parse(localStorage.getItem(attKey) || '[]')
      return saved.map((att) => ({ key: uid(), file: new File([], att.name, { type: att.mime }), progress: 1, att,
        preview: att.is_image ? att.url : undefined }))
    } catch { return [] }
  })
  const [attachOpen, setAttachOpen] = useState(false)
  const [focused, setFocused] = useState(false)
  const ta = useRef<HTMLTextAreaElement>(null)
  const imgIn = useRef<HTMLInputElement>(null)
  const camIn = useRef<HTMLInputElement>(null)

  const uploading = files.some((f) => !f.att && !f.error)
  const ready = files.filter((f) => f.att).map((f) => f.att!)
  const canSend = !disabled && !busy && !uploading && (text.trim().length > 0 || ready.length > 0)

  useEffect(() => { text ? localStorage.setItem(draftKey, text) : localStorage.removeItem(draftKey) }, [text])
  useEffect(() => {
    const done = files.filter((f) => f.att).map((f) => f.att!)
    done.length ? localStorage.setItem(attKey, JSON.stringify(done)) : localStorage.removeItem(attKey)
  }, [files])
  useEffect(() => { if (fill) { setText(fill.text); setTimeout(() => ta.current?.focus(), 30) } }, [fill?.n])
  useEffect(() => { resize() }, [text])
  useEffect(() => () => files.forEach((f) => f.preview && revoke(f.preview)), [])

  const revoke = (u: string) => { if (u.startsWith('blob:')) URL.revokeObjectURL(u) }

  const resize = () => {
    const el = ta.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, Math.round(window.innerHeight * 0.38)) + 'px'
  }

  const addFiles = (list: FileList | File[] | null) => {
    if (!list) return
    const arr = Array.from(list).filter((f) => f.type.startsWith('image/'))
    if (!arr.length) return
    const items: Pending[] = arr.map((file) => ({
      key: uid(), file, progress: 0,
      preview: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
    }))
    setFiles((cur) => [...cur, ...items])
    for (const it of items) {
      chatApi.upload(sid, [it.file], (p) => setFiles((cur) => cur.map((f) => (f.key === it.key ? { ...f, progress: p } : f))))
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
      if (f?.preview) revoke(f.preview)
      return cur.filter((x) => x.key !== key)
    })
  }

  const submit = async () => {
    if (!canSend) return
    haptic()
    const t = text
    const atts = ready
    setText('')
    const keep = files
    setFiles([])
    const ok = await onSend(t, atts)
    if (!ok) {
      setText(t)
      setFiles(keep)
    } else {
      keep.forEach((f) => f.preview && revoke(f.preview))
    }
    // Keep the keyboard up on mobile after sending.
    ta.current?.focus()
  }

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape' && busy) { e.preventDefault(); onStop(); return }
    // Plain Enter inserts a newline; Ctrl/Cmd+Enter sends.
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  const onPaste = (e: ClipboardEvent) => {
    const fs = e.clipboardData?.files
    if (fs && fs.length) { e.preventDefault(); addFiles(fs) }
  }

  const [drag, setDrag] = useState(false)
  const [cropping, setCropping] = useState<File | null>(null)

  return (
    <div class={`composer-wrap ${drag ? 'drag' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer?.files || null) }}>
      <div class={`composer ${focused ? 'focused' : ''} ${busy ? 'busy' : ''}`}>
        {files.length > 0 && (
          <div class="att-strip">
            {files.map((f) => (
              <div key={f.key} class={`att-chip pop ${f.error ? 'err' : ''}`}>
                {f.preview ? <img src={f.preview} alt="" /> : <span class="att-icon"><IconFile width={18} height={18} /></span>}
                <span class="att-meta">
                  <span class="att-name">{f.file.name}</span>
                  <span class="att-size">{f.error ? 'Failed' : f.att ? fmtBytes(f.att.size) : `${Math.round(f.progress * 100)}%`}</span>
                </span>
                {!f.att && !f.error && <span class="att-progress" style={{ transform: `scaleX(${f.progress})` }} />}
                <button class="att-x" aria-label="Remove" onClick={() => removeFile(f.key)}>×</button>
              </div>
            ))}
          </div>
        )}
        <textarea ref={ta} rows={1} value={text} enterkeyhint="enter"
          placeholder="Message"
          onInput={(e) => setText((e.target as HTMLTextAreaElement).value)}
          onKeyDown={onKey} onPaste={onPaste}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} />
        <div class="composer-bar">
          <button class="icon-btn" aria-label="Attach" onClick={() => setAttachOpen(true)}><IconPaperclip /></button>
          <button class="model-chip" onClick={onOpenModel} aria-label={`Model: ${model}. Change model`}>
            <span class="model-chip-name">{model || 'Pick a model'}</span>
            <IconChevronDown width={14} height={14} />
          </button>
          <button class="model-chip" onClick={onOpenEffort} aria-label={`Thinking: ${effort}`}>
            <IconBrain width={14} height={14} /><span class="model-chip-name">{effort}</span>
          </button>
          {mcpOn !== null && <button class={`model-chip ${mcpOn ? 'on' : ''}`} onClick={onOpenMcp} aria-label={`MCP servers: ${mcpOn} on`}>
            <IconPlug width={14} height={14} /><span class="model-chip-name">{mcpOn}</span>
          </button>}
          <span style={{ flex: 1 }} />
          {busy ? (
            <button class="send-btn stop pop" aria-label="Stop" onClick={() => { haptic(); onStop() }}>
              <IconStop />
            </button>
          ) : (
            <button class={`send-btn ${canSend ? 'ready' : ''}`} aria-label="Send"
              disabled={!canSend} onClick={() => submit()}>
              <IconSend />
            </button>
          )}
        </div>
      </div>
      <input ref={imgIn} type="file" accept="image/*" multiple hidden onChange={(e) => { addFiles((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = '' }} />
      <input ref={camIn} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) setCropping(f); (e.target as HTMLInputElement).value = '' }} />
      <CropSheet file={cropping} onCancel={() => setCropping(null)} onDone={(f) => { setCropping(null); addFiles([f]) }} />
      <Sheet open={attachOpen} onClose={() => setAttachOpen(false)} title="Add to message">
        <div class="attach-grid">
          <button onClick={() => { setAttachOpen(false); camIn.current?.click() }}><span><IconCamera /></span>Camera</button>
          <button onClick={() => { setAttachOpen(false); imgIn.current?.click() }}><span><IconImage /></span>Photos</button>
        </div>
      </Sheet>
    </div>
  )
}
