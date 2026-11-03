// Workflow tile and card icons, by name (plugins declare an icon name in their schema). Stroke SVG like components/icons.tsx.

const P: Record<string, string> = {
  plus: 'M12 5v14M5 12h14',
  play: 'M7 4.5l12 7.5-12 7.5z',
  stop: 'M6 6h12v12H6z',
  more: 'M5 12.01h.01M12 12.01h.01M19 12.01h.01',
  undo: 'M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',
  redo: 'M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  copy: 'M9 9h11v11H9zM5 15V4h11',
  up: 'M12 19V5M5 12l7-7 7 7',
  down: 'M12 5v14M19 12l-7 7-7-7',
  grip: 'M9 6.01h.01M15 6.01h.01M9 12.01h.01M15 12.01h.01M9 18.01h.01M15 18.01h.01',
  sparkles: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z',
  clock: 'M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  text: 'M5 6h14M12 6v13M9 19h6',
  help: 'M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z',
  workflow: 'M4 4h6v6H4zM14 14h6v6h-6zM10 7h4a3 3 0 0 1 3 3v4',
  split: 'M12 3v6M12 9l-6 6v6M12 9l6 6v6',
  puzzle: 'M10 4a2 2 0 1 1 4 0v1h4v4h1a2 2 0 1 1 0 4h-1v5h-5v-1a2 2 0 1 0-4 0v1H4v-5h1a2 2 0 1 0 0-4H4V5h6z',
  branch: 'M6 3v12M6 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM18 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM18 9a9 9 0 0 1-9 9',
  repeat: 'M17 2l4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3',
  folder: 'M3 6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  check: 'M5 13l4 4L19 7',
  x: 'M6 6l12 12M18 6L6 18',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5',
  download: 'M12 4v12M6 12l6 6 6-6M5 20h14',
  upload: 'M12 20V8M6 12l6-6 6 6M5 4h14',
  history: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 8v5l3 2',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  home: 'M4 11l8-7 8 7v9H4z',
  bolt: 'M13 3L5 14h6l-1 7 8-11h-6z',
  star: 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z',
  heart: 'M12 20s-8-5-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 9c0 6-8 11-8 11z',
  book: 'M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10',
  code: 'M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16',
  mail: 'M4 6h16v12H4zM4 7l8 6 8-6',
  bell: 'M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 21h4',
  globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',
  file: 'M6 3h8l5 5v13H6zM14 3v5h5',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  refresh: 'M20 11a8 8 0 0 0-14.5-4M4 5v4h4M4 13a8 8 0 0 0 14.5 4M20 19v-4h-4',
  variable: 'M8 4c-2 0-3 1-3 3v2c0 1.5-1 3-2 3 1 0 2 1.5 2 3v2c0 2 1 3 3 3M16 4c2 0 3 1 3 3v2c0 1.5 1 3 2 3-1 0-2 1.5-2 3v2c0 2-1 3-3 3M9.5 9l5 6M14.5 9l-5 6',
  terminal: 'M4 5h16v14H4zM8 10l3 2-3 2M13 14h4',
  'skip-forward': 'M5 5l9 7-9 7zM18 5v14',
  target: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  flask: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3',
  ban: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM5.6 5.6l12.8 12.8',
  sliders: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4',
  input: 'M4 6h16v12H4zM8 10v4M12 10v4',
  user: 'M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 21a8 8 0 0 1 16 0',
  agent: 'M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 21a8 8 0 0 1 16 0M18 3l.6 1.7 1.7.6-1.7.6L18 7.6l-.6-1.7-1.7-.6 1.7-.6z',
  plug: 'M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4',
}

export const ICON_CHOICES = ['sparkles', 'bolt', 'star', 'heart', 'book', 'code', 'mail', 'bell', 'globe', 'file', 'workflow', 'terminal', 'clock', 'search', 'folder', 'link']
export const COLOR_CHOICES = ['pink', 'orange', 'yellow', 'green', 'blue', 'purple', 'red', 'gray']

export function WfIcon({ name, size = 20 }: { name?: string; size?: number }) {
  const heavy = name === 'more' || name === 'grip'
  return (
    <svg class="wf-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width={heavy ? 3 : 1.9} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d={P[name || ''] || P.puzzle} />
    </svg>
  )
}
