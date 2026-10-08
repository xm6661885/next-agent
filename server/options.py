"""Build SDK client options from durable settings."""
import logging
from pathlib import Path
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import AgentDefinition
from .config import DEFAULT_FILE_OUTPUT_PROMPT

log = logging.getLogger(__name__)

def build_options(agent, session, defaults, server_cfg, can_use_tool, resume=None, fork=False,
                  resume_at=None, resume_session_at=None, new_session_id=None, stderr=None, custom_md_path=None):
    overrides = session.get('overrides',{})
    def choose(name):
        return overrides.get(name) or getattr(agent,name,'') or getattr(defaults,name,'') or None
    prompt = agent.system_prompt
    if agent.system_prompt_mode=='preset' and agent.claude_md=='custom':
        path = Path(custom_md_path) if custom_md_path else None
        if path and path.exists():
            prompt = '\n\n'.join(filter(None,[prompt,'# Agent instructions (CLAUDE.md)\n'+path.read_text()]))
    enabled = agent.file_output=='on' or (agent.file_output=='' and defaults.file_output)
    if enabled:
        text = agent.file_output_prompt or defaults.file_output_prompt or DEFAULT_FILE_OUTPUT_PROMPT
        prompt = '\n\n'.join(filter(None,[prompt,text]))
    if agent.system_prompt_mode=='custom':
        system_prompt = prompt
    else:
        system_prompt = {'type':'preset','preset':'claude_code'}
        if prompt: system_prompt['append']=prompt
    thinking = None
    if agent.thinking=='adaptive': thinking={'type':'adaptive'}
    elif agent.thinking=='enabled': thinking={'type':'enabled','budget_tokens':agent.thinking_budget or 8000}
    elif agent.thinking=='disabled': thinking={'type':'disabled'}
    sources = list(agent.setting_sources)
    if 'user' not in sources:
        log.warning('Adding user setting source for credentials')
        sources.insert(0,'user')
    definitions = {name:AgentDefinition(**value) for name,value in agent.agents.items()}
    kwargs = dict(cwd=agent.cwd, model=choose('model'), effort=choose('effort'),
                  permission_mode=choose('permission_mode'), system_prompt=system_prompt, thinking=thinking,
                  setting_sources=sources, include_partial_messages=True, can_use_tool=can_use_tool,
                  enable_file_checkpointing=agent.enable_file_checkpointing,
                  extra_args={'replay-user-messages':None,**agent.extra_args},
                  allowed_tools=agent.allowed_tools,disallowed_tools=agent.disallowed_tools,
                  add_dirs=agent.add_dirs,env=agent.env,mcp_servers=agent.mcp_servers,
                  agents=definitions or None,max_turns=agent.max_turns or None,
                  max_budget_usd=agent.max_budget_usd or None,fallback_model=agent.fallback_model or None,
                  cli_path=server_cfg.cli_path or None,stderr=stderr)
    if agent.tools: kwargs['tools']=agent.tools
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
