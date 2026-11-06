// Assistant files: text files every chat with this assistant can read.

import { useEffect, useRef, useState } from 'preact/hooks'
import { chatVersion, toast, toastError } from '../../lib/store'
import { back } from '../../lib/router'
import { BackButton, Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../../components/ui'
import { IconEdit, IconFile, IconImport, IconMore, IconPlus, IconTrash } from '../../components/icons'
import { fmtBytes } from '../../lib/util'
import { chatApi, TEXT_ACCEPT, type Assistant, type AssistantFile } from './api'
import { TextViewer } from './TextViewer'

export function FilesPage({ assistantId }: { assistantId: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const [a, setA] = useState<Assistant | null>(null)
  const [list, setList] = useState<AssistantFile[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [view, setView] = useState<AssistantFile | null>(null)
  const [menu, setMenu] = useState<AssistantFile | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const load = () => chatApi.files(assistantId).then(setList).catch(toastError)
  useEffect(() => { chatApi.assistant(assistantId).then(setA).catch(toastError) }, [assistantId, chatVersion.value])
  useEffect(() => { load() }, [assistantId])
  const name = a?.name || 'this assistant'

  const upload = async (fs: FileList | null) => {
    const arr = fs ? Array.from(fs) : []
    if (!arr.length) return
    setBusy(true)
    try { await chatApi.uploadFiles(assistantId, arr); toast(arr.length > 1 ? `${arr.length} files added` : 'File added'); await load() }
    catch (e) { toastError(e) } finally { setBusy(false) }
  }
  const rename = async (f: AssistantFile) => {
    setMenu(null)
    const n = (await promptDialog({ title: 'Rename file', value: f.name, confirm: 'Rename' }))?.trim()
    if (!n || n === f.name) return
    try { await chatApi.renameFile(assistantId, f.id, n); load() } catch (e) { toastError(e) }
  }
  const download = (f: AssistantFile) => {
    setMenu(null)
    const el = document.createElement('a')
    el.href = chatApi.fileUrl(assistantId, f.id); el.download = f.name
    el.click()
  }
  const remove = async (f: AssistantFile) => {
    setMenu(null)
    if (!await confirmDialog({ title: 'Delete file?', body: f.name, confirm: 'Delete', danger: true })) return
    try { await chatApi.deleteFile(assistantId, f.id); setList((l) => l && l.filter((x) => x.id !== f.id)) } catch (e) { toastError(e) }
  }

  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label={name} onClick={() => back({ name: 'assistant', assistantId })} />}
        right={<button class="icon-btn" aria-label="Add files" disabled={busy} onClick={() => input.current?.click()}>{busy ? <span class="spinner" /> : <IconPlus />}</button>}>
        {scrolled && <span class="topbar-center fade-in">Files</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Files</h1>
          <p class="subtitle rise" style={{ '--i': 1 }}>Every chat with {name} can read these files.</p>
          {list === null ? (
            <div class="group">{[0, 1].map((i) => <div key={i} class="row"><div class="skeleton" style={{ height: '36px', flex: 1 }} /></div>)}</div>
          ) : list.length === 0 ? (
            <div class="empty rise" style={{ padding: '28px 20px' }}>
              <IconFile width={30} height={30} style={{ color: 'var(--text-3)' }} />
              <p style={{ margin: '8px 0 12px' }}>No files yet. Add notes, documents or code as plain text, up to 2 MiB each and 100 files.</p>
              <button class="btn primary small" onClick={() => input.current?.click()}><IconPlus width={16} height={16} /> Add files</button>
            </div>
          ) : (
            <div class="group">
              {list.map((f) => (
                <div key={f.id} class="session-row">
                  <button class="row" onClick={() => setView(f)}>
                    <span class="session-state"><IconFile width={16} height={16} style={{ color: 'var(--text-3)' }} /></span>
                    <span class="label"><span class="session-title">{f.name}</span>
                      <span class="hint">{fmtBytes(f.size)} · {f.lines} line{f.lines === 1 ? '' : 's'} · {new Date(f.created_at).toLocaleDateString()}</span></span>
                  </button>
                  <button class="icon-btn session-more" aria-label="More" onClick={() => setMenu(f)}><IconMore /></button>
                </div>
              ))}
            </div>
          )}
          <p class="fhint" style={{ padding: '10px 4px' }}>Text files only. Files are read on demand, so large ones don't fill the context.</p>
        </div>
      </div>
      <input ref={input} type="file" multiple accept={TEXT_ACCEPT} hidden onChange={(e) => { upload((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = '' }} />
      <TextViewer open={!!view} onClose={() => setView(null)} name={view?.name || ''} url={view ? chatApi.fileUrl(assistantId, view.id) : ''} />
      <Sheet open={!!menu} onClose={() => setMenu(null)} title={menu?.name || 'File'}>
        {menu && (
          <div class="menu">
            <button onClick={() => rename(menu)}><IconEdit /> Rename</button>
            <button onClick={() => download(menu)}><IconImport /> Download</button>
            <button class="danger" onClick={() => remove(menu)}><IconTrash /> Delete</button>
          </div>
        )}
      </Sheet>
    </div>
  )
}
