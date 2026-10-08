import asyncio
import bcrypt
import pytest
from server.paths import DataDir
from server.config import ConfigStore, DEFAULT_FILE_OUTPUT_PROMPT

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
        store.paths.config.write_text(store.paths.config.read_text().replace('model = ""','model = "opus"'))
        await asyncio.sleep(.05)
        assert store.config.defaults.model=='opus'
        store.paths.config.write_text('invalid = [')
        await asyncio.sleep(.05)
        assert store.config.defaults.model=='opus' and len(calls)==1
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
    agent=logged.post('/api/agents',json={'name':'Output','cwd':str(tmp_path),'file_output':'off'})
    assert agent.json()['file_output']=='off'
    assert logged.patch('/api/agents/output',json={'file_output':'sometimes'}).status_code==422
