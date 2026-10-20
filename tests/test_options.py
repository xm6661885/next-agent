from server.config import Agent, Defaults, ServerConfig
from server.options import build_options
from server.config import DEFAULT_FILE_OUTPUT_PROMPT

def test_options_and_custom_md(tmp_path):
    path=tmp_path/'CLAUDE.md'; path.write_text('Be precise')
    agent=Agent(id='a',name='A',cwd=str(tmp_path),claude_md='custom',thinking='enabled',override_groups=['model'],
                setting_sources=['project'],agents={'reviewer':{'description':'Review','prompt':'Review code'}})
    session={'overrides':{'model':'sonnet','effort':None,'permission_mode':None}}
    opts=build_options(agent,session,Defaults(genui=False),ServerConfig(password_hash='***'),lambda *a:None,
                       new_session_id='new',custom_md_path=path)
    assert opts.session_id=='new' and opts.resume is None
    assert opts.model=='sonnet' and opts.thinking=={'type':'enabled','budget_tokens':8000}
    assert 'Be precise' in opts.system_prompt['append']
    assert opts.setting_sources==['project']
    assert opts.tools is None and opts.env['CLAUDE_CODE_DISABLE_AUTO_MEMORY']=='0'
    assert opts.agents['reviewer'].description=='Review'
    agent.override_groups=['system_prompt']
    agent.system_prompt_mode='custom'
    agent.system_prompt='Only this'
    opts=build_options(agent,session,Defaults(genui=False),ServerConfig(password_hash='***'),lambda *a:None,
                       resume='old',fork=True,resume_at='u',custom_md_path=path)
    assert opts.system_prompt=='Only this\n\n'+DEFAULT_FILE_OUTPUT_PROMPT
    assert opts.resume=='old' and opts.fork_session and opts.resume_session_at=='u'

def test_file_output_prompt_and_resume_without_fork(tmp_path):
    agent=Agent(id='a',name='A',cwd=str(tmp_path),override_groups=['system_prompt'],system_prompt='Hello')
    defaults=Defaults(genui=False)
    cfg=ServerConfig(password_hash='***')
    opts=build_options(agent,{},defaults,cfg,None,resume='old',resume_session_at='parent')
    assert opts.resume_session_at=='parent' and not opts.fork_session
    assert opts.system_prompt['append']=='Hello\n\n'+DEFAULT_FILE_OUTPUT_PROMPT
    agent.override_groups.append('file_output'); agent.file_output=False
    opts=build_options(agent,{},defaults,cfg,None)
    assert opts.system_prompt['append']=='Hello'
    agent.file_output=True; agent.file_output_prompt='Custom'
    agent.system_prompt_mode='custom'
    opts=build_options(agent,{},defaults,cfg,None)
    assert opts.system_prompt=='Hello\n\nCustom'

def test_genui_prompt(tmp_path):
    from server.config import DEFAULT_GENUI_PROMPT, GENUI_WIDGETS
    agent=Agent(id='a',name='A',cwd=str(tmp_path),override_groups=['system_prompt','file_output'],system_prompt='Hi',file_output=False)
    cfg=ServerConfig(password_hash='***')
    opts=build_options(agent,{},Defaults(),cfg,None)
    assert opts.system_prompt['append']=='Hi\n\n'+'\n'.join([DEFAULT_GENUI_PROMPT,*GENUI_WIDGETS.values()])
    opts=build_options(agent,{},Defaults(genui=False),cfg,None)
    assert opts.system_prompt['append']=='Hi'
    agent.override_groups.append('genui'); agent.genui=True; agent.genui_prompt='UI'
    opts=build_options(agent,{},Defaults(genui=False),cfg,None)
    assert opts.system_prompt['append'].startswith('Hi\n\nUI\n- ask:')
    agent=Agent.model_validate({**agent.model_dump(),'genui_widgets':{'ask':{'on':True,'prompt':'ASK'},**{k:{'on':False} for k in GENUI_WIDGETS if k!='ask'}}})
    opts=build_options(agent,{},Defaults(genui=False),cfg,None)
    assert opts.system_prompt['append']=='Hi\n\nUI\nASK'
    agent.genui_widgets['ask'].on=False
    opts=build_options(agent,{},Defaults(genui=False),cfg,None)
    assert opts.system_prompt['append']=='Hi'

