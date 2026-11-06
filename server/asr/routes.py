"""Authenticated ASR REST routes."""
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from . import transcribe as tr

MAX_CHUNK = 20 * 1024 * 1024
MAX_UPLOAD = 500 * 1024 * 1024

def router(core, jobs):
    routes = APIRouter(prefix='/api/asr')
    store = jobs.store
    config = jobs.config

    async def stream(req, dst, limit):
        n = 0
        tmp = dst.with_name(dst.name + '.part')
        try:
            with tmp.open('wb') as f:
                async for chunk in req.stream():
                    n += len(chunk)
                    if n > limit:
                        raise HTTPException(413, 'file too large')
                    f.write(chunk)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        if not n:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, 'empty body')
        tmp.replace(dst)
        return n
    auth = {'dependencies': [Depends(core.require)]}

    class SettingsIn(BaseModel):
        api_base: str | None = None
        api_key: str | None = None
        clear_key: bool = False
        model: str | None = None
        language: str | None = None
        prompt: str | None = None
        chunk_sec: int | None = None
        retranscribe_on_finish: bool | None = None

    @routes.get('/settings', **auth)
    async def settings_get():
        return config.data.model_dump()

    @routes.patch('/settings', **auth)
    async def settings_patch(body: SettingsIn):
        values = body.model_dump(exclude_unset=True, exclude_none=True)
        values.pop('clear_key', None)
        if body.clear_key:
            values['api_key'] = ''
        if 'api_key' in values:
            values['api_key'] = values['api_key'].strip()
        merged = config.data.model_dump() | values
        try:
            new = config.model.model_validate(merged)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        for key in values:
            config.doc[key] = getattr(new, key)
        config.save()
        return new.model_dump()

    @routes.post('/settings/test', **auth)
    async def settings_test():
        return await tr.list_models(config.data)

    @routes.get('/recordings', **auth)
    async def recordings_list(q: str = ''):
        q = q.strip().lower()
        out = []
        for p in sorted((p for p in store.recordings.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
            try:
                m = store.load(p.name)
            except KeyError:
                continue
            if q and q not in m['title'].lower() and (q not in store.full_text(m).lower()):
                continue
            out.append(store.summary(m))
        return out

    class CreateIn(BaseModel):
        title: str | None = None
        live: bool = True

    @routes.post('/recordings', **auth)
    async def recording_create(body: CreateIn):
        title = (body.title or '').strip() or 'Recording ' + time.strftime('%m-%d %H:%M')
        m = store.create(title[:200], 'record')
        rid = m['id']
        if not body.live:
            m['live'] = False
        store.save(m)
        core.emit({'type': 'asr_changed', 'module': 'asr', 'id': rid})
        return store.public(m)

    @routes.post('/recordings/upload', **auth)
    async def recording_upload(req: Request, filename: str = 'audio', title: str = ''):
        m = store.create((title.strip() or Path(filename).stem or 'Upload')[:200], 'upload')
        rid = m['id']
        d = store.rec_dir(rid)
        ext = re.sub('[^a-z0-9]', '', Path(filename).suffix.lower())[:8] or 'bin'
        try:
            m['size'] = await stream(req, d / f'original.{ext}', MAX_UPLOAD)
            store.save(m)
        except BaseException:
            shutil.rmtree(d)
            raise
        jobs.changed(rid)
        jobs.spawn(rid, jobs.process_full(rid))
        return store.public(m)

    @routes.get('/recordings/{rid}', **auth)
    async def recording_get(rid):
        return store.public(store.get(rid))

    @routes.post('/recordings/{rid}/chunks', **auth)
    async def recording_chunk(rid, seq: int, start: float, end: float, req: Request):
        m = store.get(rid)
        if m['source'] != 'record':
            raise HTTPException(400, 'not a live recording')
        if seq < 0 or seq > 100000:
            raise HTTPException(400, 'bad seq')
        d = store.rec_dir(rid) / 'chunks'
        d.mkdir(exist_ok=True)
        path = d / f'{seq}.wav'
        await stream(req, path, MAX_CHUNK)
        seg = {'seq': seq, 'start': round(start, 3), 'end': round(end, 3), 'text': '', 'status': 'ok'}
        if m.get('live', True) and (not tr.is_silent(path)):
            try:
                seg['text'] = await tr.transcribe(path, config.data, store.tail(m, seq))
            except tr.TranscribeError as exc:
                seg.update(status='error', error=str(exc))

        def put(mm):
            store.upsert(mm, seg)
            mm['duration'] = max(mm['duration'], seg['end'])
        if await jobs.update(rid, put) is None:
            raise HTTPException(404, 'not found')
        return seg

    class FinishIn(BaseModel):
        duration: float | None = None

    @routes.post('/recordings/{rid}/finish', **auth)
    async def recording_finish(rid, body: FinishIn):
        store.get(rid)

        def f(m):
            if m['source'] != 'record':
                raise HTTPException(400, 'not a live recording')
            m['status'] = 'processing'
            m['duration'] = body.duration or m['duration']
        m = await jobs.update(rid, f)
        jobs.spawn(rid, jobs.finish_live(rid))
        return store.public(m)

    @routes.post('/recordings/{rid}/retranscribe', **auth)
    async def recording_retranscribe(rid):
        store.get(rid)
        d = store.rec_dir(rid)
        if not (d / 'audio.m4a').exists() and (not list(d.glob('original.*'))):
            raise HTTPException(409, 'audio is not ready')

        def begin(mm):
            if mm['status'] in ('recording', 'processing'):
                raise HTTPException(409, 'recording is busy')
            mm.update(status='processing', error=None, pending='full', text=None)
        m = await jobs.update(rid, begin)
        jobs.spawn(rid, jobs.process_full(rid))
        return store.public(m)

    @routes.post('/recordings/{rid}/segments/{seq}/retry', **auth)
    async def recording_retry(rid, seq: int):
        m = store.get(rid)
        seg = next((s for s in m['segments'] if s['seq'] == seq), None)
        if not seg:
            raise HTTPException(404, 'segment not found')
        d = store.rec_dir(rid)
        chunk = d / 'chunks' / f'{seq}.wav'
        tmp = None
        if not chunk.exists():
            if not (d / 'audio.m4a').exists():
                raise HTTPException(409, 'audio is not ready')
            tmp = d / f'retry-{seq}.wav'
            try:
                await tr.slice_wav(d / 'audio.m4a', tmp, seg['start'], seg['end'])
            except tr.TranscribeError as exc:
                tmp.unlink(missing_ok=True)
                raise HTTPException(500, str(exc)) from exc
            chunk = tmp
        new = {'seq': seq, 'start': seg['start'], 'end': seg['end'], 'text': '', 'status': 'ok'}
        try:
            if not tr.is_silent(chunk):
                new['text'] = await tr.transcribe(chunk, config.data, store.tail(m, seq))
        except tr.TranscribeError as exc:
            new.update(status='error', error=str(exc))
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)

        def replace(mm):
            store.upsert(mm, new)
            if mm['status'] == 'error' and any(s['status'] == 'ok' for s in mm['segments']) and (d / 'audio.m4a').exists():
                mm.update(status='done', error=None)
        await jobs.update(rid, replace)
        return new

    class PatchIn(BaseModel):
        title: str | None = None
        text: str | None = None
        reset_text: bool = False
        starred: bool | None = None

    @routes.patch('/recordings/{rid}', **auth)
    async def recording_patch(rid, body: PatchIn):
        store.get(rid)
        fields = body.model_fields_set

        def f(m):
            if body.title is not None and body.title.strip():
                m['title'] = body.title.strip()[:200]
            if body.reset_text or ('text' in fields and body.text is None):
                m['text'] = None
            elif body.text is not None:
                m['text'] = None if body.text == store.joined(m) else body.text
            if body.starred is not None:
                m['starred'] = body.starred
        return store.public(await jobs.update(rid, f))

    @routes.delete('/recordings/{rid}', **auth)
    async def recording_delete(rid):
        store.get(rid)
        await jobs.cancel(rid)
        async with store.lock(rid):
            shutil.rmtree(store.rec_dir(rid))
        core.emit({'type': 'asr_changed', 'module': 'asr', 'id': rid})
        return {'ok': True}

    @routes.get('/recordings/{rid}/audio', **auth)
    async def recording_audio(rid):
        store.get(rid)
        path = store.rec_dir(rid) / 'audio.m4a'
        if not path.exists():
            raise HTTPException(404, 'audio not ready')
        return FileResponse(path, media_type='audio/mp4', headers={'Cache-Control': 'private, max-age=3600'})

    def srt_time(t):
        ms = int(round(t * 1000))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'

    @routes.get('/recordings/{rid}/export', **auth)
    async def recording_export(rid, fmt: str = 'txt'):
        m = store.get(rid)
        if fmt not in ('txt', 'srt'):
            raise HTTPException(400, 'fmt must be txt or srt')

        def gen():
            if fmt == 'srt':
                i = 0
                for s in m['segments']:
                    if s.get('text'):
                        i += 1
                        yield f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}\n\n".encode()
            elif m.get('text') is not None:
                yield (m['text'] + '\n').encode()
            else:
                for s in m['segments']:
                    if s.get('text'):
                        yield (s['text'] + '\n').encode()
        fname = re.sub('[\\\\/:*?"<>|\\r\\n]', '_', m['title']) + '.' + fmt
        disposition = f"attachment; filename=\"export.{fmt}\"; filename*=UTF-8''{quote(fname)}"
        return StreamingResponse(gen(), media_type='text/plain; charset=utf-8',
                                 headers={'Content-Disposition': disposition})
    return routes
