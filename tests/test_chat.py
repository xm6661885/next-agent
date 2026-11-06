import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from server.auth import Auth, COOKIE
from server.core import Core
from server.paths import DataDir
from server.chat import mount, mcp_tools, providers
from server.chat.routes import ConfigPatch
from server.chat.store import ChatStore


def make_app(tmp_path):
    paths = DataDir(tmp_path)
    paths.prepare()
    auth = Auth(paths, SimpleNamespace(config=SimpleNamespace(server=SimpleNamespace(password_hash='test-hash'))))
    events = []
    core = Core(paths, auth, auth.require_auth, events.append, lambda: None, modules={'raw_configs': {}})

    @asynccontextmanager
    async def lifespan(app):
        await core.start()
        try: yield
        finally: await core.stop()

    app = FastAPI(lifespan=lifespan)
    mount(app, core)
    return app, core, events


def sse(*events):
    return ''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()


def oa(delta=None, reason=None, usage=None):
    return {'choices': [{'delta': delta or {}, 'finish_reason': reason}], **({'usage': usage} if usage else {})}


def anthropic_start():
    return {'type': 'message_start', 'message': {'usage': {'input_tokens': 10, 'output_tokens': 0}}}


def anthropic_end(reason, tokens=4):
    return [{'type': 'message_delta', 'delta': {'stop_reason': reason}, 'usage': {'output_tokens': tokens}}, {'type': 'message_stop'}]


