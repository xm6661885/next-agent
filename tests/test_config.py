import asyncio
import bcrypt
import pytest
from server.paths import DataDir
from server.config import ConfigStore, DEFAULT_FILE_OUTPUT_PROMPT, DEFAULT_GENUI_PROMPT, Agent, Defaults, effective, GROUPS

def test_first_start_roundtrip(tmp_path):
    store=ConfigStore(DataDir(tmp_path))
    assert '070827' not in store.paths.config.read_text()
    assert bcrypt.checkpw(b'070827',store.config.server.password_hash.encode())
    store.doc['defaults']['model']='sonnet'; store.save()
    assert '# next-agent configuration' in store.paths.config.read_text()
    assert ConfigStore(DataDir(tmp_path)).config.defaults.model=='sonnet'

@pytest.mark.asyncio
async def test_hot_reload_invalid(tmp_path):
    store=ConfigStore(DataDir(tmp_path)); calls=[]
    async def changed(): calls.append(True)
    task=asyncio.create_task(store.watch(changed,interval=.01))
    try:
        store.paths.config.write_text(store.paths.config.read_text().replace('effort = "','effort = "max" #',1))
        await asyncio.sleep(.5)
        assert store.config.defaults.effort=='max'
        store.paths.config.write_text('invalid = [')
        await asyncio.sleep(.5)
        assert store.config.defaults.effort=='max' and len(calls)==1
    finally: task.cancel()

def test_raw_config_mask_and_validation(logged,app):
    response=logged.get('/api/config/raw')
    assert '***' in response.json()['content']
    original=app.state.config.config.server.password_hash
    content=response.json()['content'].replace('max_concurrent = 3','max_concurrent = 2')
    assert logged.put('/api/config/raw',json={'content':content}).status_code==200
    assert app.state.config.config.server.password_hash==original
    assert app.state.config.config.server.max_concurrent==2
    assert logged.put('/api/config/raw',json={'content':'invalid = ['}).status_code==400

def test_form_defaults_pricing_validation(logged,app):
    store=app.state.config
    form=logged.get('/api/config').json()
    assert 'password_hash' not in form['server']
    assert form['defaults']['file_output_prompt']==DEFAULT_FILE_OUTPUT_PROMPT
    assert form['default_file_output_prompt']==DEFAULT_FILE_OUTPUT_PROMPT
    old_hash=store.config.server.password_hash
    response=logged.patch('/api/config',json={'server':{'max_concurrent':2,'host':'no','password_hash':'no'},
                   'defaults':{'custom_models':[' custom ','','custom','opus'],'file_output_prompt':''},
                   'pricing':{' claude-opus-5-5 ':{'input':5,'output':25}}})
    assert response.status_code==200,response.text
    assert response.json()['server']['max_concurrent']==2
    assert store.config.server.password_hash==old_hash and store.config.server.host=='::'
    assert response.json()['defaults']['custom_models']==['custom','opus']
    assert response.json()['defaults']['file_output_prompt']==DEFAULT_FILE_OUTPUT_PROMPT
    assert response.json()['pricing']['claude-opus-5-5']['input']==5
    assert '[pricing."claude-opus-5-5"]' in store.paths.config.read_text()
    assert '# next-agent configuration' in store.paths.config.read_text()
    assert logged.get('/api/meta').json()['models'].count('opus')==1
    before=store.paths.config.read_text()
    response=logged.patch('/api/config',json={'pricing':{'bad':{'input':-1}}})
    assert response.status_code==422 and 'input' in response.json()['detail']
    assert store.paths.config.read_text()==before
    assert logged.patch('/api/config',json={'pricing':{}}).json()['pricing']=={}

def test_agent_file_output_validation(logged,tmp_path):
    agent=logged.post('/api/agents',json={'name':'Output','cwd':str(tmp_path),'file_output':False,'override_groups':['file_output']})
    assert agent.json()['file_output'] is False
    assert logged.patch('/api/agents/output',json={'file_output':'sometimes'}).status_code==422

def test_genui_config(logged,tmp_path):
    form=logged.get('/api/config').json()
    assert form['defaults']['genui'] is True and form['default_genui_prompt']==DEFAULT_GENUI_PROMPT
    r=logged.patch('/api/config',json={'defaults':{'genui':False,'genui_prompt':''}})
    assert r.json()['defaults']['genui'] is False and r.json()['defaults']['genui_prompt']==DEFAULT_GENUI_PROMPT
    assert logged.post('/api/agents',json={'name':'G','cwd':str(tmp_path),'genui':'maybe'}).status_code==422

