// Run log page: run metadata and a monospace log that tails while the run is live.

import { useEffect, useRef, useState } from 'preact/hooks'
import { BackButton, TopBar, useScrolled } from '../../components/ui'
import { IconCopy } from '../../components/icons'
import { back, navigate } from '../../lib/router'
import { toastError } from '../../lib/store'
import { autoApi, type Run } from './api'
import { TRIGGER_LABEL, fmtDateTime, fmtSpan, runOutcome } from './format'
import { OutcomeBadge, copy } from './ui'

const POLL_MS = 1500

export function RunLog({ id }: { id: string }) {
  const { scrolled, onScroll: baseScroll, ref } = useScrolled()
  const [run, setRun] = useState<Run | null>(null)
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [done, setDone] = useState(false)
  const offset = useRef(0)
  const pinned = useRef(true)
  const doneRef = useRef(false)

  useEffect(() => {
    let dead = false
    let timer: number | undefined
    const pull = async () => {
      clearTimeout(timer)
      if (dead || doneRef.current) return
      if (document.visibilityState !== 'visible') return  // resumed by visibilitychange
      try {
        const c = await autoApi.log(id, offset.current)
        if (dead) return
        offset.current = c.offset
        if (c.text) setText((t) => t + c.text)
        if (c.done) {
          doneRef.current = true; setDone(true)
          setRun((r) => r && { ...r, exit_code: c.exit_code, finished_at: c.finished_at })
          return
        }
      } catch (e) { if (!dead) toastError(e) }
      timer = window.setTimeout(pull, POLL_MS)
    }
    const wake = () => { if (document.visibilityState === 'visible') pull() }
    document.addEventListener('visibilitychange', wake)
    ;(async () => {
      try {
        const r = await autoApi.runInfo(id)
        if (dead) return
        setRun(r)
        autoApi.task(r.task_id).then((t) => !dead && setName(t.name)).catch(() => {})
      } catch (e) { toastError(e) }
      pull()
    })()
    return () => { dead = true; clearTimeout(timer); document.removeEventListener('visibilitychange', wake) }
  }, [id])

  // Keep the view on the newest output unless the user scrolled up.
  useEffect(() => {
    const el = ref.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [text])

  const onScroll = (e: Event) => {
    const el = e.currentTarget as HTMLElement
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
    baseScroll(e)
  }

  const o = run ? runOutcome(run) : null
  return (
    <div class="page">
      <TopBar scrolled={scrolled}
        left={<BackButton label="Back" onClick={() => back({ name: 'automations' })} />}
        right={<div class="topbar-actions"><button class="icon-btn" aria-label="Copy log" disabled={!text} onClick={() => copy(text)}><IconCopy /></button></div>}>
        <span class="topbar-center">Run #{id}</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          {run && (
            <div class="group auto-run-head">
              <button class="row press" onClick={() => navigate({ name: 'automation-task', taskId: String(run.task_id) })}>
                <span class="label">{name || `Task ${run.task_id}`}<span class="hint">{TRIGGER_LABEL[run.trigger] || run.trigger} · started {fmtDateTime(run.started_at)}</span></span>
                {o && <OutcomeBadge o={o} />}
              </button>
              <div class="row"><span class="label">Finished<span class="hint">{run.finished_at ? `${fmtDateTime(run.finished_at)} · took ${fmtSpan(run.started_at, run.finished_at)}` : 'Still running'}</span></span>
                {run.finished_at && <span class="value">{run.exit_code === null ? 'no exit code' : `exit ${run.exit_code}`}</span>}</div>
            </div>
          )}
          <pre class="auto-log">{text || (done ? '(no output)' : 'Waiting for output')}</pre>
        </div>
      </div>
    </div>
  )
}
