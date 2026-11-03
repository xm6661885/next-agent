import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, UserMessage
from conftest import FakeClaudeSDKClient
from test_runtime import until, result
from server.items import item

def delivered(runtime, count=1):
    return len([x for x in runtime.items.items if x['kind']=='user' and not x['pending']])==count

@pytest.mark.parametrize('agent_id',['claude','_temp',None])
async def test_run_claude_metadata_options_and_result(app,tmp_path,agent_id):
    bridge=app.state.core.bridge
    parent={'run_id':'run','block_id':'block'}
    extra={'append_system_prompt':'Bridge instructions','env':{'BRIDGE':'yes'},'allowed_tools':['Read'],
           'output_schema':{'type':'object'}}
    task=asyncio.create_task(bridge.run_claude(agent_id,'Do the work',title='Bridge turn',origin='schedule',parent=parent,
                            cwd=str(tmp_path),overrides={'model':'haiku','effort':'low'},extra=extra))
    try:
        await until(lambda:bool(app.state.manager.runtimes))
        runtime=next(iter(app.state.manager.runtimes.values()))
        await until(lambda:delivered(runtime))
        client=FakeClaudeSDKClient.instances[-1]
        assert bridge.view('agents',runtime.sid)['title']=='Bridge turn'
        assert runtime.session['origin']=='schedule' and runtime.session['parent']==parent and runtime.session['extra']==extra
        assert client.options.model=='haiku' and client.options.effort=='low'
        assert client.options.system_prompt['append'].endswith('\n\nBridge instructions')
        assert client.options.env['BRIDGE']=='yes' and client.options.allowed_tools==['Read']
        assert client.options.output_format=={'type':'json_schema','schema':{'type':'object'}}
        if agent_id!='claude': assert client.options.cwd==str(tmp_path) and runtime.session['agent_id']=='_temp'
        client.push(AssistantMessage(content=[TextBlock('Child text')],model='haiku',parent_tool_use_id='child'))
        client.push(AssistantMessage(content=[TextBlock('First'),TextBlock('Second')],model='haiku'))
        msg=result(runtime.sid,.25)
        msg.structured_output={'answer':42}
        if agent_id=='claude': msg.result='Result text'
        client.push(msg)
        answer=await asyncio.wait_for(task,2)
        assert answer=={'session_id':runtime.sid,'text':'Result text' if agent_id=='claude' else 'First\n\nSecond',
                        'structured':{'answer':42},'cost_usd':.25,'is_error':False,'error':None}
        assert next(x for x in bridge.items('agents',runtime.sid) if x['kind']=='result')['structured']=={'answer':42}
        assert not runtime.subscribers
    finally:
        task.cancel()
        await app.state.manager.shutdown()

async def test_start_wait_current_and_next_send_stop_items(app,monkeypatch):
    bridge=app.state.core.bridge
    sid=bridge.start_claude(None,'First')
    assert bridge.view('agents',sid)['cwd']==str(Path.home())
    runtime=app.state.manager.get_or_create(sid)
    waiting=asyncio.create_task(bridge.wait_claude(sid))
    try:
        await until(lambda:delivered(runtime))
        client=FakeClaudeSDKClient.instances[-1]
        client.push(AssistantMessage(content=[TextBlock('Started text')],model='opus'))
        await until(lambda:any(x['kind']=='text' for x in runtime.items.items))
        current=asyncio.create_task(bridge.wait_claude(sid))
        await asyncio.sleep(0)
        client.push(result(sid,.1))
        assert (await asyncio.wait_for(waiting,2))['text']=='Started text'
        assert (await asyncio.wait_for(current,2))['text']=='Started text'
        history=[item('text',text='History',streaming=False)]
        runtime.history_base=history
        assert bridge.items('agents',sid)[0]['text']=='History'
        waiting=asyncio.create_task(bridge.wait_claude(sid))
        await asyncio.sleep(0)
        assert not waiting.done()
        await bridge.send('agents',sid,'Next')
        await until(lambda:delivered(runtime,2))
        await bridge.stop('agents',sid)
        await until(lambda:client.interrupted)
        msg=result(sid,.2)
        msg.result='Next result'
        client.push(msg)
        answer=await asyncio.wait_for(waiting,2)
        assert answer['text']=='Next result' and answer['cost_usd']==.1
    finally:
        waiting.cancel()
        await bridge.close()
        await app.state.manager.shutdown()

