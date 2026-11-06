"""Image API wire contracts and persistent job lifecycle with MockTransport."""
import asyncio
import base64
import json
import struct
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from server.imagegen import mount, client
from server.imagegen import routes
from server.auth import Auth, COOKIE
from server.core import Core
from server.paths import DataDir

BASE = '/api/imagegen'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jhGQAAAAASUVORK5CYII=')
GIF = b'GIF89a' + struct.pack('<HH', 2, 3) + b'\0' * 10


@pytest.fixture
async def imagegen(tmp_path, monkeypatch):
    paths = DataDir(tmp_path)
    paths.prepare()
    auth = Auth(paths, SimpleNamespace(config=SimpleNamespace(server=SimpleNamespace(password_hash='hash'))))
    events, calls = [], []
    core = Core(paths, auth, auth.require_auth, events.append, lambda: None)
    app = FastAPI()
    mount(app, core)
    state = SimpleNamespace(core=core, jobs=core.modules['imagegen'], events=events, calls=calls, handler=None)
    async def handler(req):
        calls.append(req)
        if state.handler:
            result = state.handler(req)
            return await result if asyncio.iscoroutine(result) else result
        if req.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': 'z'}, {'id': 'a'}]})
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(PNG).decode(), 'revised_prompt': 'Revised'}]})
    monkeypatch.setattr(client, 'transport', httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test',
                               cookies={COOKIE: auth.token()}) as http:
        state.http = http
        await http.patch(BASE + '/settings', json={'api_base': 'https://images.test/v1', 'api_key': 'secret'})
        yield state
    await core.stop()


async def create(imagegen, data=None, files=None):
    response = await imagegen.http.post(BASE + '/jobs', data={'prompt': 'Draw a tree', **(data or {})}, files=files)
    assert response.status_code == 200, response.text
    return response.json()


async def settle(imagegen, job):
    task = imagegen.jobs.tasks.get(job['id'])
    if task:
        await asyncio.wait_for(task, 5)
    return (await imagegen.http.get(BASE + '/jobs/' + job['id'])).json()


def references(n=1, mask=False):
    files = [('images[]', ('same.png', PNG, 'application/octet-stream')) for _ in range(n)]
    if mask:
        files.append(('mask', ('same.png', PNG, 'image/png')))
    return files


async def test_settings_defaults_models_clear_key_raw_config(imagegen):
    c = imagegen.http
    settings = (await c.get(BASE + '/settings')).json()
    assert settings == {'api_base': 'https://images.test/v1', 'api_key': 'secret', 'models': ['gpt-image-2'],
                        'default_model': 'gpt-image-2', 'reference_mode': 'generations', 'timeout': 300}
    assert (await c.post(BASE + '/settings/models')).json() == {'models': ['a', 'z']}
    assert (await c.get(BASE + '/settings')).json()['models'] == ['gpt-image-2']
    assert (await c.post(BASE + '/settings/test')).json() == {'ok': True, 'detail': 'Connected, 2 models', 'models': ['a', 'z']}
    updated = await c.patch(BASE + '/settings', json={'models': ['z', ' z ', ''], 'default_model': '', 'api_key': ''})
    assert updated.json()['models'] == ['z'] and updated.json()['api_key'] == '' and updated.json()['default_model'] == ''
    config = imagegen.core.modules['raw_configs']['imagegen']
    config.replace_raw(config.path.read_text().replace('timeout = 300', 'timeout = 10'))
    assert (await c.get(BASE + '/settings')).json()['timeout'] == 10
    assert (await c.patch(BASE + '/settings', json={'timeout': 0})).status_code == 422
    assert (await c.patch(BASE + '/settings', json={'reference_mode': 'other'})).status_code == 422
    assert (await c.patch(BASE + '/settings', json={'api_base': 'bad'})).status_code == 422


