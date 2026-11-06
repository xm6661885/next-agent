// Assistant memory: short notes injected into every chat with this assistant.

import { useEffect, useState } from 'preact/hooks'
import { chatVersion, toastError } from '../../lib/store'
import { back } from '../../lib/router'
import { BackButton, Sheet, TopBar, confirmDialog, promptDialog, useScrolled } from '../../components/ui'
import { IconBrain, IconMore, IconPlus, IconTrash } from '../../components/icons'
import { relTime } from '../../lib/util'
import { chatApi, type Assistant, type Memory } from './api'

export function MemoryPage({ assistantId }: { assistantId: string }) {
  const { scrolled, onScroll, ref } = useScrolled()
  const [a, setA] = useState<Assistant | null>(null)
  const [list, setList] = useState<Memory[] | null>(null)
  const [edit, setEdit] = useState<Memory | null>(null)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [menu, setMenu] = useState(false)
  // Every chat_changed event bumps chatVersion, including the memory scope for this assistant.
  useEffect(() => { chatApi.assistant(assistantId).then(setA).catch(toastError) }, [assistantId])
  useEffect(() => { chatApi.memories(assistantId).then(setList).catch(toastError) }, [assistantId, chatVersion.value])
  const name = a?.name || 'the assistant'

  const add = async () => {
    const t = (await promptDialog({ title: 'Add to memory', placeholder: 'Something to remember', confirm: 'Add' }))?.trim()
    if (!t) return
    try { const m = await chatApi.addMemory(assistantId, t); setList((l) => [...(l || []).filter((x) => x.id !== m.id), m]) } catch (e) { toastError(e) }
  }
  const openEdit = (m: Memory) => { setEdit(m); setDraft(m.text) }
  const save = async () => {
    if (!edit || !draft.trim()) return
    setSaving(true)
    try { const m = await chatApi.updateMemory(assistantId, edit.id, draft.trim()); setList((l) => l && l.map((x) => x.id === m.id ? m : x)); setEdit(null) } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  const remove = async (m: Memory) => {
    setEdit(null)
    if (!await confirmDialog({ title: 'Delete this memory?', body: m.text.slice(0, 120), confirm: 'Delete', danger: true })) return
    try { await chatApi.deleteMemory(assistantId, m.id); setList((l) => l && l.filter((x) => x.id !== m.id)) } catch (e) { toastError(e) }
  }
  const clear = async () => {
    setMenu(false)
    if (!await confirmDialog({ title: 'Clear all memory?', body: `${name} forgets everything saved here.`, confirm: 'Clear all', danger: true })) return
    try { await chatApi.clearMemory(assistantId); setList([]) } catch (e) { toastError(e) }
  }

  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label={name} onClick={() => back({ name: 'assistant', assistantId })} />}
        right={<div class="topbar-actions">
          {!!list?.length && <button class="icon-btn" aria-label="More" onClick={() => setMenu(true)}><IconMore /></button>}
          <button class="icon-btn" aria-label="Add memory" onClick={add}><IconPlus /></button>
        </div>}>
        {scrolled && <span class="topbar-center fade-in">Memory</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Memory</h1>
          <p class="subtitle rise" style={{ '--i': 1 }}>What {name} remembers across chats.</p>
          {list === null ? (
            <div class="group">{[0, 1].map((i) => <div key={i} class="row"><div class="skeleton" style={{ height: '36px', flex: 1 }} /></div>)}</div>
          ) : list.length === 0 ? (
            <div class="empty rise" style={{ padding: '28px 20px' }}>
              <IconBrain width={30} height={30} style={{ color: 'var(--text-3)' }} />
              <p style={{ margin: '8px 0 0' }}>Memory is a list of short notes that {name} reads at the start of every chat. It saves useful facts and preferences by itself while you talk, and you can add your own with the plus button.</p>
            </div>
          ) : (
            <div class="group">
              {list.map((m) => (
                <div key={m.id} class="session-row">
                  <button class="row" onClick={() => openEdit(m)}>
                    <span class="label"><span class="mem-text">{m.text}</span>
                      <span class="hint">{m.source === 'assistant' ? `Saved by ${name}` : 'Added by you'} · {relTime(m.updated_at)}</span></span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <Sheet open={!!edit} onClose={() => setEdit(null)} title="Edit memory"
        actions={<button class="btn primary small" disabled={saving || !draft.trim() || draft.trim() === edit?.text} onClick={save}>{saving ? <span class="spinner" /> : 'Save'}</button>}>
        <label class="field"><textarea class="input" rows={5} maxLength={1000} value={draft} onInput={(e) => setDraft((e.target as HTMLTextAreaElement).value)} /></label>
        {edit && <button class="btn danger block" style={{ marginTop: '14px' }} onClick={() => remove(edit)}><IconTrash width={18} height={18} /> Delete</button>}
      </Sheet>
      <Sheet open={menu} onClose={() => setMenu(false)} title="Memory">
        <div class="menu"><button class="danger" onClick={clear}><IconTrash /> Clear all</button></div>
      </Sheet>
    </div>
  )
}
