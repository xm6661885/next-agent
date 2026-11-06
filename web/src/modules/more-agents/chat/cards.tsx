// Permission and question cards for More Agents chat.

import { useState } from 'preact/hooks'
import type { Permission, Question } from '../api'
import type { MoreAgentConn } from './conn'
import { toolSummary } from './tools'
import { highlightCode } from './markdown'
import { IconShield, IconCheck } from '../../../components/icons'

export function PermissionCard({ req, conn }: { req: Permission; conn: MoreAgentConn }) {
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

export function QuestionCard({ req, onReply }: { req: Question; onReply: (id: string, answers: Record<string, string[]> | null) => void }) {
  const [answers, setAnswers] = useState<Record<string, string[]>>({})
  const [submitting, setSubmitting] = useState(false)

  const submit = () => {
    setSubmitting(true)
    onReply(req.id, answers)
  }
  const cancel = () => {
    setSubmitting(true)
    onReply(req.id, null)
  }

  return (
    <div class="permission-card rise">
      <div class="permission-head">
        <span class="permission-icon">?</span>
        <div class="permission-title">Agent question</div>
      </div>
      <div class="permission-body">
        {req.questions.map((q) => {
          const selected = answers[q.id] || []
          const setAnswer = (val: string, checked: boolean) => {
            const newVals = checked ? [...selected, val] : selected.filter((v) => v !== val)
            setAnswers({ ...answers, [q.id]: newVals })
          }
          const otherValue = selected.find((v) => !q.options.some((o) => o.label === v)) || ''
          return (
            <div key={q.id} class="question-item">
              {q.header && <div class="question-header">{q.header}</div>}
              <div class="question-text">{q.question}</div>
              <div class="question-options">
                {q.options.map((opt) => {
                  const checked = selected.includes(opt.label)
                  return (
                    <button
                      key={opt.label}
                      type="button"
                      class={`chip ${checked ? 'pink' : ''}`}
                      onClick={() => setAnswer(opt.label, !checked)}
                      disabled={submitting}
                    >
                      {checked && <IconCheck width={14} height={14} />} {opt.label}
                      {opt.description && <span class="chip-hint">{opt.description}</span>}
                    </button>
                  )
                })}
                {q.is_other && (
                  <label class="field">
                    <span class="flabel">Other</span>
                    <input
                      type={q.is_secret ? 'password' : 'text'}
                      class="input"
                      value={otherValue}
                      placeholder={q.is_secret ? 'Secret value' : 'Type your answer'}
                      disabled={submitting}
                      onInput={(e) => {
                        const val = (e.target as HTMLInputElement).value
                        const filtered = selected.filter((v) => q.options.some((o) => o.label === v))
                        setAnswers({ ...answers, [q.id]: val ? [...filtered, val] : filtered })
                      }}
                    />
                  </label>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div class="permission-actions">
        <button class="btn secondary small" onClick={cancel} disabled={submitting}>Cancel</button>
        <button class="btn primary small" onClick={submit} disabled={submitting}>
          {submitting ? <span class="spinner" /> : 'Submit'}
        </button>
      </div>
    </div>
  )
}
