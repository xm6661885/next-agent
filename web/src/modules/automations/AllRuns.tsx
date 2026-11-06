// Global recent runs, newest first, paged.

import { useEffect, useRef, useState } from 'preact/hooks'
import { BackButton, TopBar, useScrolled } from '../../components/ui'
import { back, navigate } from '../../lib/router'
import { automationsVersion, toastError } from '../../lib/store'
import { autoApi, type Run } from './api'
import { RunRow } from './TaskPage'
import { Empty } from './ui'

const PAGE = 30

export function AllRuns() {
  const { scrolled, onScroll, ref } = useScrolled()
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [names, setNames] = useState<Record<number, string>>({})
  const [more, setMore] = useState(false)
  const timer = useRef<number>()

  const loadNames = () => autoApi.tasks().then((ts) => setNames(Object.fromEntries(ts.map((t) => [t.id, t.name])))).catch(() => {})
  useEffect(() => {
    clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      autoApi.runs(0, PAGE).then((r) => { setRuns(r); setMore(r.length === PAGE) }).catch(toastError)
      loadNames()
    }, runs ? 300 : 0)
    return () => clearTimeout(timer.current)
  }, [automationsVersion.value])

  const loadMore = async () => {
    try { const n = await autoApi.runs(runs?.length || 0, PAGE); setRuns((o) => [...(o || []), ...n]); setMore(n.length === PAGE) } catch (e) { toastError(e) }
  }
  return (
    <div class="page">
      <TopBar scrolled={scrolled} left={<BackButton label="Automations" onClick={() => back({ name: 'automations' })} />}>
        <span class="topbar-center">Run history</span>
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          {runs === null && <div class="skeleton" style={{ height: '200px', borderRadius: '20px' }} />}
          {runs?.length === 0 && <Empty title="No runs yet">Runs from every task show up here.</Empty>}
          {runs && runs.length > 0 && (
            <div class="group">{runs.map((r) => <RunRow key={r.id} r={r} name={names[r.task_id] || `Task ${r.task_id}`} onClick={() => navigate({ name: 'automation-run', runId: String(r.id) })} />)}</div>
          )}
          {more && <button class="btn block ghost" style={{ marginTop: '12px' }} onClick={loadMore}>Load more</button>}
        </div>
      </div>
    </div>
  )
}
