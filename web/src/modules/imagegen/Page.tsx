// Image generation: compose area (prompt, ordered reference images, options) above the job grid.

import { useEffect, useRef, useState } from 'preact/hooks'
import { back, navigate } from '../../lib/router'
import { imagegenVersion, toast, toastError } from '../../lib/store'
import { BackButton, confirmDialog, Segmented, Sheet, TopBar, useScrolled } from '../../components/ui'
import { openViewer } from '../../components/ImageViewer'
import { IconCamera, IconChevronDown, IconClose, IconCopy, IconImage, IconMore, IconPlus, IconRefresh, IconTrash } from '../../components/icons'
import { IconAlert, IconArrowLeft, IconArrowRight, IconDownload, IconShare, IconSparkle } from '../../components/icons-apps'
import { aspectOf, DEFAULT_OPTS, imgApi, type ImgSettings, type Job, type Opts } from './api'

const OPTS_KEY = 'imagegen-opts'
const PAGE = 20
const MAX_REFS = 8
const SIZES = ['1024x1024', '1536x1024', '1024x1536']

interface Ref { file: File; url: string }

function loadOpts(): Opts {
  try { return { ...DEFAULT_OPTS, ...JSON.parse(localStorage.getItem(OPTS_KEY) || '{}') } } catch { return { ...DEFAULT_OPTS } }
}
const val = (e: Event) => (e.target as HTMLInputElement).value

