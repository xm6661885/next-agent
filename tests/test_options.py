from server.config import Agent, Defaults, ServerConfig
from server.options import build_options
from server.config import DEFAULT_FILE_OUTPUT_PROMPT

def test_options_and_custom_md(tmp_path):
    path=tmp_path/'CLAUDE.md'; path.write_text('Be precise')
    agent=Agent(id='a',name='A',cwd=str(tmp_path),claude_md='custom',thinking='enabled',
                setting_sources=['project'],agents={'reviewer':{'description':'Review','prompt':'Review code'}})
    session={'overrides':{'model':'sonnet','effort':None,'permission_mode':None}}
    opts=build_options(agent,session,Defaults(),ServerConfig(password_hash='***'),lambda *a:None,
                       new_session_id='new',custom_md_path=path)
    assert opts.session_id=='new' and opts.resume is None
    assert opts.model=='sonnet' and opts.thinking=={'type':'enabled','budget_tokens':8000}
    assert 'Be precise' in opts.system_prompt['append']
    assert 'user' in opts.setting_sources
    assert opts.agents['reviewer'].description=='Review'
    agent.system_prompt_mode='custom'
    agent.system_prompt='Only this'
    opts=build_options(agent,session,Defaults(),ServerConfig(password_hash='***'),lambda *a:None,
                       resume='old',fork=True,resume_at='u',custom_md_path=path)
    assert opts.system_prompt=='Only this\n\n'+DEFAULT_FILE_OUTPUT_PROMPT
    assert opts.resume=='old' and opts.fork_session and opts.resume_session_at=='u'

def test_file_output_prompt_and_resume_without_fork(tmp_path):
    agent=Agent(id='a',name='A',cwd=str(tmp_path),system_prompt='Hello')
    defaults=Defaults()
    cfg=ServerConfig(password_hash='***')
    opts=build_options(agent,{},defaults,cfg,None,resume='old',resume_session_at='parent')
    assert opts.resume_session_at=='parent' and not opts.fork_session
    assert opts.system_prompt['append']=='Hello\n\n'+DEFAULT_FILE_OUTPUT_PROMPT
    agent.file_output='off'
    opts=build_options(agent,{},defaults,cfg,None)
    assert opts.system_prompt['append']=='Hello'
    agent.file_output='on'; agent.file_output_prompt='Custom'
    agent.system_prompt_mode='custom'
    opts=build_options(agent,{},defaults,cfg,None)
    assert opts.system_prompt=='Hello\n\nCustom'
