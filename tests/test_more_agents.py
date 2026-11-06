import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from server.auth import COOKIE
from server.bridge import AgentBridge
from server.more_agents.config import AcpAgent, CodexAgent, MoreAgentsConfig
from server.more_agents.manager import MoreAgentsManager
from server.more_agents.store import MoreAgentsStore
from test_more_agents_acp import make_app, until


@pytest.fixture
async def codex(tmp_path, monkeypatch):
    real_exec = asyncio.create_subprocess_exec
    script = Path(__file__).parent/'fixtures'/'fake_codex_app_server.py'
    launches = []
    async def fixture_exec(*argv, **kwargs):
        # Verify the production argv; Python cannot accept Codex's required app-server prefix.
        assert argv[:6] == (sys.executable, 'app-server', '--listen', 'stdio://', '-c', 'analytics.enabled=false')
        assert argv[6:] == (str(script),)
        assert kwargs['limit'] == 64*1024*1024
        process = await real_exec(sys.executable, str(script), **kwargs)
        launches.append(process)
        return process
    monkeypatch.setattr('server.more_agents.kinds.codex.process.asyncio.create_subprocess_exec', fixture_exec)
    app, core, events = make_app(tmp_path)
    manager = core.modules['more_agents']
    logfile = tmp_path/'rpc.jsonl'
    await manager.create_agent(dict(kind='codex',id='native',name='Native',command=sys.executable,args=[str(script)],
                                    env={'FAKE_LOG':str(logfile)},cwd=str(tmp_path),as_subagent=True))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver',cookies={COOKIE:core.auth.token()}) as client:
        yield SimpleNamespace(manager=manager, core=core, http=client, launches=launches, log=lambda: [json.loads(l) for l in logfile.read_text().splitlines()], cwd=str(tmp_path))
    await manager.close()
    assert all(p.returncode is not None for p in launches)


def test_config_discriminates_kinds():
    config = MoreAgentsConfig(agents=[dict(kind='acp',id='a',name='A',host='localhost',port=1),dict(kind='codex',id='c',name='C')])
    assert isinstance(config.agents[0], AcpAgent) and isinstance(config.agents[1], CodexAgent)
    with pytest.raises(ValidationError): MoreAgentsConfig(agents=[dict(id='a',name='A',host='localhost',port=1)])


async def test_preload_settings_stream_and_usage(codex):
    c, m = codex, codex.manager
    sid = (await c.http.post('/api/more-agents/agents/native/sessions',json={})).json()['id']
    await m.prepare(sid)
    assert m.view(sid)['state']=='idle' and not m.items(sid)
    assert len(c.launches)==1
    assert not any(r.get('method')=='turn/start' for r in c.log())
    assert m.view(sid)['cwd']==c.cwd and m.view(sid)['kind']=='codex'
    assert m.agents()[0]['capabilities']==dict(images=True,steer=True,modes=True,local_cwd=True)
    assert m.agents()[0]['recent'][0]['id']==sid
    await m.set_option(sid,'effort','high')
    await m.set_option(sid,'model','other')
    assert m.view(sid)['config_options'][1]['currentValue']=='medium'
    await m.set_mode(sid,'auto')
    result = await m.run_turn('native','trace',session_id=sid)
    assert result == dict(session_id=sid,text='Working.ok',stop_reason='completed',is_error=False,error=None)
    items = m.items(sid)
    assert len([i for i in items if i['kind']=='user'])==1
    text = [i for i in items if i['kind']=='text']
    assert [(i['text'],i['phase']) for i in text]==[('Working.','commentary'),('ok','final')]
    assert next(i for i in items if i['kind']=='thinking')['text']=='Think\nNext'
    command = next(i for i in items if i.get('tool_kind')=='execute')
    assert command['output']=='ok\n' and command['exit_code']==0 and not command['streaming']
    patch = next(i for i in items if i.get('tool_kind')=='edit')
    assert patch['changes']==[dict(path='/workspace/a',kind='update',move_path=None,diff='@@\n-old\n+latest')]
    tool = next(i for i in items if i.get('tool_kind')=='mcp')
    assert tool['result']['content']=='doc\nmore' and tool['raw']['content']
    assert next(i for i in items if i.get('tool_kind')=='fetch')['url']=='https://example.com'
    assert next(i for i in items if i.get('tool_kind')=='other')['input']['payload']=='kept'
    plans = [i for i in items if i['kind']=='plan']
    assert len(plans)==1 and plans[0]['entries']==[dict(content='Implement',status='completed')]
    assert plans[0]['explanation']=='Done'
    assert items[-1]['usage']==dict(input=10,cached_input=2,output=4,reasoning=1)
    assert any(e['type']=='delta' and e['field']=='output' for e in m.runtime(sid).ring)
    assert m.view(sid)['context']==dict(used=14,max=1000)
    await m.run_turn('native','again',session_id=sid)
    assert m.items(sid)[-1]['usage']==items[-1]['usage']
    assert m.view(sid)['usage']['input']==20
    starts=[r['params'] for r in c.log() if r.get('method')=='turn/start']
    assert all(p['model']=='other' and p['effort']=='medium' for p in starts)
    assert starts[0]['sandboxPolicy']==dict(type='workspaceWrite',writableRoots=[c.cwd])
    assert starts[0]['approvalPolicy']=='on-request'
    assert m.store.load_items(sid)==m.items(sid)


