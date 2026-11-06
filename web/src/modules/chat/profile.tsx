// The user's own name and picture in chats ([profile] in chat.toml).

import { useEffect, useRef, useState } from 'preact/hooks'
import { chatVersion, toast, toastError } from '../../lib/store'
import { Sheet } from '../../components/ui'
import { IconChevron } from '../../components/icons'
import { CRAB_COLORS, Crab } from '../../components/crab'
import { chatApi, type Profile } from './api'

export function UserAvatar({ p, size }: { p: Profile; size: number }) {
  const style = { width: `${size}px`, height: `${size}px` }
  if (p.avatar === 'file') return <span class="avatar" style={style}><img src={chatApi.profileAvatarUrl(p)} alt="" loading="lazy" decoding="async" /></span>
  if (p.avatar.startsWith('crab:')) {
    const c = CRAB_COLORS[p.avatar.slice(5)] || CRAB_COLORS.pink
    return <span class="avatar" style={{ ...style, background: c.bg }}><Crab color={c.body} /></span>
  }
  return <span class="avatar user-initial" style={{ ...style, fontSize: `${Math.round(size * 0.42)}px` }}>{(p.name || 'You').trim().slice(0, 1).toUpperCase()}</span>
}

/** Settings home: the chat profile as a card; tap to edit it in the profile sheet. */
export function ProfileCard() {
  const [p, setP] = useState<Profile | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => { chatApi.config().then((c) => setP(c.profile)).catch(() => {}) }, [chatVersion.value])
  const save = async (next: Profile) => {
    try {
      const c = await chatApi.saveConfig({ profile: next })
      setP(c.profile); chatVersion.value++; toast('Settings saved')
      return true
    } catch (e) { toastError(e); return false }
  }
  return (
    <>
      <div class="group">
        <button type="button" class="row press" disabled={!p} onClick={() => setOpen(true)}>
          {p ? <UserAvatar p={p} size={44} /> : <span class="skeleton" style={{ width: '44px', height: '44px', borderRadius: '50%' }} />}
          <span class="label">{p?.name || 'You'}<span class="hint">Your name and avatar in chats</span></span>
          <IconChevron class="chev" />
        </button>
      </div>
      {p && <ProfileSheet open={open} p={p} onSave={save} onClose={() => setOpen(false)} />}
    </>
  )
}

export function ProfileSheet({ open, p, onSave, onClose }: { open: boolean; p: Profile; onSave: (p: Profile) => Promise<boolean>; onClose: () => void }) {
  const [d, setD] = useState(p)
  const [saving, setSaving] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  useEffect(() => { if (open) setD(p) }, [open])
  const upload = async (e: Event) => {
    const f = (e.target as HTMLInputElement).files?.[0]
    ;(e.target as HTMLInputElement).value = ''
    if (!f) return
    try { const r = await chatApi.uploadProfileAvatar(f); setD((x) => ({ ...x, avatar: r.profile.avatar })); toast('Picture uploaded') } catch (err) { toastError(err) }
  }
  const submit = async () => {
    if (!d.name.trim()) return toast('Name is required', 'error')
    setSaving(true)
    const ok = await onSave({ ...d, name: d.name.trim() })
    setSaving(false)
    if (ok) onClose()
  }
  return (
    <Sheet open={open} onClose={onClose} title="You"
      actions={<button class="btn primary small" disabled={saving} onClick={submit}>{saving ? <span class="spinner" /> : 'Save'}</button>}>
      <div class="avatar-editor">
        <UserAvatar p={d} size={80} />
        <div class="crab-swatches">
          <button type="button" class={`swatch initial ${d.avatar === '' ? 'on' : ''}`} onClick={() => setD({ ...d, avatar: '' })}>{(d.name || 'Y').slice(0, 1).toUpperCase()}</button>
          {Object.entries(CRAB_COLORS).map(([k, c]) => (
            <button key={k} type="button" class={`swatch ${d.avatar === `crab:${k}` ? 'on' : ''}`} style={{ background: c.bg }} aria-label={`${k} crab`} onClick={() => setD({ ...d, avatar: `crab:${k}` })}><Crab color={c.body} /></button>
          ))}
          <button type="button" class={`swatch upload ${d.avatar === 'file' ? 'on' : ''}`} onClick={() => file.current?.click()}>Photo</button>
          <input ref={file} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={upload} />
        </div>
      </div>
      <div class="group">
        <label class="field"><span class="flabel">Name</span>
          <input class="input" value={d.name} maxLength={40} placeholder="You" onInput={(e) => setD({ ...d, name: (e.target as HTMLInputElement).value })} />
        </label>
      </div>
      <p class="fhint">Shown next to your messages in every chat.</p>
    </Sheet>
  )
}
