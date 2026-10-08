// Interactive cards for pending requests: tool permission, AskUserQuestion, ExitPlanMode.

import { useState } from 'preact/hooks'
import type { PermissionRequest, Question } from '../lib/types'
import { renderMarkdown, highlightCode } from './markdown'
import { toolSummary } from './tools'
import { IconCheck, IconClose, IconMap, IconQuestion, IconShield } from '../components/icons'
import { MODE_LABELS } from '../lib/util'
import type { ChatConn } from './conn'

type Reply = (p: Record<string, any>) => Promise<void>

export function PermissionCard({ req, conn }: { req: PermissionRequest; conn: ChatConn }) {
  const [busy, setBusy] = useState(false)
  const reply: Reply = async (p) => {
    setBusy(true)
    const err = await conn.send({ type: 'permission_reply', id: req.id, ...p })
    if (err) { setBusy(false); conn.onError?.(err) }
  }
  if (req.kind === 'question') return <QuestionCard req={req} reply={reply} busy={busy} />
  if (req.kind === 'plan') return <PlanCard req={req} reply={reply} busy={busy} />
  return <ToolPermCard req={req} reply={reply} busy={busy} />
}

function ToolPermCard({ req, reply, busy }: { req: PermissionRequest; reply: Reply; busy: boolean }) {
  const [denying, setDenying] = useState(false)
  const [reason, setReason] = useState('')
  const { verb, arg } = toolSummary({ kind: 'tool', id: req.tool_use_id, tool_use_id: req.tool_use_id, name: req.tool_name, input: req.input, streaming: false, result: null })
  const cmd = req.tool_name === 'Bash' ? req.input.command : null
  return (
    <div class="ask-card pop">
      <div class="ask-head"><IconShield width={18} height={18} /><span>{req.title || `Allow ${verb}?`}</span></div>
      {cmd ? (
        <div class="tool-cmd ask-cmd"><span class="prompt">$</span><code dangerouslySetInnerHTML={{ __html: highlightCode(cmd, 'bash') }} /></div>
      ) : (
        <div class="ask-target"><b>{verb}</b> {arg}</div>
      )}
      {(req.description || req.decision_reason || req.input?.description) && (
        <div class="ask-desc">{req.description || req.input?.description || req.decision_reason}</div>
      )}
      {req.blocked_path && <div class="ask-desc mono">{req.blocked_path}</div>}
      {denying ? (
        <form class="ask-deny" onSubmit={(e) => { e.preventDefault(); reply({ decision: 'deny', message: reason }) }}>
          <input class="input" autoFocus placeholder="Tell Claude what to do instead (optional)" value={reason}
            onInput={(e) => setReason((e.target as HTMLInputElement).value)} />
          <div class="ask-actions">
            <button type="button" class="btn small" onClick={() => setDenying(false)}>Back</button>
            <button type="submit" class="btn small danger" disabled={busy}>Deny</button>
          </div>
        </form>
      ) : (
        <div class="ask-actions">
          <button class="btn small primary" disabled={busy} onClick={() => reply({ decision: 'allow' })}><IconCheck width={16} height={16} /> Allow</button>
          <button class="btn small" disabled={busy} onClick={() => reply({ decision: 'allow_always' })}>Always allow</button>
          <button class="btn small ghost" disabled={busy} onClick={() => setDenying(true)}>Deny</button>
        </div>
      )}
    </div>
  )
}

