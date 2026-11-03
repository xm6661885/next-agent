// Workflow tab routes. Workflows, Console and Runs are tab roots switched by the segmented control at the top.

import type { Route } from '../../lib/router'
import { Editor } from './Editor'
import { WorkflowHome } from './Home'
import { WorkflowConsole, WorkflowRuns } from './Lists'
import { RunPage } from './Run'

export function WorkflowRoute(r: Route) {
  switch (r.name) {
    case 'workflows': return <WorkflowHome />
    case 'wf-console': return <WorkflowConsole />
    case 'wf-runs': return <WorkflowRuns workflowId={r.workflowId} />
    case 'wf-editor': return <Editor id={r.workflowId} />
    case 'wf-run': return <RunPage id={r.runId} />
  }
  return null
}