class HeldStream(httpx.AsyncByteStream):
    def __init__(self, format):
        self.format, self.release, self.closed = format, asyncio.Event(), False

    async def __aiter__(self):
        if self.format=='openai': yield sse(oa({'content': 'partial'}))
        else:
            yield sse(anthropic_start(), {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
                      {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'partial'}})
        await self.release.wait()
        if self.format=='openai': yield sse(oa({'content': ' complete'}, 'stop', {'prompt_tokens': 10, 'completion_tokens': 6}))
        else:
            yield sse({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': ' complete'}},
                      {'type': 'content_block_stop', 'index': 0}, *anthropic_end('end_turn', 6))

    async def aclose(self): self.closed = True


class Peer:
    def __init__(self, format):
        self.format, self.requests, self.held, self.calls, self.closed = format, [], [], [], []
        self.error = self.broken = False
        self.title_error = False

    def handle(self, request):
        body = json.loads(request.content) if request.content else None
        self.requests.append((request, body))
        if request.method=='GET': return httpx.Response(200, json={'data': [{'id': 'small'}, {'id': 'large'}]})
        if not body.get('stream'):
            if self.title_error: return httpx.Response(503, text='title unavailable')
            if self.format=='openai': return httpx.Response(200, json={'choices': [{'message': {'content': 'A generated title'}}]})
            return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'A generated title'}]})
        if self.error: return httpx.Response(429, text='provider quota exhausted')
        if self.broken: return httpx.Response(200, content=b'data: not-json\n\n', headers={'content-type': 'text/event-stream'})
        last_user = next(m for m in reversed(body['messages']) if m['role']=='user')
        text = json.dumps(last_user['content'])
        if 'hold' in text:
            stream = HeldStream(self.format)
            self.held.append(stream)
            return httpx.Response(200, stream=stream, headers={'content-type': 'text/event-stream'})
        has_tool = body['messages'][-1]['role']=='tool' if self.format=='openai' else any(
            b.get('type')=='tool_result' for b in last_user['content'])
        if self.format=='openai':
            if has_tool:
                data = sse(oa({'content': 'Answer '}), oa({'content': 'ready'}, 'stop'),
                           {'choices': [], 'usage': {'prompt_tokens': 12, 'completion_tokens': 6}})+b'data: [DONE]\n\n'
            else:
                data = sse(oa({'reasoning_content': 'Think'}), oa({'reasoning_content': 'ing'}), oa({'content': 'Looking '}),
                           oa({'tool_calls': [{'index': 0, 'id': 'call-1', 'type': 'function',
                                              'function': {'name': 'mcp__fetch__lookup', 'arguments': '{"q":'}}]}),
                           oa({'tool_calls': [{'index': 0, 'function': {'arguments': '"hello"}'}}]}, 'tool_calls'),
                           {'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 4}})+b'data: [DONE]\n\n'
        elif has_tool:
            data = sse({'type': 'message_start', 'message': {'usage': {'input_tokens': 12, 'output_tokens': 0}}},
                       {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
                       {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'Answer '}},
                       {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'ready'}},
                       {'type': 'content_block_stop', 'index': 0}, *anthropic_end('end_turn', 6))
        else:
            data = sse(anthropic_start(),
                       {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}},
                       {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'Think'}},
                       {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'ing'}},
                       {'type': 'content_block_stop', 'index': 0},
                       {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': 'Looking '}},
                       {'type': 'content_block_stop', 'index': 1},
                       {'type': 'content_block_start', 'index': 2, 'content_block': {'type': 'tool_use', 'id': 'call-1', 'name': 'mcp__fetch__lookup', 'input': {}}},
                       {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '{"q":'}},
                       {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '"hello"}'}},
                       {'type': 'content_block_stop', 'index': 2}, *anthropic_end('tool_use'))
        return httpx.Response(200, content=data, headers={'content-type': 'text/event-stream'})

    def install(self, monkeypatch):
        monkeypatch.setattr(providers, 'client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.handle)))

        async def list_tools(layer):
            layer.stack.callback(self.closed.append, True)
            if 'broken' in layer.enabled: layer.notice('MCP broken: refused')
            return [{'name': 'mcp__fetch__lookup', 'description': 'Lookup', 'parameters': {'type': 'object', 'properties': {'q': {'type': 'string'}}}}]

        async def call_tool(layer, name, arguments):
            self.calls.append((name, arguments))
            return {'content': 'Found it', 'is_error': False, 'images': []}

        monkeypatch.setattr(mcp_tools, 'list_tools', list_tools)
        monkeypatch.setattr(mcp_tools, 'call_tool', call_tool)


def configure(manager, format):
    manager.patch_config(ConfigPatch.model_validate({
        'providers': [{'id': 'local', 'name': 'Local', 'format': format, 'base_url': 'https://provider.test/v1',
                       'api_key': 'secret', 'models': ['small', 'large'], 'headers': {'x-extra': 'yes'}}],
        'defaults': {'mcp': ['fetch'], 'effort': 'low', 'system_prompt': 'Be helpful'},
        'mcp_servers': {'fetch': {'type': 'http', 'url': 'https://mcp.test'}}}))


@pytest.fixture(params=['openai', 'anthropic'])
async def chat(tmp_path, monkeypatch, request):
    app, core, events = make_app(tmp_path)
    manager = core.modules['chat']
    configure(manager, request.param)
    peer = Peer(request.param)
    peer.install(monkeypatch)
    await core.start()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', cookies={COOKIE: core.auth.token()}) as client:
        yield SimpleNamespace(app=app, core=core, manager=manager, peer=peer, http=client, events=events, format=request.param)
    await core.stop()


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate(): await asyncio.sleep(.005)


async def test_stream_tools_history_and_persistence(chat):
    m, c, peer = chat.manager, chat.http, chat.peer
    sid = (await c.post('/api/chat/assistants/_default/sessions', json={})).json()['id']
    attachment = (await c.post(f'/api/chat/sessions/{sid}/uploads', files={'files': ('pic.png', b'image-data', 'image/png')})).json()[0]
    runtime = m.runtime(sid)
    runtime.send('hello', [attachment], 'client-1')
    await asyncio.wait_for(asyncio.shield(runtime.task), 3)
    await runtime.title_task
    items = runtime.items
    assert [i['kind'] for i in items]==['user', 'thinking', 'text', 'tool', 'text', 'result']
    assert items[0]['uuid']==items[0]['id'] and items[0]['client_id']=='client-1'
    assert items[1]['text']=='Thinking' and items[4]['text']=='Answer ready'
    assert items[3]['input']=={'q': 'hello'} and items[3]['result']['content']=='Found it'
    assert items[-1]['usage']=={'input': 22, 'output': 10}
    assert items[-1]['model']=='local/small'
    assert items[-1]['stop_reason']==('stop' if chat.format=='openai' else 'end_turn')
    assert not any(i.get('streaming') for i in items)
    assert peer.calls==[('mcp__fetch__lookup', {'q': 'hello'})] and peer.closed==[True]
    events = list(runtime.ring)
    assert any(e['type']=='delta' and e['field']=='input_partial' for e in events)
    assert any(e['type']=='patch' and e['patch'].get('streaming') is False for e in events)
    assert next(e['item'] for e in events if e['type']=='item' and e['item']['kind']=='thinking')['text']==''
    assert ChatStore(m.core.paths.root).load_items(sid)==items
    assert m.view(sid)['title']=='A generated title' and m.view(sid)['unread']
    assert m.view(sid)['usage']=={'input': 22, 'output': 10}
    assert (await c.post(f'/api/chat/sessions/{sid}/read')).json()['unread'] is False
    assert (await c.get(f'/api/chat/assistants/_default/search?q=ANSWER')).json()[0]['snippet']=='Answer ready'
    assert (await c.get(f'/api/chat/assistants/_default/search?q=Thinking')).json()==[]
    last = (await c.get(f'/api/chat/sessions/{sid}/items?limit=2')).json()
    assert last['has_more'] and last['items']==items[-2:]
    earlier = (await c.get(f"/api/chat/sessions/{sid}/items?before={items[-2]['id']}&limit=2")).json()
    assert earlier['items']==items[-4:-2]
    assert (await c.get(attachment['url'])).content==b'image-data'
    replies = [(request, body) for request, body in peer.requests if body and body.get('stream')]
    request, first = replies[0]
    assert request.headers['x-extra']=='yes'
    assert first['tools'] and first['model']=='small'
    second = replies[1][1]
    assert 'Thinking' not in json.dumps(second['messages']) and 'Found it' in json.dumps(second['messages'])
    if chat.format=='openai':
        assert request.headers['authorization']=='Bearer secret'
        assert first['reasoning_effort']=='low' and first['messages'][0]['content']=='Be helpful'
        assert first['messages'][1]['content'][1]['image_url']['url']=='data:image/png;base64,aW1hZ2UtZGF0YQ=='
        assert second['messages'][-2]['tool_calls'][0]['function']['arguments']=='{"q": "hello"}'
        assert second['messages'][-1]['tool_call_id']=='call-1'
    else:
        assert request.headers['x-api-key']=='secret' and request.headers['anthropic-version']=='2023-06-01'
        assert first['thinking']['budget_tokens']==2048 and first['max_tokens']==10240
        assert first['system']=='Be helpful'
        assert first['messages'][0]['content'][1]['source']['data']=='aW1hZ2UtZGF0YQ=='
        assert second['messages'][-2]['content'][-1]['type']=='tool_use'
        assert second['messages'][-1]['content'][0]['tool_use_id']=='call-1'
    assert len(peer.requests)==3 and sum(not body['stream'] for _, body in peer.requests)==1
    assert any(e.get('module')=='chat' and e.get('unread') for e in chat.events)


async def test_config_assistants_uploads_and_delete(chat):
    m, c = chat.manager, chat.http
    assert m.core.modules['raw_configs']['chat'] is m.config
    assert (await c.get('/api/chat/assistants')).json()==[]
    default = (await c.get('/api/chat/assistants/_default')).json()
    assert default['name']=='Temporary chat' and default['avatar']=='crab:gray'
    assert (await c.delete('/api/chat/assistants/_default')).status_code==400
    config = (await c.get('/api/chat/config')).json()
    provider = config['providers'][0]
    assert provider['api_key']!=''
    provider.pop('api_key')
    provider['name'] = 'Renamed'
    response = await c.patch('/api/chat/config', json={'providers': [provider], 'defaults': {'effort': 'max'}})
    assert response.status_code==200
    assert m.config.data.providers[0].api_key=='secret' and m.config.data.defaults.system_prompt=='Be helpful'
    assert (await c.patch('/api/chat/config', json={'providers': [provider, provider]})).status_code==422
    assert (await c.patch('/api/chat/config', json={'defaults': {'effort': 'invalid'}})).status_code==422
    assert m.config.data.providers[0].api_key=='secret'
    meta = (await c.get('/api/chat/meta')).json()
    assert meta['models'][0]=={'id': 'local/small', 'provider': 'local', 'model': 'small', 'format': chat.format}
    assert meta['mcp_servers']==['fetch']
    assert (await c.post('/api/chat/providers/local/test')).json()['ok']
    assert (await c.post('/api/chat/providers/missing/test')).status_code==404
    writer = (await c.post('/api/chat/assistants', json={'name': 'Writer', 'mcp': ['fetch', 'extra'], 'max_tokens': 123})).json()
    assert writer['id']=='writer' and writer['max_tokens']==123
    assert (await c.post('/api/chat/assistants', json={'name': 'Writer'})).status_code==409
    assert (await c.post('/api/chat/assistants', json={'name': 'Bad', 'id': '../bad'})).status_code==422
    assert (await c.post('/api/chat/assistants', json={'name': 'Reader'})).status_code==200
    assert (await c.post('/api/chat/assistants/reorder', json={'ids': ['reader', 'writer']})).json()=={'ok': True}
    assert [a['id'] for a in (await c.get('/api/chat/assistants')).json()]==['reader', 'writer']
    assert (await c.post('/api/chat/assistants/reorder', json={'ids': ['writer']})).status_code==400
    assert (await c.patch('/api/chat/assistants/writer', json={'id': 'changed'})).status_code==400
    assert (await c.patch('/api/chat/assistants/writer', json={'name': 'Writing'})).json()['name']=='Writing'
    assert (await c.patch('/api/chat/assistants/_default', json={'system_prompt': 'Default prompt'})).status_code==200
    avatar = await c.post('/api/chat/assistants/writer/avatar', files={'file': ('a.png', b'avatar', 'image/png')})
    assert avatar.json()['avatar']=='file'
    assert (await c.get('/api/chat/assistants/writer/avatar')).content==b'avatar'
    assert (await c.post('/api/chat/assistants/writer/avatar', files={'file': ('a.svg', b'<svg/>', 'image/svg+xml')})).status_code==415
    assert (await c.post('/api/chat/assistants/writer/avatar', files={'file': ('a.png', b'x'*(2*1024*1024+1), 'image/png')})).status_code==413
    sid = (await c.post('/api/chat/assistants/writer/sessions', json={'title': 'Saved'})).json()['id']
    assert m.view(sid)['mcp']==['fetch', 'extra']
    assert (await c.get('/api/chat/assistants/writer')).json()['status']['last_session']['id']==sid
    patch = await c.patch(f'/api/chat/sessions/{sid}', json={'title': 'Changed', 'overrides': {'model': 'local/large', 'effort': 'off'}, 'mcp': ['fetch', 'fetch']})
    assert patch.json()['mcp']==['fetch'] and patch.json()['overrides']['model']=='local/large'
    assert (await c.patch(f'/api/chat/sessions/{sid}', json={'overrides': {'temperature': 'bad'}})).status_code==422
    assert (await c.get('/api/chat/assistants/writer/sessions')).json()[0]['title']=='Changed'
    assert (await c.post(f'/api/chat/sessions/{sid}/uploads', files={'files': ('x.txt', b'no\x00', 'text/plain')})).status_code==415
    assert (await c.post(f'/api/chat/sessions/{sid}/uploads', files={'files': ('x.png', b'x'*(10*1024*1024+1), 'image/png')})).status_code==413
    attachment = (await c.post(f'/api/chat/sessions/{sid}/uploads', files={'files': ('x.png', b'yes', 'image/png')})).json()[0]
    other = m.create_session('_default')['id']
    assert (await c.get(f"/api/chat/uploads/{other}/{attachment['id']}")).status_code==404
    m.runtime(sid).send('hello')
    await m.runtime(sid).task
    assert m.core.modules['overview_chat']()=={'assistants': 2, 'providers': 1, 'sessions': 2}
    assert m.core.hello[0]()['chat_sessions'][0]['id']==sid
    assert (await c.delete('/api/chat/assistants/writer')).json()=={'ok': True}
    assert sid not in m.store.sessions and not (m.store.root/'messages'/f'{sid}.jsonl').exists()
    assert not (m.store.root/'uploads'/sid).exists() and not (m.store.avatars/'writer').exists()
    assert (await c.delete(f'/api/chat/sessions/{other}')).json()=={'ok': True}
    assert not m.core.hello[0]()['chat_sessions']
    assert any(e['type']=='chat_changed' for e in chat.events)
    raw = m.config.path.read_text().replace('Default prompt', 'Reloaded')
    m.config.replace_raw(raw)
    await m.config.changed()
    assert m.assistant('_default').system_prompt=='Reloaded'
    c.cookies.clear()
    assert (await c.get('/api/chat/config')).status_code==401


def receive_until(ws, predicate):
    events = []
    for _ in range(200):
        event = ws.receive_json()
        events.append(event)
        if predicate(event): return events
    raise AssertionError('Expected WebSocket event was not received')


def idle(ws):
    return receive_until(ws, lambda e: e['type']=='state' and e['state']=='idle')


@pytest.mark.parametrize('format', ['openai', 'anthropic'])
def test_websocket_edit_regenerate_stop_resume_and_disconnect(tmp_path, monkeypatch, format):
    app, core, _ = make_app(tmp_path)
    m = core.modules['chat']
    configure(m, format)
    peer = Peer(format)
    peer.install(monkeypatch)
    with TestClient(app, base_url='http://testserver') as c:
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect('/ws/chat/missing', headers={'origin': 'http://testserver'}) as ws: ws.receive_json()
        assert exc.value.code==4401
        c.cookies.set(COOKIE, core.auth.token())
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect('/ws/chat/missing', headers={'origin': 'http://elsewhere'}) as ws: ws.receive_json()
        assert exc.value.code==4403
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect('/ws/chat/missing', headers={'origin': 'http://testserver'}) as ws: ws.receive_json()
        assert exc.value.code==4404
        sid = c.post('/api/chat/assistants/_default/sessions', json={'title': 'WS'}).json()['id']
        path = f'/ws/chat/{sid}'
        runtime = m.runtime(sid)
        with c.websocket_connect(path, headers={'origin': 'http://testserver'}) as ws:
            ws.send_json({'type': 'resume', 'seq': 0})
            assert ws.receive_json()['type']=='snapshot' and ws.receive_json()['type']=='resumed'
            assert not peer.requests
            ws.send_json({'type': 'send', 'text': {'bad': True}, 'req_id': 'invalid'})
            assert ws.receive_json()['req_id']=='invalid'
            ws.send_json({'type': 'send', 'text': 'original', 'client_id': 'one'})
            events = idle(ws)
            user = next(e['item'] for e in events if e.get('item', {}).get('kind')=='user')
            assert any(e.get('item', {}).get('kind')=='result' for e in events)
            assert not m.view(sid)['unread']
            ws.send_json({'type': 'edit', 'uuid': user['uuid'], 'text': 'edited', 'client_id': 'two', 'attachments': ['missing'], 'req_id': 'bad-upload'})
            assert ws.receive_json()['req_id']=='bad-upload'
            assert runtime.items[0]['text']=='original'
            ws.send_json({'type': 'edit', 'uuid': user['uuid'], 'text': 'edited', 'client_id': 'two'})
            events = idle(ws)
            assert any(e['type']=='items' and e['items'][0]['version']==[1, 2] for e in events)
            assert runtime.items[0]['text']=='edited' and sum(i['kind']=='user' for i in runtime.items)==1
            user = runtime.items[0]
            old_text_id = runtime.items[-2]['id']
            ws.send_json({'type': 'regenerate', 'uuid': user['uuid']})
            events = idle(ws)
            assert any(e['type']=='items' and e['items'][0]['reply_version']==[1, 2] for e in events)
            assert runtime.items[0]['id']==user['id'] and runtime.items[-2]['id']!=old_text_id
            assert sum(i['kind']=='result' for i in runtime.items)==1
            ws.send_json({'type': 'edit_reply', 'id': runtime.items[-2]['id'], 'text': 'Edited over WS'})
            event = receive_until(ws, lambda e: e['type']=='items')[-1]
            assert event['items'][-2]['text']=='Edited over WS' and event['items'][-1]['stop_reason']=='edited'
            ws.send_json({'type': 'switch', 'key': 'r:'+user['uuid'], 'index': 0})
            event = receive_until(ws, lambda e: e['type']=='items')[-1]
            assert event['items'][-2]['id']==old_text_id and event['items'][0]['reply_version']==[0, 3]
            ws.send_json({'type': 'switch', 'key': 'r:'+user['uuid'], 'req_id': 'missing-index'})
            assert receive_until(ws, lambda e: e['type']=='error')[-1]['req_id']=='missing-index'
            ws.send_json({'type': 'set_model', 'model': 'local/large'})
            receive_until(ws, lambda e: e['type']=='session' and e['session']['overrides']['model']=='local/large')
            ws.send_json({'type': 'set_effort', 'effort': 'off'})
            receive_until(ws, lambda e: e['type']=='session' and e['session']['overrides']['effort']=='off')
            ws.send_json({'type': 'set_mcp', 'mcp': []})
            receive_until(ws, lambda e: e['type']=='session' and e['session']['mcp']==[])
            ws.send_json({'type': 'set_model', 'model': ''})
            receive_until(ws, lambda e: e['type']=='session' and e['session']['overrides']['model'] is None)
            ws.send_json({'type': 'send', 'text': 'hold'})
            receive_until(ws, lambda e: e['type']=='delta' and e['text']=='partial')
            ws.send_json({'type': 'send', 'text': 'busy', 'req_id': 'busy'})
            error = receive_until(ws, lambda e: e['type']=='error')[-1]
            assert error['message']=='Still replying' and error['req_id']=='busy'
            ws.send_json({'type': 'switch', 'key': 'r:'+user['uuid'], 'index': 1, 'req_id': 'busy-switch'})
            error = receive_until(ws, lambda e: e['type']=='error')[-1]
            assert error['message']=='Still replying' and error['req_id']=='busy-switch'
            ws.send_json({'type': 'stop'})
            events = idle(ws)
            assert any(e.get('item', {}).get('text')=='Stopped' for e in events)
            assert runtime.items[-1]['stop_reason']=='cancelled' and peer.held[-1].closed
            assert any(i['kind']=='text' and i['text']=='partial' and not i['streaming'] for i in m.store.load_items(sid))
            ws.send_json({'type': 'send', 'text': 'hold again'})
            last = receive_until(ws, lambda e: e['type']=='delta' and e['text']=='partial')[-1]['seq']
        c.portal.call(until, lambda: runtime.viewers==0)
        assert c.get(f'/api/chat/sessions/{sid}').json()['state']=='running'
        c.portal.call(peer.held[-1].release.set)
        c.portal.call(until, lambda: runtime.state=='idle')
        assert m.view(sid)['unread'] and runtime.items[-2]['text']=='partial complete'
        assert peer.held[-1].closed
        with c.websocket_connect(path, headers={'origin': 'http://testserver'}) as ws:
            ws.send_json({'type': 'resume', 'seq': last})
            events = receive_until(ws, lambda e: e['type']=='resumed')[:-1]
            assert events and all(e['type']!='snapshot' and e['seq']>last for e in events)
            assert [e['seq'] for e in events]==sorted({e['seq'] for e in events})
            assert not m.view(sid)['unread']
            ws.send_json({'type': 'resume', 'seq': 999999})
            assert ws.receive_json()['type']=='snapshot' and ws.receive_json()['type']=='resumed'
            ws.send_json({'type': 'ping'})
            assert ws.receive_json()['type']=='pong'
        assert m.store.load_items(sid)==runtime.items


async def test_errors_shutdown_and_resolution(chat):
    m, peer = chat.manager, chat.peer
    m.patch_config(ConfigPatch(defaults={'model': 'local/large', 'effort': 'high', 'temperature': .8, 'max_tokens': 1000}))
    m.patch_assistant('_default', {'model': 'local/small', 'effort': 'low', 'temperature': .5, 'max_tokens': 2000, 'system_prompt': 'assistant'})
    sid = m.create_session('_default', 'Existing')['id']
    m.update_session(sid, overrides={'model': 'local/large', 'effort': 'off', 'temperature': 0, 'max_tokens': 10, 'system_prompt': 'override'})
    assert m.resolve(sid)=={'model': 'local/large', 'effort': 'off', 'system_prompt': 'override', 'temperature': 0, 'max_tokens': 10}
    runtime = m.runtime(sid)
    peer.error = True
    runtime.send('error')
    await runtime.task
    assert runtime.items[-2]['kind']=='notice' and '429: provider quota exhausted' in runtime.items[-2]['text']
    assert runtime.items[-1]['stop_reason']=='error'
    body = peer.requests[-1][1]
    assert body['temperature']==0 and body['max_tokens']==10
    assert 'thinking' not in body and 'reasoning_effort' not in body
    peer.error, peer.broken = False, True
    runtime.send('bad stream')
    await runtime.task
    assert runtime.items[-1]['stop_reason']=='error'
    m.update_session(sid, overrides={'model': 'missing/model'})
    requests = len(peer.requests)
    runtime.send('unknown')
    await runtime.task
    assert len(peer.requests)==requests and runtime.items[-2]['text']=='Unknown provider: missing'
    m.update_session(sid, overrides={'model': '', 'effort': None, 'temperature': -1, 'max_tokens': 0, 'system_prompt': ''})
    assert m.resolve(sid)=={'model': 'local/small', 'effort': 'low', 'temperature': .5, 'max_tokens': 2000, 'system_prompt': 'assistant'}
    m.patch_assistant('_default', {'model': '', 'effort': '', 'temperature': -1, 'max_tokens': 0, 'system_prompt': ''})
    assert m.resolve(sid)=={'model': 'local/large', 'effort': 'high', 'temperature': .8, 'max_tokens': 1000, 'system_prompt': 'Be helpful'}
    peer.broken = False
    runtime.send('hold shutdown')
    await until(lambda: runtime.active is not None)
    await m.close()
    assert runtime.state=='idle' and peer.held[-1].closed
    assert m.store.load_items(sid)==runtime.items and runtime.items[-1]['stop_reason']=='cancelled'
    assert any(i['kind']=='text' and i['text']=='partial' for i in runtime.items)


async def test_title_fallback_and_mcp_failure_notice(chat):
    m, peer = chat.manager, chat.peer
    peer.title_error = True
    sid = m.create_session('_default')['id']
    m.update_session(sid, mcp=['fetch', 'broken'])
    runtime = m.runtime(sid)
    runtime.send('A useful fallback title')
    await runtime.task
    assert m.view(sid)['title']=='A useful fallback title'
    assert any(i['kind']=='notice' and i['text']=='MCP broken: refused' for i in runtime.items)
    assert runtime.items[-1]['stop_reason']!='error'
    assert peer.closed==[True]


async def test_user_versions_switch_and_reload(chat):
    m = chat.manager
    sid = m.create_session('_default', 'Versions')['id']
    runtime = m.runtime(sid)
    runtime.send('original')
    await runtime.task
    first = runtime.items[0]
    group = first['group']
    assert group==first['id'] and first['version']==first['reply_version']==[0, 1]
    runtime.send('later original turn')
    await runtime.task
    original_ids = [i['id'] for i in runtime.items]
    for text in ('edit one', 'edit two'):
        runtime.send(text, uuid=runtime.items[0]['uuid'])
        await runtime.task
    key = 'u:'+group
    latest_ids = [i['id'] for i in runtime.items]
    assert runtime.items[0]['group']==group and runtime.items[0]['version']==[2, 3]
    assert runtime.forks[key]['active']==2 and runtime.forks[key]['versions'][2] is None
    runtime.switch(key, 0)
    assert [i['id'] for i in runtime.items]==original_ids
    assert runtime.items[0]['text']=='original' and runtime.items[0]['version']==[0, 3]
    assert any(i.get('text')=='Answer ready' for i in runtime.items)
    runtime.switch(key, 2)
    assert [i['id'] for i in runtime.items]==latest_ids
    assert not m.search('_default', 'later original turn')
    m.store = ChatStore(m.core.paths.root)
    m.runtimes.pop(sid)
    runtime = m.runtime(sid)
    assert runtime.items[0]['version']==[2, 3]
    assert runtime.forks==m.store.load_forks(sid)
    runtime.switch(key, 0)
    assert [i['id'] for i in runtime.items]==original_ids
    runtime.switch(key, 2)
    assert [i['id'] for i in runtime.items]==latest_ids
    await m.delete_session(sid)
    assert not (m.store.root/'messages'/f'{sid}.forks.json').exists()


async def test_reply_versions_and_visible_provider_history(chat):
    m, peer = chat.manager, chat.peer
    sid = m.create_session('_default', 'Replies')['id']
    runtime = m.runtime(sid)
    runtime.send('first turn')
    await runtime.task
    user = runtime.items[0]
    old_reply = [i['id'] for i in runtime.items[1:]]
    runtime.send('hidden later turn')
    await runtime.task
    original_ids = [i['id'] for i in runtime.items]
    runtime.regenerate(user['uuid'])
    await runtime.task
    key = 'r:'+user['uuid']
    regenerated_ids = [i['id'] for i in runtime.items]
    assert user['reply_version']==[1, 2]
    assert not set(old_reply)&{i['id'] for i in runtime.items}
    runtime.switch(key, 0)
    assert [i['id'] for i in runtime.items]==original_ids
    assert user['reply_version']==[0, 2]
    runtime.switch(key, 1)
    assert [i['id'] for i in runtime.items]==regenerated_ids
    requests = len(peer.requests)
    expected = providers.history([*runtime.items, {'kind': 'user', 'text': 'next visible turn'}], chat.format)
    if chat.format=='openai': expected.insert(0, {'role': 'system', 'content': 'Be helpful'})
    runtime.send('next visible turn')
    await runtime.task
    messages = peer.requests[requests][1]['messages']
    assert messages==expected
    assert 'hidden later turn' not in json.dumps(messages)
    assert 'version' not in json.dumps(messages)


async def test_edit_reply_preserves_turn_and_later_branch(chat):
    m, peer = chat.manager, chat.peer
    sid = m.create_session('_default', 'Edited replies')['id']
    runtime = m.runtime(sid)
    runtime.send('first')
    await runtime.task
    user = runtime.items[0]
    turn = runtime.items[1:]
    target = next(i for i in reversed(turn) if i['kind']=='text')
    runtime.send('later turn')
    await runtime.task
    original_ids = [i['id'] for i in runtime.items]
    usage, requests = dict(runtime.session['usage']), len(peer.requests)
    runtime.edit_reply(target['id'], 'Manually edited reply')
    assert len(peer.requests)==requests and runtime.state=='idle'
    assert runtime.session['usage']==usage and user['reply_version']==[1, 2]
    assert [i['kind'] for i in runtime.items[1:]]==[i['kind'] for i in turn]
    assert not {i['id'] for i in turn}&{i['id'] for i in runtime.items[1:]}
    assert runtime.items[-2]['text']=='Manually edited reply'
    result = runtime.items[-1]
    assert result['stop_reason']=='edited' and result['duration_ms']==0
    assert result['usage']=={'input': 0, 'output': 0} and result['model']=='' and result['ts']
    messages = json.dumps(providers.history(runtime.items, chat.format))
    assert 'Manually edited reply' in messages and 'edited"' not in messages
    assert 'later turn' not in messages
    edited_ids = [i['id'] for i in runtime.items]
    runtime.switch('r:'+user['uuid'], 0)
    assert [i['id'] for i in runtime.items]==original_ids
    runtime.switch('r:'+user['uuid'], 1)
    assert [i['id'] for i in runtime.items]==edited_ids
    for id in (user['id'], 'missing', result['id']):
        with pytest.raises(ValueError, match='Reply text not found'): runtime.edit_reply(id, 'bad')
    orphan = m.runtime(m.create_session('_default', 'Orphan')['id'])
    text = orphan.add('text', text='No user', streaming=False)
    with pytest.raises(ValueError, match='Reply text not found'): orphan.edit_reply(text['id'], 'bad')
    user = orphan.add('user', text='User', attachments=[])
    text = orphan.add('text', text='Streaming', streaming=True)
    with pytest.raises(ValueError, match='Reply text not found'): orphan.edit_reply(text['id'], 'bad')


async def test_nested_versions_and_switch_errors(chat):
    m = chat.manager
    sid = m.create_session('_default', 'Nested')['id']
    runtime = m.runtime(sid)
    runtime.send('root original')
    await runtime.task
    root = runtime.items[0]
    runtime.send('child original')
    await runtime.task
    child = next(i for i in runtime.items if i['kind']=='user' and i['id']!=root['id'])
    runtime.send('child edit', uuid=child['uuid'])
    await runtime.task
    child_key, root_key = 'u:'+child['group'], 'u:'+root['group']
    child_ids = [i['id'] for i in runtime.items]
    runtime.send('root edit', uuid=root['uuid'])
    await runtime.task
    with pytest.raises(ValueError, match='Version not visible'): runtime.switch(child_key, 0)
    runtime.switch(root_key, 0)
    assert [i['id'] for i in runtime.items]==child_ids
    assert next(i for i in runtime.items if i.get('text')=='child edit')['version']==[1, 2]
    runtime.switch(child_key, 0)
    assert any(i.get('text')=='child original' for i in runtime.items)
    runtime.switch(child_key, 1)
    runtime.switch(root_key, 1)
    runtime.switch(root_key, 0)
    assert [i['id'] for i in runtime.items]==child_ids
    seq = runtime.seq
    runtime.switch(root_key, 0)
    assert runtime.seq==seq
    with pytest.raises(ValueError, match='Version not found'): runtime.switch('u:missing', 0)
    for index in (-1, 2):
        with pytest.raises(ValueError, match='out of range'): runtime.switch(root_key, index)
    runtime.send('hold running')
    for op in (lambda: runtime.switch(root_key, 1), lambda: runtime.send('edit', uuid=root['uuid']),
               runtime.regenerate, lambda: runtime.edit_reply('missing', 'bad')):
        with pytest.raises(ValueError, match='Still replying'): op()
    await runtime.stop()


def test_old_chat_config_and_items(tmp_path):
    from server.chat.config import ChatConfig
    assert ChatConfig.model_validate({}).profile.model_dump()=={'name': 'You', 'avatar': ''}
    _, core, _ = make_app(tmp_path)
    m = core.modules['chat']
    sid = m.create_session('_default')['id']
    m.store.save_items(sid, [{'id': 'old', 'uuid': 'old', 'kind': 'user', 'text': 'Old message'}])
    assert m.store.load_items(sid)[0]['group']=='old'
    user = m.runtime(sid).items[0]
    assert user['group']=='old' and user['version']==user['reply_version']==[0, 1]


async def test_profile_patch_avatar_and_reload(chat):
    m, c = chat.manager, chat.http
    path = '/api/chat/profile/avatar'
    assert (await c.get('/api/chat/config')).json()['profile']=={'name': 'You', 'avatar': ''}
    assert (await c.get(path)).status_code==404
    assert (await c.patch('/api/chat/config', json={'profile': {'name': 'Alice', 'avatar': 'crab:pink'}})).json()['profile']=={
        'name': 'Alice', 'avatar': 'crab:pink'}
    assert (await c.patch('/api/chat/config', json={'profile': {'name': ''}})).status_code==422
    response = await c.post(path, files={'file': ('user.png', b'user-avatar', 'image/png')})
    assert response.json()=={'profile': {'name': 'Alice', 'avatar': 'file'}}
    avatar = await c.get(path)
    assert avatar.content==b'user-avatar' and avatar.headers['content-type']=='image/png'
    assert (m.store.avatars/'_user').read_bytes()==b'user-avatar'
    assert (m.store.avatars/'_user.mime').read_text()=='image/png'
    assert (await c.post(path, files={'file': ('a.svg', b'<svg/>', 'image/svg+xml')})).status_code==415
    assert (await c.post(path, files={'file': ('a.png', b'x'*(2*1024*1024+1), 'image/png')})).status_code==413
    assert (await c.patch('/api/chat/config', json={'profile': {'name': 'Renamed'}})).json()['profile']=={
        'name': 'Renamed', 'avatar': 'file'}
    m.config.replace_raw(m.config.path.read_text())
    assert (await c.get('/api/chat/meta')).json()['profile']=={'name': 'Renamed', 'avatar': 'file'}
    assert m.config.doc['profile']['name']=='Renamed'
    c.cookies.clear()
    assert (await c.post(path, files={'file': ('a.png', b'x', 'image/png')})).status_code==401


async def test_fetch_models_keys_headers_and_errors(chat, monkeypatch):
    m, c = chat.manager, chat.http
    requests = []
    response = httpx.Response(200, json={'data': [{'id': 'z'}, {'id': 'a'}, {'id': 'z'}]})

    def handle(request):
        requests.append(request)
        return response

    monkeypatch.setattr(providers, 'client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    body = m.config.data.providers[0].model_dump()
    path = '/api/chat/providers/models'
    for key in (None, '', 'unsaved-key'):
        body.pop('api_key', None)
        if key is not None: body['api_key'] = key
        result = await c.post(path, json=body)
        assert result.status_code==200 and result.json()=={'models': ['a', 'z']}
        request = requests[-1]
        assert request.method=='GET' and str(request.url)=='https://provider.test/v1/models'
        assert request.headers['x-extra']=='yes'
        expected = key or 'secret'
        if chat.format=='openai': assert request.headers['authorization']=='Bearer '+expected
        else: assert request.headers['x-api-key']==expected and request.headers['anthropic-version']=='2023-06-01'
    assert m.config.data.providers[0].api_key=='secret'
    if chat.format=='openai':
        assert (await c.post('/api/chat/providers/local/test')).json()=={'ok': True, 'models': ['a', 'z']}
    body.pop('api_key')
    body['id'] = 'new'
    assert (await c.post(path, json=body)).status_code==200
    assert requests[-1].headers.get('x-api-key', requests[-1].headers.get('authorization')) in ('', 'Bearer ')
    for invalid in ({}, {'data': {}}, {'data': [None]}, {'data': [{'id': 3}]}, []):
        response = httpx.Response(200, json=invalid)
        result = await c.post(path, json=body)
        assert result.status_code==502 and result.json()['detail']=='Invalid models response'
    response = httpx.Response(200, content=b'not json')
    assert (await c.post(path, json=body)).status_code==502
    response = httpx.Response(503, text='models unavailable')
    result = await c.post(path, json=body)
    assert result.status_code==502 and '503: models unavailable' in result.json()['detail']

    def unavailable(request): raise httpx.ConnectError('Connection refused', request=request)

    monkeypatch.setattr(providers, 'client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(unavailable)))
    result = await c.post(path, json=body)
    assert result.status_code==502 and 'Connection refused' in result.json()['detail']
    body['format'] = 'invalid'
    assert (await c.post(path, json=body)).status_code==422
    c.cookies.clear()
    assert (await c.post(path, json=body)).status_code==401
