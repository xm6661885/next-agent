// Folder browser sheet: walk the server's filesystem one directory at a time and pick a folder.

import { useEffect, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { toastError } from '../lib/store'
import { shortPath } from '../lib/util'
import type { DirListing } from '../lib/types'
import { Sheet, Switch } from './ui'
import { IconBack, IconChevron, IconClock, IconCode, IconFolder } from './icons'

export function DirPicker({ open, onClose, onPick, confirm = 'Open here' }: {
  open: boolean
  onClose: () => void
  onPick: (path: string) => void
  confirm?: string
}) {
  const [listing, setListing] = useState<DirListing | null>(null)
  const [path, setPath] = useState('')
  const [typed, setTyped] = useState('')
  const [hidden, setHidden] = useState(false)
  const [loading, setLoading] = useState(false)

  // Each directory is listed only when the user opens it.
  const load = (p: string) => {
    setLoading(true)
    api.dirs(p, hidden)
      .then((l) => { setListing(l); setPath(l.path); setTyped(shortPath(l.path)) })
      .catch(toastError)
      .finally(() => setLoading(false))
  }
  useEffect(() => { if (open) load(path) }, [open, hidden])

  const go = (e: Event) => {
    e.preventDefault()
    const t = typed.trim()
    if (t) load(listing && t.startsWith('~') ? listing.home + t.slice(1) : t)
  }

  return (
    <Sheet open={open} onClose={onClose} title="Choose a folder"
      actions={<button class="btn primary small" disabled={!listing || loading} onClick={() => onPick(path)}>{confirm}</button>}>
      <form class="dir-path" onSubmit={go}>
        <button type="button" class="icon-btn" aria-label="Parent folder" disabled={!listing?.parent || loading}
          onClick={() => listing?.parent && load(listing.parent)}><IconBack /></button>
        <input class="input mono" aria-label="Folder path" value={typed} spellcheck={false} autocapitalize="off"
          onInput={(e) => setTyped((e.target as HTMLInputElement).value)} />
      </form>

      {!!listing?.recent.length && (
        <>
          <div class="group-title">Recent</div>
          <div class="group">
            {listing.recent.map((r) => (
              <button key={r} class="row" onClick={() => load(r)}>
                <IconClock width={18} height={18} class="dir-icon" />
                <span class="label mono-label">{shortPath(r)}</span>
              </button>
            ))}
          </div>
        </>
      )}

      <div class="group-title dir-head">
        <span>{loading ? 'Loading' : `${listing?.dirs.length ?? 0} folders`}</span>
        <span class="dir-hidden">Show hidden <Switch on={hidden} onChange={setHidden} label="Show hidden folders" /></span>
      </div>
      <div class="group dir-list">
        {listing && listing.dirs.length === 0 && !loading && <div class="row"><span class="label hint">No subfolders</span></div>}
        {listing?.dirs.map((d) => (
          <button key={d.path} class="row" onClick={() => load(d.path)}>
            {d.git ? <IconCode width={18} height={18} class="dir-icon git" /> : <IconFolder width={18} height={18} class="dir-icon" />}
            <span class="label">{d.name}</span>
            <IconChevron class="chev" />
          </button>
        ))}
      </div>
    </Sheet>
  )
}
