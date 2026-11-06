// Create or edit a More Agent: identity, endpoint (ACP) or command (Codex), defaults, subagent permission.

import { useEffect, useRef, useState } from 'preact/hooks'
import { moreAgentsVersion, toast, toastError } from '../../lib/store'
import { back, navigate } from '../../lib/router'
import { CRAB_COLORS, Crab, Spark } from '../../components/crab'
import { BackButton, SecretInput, Switch, TopBar, confirmDialog, useScrolled } from '../../components/ui'
import { IconBolt, IconTrash } from '../../components/icons'
import { moreAgentsApi, type MoreAgent, type AcpAgent, type CodexAgent, type ConfigOption, type Model } from './api'
import { MoreAgentAvatar } from './chat/Chat'
import { ModelPicker } from '../../components/ModelPicker'
import { EffortSlider } from '../../components/EffortSlider'
import { DirPicker } from '../../components/DirPicker'

const BLANK_ACP: Partial<AcpAgent> = { kind: 'acp', name: '', avatar: 'crab:blue', description: '', group: '', host: '', port: 8788, token: '', cwd: '/', config_defaults: {}, as_subagent: false }
const BLANK_CODEX: Partial<CodexAgent> = { kind: 'codex', name: '', avatar: 'crab:blue', description: '', group: '', command: 'codex', args: [], env: {}, cwd: '~', model: '', effort: '', mode: 'full-access', instructions: '', as_subagent: false }

