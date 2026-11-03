import asyncio
import json
import time
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from server.acp.config import AcpAgent
from server.auth import COOKIE
from server.builtin import Builtin, epoch
from server.config import Agent, Defaults, ServerConfig
from server.options import build_options, options_key


class FakeBridge:
    def __init__(self, app):
        self.index = app.state.index
        self.acp = app.state.core.modules['acp']
        self.calls, self.states, self.transcripts, self.results = [], {}, {}, {}
        self.auto = False

    def start_claude(self, aid, prompt, **kwargs):
        self.calls.append(('agents', aid, prompt, kwargs))
        sid = kwargs['session_id']
        if not sid:
            sid = self.index.create(aid, kwargs['title'] or prompt[:60], origin=kwargs['origin'], parent=kwargs['parent'])['id']
        self.begin(sid, prompt)
        return sid

    def begin(self, sid, prompt):
        self.states[sid] = 'running'
        self.transcripts.setdefault(sid, []).append(dict(id=uuid4().hex, kind='user', text=prompt))
        self.results[sid] = asyncio.get_running_loop().create_future()
        if self.auto: asyncio.get_running_loop().call_soon(self.finish, sid)

    def finish(self, sid, text='Done', error=None):
        self.transcripts[sid].extend([dict(id=uuid4().hex, kind='text', text=text),
            dict(id=uuid4().hex, kind='result', is_error=bool(error))])
        self.states[sid] = 'idle'
        self.results[sid].set_result(dict(session_id=sid, text=text, is_error=bool(error), error=error))

    async def wait_claude(self, sid): return await asyncio.shield(self.results[sid])

    def start_acp(self, aid, prompt, **kwargs):
        self.calls.append(('acp', aid, prompt, kwargs))
        return self.acp.start_turn(aid, prompt, **kwargs)

    def view(self, module, sid):
        if module=='acp': return self.acp.view(sid)
        return {**self.index.sessions[sid], 'state': self.states.get(sid, 'offline')}

    def items(self, module, sid):
        return self.acp.items(sid) if module=='acp' else self.transcripts.get(sid, [])

    async def send(self, module, sid, prompt):
        self.calls.append(('send', module, sid, prompt))
        if module=='acp': await self.acp.send(sid, prompt)
        else: self.begin(sid, prompt)

    async def stop(self, module, sid):
        self.calls.append(('stop', module, sid))
        if module=='acp': await self.acp.stop(sid)
        else:
            self.states[sid] = 'interrupting'
            if not self.results[sid].done(): self.finish(sid, 'Stopped')


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate(): await asyncio.sleep(.005)


@pytest.fixture
async def builtin(app, monkeypatch):
    core = app.state.core
    events = []
    core.emit = events.append
    core.bridge = FakeBridge(app)
    config = app.state.config.config
    config.agents.extend([Agent(id='worker', name='Worker', cwd=str(app.state.paths.root), as_subagent=True),
                          Agent(id='private', name='Private', cwd=str(app.state.paths.root))])
    config.agents[0].as_subagent = True
    config.builtin_mcp['enabled'] = True
    acp = core.modules['acp']
    acp.config.data.agents.append(AcpAgent(id='phone', name='Phone', host='127.0.0.1', port=1, as_subagent=True))
    monkeypatch.setattr('server.builtin.create_sdk_mcp_server',
                        lambda name, tools: dict(type='sdk', name=name, instance=object(), tools={t.name: t for t in tools}))
    session = app.state.index.create('claude', 'Caller')
    module = core.modules['builtin']
    context = SimpleNamespace(app=app, core=core, module=module, schedules=module.schedules,
        config=config, agent=config.agents[0], session=session, events=events, bridge=core.bridge,
        caller=dict(module='agents', agent_id='claude', session_id=session['id']))
    yield context
    await module.close()
    await acp.close()
    await app.state.manager.shutdown()


def tools_for(b, session=None, agent=None):
    return b.module.servers_for(agent or b.agent, session or b.session)['next']['tools']


