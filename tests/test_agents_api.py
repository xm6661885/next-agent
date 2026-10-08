def test_crud_reorder_md(logged,tmp_path):
    cwd=tmp_path/'work'; cwd.mkdir()
    response=logged.post('/api/agents',json={'name':'Test Agent','cwd':str(cwd)})
    assert response.status_code==200,response.text
    aid=response.json()['id']; assert aid=='test-agent'
    assert logged.post('/api/agents',json={'name':'Test Agent','cwd':str(cwd)}).status_code==409
    assert logged.patch(f'/api/agents/{aid}',json={'description':'hello'}).json()['description']=='hello'
    assert logged.patch(f'/api/agents/{aid}',json={'id':'other'}).status_code==400
    assert logged.post('/api/agents/reorder',json={'ids':[aid,'claude']}).status_code==200
    assert logged.get('/api/agents').json()[0]['id']==aid
    assert logged.put(f'/api/agents/{aid}/claude-md',json={'content':'inherit'}).json()['path']==str(cwd/'CLAUDE.md')
    logged.patch(f'/api/agents/{aid}',json={'claude_md':'custom'})
    assert logged.put(f'/api/agents/{aid}/claude-md',json={'content':'custom'}).json()['path'].endswith(f'agents/{aid}/CLAUDE.md')
    assert logged.delete(f'/api/agents/{aid}').json()=={'ok':True}

def test_avatar_limits(logged,tmp_path):
    aid=logged.post('/api/agents',json={'name':'Avatar','cwd':str(tmp_path)}).json()['id']
    url=f'/api/agents/{aid}/avatar'
    assert logged.post(url,files={'file':('a.txt',b'x','text/plain')}).status_code==415
    assert logged.post(url,files={'file':('a.png',b'x'*(2*1024*1024+1),'image/png')}).status_code==413
    assert logged.post(url,files={'file':('a.png',b'PNG','image/png')}).json()['avatar']=='file'
    assert logged.get(url).content==b'PNG'
