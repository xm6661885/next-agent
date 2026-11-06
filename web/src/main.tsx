import { render } from 'preact'
import { App } from './App'
import './styles/base.css'
import './styles/components.css'
import './styles/pages.css'
import './styles/chat.css'
import './styles/workflow.css'
import './styles/automations.css'

// Track the visual viewport so the composer sits right above the iOS keyboard. Events are coalesced to one
// update per frame; layout is read before anything is written, and a CSS variable or class is only touched
// when its value changed, so a burst of resize/scroll events does not keep invalidating layout.
function syncViewport() {
  const root = document.documentElement
  const vv = window.visualViewport
  // Reads first. The keyboard covers the bottom of the layout viewport: iOS Safari shrinks innerHeight with it
  // but not the layout viewport (clientHeight), which is what position: fixed; bottom: 0 uses.
  const layout = root.clientHeight
  const h = `${vv ? vv.height : window.innerHeight}px`
  const offset = vv ? vv.offsetTop : 0
  const kb = vv ? Math.max(0, layout - vv.height - Math.max(0, offset)) : 0
  const kbPx = `${Math.round(kb)}px`
  // Writes, only on change.
  if (root.style.getPropertyValue('--app-h') !== h) root.style.setProperty('--app-h', h)
  if (root.style.getPropertyValue('--kb') !== kbPx) root.style.setProperty('--kb', kbPx)
  const open = kb > 80
  if (root.classList.contains('kb-open') !== open) root.classList.toggle('kb-open', open)
  // iOS scrolls the layout viewport when the keyboard opens; pin it back.
  if (offset > 0) window.scrollTo(0, 0)
}
let viewportFrame = 0
function queueViewport() {
  if (viewportFrame) return
  viewportFrame = requestAnimationFrame(() => { viewportFrame = 0; syncViewport() })
}
syncViewport()
window.visualViewport?.addEventListener('resize', queueViewport, { passive: true })
window.visualViewport?.addEventListener('scroll', queueViewport, { passive: true })
window.addEventListener('resize', queueViewport, { passive: true })

// Prevent pinch / double-tap zoom in standalone mode, like a native app.
document.addEventListener('gesturestart', (e) => e.preventDefault())
let lastTouch = 0
document.addEventListener('touchend', (e) => {
  const now = Date.now()
  if (now - lastTouch < 300 && !(e.target as HTMLElement).closest('input, textarea')) e.preventDefault()
  lastTouch = now
}, { passive: false })

if ('serviceWorker' in navigator && location.protocol === 'https:') {
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}) })
}

render(<App />, document.getElementById('app')!)

const splash = document.getElementById('splash')
if (splash) {
  requestAnimationFrame(() => splash.classList.add('hide'))
  setTimeout(() => splash.remove(), 400)
}