async def test_generations_payload_lifecycle_files_and_events(imagegen):
    job = await create(imagegen, data={'model': 'custom', 'size': '400x600', 'quality': 'high', 'n': '2',
        'background': 'opaque', 'output_format': 'jpeg', 'output_compression': '80', 'moderation': 'low'})
    assert job['status'] == 'running' and job['images'] == [] and job['finished_at'] is None
    done = await settle(imagegen, job)
    request = imagegen.calls[0]
    assert request.url.path == '/v1/images/generations' and request.headers['authorization'] == 'Bearer secret'
    assert json.loads(request.content) == {'prompt': 'Draw a tree', 'model': 'custom', 'size': '400x600', 'quality': 'high',
        'n': 2, 'background': 'opaque', 'output_format': 'jpeg', 'output_compression': 80, 'moderation': 'low'}
    assert done['status'] == 'done' and done['error'] is None and done['revised_prompt'] == 'Revised'
    assert done['finished_at'] >= done['created_at'] and done['duration_ms'] >= 0
    image = done['images'][0]
    assert image['name'] == 'image-1.png' and (image['width'], image['height'], image['bytes']) == (1, 1, len(PNG))
    output = await imagegen.http.get(image['url'])
    assert output.content == PNG and output.headers['content-type'] == 'image/png'
    assert output.headers['content-disposition'] == 'inline; filename="image-1.png"'
    assert json.loads((imagegen.jobs.path(job['id']) / 'job.json').read_text()) == done
    assert [e['status'] for e in imagegen.events] == ['running', 'done']
    assert all(e['type'] == 'imagegen_changed' and e['module'] == 'imagegen' and e['id'] == job['id'] for e in imagegen.events)
    assert (await imagegen.http.get(BASE + '/files/' + job['id'] + '/job.json')).status_code == 404


@pytest.mark.parametrize('mode', ['generations', 'edits', 'auto'])
@pytest.mark.parametrize('count', [0, 1, 2])
async def test_routing_multi_reference_and_mask(imagegen, mode, count):
    await imagegen.http.patch(BASE + '/settings', json={'reference_mode': mode})
    job = await create(imagegen, files=references(count, mask=count > 0), data={'quality': 'low', 'output_format': 'webp',
        'output_compression': '0', 'moderation': 'low'})
    done = await settle(imagegen, job)
    assert done['status'] == 'done'
    request = imagegen.calls[0]
    edits = count > 0 and mode != 'generations'
    assert request.url.path.endswith('/edits' if edits else '/generations')
    if edits:
        body = request.content
        field = b'name="image"' if count == 1 else b'name="image[]"'
        assert body.count(field) == count and b'name="mask"' in body
        assert b'Content-Type: image/png' in body
        assert b'name="quality"\r\n\r\nlow' in body
        assert b'output_compression' not in body and b'moderation' not in body
    else:
        payload = json.loads(request.content)
        assert 'size' not in payload and payload['n'] == 1
        if count:
            assert payload['mask'].startswith('data:image/png;base64,')
            assert isinstance(payload['image'], list) == (count > 1)
        else:
            assert 'image' not in payload and 'mask' not in payload
    assert len(done['references']) == count
    for ref in done['references']:
        assert (await imagegen.http.get(ref['url'])).content == PNG


@pytest.mark.parametrize('failure', ['http', 'empty', 'json', 'network'])
async def test_auto_fallback_only_http_or_empty(imagegen, failure):
    await imagegen.http.patch(BASE + '/settings', json={'reference_mode': 'auto'})
    def handler(req):
        if req.url.path.endswith('/edits'):
            if failure == 'http':
                return httpx.Response(404, text='no edits')
            if failure == 'empty':
                return httpx.Response(200, json={'data': []})
            if failure == 'json':
                return httpx.Response(200, text='invalid json')
            raise httpx.ConnectError('offline', request=req)
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(PNG).decode()}]})
    imagegen.handler = handler
    done = await settle(imagegen, await create(imagegen, files=references(2, True)))
    fallback = failure in ('http', 'empty')
    assert done['status'] == ('done' if fallback else 'error')
    assert len(imagegen.calls) == (2 if fallback else 1)
    if fallback:
        payload = json.loads(imagegen.calls[1].content)
        assert len(payload['image']) == 2 and payload['mask']