def test_effective_groups_and_validation(tmp_path):
    defaults=Defaults(model='sonnet',effort='high',permission_mode='plan',system_prompt='Global',
                      file_output=False,genui=False,idle_mode='never')
    agent=Agent(id='a',name='A',cwd=str(tmp_path),override_groups=['model','model','file_output','genui','idle'],
                model='opus',effort='low',file_output=True,genui=True,idle_mode='adaptive',
                idle_timeout_min=2,adaptive_keep=3)
    assert agent.override_groups==['model','file_output','genui','idle']
    result=effective(agent,defaults)
    assert set(result)=={field for fields in GROUPS.values() for field in fields}
    assert result['model']=='opus' and result['effort']=='low' and result['permission_mode']=='plan'
    assert result['system_prompt']=='Global' and result['idle_mode']=='adaptive' and result['adaptive_keep']==3
    assert result['file_output_prompt']==DEFAULT_FILE_OUTPUT_PROMPT
    assert result['genui_prompt']==DEFAULT_GENUI_PROMPT
    from pydantic import ValidationError
    for bad in ({'override_groups':['unknown']},{'file_output':'on'},{'genui':'off'},
                {'permission_mode':''},{'idle_timeout_min':-1},{'adaptive_keep':0}):
        with pytest.raises(ValidationError): Agent(id='a',name='A',cwd=str(tmp_path),**bad)

def test_old_config_migration(tmp_path):
    store=ConfigStore(DataDir(tmp_path))
    old=f'''# keep this comment
[server]
password_hash = "{store.config.server.password_hash}"
idle_mode = "adaptive" # old location
idle_timeout_min = 4
adaptive_keep = 2
[defaults]
permission_mode = "plan"
file_output = false
genui = true
[[agents]]
id = "old"
name = "Old"
cwd = "{tmp_path}"
model = "opus"
effort = "low"
permission_mode = ""
file_output = ""
[[agents]]
id = "special"
name = "Special"
cwd = "{tmp_path}"
model = ""
effort = ""
permission_mode = "default"
system_prompt_mode = "custom"
system_prompt = "Own"
file_output = "off"
genui = "on"
genui_prompt = "Own UI"
'''
    store.paths.config.write_text(old)
    store.load()
    agent=store.config.agents[0]
    assert agent.override_groups==['model']
    assert (agent.model,agent.effort,agent.permission_mode)==('opus','low','plan')
    assert agent.file_output is False and agent.genui is True
    assert (agent.idle_mode,agent.idle_timeout_min,agent.adaptive_keep)==('adaptive',4,2)
    special=store.config.agents[1]
    assert special.override_groups==['permissions','system_prompt','file_output','genui']
    assert special.model and special.effort and special.permission_mode=='default'
    assert special.file_output is False and special.genui is True
    assert store.config.defaults.idle_mode=='adaptive' and not hasattr(store.config.server,'idle_mode')
    content=store.paths.config.read_text()
    assert '# keep this comment' in content and 'idle_mode = "adaptive" # old location' in content
    assert '[server]\npassword_hash' in content and 'override_groups = ["model"]' in content
    store.load()
    assert store.paths.config.read_text()==content

def test_migration_keeps_existing_default_idle(tmp_path):
    store=ConfigStore(DataDir(tmp_path))
    store.doc['defaults']['idle_mode']='never'
    store.doc['server']['idle_mode']='adaptive'
    store.save()
    store.load()
    assert store.config.defaults.idle_mode=='never'
    assert 'idle_mode' not in store.doc['server']

def test_config_form_new_keys(logged,app):
    form=logged.get('/api/config').json()
    assert {'system_prompt_mode','system_prompt','idle_mode','idle_timeout_min','adaptive_keep','artifacts'} <= form['defaults'].keys()
    response=logged.patch('/api/config',json={'server':{'idle_mode':'never','max_concurrent':2},
        'defaults':{'system_prompt_mode':'custom','system_prompt':'Hello','idle_mode':'adaptive',
                    'idle_timeout_min':3,'adaptive_keep':2,'artifacts':False}})
    assert response.status_code==200,response.text
    assert response.json()['defaults']['system_prompt']=='Hello'
    assert response.json()['defaults']['idle_mode']=='adaptive'
    assert response.json()['defaults']['artifacts'] is False
    assert 'idle_mode' not in response.json()['server']
    assert 'idle_mode' not in app.state.config.doc['server']
    assert logged.patch('/api/config',json={'defaults':{'artifacts':'off'}}).status_code==422
