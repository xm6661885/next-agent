// Create or edit a chat assistant: identity, model, effort, prompt, temperature, MCP servers.
// The built-in assistant (_default) has the same page without the ID and delete.

import { useEffect, useRef, useState } from 'preact/hooks'
import { chatVersion, toast, toastError } from '../../lib/store'
import { back, navigate } from '../../lib/router'
import { CRAB_COLORS, Crab } from '../../components/crab'
import { BackButton, Switch, TopBar, confirmDialog, useScrolled } from '../../components/ui'
import { IconTrash } from '../../components/icons'
import { DEFAULT_ASSISTANT, EFFORTS, chatApi, modelLabel, type Assistant, type ChatMeta } from './api'
import { AssistantAvatar } from './chat/Chat'

const BLANK: Partial<Assistant> = { name: '', avatar: 'crab:pink', description: '', model: '', effort: '', system_prompt: '', temperature: -1, mcp: [] }

export function AssistantSettings({ assistantId }: { assistantId?: string }) {
  const isNew = !assistantId
  const builtin = assistantId === DEFAULT_ASSISTANT
  const { scrolled, onScroll, ref } = useScrolled()
  const [a, setA] = useState<Partial<Assistant> | null>(isNew ? { ...BLANK } : null)
  const [orig, setOrig] = useState('')
  const [meta, setMeta] = useState<ChatMeta | null>(null)
  const [saving, setSaving] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!isNew) chatApi.assistant(assistantId!).then((x) => { setA(x); setOrig(JSON.stringify(x)) }).catch(toastError)
    chatApi.meta().then(setMeta).catch(() => {})
  }, [assistantId])

  if (!a) return (
    <div class="page">
      <TopBar left={<BackButton onClick={() => back()} />} title="Assistant" />
      <div class="container"><div class="skeleton" style={{ height: '300px', marginTop: '20px', borderRadius: '20px' }} /></div>
    </div>
  )
  const set = <K extends keyof Assistant>(k: K, v: Assistant[K]) => setA({ ...a, [k]: v })
  const dirty = isNew || JSON.stringify(a) !== orig
  const d = meta?.defaults

  const save = async () => {
    if (!a.name?.trim()) return toast('Give the assistant a name', 'error')
    const body: Partial<Assistant> = { ...a }
    delete body.status
    setSaving(true)
    try {
      const saved = isNew ? await chatApi.create(body) : await chatApi.update(assistantId!, body)
      chatVersion.value++
      toast(isNew ? 'Assistant created' : 'Saved')
      if (isNew) navigate({ name: 'assistant', assistantId: saved.id }, { replace: true })
      else { setA(saved); setOrig(JSON.stringify(saved)) }
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  const remove = async () => {
    if (!await confirmDialog({ title: `Delete ${a.name}?`, body: 'The assistant and all of its conversations are deleted.', confirm: 'Delete assistant', danger: true })) return
    try { await chatApi.remove(assistantId!); chatVersion.value++; toast('Assistant deleted'); navigate({ name: 'chats' }, { replace: true }) } catch (e) { toastError(e) }
  }
  const onAvatarFile = async (e: Event) => {
    const f = (e.target as HTMLInputElement).files?.[0]
    ;(e.target as HTMLInputElement).value = ''
    if (!f) return
    if (isNew) return toast('Create the assistant first, then upload a picture', 'error')
    try { const saved = await chatApi.uploadAvatar(assistantId!, f); setA({ ...a, avatar: saved.avatar, order: saved.order }); toast('Avatar updated') } catch (err) { toastError(err) }
  }
  const globalMcp = d?.mcp || []
  const toggleMcp = (id: string, on: boolean) => set('mcp', on ? [...(a.mcp || []), id] : (a.mcp || []).filter((x) => x !== id))

  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label={isNew ? 'Cancel' : 'Back'} onClick={() => back()} />}
        right={<button class="btn primary small" disabled={saving || !dirty} onClick={save}>{saving ? <span class="spinner" /> : isNew ? 'Create' : 'Save'}</button>}>
        <span class="topbar-center">{isNew ? 'New assistant' : 'Assistant'}</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">
          <div class="avatar-editor rise">
            <AssistantAvatar a={{ id: assistantId || 'new', avatar: a.avatar || 'crab:pink', order: a.order || 0 }} size={92} />
            <div class="crab-swatches">
              {Object.entries(CRAB_COLORS).map(([k, c]) => (
                <button key={k} type="button" class={`swatch ${a.avatar === `crab:${k}` ? 'on' : ''}`} style={{ background: c.bg }} aria-label={`${k} crab`} onClick={() => set('avatar', `crab:${k}`)}>
                  <Crab color={c.body} />
                </button>
              ))}
              <button type="button" class={`swatch upload ${a.avatar === 'file' ? 'on' : ''}`} onClick={() => fileRef.current?.click()}>Photo</button>
              <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={onAvatarFile} />
            </div>
          </div>

          <div class="group-title">Identity</div>
          <div class="group">
            <label class="field"><span class="flabel">Name</span>
              <input class="input" value={a.name} placeholder="Writer" onInput={(e) => set('name', (e.target as HTMLInputElement).value)} />
            </label>
            {isNew && <label class="field"><span class="flabel">ID</span>
              <input class="input mono" value={a.id || ''} autocapitalize="off" spellcheck={false} maxLength={40} placeholder="derived from name"
                onInput={(e) => set('id', (e.target as HTMLInputElement).value.toLowerCase())} />
              <span class="fhint">Lowercase letters, digits and -. It can't be changed later.</span>
            </label>}
            <label class="field"><span class="flabel">Description</span>
              <input class="input" value={a.description} placeholder={builtin ? 'Quick chats' : 'What this assistant is for'} onInput={(e) => set('description', (e.target as HTMLInputElement).value)} />
            </label>
          </div>

          <div class="group-title">Model</div>
          <div class="group">
            <div class="field"><span class="flabel">Model</span>
              <select class="input" value={a.model} onChange={(e) => set('model', (e.target as HTMLSelectElement).value)}>
                <option value="">Default{d?.model ? ` (${modelLabel(d.model)})` : ''}</option>
                {(meta?.models || []).map((m) => <option key={m.id} value={m.id}>{m.model} · {m.provider}</option>)}
              </select>
            </div>
            <div class="field"><span class="flabel">Thinking</span>
              <div class="chips">
                {(['', ...EFFORTS] as const).map((e) => (
                  <button key={e || '_d'} type="button" class={`chip ${(a.effort || '') === e ? 'pink' : ''}`} onClick={() => set('effort', e)}>{e || `Default (${d?.effort || 'medium'})`}</button>
                ))}
              </div>
            </div>
            <label class="field"><span class="flabel">Temperature</span>
              <input class="input mono" type="number" step="0.1" min={-1} max={2} value={a.temperature}
                onInput={(e) => set('temperature', Number((e.target as HTMLInputElement).value))} />
              <span class="fhint">-1 uses the global default. Most providers accept 0 to 2.</span>
            </label>
          </div>

          <div class="group-title">System prompt</div>
          <div class="group">
            <label class="field">
              <textarea class="input" rows={6} value={a.system_prompt} placeholder={d?.system_prompt ? `Empty uses the default: ${d.system_prompt.slice(0, 80)}` : 'You are a helpful assistant.'}
                onInput={(e) => set('system_prompt', (e.target as HTMLTextAreaElement).value)} />
            </label>
          </div>

          {(meta?.mcp_servers.length || 0) > 0 && <>
            <div class="group-title">MCP servers</div>
            <div class="group">
              {meta!.mcp_servers.map((id) => {
                const always = globalMcp.includes(id)
                return (
                  <div key={id} class="row">
                    <span class="label">{id}<span class="hint">{always ? 'On for every assistant (Settings, Chat, MCP)' : 'Available in this assistant\'s chats'}</span></span>
                    <Switch on={always || (a.mcp || []).includes(id)} onChange={(v) => !always && toggleMcp(id, v)} label={id} />
                  </div>
                )
              })}
            </div>
            <p class="fhint" style={{ padding: '8px 4px 0' }}>Each chat can still turn servers off from the composer.</p>
          </>}

          {!isNew && !builtin && <button class="btn danger block" style={{ marginTop: '28px' }} onClick={remove}><IconTrash width={18} height={18} /> Delete assistant</button>}
        </div>
      </div>
    </div>
  )
}