export function MoreAgentSettings({ agentId }: { agentId?: string }) {
  const isNew = !agentId
  const { scrolled, onScroll, ref } = useScrolled()
  const [a, setA] = useState<Partial<MoreAgent> | null>(null)
  const [orig, setOrig] = useState(isNew ? '' : '')
  const [groups, setGroups] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [tested, setTested] = useState<{ ok: boolean; error?: string; options?: ConfigOption[]; info?: AcpAgent['info']; models?: Model[] } | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [dirPicker, setDirPicker] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!isNew) {
      moreAgentsApi.agent(agentId!).then((x) => { setA(x); setOrig(JSON.stringify(x)); if (x.kind === 'codex') loadModels(agentId!) }).catch(toastError)
    } else {
      // Read ?kind= query param and initialize
      const query = new URLSearchParams(window.location.search)
      const kind = query.get('kind') as 'acp' | 'codex' | null
      if (kind === 'codex') setA({ ...BLANK_CODEX })
      else setA({ ...BLANK_ACP })
    }
    moreAgentsApi.groups().then((g) => setGroups(g.groups)).catch(() => {})
  }, [agentId])

  const loadModels = (id: string) => {
    moreAgentsApi.models(id).then(setModels).catch(() => {})
  }

  if (!a) return (
    <div class="page">
      <TopBar left={<BackButton onClick={() => back()} />} title="Agent" />
      <div class="container"><div class="skeleton" style={{ height: '300px', marginTop: '20px', borderRadius: '20px' }} /></div>
    </div>
  )
  const set = (k: string, v: any) => setA({ ...a, [k]: v })
  const dirty = isNew || JSON.stringify(a) !== orig

  const save = async () => {
    if (!a.name?.trim()) return toast('Give the agent a name', 'error')
    if (a.kind === 'acp') {
      const acp = a as Partial<AcpAgent>
      if (!acp.host?.trim() || !acp.port) return toast('Host and port are required', 'error')
    }
    const body: Partial<MoreAgent> = { ...a }
    delete body.status; delete body.info
    setSaving(true)
    try {
      const saved = isNew ? await moreAgentsApi.create(body as any) : await moreAgentsApi.update(agentId!, body)
      moreAgentsVersion.value++
      toast(isNew ? 'Agent added' : 'Saved')
      if (isNew) navigate({ name: 'more-agent', agentId: saved.id }, { replace: true })
      else { setA(saved); setOrig(JSON.stringify(saved)) }
    } catch (e) { toastError(e) } finally { setSaving(false) }
  }
  const test = async () => {
    if (isNew || dirty) return toast('Save first, then test the connection', 'error')
    setTesting(true); setTested(null)
    try {
      const result = await moreAgentsApi.test(agentId!)
      setTested(result)
      if (result.models) setModels(result.models)
    } catch (e) { toastError(e) } finally { setTesting(false) }
  }
  const remove = async () => {
    if (!await confirmDialog({ title: `Delete ${a.name}?`, body: 'The agent and its conversation list are removed from next-agent.', confirm: 'Delete agent', danger: true })) return
    try { await moreAgentsApi.remove(agentId!); moreAgentsVersion.value++; toast('Agent deleted'); navigate({ name: 'home' }, { replace: true }) } catch (e) { toastError(e) }
  }
  const onAvatarFile = async (e: Event) => {
    const f = (e.target as HTMLInputElement).files?.[0]
    ;(e.target as HTMLInputElement).value = ''
    if (!f) return
    if (isNew) return toast('Save the agent first, then upload a picture', 'error')
    try { const saved = await moreAgentsApi.uploadAvatar(agentId!, f); setA({ ...a, avatar: saved.avatar, order: saved.order }); toast('Avatar updated') } catch (err) { toastError(err) }
  }

  const options = tested?.options || []
  const kind = a.kind || 'acp'
  const acp = kind === 'acp' ? (a as Partial<AcpAgent>) : null
  const codex = kind === 'codex' ? (a as Partial<CodexAgent>) : null

  // Model picker for Codex
  const currentModel = codex ? models.find((m) => m.id === codex.model) : null
  const currentEffort = codex?.effort || currentModel?.defaultReasoningEffort || ''

  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label={isNew ? 'Cancel' : 'Back'} onClick={() => back()} />}
        right={<button class="btn primary small" disabled={saving || !dirty} onClick={save}>{saving ? <span class="spinner" /> : isNew ? 'Add' : 'Save'}</button>}>
        <span class="topbar-center">{isNew ? 'New agent' : 'Agent settings'}</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container settings">
          <div class="avatar-editor rise">
            <MoreAgentAvatar a={{ id: agentId || 'new', avatar: a.avatar || 'crab:blue', order: a.order || 0 }} size={92} />
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

          {isNew && (
            <div class="group">
              <div class="field">
                <span class="flabel">Agent type</span>
                <div class="chips" role="radiogroup">
                  <button type="button" role="radio" aria-checked={kind === 'acp'} class={`chip ${kind === 'acp' ? 'pink' : ''}`}
                    onClick={() => setA({ ...BLANK_ACP, name: a.name, description: a.description, group: a.group })}>ACP</button>
                  <button type="button" role="radio" aria-checked={kind === 'codex'} class={`chip ${kind === 'codex' ? 'pink' : ''}`}
                    onClick={() => setA({ ...BLANK_CODEX, name: a.name, description: a.description, group: a.group })}>Codex</button>
                </div>
              </div>
            </div>
          )}

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

          {acp && (
            <>
              <div class="group-title">Endpoint</div>
              <div class="group">
                <div class="field-row">
                  <label class="field" style={{ flex: 2 }}><span class="flabel">Host</span>
                    <input class="input mono" value={acp.host} placeholder="mi-10 or 100.64.0.2" autocapitalize="off" spellcheck={false} onInput={(e) => set('host', (e.target as HTMLInputElement).value.trim())} />
                  </label>
                  <label class="field" style={{ flex: 1 }}><span class="flabel">Port</span>
                    <input class="input mono" type="number" min={1} max={65535} value={acp.port} onInput={(e) => set('port', Number((e.target as HTMLInputElement).value))} />
                  </label>
                </div>
                <label class="field"><span class="flabel">Token</span>
                  <SecretInput value={acp.token || ''} placeholder="Optional" label="token" onInput={(v) => set('token', v)} />
                  <span class="fhint">Sent as the first line, AUTH &lt;token&gt;, when the connection opens.</span>
                </label>
                <label class="field"><span class="flabel">Working directory on the agent</span>
                  <input class="input mono" value={acp.cwd} placeholder="/" autocapitalize="off" spellcheck={false} onInput={(e) => set('cwd', (e.target as HTMLInputElement).value)} />
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
                  {options.map((o) => {
                    const defaults = acp.config_defaults || {}
                    return (
                      <div key={o.id} class="field"><span class="flabel">{o.name}</span>
                        <div class="chips">
                          {[{ value: '', name: 'Agent default' }, ...o.options].map((v) => (
                            <button key={v.value} type="button" class={`chip ${(defaults[o.id] || '') === v.value ? 'pink' : ''}`}
                              onClick={() => { const d = { ...defaults }; if (v.value) d[o.id] = v.value; else delete d[o.id]; set('config_defaults', d) }}>{v.name}</button>
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </>}
              {!options.length && acp.config_defaults && Object.keys(acp.config_defaults).length > 0 && <p class="fhint" style={{ padding: '10px 4px 0' }}>Defaults set: {Object.entries(acp.config_defaults).map(([k, v]) => `${k} = ${v}`).join(', ')}. Test the connection to change them.</p>}
            </>
          )}

          {codex && (
            <>
              <div class="group-title">Command</div>
              <div class="group">
                <label class="field"><span class="flabel">Command</span>
                  <input class="input mono" value={codex.command} placeholder="codex" autocapitalize="off" spellcheck={false} onInput={(e) => set('command', (e.target as HTMLInputElement).value)} />
                </label>
                <label class="field"><span class="flabel">Arguments</span>
                  <input class="input mono" value={(codex.args || []).join(' ')} placeholder="Extra app-server arguments"
                    autocapitalize="off" spellcheck={false} onInput={(e) => set('args', (e.target as HTMLInputElement).value.split(' ').filter(Boolean))} />
                  <span class="fhint">Separate with spaces. These are passed to the app-server.</span>
                </label>
                <label class="field"><span class="flabel">Environment</span>
                  <textarea class="input mono" rows={3} value={Object.entries(codex.env || {}).map(([k, v]) => `${k}=${v}`).join('\n')} placeholder="KEY=value, one per line"
                    autocapitalize="off" spellcheck={false} onInput={(e) => {
                      const lines = (e.target as HTMLTextAreaElement).value.split('\n')
                      const env: Record<string, string> = {}
                      for (const l of lines) {
                        const [k, ...v] = l.split('=')
                        if (k.trim()) env[k.trim()] = v.join('=')
                      }
                      set('env', env)
                    }} />
                </label>
                <div class="field"><span class="flabel">Working directory</span>
                  <div class="field-row">
                    <input class="input mono" value={codex.cwd} readonly placeholder="~" style={{ flex: 1 }} />
                    <button type="button" class="btn small" onClick={() => setDirPicker(true)}>Browse</button>
                  </div>
                </div>
              </div>

              <div class="group-title">Model</div>
              <div class="group">
                <div class="field"><span class="flabel">Model</span>
                  <ModelPicker value={codex.model || ''} onChange={(m) => set('model', m)} noneLabel="Default" />
                </div>
              </div>

              <div class="group-title">Reasoning</div>
              <div class="group">
                <div class="field"><span class="flabel">Effort</span>
                  <EffortSlider value={currentEffort} onChange={(e) => set('effort', e)} />
                  <span class="fhint">How deeply the model thinks before responding. Higher effort means more careful reasoning.</span>
                </div>
              </div>

              <div class="group-title">Permissions</div>
              <div class="group">
                <div class="field"><span class="flabel">Mode</span>
                  <div class="chips" role="radiogroup">
                    {['full-access', 'auto', 'read-only'].map((m) => (
                      <button key={m} type="button" role="radio" aria-checked={codex.mode === m}
                        class={`chip ${codex.mode === m ? 'pink' : ''}`} onClick={() => set('mode', m as CodexAgent['mode'])}>{m}</button>
                    ))}
                  </div>
                  <span class="fhint">
                    {codex.mode === 'full-access' && 'Never asks for permissions.'}
                    {codex.mode === 'auto' && 'Workspace write, asks on request.'}
                    {codex.mode === 'read-only' && 'Read-only, asks on request.'}
                  </span>
                </div>
              </div>

              <div class="group-title">Instructions</div>
              <div class="group">
                <label class="field"><span class="flabel">Developer instructions</span>
                  <textarea class="input" rows={6} value={codex.instructions} placeholder="Custom instructions for this agent"
                    onInput={(e) => set('instructions', (e.target as HTMLTextAreaElement).value)} />
                </label>
              </div>
            </>
          )}

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
      {codex && <DirPicker open={dirPicker} onClose={() => setDirPicker(false)} onPick={(p) => { set('cwd', p); setDirPicker(false) }} />}
    </div>
  )
}