async def test_steer_race_interrupt_and_queue_results(codex):
    m=codex.manager
    sid=m.start_turn('native','hold',cwd=codex.cwd)
    await until(lambda: m.runtime(sid).turn is not None)
    first=asyncio.create_task(m.wait_turn(sid))
    await asyncio.sleep(0)
    await m.send(sid,'steer')
    answer=await m.wait_turn(sid)
    assert answer==await first and m.view(sid)['turns']==1
    assert [i for i in m.items(sid) if i['kind']=='user'][-1]['steered']
    m.start_turn('native','race',session_id=sid)
    await until(lambda: m.runtime(sid).turn is not None)
    await m.send(sid,'race followup')
    assert (await m.wait_turn(sid))['text']=='Working.ok'
    assert m.view(sid)['turns']==3
    assert not [i for i in m.items(sid) if i['kind']=='user'][-1].get('steered')
    m.start_turn('native','hold',session_id=sid)
    await until(lambda: m.runtime(sid).turn is not None)
    assert m.running()[0]['session_id']==sid
    await m.stop(sid)
    assert (await m.wait_turn(sid))['stop_reason']=='interrupted'
    assert m.running()==[]


@pytest.mark.parametrize('prompt,reply_value,expected',[
    ('approve','acceptForSession',{'decision':'acceptForSession'}),
    ('file-approve',None,{'decision':'cancel'}),
    ('profile','accept',{'permissions':{'network':{'enabled':True}},'scope':'turn'}),
    ('profile',None,{'permissions':{},'scope':'turn'}),
    ('question',{'q':['One']},{'answers':{'q':{'answers':['One']}}}),
    ('question',None,{'answers':{'q':{'answers':[]}}}),
])
async def test_interactive_requests(codex,prompt,reply_value,expected):
    m=codex.manager
    sid=m.start_turn('native',prompt,cwd=codex.cwd)
    r=m.runtime(sid)
    pending=r.questions if prompt=='question' else r.permissions
    await until(lambda: pending)
    assert m.running()[0]['pending']==1
    pid=next(iter(pending))
    if prompt=='question':
        q=r.snapshot()['questions'][0]['questions'][0]
        assert q['is_other'] is True and q['is_secret'] is False
        r.reply_question(pid,reply_value)
    else:
        assert r.snapshot()['permissions'][0]['tool_call']['tool_kind'] in ('execute','edit','other')
        r.reply_permission(pid,reply_value)
    assert (await m.wait_turn(sid))['stop_reason']=='completed'
    assert next(v for v in reversed(codex.log()) if str(v.get('id','')).startswith('approval-'))['result']==expected
    assert not pending


async def test_unsupported_request_failure_exit_and_shared_process(codex):
    c,m=codex,codex.manager
    sid=m.start_turn('native','unsupported',cwd=c.cwd)
    assert (await m.wait_turn(sid))['stop_reason']=='completed'
    assert any(i['kind']=='notice' and i['level']=='warn' for i in m.items(sid))
    reply=next(v for v in c.log() if str(v.get('id','')).startswith('approval-'))
    assert reply['error']['code']==-32601
    assert (await m.run_turn('native','fail',session_id=sid))['is_error']
    second=m.start_turn('native','question',cwd=c.cwd)
    await until(lambda: m.runtime(second).questions)
    assert len(c.launches)==1
    result=await m.run_turn('native','exit',session_id=sid)
    assert result['stop_reason']=='disconnected'
    assert (await m.wait_turn(second))['stop_reason']=='disconnected'
    await until(lambda: all(s['state']=='offline' for s in m.sessions()))
    assert not m.runtime(second).questions
    assert any(i['kind']=='notice' for i in m.items(second))


async def test_models_cache_resume_and_missing_thread(codex):
    c,m=codex,codex.manager
    assert (await c.http.get('/api/more-agents/agents/native/models')).json()[0]['model']=='fake'
    assert c.launches[0].returncode==0
    assert m.cached_models('native') and len(c.launches)==1
    assert (await m.models('native'))==m.cached_models('native') and len(c.launches)==1
    sid=m.create_session('native')['id'];await m.prepare(sid)
    remote=m.view(sid)['remote_id']
    second=m.create_session('native')['id'];await m.prepare(second)
    await m.sleep(sid)
    assert c.launches[-1].returncode is None
    await m.sleep(second)
    assert c.launches[-1].returncode==0
    assert sum(r.get('method')=='thread/unsubscribe' for r in c.log())==2
    await m.close()
    restored=MoreAgentsManager(c.core,m.config,MoreAgentsStore(c.core.paths.root))
    try:
        assert restored.cached_models('native')==m.cached_models('native')
        await restored.prepare(sid)
        assert restored.view(sid)['remote_id']==remote
        params=[r['params'] for r in c.log() if r.get('method')=='thread/resume'][-1]
        assert params['threadId']==remote and params['excludeTurns'] is True and params['cwd']==c.cwd
        await restored.sleep(sid)
        restored.store.update(sid,remote_id='missing')
        await restored.prepare(sid)
        assert restored.view(sid)['remote_id']!='missing'
        assert any('Remote session was gone' in i.get('text','') for i in restored.items(sid))
    finally: await restored.close()


