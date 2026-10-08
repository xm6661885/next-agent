import { render } from 'preact'
import { App } from './App'
import './styles/base.css'
import './styles/components.css'
import './styles/pages.css'
import './styles/chat.css'

// Track the visual viewport so the composer sits right above the iOS keyboard.
function syncViewport() {
  const vv = window.visualViewport
  const h = vv ? vv.height : window.innerHeight
  document.documentElement.style.setProperty('--app-h', `${h}px`)
  // iOS scrolls the layout viewport when the keyboard opens; pin it back.
  if (vv && vv.offsetTop > 0) window.scrollTo(0, 0)
}
syncViewport()
window.visualViewport?.addEventListener('resize', syncViewport)
window.visualViewport?.addEventListener('scroll', syncViewport)
window.addEventListener('resize', syncViewport)

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
