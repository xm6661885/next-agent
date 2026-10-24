"""Build SDK client options from durable settings."""
import logging
from pathlib import Path
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import AgentDefinition
from .config import effective, genui_text

log = logging.getLogger(__name__)

def build_options(agent, session, defaults, server_cfg, can_use_tool, resume=None, fork=False,
                  resume_at=None, resume_session_at=None, new_session_id=None, stderr=None, custom_md_path=None):
    overrides = session.get('overrides',{})
    eff = effective(agent, defaults)
    def choose(name):
        return overrides.get(name) or eff[name] or None
    prompt = eff['system_prompt']
    if eff['system_prompt_mode']=='preset' and agent.claude_md=='custom':
        path = Path(custom_md_path) if custom_md_path else None
        if path and path.exists():
            prompt = '\n\n'.join(filter(None,[prompt,'# Agent instructions (CLAUDE.md)\n'+path.read_text()]))
    if eff['file_output']: prompt = '\n\n'.join(filter(None,[prompt,eff['file_output_prompt']]))
    if eff['genui']: prompt = '\n\n'.join(filter(None,[prompt,genui_text(eff['genui_prompt'],eff['genui_widgets'])]))
    if eff['system_prompt_mode']=='custom':
        system_prompt = prompt
    else:
        system_prompt = {'type':'preset','preset':'claude_code'}
        if prompt: system_prompt['append']=prompt
    thinking = None
    if eff['thinking']=='adaptive': thinking={'type':'adaptive'}
    elif eff['thinking']=='enabled': thinking={'type':'enabled','budget_tokens':eff['thinking_budget'] or 8000}
    elif eff['thinking']=='disabled': thinking={'type':'disabled'}
    sources = list(agent.setting_sources)
    env = {'CLAUDE_CODE_DISABLE_AUTO_MEMORY':'0' if agent.auto_memory else '1'}
    if server_cfg.anthropic_base_url: env['ANTHROPIC_BASE_URL']=server_cfg.anthropic_base_url
    if server_cfg.anthropic_api_key: env['ANTHROPIC_API_KEY']=server_cfg.anthropic_api_key
    env.update(agent.env)
    definitions = {name:AgentDefinition(**value) for name,value in agent.agents.items()}
    kwargs = dict(cwd=agent.cwd, model=choose('model'), effort=choose('effort'),
                  permission_mode=choose('permission_mode'), system_prompt=system_prompt, thinking=thinking,
                  setting_sources=sources, include_partial_messages=True, can_use_tool=can_use_tool,
                  enable_file_checkpointing=agent.enable_file_checkpointing,
                  extra_args={'replay-user-messages':None,'allow-dangerously-skip-permissions':None,**agent.extra_args},
                  allowed_tools=agent.allowed_tools,disallowed_tools=agent.disallowed_tools,
                  add_dirs=agent.add_dirs,env=env,mcp_servers=agent.mcp_servers,
                  agents=definitions or None,max_turns=agent.max_turns or None,
                  max_budget_usd=agent.max_budget_usd or None,fallback_model=eff['fallback_model'] or None,
                  cli_path=server_cfg.cli_path or None,stderr=stderr,
                  max_buffer_size=64*1024*1024)
    if '*' not in agent.tools: kwargs['tools']=agent.tools
    if resume:
        kwargs['resume']=resume
        if fork:
            kwargs['fork_session']=True
            kwargs['resume_session_at']=resume_at
        elif resume_session_at:
            kwargs['resume_session_at']=resume_session_at
    elif new_session_id:
        kwargs['session_id']=new_session_id
    return ClaudeAgentOptions(**kwargs)

# Fields that only describe how to attach to the session, not how the CLI behaves.
_SESSION_FIELDS = {'can_use_tool','stderr','resume','fork_session','resume_session_at','session_id'}

def options_key(opts):
    """Comparable fingerprint of the settings a running CLI was launched with."""
    return repr({k:v for k,v in vars(opts).items() if k not in _SESSION_FIELDS})
