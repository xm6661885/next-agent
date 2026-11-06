// Live recorder: captures mic PCM, cuts it into ~N-second WAV chunks (preferring a quiet moment
// near the boundary so words are not split), and uploads them in order for pseudo-streaming
// transcription. The server holds the canonical audio; chunks are retried until they land.

import { signal } from '@preact/signals'
import { asrApi as api, type Segment } from './api'

const RATE = 16000

export type RecState = 'idle' | 'starting' | 'recording' | 'paused' | 'stopping'

export const rec = {
  state: signal<RecState>('idle'),
  id: signal<string | null>(null),
  title: signal(''),
  elapsed: signal(0),
  segments: signal<Segment[]>([]),
  /** Seq numbers waiting for upload / transcription. */
  pending: signal<number[]>([]),
}

let ctx: AudioContext | null = null
let stream: MediaStream | null = null
let node: ScriptProcessorNode | null = null
let source: MediaStreamAudioSourceNode | null = null
let wakeLock: any = null

let buf: Float32Array[] = []
let bufLen = 0
let chunkStart = 0 // seconds into the recording where the buffered audio starts
let total = 0      // samples (at RATE) captured so far
let seq = 0
let chunkSec = 15
let resample: ((x: Float32Array) => Float32Array) | null = null
let analyser: AnalyserNode | null = null
let levelBuf: Float32Array | null = null

/** Current input peak 0..1, read by the waveform on every animation frame (no re-renders). */
export function currentLevel(): number {
  if (!analyser || !levelBuf || rec.state.value !== 'recording') return 0
  analyser.getFloatTimeDomainData(levelBuf as any)
  let peak = 0
  for (let i = 0; i < levelBuf.length; i++) { const v = Math.abs(levelBuf[i]); if (v > peak) peak = v }
  return Math.min(1, Math.pow(peak, 0.6) * 1.4)
}

const queue: { seq: number; start: number; end: number; wav: Blob }[] = []
let uploading = false
let finishWaiters: (() => void)[] = []

function makeResampler(from: number) {
  if (from === RATE) return (x: Float32Array) => x
  const ratio = from / RATE
  let carry = 0 // fractional read position carried between blocks
  return (x: Float32Array) => {
    const n = Math.floor((x.length - carry) / ratio)
    const out = new Float32Array(Math.max(0, n))
    for (let i = 0; i < out.length; i++) {
      // box filter over the source span: cheap anti-aliasing
      const a = carry + i * ratio
      const b = a + ratio
      let s = 0, c = 0
      for (let j = Math.floor(a); j < Math.min(x.length, Math.ceil(b)); j++) { s += x[j]; c++ }
      out[i] = c ? s / c : 0
    }
    carry = carry + out.length * ratio - x.length
    return out
  }
}

function encodeWav(samples: Float32Array): Blob {
  const b = new ArrayBuffer(44 + samples.length * 2)
  const v = new DataView(b)
  const w = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)) }
  w(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); w(8, 'WAVE'); w(12, 'fmt ')
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, RATE, true); v.setUint32(28, RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  w(36, 'data'); v.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([b], { type: 'audio/wav' })
}

function flat(): Float32Array {
  const out = new Float32Array(bufLen)
  let o = 0
  for (const p of buf) { out.set(p, o); o += p.length }
  return out
}

/** Index of the quietest 100ms window in the last few seconds, to cut there. */
function quietCut(x: Float32Array): number {
  const win = RATE / 10
  const from = Math.max(win, x.length - RATE * 4)
  let best = x.length, bestE = Infinity
  for (let s = from; s + win <= x.length; s += win / 2) {
    let e = 0
    for (let i = s; i < s + win; i++) e += x[i] * x[i]
    if (e < bestE) { bestE = e; best = s + win / 2 }
  }
  return Math.floor(best)
}

function cut(final: boolean) {
  if (!bufLen) return
  const all = flat()
  const at = final ? all.length : quietCut(all)
  const part = all.subarray(0, at)
  const rest = all.slice(at)
  const start = chunkStart
  const end = start + part.length / RATE
  queue.push({ seq: seq, start, end, wav: encodeWav(part) })
  rec.pending.value = [...rec.pending.value, seq]
  seq++
  chunkStart = end
  buf = rest.length ? [rest] : []
  bufLen = rest.length
  pump()
}

async function pump() {
  if (uploading) return
  uploading = true
  while (queue.length && rec.id.value) {
    const c = queue[0]
    try {
      const seg = await api.chunk(rec.id.value, c.seq, c.start, c.end, c.wav)
      rec.segments.value = [...rec.segments.value.filter((s) => s.seq !== seg.seq), seg].sort((a, b) => a.seq - b.seq)
      queue.shift()
      rec.pending.value = rec.pending.value.filter((s) => s !== c.seq)
    } catch (e: any) {
      if (e && e.status === 404) { queue.length = 0; rec.pending.value = []; break }
      // Offline or server hiccup: keep the chunk and try again shortly.
      await new Promise((r) => setTimeout(r, 3000))
    }
  }
  uploading = false
  if (!queue.length) { finishWaiters.forEach((f) => f()); finishWaiters = [] }
}

