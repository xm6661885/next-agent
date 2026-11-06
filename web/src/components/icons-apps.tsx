// Icons used by the Speech to text and Image generation apps. Same 24x24 stroke style as icons.tsx.

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

export const IconMic = (p: P) => I(<><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><path d="M12 18v3" /></>, p)
export const IconStar = (p: P) => I(<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" />, p)
export const IconPlay = (p: P) => I(<path d="M7 4.5v15l12-7.5z" fill="currentColor" />, p)
export const IconPause = (p: P) => I(<><rect x="6.5" y="5" width="3.8" height="14" rx="1" fill="currentColor" /><rect x="13.7" y="5" width="3.8" height="14" rx="1" fill="currentColor" /></>, p)
export const IconDownload = (p: P) => I(<><path d="M12 4v11" /><path d="m7 11 5 5 5-5" /><path d="M5 20h14" /></>, p)
export const IconUpload = (p: P) => I(<><path d="M12 16V5" /><path d="m7 9 5-5 5 5" /><path d="M5 20h14" /></>, p)
export const IconShare = (p: P) => I(<><path d="M12 15V4" /><path d="m8 8 4-4 4 4" /><path d="M6 12v7h12v-7" /></>, p)
export const IconSkipBack = (p: P) => I(<><path d="M4 12a8 8 0 1 0 2.4-5.7" /><path d="M4 4v4h4" /><path d="M10 9.5v5M13.5 9.5h1.8a.7.7 0 0 1 .7.7v3.6a.7.7 0 0 1-.7.7h-1.8a.7.7 0 0 1-.7-.7v-3.6a.7.7 0 0 1 .7-.7z" stroke-width="1.5" /></>, p)
export const IconSkipFwd = (p: P) => I(<><path d="M20 12a8 8 0 1 1-2.4-5.7" /><path d="M20 4v4h-4" /><path d="M10 9.5v5M13.5 9.5h1.8a.7.7 0 0 1 .7.7v3.6a.7.7 0 0 1-.7.7h-1.8a.7.7 0 0 1-.7-.7v-3.6a.7.7 0 0 1 .7-.7z" stroke-width="1.5" /></>, p)
export const IconAlert = (p: P) => I(<><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5" /><path d="M12 16h.01" /></>, p)
export const IconArrowLeft = (p: P) => I(<><path d="M19 12H5" /><path d="m11 18-6-6 6-6" /></>, p)
export const IconArrowRight = (p: P) => I(<><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>, p)
export const IconSparkle = (p: P) => I(<><path d="M12 3v4M12 17v4M3 12h4M17 12h4" /><path d="m12 8 1.5 3.5L17 12l-3.5 1.5L12 17l-1.5-3.5L7 12l3.5-1.5z" /></>, p)
