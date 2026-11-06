import asyncio
from types import SimpleNamespace
import pytest


def test_running_requires_auth(client):
    assert client.get('/api/running').status_code==401


def test_running_empty(logged):
    assert logged.get('/api/running').json()==[]


@pytest.mark.parametrize('kind',['acp','codex'])
def test_running_mounted_more_agents(logged,app,tmp_path,monkeypatch,kind):
    from server.more_agents.config import AcpAgent, CodexAgent
    from unittest.mock import Mock

    more=app.state.core.modules['more_agents']
    agent=(AcpAgent(id='remote',name='Remote',host='localhost',port=1,avatar='crab:blue') if kind=='acp'
           else CodexAgent(id='remote',name='Remote',avatar='crab:blue'))
    more.config.data.agents.append(agent)
    expected=[]
    for number,(state,permissions,questions) in enumerate([
            ('running',0,0),('interrupting',0,0),('idle',1,1),('offline',0,1),('idle',0,0),('offline',0,0)]):
        session=more.store.create(agent.id,f'Session {number}',kind=kind,cwd=str(tmp_path))
        session.update(updated_at=f'2026-11-06T00:00:{number:02d}+00:00',preview=f'Preview {number}',unread=True)
        runtime=more.runtime(session['id'])
        runtime.state=state
        runtime.permissions={str(i):object() for i in range(permissions)}
        runtime.questions={str(i):object() for i in range(questions)}
        if number<4:
            expected.append(dict(module='more_agents',session_id=session['id'],agent_id=agent.id,
                                 agent_name=agent.name,avatar=agent.avatar,title=session['title'],state=state,
                                 pending=permissions+questions,unread=True,updated_at=session['updated_at'],
                                 preview=session['preview'],cwd=str(tmp_path)))
    claude=app.state.index.create('claude','Claude')
    claude['updated_at']='2026-11-05T00:00:00+00:00'
    app.state.manager.get_or_create(claude['id']).state='running'
    provider=Mock(wraps=more.running)
    monkeypatch.setattr(more,'running',provider)
    rows=logged.get('/api/running').json()
    provider.assert_called_once_with()
    assert rows[:-1]==list(reversed(expected))
    assert rows[-1]['module']=='agents'
    assert set(rows[0])==set(rows[-1])


def test_running_across_modules(logged,app,tmp_path):
    manager=app.state.manager
    index=app.state.index
    agent=logged.get('/api/agents/claude').json()
    temp=logged.patch('/api/agents/_temp',json={'name':'Scratch','avatar':'crab:blue'}).json()
    selected=[]
    for number,(state,pending) in enumerate([('running',0),('interrupting',0),('idle',2),('offline',1),
                                           ('idle',0),('offline',0),('starting',0),('queued',0)]):
        session=index.create('claude',f'{state} {pending}',preview=f'preview {number}',unread=bool(number%2))
        session['updated_at']=f'2026-11-06T00:00:{number:02d}+00:00'
        runtime=manager.get_or_create(session['id'])
        runtime.state=state
        runtime.permissions.pending={str(i):object() for i in range(pending)}
        if number<4: selected.append(session)
    session=index.create('_temp','Temporary',cwd=str(tmp_path),preview='temp preview')
    session['updated_at']='2026-11-06T00:00:20+00:00'
    manager.get_or_create(session['id']).state='running'
    index.create('claude','No runtime')
    calls=[]
    remote={'module':'more_agents','session_id':'remote','agent_id':'remote-agent','agent_name':'Remote',
            'avatar':'file','title':'Remote session','state':'running','pending':0,'unread':False,
            'updated_at':'2026-11-06T00:00:10+00:00','preview':'remote preview','cwd':''}
    def running():
        calls.append(True)
        return [remote]
    app.state.core.modules['more_agents']=SimpleNamespace(running=running)
    app.state.core.modules['no_provider']=SimpleNamespace(running=[])
    rows=logged.get('/api/running').json()
    assert len(calls)==1
    assert [r['session_id'] for r in rows]==[session['id'],'remote',*(s['id'] for s in reversed(selected))]
    assert rows[0]=={'module':'agents','session_id':session['id'],'agent_id':'_temp','agent_name':temp['name'],
                     'avatar':temp['avatar'],'title':'Temporary','state':'running','pending':0,'unread':False,
                     'updated_at':session['updated_at'],'preview':'temp preview','cwd':str(tmp_path)}
    assert rows[1]==remote
    row=rows[-1]
    assert row=={'module':'agents','session_id':selected[0]['id'],'agent_id':'claude','agent_name':agent['name'],
                 'avatar':agent['avatar'],'title':'running 0','state':'running','pending':0,'unread':False,
                 'updated_at':selected[0]['updated_at'],'preview':'preview 0','cwd':agent['cwd']}
    assert rows[2]['pending']==1 and rows[2]['unread'] is True
    assert rows[3]['pending']==2
    session.pop('cwd')
    assert logged.get('/api/running').json()[0]['cwd']==''


@pytest.mark.asyncio
async def test_claude_session_state_has_module(app):
    manager=app.state.manager
    session=app.state.index.create('claude','Title',preview='Preview')
    runtime=manager.get_or_create(session['id'])
    runtime.state='running'
    queue=asyncio.Queue()
    manager.global_subscribers.add(queue)
    manager.session_state(runtime)
    event=queue.get_nowait()
    assert event=={'type':'session_state','module':'agents','session_id':session['id'],'agent_id':'claude',
                   'state':'running','pending':0,'unread':False,'title':'Title',
                   'updated_at':session['updated_at'],'preview':'Preview'}
    await asyncio.sleep(0)
