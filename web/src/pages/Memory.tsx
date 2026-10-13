// Claude Code memory on this machine: the global CLAUDE.md plus each project's auto-memory folder
// (~/.claude/projects/<id>/memory/*.md). Tap a file to edit it in a sheet.

import { useEffect, useState } from 'preact/hooks'
import { api } from '../lib/api'
import { toast, toastError } from '../lib/store'
import { back } from '../lib/router'
import { BackButton, Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../components/ui'
import { IconFile, IconPlus, IconSearch, IconTrash } from '../components/icons'
import { relTime, shortPath } from '../lib/util'
import type { MemoryFile, MemoryListing } from '../lib/types'

const TEMPLATE = (slug: string) => `---\nname: ${slug}\ndescription: \nmetadata:\n  type: project\n---\n\n`

export function Memory() {
  const { scrolled, onScroll, ref } = useScrolled()
  const [data, setData] = useState<MemoryListing | null>(null)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  const load = () => api.memory().then(setData).catch(toastError)
  useEffect(() => { load() }, [])

  const create = async (pid: string) => {
    const raw = await promptDialog({ title: 'New memory', placeholder: 'short-kebab-name', confirm: 'Create' })
    const slug = raw?.trim().replace(/\.md$/, '').replace(/[^\w.-]+/g, '-')
    if (!slug) return
    const path = `projects/${pid}/memory/${slug}.md`
    try { await api.putMemoryFile(path, TEMPLATE(slug), true); await load(); setOpen(path) } catch (e) { toastError(e) }
  }

  const needle = q.trim().toLowerCase()
  const match = (f: MemoryFile) => !needle || [f.name, f.title, f.description].some((s) => s?.toLowerCase().includes(needle))
  const projects = (data?.projects || [])
    .map((p) => ({ ...p, shown: p.files.filter(match) }))
    .filter((p) => p.shown.length > 0 || (p.cwd || p.id).toLowerCase().includes(needle))

  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label="Settings" onClick={() => back({ name: 'settings' })} />}>
        <span class="topbar-center">Memory</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">
          <label class="mem-search">
            <IconSearch width={16} height={16} />
            <input class="input" value={q} placeholder="Search memory" onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
          </label>
          {!data ? <div class="skeleton" style={{ height: '240px', marginTop: '16px', borderRadius: '20px' }} /> : (
            <>
              <div class="group-title">Global</div>
              <div class="group">
                {data.global
                  ? <FileRow f={data.global} label={`${shortPath(data.root)}/CLAUDE.md`} onOpen={setOpen} />
                  : <button class="row" onClick={async () => {
                      try { await api.putMemoryFile('CLAUDE.md', '', true); await load(); setOpen('CLAUDE.md') } catch (e) { toastError(e) }
                    }}><IconPlus width={18} height={18} /><span class="label">Create global CLAUDE.md</span></button>}
              </div>
              {projects.length === 0 && <p class="fhint" style={{ padding: '16px 4px' }}>{needle ? 'No matches.' : 'No project has auto-memory yet.'}</p>}
              {projects.map((p) => (
                <section key={p.id}>
                  <div class="group-title temp-head">
                    <span class="mono-label" title={p.cwd || p.id}>{p.cwd ? shortPath(p.cwd) : p.id}</span>
                    <button class="btn ghost small" onClick={() => create(p.id)}><IconPlus width={16} height={16} /> New</button>
                  </div>
                  <div class="group">{p.shown.map((f) => <FileRow key={f.path} f={f} onOpen={setOpen} />)}</div>
                </section>
              ))}
              <div style={{ height: '40px' }} />
            </>
          )}
        </div>
      </div>
      <Editor path={open} onClose={() => setOpen(null)} onChanged={load} />
    </div>
  )
}

function FileRow({ f, label, onOpen }: { f: MemoryFile; label?: string; onOpen: (p: string) => void }) {
  return (
    <button class="row" onClick={() => onOpen(f.path)}>
      <IconFile width={18} height={18} class="dir-icon" />
      <span class="label">
        <span class="session-title">{label || f.title || f.name}{f.type && <span class={`mem-type t-${f.type}`}>{f.type}</span>}</span>
        {(f.description || f.name === 'MEMORY.md') && <span class="hint">{f.description || 'Index loaded into every session'}</span>}
      </span>
      <span class="session-meta">{relTime(f.mtime)}</span>
    </button>
  )
}

function Editor({ path, onClose, onChanged }: { path: string | null; onClose: () => void; onChanged: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [orig, setOrig] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setText(null)
    if (path) api.memoryFile(path).then((r) => { setText(r.content); setOrig(r.content) }).catch((e) => { toastError(e); onClose() })
  }, [path])

  const close = async () => {
    if (text !== null && text !== orig && !(await confirmDialog({ title: 'Discard changes?', confirm: 'Discard', danger: true }))) return
    onClose()
  }
  const save = async () => {
    if (!path || text === null) return
    setSaving(true)
    try { const r = await api.putMemoryFile(path, text); setOrig(r.content); toast('Saved'); onChanged() } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  const remove = async () => {
    if (!path || !(await confirmDialog({ title: 'Delete this memory?', body: path.split('/').pop(), confirm: 'Delete', danger: true }))) return
    try { await api.deleteMemoryFile(path); onClose(); onChanged() } catch (e) { toastError(e) }
  }

  return (
    <Sheet open={!!path} onClose={close} title={<span class="mono-label">{path?.split('/').pop()}</span>}
      actions={path !== 'CLAUDE.md' && <button class="icon-btn" aria-label="Delete" onClick={remove}><IconTrash width={18} height={18} /></button>}>
      {text === null ? <div class="skeleton" style={{ height: '300px' }} /> : (
        <>
          <textarea class="textarea mono config-editor" rows={16} spellcheck={false} value={text}
            onInput={(e) => setText((e.target as HTMLTextAreaElement).value)} />
          <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
            <button class="btn small" disabled={text === orig} onClick={() => setText(orig)}>Revert</button>
            <button class="btn small primary" disabled={saving || text === orig} onClick={save}>{saving ? <span class="spinner" /> : 'Save'}</button>
          </div>
        </>
      )}
    </Sheet>
  )
}
