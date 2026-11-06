// Speech to text home: recordings list with search, starred filter and upload, plus the record panel at the bottom.

import { useEffect, useRef, useState } from 'preact/hooks'
import { back, navigate } from '../../lib/router'
import { asrVersion, toast, toastError } from '../../lib/store'
import { BackButton, confirmDialog, promptDialog, Sheet, TopBar, useScrolled } from '../../components/ui'
import { IconClose, IconEdit, IconMore, IconSearch, IconTrash } from '../../components/icons'
import { IconAlert, IconMic, IconStar, IconUpload } from '../../components/icons-apps'
import { asrApi, clock, when, type Summary } from './api'
import { rec } from './recorder'
import { RecordPanel } from './RecordPanel'

let cache: Summary[] | null = null

export function AsrHome() {
  const [items, setItems] = useState<Summary[] | null>(cache)
  const [q, setQ] = useState('')
  const [starOnly, setStarOnly] = useState(false)
  const [menu, setMenu] = useState<Summary | null>(null)
  const [upload, setUpload] = useState<{ name: string; p: number } | null>(null)
  const { scrolled, onScroll, ref } = useScrolled()
  const fileRef = useRef<HTMLInputElement>(null)
  const live = rec.state.value !== 'idle'

  const load = () => asrApi.list(q).then((l) => { if (!q) cache = l; setItems(l) }).catch(toastError)
  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t) }, [q, asrVersion.value])

  // Slow poll only while something is processing and the page is visible; events do the rest.
  const busy = !!items?.some((i) => i.status === 'processing')
  useEffect(() => {
    if (!busy) return
    const t = setInterval(() => { if (document.visibilityState === 'visible') load() }, 3000)
    return () => clearInterval(t)
  }, [busy, q])

  const onFile = async (e: Event) => {
    const input = e.target as HTMLInputElement
    const f = input.files?.[0]
    input.value = ''
    if (!f) return
    setUpload({ name: f.name, p: 0 })
    try {
      const r = await asrApi.upload(f, (p) => setUpload({ name: f.name, p }))
      toast('Uploaded. Transcribing...')
      load()
      navigate({ name: 'asr-detail', id: r.id })
    } catch (ex) { toastError(ex) } finally { setUpload(null) }
  }

  const rename = async () => {
    const it = menu!
    setMenu(null)
    const t = await promptDialog({ title: 'Rename', value: it.title })
    if (!t || !t.trim() || t.trim() === it.title) return
    try { await asrApi.patch(it.id, { title: t.trim() }); load() } catch (e) { toastError(e) }
  }
  const star = async () => {
    const it = menu!
    setMenu(null)
    try { await asrApi.patch(it.id, { starred: !it.starred }); load() } catch (e) { toastError(e) }
  }
  const remove = async () => {
    const it = menu!
    setMenu(null)
    if (!(await confirmDialog({ title: 'Delete recording?', body: 'The audio and transcript will be removed.', confirm: 'Delete', danger: true }))) return
    try { await asrApi.remove(it.id); load() } catch (e) { toastError(e) }
  }

  const shown = items?.filter((i) => (!starOnly || i.starred) && i.id !== rec.id.value)

  return (
    <div class="page asr-home">
      <TopBar scrolled={scrolled} left={<BackButton label="More" onClick={() => back({ name: 'more' })} />}
        right={<button class="icon-btn" onClick={() => fileRef.current?.click()} aria-label="Upload audio" disabled={!!upload}><IconUpload /></button>}>
        {scrolled && <span class="fade-in">Speech to text</span>}
      </TopBar>
      <input ref={fileRef} type="file" accept="audio/*,video/*,.m4a,.mp3,.wav,.aac,.ogg,.opus,.flac,.amr,.webm" hidden onChange={onFile} />
      <div class={`page-scroll ${live ? 'with-panel-open' : ''}`} ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Speech to text</h1>
          <div class="search-box rise" style={{ '--i': 1 }}>
            <IconSearch />
            <input type="search" placeholder="Search titles and transcripts" value={q} enterkeyhint="search"
              onInput={(e) => setQ((e.target as HTMLInputElement).value)} aria-label="Search" />
            {q && <button type="button" class="search-clear" onClick={() => setQ('')} aria-label="Clear"><IconClose /></button>}
          </div>
          <div class="asr-filters">
            <button class={`chip ${starOnly ? 'pink' : ''}`} aria-pressed={starOnly} onClick={() => setStarOnly(!starOnly)}>
              <IconStar fill={starOnly ? 'currentColor' : 'none'} />Starred
            </button>
          </div>
          {upload && (
            <div class="upload-card rise">
              <span class="uc-name">Uploading {upload.name}</span>
              <span class="uc-bar"><i style={{ width: `${upload.p * 100}%` }} /></span>
            </div>
          )}
          {items === null && <div class="asr-list">{[0, 1, 2].map((i) => <div key={i} class="skeleton rec-skel" />)}</div>}
          {shown && shown.length === 0 && !upload && (
            <div class="empty fade-in">
              <div class="empty-icon"><IconMic width={48} height={48} /></div>
              <h3>{q ? 'No matches' : starOnly ? 'Nothing starred' : 'No recordings yet'}</h3>
              <p>{q ? 'Try another word.' : 'Tap the button below to record, or upload a file.'}</p>
            </div>
          )}
          {shown && shown.length > 0 && (
            <div class="asr-list">
              {shown.map((it, i) => <Row key={it.id} it={it} i={i} onMenu={setMenu} />)}
            </div>
          )}
        </div>
      </div>
      <RecordPanel onChanged={load} />
      <Sheet open={!!menu} onClose={() => setMenu(null)} title={menu?.title}>
        <div class="menu">
          <button onClick={rename}><IconEdit />Rename</button>
          <button onClick={star}><IconStar />{menu?.starred ? 'Remove star' : 'Star'}</button>
          <button class="danger" onClick={remove}><IconTrash />Delete</button>
        </div>
      </Sheet>
    </div>
  )
}

function Row({ it, i, onMenu }: { it: Summary; i: number; onMenu: (it: Summary) => void }) {
  const status = it.status === 'processing'
    ? <span class="rec-status busy"><span class="spinner tiny" />{it.progress ? `Transcribing ${it.progress.done}/${it.progress.total}` : 'Processing'}</span>
    : it.status === 'error'
      ? <span class="rec-status err"><IconAlert />Failed</span>
      : it.status === 'recording' ? <span class="rec-status busy">Unfinished</span> : null
  return (
    <div class="rec-row rise" style={{ '--i': Math.min(i, 12) } as any} onContextMenu={(e) => { e.preventDefault(); onMenu(it) }}>
      <button class="rr-main" onClick={() => navigate({ name: 'asr-detail', id: it.id })}>
        <div class="rr-top">
          <span class="rr-title">{it.title}</span>
          {it.starred && <IconStar class="rr-star" fill="currentColor" />}
        </div>
        {it.preview ? <p class="rr-preview">{it.preview}</p> : !status && <p class="rr-preview dim">No speech</p>}
        <div class="rr-meta">
          <span>{when(it.created_at)}</span>
          {it.source === 'upload' && <span class="rr-tag">Upload</span>}
          {status}
          <span class="rr-dur">{clock(it.duration)}</span>
        </div>
      </button>
      <button class="icon-btn rr-more" onClick={() => onMenu(it)} aria-label="Recording actions"><IconMore /></button>
    </div>
  )
}
