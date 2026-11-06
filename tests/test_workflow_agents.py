import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_workflow import events, make_wf, ref, run


class FakeBridge:
    def __init__(self):
        self.calls, self.stops, self.sessions = [], [], {}
        self.block = False
        self.error = None

    async def turn(self, module, aid, prompt, **kwargs):
        on_session = kwargs.pop('on_session')
        sid = kwargs['session_id'] or f'session-{len(self.sessions)+1}'
        if sid in self.sessions: assert self.sessions[sid]['agent_id']==aid
        else: self.sessions[sid] = dict(id=sid, agent_id=aid, module=module, state='running',
                                       **{k: kwargs[k] for k in ('origin', 'title', 'parent')})
        on_session(sid)
        self.calls.append((module, aid, prompt, kwargs))
        if self.block: await asyncio.Future()
        self.sessions[sid]['state'] = 'idle'
        return dict(session_id=sid, text='Answer: '+prompt, structured={'ok': True}, cost_usd=.05,
                    is_error=bool(self.error), error=self.error)

    async def run_claude(self, *args, **kwargs): return await self.turn('agents', *args, **kwargs)
    async def run_more(self, *args, **kwargs): return await self.turn('acp', *args, **kwargs)
    async def stop(self, module, sid):
        self.stops.append((module, sid))
        self.sessions[sid]['state'] = 'idle'
    def view(self, module, sid): return self.sessions[sid]


@pytest.fixture
def bridge(app, monkeypatch):
    fake = FakeBridge()
    monkeypatch.setattr(app.state.core, 'bridge', fake)
    return fake


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate(): await asyncio.sleep(.01)


@pytest.mark.parametrize('card,aid,module', [('temp_task', '_temp', 'agents'), ('agent_task', 'claude', 'agents'), ('acp_task', 'remote', 'acp')])
def test_cards_continue_and_session_events(logged, bridge, card, aid, module):
    params = {'prompt': 'hello'}
    if card!='temp_task': params['agent'] = aid
    wid = make_wf(logged, [
        {'id': 'a', 'type': 'builtin.'+card, 'params': params},
        {'id': 'b', 'type': 'builtin.'+card, 'note': 'Follow up',
         'params': {**params, 'prompt': ['continue ', ref('a', 'result')], 'session_id': [ref('a', 'session_id')]}}
    ])
    answer = run(logged, wid)
    assert answer['status']=='success' and answer['result']=='Answer: continue Answer: hello'
    assert answer['cost_usd']==pytest.approx(.1 if module=='agents' else 0)
    assert len(bridge.sessions)==1 and len(bridge.calls)==2
    first, second = bridge.calls
    assert first[:3]==(module, aid, 'hello') and first[3]['origin']=='workflow'
    name = {'temp_task': 'Temporary task', 'agent_task': 'Agent task', 'acp_task': 'ACP agent task'}[card]
    assert first[3]['title']==f't: {name}' and second[3]['title']=='Follow up'
    assert first[3]['parent']=={'module': 'workflow', 'run_id': answer['run_id'], 'block_id': 'a'}
    assert second[3]['session_id']=='session-1'
    if module=='agents':
        assert first[3]['extra']=={} and all(v is None for v in first[3]['overrides'].values())
    if card=='temp_task': assert first[3]['cwd'] is None
    evs = events(logged, answer['run_id'])
    agent_events = [e for e in evs if e['type']=='agent_session']
    assert [e['block_id'] for e in agent_events]==['a', 'b']
    assert all(e['data']==dict(module=module, agent_id=aid, session_id='session-1', path='') for e in agent_events)
    assert not {'text_delta', 'tool_use', 'tool_result', 'agent_text'} & {e['type'] for e in evs}
    outputs = logged.get(f"/api/workflow/runs/{answer['run_id']}/outputs").json()
    fields = outputs[0]['fields']
    assert set(fields)==({'result', 'session_id', 'structured', 'cost_usd'} if module=='agents' else {'result', 'session_id'})
    schemas = {p['id']: p for p in logged.get('/api/workflow/plugins').json()['plugins']}
    assert schemas['builtin.'+card]['uses_agent_slot']
    if card!='temp_task':
        assert schemas['builtin.'+card]['inputs'][0]['type']==('agent' if module=='agents' else 'more_agent')


