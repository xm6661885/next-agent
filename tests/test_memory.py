import json

def test_memory_files(logged,tmp_path,monkeypatch):
    root=tmp_path/'claude'; monkeypatch.setenv('CLAUDE_CONFIG_DIR',str(root))
    proj=root/'projects'/'-w-app'; (proj/'memory').mkdir(parents=True)
    (proj/'s.jsonl').write_text(json.dumps({'type':'user','cwd':'/w/app'})+'\n')
    (proj/'memory'/'MEMORY.md').write_text('- [A](a.md)\n')
    (proj/'memory'/'a.md').write_text('---\nname: a\ndescription: the a fact\nmetadata:\n  type: user\n---\nbody\n')
    (root/'projects'/'-empty'/'memory').mkdir(parents=True)
    (root/'CLAUDE.md').write_text('global')
    l=logged.get('/api/memory').json()
    assert l['global']['path']=='CLAUDE.md' and len(l['projects'])==1
    p=l['projects'][0]
    assert p['cwd']=='/w/app' and [f['name'] for f in p['files']]==['MEMORY.md','a.md']
    assert p['files'][1]['description']=='the a fact' and p['files'][1]['type']=='user'
    assert logged.get('/api/memory/file',params={'path':'CLAUDE.md'}).json()['content']=='global'
    assert logged.put('/api/memory/file',json={'path':'CLAUDE.md','content':'new'}).json()['content']=='new'
    assert (root/'CLAUDE.md').read_text()=='new'
    rel='projects/-w-app/memory/b.md'
    assert logged.put('/api/memory/file',json={'path':rel,'content':'x','create':True}).status_code==200
    assert logged.put('/api/memory/file',json={'path':rel,'content':'x','create':True}).status_code==409
    assert logged.put('/api/memory/file',json={'path':'projects/-nope/memory/b.md','content':'x'}).status_code==404
    for bad in ['../x.md','settings.json','projects/../CLAUDE.md','projects/a/memory/x.txt']:
        assert logged.get('/api/memory/file',params={'path':bad}).status_code==400
    assert logged.delete('/api/memory/file',params={'path':rel}).status_code==200
    assert not (root/'projects'/'-w-app'/'memory'/'b.md').exists()

def test_memory_requires_auth(client):
    assert client.get('/api/memory').status_code==401
