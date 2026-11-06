// Create or edit an ACP agent: identity, endpoint (host, port, token), default options, subagent permission.

import { useEffect, useRef, useState } from 'preact/hooks'
import { acpVersion, toast, toastError } from '../../lib/store'
import { back, navigate } from '../../lib/router'
import { CRAB_COLORS, Crab, Spark } from '../../components/crab'
import { BackButton, Switch, TopBar, confirmDialog, useScrolled } from '../../components/ui'
import { IconBolt, IconTrash } from '../../components/icons'
import { acpApi, type AcpAgent, type ConfigOption } from './api'
import { AcpAvatar } from './chat/Chat'

const BLANK: Partial<AcpAgent> = { name: '', avatar: 'crab:blue', description: '', group: '', host: '', port: 8788, token: '', cwd: '/', config_defaults: {}, as_subagent: false }

export function AcpAgentSettings({ agentId }: { agentId?: string }) {
  const isNew = !agentId
  const { scrolled, onScroll, ref } = useScrolled()
  const [a, setA] = useState<Partial<AcpAgent> | null>(isNew ? { ...BLANK } : null)
  const [orig, setOrig] = useState(isNew ? '' : '')
  const [groups, setGroups] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [tested, setTested] = useState<{ ok: boolean; error?: string; options?: ConfigOption[]; info?: AcpAgent['info'] } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!isNew) acpApi.agent(agentId!).then((x) => { setA(x); setOrig(JSON.stringify(x)) }).catch(toastError)
    acpApi.groups().then((g) => setGroups(g.groups)).catch(() => {})
  }, [agentId])

  if (!a) return (
    <div class="page">
      <TopBar left={<BackButton onClick={() => back()} />} title="ACP agent" />
      <div class="container"><div class="skeleton" style={{ height: '300px', marginTop: '20px', borderRadius: '20px' }} /></div>
    </div>
  )
  const set = <K extends keyof AcpAgent>(k: K, v: AcpAgent[K]) => setA({ ...a, [k]: v })
  const dirty = isNew || JSON.stringify(a) !== orig

  const save = async () => {
    if (!a.name?.trim()) return toast('Give the agent a name', 'error')
    if (!a.host?.trim() || !a.port) return toast('Host and port are required', 'error')
    const body: Partial<AcpAgent> = { ...a }
    delete body.status; delete body.info
    setSaving(true)
    try {
      const saved = isNew ? await acpApi.create(body) : await acpApi.update(agentId!, body)
      acpVersion.value++
      toast(isNew ? 'Agent added' : 'Saved')
      if (isNew) navigate({ name: 'acp', agentId: saved.id }, { replace: true })
      else { setA(saved); setOrig(JSON.stringify(saved)) }
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  const test = async () => {
    if (isNew || dirty) return toast('Save first, then test the connection', 'error')
    setTesting(true); setTested(null)
    try { setTested(await acpApi.test(agentId!)) } catch (e) { toastError(e) } finally { setTesting(false) }
  }
  const remove = async () => {
    if (!await confirmDialog({ title: `Delete ${a.name}?`, body: 'The agent and its conversation list are removed from next-agent.', confirm: 'Delete agent', danger: true })) return
    try { await acpApi.remove(agentId!); acpVersion.value++; toast('Agent deleted'); navigate({ name: 'home' }, { replace: true }) } catch (e) { toastError(e) }
  }
  const onAvatarFile = async (e: Event) => {
    const f = (e.target as HTMLInputElement).files?.[0]
    ;(e.target as HTMLInputElement).value = ''
    if (!f) return
    if (isNew) return toast('Save the agent first, then upload a picture', 'error')
    try { const saved = await acpApi.uploadAvatar(agentId!, f); setA({ ...a, avatar: saved.avatar, order: saved.order }); toast('Avatar updated') } catch (err) { toastError(err) }
  }
  const options = tested?.options || []
  const defaults = a.config_defaults || {}

  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label={isNew ? 'Cancel' : 'Back'} onClick={() => back()} />}
        right={<button class="btn primary small" disabled={saving || !dirty} onClick={save}>{saving ? <span class="spinner" /> : isNew ? 'Add' : 'Save'}</button>}>
        <span class="topbar-center">{isNew ? 'New ACP agent' : 'ACP agent'}</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">
          <div class="avatar-editor rise">
            <AcpAvatar a={{ id: agentId || 'new', avatar: a.avatar || 'crab:blue', order: a.order || 0 }} size={92} />
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
              <input class="input" value={a.name} placeholder="Phone agent" onInput={(e) => set('name', (e.target as HTMLInputElement).value)} />
            </label>
            {isNew && <label class="field"><span class="flabel">ID</span>
              <input class="input mono" value={a.id || ''} autocapitalize="off" spellcheck={false} maxLength={40} placeholder="derived from name"
                onInput={(e) => set('id', (e.target as HTMLInputElement).value.toLowerCase())} />
              <span class="fhint">Lowercase letters, digits and -. It can't be changed later.</span>
            </label>}
            <label class="field"><span class="flabel">Description</span>
              <input class="input" value={a.description} placeholder="What this agent is for" onInput={(e) => set('description', (e.target as HTMLInputElement).value)} />
            </label>
            {groups.length > 0 && <div class="field"><span class="flabel">Group</span>
              <div class="chips" role="radiogroup">
                {['', ...groups].map((g) => (
                  <button key={g || '_none'} type="button" role="radio" aria-checked={(a.group || '') === g}
                    class={`chip ${(a.group || '') === g ? 'pink' : ''}`} onClick={() => set('group', g)}>{g || 'None'}</button>
                ))}
              </div>
            </div>}
          </div>

          <div class="group-title">Endpoint</div>
          <div class="group">
            <div class="field-row">
              <label class="field" style={{ flex: 2 }}><span class="flabel">Host</span>
                <input class="input mono" value={a.host} placeholder="mi-10 or 100.64.0.2" autocapitalize="off" spellcheck={false} onInput={(e) => set('host', (e.target as HTMLInputElement).value.trim())} />
              </label>
              <label class="field" style={{ flex: 1 }}><span class="flabel">Port</span>
                <input class="input mono" type="number" min={1} max={65535} value={a.port} onInput={(e) => set('port', Number((e.target as HTMLInputElement).value))} />
              </label>
            </div>
            <label class="field"><span class="flabel">Token</span>
              <input class="input mono" type="password" value={a.token || ''} autocomplete="off" autocapitalize="off" spellcheck={false}
                placeholder="Optional" onInput={(e) => set('token', (e.target as HTMLInputElement).value)} />
              <span class="fhint">Sent as the first line, AUTH &lt;token&gt;, when the connection opens.</span>
            </label>
            <label class="field"><span class="flabel">Working directory on the agent</span>
              <input class="input mono" value={a.cwd} placeholder="/" autocapitalize="off" spellcheck={false} onInput={(e) => set('cwd', (e.target as HTMLInputElement).value)} />
            </label>
            {!isNew && (
              <div class="field">
                <button type="button" class="btn small" disabled={testing} onClick={test}>{testing ? <Spark size={16} /> : <IconBolt width={16} height={16} />} Test connection</button>
                {tested && <span class={`fhint ${tested.ok ? '' : 'err'}`}>{tested.ok ? `Connected: ${tested.info?.title || tested.info?.name || 'agent'}${tested.info?.version ? ` ${tested.info.version}` : ''}` : tested.error}</span>}
              </div>
            )}
          </div>

          {options.length > 0 && <>
            <div class="group-title">Defaults for new chats</div>
            <div class="group">
              {options.map((o) => (
                <div key={o.id} class="field"><span class="flabel">{o.name}</span>
                  <div class="chips">
                    {[{ value: '', name: 'Agent default' }, ...o.options].map((v) => (
                      <button key={v.value} type="button" class={`chip ${(defaults[o.id] || '') === v.value ? 'pink' : ''}`}
                        onClick={() => { const d = { ...defaults }; if (v.value) d[o.id] = v.value; else delete d[o.id]; set('config_defaults', d) }}>{v.name}</button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </>}
          {!options.length && Object.keys(defaults).length > 0 && <p class="fhint" style={{ padding: '10px 4px 0' }}>Defaults set: {Object.entries(defaults).map(([k, v]) => `${k} = ${v}`).join(', ')}. Test the connection to change them.</p>}

          <div class="group-title">Collaboration</div>
          <div class="group">
            <div class="row">
              <span class="label">Available as a subagent<span class="hint">Claude agents with the collaboration tools turned on can hand tasks to this agent.</span></span>
              <Switch on={!!a.as_subagent} onChange={(v) => set('as_subagent', v)} label="Available as a subagent" />
            </div>
          </div>

          {!isNew && <button class="btn danger block" style={{ marginTop: '28px' }} onClick={remove}><IconTrash width={18} height={18} /> Delete agent</button>}
        </div>
      </div>
    </div>
  )
}