@pytest.mark.parametrize('mode', ['edits', 'generations'])
async def test_explicit_modes_do_not_fallback(imagegen, mode):
    await imagegen.http.patch(BASE + '/settings', json={'reference_mode': mode})
    imagegen.handler = lambda req: httpx.Response(503, text='unavailable')
    done = await settle(imagegen, await create(imagegen, files=references()))
    assert done['status'] == 'error' and '503' in done['error'] and len(imagegen.calls) == 1


@pytest.mark.parametrize('source', ['b64', 'url', 'data-url'])
async def test_response_decoding_and_detected_mime(imagegen, source):
    def handler(req):
        if req.url.host == 'cdn.test':
            assert 'authorization' not in req.headers
            return httpx.Response(200, content=GIF)
        item = {'b64_json': base64.b64encode(GIF).decode()} if source == 'b64' else {
            'url': 'https://cdn.test/a.gif' if source == 'url' else 'data:image/gif;base64,' + base64.b64encode(GIF).decode()}
        return httpx.Response(200, json={'data': [item]})
    imagegen.handler = handler
    done = await settle(imagegen, await create(imagegen))
    image = done['images'][0]
    assert done['status'] == 'done' and image['name'] == 'image-1.gif'
    assert (image['width'], image['height']) == (2, 3)
    response = await imagegen.http.get(image['url'])
    assert response.content == GIF and response.headers['content-type'] == 'image/gif'


async def test_retry_keeps_params_duplicate_references_and_mask(imagegen):
    old = await create(imagegen, files=references(2, True), data={'n': '3', 'size': 'auto'})
    old = await settle(imagegen, old)
    assert len({ref['name'] for ref in old['references'] + [old['mask']]}) == 3
    response = await imagegen.http.post(BASE + '/jobs/' + old['id'] + '/retry')
    new = response.json()
    assert new['id'] != old['id'] and new['params'] == old['params']
    done = await settle(imagegen, new)
    assert done['status'] == 'done' and len(done['references']) == 2 and done['mask']
    assert json.loads(imagegen.calls[-1].content)['mask']
    assert (await imagegen.http.delete(BASE + '/jobs/' + old['id'])).json() == {'ok': True}
    assert (await imagegen.http.get(BASE + '/jobs/' + old['id'])).status_code == 404
    assert imagegen.events[-1]['status'] == 'deleted'


@pytest.mark.parametrize('data', [{'prompt': ''}, {'prompt': '  '}, {'n': '0'}, {'n': '5'}, {'size': 'square'},
    {'size': '0x2'}, {'quality': 'ultra'}, {'background': 'none'}, {'output_format': 'gif'}, {'moderation': 'high'},
    {'output_compression': '-1', 'output_format': 'jpeg'}, {'output_compression': '101', 'output_format': 'webp'},
    {'output_compression': '50'}, {'output_compression': '50', 'output_format': 'png'}])
async def test_validation_fields(imagegen, data):
    response = await imagegen.http.post(BASE + '/jobs', data={'prompt': 'p', **data})
    assert response.status_code == 422
    assert not imagegen.calls and not list(imagegen.jobs.root.iterdir())


async def test_validation_files_size_count_mask_and_magic(imagegen, monkeypatch):
    c = imagegen.http
    assert routes.MAX_REF == 20 * 1024 * 1024
    assert (await c.post(BASE + '/jobs', data={'prompt': 'p'}, files=references(9))).status_code == 422
    assert (await c.post(BASE + '/jobs', data={'prompt': 'p'}, files=[('mask', ('a.png', PNG))])).status_code == 422
    assert (await c.post(BASE + '/jobs', data={'prompt': 'p'}, files={'images[]': ('x.png', b'not png')})).status_code == 415
    monkeypatch.setattr(routes, 'MAX_REF', len(PNG) - 1)
    assert (await c.post(BASE + '/jobs', data={'prompt': 'p'}, files=references())).status_code == 413
    monkeypatch.setattr(routes, 'MAX_REF', len(PNG))
    assert (await c.post(BASE + '/jobs', data={'prompt': 'p'}, files=references() + [('mask', ('mask.png', PNG + b'x'))])).status_code == 413
    assert client.sniff(b'\xff\xd8\xffxxx') == ('image/jpeg', '.jpg')
    assert client.sniff(b'RIFF1234WEBPxxx') == ('image/webp', '.webp')
    with pytest.raises(HTTPException, match='unsupported image'):
        client.sniff(b'RIFF1234WAVE')


