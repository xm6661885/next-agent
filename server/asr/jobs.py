"""Live finalization, full transcription and restart recovery."""
import asyncio
import time
from . import transcribe as tr

PIECE_SEC = 60.0

class AsrJobs:

    def __init__(self, core, config, store):
        self.core = core
        self.config = config
        self.store = store
        self.tasks = {}

    async def update(self, rid, fn):
        async with self.store.lock(rid):
            try:
                m = self.store.load(rid)
            except KeyError:
                return None
            fn(m)
            self.store.save(m)
            self.changed(rid)
            return m

    def changed(self, rid):
        self.core.emit({'type': 'asr_changed', 'module': 'asr', 'id': rid})

    def spawn(self, rid, coro):
        old = self.tasks.get(rid)
        if old and (not old.done()):
            old.cancel()
        task = asyncio.create_task(coro)
        self.tasks[rid] = task
        task.add_done_callback(lambda t: self.tasks.get(rid) is t and self.tasks.pop(rid, None))

    async def process_full(self, rid):
        d = self.store.rec_dir(rid)
        work = d / 'work.wav'
        try:
            orig = next(iter(sorted(d.glob('original.*'))), None)
            src = orig or d / 'audio.m4a'
            if not src.exists():
                raise tr.TranscribeError('no audio file')
            if not (d / 'audio.m4a').exists():
                await tr.to_m4a(src, d / 'audio.m4a')
            await tr.run('ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', str(src), '-vn', '-ac', '1',
                         '-ar', '16000', '-c:a', 'pcm_s16le', str(work))
            total = await tr.duration(work) or await tr.duration(src)
            pieces = await tr.plan_pieces(work, total, PIECE_SEC)
            size = (d / 'audio.m4a').stat().st_size

            def start(m):
                m.update(duration=total, size=size, segments=[], text=None, error=None, progress={'done': 0, 'total': len(pieces)})
                m['pending'] = 'full'
            if await self.update(rid, start) is None:
                return
            prev = ''
            ok = 0
            for i, (a, b) in enumerate(pieces):
                piece = d / f'piece-{i}.wav'
                seg = {'seq': i, 'start': round(a, 3), 'end': round(b, 3), 'text': '', 'status': 'ok'}
                try:
                    await tr.slice_wav(work, piece, a, b)
                    if not tr.is_silent(piece):
                        seg['text'] = await tr.transcribe(piece, self.config.data, prev[-200:])
                    ok += 1
                except tr.TranscribeError as exc:
                    seg.update(status='error', error=str(exc))
                finally:
                    piece.unlink(missing_ok=True)
                if seg['text']:
                    prev = seg['text']

                def add(m, seg=seg, i=i):
                    self.store.upsert(m, seg)
                    m['progress'] = {'done': i + 1, 'total': len(pieces)}
                if await self.update(rid, add) is None:
                    return

            def finish(m):
                m.pop('pending', None)
                m['progress'] = None
                error = next((s['error'] for s in m['segments'] if s.get('error')), 'failed')
                m.update(status='done' if ok else 'error', error=None if ok else error)
            await self.update(rid, finish)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.fail(rid, str(exc))
        finally:
            work.unlink(missing_ok=True)

    async def finish_live(self, rid):
        d = self.store.rec_dir(rid)
        wavs = sorted((d / 'chunks').glob('*.wav'), key=lambda p: int(p.stem)) if (d / 'chunks').exists() else []
        try:
            if await self.update(rid, lambda m: m.update(status='processing')) is None:
                return
            if not wavs:
                raise tr.TranscribeError('no audio was recorded')
            await tr.concat_wavs(wavs, d / 'audio.m4a')
            dur = await tr.duration(d / 'audio.m4a')
            size = (d / 'audio.m4a').stat().st_size

            def done(m):
                m.update(size=size, error=None)
                m['duration'] = dur or m['duration']
                if self.config.data.retranscribe_on_finish or not m.get('live', True):
                    m['pending'] = 'full'
                else:
                    m['status'] = 'done'
            m = await self.update(rid, done)
            if m and m.get('pending') == 'full':
                await self.process_full(rid)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.fail(rid, str(exc))

    async def startup(self):
        now = time.time()
        for name in sorted((p.name for p in self.store.recordings.iterdir() if p.is_dir()), reverse=True):
            try:
                m = self.store.load(name)
            except KeyError:
                continue
            if m['status'] == 'processing':
                full = m['source'] == 'upload' or m.get('pending') == 'full'
                self.spawn(name, self.process_full(name) if full else self.finish_live(name))
            elif m['status'] == 'recording' and now - m['created_at'] > 6 * 3600:
                self.spawn(name, self.finish_live(name))

    async def fail(self, rid, error):
        def apply(m):
            m.pop('pending', None)
            m.update(status='error', error=error, progress=None)
        await self.update(rid, apply)

    async def cancel(self, rid):
        task = self.tasks.pop(rid, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
