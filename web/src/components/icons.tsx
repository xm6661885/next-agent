// Inline SVG icon set (stroke icons, 24x24). No emoji anywhere in the UI.

import type { JSX } from 'preact'

type P = JSX.SVGAttributes<SVGSVGElement>

function I(paths: JSX.Element, props: P) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"
      stroke-linejoin="round" aria-hidden="true" {...props}>
      {paths}
    </svg>
  )
}

export const IconBack = (p: P) => I(<path d="m15 18-6-6 6-6" />, p)
export const IconChevron = (p: P) => I(<path d="m9 18 6-6-6-6" />, p)
export const IconChevronDown = (p: P) => I(<path d="m6 9 6 6 6-6" />, p)
export const IconPlus = (p: P) => I(<path d="M12 5v14M5 12h14" />, p)
export const IconClose = (p: P) => I(<path d="M18 6 6 18M6 6l12 12" />, p)
export const IconCheck = (p: P) => I(<path d="M20 6 9 17l-5-5" />, p)
export const IconSend = (p: P) => I(<><path d="M12 19V5" /><path d="m5 12 7-7 7 7" /></>, p)
export const IconStop = (p: P) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...p}><rect x="6.5" y="6.5" width="11" height="11" rx="2.5" fill="currentColor" /></svg>
)
export const IconPaperclip = (p: P) =>
  I(<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />, p)
export const IconImage = (p: P) =>
  I(<><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21" /></>, p)
export const IconCamera = (p: P) =>
  I(<><path d="M14.5 4h-5L7.5 6.5H5a2 2 0 0 0-2 2V18a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8.5a2 2 0 0 0-2-2h-2.5z" /><circle cx="12" cy="13" r="3.5" /></>, p)
export const IconFile = (p: P) =>
  I(<><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></>, p)
export const IconSettings = (p: P) =>
  I(<><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></>, p)
export const IconMoon = (p: P) =>
  I(<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z" />, p)
export const IconMore = (p: P) =>
  I(<><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="19" cy="12" r="1" fill="currentColor" /></>, p)
export const IconTrash = (p: P) =>
  I(<><path d="M3 6h18" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /></>, p)
export const IconEdit = (p: P) =>
  I(<><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></>, p)
export const IconFork = (p: P) =>
  I(<><circle cx="6" cy="5" r="2" /><circle cx="18" cy="5" r="2" /><circle cx="12" cy="19" r="2" /><path d="M6 7v2a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3V7" /><path d="M12 12v5" /></>, p)
export const IconImport = (p: P) =>
  I(<><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" /></>, p)
export const IconTerminal = (p: P) =>
  I(<><path d="m4 17 6-6-6-6" /><path d="M12 19h8" /></>, p)
export const IconFolder = (p: P) =>
  I(<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2z" />, p)
export const IconSearch = (p: P) => I(<><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>, p)
export const IconPencilLine = (p: P) => I(<><path d="M4 20h4L18.5 9.5a2.83 2.83 0 0 0-4-4L4 16z" /></>, p)
export const IconGlobe = (p: P) =>
  I(<><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></>, p)
export const IconSort = (p: P) =>
  I(<><path d="m3 8 4-4 4 4" /><path d="M7 4v16" /><path d="m21 16-4 4-4-4" /><path d="M17 20V4" /></>, p)
export const IconGrip = (p: P) =>
  I(<><circle cx="9" cy="6" r="1" fill="currentColor" /><circle cx="15" cy="6" r="1" fill="currentColor" /><circle cx="9" cy="12" r="1" fill="currentColor" /><circle cx="15" cy="12" r="1" fill="currentColor" /><circle cx="9" cy="18" r="1" fill="currentColor" /><circle cx="15" cy="18" r="1" fill="currentColor" /></>, p)
export const IconList = (p: P) =>
  I(<><path d="M8 6h13M8 12h13M8 18h13" /><path d="M3 6h.01M3 12h.01M3 18h.01" /></>, p)
export const IconBrain = (p: P) =>
  I(<><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" /><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" /></>, p)
export const IconTool = (p: P) =>
  I(<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />, p)
export const IconAgents = (p: P) =>
  I(<><circle cx="9" cy="8" r="3.2" /><path d="M3 20a6 6 0 0 1 12 0" /><path d="M16 4.5a3.2 3.2 0 0 1 0 6.2" /><path d="M21 20a6 6 0 0 0-4-5.65" /></>, p)
export const IconShield = (p: P) => I(<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />, p)
export const IconMap = (p: P) =>
  I(<><path d="M9 3 3 6v15l6-3 6 3 6-3V3l-6 3z" /><path d="M9 3v15M15 6v15" /></>, p)
export const IconQuestion = (p: P) =>
  I(<><circle cx="12" cy="12" r="10" /><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3" /><path d="M12 17h.01" /></>, p)
export const IconCopy = (p: P) =>
  I(<><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>, p)
export const IconRewind = (p: P) =>
  I(<><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></>, p)
export const IconLogout = (p: P) =>
  I(<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" /></>, p)
export const IconChat = (p: P) =>
  I(<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />, p)
export const IconNewChat = (p: P) =>
  I(<><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" /><path d="M12 8.5v6M9 11.5h6" /></>, p)
export const IconClock = (p: P) => I(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>, p)
export const IconBolt = (p: P) => I(<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />, p)
export const IconCode = (p: P) => I(<><path d="m16 18 6-6-6-6" /><path d="m8 6-6 6 6 6" /></>, p)
export const IconLock = (p: P) =>
  I(<><rect x="4" y="11" width="16" height="10" rx="2.5" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>, p)
export const IconSteer = (p: P) =>
  I(<><path d="M5 12h11" /><path d="m12 7 5 5-5 5" /><path d="M19 5v14" /></>, p)
