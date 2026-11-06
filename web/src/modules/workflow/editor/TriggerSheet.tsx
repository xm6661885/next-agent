// Per-workflow API trigger: enable switch, URL, token, regenerate, last used and a curl example.

import { useEffect, useState } from 'preact/hooks'
import { SecretInput, Sheet, Switch, confirmDialog } from '../../../components/ui'
import { IconCopy } from '../../../components/icons'
import { copyText } from '../../../lib/util'
import { toast, toastError } from '../../../lib/store'
import { fmtTime, wfApi, type TriggerInfo } from '../api'
import { def } from './state'

const PLACEHOLDER: Record<string, unknown> = { number: 0, bool: false, boolean: false, json: {}, list: [] }

export function TriggerSheet({ open, close, wid }: { open: boolean; close: () => void; wid: string }) {
  const [t, setT] = useState<TriggerInfo | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open && !t) wfApi.trigger(wid).then(setT).catch(toastError) }, [open])
  const run = (p: Promise<TriggerInfo>) => { setBusy(true); p.then(setT).catch(toastError).finally(() => setBusy(false)) }
  const url = t ? location.origin + t.path : ''
  const body: Record<string, unknown> = {}
  for (const i of def.value.inputs || []) body[i.name] = i.type && i.type in PLACEHOLDER ? PLACEHOLDER[i.type] : `<${i.name}>`
  const curl = t ? `curl -X POST '${url}?wait=1' -H 'Authorization: Bearer ${t.token}' -H 'Content-Type: application/json' -d '${JSON.stringify(body)}'` : ''
  const regen = async () => {
    if (await confirmDialog({ title: 'Regenerate token?', body: 'The old token stops working immediately.', confirm: 'Regenerate', danger: true })) run(wfApi.regenTrigger(wid))
  }
  return (
    <Sheet open={open} onClose={close} title="API trigger">
      {!t ? <p class="fhint" style={{ padding: '8px 4px' }}>Loading...</p> : (
        <>
          <div class="row wf-bool">
            <span class="label">Enabled<span class="hint">Last used: {t.last_used_at ? fmtTime(t.last_used_at) : 'never'}</span></span>
            <Switch on={t.enabled} disabled={busy} onChange={(v) => run(wfApi.setTrigger(wid, v))} label="Enable API trigger" />
          </div>
          <div class="wf-field"><span class="flabel">URL</span>
            <div class="secret-input">
              <input class="input mono" readOnly value={url} />
              <button type="button" class="icon-btn" aria-label="Copy URL" onClick={() => copyText(url).then(() => toast('Copied')).catch(toastError)}><IconCopy /></button>
            </div></div>
          <div class="wf-field"><span class="flabel">Token</span>
            <SecretInput value={t.token} onInput={() => {}} label="token" /></div>
          <button class="btn block" style={{ marginTop: '8px' }} disabled={busy} onClick={regen}>Regenerate token</button>
          <div class="wf-field" style={{ marginTop: '14px' }}><span class="flabel">Example</span>
            <textarea class="textarea mono" readOnly rows={5} value={curl} />
            <button class="btn block" onClick={() => copyText(curl).then(() => toast('Copied')).catch(toastError)}>Copy curl command</button></div>
          <p class="fhint" style={{ margin: '8px 4px' }}>The JSON body fills the workflow inputs; wait=1 makes the call return the result instead of only the run id.</p>
        </>
      )}
    </Sheet>
  )
}