function QuestionCard({ req, reply, busy }: { req: PermissionRequest; reply: Reply; busy: boolean }) {
  const questions: Question[] = req.input?.questions || []
  const [answers, setAnswers] = useState<Record<string, string[]>>({})
  const [other, setOther] = useState<Record<string, string>>({})
  const [step, setStep] = useState(0)

  const pick = (q: Question, label: string) => {
    const cur = answers[q.question] || []
    if (q.multiSelect) {
      setAnswers({ ...answers, [q.question]: cur.includes(label) ? cur.filter((l) => l !== label) : [...cur, label] })
    } else {
      setAnswers({ ...answers, [q.question]: [label] })
      setOther({ ...other, [q.question]: '' })
      if (step < questions.length - 1) setTimeout(() => setStep(step + 1), 220)
    }
  }

  const final = () => {
    const out: Record<string, string | string[]> = {}
    for (const q of questions) {
      const sel = [...(answers[q.question] || [])]
      const o = other[q.question]?.trim()
      if (o) { if (q.multiSelect) sel.push(o); else sel.splice(0, sel.length, o) }
      out[q.question] = q.multiSelect ? sel : (sel[0] || '')
    }
    return out
  }
  const complete = questions.every((q) => (answers[q.question]?.length || 0) > 0 || other[q.question]?.trim())
  const q = questions[step]
  if (!q) return null

  return (
    <div class="ask-card question pop">
      <div class="ask-head">
        <IconQuestion width={18} height={18} />
        <span>{q.header || 'Question'}</span>
        {questions.length > 1 && (
          <span class="q-steps">
            {questions.map((_, k) => (
              <button key={k} class={`q-step ${k === step ? 'on' : ''} ${(answers[questions[k].question]?.length || other[questions[k].question]) ? 'done' : ''}`}
                onClick={() => setStep(k)} aria-label={`Question ${k + 1}`} />
            ))}
          </span>
        )}
      </div>
      <div class="q-text" key={step}>{q.question}</div>
      <div class="q-options" key={`o${step}`}>
        {q.options.map((o, k) => {
          const on = (answers[q.question] || []).includes(o.label)
          return (
            <button key={o.label} class={`q-opt rise ${on ? 'on' : ''}`} style={{ '--i': k }} onClick={() => pick(q, o.label)}>
              <span class={`q-mark ${q.multiSelect ? 'square' : ''}`}>{on && <IconCheck width={12} height={12} />}</span>
              <span class="q-opt-text">
                <span class="q-label">{o.label}</span>
                {o.description && <span class="q-desc">{o.description}</span>}
              </span>
            </button>
          )
        })}
        <input class="input q-other" placeholder="Something else" value={other[q.question] || ''}
          onInput={(e) => setOther({ ...other, [q.question]: (e.target as HTMLInputElement).value })} />
      </div>
      <div class="ask-actions">
        {step > 0 && <button class="btn small ghost" onClick={() => setStep(step - 1)}>Back</button>}
        <span style={{ flex: 1 }} />
        <button class="btn small ghost" disabled={busy} onClick={() => reply({ decision: 'deny' })}>Skip</button>
        {step < questions.length - 1 ? (
          <button class="btn small primary" onClick={() => setStep(step + 1)}>Next</button>
        ) : (
          <button class="btn small primary" disabled={busy || !complete} onClick={() => reply({ decision: 'allow', answers: final() })}>Submit</button>
        )}
      </div>
    </div>
  )
}

function PlanCard({ req, reply, busy }: { req: PermissionRequest; reply: Reply; busy: boolean }) {
  const [feedback, setFeedback] = useState('')
  const [revising, setRevising] = useState(false)
  const plan: string = req.input?.plan || ''
  return (
    <div class="ask-card plan pop">
      <div class="ask-head"><IconMap width={18} height={18} /><span>Ready to code?</span></div>
      <div class="plan-body md" dangerouslySetInnerHTML={{ __html: renderMarkdown(plan) }} />
      {revising ? (
        <form class="ask-deny" onSubmit={(e) => { e.preventDefault(); reply({ decision: 'deny', message: feedback }) }}>
          <textarea class="textarea" rows={3} autoFocus placeholder="What should change in the plan?" value={feedback}
            onInput={(e) => setFeedback((e.target as HTMLTextAreaElement).value)} />
          <div class="ask-actions">
            <button type="button" class="btn small" onClick={() => setRevising(false)}>Back</button>
            <button type="submit" class="btn small primary" disabled={busy}>Send feedback</button>
          </div>
        </form>
      ) : (
        <div class="ask-actions wrap">
          <button class="btn small primary" disabled={busy} onClick={() => reply({ decision: 'allow', mode: 'acceptEdits' })}>
            <IconCheck width={16} height={16} /> Approve, {MODE_LABELS.acceptEdits.toLowerCase()}
          </button>
          <button class="btn small" disabled={busy} onClick={() => reply({ decision: 'allow', mode: 'default' })}>Approve, ask first</button>
          <button class="btn small ghost" disabled={busy} onClick={() => setRevising(true)}><IconClose width={16} height={16} /> Keep planning</button>
        </div>
      )}
    </div>
  )
}