async def test_bridge_turns_wait_for_running_turn_and_each_other(app):
    bridge=app.state.core.bridge
    sid=app.state.index.create('claude')['id']
    runtime=app.state.manager.get_or_create(sid)
    await bridge.send('agents',sid,'UI turn')
    await until(lambda:delivered(runtime))
    first=asyncio.create_task(bridge.run_claude('claude','Bridge one',session_id=sid))
    second=asyncio.create_task(bridge.run_claude('claude','Bridge two',session_id=sid))
    try:
        client=FakeClaudeSDKClient.instances[-1]
        await asyncio.sleep(0)
        assert len(client.queries)==1
        client.push(AssistantMessage(content=[TextBlock('Old text')],model='opus'))
        client.push(result(sid,.1))
        await until(lambda:delivered(runtime,2))
        assert len(client.queries)==2 and not first.done() and not second.done()
        client.push(AssistantMessage(content=[TextBlock('One')],model='opus'))
        client.push(result(sid,.2))
        assert (await asyncio.wait_for(first,2))['text']=='One'
        await until(lambda:delivered(runtime,3))
        client.push(AssistantMessage(content=[TextBlock('Two')],model='opus'))
        client.push(result(sid,.3))
        assert (await asyncio.wait_for(second,2))['text']=='Two'
    finally:
        first.cancel(); second.cancel()
        await app.state.manager.shutdown()

async def test_bridge_collects_only_after_echo_and_survives_reconfigure(app,monkeypatch):
    async def query(self,prompt,session_id='default'):
        async for message in prompt: self.queries.append(message)
        self.push(AssistantMessage(content=[TextBlock('Before echo')],model='opus'))
        self.push(UserMessage(content='Prompt',uuid='echo'))
    monkeypatch.setattr(FakeClaudeSDKClient,'query',query)
    bridge=app.state.core.bridge
    task=asyncio.create_task(bridge.run_claude('claude','Prompt'))
    try:
        await until(lambda:bool(app.state.manager.runtimes))
        runtime=next(iter(app.state.manager.runtimes.values()))
        await until(lambda:delivered(runtime))
        runtime.restart_needed=True
        client=FakeClaudeSDKClient.instances[-1]
        client.push(AssistantMessage(content=[TextBlock('After echo')],model='opus'))
        client.push(result(runtime.sid,.1))
        answer=await asyncio.wait_for(task,2)
        assert answer['text']=='After echo' and not answer['is_error']
    finally:
        task.cancel()
        await app.state.manager.shutdown()

@pytest.mark.parametrize('failure',['connect','disconnect','result'])
async def test_bridge_errors(app,monkeypatch,failure):
    if failure=='connect':
        async def connect(self): raise RuntimeError('Cannot connect')
        monkeypatch.setattr(FakeClaudeSDKClient,'connect',connect)
    task=asyncio.create_task(app.state.core.bridge.run_claude('claude','Prompt'))
    try:
        if failure!='connect':
            await until(lambda:bool(app.state.manager.runtimes))
            runtime=next(iter(app.state.manager.runtimes.values()))
            await until(lambda:delivered(runtime))
            client=FakeClaudeSDKClient.instances[-1]
            if failure=='disconnect': client.push(RuntimeError('Disconnected'))
            else:
                msg=result(runtime.sid,.1)
                msg.is_error=True
                msg.errors=['Turn failed']
                client.push(msg)
        answer=await asyncio.wait_for(task,2)
        assert answer['is_error'] and {'connect':'Cannot connect','disconnect':'Disconnected','result':'Turn failed'}[failure] in answer['error']
    finally:
        task.cancel()
        await app.state.manager.shutdown()