async def call(tools, name, args=None, error=False):
    result = await tools[name].handler(args or {})
    assert result.get('is_error', False)==error, result
    return json.loads(result['content'][0]['text'])


@pytest.mark.parametrize('global_values,override,origin,expected', [
    ({'enabled': False}, {}, 'ui', ()),
    ({'enabled': False}, {'enabled': True, 'history': False}, 'ui', ('schedules', 'collab')),
    ({}, {'enabled': False}, 'ui', ()),
    ({'schedules': False}, {'history': False, 'collab': False}, 'ui', ()),
    ({'schedules': False}, {'schedules': True}, 'subagent', ('schedules', 'history')),
    ({}, {}, 'ui', ('schedules', 'history', 'collab')),
])
async def test_effective_categories(builtin, global_values, override, origin, expected):
    b = builtin
    b.config.builtin_mcp.update(global_values)
    b.agent.builtin_mcp = override
    b.session['origin'] = origin
    assert b.module.categories_for(b.agent, b.session)==expected
    servers = b.module.servers_for(b.agent, b.session)
    assert bool(servers)==bool(expected)
    if expected:
        assert set('mcp__next__'+n for n in servers['next']['tools'])==set(b.module.allowed_tools(expected))


async def test_options_injection_and_stable_fingerprint(builtin):
    b = builtin
    b.agent.mcp_servers = {'external': {'command': 'tool'}}
    b.agent.allowed_tools = ['Read']
    b.session['extra'] = {'allowed_tools': ['Write']}
    def options(module=b.module, session=b.session):
        return build_options(b.agent, session, Defaults(), ServerConfig(password_hash='***'), None, builtin=module)
    first, second = options(), options()
    assert first.mcp_servers['next']['instance'] is not second.mcp_servers['next']['instance']
    assert options_key(first)==options_key(second)
    assert first.allowed_tools==['Write', *b.module.allowed_tools(('schedules', 'history', 'collab'))]
    assert b.agent.allowed_tools==['Read'] and set(b.agent.mcp_servers)=={'external'}
    assert options_key(first)==options_key(options(session={**b.session, 'id': 'different'}))
    b.agent.builtin_mcp['collab'] = False
    assert options_key(first)!=options_key(options())
    assert options(None).mcp_servers==b.agent.mcp_servers
    runtime = b.app.state.manager.get_or_create(b.session['id'])
    assert 'next' in runtime._build_options_for_key().mcp_servers


async def test_idle_runtime_restarts_only_for_effective_changes(builtin):
    from conftest import FakeClaudeSDKClient
    b = builtin
    manager = b.app.state.manager
    runtime = manager.get_or_create(b.session['id'])
    runtime.submit(('warm',))
    await until(lambda: runtime.state=='idle')
    assert 'next' in runtime.client.options.mcp_servers
    b.agent.builtin_mcp['history'] = False
    manager.reconfigure('claude')
    await until(lambda: len(FakeClaudeSDKClient.instances)==2 and runtime.state=='idle')
    assert 'mcp__next__history_read' not in runtime.client.options.allowed_tools
    manager.reconfigure('claude')
    await runtime.commands.join()
    assert len(FakeClaudeSDKClient.instances)==2