def test_temp_overrides_extra_and_cwd(logged, app, bridge, tmp_path):
    base = tmp_path/'workspace'
    logged.patch('/api/workflow/settings', json={'default_cwd': str(base), 'env': {'GLOBAL': 'yes', 'OVERRIDE': 'old'}})
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}
    params = dict(prompt='work', cwd='relative', model='haiku', effort='low', permission_mode='plan',
                  append_system_prompt='instructions', output_schema=schema, allowed_tools='Read, Bash\nEdit',
                  disallowed_tools='Write', add_dirs='/tmp/a\n/tmp/b', max_turns=4, max_budget_usd=.5,
                  env={'LOCAL': 'yes', 'OVERRIDE': 'new'})
    wid = make_wf(logged, [{'id': 'a', 'type': 'builtin.temp_task', 'params': params}])
    answer = run(logged, wid)
    assert answer['status']=='success'
    kw = bridge.calls[0][3]
    assert kw['cwd']==str(base/'relative') and (base/'relative').is_dir()
    assert kw['overrides']==dict(model='haiku', effort='low', permission_mode='plan')
    assert kw['extra']==dict(append_system_prompt='instructions', output_schema=schema,
                             allowed_tools=['Read', 'Bash', 'Edit'], disallowed_tools=['Write'],
                             add_dirs=['/tmp/a', '/tmp/b'], max_turns=4, max_budget_usd=.5,
                             env={'GLOBAL': 'yes', 'LOCAL': 'yes', 'OVERRIDE': 'new'})
    wid = make_wf(logged, [{'id': 'a', 'type': 'builtin.agent_task', 'params': dict(
        agent='claude', prompt='named', model='sonnet', effort='high', append_system_prompt='append', output_schema=schema)}])
    assert run(logged, wid)['status']=='success'
    kw = bridge.calls[-1][3]
    assert 'cwd' not in kw and kw['overrides']=={'model': 'sonnet', 'effort': 'high'}
    assert kw['extra']['output_schema']==schema and kw['extra']['append_system_prompt']=='append'


@pytest.mark.parametrize('card', ['temp_task', 'acp_task'])
def test_bridge_error_fails_step(logged, bridge, card):
    bridge.error = 'Agent turn failed'
    wid = make_wf(logged, [{'id': 'a', 'type': 'builtin.'+card, 'params': {'agent': 'remote', 'prompt': 'fail'}}])
    answer = run(logged, wid)
    assert answer['status']=='failed' and bridge.error in answer['error']
    assert any(e['type']=='step_failed' and bridge.error in e['data']['error'] for e in events(logged, answer['run_id']))


@pytest.mark.parametrize('card,module', [('temp_task', 'agents'), ('acp_task', 'acp')])
def test_cancel_stops_session_before_result(logged, app, bridge, monkeypatch, card, module):
    bridge.block = True
    manager = app.state.core.modules['workflow']
    feed = []
    monkeypatch.setattr(app.state.core, 'emit', feed.append)
    wid = make_wf(logged, [{'id': 'a', 'type': 'builtin.'+card, 'params': {'agent': 'remote', 'prompt': 'wait'}}])
    rid = logged.post(f'/api/workflow/workflows/{wid}/run', json={}).json()['run_id']
    logged.portal.call(until, lambda: bool(bridge.calls))
    logged.portal.call(manager.bus.flush_db)
    rows = logged.portal.call(manager.db.fetchall, 'SELECT type,data FROM run_events WHERE run_id=?', (rid,))
    assert any(e['type']=='agent_session' and 'session-1' in e['data'] for e in rows)
    assert logged.post(f'/api/workflow/runs/{rid}/cancel').status_code==200
    assert logged.portal.call(manager.wait, rid, 3)
    assert bridge.stops==[(module, 'session-1')]
    assert logged.get(f'/api/workflow/runs/{rid}').json()['status']=='cancelled'
    assert [e['status'] for e in feed if e['type']=='run_state']==['queued', 'running', 'cancelled']


