import asyncio
import json
import server.history
from server.options import build_options

def test_temp_session_lifecycle(logged,app,tmp_path):
    work=tmp_path/'proj'; work.mkdir(); (work/'sub').mkdir(); (work/'.hid').mkdir()
    assert logged.post('/api/temp/sessions',json={'cwd':str(tmp_path/'missing')}).status_code==422
    s=logged.post('/api/temp/sessions',json={'cwd':str(work)}).json()
    assert s['agent_id']=='_temp' and s['cwd']==str(work)
    assert [x['id'] for x in logged.get('/api/temp/sessions').json()]==[s['id']]
    assert '_temp' not in [a['id'] for a in logged.get('/api/agents').json()]
    assert logged.get('/api/agents/_temp').json()['name']=='Claude Code'
    manager=app.state.manager
    agent=manager.session_agent(app.state.index.sessions[s['id']])
    assert agent.cwd==str(work)
    opts=build_options(agent,app.state.index.sessions[s['id']],app.state.config.config.defaults,
                       app.state.config.config.server,None)
    assert opts.cwd==str(work) and opts.permission_mode=='bypassPermissions'
    fork=logged.post(f"/api/sessions/{s['id']}/fork",json={}).json()
    assert fork['cwd']==str(work)
    listing=logged.get('/api/fs/dirs',params={'path':str(work)}).json()
    assert [d['name'] for d in listing['dirs']]==['sub'] and listing['recent']==[str(work)]
    assert [d['name'] for d in logged.get('/api/fs/dirs',params={'path':str(work),'hidden':1}).json()['dirs']]==['.hid','sub']
    assert logged.delete(f"/api/sessions/{s['id']}").status_code==200

def test_fs_requires_auth(client):
    assert client.get('/api/fs/dirs').status_code==401

def test_temp_agent_settings_and_routes(logged,app,tmp_path):
    url='/api/agents/_temp'
    first=logged.get(url).json()
    assert first['name']=='Claude Code' and first['avatar']=='crab:gray'
    assert first['effective']['permission_mode']=='bypassPermissions'
    assert first['status']['last_session'] is None
    with logged.websocket_connect('/ws/events',headers={'origin':'http://testserver'}) as ws:
        assert ws.receive_json()['type']=='hello'
        patched=logged.patch(url,json={'name':'Scratch','override_groups':['permissions'],
            'permission_mode':'plan','id':'bad','cwd':'/bad','order':99,'created_at':'bad',
            'effective':{'model':'bad'},'status':{'running':99}}).json()
        assert ws.receive_json()['type']=='agents_changed'
    assert patched['name']=='Scratch' and patched['effective']['permission_mode']=='plan'
    assert patched['id']=='_temp' and patched['cwd']==first['cwd'] and patched['order']==0
    assert app.state.config.config.temp_agent.name=='Scratch'
    assert '[temp_agent]' in app.state.config.paths.config.read_text()
    assert logged.patch(url,json={'override_groups':['bogus']}).status_code==422
    assert logged.patch(url,json={'genui':'on'}).status_code==422
    assert logged.post(url+'/avatar',files={'file':('a.png',b'PNG','image/png')}).json()['avatar']=='file'
    assert logged.get(url+'/avatar').content==b'PNG'
    assert logged.delete(url).status_code==400
    assert logged.get(url+'/claude-md').status_code==400
    assert logged.put(url+'/claude-md',json={'content':'x'}).status_code==400
    assert logged.get(url+'/importable').status_code==400
    assert logged.post(url+'/import',json={'sdk_session_ids':[]}).status_code==400
    assert logged.post(url+'/sessions',json={}).status_code==400
    assert logged.get(url).json()['name']=='Scratch'

def test_temp_search_uses_each_cwd(logged,app,tmp_path,monkeypatch):
    one=tmp_path/'one'; two=tmp_path/'two'; one.mkdir(); two.mkdir()
    first=logged.post('/api/temp/sessions',json={'cwd':str(one)}).json()['id']
    second=logged.post('/api/temp/sessions',json={'cwd':str(two)}).json()['id']
    app.state.index.update(first,sdk_session_id='sdk-one')
    app.state.index.update(second,sdk_session_id='sdk-two')
    (one/'sdk-one.jsonl').write_text(json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':'alpha needle'}]}}))
    (two/'sdk-two.jsonl').write_text(json.dumps({'type':'user','message':{'content':'beta needle'}}))
    monkeypatch.setattr(server.history,'transcript_path',lambda sid,cwd: __import__('pathlib').Path(cwd)/(sid+'.jsonl'))
    hits=logged.get('/api/agents/_temp/search',params={'q':'needle'}).json()
    assert {h['session']['id'] for h in hits}=={first,second}
    assert logged.get('/api/agents/_temp').json()['status']['last_session']['id']==second
