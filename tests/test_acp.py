import asyncio
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.acp import mount
from server.acp.client import AcpConnection, AcpError, LINE_LIMIT
from server.acp.config import config_file
from server.acp.runtime import AcpManager
from server.acp.store import AcpStore
from server.auth import Auth, COOKIE
from server.core import Core
from server.paths import DataDir


OPTIONS = [{'id': 'model', 'name': 'Model', 'type': 'select', 'currentValue': 'small',
            'options': [{'value': 'small', 'name': 'Small'}, {'value': 'large', 'name': 'Large'}]}]
MODES = {'currentModeId': 'ask', 'availableModes': [{'id': 'ask', 'name': 'Ask'}, {'id': 'auto', 'name': 'Auto'}]}


class Peer:
    def __init__(self):
        self.server = None
        self.writers = set()
        self.handlers = set()
        self.requests = []
        self.auth = []
        self.errors = []
        self.permissions = {}
        self.cancelled = {}
        self.sessions = set()
        self.serial = 0
        self.load_missing = False
        self.capabilities = {'loadSession': True, 'promptCapabilities': {'image': True, 'embeddedContext': True},
                             'sessionCapabilities': {'list': True}}

    async def start(self):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        for writer in list(self.writers): writer.close()
        for task in list(self.handlers): task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)

    async def write(self, writer, message):
        writer.write((json.dumps({'jsonrpc': '2.0', **message})+'\n').encode())
        await writer.drain()

    async def update(self, writer, sid, update_kind, **fields):
        await self.write(writer, {'method': 'session/update', 'params': {'sessionId': sid, 'update': {'sessionUpdate': update_kind, **fields}}})

    async def turn(self, writer, message):
        params = message['params']
        sid = params['sessionId']
        prompt = params['prompt']
        text = next((b['text'] for b in prompt if b['type']=='text'), '')
        self.cancelled[sid] = asyncio.Event()
        try:
            await self.update(writer, sid, 'user_message_chunk', content={'type': 'text', 'text': text})
            if text=='disconnect':
                await self.update(writer, sid, 'agent_message_chunk', content={'type': 'text', 'text': 'partial'})
                writer.close()
                return
            if text=='rpc-error':
                await self.write(writer, {'id': message['id'], 'error': {'code': -32602, 'message': 'bad prompt'}})
                return
            if text=='hold':
                await self.cancelled[sid].wait()
            else:
                await self.update(writer, sid, 'agent_message_chunk', content={'type': 'text', 'text': 'Hello '})
                await self.update(writer, sid, 'agent_message_chunk', content={'type': 'text', 'text': text or 'upload'})
                await self.update(writer, sid, 'agent_thought_chunk', content={'type': 'text', 'text': 'think'})
                await self.update(writer, sid, 'agent_thought_chunk', content={'type': 'text', 'text': 'ing'})
                await self.update(writer, sid, 'tool_call', toolCallId='tool-1', title='Read', kind='read', status='pending', rawInput={'path': '/tmp/x'})
                await self.update(writer, sid, 'tool_call_update', toolCallId='tool-1', title='Read file', status='in_progress',
                                  content=[{'type': 'content', 'content': {'type': 'text', 'text': 'one'}},
                                           {'type': 'content', 'content': {'type': 'text', 'text': 'two'}},
                                           {'type': 'diff', 'path': '/tmp/x', 'oldText': 'old', 'newText': 'new'}])
                if text=='permission':
                    rid = 'agent-'+str(message['id'])
                    future = asyncio.get_running_loop().create_future()
                    self.permissions[rid] = future
                    await self.write(writer, {'id': rid, 'method': 'session/request_permission',
                        'params': {'sessionId': sid, 'toolCall': {'toolCallId': 'tool-1', 'title': 'Read file'},
                                   'options': [{'optionId': 'allow', 'name': 'Allow', 'kind': 'allow_once'},
                                               {'optionId': 'deny', 'name': 'Deny', 'kind': 'reject_once'}]}})
                    await future
                await self.update(writer, sid, 'tool_call_update', toolCallId='tool-1', status='completed')
                await self.update(writer, sid, 'plan', entries=[{'content': 'Do work', 'priority': 'high', 'status': 'pending'}])
                await self.update(writer, sid, 'plan', entries=[{'content': 'Do work', 'priority': 'high', 'status': 'completed'}])
                await self.update(writer, sid, 'available_commands_update', availableCommands=[{'name': 'help', 'description': 'Help'}])
                await self.update(writer, sid, 'current_mode_update', currentModeId='auto')
                await self.update(writer, sid, 'config_option_update', configOptions=OPTIONS)
                if text=='title': await self.update(writer, sid, 'session_info_update', title='Remote title')
                await self.update(writer, sid, 'usage_update', used=10, size=100)
                await self.update(writer, sid, 'future_update', ignored=True)
                await self.update(writer, sid, 'agent_message_chunk', content={'type': 'text', 'text': 'Done'})
            reason = 'cancelled' if self.cancelled[sid].is_set() else 'end_turn'
            await self.write(writer, {'id': message['id'], 'result': {'stopReason': reason}})
        except (ConnectionError, asyncio.CancelledError): pass

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.writers.add(writer)
        turns = set()
        try:
            line = await reader.readline()
            if line.startswith(b'AUTH '):
                self.auth.append(line.decode())
                line = await reader.readline()
            while line:
                message = json.loads(line)
                if 'method' not in message:
                    self.permissions[message['id']].set_result(message)
                else:
                    self.requests.append(message)
                    method, params = message['method'], message['params']
                    if method=='initialize':
                        assert params['protocolVersion']==1
                        assert params['clientCapabilities']=={'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False}
                        result = {'agentCapabilities': self.capabilities, 'agentInfo': {'name': 'fake', 'title': 'Fake ACP', 'version': '1'}}
                    elif method=='session/new':
                        assert params['mcpServers']==[]
                        self.serial += 1
                        sid = str(self.serial)
                        self.sessions.add(sid)
                        result = {'sessionId': sid, 'modes': MODES, 'configOptions': OPTIONS}
                    elif method=='session/load':
                        if self.load_missing:
                            await self.write(writer, {'id': message['id'], 'error': {'code': -32602, 'message': 'Unknown session'}})
                            line = await reader.readline()
                            continue
                        await self.update(writer, params['sessionId'], 'agent_message_chunk', content={'type': 'text', 'text': 'REPLAY MUST NOT APPEAR'})
                        await self.update(writer, params['sessionId'], 'session_info_update', title='Replay title')
                        result = {'modes': MODES, 'configOptions': OPTIONS}
                    elif method=='session/set_config_option':
                        result = {'configOptions': [{**OPTIONS[0], 'currentValue': params['value']}]}
                    elif method=='session/set_mode': result = {}
                    elif method=='malformed-error':
                        await self.write(writer, {'id': message['id'], 'error': {}})
                        line = await reader.readline()
                        continue
                    elif method=='session/list': result = {'sessions': [{'sessionId': sid, 'cwd': '/', 'title': sid, 'updatedAt': ''} for sid in self.sessions]}
                    elif method=='session/prompt':
                        turn = asyncio.create_task(self.turn(writer, message))
                        turns.add(turn)
                        turn.add_done_callback(turns.discard)
                        line = await reader.readline()
                        continue
                    elif method=='session/cancel':
                        assert 'id' not in message
                        self.cancelled[params['sessionId']].set()
                        line = await reader.readline()
                        continue
                    else:
                        await self.write(writer, {'id': message['id'], 'error': {'code': -32601, 'message': 'Method not found'}})
                        line = await reader.readline()
                        continue
                    await self.write(writer, {'id': message['id'], 'result': result})
                line = await reader.readline()
        except (asyncio.CancelledError, ConnectionError): pass
        except Exception as exc:
            self.errors.append(exc)
        finally:
            for turn in turns: turn.cancel()
            await asyncio.gather(*turns, return_exceptions=True)
            writer.close()
            await writer.wait_closed()
            self.writers.discard(writer)
            self.handlers.discard(task)


def make_app(tmp_path):
    paths = DataDir(tmp_path)
    paths.prepare()
    auth = Auth(paths, SimpleNamespace(config=SimpleNamespace(server=SimpleNamespace(password_hash='test-hash'))))
    events = []
    core = Core(paths, auth, auth.require_auth, events.append, lambda: None, version='test', modules={'raw_configs': {}})

    @asynccontextmanager
    async def lifespan(app):
        await core.start()
        try: yield
        finally: await core.stop()

    app = FastAPI(lifespan=lifespan)
    mount(app, core)
    return app, core, events


@pytest.fixture
async def acp(tmp_path):
    app, core, events = make_app(tmp_path)
    peer = Peer()
    await peer.start()
    manager = core.modules['acp']
    await manager.create_agent({'id': 'phone', 'name': 'Phone', 'host': '127.0.0.1', 'port': peer.port, 'token': 'secret', 'config_defaults': {'model': 'large'}})
    await core.start()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', cookies={COOKIE: core.auth.token()}) as client:
        yield SimpleNamespace(app=app, core=core, manager=manager, peer=peer, http=client, events=events)
    await core.stop()
    await peer.close()
    assert not peer.errors


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate(): await asyncio.sleep(.005)


async def test_turn_mapping_persistence_and_restart(acp):
    m = acp.manager
    result = await asyncio.wait_for(m.run_turn('phone', 'first'), 3)
    sid = result['session_id']
    assert result=={'session_id': sid, 'text': 'Hello firstDone', 'stop_reason': 'end_turn'}
    session = m.view(sid)
    assert (session['title'], session['preview'], session['turns'], session['unread'], session['state'])==('first', 'Done', 1, True, 'idle')
    items = m.items(sid)
    assert [i['kind'] for i in items]==['user', 'text', 'thinking', 'tool', 'plan', 'text', 'result']
    assert items[0]['pending'] is False
    assert items[1]['text']=='Hello first' and items[1]['streaming'] is False
    assert items[2]['text']=='thinking'
    assert items[3]['name']=='Read file' and items[3]['input']=={'path': '/tmp/x'}
    assert items[3]['result']=={'content': 'one\ntwo', 'is_error': False, 'images': [], 'diffs': [{'path': '/tmp/x', 'old_text': 'old', 'new_text': 'new'}]}
    assert items[4]['entries'][0]['status']=='completed'
    assert session['commands'][0]['name']=='help'
    assert acp.peer.auth==['AUTH secret\n']
    assert [r['method'] for r in acp.peer.requests[:4]]==['initialize', 'session/new', 'session/set_config_option', 'session/prompt']
    ring = list(m.runtime(sid).ring)
    first_text = next(e for e in ring if e.get('item', {}).get('kind')=='text')
    assert first_text['item']['text']=='Hello ' and first_text['item']['streaming'] is True
    assert any(e['type']=='delta' and e['text']=='first' for e in ring)
    assert m.store.load_items(sid)==items
    assert acp.core.hello[0]()['acp_sessions'][0]['id']==sid
    assert any(e.get('module')=='acp' and e['state']=='running' for e in acp.events)
    assert acp.core.modules['overview_acp']()=={'acp_agents': 1, 'sessions': 1}
    await m.close()
    restored = AcpManager(acp.core, m.config, AcpStore(acp.core.paths.root))
    assert restored.view(sid)['state']=='offline'
    assert restored.items(sid)==items
    assert not restored.runtimes[sid].worker
    await restored.close()


async def test_load_replay_missing_session_and_titles(acp):
    m = acp.manager
    sid = (await m.run_turn('phone', 'original'))['session_id']
    remote = m.view(sid)['remote_id']
    await m.sleep(sid)
    await m.run_turn('phone', 'title', session_id=sid)
    assert m.view(sid)['title']=='Remote title'
    assert m.view(sid)['remote_id']==remote
    assert 'REPLAY' not in json.dumps(m.items(sid))
    assert sum(r['method']=='session/set_config_option' for r in acp.peer.requests)==1
    await m.sleep(sid)
    acp.peer.load_missing = True
    await m.run_turn('phone', 'after', session_id=sid)
    assert m.view(sid)['remote_id']!=remote
    assert any(i['kind']=='notice' and i['level']=='warn' and 'Remote session was gone' in i['text'] for i in m.items(sid))
    assert sum(r['method']=='session/set_config_option' for r in acp.peer.requests)==2


async def test_permission_queue_cancel_and_interrupt(acp):
    m = acp.manager
    sid = m.start_turn('phone', 'permission')
    runtime = m.runtime(sid)
    await until(lambda: runtime.permissions)
    assert m.view(sid)['origin']=='subagent' and m.agents()[0]['status']['pending']==1
    pid = next(iter(runtime.permissions))
    with pytest.raises(ValueError): runtime.reply_permission(pid, 'invalid')
    next_turn = asyncio.create_task(m.run_turn('phone', 'next', session_id=sid))
    await until(lambda: runtime.queued)
    dropped = runtime.enqueue('drop')
    await until(lambda: len(runtime.queued)==2)
    drop_id = runtime.queued[-1][0]['item']['id']
    assert runtime.queued[0][0]['item']['queued'] is True
    await runtime.submit('cancel_queued', drop_id)
    assert (await dropped)['stop_reason']=='cancelled'
    assert next(i for i in m.items(sid) if i['id']==drop_id)['cancelled']
    assert not next_turn.done()
    runtime.reply_permission(pid, 'allow')
    assert (await asyncio.wait_for(next_turn, 3))['text']=='Hello nextDone'
    assert next(iter(acp.peer.permissions.values())).result()['result']=={'outcome': {'outcome': 'selected', 'optionId': 'allow'}}
    task = asyncio.create_task(m.run_turn('phone', 'permission', session_id=sid))
    await until(lambda: runtime.permissions)
    await m.stop(sid)
    assert (await asyncio.wait_for(task, 3))['stop_reason']=='cancelled'
    assert not runtime.permissions
    assert list(acp.peer.permissions.values())[-1].result()['result']=={'outcome': {'outcome': 'cancelled'}}
    assert not any(r['params'].get('prompt', [{}])[0].get('text')=='drop' for r in acp.peer.requests if r['method']=='session/prompt')


async def test_disconnect_rpc_error_and_shutdown(acp):
    m = acp.manager
    result = await m.run_turn('phone', 'disconnect')
    sid = result['session_id']
    assert result['stop_reason']=='disconnected' and result['text']=='partial' and result['is_error']
    assert m.view(sid)['state']=='offline'
    assert m.items(sid)[-1]['stop_reason']=='disconnected'
    result = await m.run_turn('phone', 'rpc-error', session_id=sid)
    assert result['stop_reason']=='error' and result['error']=='bad prompt'
    task = asyncio.create_task(m.run_turn('phone', 'permission', session_id=sid))
    await until(lambda: m.runtime(sid).permissions)
    queued = asyncio.create_task(m.run_turn('phone', 'queued', session_id=sid))
    await until(lambda: m.runtime(sid).queued)
    with pytest.raises(HTTPException) as exc: await m.sleep(sid)
    assert exc.value.status_code==409
    await m.close()
    assert (await task)['stop_reason']=='disconnected'
    assert (await queued)['stop_reason']=='disconnected'
    assert not m.runtime(sid).permissions
    assert m.view(sid)['state']=='offline'


async def test_rest_config_sessions_uploads_and_auth(acp):
    c, m = acp.http, acp.manager
    agent = (await c.get('/api/acp/agents/phone')).json()
    assert agent['kind']=='acp' and agent['token']=='' and agent['token_set'] is True
    assert (await c.patch('/api/acp/agents/phone', json={'token': None, 'name': 'New name'})).status_code==200
    assert m.agent('phone').token=='secret'
    assert (await c.patch('/api/acp/agents/phone', json={'token': ''})).json()['token_set'] is False
    assert (await c.post('/api/acp/agents', json={'name': 'Phone', 'host': 'localhost', 'port': 1})).status_code==409
    for body in ({'id': '../bad', 'name': 'Bad', 'host': 'x', 'port': 1}, {'name': 'Bad', 'host': 'x', 'port': 0}, {'name': 'Bad', 'host': 'x', 'port': 1, 'token': 'x\ny'}):
        assert (await c.post('/api/acp/agents', json=body)).status_code==422
    assert (await c.patch('/api/acp/agents/phone', json={'id': 'new'})).status_code==400
    assert (await c.put('/api/acp/groups', json={'groups': [' Work ', 'Home']})).json()=={'groups': ['Work', 'Home']}
    assert (await c.patch('/api/acp/agents/phone', json={'group': 'Work'})).status_code==200
    await c.put('/api/acp/groups', json={'groups': ['Renamed'], 'renames': {'Work': 'Renamed'}})
    assert m.agent('phone').group=='Renamed'
    assert (await c.put('/api/acp/groups', json={'groups': ['x', 'x']})).status_code==422
    assert (await c.post('/api/acp/agents/reorder', json={'ids': []})).status_code==400
    assert (await c.post('/api/acp/agents/reorder', json={'ids': ['phone']})).status_code==200
    tested = (await c.post('/api/acp/agents/phone/test')).json()
    assert tested['ok'] and tested['config_options']==OPTIONS and tested['info']['name']=='fake'
    assert not m.store.sessions
    assert (await c.post('/api/acp/agents/phone/avatar', files={'file': ('x.svg', b'<svg/>', 'image/svg+xml')})).status_code==415
    assert (await c.post('/api/acp/agents/phone/avatar', files={'file': ('x.png', b'x'*(2*1024*1024+1), 'image/png')})).status_code==413
    assert (await c.post('/api/acp/agents/phone/avatar', files={'file': ('x.png', b'png', 'image/png')})).json()['avatar']=='file'
    assert (await c.get('/api/acp/agents/phone/avatar')).content==b'png'
    sid = (await c.post('/api/acp/agents/phone/sessions', json={})).json()['id']
    assert m.view(sid)['state']=='offline'
    response = await c.post(f'/api/acp/sessions/{sid}/uploads', files=[('files', ('note.txt', b'file text', 'text/plain')), ('files', ('pic.png', b'image', 'image/png'))])
    uploads = response.json()
    assert response.status_code==200 and len(uploads)==2
    assert (await c.get(uploads[0]['url'])).content==b'file text'
    other = m.create_session('phone')['id']
    assert (await c.get(f'/api/acp/uploads/{other}/{uploads[0]["id"]}')).status_code==404
    await m.runtime(sid).enqueue('files', uploads)
    prompt = [r['params']['prompt'] for r in acp.peer.requests if r['method']=='session/prompt'][-1]
    assert [b['type'] for b in prompt]==['text', 'resource', 'image']
    assert prompt[1]['resource']['text']=='file text' and prompt[2]['data']=='aW1hZ2U='
    fallback = m.store.prompt('', uploads, {})
    assert [b['text'] for b in fallback]==['The user sent a file: note.txt', 'The user sent a file: pic.png']
    assert (await c.post(f'/api/acp/sessions/{sid}/read')).json()['unread'] is False
    assert (await c.patch(f'/api/acp/sessions/{sid}', json={'title': 'Changed'})).json()['title']=='Changed'
    items = (await c.get(f'/api/acp/sessions/{sid}/items', params={'limit': 2})).json()
    assert items['has_more'] and len(items['items'])==2
    previous = (await c.get(f'/api/acp/sessions/{sid}/items', params={'before': items['items'][0]['id'], 'limit': 2})).json()
    assert len(previous['items'])==2 and previous['items'][-1]['id']!=items['items'][0]['id']
    assert (await c.get('/api/acp/agents/phone/search', params={'q': 'HELLO files'})).json()[0]['session']['id']==sid
    assert (await c.post(f'/api/acp/sessions/{sid}/sleep')).json()['state']=='offline'
    assert acp.core.modules['raw_configs']['acp'] is m.config
    raw = m.config.path.read_text().replace('idle_timeout_min = 10', 'idle_timeout_min = 0')
    m.config.replace_raw(raw)
    await m.config.changed()
    assert m.config.data.server.idle_timeout_min==0
    assert (await c.delete('/api/acp/agents/phone')).json()=={'ok': True}
    assert not m.store.sessions and not (m.store.root/'items'/f'{sid}.jsonl').exists()
    assert not (m.store.root/'uploads'/sid).exists()
    assert not (m.store.avatars/'phone').exists()
    c.cookies.clear()
    assert (await c.get('/api/acp/agents')).status_code==401


def receive_until(ws, predicate):
    for _ in range(200):
        event = ws.receive_json()
        if predicate(event): return event
    raise AssertionError('Expected WebSocket event was not received')


def test_websocket_resume_permissions_and_disconnect(tmp_path):
    app, core, events = make_app(tmp_path)
    m = core.modules['acp']
    peer = Peer()
    with TestClient(app, base_url='http://testserver') as c:
        c.portal.call(peer.start)
        try:
            with pytest.raises(WebSocketDisconnect) as exc:
                with c.websocket_connect('/ws/acp/missing', headers={'origin': 'http://testserver'}) as ws: ws.receive_json()
            assert exc.value.code==4401
            c.cookies.set(COOKIE, core.auth.token())
            c.post('/api/acp/agents', json={'id': 'phone', 'name': 'Phone', 'host': '127.0.0.1', 'port': peer.port, 'token': 'secret'})
            sid = c.post('/api/acp/agents/phone/sessions', json={}).json()['id']
            path = f'/ws/acp/{sid}'
            with pytest.raises(WebSocketDisconnect) as exc:
                with c.websocket_connect(path, headers={'origin': 'http://elsewhere'}) as ws: ws.receive_json()
            assert exc.value.code==4403
            with pytest.raises(WebSocketDisconnect) as exc:
                with c.websocket_connect('/ws/acp/missing', headers={'origin': 'http://testserver'}) as ws: ws.receive_json()
            assert exc.value.code==4404
            with c.websocket_connect(path, headers={'origin': 'http://testserver'}) as ws:
                ws.send_json({'type': 'resume', 'seq': 0})
                assert ws.receive_json()['type']=='snapshot'
                assert ws.receive_json()['type']=='resumed'
                assert not peer.requests
                ws.send_json({'type': 'send', 'text': 'permission', 'client_id': 'one'})
                permission = receive_until(ws, lambda e: e['type']=='permission')['request']
                assert permission['options'][0]['option_id']=='allow'
                ws.send_json({'type': 'permission_reply', 'id': permission['id'], 'option_id': 'unknown', 'req_id': 'bad'})
                assert receive_until(ws, lambda e: e['type']=='error')['req_id']=='bad'
                assert c.post(f'/api/acp/sessions/{sid}/sleep').status_code==409
                ws.send_json({'type': 'send', 'text': 'drop', 'client_id': 'two'})
                queued = receive_until(ws, lambda e: e.get('item', {}).get('client_id')=='two')['item']
                assert queued['queued'] and queued['pending']
                ws.send_json({'type': 'cancel_queued', 'id': queued['id']})
                assert receive_until(ws, lambda e: e.get('patch', {}).get('cancelled'))['id']==queued['id']
                ws.send_json({'type': 'permission_reply', 'id': permission['id'], 'option_id': 'allow'})
                receive_until(ws, lambda e: e.get('item', {}).get('kind')=='result')
                session = receive_until(ws, lambda e: e['type']=='session' and e['session']['turns']==1)['session']
                assert session['unread'] is False
                ws.send_json({'type': 'set_config', 'config_id': 'model', 'value': 'large'})
                receive_until(ws, lambda e: e['type']=='session' and e['session']['config_options'][0]['currentValue']=='large')
                ws.send_json({'type': 'set_mode', 'mode_id': 'ask'})
                receive_until(ws, lambda e: e['type']=='session' and e['session']['modes']['currentModeId']=='ask')
                ws.send_json({'type': 'send', 'text': 'hold'})
                last = receive_until(ws, lambda e: e['type']=='state' and e['state']=='running')['seq']
            assert c.get(f'/api/acp/sessions/{sid}').json()['state']=='running'
            c.portal.call(m.stop, sid)
            c.portal.call(until, lambda: m.view(sid)['state']=='idle')
            assert m.view(sid)['unread'] is True
            with c.websocket_connect(path, headers={'origin': 'http://testserver'}) as ws:
                ws.send_json({'type': 'resume', 'seq': last})
                replay = []
                while True:
                    event = ws.receive_json()
                    if event['type']=='resumed': break
                    replay.append(event)
                assert replay and all(e['type']!='snapshot' and e['seq']>last for e in replay)
                assert [e['seq'] for e in replay]==sorted({e['seq'] for e in replay})
                assert any(e.get('item', {}).get('stop_reason')=='cancelled' for e in replay)
                ws.send_json({'type': 'resume', 'seq': 999999})
                assert ws.receive_json()['type']=='snapshot'
                assert ws.receive_json()['type']=='resumed'
                ws.send_json({'type': 'ping'})
                assert ws.receive_json()['type']=='pong'
                ws.send_json({'type': 'send', 'text': {'bad': 'input'}, 'req_id': 'invalid'})
                assert ws.receive_json()['req_id']=='invalid'
            assert not m.view(sid)['unread']
        finally:
            c.portal.call(m.close)
            c.portal.call(peer.close)
    assert not peer.errors


async def test_client_server_requests_errors_and_large_lines(acp):
    connection = AcpConnection()
    try:
        await connection.open('127.0.0.1', acp.peer.port, 'secret')
        await connection.initialize('test')
        assert (await connection.request('session/list', {}))=={'sessions': []}
        with pytest.raises(AcpError) as exc: await connection.request('unknown', {})
        assert exc.value.code==-32601
        writer = next(iter(acp.peer.writers))
        for method in ('fs/read_text_file', 'terminal/create'):
            future = asyncio.get_running_loop().create_future()
            acp.peer.permissions[method] = future
            await acp.peer.write(writer, {'id': method, 'method': method, 'params': {}})
            assert (await asyncio.wait_for(future, 2))['error']['code']==-32601
        await acp.peer.write(writer, {'method': 'session/update', 'params': {'large': 'x'*100000}})
        assert await connection.request('session/list', {})=={'sessions': []}
        writer.write(b'x'*(LINE_LIMIT+1)+b'\n')
        with pytest.raises((ConnectionError, BrokenPipeError)):
            await writer.drain()
            await asyncio.wait_for(connection.closed, 3)
            await connection.request('session/list', {})
        assert connection.closed.done()
    finally: await connection.close()


async def test_connection_test_failure_and_timeout(acp, monkeypatch):
    async def refused(*args): raise ConnectionRefusedError('refused')
    with monkeypatch.context() as patch:
        patch.setattr(AcpConnection, 'open', refused)
        response = await acp.http.post('/api/acp/agents/phone/test')
        assert response.status_code==200 and response.json()['ok'] is False and response.json()['error']=='refused'
    async def stalled(*args): await asyncio.Future()
    with monkeypatch.context() as patch:
        patch.setattr(AcpConnection, 'initialize', stalled)
        started = time.monotonic()
        response = await acp.http.post('/api/acp/agents/phone/test')
        assert 9<=time.monotonic()-started<12
        assert response.status_code==200 and response.json()['ok'] is False
    assert not acp.manager.store.sessions
    await until(lambda: not acp.peer.writers)


async def test_offline_config_connect_and_idle_reaper(acp, monkeypatch):
    m = acp.manager
    sid = m.create_session('phone')['id']
    runtime = m.runtime(sid)
    await runtime.submit('set_config', {'config_id': 'model', 'value': 'large'})
    assert runtime.state=='idle' and m.view(sid)['turns']==0
    assert m.view(sid)['config_options'][0]['currentValue']=='large'
    runtime.last_activity = time.monotonic()-1000
    import server.acp.runtime as module
    original = asyncio.sleep
    async def tick(seconds): await original(.005)
    monkeypatch.setattr(module, 'asyncio', SimpleNamespace(**{**vars(asyncio), 'sleep': tick}))
    m.config.data.server.idle_timeout_min = 0
    task = asyncio.create_task(m.reaper())
    await original(.02)
    assert runtime.state=='idle'
    m.config.data.server.idle_timeout_min = 10
    await until(lambda: runtime.state=='offline')
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_malformed_peer_response_fails_pending_request(acp):
    connection = AcpConnection()
    try:
        await connection.open('127.0.0.1', acp.peer.port)
        await connection.initialize()
        with pytest.raises(ConnectionError, match='Invalid JSON-RPC error'):
            await asyncio.wait_for(connection.request('malformed-error', {}), 2)
        assert connection.closed.done() and not connection.pending
    finally: await connection.close()