def test_limit_raw_resize_console_and_shutdown(logged, app, bridge, monkeypatch):
    core = app.state.core
    manager = core.modules['workflow']
    bridge.block = True
    monkeypatch.setattr(core.modules['agents'], 'sessions', lambda: list(bridge.sessions.values()))
    wid = make_wf(logged, [{'id': 'a', 'type': 'builtin.temp_task', 'params': {'prompt': 'wait'}}])
    rids = [logged.post(f'/api/workflow/workflows/{wid}/run', json={}).json()['run_id'] for _ in range(2)]
    logged.portal.call(until, lambda: bool(bridge.calls))
    assert len(bridge.calls)==1 and manager.limiter.active==1
    console = logged.get('/api/workflow/console').json()
    assert {r['id'] for r in console['runs']}==set(rids)
    assert console['sessions']==[dict(module='agents', agent_id='_temp', session_id='session-1',
        title='t: Temporary task', state='running', parent={'module': 'workflow', 'run_id': rids[0], 'block_id': 'a'})]
    raw = logged.get('/api/config/raw?file=workflow').json()['content']
    assert logged.put('/api/config/raw?file=workflow', json={'content': raw.replace('agent_concurrency = 1', 'agent_concurrency = 2')}).status_code==200
    logged.portal.call(until, lambda: len(bridge.calls)==2)
    assert manager.limiter.active==2
    logged.portal.call(manager.shutdown)
    assert set(bridge.stops)=={('agents', 'session-1'), ('agents', 'session-2')}
    assert all(logged.get(f'/api/workflow/runs/{rid}').json()['status']=='cancelled' for rid in rids)
    assert logged.get('/api/workflow/console').json()=={'runs': [], 'sessions': []}


async def test_bridge_callbacks_precede_turn(app, monkeypatch):
    bridge, acp = app.state.core.bridge, app.state.core.modules['more_agents']
    seen = []
    async def run_turn(sid, prompt):
        assert seen==[sid]
        return {'session_id': sid}
    monkeypatch.setattr(app.state.manager, 'run_turn', run_turn)
    result = await bridge.run_claude('_temp', 'hi', on_session=seen.append)
    assert result['session_id']==seen[0]
    seen.clear()
    monkeypatch.setattr(acp, 'agent', lambda aid: None)
    future = asyncio.get_running_loop().create_future()
    def runtime(sid):
        def enqueue(prompt):
            assert seen==[sid]
            future.set_result({'session_id': sid})
            return future
        return SimpleNamespace(enqueue=enqueue)
    monkeypatch.setattr(acp, 'runtime', runtime)
    result = await bridge.run_more('remote', 'hi', on_session=seen.append)
    assert result['session_id']==seen[0]


async def test_recovery_early_cancel_and_retention(app, monkeypatch):
    core = app.state.core
    manager = core.modules['workflow']
    feed = []
    monkeypatch.setattr(core, 'emit', feed.append)
    await manager.db.open()
    from server.workflow.db import dumps, now
    for status in ('queued', 'running', 'waiting_input'):
        await manager.db.execute('INSERT INTO runs(id,workflow_id,snapshot,status,created_at) VALUES(?,?,?,?,?)',
                                 (status, 'wf', dumps({}), status, now()))
    await manager.db.close()
    await core.start()
    try:
        assert [e['status'] for e in feed if e['type']=='run_state']==['failed']*3
        for status in ('queued', 'running', 'waiting_input'):
            row = await manager.db.fetchone('SELECT status,error,finished_at FROM runs WHERE id=?', (status,))
            assert row['status']=='failed' and 'restarted' in row['error'] and row['finished_at']
            replay = [e async for e in manager.bus.subscribe(status)]
            assert replay[-1]['type']=='run_finished'
        rid = await manager.start_run({'blocks': []}, workflow_id='wf', workflow_name='early', inputs={})
        assert manager.cancel(rid) and await manager.wait(rid, 3)
        assert (await manager.db.fetchone('SELECT status FROM runs WHERE id=?', (rid,)))['status']=='cancelled'
        manager.config.data.server.run_retention = 1
        await manager.prune()
        assert len(await manager.db.fetchall('SELECT * FROM runs'))==1
        assert not await manager.db.fetchall('SELECT * FROM run_events WHERE run_id NOT IN (SELECT id FROM runs)')
        manager.config.data.server.run_retention = 0
        await manager.start_run({'blocks': []}, workflow_id='wf', workflow_name='kept', inputs={})
        await manager.shutdown()
        assert len(await manager.db.fetchall('SELECT * FROM runs'))==2
    finally:
        await core.stop()