async def test_bridge_bad_temp_directory(app,tmp_path):
    bridge=app.state.core.bridge
    with pytest.raises(ValueError,match='existing directory'):
        await bridge.run_claude('_temp','Prompt',cwd=str(tmp_path/'missing'))
    assert not app.state.index.sessions

async def test_bridge_result_without_assistant_text(app):
    bridge=app.state.core.bridge
    task=asyncio.create_task(bridge.run_claude('claude','Prompt'))
    try:
        await until(lambda:bool(app.state.manager.runtimes))
        runtime=next(iter(app.state.manager.runtimes.values()))
        await until(lambda:delivered(runtime))
        msg=result(runtime.sid,0)
        msg.structured_output={'answer':42}
        FakeClaudeSDKClient.instances[-1].push(msg)
        answer=await asyncio.wait_for(task,2)
        assert answer['text']=='' and answer['structured']=={'answer':42} and not answer['is_error']
    finally:
        task.cancel()
        await app.state.manager.shutdown()

async def test_bridge_existing_session_applies_new_launch_options(app):
    bridge=app.state.core.bridge
    sid=bridge.start_claude('claude','First')
    runtime=app.state.manager.get_or_create(sid)
    try:
        await until(lambda:delivered(runtime))
        first=FakeClaudeSDKClient.instances[-1]
        first.push(result(sid,.1))
        await until(lambda:not bridge.tasks)
        task=asyncio.create_task(bridge.run_claude('claude','Second',session_id=sid,
                                overrides={'model':'haiku'},extra={'env':{'SECOND':'yes'}}))
        await until(lambda:len(FakeClaudeSDKClient.instances)==2 and delivered(runtime))
        second=FakeClaudeSDKClient.instances[-1]
        assert not first.connected and second.options.model=='haiku' and second.options.env['SECOND']=='yes'
        assert second.options.resume==sid and not task.done()
        msg=result(sid,.2)
        msg.result='Second answer'
        second.push(msg)
        assert (await asyncio.wait_for(task,2))['text']=='Second answer'
    finally:
        await bridge.close()
        await app.state.manager.shutdown()

async def test_acp_delegation_and_unavailable(app):
    core=app.state.core
    bridge=core.bridge
    acp=SimpleNamespace(run_turn=AsyncMock(return_value={'text':'done'}),start_turn=Mock(return_value='acp-session'),
                        send=AsyncMock(),stop=AsyncMock(),view=Mock(return_value={'id':'acp-session'}),
                        items=Mock(return_value=[{'kind':'text'}]))
    core.modules['acp']=acp
    kwargs=dict(session_id='acp-session',title='Title',origin='subagent',parent={'task_id':'task'})
    assert await bridge.run_acp('agent','Prompt',**kwargs)=={'text':'done'}
    acp.run_turn.assert_awaited_once_with('agent','Prompt',**kwargs)
    assert bridge.start_acp('agent','Prompt',**kwargs)=='acp-session'
    acp.start_turn.assert_called_once_with('agent','Prompt',**kwargs)
    await bridge.send('acp','acp-session','More')
    await bridge.stop('acp','acp-session')
    acp.send.assert_awaited_once_with('acp-session','More')
    acp.stop.assert_awaited_once_with('acp-session')
    assert bridge.view('acp','acp-session')=={'id':'acp-session'}
    assert bridge.items('acp','acp-session')==[{'kind':'text'}]
    del core.modules['acp']
    for call in (lambda:bridge.start_acp('a','p'),lambda:bridge.view('acp','s'),lambda:bridge.items('acp','s')):
        with pytest.raises(RuntimeError,match='^ACP module unavailable$'): call()
    for call in (bridge.run_acp('a','p'),bridge.send('acp','s','p'),bridge.stop('acp','s')):
        with pytest.raises(RuntimeError,match='^ACP module unavailable$'): await call