export function ImagesPage() {
  const { scrolled, onScroll, ref } = useScrolled()
  const [cfg, setCfg] = useState<ImgSettings | null>(null)
  const [prompt, setPrompt] = useState('')
  const [refs, setRefs] = useState<Ref[]>([])
  const [mask, setMask] = useState<Ref | null>(null)
  const [opts, setOpts] = useState<Opts>(loadOpts)
  const [optsOpen, setOptsOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [more, setMore] = useState(false)
  const [menu, setMenu] = useState<Job | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const galleryRef = useRef<HTMLInputElement>(null)
  const cameraRef = useRef<HTMLInputElement>(null)
  const maskInput = useRef<HTMLInputElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)
  // Object URLs are released when the page goes away.
  const urls = useRef<string[]>([])
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), [])

  useEffect(() => { imgApi.settings().then(setCfg).catch(toastError) }, [])
  useEffect(() => { localStorage.setItem(OPTS_KEY, JSON.stringify(opts)) }, [opts])

  const loaded = useRef(0)
  const load = () => {
    const limit = Math.min(200, Math.max(PAGE, loaded.current))
    imgApi.jobs('', limit).then((l) => { loaded.current = l.length; setJobs(l); setMore(l.length >= limit) }).catch(toastError)
  }
  const ver = imagegenVersion.value
  useEffect(load, [ver])

  const loadMore = () => {
    const last = jobs?.[jobs.length - 1]
    if (!last) return
    imgApi.jobs(last.id, PAGE).then((l) => {
      loaded.current += l.length
      setJobs((j) => [...(j || []), ...l])
      setMore(l.length >= PAGE)
    }).catch(toastError)
  }

  // Elapsed time ticks only while a job is running and the page is visible.
  const running = !!jobs?.some((j) => j.status === 'running')
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => { if (document.visibilityState === 'visible') setNow(Date.now()) }, 1000)
    return () => clearInterval(t)
  }, [running])
  // Fallback if an event is missed: refresh slowly while running.
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => { if (document.visibilityState === 'visible') load() }, 5000)
    return () => clearInterval(t)
  }, [running])

  const grow = () => { const el = area.current; if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 220)}px` } }
  useEffect(grow, [prompt])

  const mk = (file: File): Ref => { const url = URL.createObjectURL(file); urls.current.push(url); return { file, url } }
  const addFiles = (files: FileList | null) => {
    if (!files?.length) return
    const room = MAX_REFS - refs.length
    if (files.length > room) toast(`At most ${MAX_REFS} reference images`, 'error')
    setRefs((r) => [...r, ...Array.from(files).slice(0, Math.max(0, room)).map(mk)])
  }
  const move = (i: number, d: number) => setRefs((r) => {
    const j = i + d
    if (j < 0 || j >= r.length) return r
    const n = r.slice(); [n[i], n[j]] = [n[j], n[i]]
    return n
  })
  const setOpt = <K extends keyof Opts>(k: K, v: Opts[K]) => setOpts((o) => ({ ...o, [k]: v }))

  const model = opts.model || cfg?.default_model || ''
  const models = cfg ? [...new Set([...cfg.models, ...(cfg.default_model ? [cfg.default_model] : []), ...(opts.model ? [opts.model] : [])])] : []
  const needsConfig = cfg !== null && (!cfg.api_base.trim() || !cfg.api_key.trim())

  const generate = async () => {
    const text = prompt.trim()
    if (!text) return toast('Write a prompt first', 'error')
    if (mask && refs.length === 0) return toast('A mask needs at least one reference image', 'error')
    let size = opts.size
    if (size === 'custom') {
      if (!/^\d+$/.test(opts.w) || !/^\d+$/.test(opts.h) || +opts.w < 1 || +opts.h < 1) return toast('Enter a custom size as width and height', 'error')
      size = `${+opts.w}x${+opts.h}`
    }
    const fd = new FormData()
    fd.append('prompt', text)
    if (model) fd.append('model', model)
    fd.append('n', String(opts.n))
    if (size) fd.append('size', size)
    if (opts.quality) fd.append('quality', opts.quality)
    if (opts.background) fd.append('background', opts.background)
    if (opts.output_format) fd.append('output_format', opts.output_format)
    if (opts.compression !== null && (opts.output_format === 'jpeg' || opts.output_format === 'webp')) fd.append('output_compression', String(opts.compression))
    if (opts.moderation) fd.append('moderation', opts.moderation)
    for (const r of refs) fd.append('images[]', r.file, r.file.name)
    if (mask) fd.append('mask', mask.file, mask.file.name)
    setSending(true)
    try {
      const job = await imgApi.create(fd)
      setJobs((j) => [job, ...(j || []).filter((x) => x.id !== job.id)])
      setNow(Date.now())
    } catch (e) { toastError(e) } finally { setSending(false) }
  }

  // ----- job actions -----
  const fetchFile = async (url: string, name: string) => {
    const res = await fetch(url, { credentials: 'same-origin' })
    if (!res.ok) throw new Error(`Could not load ${name}`)
    const blob = await res.blob()
    return new File([blob], name, { type: blob.type })
  }
  const download = (j: Job) => {
    setMenu(null)
    j.images.forEach((im, i) => setTimeout(() => {
      const a = document.createElement('a')
      a.href = im.url; a.download = im.name
      document.body.appendChild(a); a.click(); a.remove()
    }, i * 250))
  }
  const share = async (j: Job) => {
    setMenu(null)
    try {
      const files = await Promise.all(j.images.map((im) => fetchFile(im.url, im.name)))
      if (navigator.canShare?.({ files })) await navigator.share({ files, text: j.prompt })
      else if (navigator.share) await navigator.share({ title: j.prompt, url: new URL(j.images[0].url, location.href).href })
      else toast('Sharing is not supported here. Use Download.', 'error')
    } catch (e: any) { if (e?.name !== 'AbortError') toastError(e) }
  }
  const useAsRef = async (j: Job) => {
    setMenu(null)
    try {
      const room = MAX_REFS - refs.length
      if (room <= 0) return toast(`At most ${MAX_REFS} reference images`, 'error')
      const files = await Promise.all(j.images.slice(0, room).map((im) => fetchFile(im.url, im.name)))
      setRefs((r) => [...r, ...files.map(mk)])
      toast(`Added ${files.length} reference image${files.length > 1 ? 's' : ''}`)
      ref.current?.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (e) { toastError(e) }
  }
  const reuse = (j: Job) => {
    setMenu(null)
    setPrompt(j.prompt)
    const p = j.params
    const custom = p.size && p.size !== 'auto' && !SIZES.includes(p.size)
    const [w, h] = custom ? p.size!.split('x') : [opts.w, opts.h]
    setOpts({ model: j.model, size: custom ? 'custom' : p.size === 'auto' ? '' : p.size || '', w, h, quality: p.quality || '', n: p.n || 1,
      background: p.background || '', output_format: p.output_format || '', compression: p.output_compression ?? null, moderation: p.moderation || '' })
    ref.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const retry = async (j: Job) => {
    setMenu(null)
    try { const n = await imgApi.retry(j.id); setJobs((l) => [n, ...(l || [])]); setNow(Date.now()) } catch (e) { toastError(e) }
  }
  const remove = async (j: Job) => {
    setMenu(null)
    if (!(await confirmDialog({ title: 'Delete this job?', body: 'The images are removed from the server.', confirm: 'Delete', danger: true }))) return
    try { await imgApi.remove(j.id); setJobs((l) => (l || []).filter((x) => x.id !== j.id)) } catch (e) { toastError(e) }
  }

  const compress = opts.output_format === 'jpeg' || opts.output_format === 'webp'

  return (
    <div class="page images-page wide-page">
      <TopBar scrolled={scrolled} left={<BackButton label="More" onClick={() => back({ name: 'more' })} />}>
        {scrolled && <span class="fade-in">Image generation</span>}
      </TopBar>
      <div class="page-scroll" ref={ref} onScroll={onScroll}>
        <div class="container">
          <h1 class="large-title rise">Image generation</h1>

          {needsConfig && (
            <button class="img-setup rise" onClick={() => navigate({ name: 'settings-section', module: 'apps', section: 'imagegen' })}>
              <IconAlert />
              <span><b>Set up the image API</b><br />Add an API base and key in Settings, Apps, Image generation.</span>
              <IconArrowRight />
            </button>
          )}

          <div class="img-compose rise" style={{ '--i': 1 }}>
            <textarea ref={area} class="img-prompt" rows={3} value={prompt} placeholder="Describe the image you want"
              onInput={(e) => setPrompt(val(e))} />
            <div class="img-refs">
              {refs.map((r, i) => (
                <div key={r.url} class="img-ref">
                  <img src={r.url} alt={`Reference ${i + 1}`} loading="lazy" decoding="async" />
                  <button class="img-ref-x" onClick={() => setRefs((l) => l.filter((x) => x !== r))} aria-label="Remove reference"><IconClose /></button>
                  <div class="img-ref-order">
                    <button disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move earlier"><IconArrowLeft /></button>
                    <span>{i + 1}</span>
                    <button disabled={i === refs.length - 1} onClick={() => move(i, 1)} aria-label="Move later"><IconArrowRight /></button>
                  </div>
                </div>
              ))}
              <button class="img-add" onClick={() => galleryRef.current?.click()} disabled={refs.length >= MAX_REFS} aria-label="Add reference images"><IconImage /><IconPlus class="img-add-plus" /></button>
              <button class="img-add" onClick={() => cameraRef.current?.click()} disabled={refs.length >= MAX_REFS} aria-label="Take a photo"><IconCamera /></button>
            </div>
            <input ref={galleryRef} type="file" accept="image/*" multiple hidden onChange={(e) => { addFiles((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = '' }} />
            <input ref={cameraRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { addFiles((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = '' }} />

            <button class="img-opts-toggle" onClick={() => setOptsOpen(!optsOpen)} aria-expanded={optsOpen}>
              Options<span class="img-opts-sum">{model}{opts.n > 1 ? ` x${opts.n}` : ''}</span>
              <IconChevronDown class={optsOpen ? 'open' : ''} />
            </button>
            {optsOpen && (
              <div class="img-opts">
                <label class="img-opt"><span>Model</span>
                  <select class="select" value={opts.model || ''} onChange={(e) => setOpt('model', val(e))}>
                    <option value="">{cfg?.default_model ? `Default (${cfg.default_model})` : 'Default'}</option>
                    {models.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select></label>
                <label class="img-opt"><span>Size</span>
                  <select class="select" value={opts.size} onChange={(e) => setOpt('size', val(e))}>
                    <option value="">Auto</option>
                    {SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
                    <option value="custom">Custom</option>
                  </select></label>
                {opts.size === 'custom' && (
                  <div class="img-opt img-custom"><span>Width x height</span>
                    <div>
                      <input class="input" inputMode="numeric" value={opts.w} onInput={(e) => setOpt('w', val(e))} aria-label="Width" />
                      <i>x</i>
                      <input class="input" inputMode="numeric" value={opts.h} onInput={(e) => setOpt('h', val(e))} aria-label="Height" />
                    </div></div>
                )}
                <label class="img-opt"><span>Quality</span>
                  <select class="select" value={opts.quality} onChange={(e) => setOpt('quality', val(e))}>
                    <option value="">Not set</option>
                    {['auto', 'low', 'medium', 'high'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select></label>
                <div class="img-opt"><span>Count</span>
                  <Segmented value={String(opts.n)} onChange={(v) => setOpt('n', Number(v))}
                    options={['1', '2', '3', '4'].map((v) => ({ value: v, label: v }))} /></div>
                <label class="img-opt"><span>Background</span>
                  <select class="select" value={opts.background} onChange={(e) => setOpt('background', val(e))}>
                    <option value="">Not set</option>
                    {['auto', 'opaque', 'transparent'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select></label>
                <label class="img-opt"><span>Output format</span>
                  <select class="select" value={opts.output_format} onChange={(e) => setOpt('output_format', val(e))}>
                    <option value="">Not set</option>
                    {['png', 'jpeg', 'webp'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select></label>
                {compress && (
                  <label class="img-opt"><span>Compression: {opts.compression === null ? 'default' : opts.compression}</span>
                    <input class="range" type="range" min={0} max={100} value={opts.compression ?? 80} onInput={(e) => setOpt('compression', Number(val(e)))} />
                    {opts.compression !== null && <button type="button" class="link" onClick={() => setOpt('compression', null)}>Use default</button>}</label>
                )}
                <label class="img-opt"><span>Moderation</span>
                  <select class="select" value={opts.moderation} onChange={(e) => setOpt('moderation', val(e))}>
                    <option value="">Not set</option>
                    {['auto', 'low'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select></label>
                <div class="img-opt"><span>Mask image</span>
                  {mask
                    ? <div class="img-ref small"><img src={mask.url} alt="Mask" /><button class="img-ref-x" onClick={() => setMask(null)} aria-label="Remove mask"><IconClose /></button></div>
                    : <button class="btn small" onClick={() => maskInput.current?.click()}><IconPlus width={16} />Add mask</button>}
                  <span class="fhint">Needs at least one reference image.</span>
                  <input ref={maskInput} type="file" accept="image/*" hidden onChange={(e) => { const f = (e.target as HTMLInputElement).files?.[0]; (e.target as HTMLInputElement).value = ''; if (f) setMask(mk(f)) }} /></div>
              </div>
            )}
            <button class="btn primary block img-go" onClick={generate} disabled={sending || !prompt.trim()}>
              {sending ? <span class="spinner tiny" /> : <IconSparkle width={18} />}Generate
            </button>
          </div>

          {jobs === null && <div class="img-grid">{[0, 1].map((i) => <div key={i} class="skeleton img-skel" />)}</div>}
          {jobs && jobs.length === 0 && (
            <div class="empty fade-in"><div class="empty-icon"><IconImage width={48} height={48} /></div><h3>No images yet</h3><p>Your generated images appear here.</p></div>
          )}
          {jobs && jobs.length > 0 && (
            <div class="img-grid">
              {jobs.map((j) => <JobCard key={j.id} j={j} now={now} onMenu={setMenu} />)}
            </div>
          )}
          {more && <button class="btn block img-more" onClick={loadMore}>Load more</button>}
        </div>
      </div>

      <Sheet open={!!menu} onClose={() => setMenu(null)} title={menu ? menu.prompt.slice(0, 60) : ''}>
        {menu && (
          <div class="menu">
            {menu.images.length > 0 && <>
              <button onClick={() => download(menu)}><IconDownload />Download</button>
              <button onClick={() => share(menu)}><IconShare />Share</button>
              <button onClick={() => useAsRef(menu)}><IconImage />Use as reference</button>
            </>}
            <button onClick={() => reuse(menu)}><IconCopy />Reuse prompt and options</button>
            <button onClick={() => retry(menu)}><IconRefresh />Retry</button>
            <button class="danger" onClick={() => remove(menu)}><IconTrash />Delete</button>
          </div>
        )}
      </Sheet>
    </div>
  )
}

function elapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

function JobCard({ j, now, onMenu }: { j: Job; now: number; onMenu: (j: Job) => void }) {
  const view = (i: number) => openViewer(j.images.map((im) => ({ src: im.url, name: im.name, download: im.url })), i)
  return (
    <div class={`img-card ${j.status}`}>
      {j.status === 'running' && (
        <div class="img-wait" style={{ aspectRatio: aspectOf(j.params.size) }}>
          <span>{elapsed(now - j.created_at * 1000)}</span>
        </div>
      )}
      {j.status === 'error' && (
        <div class="img-err"><IconAlert /><span class="selectable">{j.error || 'Generation failed'}</span></div>
      )}
      {j.status === 'done' && (
        <div class={`img-out n${Math.min(j.images.length, 4)}`}>
          {j.images.map((im, i) => (
            <button key={im.name} class="img-out-btn" onClick={() => view(i)} aria-label={`Open image ${i + 1}`}
              style={im.width && im.height ? { aspectRatio: `${im.width} / ${im.height}` } : undefined}>
              <img src={im.url} alt={j.prompt} loading="lazy" decoding="async" />
            </button>
          ))}
        </div>
      )}
      <div class="img-foot">
        <span class="img-prompt-line">{j.prompt}</span>
        <button class="icon-btn" onClick={() => onMenu(j)} aria-label="Job actions"><IconMore /></button>
      </div>
      <div class="img-meta">
        <span>{j.model}</span>
        {j.references.length > 0 && <span>{j.references.length} ref</span>}
        {j.status === 'done' && j.duration_ms !== null && <span>{elapsed(j.duration_ms)}</span>}
      </div>
    </div>
  )
}
