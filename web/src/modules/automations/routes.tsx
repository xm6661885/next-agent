// Automations tab routes. The page is a placeholder until the Automations module lands.

import type { Route } from '../../lib/router'
import { Automations } from './Home'

export function AutomationsRoute(r: Route) {
  switch (r.name) {
    case 'automations': return <Automations />
  }
  return null
}
