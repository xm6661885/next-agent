// Speech to text routes: /more/asr (list + record panel) and /more/asr/<id> (detail).

import type { Route } from '../../lib/router'
import { AsrHome } from './Home'
import { AsrDetail } from './Detail'

export function AsrRoute(r: Route) {
  switch (r.name) {
    case 'asr': return <AsrHome />
    case 'asr-detail': return <AsrDetail id={r.id} />
  }
  return null
}
