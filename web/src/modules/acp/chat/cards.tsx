// ACP permission request: the agent sends its own options (allow once, allow always, reject ...).

import { useState } from 'preact/hooks'
import type { AcpPermission } from '../api'
import type { AcpConn } from './conn'
import { toolSummary } from './tools'
import { highlightCode } from './markdown'
import { IconShield } from '../../../components/icons'

export function PermissionCard({ req, conn }: { req: AcpPermission; conn: AcpConn }) {
  const [busy, setBusy] = useState(false)
  const t = req.tool_call || {}
  const { verb, arg } = toolSummary({ name: t.title || '', acp_kind: t.kind, input: t.rawInput, locations: t.locations })
  const cmd = t.kind === 'execute' && typeof t.rawInput?.command === 'string' ? t.rawInput.command : null
  const reply = async (option_id: string | null) => {
    setBusy(true)
    const err = await conn.send({ type: 'permission_reply', id: req.id, option_id })
    if (err) { setBusy(false); conn.onError?.(err) }
  }
  const rank = (k: string) => ['allow_once', 'allow_always', 'reject_once', 'reject_always'].indexOf(k)
  const options = [...req.options].sort((a, b) => rank(a.kind) - rank(b.kind))
  return (
    <div class="ask-card pop">
      <div class="ask-head"><IconShield width={18} height={18} /><span>Allow {verb.toLowerCase()}?</span></div>
      {cmd
        ? <div class="tool-cmd ask-cmd"><span class="prompt">$</span><code dangerouslySetInnerHTML={{ __html: highlightCode(cmd, 'bash') }} /></div>
        : <div class="ask-target"><b>{verb}</b> {arg}</div>}
      <div class="ask-actions">
        {options.map((o, i) => (
          <button key={o.option_id} disabled={busy} onClick={() => reply(o.option_id)}
            class={`btn small ${i === 0 && o.kind.startsWith('allow') ? 'primary' : o.kind.startsWith('reject') ? 'ghost' : ''}`}>{o.name}</button>
        ))}
      </div>
    </div>
  )
}
