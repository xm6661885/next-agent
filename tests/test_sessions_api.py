import json
import server.history
import server.app

def test_batch_delete(logged,tmp_path):
    aid=logged.post('/api/agents',json={'name':'Del','cwd':str(tmp_path)}).json()['id']
    ids=[logged.post(f'/api/agents/{aid}/sessions',json={'title':f't{i}'}).json()['id'] for i in range(3)]
    r=logged.post('/api/sessions/delete',json={'ids':ids[:2]+['missing']}).json()
    assert r=={'ok':True,'deleted':ids[:2]}
    assert [s['id'] for s in logged.get(f'/api/agents/{aid}/sessions').json()]==[ids[2]]

def test_search(logged,tmp_path,monkeypatch):
    aid=logged.post('/api/agents',json={'name':'Find','cwd':str(tmp_path)}).json()['id']
    a=logged.post(f'/api/agents/{aid}/sessions',json={'title':'Login bug'}).json()['id']
    b=logged.post(f'/api/agents/{aid}/sessions',json={'title':'Other'}).json()['id']
    index=logged.app.state.index
    index.update(b,sdk_session_id='sdk-b')
    transcript=tmp_path/'sdk-b.jsonl'
    lines=[{'type':'user','message':{'role':'user','content':'请帮我修复 Webhook 重试'}},
           {'type':'assistant','message':{'content':[{'type':'tool_use','id':'x','name':'Bash','input':{'command':'zebra'}}]}},
           {'type':'assistant','message':{'content':[{'type':'text','text':'Done. The webhook now retries.'}]}}]
    transcript.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in lines))
    monkeypatch.setattr(server.history,'transcript_path',lambda sid,cwd: transcript if sid=='sdk-b' else None)
    url=f'/api/agents/{aid}/search'
    assert logged.get(url,params={'q':''}).json()==[]
    hits=logged.get(url,params={'q':'webhook'}).json()
    assert [h['session']['id'] for h in hits]==[b] and 'Webhook' in hits[0]['snippet']
    assert logged.get(url,params={'q':'修复'}).json()[0]['session']['id']==b
    assert logged.get(url,params={'q':'zebra'}).json()==[]
    hits=logged.get(url,params={'q':'login'}).json()
    assert [h['session']['id'] for h in hits]==[a] and hits[0]['snippet']==''

def test_session_metadata_and_all_origins_in_lists_and_search(logged,app,tmp_path):
    from server.store import SessionIndex
    index=app.state.index
    first=logged.post('/api/agents/claude/sessions',json={'title':'needle ui'}).json()
    assert (first['origin'],first['parent'],first['extra'])==('ui',None,None)
    parent={'run_id':'run','block_id':'block'}
    extra={'allowed_tools':['Read']}
    second=index.create('claude','needle workflow',origin='workflow',parent=parent,extra=extra)
    third=index.create('_temp','needle schedule',origin='schedule',cwd=str(tmp_path))
    fourth=logged.post('/api/temp/sessions',json={'cwd':str(tmp_path)}).json()
    assert fourth['origin']=='ui' and fourth['extra'] is None
    assert {s['id'] for s in logged.get('/api/agents/claude/sessions').json()}=={first['id'],second['id']}
    assert {s['id'] for s in logged.get('/api/temp/sessions').json()}=={third['id'],fourth['id']}
    hits=logged.get('/api/agents/claude/search?q=needle').json()
    assert {h['session']['origin'] for h in hits}=={'ui','workflow'}
    assert logged.get('/api/agents/_temp/search?q=needle').json()[0]['session']['origin']=='schedule'
    saved=SessionIndex(app.state.paths).sessions[second['id']]
    assert saved['origin']=='workflow' and saved['parent']==parent and saved['extra']==extra
    for key in ('origin','parent','extra'): index.sessions[first['id']].pop(key)
    assert logged.get('/api/sessions/'+first['id']).json()['origin']=='ui'