def test_uploads_go_to_agent_cwd(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from server.uploads import UploadService
    index=SimpleNamespace(sessions={'s':{'id':'s','agent_id':'a'}},uploads={},save=lambda:None)
    manager=SimpleNamespace(session_agent=lambda s:SimpleNamespace(cwd=str(tmp_path)))
    service=UploadService(SimpleNamespace(uploads=tmp_path/'data'),index,manager)
    class F:
        filename='a b.png'
        async def read(self,n): return b'x'
    record=asyncio.run(service.save('s',F()))
    assert record['path'].startswith(str(tmp_path/'uploads'))
    service.remove_session('s')
    assert not index.uploads and not list((tmp_path/'uploads').iterdir())

def test_effective_options_and_session_overrides(tmp_path):
    agent=Agent(id='a',name='A',cwd=str(tmp_path),model='opus',effort='low',permission_mode='plan',
                system_prompt='Own',system_prompt_mode='custom',file_output=False,genui=False)
    defaults=Defaults(model='sonnet',effort='high',permission_mode='acceptEdits',system_prompt_mode='custom',
                      system_prompt='Global',file_output=False,genui=False)
    cfg=ServerConfig(password_hash='***')
    opts=build_options(agent,{},defaults,cfg,None)
    assert (opts.model,opts.effort,opts.permission_mode)==('sonnet','high','acceptEdits')
    assert opts.system_prompt=='Global'
    agent.override_groups=['model','permissions','system_prompt']
    opts=build_options(agent,{'overrides':{'model':'haiku','effort':'max','permission_mode':'default'}},defaults,cfg,None)
    assert (opts.model,opts.effort,opts.permission_mode)==('haiku','max','default')
    assert opts.system_prompt=='Own'

def test_thinking_and_fallback_follow_global(tmp_path):
    agent=Agent(id='a',name='A',cwd=str(tmp_path),thinking='enabled',fallback_model='haiku')
    opts=build_options(agent,{},Defaults(model='opus',effort='low',thinking='disabled',fallback_model='sonnet'),
                       ServerConfig(password_hash='***'),lambda *a:None)
    assert opts.thinking=={'type':'disabled'} and opts.fallback_model=='sonnet' and opts.effort=='low'

def test_api_env_tools_and_memory(tmp_path):
    agent=Agent(id='a',name='A',cwd=str(tmp_path),tools=[],auto_memory=False,env={'X':'1'})
    cfg=ServerConfig(password_hash='***',anthropic_base_url='https://api.example',anthropic_api_key='sk')
    opts=build_options(agent,{},Defaults(),cfg,None)
    assert opts.tools==[]
    assert opts.env=={'CLAUDE_CODE_DISABLE_AUTO_MEMORY':'1','ANTHROPIC_BASE_URL':'https://api.example','ANTHROPIC_API_KEY':'sk','X':'1'}
    agent.tools=['Read']
    assert build_options(agent,{},Defaults(),cfg,None).tools==['Read']

def test_btw_options_strip_tools(tmp_path):
    from server.btw import btw_options
    agent=Agent(id='a',name='A',cwd=str(tmp_path),mcp_servers={'x':{'command':'x'}})
    opts=btw_options(agent,{},'old',Defaults(genui=False),ServerConfig(password_hash='***'))
    assert opts.tools==[] and opts.max_turns==1 and opts.mcp_servers=={} and opts.can_use_tool is None
    assert opts.resume=='old' and opts.fork_session
    assert 'no-session-persistence' in opts.extra_args and 'replay-user-messages' not in opts.extra_args
