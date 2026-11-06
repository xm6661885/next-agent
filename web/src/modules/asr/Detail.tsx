// One recording: player, transcript timeline (tap to seek, retry failed segments) or editable text, and actions.

import { useEffect, useRef, useState } from 'preact/hooks'
import { back } from '../../lib/router'
import { asrVersion, lastAsrId, toast, toastError } from '../../lib/store'
import { copyText, fmtBytes, haptic } from '../../lib/util'
import { BackButton, confirmDialog, promptDialog, Segmented, Sheet, TopBar, useScrolled } from '../../components/ui'
import { IconCopy, IconEdit, IconMore, IconRefresh, IconTrash } from '../../components/icons'
import { IconAlert, IconDownload, IconPause, IconPlay, IconShare, IconSkipBack, IconSkipFwd, IconStar } from '../../components/icons-apps'
import { asrApi, clock, type Recording, type Segment } from './api'

const RATES = [1, 1.25, 1.5, 2, 0.75]

export function AsrDetail({ id }: { id: string }) {
  const [r, setR] = useState<Recording | null>(null)
  const [mode, setMode] = useState<'segments' | 'text'>('segments')
  const [draft, setDraft] = useState<string | null>(null)
  const [menu, setMenu] = useState(false)
  const [retrying, setRetrying] = useState<number | null>(null)
  const { scrolled, onScroll, ref } = useScrolled()
  const seek = useRef<(t: number) => void>(() => {})
  const goBack = () => back({ name: 'asr' })

  const load = () => asrApi.get(id).then(setR).catch((e) => { toastError(e); if (e.status === 404) goBack() })
  useEffect(() => { load() }, [id])
  // Refetch when the server says something changed (events for other recordings are ignored).
  const ver = asrVersion.value
  useEffect(() => { if (ver > 0 && (!lastAsrId.value || lastAsrId.value === id)) load() }, [ver])

  // Slow poll only while processing and visible, as a fallback for a dropped event feed.
  const processing = !!r && (r.status === 'processing' || r.status === 'recording')
  useEffect(() => {
    if (!processing) return
    const t = setInterval(() => { if (document.visibilityState === 'visible') load() }, 3000)
    return () => clearInterval(t)
  }, [processing, id])

  useEffect(() => { if (r?.edited && draft === null) setMode('text') }, [r?.edited])

  const save = async (p: Parameters<typeof asrApi.patch>[1]) => {
    try { const n = await asrApi.patch(id, p); setR(n); return n } catch (e) { toastError(e) }
  }
  const rename = async () => {
    setMenu(false)
    const t = await promptDialog({ title: 'Rename', value: r!.title })
    if (t && t.trim() && t.trim() !== r!.title) save({ title: t.trim() })
  }
  const remove = async () => {
    setMenu(false)
    if (!(await confirmDialog({ title: 'Delete recording?', body: 'The audio and transcript will be removed.', confirm: 'Delete', danger: true }))) return
    try { await asrApi.remove(id); goBack() } catch (e) { toastError(e) }
  }
  const redo = async () => {
    setMenu(false)
    if (!(await confirmDialog({ title: 'Transcribe again?', body: 'The whole audio is sent again. Edits to the transcript are replaced.', confirm: 'Transcribe' }))) return
    try { setR(await asrApi.retranscribe(id)); setDraft(null); setMode('segments') } catch (e) { toastError(e) }
  }
  const retry = async (s: Segment) => {
    setRetrying(s.seq)
    try {
      const seg = await asrApi.retrySegment(id, s.seq)
      if (seg.status === 'error') toastError(seg.error || 'Failed again')
      await load()
    } catch (e) { toastError(e) } finally { setRetrying(null) }
  }
  const share = async () => {
    setMenu(false)
    if (navigator.share) { try { await navigator.share({ title: r!.title, text: r!.text }) } catch { /* cancelled */ } }
    else { await copyText(r!.text); toast('Copied') }
  }
  const saveDraft = async () => {
    if (draft === null) return
    if (draft === r!.text) { setDraft(null); return }
    if (await save({ text: draft })) setDraft(null)
  }
  const resetText = async () => {
    if (!(await confirmDialog({ title: 'Reset text?', body: 'Go back to the recognized text.', confirm: 'Reset', danger: true }))) return
    if (await save({ reset_text: true })) { setDraft(null); setMode('segments') }
  }

  if (!r) {
    return (
      <div class="page">
        <TopBar left={<BackButton onClick={goBack} label="Recordings" />} />
        <div class="container"><div class="skeleton" style={{ height: '120px', marginTop: '24px' }} /></div>
      </div>
    )
  }

  const segs = r.segments
  const errors = segs.filter((s) => s.status === 'error')
  const text = draft ?? r.text

  return (
    <div class="page asr-detail">
      <TopBar scrolled={scrolled} left={<BackButton onClick={goBack} label="Recordings" />} title={scrolled ? r.title : undefined}
        right={<>
          <button class={`icon-btn ${r.starred ? 'accent' : ''}`} onClick={() => { haptic(); save({ starred: !r.starred }) }}
            aria-label={r.starred ? 'Remove star' : 'Star'} aria-pressed={r.starred}><IconStar fill={r.starred ? 'currentColor' : 'none'} /></button>
          <button class="icon-btn" onClick={() => setMenu(true)} aria-label="More"><IconMore /></button>
        </>} />
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="d-title" onClick={rename}>{r.title}</h1>
          <div class="d-meta">
            {new Date(r.created_at * 1000).toLocaleString()} · {clock(r.duration)}{r.size ? ` · ${fmtBytes(r.size)}` : ''}{r.source === 'upload' ? ' · Upload' : ''}
          </div>

          <Player r={r} bind={(f) => { seek.current = f }} />

          {r.status === 'processing' && (
            <div class="d-banner">
              <span class="spinner tiny" />
              <span>{r.progress ? `Transcribing ${r.progress.done} of ${r.progress.total}` : 'Processing audio'}</span>
              {r.progress && <span class="d-prog"><i style={{ width: `${(r.progress.done / Math.max(1, r.progress.total)) * 100}%` }} /></span>}
            </div>
          )}
          {r.status === 'error' && (
            <div class="d-banner err"><IconAlert /><span class="selectable">{r.error || 'Transcription failed'}</span>
              <button class="btn small" onClick={redo}>Retry</button></div>
          )}

          <div class="d-tools">
            <Segmented value={mode} onChange={(v) => setMode(v)}
              options={[{ value: 'segments', label: 'Timeline' }, { value: 'text', label: 'Edit text' }]} />
            <button class="btn small ghost" onClick={async () => { await copyText(text); haptic(); toast('Copied') }} disabled={!text}>
              <IconCopy width={16} />Copy
            </button>
          </div>

          {mode === 'segments' && (
            <div class="segs">
              {r.edited && <p class="d-note">The text was edited. The timeline shows the recognized transcript.</p>}
              {segs.length === 0 && r.status !== 'processing' && <p class="d-note">No transcript.</p>}
              {segs.map((s) => (
                <div key={s.seq} class={`seg ${s.status === 'error' ? 'err' : ''}`}>
                  <button class="seg-time" onClick={() => seek.current(s.start)}>{clock(s.start)}</button>
                  {s.status === 'error'
                    ? <div class="seg-text"><span class="seg-errmsg">{s.error}</span>
                      <button class="btn small" disabled={retrying === s.seq} onClick={() => retry(s)}>
                        {retrying === s.seq ? <span class="spinner tiny" /> : <IconRefresh width={15} />}Retry</button></div>
                    : <button class={`seg-text selectable ${s.text ? '' : 'dim'}`} onClick={() => seek.current(s.start)}>{s.text || '(silence)'}</button>}
                </div>
              ))}
              {errors.length > 1 && (
                <button class="btn block" onClick={async () => { for (const s of errors) await retry(s) }}>
                  Retry {errors.length} failed segments
                </button>
              )}
            </div>
          )}

          {mode === 'text' && (
            <div class="text-wrap">
              <textarea class="d-text" value={text} placeholder="No transcript yet"
                onInput={(e) => setDraft((e.target as HTMLTextAreaElement).value)}
                ref={(el) => { if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight + 2}px` } }} />
              <div class="text-foot">
                <span>{text.length} chars{r.edited ? ' · edited' : ''}</span>
                {r.edited && <button class="link" onClick={resetText}>Reset to recognized text</button>}
                {draft !== null && <button class="btn small primary" onClick={saveDraft}>Save</button>}
              </div>
            </div>
          )}
        </div>
      </div>

      <Sheet open={menu} onClose={() => setMenu(false)} title={r.title}>
        <div class="menu">
          <button onClick={async () => { setMenu(false); await copyText(text); toast('Copied') }} disabled={!text}><IconCopy />Copy text</button>
          <button onClick={share}><IconShare />Share text</button>
          <a class="menu-a" href={asrApi.exportUrl(id, 'txt')} download onClick={() => setMenu(false)}><IconDownload />Export TXT</a>
          <a class="menu-a" href={asrApi.exportUrl(id, 'srt')} download onClick={() => setMenu(false)}><IconDownload />Export SRT subtitles</a>
          <button onClick={rename}><IconEdit />Rename</button>
          <button onClick={redo} disabled={r.status === 'processing' || r.status === 'recording'}><IconRefresh />Transcribe again</button>
          <button class="danger" onClick={remove}><IconTrash />Delete</button>
        </div>
      </Sheet>
    </div>
  )
}

function Player({ r, bind }: { r: Recording; bind: (f: (t: number) => void) => void }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [t, setT] = useState(0)
  const [dur, setDur] = useState(r.duration)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(() => Number(localStorage.getItem('asr_rate')) || 1)
  const ready = r.size > 0 && r.status !== 'recording' && r.status !== 'error'
  const src = ready ? `${asrApi.audioUrl(r.id)}?v=${r.size}` : ''
  const total = dur || r.duration

  bind((s) => {
    const a = audio.current
    if (!a || !ready) return
    a.currentTime = s
    setT(s)
    a.play().catch(() => {})
  })

  useEffect(() => { if (audio.current) audio.current.playbackRate = rate }, [rate, src])

  const toggle = () => {
    const a = audio.current
    if (!a) return
    haptic()
    if (a.paused) a.play().catch(toastError)
    else a.pause()
  }
  const jump = (to: number) => { const a = audio.current; if (a) { a.currentTime = Math.max(0, Math.min(total, to)); setT(a.currentTime) } }
  const cycleRate = () => {
    const n = RATES[(RATES.indexOf(rate) + 1) % RATES.length]
    setRate(n)
    localStorage.setItem('asr_rate', String(n))
  }

  return (
    <div class={`player ${ready ? '' : 'off'}`}>
      {src && <audio ref={audio} src={src} preload="metadata"
        onTimeUpdate={(e) => setT((e.target as HTMLAudioElement).currentTime)}
        onLoadedMetadata={(e) => { const d = (e.target as HTMLAudioElement).duration; if (isFinite(d)) setDur(d) }}
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />}
      <input class="range pl-seek" type="range" min={0} max={Math.max(1, total)} step={0.1} value={Math.min(t, total)} disabled={!ready}
        aria-label="Seek" onInput={(e) => jump(Number((e.target as HTMLInputElement).value))} />
      <div class="pl-times"><span>{clock(t)}</span><span>-{clock(Math.max(0, total - t))}</span></div>
      <div class="pl-ctrls">
        <button class="pl-rate" onClick={cycleRate} disabled={!ready} aria-label="Playback speed">{rate}x</button>
        <button class="icon-btn pl-skip" onClick={() => jump(t - 15)} disabled={!ready} aria-label="Back 15 seconds"><IconSkipBack /></button>
        <button class="pl-play" onClick={toggle} disabled={!ready} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? <IconPause /> : <IconPlay />}
        </button>
        <button class="icon-btn pl-skip" onClick={() => jump(t + 15)} disabled={!ready} aria-label="Forward 15 seconds"><IconSkipFwd /></button>
        <span class="pl-rate ghost" aria-hidden="true" />
      </div>
    </div>
  )
}