async def test_bridge_cwd_options_attachments_and_validation(codex):
    c,m=codex,codex.manager
    bridge=AgentBridge(c.core,None)
    with pytest.raises(ValueError,match='cwd'): await bridge.run_more('native','hello')
    with pytest.raises(HTTPException,match='existing directory'): m.create_session('native',cwd=c.cwd+'/missing')
    assert (await c.http.patch('/api/more-agents/agents/native',json={'kind':'acp'})).status_code==400
    seen=[]
    result=await bridge.run_more('native','hello',cwd=c.cwd,model='other',effort='medium',on_session=seen.append)
    sid=result['session_id'];assert seen==[sid]
    params=[r['params'] for r in c.log() if r.get('method')=='turn/start'][-1]
    assert params['model']=='other' and params['effort']=='medium'
    attachments=[dict(is_image=True,path=c.cwd+'/img.png'),dict(is_image=False,path=c.cwd+'/a.txt')]
    await m.runtime(sid).enqueue('files',attachments)
    params=[r['params'] for r in c.log() if r.get('method')=='turn/start'][-1]
    assert params['input']==[dict(type='text',text='files\nAttached file: '+c.cwd+'/a.txt',text_elements=[]),dict(type='localImage',path=c.cwd+'/img.png')]
    await bridge.close()


async def test_socket_attach_preloads_questions_and_detach_keeps_turn(codex):
    from starlette.websockets import WebSocketDisconnect
    from server.more_agents.routes import session_socket
    c,m=codex,codex.manager
    sid=m.create_session('native')['id'];await m.prepare(sid);await m.sleep(sid)
    class Socket:
        cookies={COOKIE:c.core.auth.token()}
        headers={'origin':'http://testserver','host':'testserver'}
        def __init__(self): self.incoming=asyncio.Queue();self.outgoing=[]
        async def accept(self): pass
        async def send_json(self,event): self.outgoing.append(event)
        async def receive_json(self):
            value=await self.incoming.get()
            if value is None: raise WebSocketDisconnect()
            return value
        async def close(self,code): pass
    ws=Socket();ws.incoming.put_nowait(dict(type='resume',seq=None))
    task=asyncio.create_task(session_socket(ws,sid,c.core,m))
    try:
        await until(lambda: m.view(sid)['state']=='idle' and ws.outgoing)
        assert ws.outgoing[0]['type']=='snapshot' and ws.outgoing[0]['questions']==[]
        assert len(c.launches)==2
        ws.incoming.put_nowait(dict(type='send',text='question'))
        await until(lambda: any(e['type']=='question' for e in ws.outgoing))
        pid=next(e['request']['id'] for e in ws.outgoing if e['type']=='question')
        ws.incoming.put_nowait(dict(type='question_reply',id=pid,answers={'q':['One']}))
        await until(lambda: m.view(sid)['turns']==1)
        assert any(e['type']=='question_resolved' for e in ws.outgoing)
        ws.incoming.put_nowait(dict(type='send',text='hold'))
        await until(lambda: m.runtime(sid).turn is not None)
        ws.incoming.put_nowait(None);await task
        assert m.view(sid)['state']=='running'
        await m.stop(sid);assert (await m.wait_turn(sid))['stop_reason']=='interrupted'
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)


async def test_native_resolved_cancels_without_stale_reply(codex):
    m=codex.manager
    sid=m.start_turn('native','resolved',cwd=codex.cwd)
    r=m.runtime(sid)
    await until(lambda: r.permissions)
    await r.adapter.process.request('test/resolve',dict(threadId=m.view(sid)['remote_id']))
    await until(lambda: not r.permissions)
    assert (await m.wait_turn(sid))['stop_reason']=='completed'
    assert not any(str(v.get('id','')).startswith('approval-') for v in codex.log())


async def test_failed_preload_stays_offline_with_notice(codex,monkeypatch):
    async def failed_exec(*args,**kwargs): raise FileNotFoundError('missing Codex executable')
    monkeypatch.setattr('server.more_agents.kinds.codex.process.asyncio.create_subprocess_exec',failed_exec)
    m=codex.manager
    sid=m.create_session('native')['id']
    await m.prepare(sid)
    assert m.view(sid)['state']=='offline'
    assert any(i['kind']=='notice' and 'missing Codex executable' in i['text'] for i in m.items(sid))