function onAudio(e: AudioProcessingEvent) {
  if (rec.state.value !== 'recording' || !resample) return
  const x = resample(e.inputBuffer.getChannelData(0))
  if (x.length) {
    buf.push(x)
    bufLen += x.length
    total += x.length
  }
  // Timer shows tenths; skip updates that would not change it to avoid re-rendering the panel.
  const t = Math.floor((total / RATE) * 10) / 10
  if (t !== rec.elapsed.value) rec.elapsed.value = t
  if (bufLen >= RATE * (chunkSec + 3)) cut(false)
  else if (bufLen >= RATE * chunkSec && silentTail(x)) cut(false)
}

function silentTail(x: Float32Array) {
  let e = 0
  for (let i = 0; i < x.length; i++) e += x[i] * x[i]
  return x.length > 0 && Math.sqrt(e / x.length) < 0.01
}

async function lockScreen() {
  try { wakeLock = await (navigator as any).wakeLock?.request('screen') } catch { /* unsupported */ }
}

/** iOS drops the wake lock and suspends the AudioContext when the page is hidden; resume on return. Installed once, on the first recording. */
let handlersOn = false
function installHandlers() {
  if (handlersOn) return
  handlersOn = true
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && (rec.state.value === 'recording' || rec.state.value === 'paused')) {
      lockScreen()
      ctx?.resume()
    }
  })
  // Warn before closing the tab mid-recording.
  window.addEventListener('beforeunload', (e) => {
    if (rec.state.value !== 'idle') { e.preventDefault(); e.returnValue = '' }
  })
}

export async function startRecording(title: string, sec: number, live = true) {
  if (rec.state.value !== 'idle') return
  rec.state.value = 'starting'
  installHandlers()
  try {
    // Create the AudioContext inside the tap handler so iOS lets it run.
    const AC = window.AudioContext || (window as any).webkitAudioContext
    ctx = new AC()
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    await ctx.resume()
    const r = await api.create(title, live)
    rec.id.value = r.id
    rec.title.value = r.title
    chunkSec = sec
    buf = []; bufLen = 0; chunkStart = 0; total = 0; seq = 0
    rec.segments.value = []; rec.pending.value = []; rec.elapsed.value = 0
    resample = makeResampler(ctx.sampleRate)
    source = ctx.createMediaStreamSource(stream)
    node = ctx.createScriptProcessor(4096, 1, 1)
    node.onaudioprocess = onAudio
    source.connect(node)
    analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    levelBuf = new Float32Array(analyser.fftSize)
    source.connect(analyser)
    // A muted sink keeps the processor pulling audio without echoing the mic.
    const mute = ctx.createGain()
    mute.gain.value = 0
    node.connect(mute).connect(ctx.destination)
    rec.state.value = 'recording'
    lockScreen()
  } catch (e) {
    teardown()
    rec.state.value = 'idle'
    rec.id.value = null
    throw e
  }
}

export function pauseRecording() {
  if (rec.state.value !== 'recording') return
  rec.state.value = 'paused'
  cut(true)
}

export function resumeRecording() {
  if (rec.state.value === 'paused') { rec.state.value = 'recording'; ctx?.resume() }
}

function teardown() {
  node?.disconnect(); source?.disconnect(); analyser?.disconnect()
  analyser = null; levelBuf = null
  stream?.getTracks().forEach((t) => t.stop())
  ctx?.close().catch(() => {})
  node = null; source = null; stream = null; ctx = null; resample = null
  try { wakeLock?.release() } catch { /* ignore */ }
  wakeLock = null
}

/** Stops capture, waits for every chunk to upload, then asks the server to finalize. */
export async function stopRecording(): Promise<string | null> {
  const id = rec.id.value
  if (!id || (rec.state.value !== 'recording' && rec.state.value !== 'paused')) return null
  rec.state.value = 'stopping'
  cut(true)
  teardown()
  if (queue.length || uploading) await new Promise<void>((r) => { finishWaiters.push(r); pump() })
  try { await api.finish(id, rec.elapsed.value) } catch { /* server resumes stale recordings */ }
  rec.state.value = 'idle'
  rec.id.value = null
  return id
}

/** Throws the recording away (server copy included). */
export async function discardRecording() {
  const id = rec.id.value
  rec.state.value = 'stopping'
  teardown()
  queue.length = 0
  rec.pending.value = []
  rec.id.value = null
  if (id) await api.remove(id).catch(() => {})
  rec.state.value = 'idle'
}

