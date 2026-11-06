"""Adapted from asr-web/tests/test_api.py; external transcription uses MockTransport."""
import asyncio
import io
import math
import struct
import time
import wave
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from server.asr import mount, transcribe as tr
from server.asr import routes
from server.asr.config import AsrConfig
from server.auth import Auth, COOKIE
from server.core import Core
from server.paths import DataDir

BASE = '/api/asr/recordings'


def wav_bytes(amp=8000, sec=0.1):
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b''.join(struct.pack('<h', int(amp * math.sin(i * 2 * math.pi * 440 / 16000)))
                                 for i in range(int(16000 * sec))))
    return out.getvalue()


@pytest.fixture
async def asr(tmp_path, monkeypatch):
    paths = DataDir(tmp_path)
    paths.prepare()
    auth = Auth(paths, SimpleNamespace(config=SimpleNamespace(server=SimpleNamespace(password_hash='hash'))))
    events, calls = [], []
    core = Core(paths, auth, auth.require_auth, events.append, lambda: None)
    app = FastAPI()
    mount(app, core)
    state = SimpleNamespace(core=core, jobs=core.modules['asr'], events=events, calls=calls, fail=None)
    def handler(req):
        if req.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': 'whisper-1'}]})
        calls.append(req)
        if state.fail:
            return httpx.Response(state.fail, text='boom')
        return httpx.Response(200, json={'text': f' hello {len(calls)} '})
    monkeypatch.setattr(tr, 'transport', httpx.MockTransport(handler))
    monkeypatch.setattr(tr, '_sem', asyncio.Semaphore(1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test',
                               cookies={COOKIE: auth.token()}) as http:
        state.http = http
        await http.patch('/api/asr/settings', json={'api_base': 'https://asr.test/v1/', 'api_key': 'secret'})
        yield state
    await core.stop()


async def create(asr, **values):
    response = await asr.http.post(BASE, json=values)
    assert response.status_code == 200
    return response.json()['id']


async def settle(asr, rid):
    task = asr.jobs.tasks.get(rid)
    if task:
        await asyncio.wait_for(task, 30)
    return (await asr.http.get(f'{BASE}/{rid}')).json()


async def chunk(asr, rid, seq=0, silent=False):
    return await asr.http.post(f'{BASE}/{rid}/chunks', params={'seq': seq, 'start': seq * .1, 'end': (seq + 1) * .1},
                               content=wav_bytes(amp=0 if silent else 8000))


async def upload(asr):
    response = await asr.http.post(BASE + '/upload', params={'filename': '讲座.wav'}, content=wav_bytes())
    assert response.status_code == 200
    return response.json()['id']


async def test_settings_clear_key_and_raw_config(asr):
    c = asr.http
    settings = (await c.get('/api/asr/settings')).json()
    assert settings['api_key'] == 'secret' and settings['api_base'] == 'https://asr.test/v1'
    assert not {'has_key', 'key_hint'} & settings.keys()
    assert (await c.patch('/api/asr/settings', json={'model': '', 'chunk_sec': 60})).json()['model'] == ''
    assert (await c.patch('/api/asr/settings', json={'chunk_sec': 2})).status_code == 422
    assert (await c.patch('/api/asr/settings', json={'api_base': 'bad'})).status_code == 422
    assert (await c.patch('/api/asr/settings', json={'prompt': None})).status_code == 200
    assert (await c.post('/api/asr/settings/test')).json()['models'] == ['whisper-1']
    config = asr.core.modules['raw_configs']['asr']
    assert config.path.name == 'asr.toml'
    config.replace_raw(config.path.read_text().replace('chunk_sec = 60', 'chunk_sec = 5'))
    assert (await c.get('/api/asr/settings')).json()['chunk_sec'] == 5
    assert (await c.patch('/api/asr/settings', json={'api_key': ''})).json()['api_key'] == ''
    assert not (await c.post('/api/asr/settings/test')).json()['ok']


async def test_live_flow_silence_context_range_export(asr):
    rid = await create(asr, title='Meeting')
    assert (await chunk(asr, rid)).json()['text'] == 'hello 1'
    assert (await chunk(asr, rid, 1, silent=True)).json()['text'] == ''
    assert len(asr.calls) == 1
    assert (await chunk(asr, rid, 2)).json()['text'] == 'hello 2'
    assert b'hello 1' in asr.calls[-1].content
    response = await asr.http.post(f'{BASE}/{rid}/finish', json={'duration': .3})
    assert response.json()['status'] == 'processing'
    m = await settle(asr, rid)
    assert m['status'] == 'done' and m['size'] > 0 and abs(m['duration'] - .3) < .1
    assert m['text'] == 'hello 1\nhello 2'
    audio = await asr.http.get(f'{BASE}/{rid}/audio', headers={'Range': 'bytes=0-9'})
    assert audio.status_code == 206 and len(audio.content) == 10
    assert audio.headers['content-range'].startswith('bytes 0-9/')
    srt = await asr.http.get(f'{BASE}/{rid}/export?fmt=srt')
    assert '00:00:00,200 --> 00:00:00,300' in srt.text
    assert "filename*=UTF-8''Meeting.srt" in srt.headers['content-disposition']
    assert [event['id'] for event in asr.events] == [rid] * len(asr.events)
    assert len(asr.events) >= 6 and all(e['type'] == 'asr_changed' and e['module'] == 'asr' for e in asr.events)


@pytest.mark.parametrize('live,retranscribe', [(False, False), (True, True)])
async def test_full_transcription_after_finish(asr, live, retranscribe):
    await asr.http.patch('/api/asr/settings', json={'retranscribe_on_finish': retranscribe})
    rid = await create(asr, live=live)
    await chunk(asr, rid)
    assert len(asr.calls) == int(live)
    await asr.http.post(f'{BASE}/{rid}/finish', json={})
    m = await settle(asr, rid)
    assert m['status'] == 'done' and m['text'] and len(asr.calls) == int(live) + 1
    assert 'pending' not in m and m['progress'] is None


async def test_chunk_error_retry_and_replacement(asr):
    rid = await create(asr)
    asr.fail = 401
    seg = (await chunk(asr, rid)).json()
    assert seg['status'] == 'error' and '401' in seg['error'] and len(asr.calls) == 1
    asr.fail = None
    seg = (await asr.http.post(f'{BASE}/{rid}/segments/0/retry')).json()
    assert seg['status'] == 'ok' and seg['text']
    await chunk(asr, rid)
    m = (await asr.http.get(f'{BASE}/{rid}')).json()
    assert len(m['segments']) == 1 and m['text'] == 'hello 3'


async def test_upload_crud_patch_search_retranscribe(asr):
    rid = await upload(asr)
    m = await settle(asr, rid)
    assert m['source'] == 'upload' and m['title'] == '讲座' and m['status'] == 'done'
    c, path = asr.http, f'{BASE}/{rid}'
    assert (await c.get(BASE, params={'q': '讲'})).json()[0]['id'] == rid
    assert (await c.get(BASE, params={'q': ' HELLO '})).json()[0]['preview'] == m['text']
    assert (await c.get(BASE, params={'q': 'zzz'})).json() == []
    m = (await c.patch(path, json={'title': 'x' * 201, 'text': 'edited', 'starred': True})).json()
    assert len(m['title']) == 200 and m['edited'] and m['starred']
    assert (await c.get(path + '/export')).text == 'edited\n'
    for reset in ({'text': None}, {'reset_text': True}, {'text': 'hello 1'}):
        await c.patch(path, json={'text': 'edit'})
        m = (await c.patch(path, json=reset)).json()
        assert not m['edited'] and m['text'] == 'hello 1'
    m = (await c.patch(path, json={'text': '', 'title': '   ', 'starred': False})).json()
    assert m['text'] == '' and m['edited'] and not m['starred'] and len(m['title']) == 200
    await c.patch(path, json={'title': '讲座:/test\n'})
    export = await c.get(path + '/export?fmt=txt')
    assert "filename*=UTF-8''%E8%AE%B2%E5%BA%A7__test.txt" in export.headers['content-disposition']
    assert (await c.get(path + '/export?fmt=pdf')).status_code == 400
    assert (await c.post(path + '/retranscribe')).json()['status'] == 'processing'
    assert (await settle(asr, rid))['status'] == 'done'
    assert (await c.delete(path)).json() == {'ok': True}
    assert (await c.get(path)).status_code == 404


async def test_retry_slices_saved_audio_and_recovers_error(asr, monkeypatch):
    asr.fail = 401
    rid = await upload(asr)
    assert (await settle(asr, rid))['status'] == 'error'
    asr.fail = None
    path = f'{BASE}/{rid}/segments/0/retry'
    seg = (await asr.http.post(path)).json()
    assert seg['status'] == 'ok' and seg['text']
    assert (await asr.http.get(f'{BASE}/{rid}')).json()['status'] == 'done'
    assert not list(asr.jobs.store.rec_dir(rid).glob('retry-*.wav'))
    async def fail(*args):
        raise tr.TranscribeError('cannot slice')
    monkeypatch.setattr(tr, 'slice_wav', fail)
    assert (await asr.http.post(path)).status_code == 500


async def test_upload_without_key_and_empty_finish(asr):
    await asr.http.patch('/api/asr/settings', json={'clear_key': True})
    rid = await upload(asr)
    m = await settle(asr, rid)
    assert m['status'] == 'error' and 'API key' in m['error']
    rid = await create(asr)
    await asr.http.post(f'{BASE}/{rid}/finish', json={})
    assert 'no audio' in (await settle(asr, rid))['error']


async def test_streaming_limits_and_partial_cleanup(asr, monkeypatch):
    assert routes.MAX_UPLOAD == 500 * 1024 * 1024
    assert routes.MAX_CHUNK == 20 * 1024 * 1024
    monkeypatch.setattr(routes, 'MAX_UPLOAD', 10)
    monkeypatch.setattr(routes, 'MAX_CHUNK', 10)
    received = []
    async def data():
        for part in (b'12345', b'67890', b'x'):
            received.append(part)
            yield part
    assert (await asr.http.post(BASE + '/upload', content=data())).status_code == 413
    assert len(received) == 3 and list(asr.jobs.store.recordings.iterdir()) == []
    assert (await asr.http.post(BASE + '/upload', content=b'')).status_code == 400
    rid = await create(asr)
    path = f'{BASE}/{rid}/chunks?seq=0&start=0&end=1'
    assert (await asr.http.post(path, content=b'')).status_code == 400
    assert (await asr.http.post(path, content=b'x' * 11)).status_code == 413
    assert not list((asr.jobs.store.rec_dir(rid) / 'chunks').iterdir())
    async def disconnect():
        yield b'123'
        raise RuntimeError('client disconnected')
    with pytest.raises(RuntimeError, match='disconnected'):
        await asr.http.post(BASE + '/upload', content=disconnect())
    assert len(list(asr.jobs.store.recordings.iterdir())) == 1


async def test_route_errors_and_auth(asr):
    rid = await create(asr)
    c, path = asr.http, f'{BASE}/{rid}'
    assert (await c.get(BASE + '/..%2Fconfig')).status_code == 404
    assert (await c.get(path + '/audio')).status_code == 404
    assert (await c.post(path + '/retranscribe')).status_code == 409
    assert (await c.post(path + '/segments/99/retry')).status_code == 404
    assert (await chunk(asr, rid, -1)).status_code == 400
    assert (await chunk(asr, rid, 100001)).status_code == 400
    (asr.jobs.store.rec_dir(rid) / 'audio.m4a').write_bytes(b'audio')
    assert (await c.post(path + '/retranscribe')).json()['detail'] == 'recording is busy'
    m = asr.jobs.store.load(rid)
    m['source'] = 'upload'
    asr.jobs.store.save(m)
    assert (await chunk(asr, rid)).status_code == 400
    assert (await c.post(path + '/finish', json={})).status_code == 400
    c.cookies.clear()
    for method, path, kwargs in [('get', BASE, {}), ('post', BASE, {'json': {}}),
                                 ('get', '/api/asr/settings', {}), ('get', f'{BASE}/{rid}/audio', {})]:
        assert (await getattr(c, method)(path, **kwargs)).status_code == 401


async def test_progress_partial_failure_silence_and_cleanup(asr, monkeypatch):
    snapshots = []
    async def pieces(*args):
        return [(0., .03), (.03, .06), (.06, .1)]
    async def slice_piece(src, dst, start, end):
        dst.write_bytes(wav_bytes(amp=0 if start == .06 else 8000))
    monkeypatch.setattr(tr, 'plan_pieces', pieces)
    monkeypatch.setattr(tr, 'slice_wav', slice_piece)
    original_emit = asr.core.emit
    def emit(event):
        original_emit(event)
        snapshots.append(asr.jobs.store.public(asr.jobs.store.load(event['id'])))
    asr.core.emit = emit
    asr.fail = 401
    rid = await upload(asr)
    m = await settle(asr, rid)
    assert m['status'] == 'done'  # Silent piece succeeds even when both spoken pieces fail.
    assert [s['status'] for s in m['segments']] == ['error', 'error', 'ok']
    assert [m['progress'] for m in snapshots if m['progress']] == [
        {'done': i, 'total': 3} for i in range(4)]
    assert m['progress'] is None and 'pending' not in m
    directory = asr.jobs.store.rec_dir(rid)
    assert not (directory / 'work.wav').exists() and not list(directory.glob('piece-*.wav'))


async def test_startup_resume_processing_and_six_hour_stale(asr, monkeypatch):
    seen = []
    async def full(rid):
        seen.append(('full', rid))
    async def finish(rid):
        seen.append(('finish', rid))
    monkeypatch.setattr(asr.jobs, 'process_full', full)
    monkeypatch.setattr(asr.jobs, 'finish_live', finish)
    ids = [await create(asr) for _ in range(6)]
    for rid, values in zip(ids, [dict(status='processing', source='upload'), dict(status='processing', pending='full'),
                                 dict(status='processing'), dict(created_at=time.time() - 6 * 3600 - 1),
                                 dict(created_at=time.time() - 6 * 3600 + 60), dict(status='done')]):
        m = asr.jobs.store.load(rid)
        m.update(values)
        asr.jobs.store.save(m)
    bad = asr.jobs.store.recordings / 'corrupt'
    bad.mkdir()
    (bad / 'meta.json').write_text('{')
    await asr.jobs.startup()
    await asyncio.gather(*asr.jobs.tasks.values())
    assert set(seen) == {('full', ids[0]), ('full', ids[1]), ('finish', ids[2]), ('finish', ids[3])}


async def test_per_recording_lock_and_delete_cancel(asr):
    rid = await create(asr)
    lock = asr.jobs.store.lock(rid)
    assert lock is asr.jobs.store.lock(rid)
    await lock.acquire()
    patch = asyncio.create_task(asr.http.patch(f'{BASE}/{rid}', json={'title': 'locked'}))
    await asyncio.sleep(0)
    assert not patch.done()
    lock.release()
    assert (await patch).json()['title'] == 'locked'
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    asr.jobs.spawn(rid, work())
    await started.wait()
    assert (await asr.http.delete(f'{BASE}/{rid}')).status_code == 200
    assert cancelled.is_set() and not asr.jobs.store.rec_dir(rid).exists()
    assert await asr.jobs.update(rid, lambda m: m.update(title='resurrected')) is None


@pytest.mark.parametrize('failure,attempts', [(401, 1), (503, 2), ('network', 2)])
async def test_transcription_retries(asr, tmp_path, monkeypatch, failure, attempts):
    calls = []
    def handler(req):
        calls.append(req)
        if failure == 'network':
            raise httpx.ConnectError('offline', request=req)
        return httpx.Response(failure, text='boom')
    monkeypatch.setattr(tr, 'transport', httpx.MockTransport(handler))
    path = tmp_path / 'tiny.wav'
    path.write_bytes(wav_bytes())
    with pytest.raises(tr.TranscribeError):
        await tr.transcribe(path, asr.jobs.config.data)
    assert len(calls) == attempts


async def test_transcription_semaphore_prompt_and_plain_response(asr, tmp_path, monkeypatch):
    active, maximum = 0, 0
    async def handler(req):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        assert b'name="language"\r\n\r\nzh' in req.content
        assert b'Bearer secret' not in req.content and req.headers['authorization'] == 'Bearer secret'
        assert b'audio/wav' in req.content and b'name="response_format"\r\n\r\njson' in req.content
        await asyncio.sleep(.001)
        active -= 1
        return httpx.Response(200, text=' plain text ')
    monkeypatch.setattr(tr, 'transport', httpx.MockTransport(handler))
    config = AsrConfig(api_key='secret', language='zh', prompt='hint')
    path = tmp_path / 'tiny.wav'
    path.write_bytes(wav_bytes())
    assert await asyncio.gather(*(tr.transcribe(path, config, 'previous') for _ in range(3))) == ['plain text'] * 3
    assert maximum == 1


async def test_silence_split_boundaries_and_ffmpeg_failure(tmp_path, monkeypatch):
    async def run(*args, on_line=None):
        on_line('silence_start: 57.0')
        on_line('silence_end: 59.0')
    monkeypatch.setattr(tr, 'run', run)
    assert await tr.plan_pieces(tmp_path / 'audio.wav', 130) == [(0., 58.), (58., 130)]
    async def fail(*args, **kwargs):
        raise tr.TranscribeError('failed')
    monkeypatch.setattr(tr, 'run', fail)
    assert await tr.plan_pieces(tmp_path / 'audio.wav', 140) == [(0., 60.), (60., 120.), (120., 140)]
    assert await tr.plan_pieces(tmp_path / 'audio.wav', 1) == [(0., 1)]
