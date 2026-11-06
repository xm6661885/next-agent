// Bottom record panel: a round record button when idle; while recording it covers the page with the
// live waveform, timer and the transcript as each chunk comes back.

import { useEffect, useRef, useState } from 'preact/hooks'
import { computed } from '@preact/signals'
import { navigate } from '../../lib/router'
import { toastError } from '../../lib/store'
import { haptic } from '../../lib/util'
import { confirmDialog } from '../../components/ui'
import { IconTrash } from '../../components/icons'
import { IconPause } from '../../components/icons-apps'
import { asrApi, clock, defaultTitle } from './api'
import { currentLevel, discardRecording, pauseRecording, rec, resumeRecording, startRecording, stopRecording } from './recorder'
import { LiveWave } from './Wave'

let chunkSec = 15
// Bound straight into the DOM text node, so the 10 Hz timer never re-renders the panel.
const timeText = computed(() => clock(rec.elapsed.value, true))

export function RecordPanel({ onChanged }: { onChanged: () => void }) {
  const state = rec.state.value
  const open = state !== 'idle'
  const textRef = useRef<HTMLDivElement>(null)
  const [live, setLive] = useState(() => localStorage.getItem('asr-live') !== '0')
  const [liveRec, setLiveRec] = useState(true)
  const toggleLive = () => { haptic(); const v = !live; setLive(v); localStorage.setItem('asr-live', v ? '1' : '0') }

  useEffect(() => { asrApi.settings().then((s) => { chunkSec = s.chunk_sec }).catch(() => {}) }, [])
  useEffect(() => {
    const el = textRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [rec.segments.value.length, rec.pending.value.length])

  const start = async () => {
    haptic()
    try {
      setLiveRec(live)
      await startRecording(defaultTitle(), chunkSec, live)
      onChanged()
    } catch (e: any) {
      if (e && e.name === 'NotAllowedError') toastError('Microphone access was denied. Allow it in the browser settings.')
      else toastError(e)
    }
  }
  const stop = async () => {
    haptic()
    try {
      const id = await stopRecording()
      onChanged()
      if (id) navigate({ name: 'asr-detail', id })
    } catch (e) { toastError(e) }
  }
  const discard = async () => {
    if (!(await confirmDialog({ title: 'Delete this recording?', body: 'The audio and transcript so far will be removed.', confirm: 'Delete', danger: true }))) return
    await discardRecording()
    onChanged()
  }

  const segs = rec.segments.value.filter((s) => s.text)
  const waiting = rec.pending.value.length
  const failed = rec.segments.value.filter((s) => s.status === 'error').length
  const busy = state === 'stopping' || state === 'starting'

  return (
    <div class={`rec-panel ${open ? 'open' : ''}`}>
      {open && (
        <div class="rp-body">
          <div class="rp-title">{rec.title.value}</div>
          <div class={`rp-time ${state === 'paused' ? 'paused' : ''}`}>{timeText}</div>
          <LiveWave level={currentLevel} active={state === 'recording'} />
          <div ref={textRef} class="rp-text selectable">
            {!liveRec && <span class="dim">Live transcript is off. The transcript is made after you stop.</span>}
            {liveRec && segs.length === 0 && !waiting && <span class="dim">Transcript appears here every few seconds.</span>}
            {segs.map((s) => <span key={s.seq} class="rp-seg">{s.text} </span>)}
            {waiting > 0 && <span class="rp-typing" aria-label="Transcribing"><i /><i /><i /></span>}
            {failed > 0 && <span class="rp-fail">{failed} chunk{failed > 1 ? 's' : ''} failed, retry later from the detail page.</span>}
          </div>
        </div>
      )}
      <div class="rp-controls">
        {open && <button class="rp-side danger" onClick={discard} disabled={busy} aria-label="Discard recording"><IconTrash /></button>}
        <button class={`rec-btn ${open ? 'on' : ''} ${busy ? 'wait' : ''}`} onClick={open ? stop : start} disabled={busy}
          aria-label={open ? 'Stop recording' : 'Start recording'}>
          <span class="rec-btn-core" />
        </button>
        {open && (
          <button class="rp-side" onClick={() => { haptic(); state === 'paused' ? resumeRecording() : pauseRecording() }}
            disabled={busy} aria-label={state === 'paused' ? 'Resume' : 'Pause'}>
            {state === 'paused' ? <span class="rp-resume" /> : <IconPause />}
          </button>
        )}
      </div>
      {!open && (
        <button class={`rp-live ${live ? 'on' : ''}`} onClick={toggleLive} role="switch" aria-checked={live}>
          <i />Live transcript {live ? 'on' : 'off'}
        </button>
      )}
      {state === 'stopping' && <div class="rp-saving"><span class="spinner tiny" />Saving{waiting ? ` (${waiting} left)` : ''}...</div>}
    </div>
  )
}
