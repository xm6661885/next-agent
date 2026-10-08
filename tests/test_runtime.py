import asyncio
import time
import pytest
from claude_agent_sdk import StreamEvent, AssistantMessage, UserMessage, ResultMessage, TextBlock, ToolUseBlock, ToolResultBlock
from conftest import FakeClaudeSDKClient
from server.items import item

async def until(predicate,timeout=2):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate(): return
        await asyncio.sleep(.005)
    raise AssertionError('condition not met')

def result(sid,cost,turns=1):
    return ResultMessage(subtype='success',duration_ms=5,duration_api_ms=4,is_error=False,
                         num_turns=turns,session_id=sid,total_cost_usd=cost)

@pytest.mark.asyncio
async def test_send_steer_stream_result_cost(app):
    manager=app.state.manager; sid=app.state.index.create('claude')['id']; r=manager.get_or_create(sid)
    r.emit(r.items.pending_user('first',[], 'c1'))
    r.submit(('send',{'content':[{'type':'text','text':'first'}]}))
    await until(lambda:r.state=='running' and len(FakeClaudeSDKClient.instances)==1)
    client=FakeClaudeSDKClient.instances[-1]
    client.push(StreamEvent(uuid='stream',session_id=sid,event={'type':'message_start','message':{'id':'msg1'}}))
    client.push(StreamEvent(uuid='stream',session_id=sid,event={'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}}))
    client.push(StreamEvent(uuid='stream',session_id=sid,event={'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'Hello'}}))
    client.push(StreamEvent(uuid='stream',session_id=sid,event={'type':'content_block_stop','index':0}))
    client.push(AssistantMessage(content=[TextBlock('Hello')],model='opus',message_id='msg1'))
    r.emit(r.items.pending_user('steer',[],'c2'))
    r.submit(('send',{'content':[{'type':'text','text':'steer'}]}))
    await until(lambda:len(client.queries)==2)
    client.push(result(sid,.5))
    await until(lambda:r.state=='idle' and any(e.get('item',{}).get('kind')=='result' for e in r.ring))
    events=list(r.ring)
    assert next(i for i,e in enumerate(events) if e['type']=='delta') < next(i for i,e in enumerate(events) if e.get('item',{}).get('kind')=='result')
    assert [x for x in r.items.items if x['kind']=='user'][1]['uuid']=='echo-2'
    assert r.session['total_cost_usd']==.5
    assert r.session['context']=={'used':100,'max':1000,'percent':10}
    r.submit(('send',{'content':[{'type':'text','text':'again'}]}))
    await until(lambda:len(client.queries)==3)
    client.push(result(sid,.8))
    await until(lambda:r.session['turns']==2)
    assert round(r.session['total_cost_usd'],2)==.8
    await manager.stop(sid)

@pytest.mark.asyncio
async def test_interrupt_reaper_reader_death(app):
    manager=app.state.manager; sid=app.state.index.create('claude')['id']; r=manager.get_or_create(sid)
    r.submit(('send',{'content':[{'type':'text','text':'go'}]}))
    await until(lambda:r.state=='running')
    c=FakeClaudeSDKClient.instances[-1]
    r.submit(('interrupt',))
    await until(lambda:c.interrupted)
    assert r.state=='interrupting'
    c.push(result(sid,0))
    await until(lambda:r.state=='idle')
    r.last_activity=time.monotonic()-2
    manager.config.config.server.idle_timeout_min=.0001
    task=asyncio.create_task(manager.reaper(interval=.01))
    await until(lambda:r.state=='offline')
    task.cancel()
    r.submit(('send',{'content':[{'type':'text','text':'next'}]}))
    await until(lambda:r.state=='running')
    FakeClaudeSDKClient.instances[-1].push(RuntimeError('died'))
    await until(lambda:r.state=='offline')
    assert any(e.get('item',{}).get('kind')=='notice' and 'stream failed' in e['item']['text'] for e in r.ring)
    await manager.stop(sid)

@pytest.mark.asyncio
async def test_concurrency_cap(app):
    manager=app.state.manager; manager.semaphore=asyncio.Semaphore(1)
    s1=app.state.index.create('claude')['id']; s2=app.state.index.create('claude')['id']
    r1=manager.get_or_create(s1); r2=manager.get_or_create(s2)
    r1.submit(('send',{'content':[{'type':'text','text':'one'}]}))
    await until(lambda:r1.state=='running')
    r2.submit(('send',{'content':[{'type':'text','text':'two'}]}))
    await until(lambda:r2.state=='queued')
    assert len(FakeClaudeSDKClient.instances)==1
    await manager.stop(s1)
    await until(lambda:r2.state=='running')
    assert len(FakeClaudeSDKClient.instances)==2
    await manager.stop(s2)

@pytest.mark.asyncio
async def test_tool_result_and_resize(app):
    from server.runtime import ResizableSemaphore
    from claude_agent_sdk import AssistantMessage, ToolUseBlock, ToolResultBlock
    gate=ResizableSemaphore(1)
    await gate.acquire()
    waiter=asyncio.create_task(gate.acquire())
    await asyncio.sleep(0)
    assert not waiter.done()
    gate.resize(2)
    await until(waiter.done)
    gate.release(); gate.release()
    sid=app.state.index.create('claude')['id']; r=app.state.manager.get_or_create(sid)
    r.submit(('send',{'content':[{'type':'text','text':'read'}]}))
    await until(lambda:r.state=='running')
    client=FakeClaudeSDKClient.instances[-1]
    client.push(AssistantMessage(content=[ToolUseBlock(id='tool1',name='Read',input={'file_path':'a'})],model='opus'))
    client.push(UserMessage(content=[ToolResultBlock(tool_use_id='tool1',content='contents')]))
    client.push(result(sid,.1))
    await until(lambda:r.state=='idle' and any(x['kind']=='tool' for x in r.items.items))
    assert next(x for x in r.items.items if x['kind']=='tool')['result']['content']=='contents'
    await app.state.manager.stop(sid)

@pytest.mark.asyncio
async def test_connect_failure_fails_pending_send(app,monkeypatch):
    import server.runtime
    class Failing(FakeClaudeSDKClient):
        async def connect(self): raise RuntimeError('cannot start')
    monkeypatch.setattr(server.runtime,'ClaudeSDKClient',Failing)
    sid=app.state.index.create('claude')['id']; r=app.state.manager.get_or_create(sid)
    r.emit(r.items.pending_user('hello',[],'c'))
    r.submit(('send',{'content':[{'type':'text','text':'hello'}]}))
    await until(lambda:any(e.get('item',{}).get('kind')=='notice' for e in r.ring))
    assert r.state=='offline'
    assert not next(x for x in r.items.items if x['kind']=='user')['pending']
    assert any(e.get('item',{}).get('kind')=='notice' and 'cannot start' in e['item']['text'] for e in r.ring)
    await app.state.manager.stop(sid)

@pytest.mark.asyncio
async def test_effort_restarts_idle_client(app):
    sid=app.state.index.create('claude')['id']; r=app.state.manager.get_or_create(sid)
    r.submit(('send',{'content':[{'type':'text','text':'go'}]}))
    await until(lambda:r.state=='running')
    first=FakeClaudeSDKClient.instances[-1]
    first.push(result(sid,.1))
    await until(lambda:r.state=='idle')
    r.submit(('set_effort','high'))
    await until(lambda:len(FakeClaudeSDKClient.instances)==2 and r.state=='idle')
    second=FakeClaudeSDKClient.instances[-1]
    assert not first.connected and second.connected
    assert second.options.effort=='high' and second.options.resume==sid
    await app.state.manager.stop(sid)

@pytest.mark.asyncio
async def test_edit_rewinds_history_and_echo(app,monkeypatch):
    import server.runtime
    sid=app.state.index.create('claude',sdk_session_id='sdk-old')['id']
    r=app.state.manager.get_or_create(sid)
    history=[item('user',text='one',attachments=[],uuid='u1',pending=False,client_id=None),
             item('text',text='answer',streaming=False),
             item('user',text='two',attachments=[],uuid='u2',pending=False,client_id=None),
             item('text',text='later',streaming=False)]
    monkeypatch.setattr(server.runtime,'load_items',lambda *a:history)
    monkeypatch.setattr(server.runtime,'transcript_parent',lambda *a:'parent-entry')
    r.submit(('send',{'content':[{'type':'text','text':'prior'}]}))
    await until(lambda:r.state=='running')
    FakeClaudeSDKClient.instances[-1].push(result('sdk-old',.1))
    await until(lambda:r.state=='idle')
    payload={'uuid':'u2','content':[{'type':'text','text':'edited'}],'text':'edited',
             'attachments':[],'client_id':'c','rewind_files':False}
    r.submit(('edit',payload))
    await until(lambda:r.state=='running' and len(FakeClaudeSDKClient.instances)==2)
    client=FakeClaudeSDKClient.instances[-1]
    assert client.options.resume=='sdk-old' and client.options.resume_session_at=='parent-entry'
    assert [e['type'] for e in r.ring if e['type']=='truncate']==['truncate']
    assert any(e.get('item',{}).get('kind')=='user' and e['item']['text']=='edited' for e in r.ring)
    assert len(client.queries)==1
    await until(lambda:next(x for x in r.items.items if x['kind']=='user')['uuid']=='echo-1')
    assert not next(x for x in r.items.items if x['kind']=='user')['pending']
    assert r.truncate_uuid is None
    assert [x.get('uuid') for x in await r.all_items() if x['kind']=='user']==['u1','echo-1']
    await app.state.manager.stop(sid)

@pytest.mark.asyncio
async def test_edit_first_message_fresh_and_rewind_files(app,monkeypatch):
    import server.runtime
    sid=app.state.index.create('claude',sdk_session_id='sdk-old',fork_of={'session_id':'other','at_uuid':'u1'})['id']
    r=app.state.manager.get_or_create(sid)
    history=[item('user',text='one',attachments=[],uuid='u1',pending=False,client_id=None)]
    monkeypatch.setattr(server.runtime,'load_items',lambda *a:history)
    monkeypatch.setattr(server.runtime,'transcript_parent',lambda *a:None)
    payload={'uuid':'u1','content':[{'type':'text','text':'edited'}],'text':'edited',
             'attachments':[],'client_id':'c','rewind_files':True}
    r.submit(('edit',payload))
    await until(lambda:r.state=='running' and len(FakeClaudeSDKClient.instances)==2)
    first,second=FakeClaudeSDKClient.instances
    assert first.rewound==['u1'] and not first.connected
    assert second.options.resume is None and second.options.session_id!=sid
    assert r.session['sdk_session_id'] is None and r.session['fork_of'] is None
    assert second.queries[0]['session_id']==second.options.session_id
    await until(lambda:r.truncate_uuid is None)
    await app.state.manager.stop(sid)

@pytest.mark.asyncio
async def test_edit_refused_while_running(app):
    sid=app.state.index.create('claude',sdk_session_id='sdk-old')['id']
    r=app.state.manager.get_or_create(sid)
    r.submit(('send',{'content':[{'type':'text','text':'go'}]}))
    await until(lambda:r.state=='running')
    client=FakeClaudeSDKClient.instances[-1]
    r.submit(('edit',{'uuid':'u','content':[{'type':'text','text':'edited'}],
                       'text':'edited','attachments':[],'client_id':'c','rewind_files':False}))
    await until(lambda:any(e['type']=='error' for e in r.ring))
    assert len(client.queries)==1
    await app.state.manager.stop(sid)