async def test_schedule_validation_ownership_and_persistence(builtin):
    b = builtin
    tools = tools_for(b)
    at = datetime.fromtimestamp(time.time()+600).isoformat()
    invalid = [dict(prompt='x'), dict(prompt='x', cron='* * * * *', at=at), dict(prompt=' ', cron='* * * * *'),
        dict(prompt='x', cron='* * * * * *'), dict(prompt='x', cron='bad'), dict(prompt='x', at='2000-01-01T00:00'),
        dict(prompt='x', at='tomorrow'), dict(prompt='x', target={'agent_id': 'worker', 'session': 'this'}, at=at),
        dict(prompt='x', target={'module': 'other'}, at=at)]
    foreign = b.app.state.index.create('worker')
    invalid.append(dict(prompt='x', target={'session': foreign['id']}, at=at))
    for data in invalid: assert 'error' in await call(tools, 'schedule_create', data, error=True)
    one = await call(tools, 'schedule_create', dict(prompt='Remind me', at=at, target={'session': 'this'}))
    assert one['target']==dict(module='agents', agent_id='claude', session=b.session['id'])
    assert one['created_by']==b.caller and one['next_run']==epoch(at)
    recurring = await call(tools, 'schedule_create', dict(prompt='Report', cron='0 9 * * *'))
    assert recurring['target']['session']=='new' and recurring['next_run']>time.time()
    assert datetime.fromtimestamp(recurring['next_run']).hour==9
    other = {**b.caller, 'agent_id': 'worker', 'session_id': foreign['id']}
    b.schedules.create(dict(prompt='Other', at=at), other)
    ui = b.schedules.create(dict(prompt='UI', at=at, target={'agent_id': 'claude'}))
    assert {s['id'] for s in await call(tools, 'schedule_list')}=={one['id'], recurring['id']}
    await call(tools, 'schedule_delete', {'id': ui['id']}, error=True)
    assert await call(tools, 'schedule_delete', {'id': one['id']})=={'ok': True}
    restored = Builtin(b.core)
    assert restored.schedules.entries==b.schedules.entries
    assert b.events[-1]=={'type': 'schedules_changed', 'module': 'builtin'}


async def test_scheduler_fires_without_waiting_and_disables_at(builtin):
    b = builtin
    cron = b.schedules.create(dict(prompt='Daily', cron='* * * * *', model='haiku', effort='low'), b.caller)
    one = b.schedules.create(dict(prompt='Once', at=datetime.fromtimestamp(time.time()+100).isoformat(),
                                 target={'session': 'this'}), b.caller)
    for s in (cron, one): s['next_run'] = time.time()-1
    await asyncio.wait_for(b.schedules.run_due(), 1)
    await until(lambda: len(b.bridge.calls)==2)
    assert len(b.bridge.calls)==2 and cron['enabled'] and cron['next_run']>time.time()
    assert not one['enabled'] and one['next_run'] is None and one['last_result'] is None
    kwargs = b.bridge.calls[0][3]
    assert kwargs['origin']=='schedule' and kwargs['title']=='Scheduled: Daily'
    assert kwargs['overrides']=={'model': 'haiku', 'effort': 'low'}
    assert b.bridge.calls[1][3]['session_id']==b.session['id']
    for sid in list(b.bridge.results): b.bridge.finish(sid)
    await until(lambda: one['last_result'] and cron['last_result'])
    assert one['last_result']==dict(session_id=b.session['id'], is_error=False, error=None)
    timetable = cron['next_run']
    await b.schedules.fire(cron['id'])
    assert cron['next_run']==timetable
    b.bridge.finish(next(reversed(b.bridge.results)), error='Failed')
    await until(lambda: cron['last_result'])
    assert cron['last_result']['is_error'] and cron['last_result']['error']=='Failed'


async def test_scheduler_startup_skip_missing_target_and_wakeup(builtin):
    b = builtin
    b.bridge.auto = True
    due = b.schedules.create(dict(prompt='Recent', cron='* * * * *'), b.caller)
    old = b.schedules.create(dict(prompt='Old', cron='* * * * *'), b.caller)
    expired = b.schedules.create(dict(prompt='Expired', at=datetime.fromtimestamp(time.time()+100).isoformat()), b.caller)
    missing = b.schedules.create(dict(prompt='Missing', cron='* * * * *', target={'agent_id': 'worker'}), b.caller)
    due['next_run'] = missing['next_run'] = time.time()-60
    old['next_run'] = expired['next_run'] = time.time()-7200
    b.config.agents[:] = [a for a in b.config.agents if a.id!='worker']
    await b.schedules.run_due(startup=True)
    await until(lambda: missing['last_result'])
    assert len(b.bridge.calls)==1 and old['next_run']>time.time() and not expired['enabled']
    assert not missing['enabled'] and missing['last_result']['error']
    scheduler = asyncio.create_task(b.schedules.run())
    try:
        await asyncio.sleep(.02)
        due['next_run'] = time.time()-1
        b.schedules.save()
        await until(lambda: len(b.bridge.calls)==2)
    finally:
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)


