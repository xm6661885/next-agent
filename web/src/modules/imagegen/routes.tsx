// Image generation route: /more/images.

import type { Route } from '../../lib/router'
import { ImagesPage } from './Page'

export function ImagegenRoute(r: Route) {
  return r.name === 'images' ? <ImagesPage /> : null
}