async def test_list_pagination_missing_ids_and_auth(imagegen):
    assert (await imagegen.http.get(BASE + '/jobs')).json() == []
    jobs = [await create(imagegen) for _ in range(3)]
    await asyncio.gather(*(settle(imagegen, job) for job in jobs))
    expected = sorted((job['id'] for job in jobs), reverse=True)
    items = (await imagegen.http.get(BASE + '/jobs?limit=2')).json()
    assert [j['id'] for j in items] == expected[:2]
    items = (await imagegen.http.get(BASE + '/jobs', params={'before': items[-1]['id']})).json()
    assert [j['id'] for j in items] == expected[2:]
    for suffix in ['/jobs/missing', '/files/missing/a.png', '/jobs/..%2Fconfig']:
        assert (await imagegen.http.get(BASE + suffix)).status_code == 404
    imagegen.http.cookies.clear()
    for method, suffix in [('get', '/settings'), ('post', '/settings/models'), ('get', '/jobs'),
                           ('delete', '/jobs/' + expected[0]), ('get', '/files/' + expected[0] + '/image-1.png')]:
        assert (await getattr(imagegen.http, method)(BASE + suffix)).status_code == 401


async def test_concurrency_cap_delete_and_restart_recovery(imagegen):
    started, release = asyncio.Queue(), asyncio.Event()
    async def handler(req):
        await started.put(req)
        await release.wait()
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(PNG).decode()}]})
    imagegen.handler = handler
    jobs = [await create(imagegen) for _ in range(3)]
    await asyncio.wait_for(started.get(), 2)
    await asyncio.wait_for(started.get(), 2)
    assert started.empty() and len(imagegen.calls) == 2
    jid = jobs[0]['id']
    assert (await imagegen.http.delete(BASE + '/jobs/' + jid)).status_code == 200
    await asyncio.wait_for(started.get(), 2)  # Third queued job takes the released semaphore slot.
    assert not imagegen.jobs.path(jid).exists()
    await imagegen.jobs.shutdown()
    assert imagegen.jobs.load(jobs[1]['id'])['status'] == 'running'
    await imagegen.jobs.startup()
    for job in jobs[1:]:
        recovered = imagegen.jobs.load(job['id'])
        assert recovered['status'] == 'error' and recovered['error'] == 'Server restarted'
        assert recovered['finished_at'] is not None and recovered['duration_ms'] >= 0


@pytest.mark.parametrize('body', [{'data': []}, {'data': [{}]}, {'data': [{'url': 'https://cdn.test/missing'}]}, []])
async def test_invalid_generation_results_are_persisted_errors(imagegen, body):
    imagegen.handler = lambda req: httpx.Response(404) if req.url.host == 'cdn.test' else httpx.Response(200, json=body)
    done = await settle(imagegen, await create(imagegen))
    assert done['status'] == 'error' and done['error'] and done['finished_at'] is not None


@pytest.mark.parametrize('response', [httpx.Response(503, text='offline'), httpx.Response(200, text='invalid'),
                                     httpx.Response(200, json={'data': [None]})])
async def test_model_fetch_and_connection_errors(imagegen, response):
    imagegen.handler = lambda req: response
    assert (await imagegen.http.post(BASE + '/settings/models')).status_code == 502
    test = (await imagegen.http.post(BASE + '/settings/test')).json()
    assert test['ok'] is False and test['detail'] and test['models'] == []


def test_dimensions_jpeg_webp():
    jpeg = b'\xff\xd8\xff\xc0\x00\x0b\x08' + struct.pack('>HH', 20, 30) + b'\0' * 4
    assert client.dimensions(jpeg, 'image/jpeg') == (30, 20)
    webp = b'RIFF1234WEBPVP8X' + b'\0' * 8 + (29).to_bytes(3, 'little') + (19).to_bytes(3, 'little')
    assert client.dimensions(webp, 'image/webp') == (30, 20)
