from datetime import datetime
import tomlkit
from pydantic import BaseModel
from server.tomlstore import TomlFile

def test_raw_files_and_form_routing(logged,app):
    config=app.state.config
    assert config.paths.core_config.read_text().startswith('# next-agent core settings: login, external API, and the Claude CLI shared by Agents and Workflow\n')
    raw=logged.get('/api/config/raw').json()
    assert raw['file']=='agents' and raw['path']==str(config.paths.agents_config)
    assert 'password_hash' not in raw['content']
    core_before=config.paths.core_config.read_bytes()
    content=raw['content'].replace('name = "Claude"','name = "Renamed" # keep me')
    assert logged.put('/api/config/raw',json={'content':content}).json()['content']==content
    assert config.config.agents[0].name=='Renamed' and config.paths.core_config.read_bytes()==core_before
    response=logged.patch('/api/config',json={'server':{'max_concurrent':2},'defaults':{'model':'haiku'},
                                            'builtin_mcp':{'first':{'enabled':True},'second':42}})
    assert response.status_code==200
    assert logged.patch('/api/config',json={'builtin_mcp':{'second':43}}).json()['builtin_mcp']=={'first':{'enabled':True},'second':43}
    assert set(tomlkit.parse(config.paths.core_config.read_text()))=={'server'}
    assert 'max_concurrent' not in config.paths.agents_config.read_text()
    assert '# keep me' in config.paths.agents_config.read_text()
    assert app.state.manager.semaphore.capacity==2
    for file,content in [('core','[server]\npassword_hash="bad"'),('agents','[server]\npassword_hash="***"'),
                         ('agents',raw['content']+raw['content'][raw['content'].index('[[agents]]'):])]:
        before=(config.paths.core_config.read_bytes(),config.paths.agents_config.read_bytes())
        assert logged.put('/api/config/raw',params={'file':file},json={'content':content}).status_code==400
        assert before==(config.paths.core_config.read_bytes(),config.paths.agents_config.read_bytes())
    for body in ({},[],{'content':7}):
        assert logged.put('/api/config/raw',json=body).status_code==400
    for method in (logged.get,logged.put):
        assert method('/api/config/raw?file=../secret').status_code==400

def test_raw_module_registry_available_at_mount(tmp_path,monkeypatch):
    import server.app
    mounted=[]
    def mount(app,core):
        assert app.state.raw_configs is core.modules['raw_configs']
        mounted.append(set(core.modules['raw_configs']))
        assert core.bridge is not None
    monkeypatch.setattr(server.app.more_agents,'mount',mount)
    server.app.create_app(tmp_path)
    assert mounted==[{'core','agents'}]

def test_module_raw_and_settings_overview(logged,app):
    core=app.state.core
    for name in ('acp','chat','workflow'): core.modules.pop('overview_'+name,None)
    empty=logged.get('/api/settings/overview').json()
    assert empty['version']==core.version
    assert empty['modules']=={'agents':{'agents':1,'more_agents_agents':0,'sessions':0},'chat':{},'workflow':{}}
    class Settings(BaseModel):
        count:int=1
    config=TomlFile(core.paths.config_dir/'chat.toml',Settings,'# module comment\ncount = 1\n')
    calls=[]
    async def changed(): calls.append(config.data.count)
    config.on_change(changed)
    core.modules['raw_configs']['chat']=config
    core.modules['overview_more_agents']=lambda:{'more_agents_agents':3,'sessions':4}
    core.modules['overview_chat']=lambda:{'assistants':2,'providers':1,'sessions':config.data.count}
    core.modules['overview_workflow']=lambda:{'workflows':5,'runs':6}
    app.state.index.create('claude',origin='schedule')
    response=logged.put('/api/config/raw?file=chat',json={'content':'# module comment\ncount = 7\n'})
    assert response.json()=={'content':'# module comment\ncount = 7\n','file':'chat','path':str(config.path)}
    assert calls==[7]
    assert logged.put('/api/config/raw?file=chat',json={'content':'count = "bad"'}).status_code==400
    overview=logged.get('/api/settings/overview').json()
    assert overview['modules']=={'agents':{'agents':1,'more_agents_agents':3,'sessions':5},
                                 'chat':{'assistants':2,'providers':1,'sessions':7},'workflow':{'workflows':5,'runs':6}}
    files={entry['file']:entry for entry in overview['files']}
    assert files['chat']['path']==str(config.path)
    assert abs(datetime.fromisoformat(files['chat']['mtime']).timestamp()-config.path.stat().st_mtime)<.000001

def test_settings_require_auth(client):
    assert client.get('/api/settings/overview').status_code==401
    assert client.get('/api/config/raw').status_code==401
