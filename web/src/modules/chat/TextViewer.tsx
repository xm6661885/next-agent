// Read-only viewer for a text file (assistant files and chat text attachments). Shows the first 2000 lines.

import { useEffect, useState } from 'preact/hooks'
import { Sheet } from '../../components/ui'
import { IconImport } from '../../components/icons'

const MAX_LINES = 2000

export function TextViewer({ open, onClose, name, url }: { open: boolean; onClose: () => void; name: string; url: string }) {
  const [text, setText] = useState<string | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (!open) return
    setText(null); setErr('')
    let live = true
    fetch(url, { credentials: 'same-origin' })
      .then((r) => r.ok ? r.text() : Promise.reject(new Error(`Could not load the file (${r.status})`)))
      .then((t) => { if (live) setText(t) })
      .catch((e) => { if (live) setErr(e.message) })
    return () => { live = false }
  }, [open, url])
  const lines = text === null ? [] : text.split('\n')
  const cut = lines.length > MAX_LINES
  return (
    <Sheet open={open} onClose={onClose} title={name}
      actions={<a class="btn small" href={url} download={name}><IconImport width={14} height={14} /> Download</a>}>
      {err ? <p class="fhint">{err}</p>
        : text === null ? <div class="skeleton" style={{ height: '160px', borderRadius: '14px' }} />
        : <>
          <pre class="text-viewer">{cut ? lines.slice(0, MAX_LINES).join('\n') : text}</pre>
          {cut && <p class="fhint" style={{ marginTop: '8px' }}>Showing the first {MAX_LINES} of {lines.length} lines. Download the file to see all of it.</p>}
        </>}
    </Sheet>
  )
}
