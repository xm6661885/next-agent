// Automations tab routes: list, task, run log, create/edit form, global run history.

import type { Route } from '../../lib/router'
import { AllRuns } from './AllRuns'
import { TaskForm } from './Form'
import { Automations } from './Home'
import { RunLog } from './RunLog'
import { TaskPage } from './TaskPage'

export function AutomationsRoute(r: Route) {
  switch (r.name) {
    case 'automations': return <Automations />
    case 'automation-task': return <TaskPage id={r.taskId} />
    case 'automation-run': return <RunLog id={r.runId} />
    case 'automation-new': return <TaskForm />
    case 'automation-edit': return <TaskForm id={r.taskId} />
    case 'automation-runs': return <AllRuns />
  }
  return null
}
