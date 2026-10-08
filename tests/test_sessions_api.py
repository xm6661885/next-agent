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