async def test_scheduler_slow_start_and_failed_acp_setup(builtin, monkeypatch):
    b = builtin
    gate = asyncio.Event()
    start = b.module.start
    async def slow(module, aid, prompt, **kwargs):
        if prompt=='Slow': await gate.wait()
        return await start(module, aid, prompt, **kwargs)
    monkeypatch.setattr(b.module, 'start', slow)
    for prompt in ('Slow', 'Fast'):
        schedule = b.schedules.create(dict(prompt=prompt, cron='* * * * *'), b.caller)
        schedule['next_run'] = time.time()-1
    await b.schedules.run_due()
    await until(lambda: b.bridge.calls)
    assert [c[2] for c in b.bridge.calls]==['Fast']
    gate.set()
    await until(lambda: len(b.bridge.calls)==2)
    for sid in list(b.bridge.results): b.bridge.finish(sid)
    await call(tools_for(b), 'task_create', dict(module='acp', agent_id='phone', prompt='Unavailable', model='large'), error=True)
    acp = b.core.modules['acp']
    assert all(r.state=='offline' and r.client is None for r in acp.runtimes.values())


async def test_history_is_scoped_paged_and_flattened(builtin, monkeypatch, tmp_path):
    b = builtin
    index = b.app.state.index
    own = index.create('claude', 'Old', sdk_session_id='old')
    own['updated_at'] = '2026-01-01T00:00:00+00:00'
    newer = index.create('claude', 'Needle title')
    newer['updated_at'] = '2026-02-01T00:00:00+00:00'
    foreign = index.create('worker', 'Needle private')
    transcript = tmp_path/'transcript.jsonl'
    transcript.write_text(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'A needle in history'}]}})+'\n')
    monkeypatch.setattr('server.history.transcript_path', lambda sid, cwd: transcript)
    b.bridge.transcripts[own['id']] = [dict(kind='user', text='U'*4100), dict(kind='thinking', text='Hidden'),
        dict(kind='text', text='A'*4100), dict(kind='tool', name='Read', input={'path': 'a\nb'}), dict(kind='result')]
    tools = tools_for(b)
    assert [s['session_id'] for s in await call(tools, 'history_list', {'limit': 1})]==[newer['id']]
    assert [s['session_id'] for s in await call(tools, 'history_list', {'before': epoch(newer['updated_at'])})]==[own['id']]
    hits = await call(tools, 'history_search', {'query': 'NEEDLE'})
    assert [h['session_id'] for h in hits]==[newer['id'], own['id']]
    assert hits[1]['snippet']=='A needle in history'
    result = await call(tools, 'history_read', {'session_id': own['id'], 'offset': 1, 'limit': 2})
    assert result['title']=='Old' and result['total']==3
    assert result['items'][0]==dict(role='assistant', text='A'*4000)
    assert result['items'][1]['role']=='tool' and '\n' not in result['items'][1]['text']
    await call(tools, 'history_read', {'session_id': foreign['id']}, error=True)
    await call(tools, 'history_list', {'limit': -1}, error=True)
    temp1 = index.create('_temp', 'Temp 1', cwd=str(tmp_path))
    temp2 = index.create('_temp', 'Temp 2', cwd='/')
    temp_tools = tools_for(b, temp1, b.app.state.manager.agent('_temp'))
    assert [s['session_id'] for s in await call(temp_tools, 'history_list')]==[temp2['id']]
    assert (await call(temp_tools, 'history_read', {'session_id': temp2['id']}))['total']==0


async def test_collaboration_lifecycle_ownership_and_recovery(builtin):
    b = builtin
    tools = tools_for(b)
    listed = await call(tools, 'agents_list')
    assert {(a['module'], a['agent_id']) for a in listed}=={('agents', 'worker'), ('acp', 'phone')}
    for aid in ('claude', 'private', 'missing'):
        await call(tools, 'task_create', dict(module='agents', agent_id=aid, prompt='Help'), error=True)
    task = await call(tools, 'task_create', dict(module='agents', agent_id='worker', prompt='Work', title='Delegate', model='haiku'))
    tid, sid = task['task_id'], task['session_id']
    assert task['state']=='running' and task['result'] is None
    session = b.bridge.view('agents', sid)
    assert session['origin']=='subagent' and session['parent']==dict(module='agents', session_id=b.session['id'], task_id=tid)
    assert b.bridge.calls[-1][3]['overrides']==dict(model='haiku', effort='')
    stranger = b.app.state.index.create('claude', 'Stranger')
    await call(tools_for(b, stranger), 'task_status', {'task_id': tid}, error=True)
    b.bridge.finish(sid, 'A'*4100)
    await until(lambda: b.module.collab.tasks[tid]['task']['result'])
    status = await call(tools, 'task_status', {'task_id': tid})
    assert status['last_text']=='A'*4000 and status['result']['text']=='A'*4100
    sent = await call(tools, 'task_send', {'task_id': tid, 'prompt': 'Again'})
    assert sent['result'] is None and b.bridge.calls[-1]==('send', 'agents', sid, 'Again')
    await call(tools, 'task_stop', {'task_id': tid})
    assert b.bridge.calls[-1]==('stop', 'agents', sid)
    await until(lambda: b.module.collab.tasks[tid]['task']['result'])
    b.module.collab.tasks.clear()
    status = await call(tools, 'task_status', {'task_id': tid})
    assert status['last_text']=='Stopped' and status['state']=='idle'
    assert [t['task_id'] for t in await call(tools, 'task_list')]==[tid]
    b.bridge.transcripts[sid] = [i for i in b.bridge.transcripts[sid] if i['kind']!='result']
    b.module.collab.tasks.clear()
    assert (await call(tools, 'task_status', {'task_id': tid}))['result'] is None
    b.bridge.auto = True
    task = await call(tools, 'task_create', dict(module='agents', agent_id='worker', prompt='Wait', wait=True))
    assert task['state']=='idle' and task['result']['text']=='Done'


async def test_acp_schedule_and_tasks_use_bridge_and_offered_options(builtin):
    from test_acp import Peer
    b = builtin
    peer = Peer()
    await peer.start()
    b.core.modules['acp'].agent('phone').port = peer.port
    try:
        schedule = b.schedules.create(dict(prompt='Scheduled', cron='* * * * *', target={'module': 'acp', 'agent_id': 'phone'},
                                           model='large', effort='high'), b.caller)
        fired = await b.schedules.fire(schedule['id'])
        await until(lambda: schedule['last_result'])
        assert not schedule['last_result']['is_error']
        assert b.bridge.view('acp', fired['session_id'])['origin']=='schedule'
        configs = [r['params'] for r in peer.requests if r['method']=='session/set_config_option']
        assert [(c['configId'], c['value']) for c in configs]==[('model', 'large')]
        assert b.bridge.calls[0][0]=='acp' and 'overrides' not in b.bridge.calls[0][3]
        tools = tools_for(b)
        task = await call(tools, 'task_create', dict(module='acp', agent_id='phone', prompt='Hi', wait=True))
        assert task['result']['text']=='Hello HiDone' and not task['result']['is_error']
        await call(tools, 'task_send', {'task_id': task['task_id'], 'prompt': 'hold'})
        await until(lambda: b.bridge.view('acp', task['session_id'])['state']=='running')
        await call(tools, 'task_send', {'task_id': task['task_id'], 'prompt': 'Followup'})
        for writer in list(peer.writers): writer.close()
        await until(lambda: b.module.collab.tasks[task['task_id']]['task']['result'])
        assert b.module.collab.tasks[task['task_id']]['task']['result']['text']=='Hello FollowupDone'
        await call(tools, 'task_send', {'task_id': task['task_id'], 'prompt': 'hold'})
        await until(lambda: b.bridge.view('acp', task['session_id'])['state']=='running')
        await call(tools, 'task_stop', {'task_id': task['task_id']})
        await until(lambda: b.module.collab.tasks[task['task_id']]['task']['result'])
        b.module.collab.tasks.clear()
        assert (await call(tools, 'task_status', {'task_id': task['task_id']}))['session_id']==task['session_id']
        assert not peer.errors
    finally:
        await b.core.modules['acp'].close()
        await peer.close()


async def test_rest_crud_auth_validation_and_task_list(builtin):
    b = builtin
    b.bridge.auto = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=b.app), base_url='http://testserver') as c:
        assert (await c.get('/api/builtin/schedules')).status_code==401
        c.cookies.set(COOKIE, b.core.auth.token())
        base = dict(prompt='UI job', cron='0 9 * * *', target={'agent_id': 'claude'})
        for bad in ({}, {**base, 'id': 'forged'}, {**base, 'enabled': 'yes'}, {**base, 'cron': 'bad'}, {**base, 'prompt': ' '}):
            assert (await c.post('/api/builtin/schedules', json=bad)).status_code==422
        response = await c.post('/api/builtin/schedules', json=base)
        assert response.status_code==200, response.text
        s = response.json()
        assert s['created_by'] is None
        path = '/api/builtin/schedules/'+s['id']
        assert (await c.get('/api/builtin/schedules')).json()==[s]
        assert (await c.patch(path, json={'title': 'Renamed'})).json()['title']=='Renamed'
        assert (await c.patch(path, json={'created_by': b.caller})).status_code==422
        assert (await c.patch(path, json={'enabled': False})).json()['next_run'] is None
        timetable = (await c.patch(path, json={'enabled': True})).json()['next_run']
        assert 'session_id' in (await c.post(path+'/run')).json()
        assert b.schedules.get(s['id'])['next_run']==timetable
        def failed(*args, **kwargs): raise RuntimeError('Cannot start')
        successful = b.bridge.start_claude
        b.bridge.start_claude = failed
        assert (await c.post(path+'/run')).status_code==502
        assert b.schedules.get(s['id'])['last_result']['error']=='Cannot start'
        b.bridge.start_claude = successful
        task = await call(tools_for(b), 'task_create', dict(module='agents', agent_id='worker', prompt='Task', wait=True))
        assert (await c.get('/api/builtin/tasks', params={'session_id': b.session['id']})).json()==[task]
        assert (await c.delete(path)).json()=={'ok': True}
        assert (await c.delete(path)).status_code==404
        assert (await c.patch(path, json={})).status_code==404
        assert (await c.post(path+'/run')).status_code==404
        assert (await c.get('/api/builtin/schedules')).json()==[]


def test_builtin_config_and_agent_fields(logged, app):
    defaults = dict(enabled=False, schedules=True, history=True, collab=True)
    assert logged.get('/api/config').json()['builtin_mcp']==defaults
    assert logged.patch('/api/config', json={'builtin_mcp': {'enabled': True, 'history': False}}).status_code==200
    assert logged.get('/api/config').json()['builtin_mcp']=={**defaults, 'enabled': True, 'history': False}
    assert logged.patch('/api/config', json={'builtin_mcp': {'collab': 'yes'}}).status_code==422
    for aid in ('claude', '_temp'):
        response = logged.patch('/api/agents/'+aid, json={'builtin_mcp': {'history': True}, 'as_subagent': True})
        assert response.status_code==200 and response.json()['builtin_mcp']=={'history': True}
        assert response.json()['as_subagent'] is True
        assert logged.patch('/api/agents/'+aid, json={'builtin_mcp': {'history': 'yes'}}).status_code==422
    app.state.config.load()
    assert app.state.config.config.temp_agent.as_subagent
