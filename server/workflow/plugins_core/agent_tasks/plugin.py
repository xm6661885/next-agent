"""Agent cards run normal Agents sessions through the shared bridge."""
import asyncio

from server.workflow.sdk import Input, Output, Plugin, StepError

PROMPT = Input('prompt', label='Prompt', multiline=True, required=True)
SESSION = Input('session_id', label='Session ID', advanced=True)
CLAUDE_INPUTS = [
    Input('model', label='Model'),
    Input('effort', 'select', 'Thinking effort', default='', options=['', 'low', 'medium', 'high', 'xhigh', 'max']),
    Input('append_system_prompt', label='System prompt (append)', multiline=True, advanced=True),
    Input('output_schema', 'json', 'Structured output JSON schema', multiline=True, advanced=True),
]
CLAUDE_OUTPUTS = [Output('result', default=True), Output('structured', 'json'), Output('session_id'), Output('cost_usd', 'number')]


def split(value):
    return [s.strip() for s in value.replace('\n', ',').split(',') if s.strip()]


class AgentCard(Plugin):
    category = 'AI'
    icon = 'sparkles'
    color = 'pink'
    uses_agent_slot = True
    outputs = CLAUDE_OUTPUTS
    module = 'agents'

    async def run(self, ctx, p):
        aid = '_temp' if self.id=='builtin.temp_task' else p['agent']
        sid = None

        def on_session(value):
            nonlocal sid
            sid = value
            ctx.log_event('agent_session', {'module': self.module, 'agent_id': aid, 'session_id': sid})

        kwargs = dict(session_id=p['session_id'] or None, origin='workflow',
                      title=ctx.block.get('note') or f'{ctx.workflow_name}: {self.name}',
                      parent={'module': 'workflow', 'run_id': ctx.run_id, 'block_id': ctx.block_id}, on_session=on_session)
        if self.module=='agents':
            kwargs['overrides'] = {key: p[key] or None for key in ('model', 'effort', 'permission_mode') if key in p}
            extra = {key: p[key] for key in ('append_system_prompt', 'output_schema') if p.get(key)}
            if p.get('output_schema') is not None and not isinstance(p['output_schema'], dict):
                raise StepError('The structured output JSON schema must be a JSON object')
            if p.get('env') is not None and (not isinstance(p['env'], dict) or
                    any(not isinstance(k, str) or not isinstance(v, str) or not k or '=' in k or '\0' in k+v for k, v in p['env'].items())):
                raise StepError('Environment variables must be a JSON object of strings')
            env = {**ctx.env, **(p.get('env') or {})}
            if env: extra['env'] = env
            for key in ('allowed_tools', 'disallowed_tools', 'add_dirs'):
                if p.get(key): extra[key] = split(p[key])
            for key in ('max_turns', 'max_budget_usd'):
                value = p.get(key)
                if value is not None:
                    if value <= 0 or (key=='max_turns' and value != int(value)):
                        raise StepError(f'{key} must be positive' + (' and an integer' if key=='max_turns' else ''))
                    extra[key] = int(value) if key=='max_turns' else value
            kwargs['extra'] = extra
            if self.id=='builtin.temp_task':
                kwargs['cwd'] = ctx.resolve_cwd(p['cwd']) if p['cwd'].strip() else None
        if self.module == 'more_agents':
            if not p.get('session_id') and not p.get('cwd', '').strip(): raise StepError('cwd is required for a new More Agents session')
            kwargs.update(cwd=p.get('cwd', ''), model=p.get('model', ''), effort=p.get('effort', ''))
        try:
            call = ctx.bridge.run_more if self.module=='more_agents' else ctx.bridge.run_claude
            result = await call(aid, p['prompt'], **kwargs)
        except asyncio.CancelledError:
            if sid is not None: await ctx.bridge.stop(self.module, sid)
            raise
        if self.module=='agents': ctx.add_cost(result.get('cost_usd'))
        if result.get('is_error'): raise StepError(result.get('error') or 'Agent failed')
        out = {'result': result['text'], 'session_id': result['session_id']}
        if self.module=='agents': out.update(structured=result.get('structured'), cost_usd=result.get('cost_usd') or 0)
        return out


class TempTask(AgentCard):
    id = 'builtin.temp_task'
    name = 'Temporary task'
    inputs = [PROMPT, Input('cwd', label='Working directory', placeholder='Leave empty to use the temporary agent default'),
              *CLAUDE_INPUTS,
              Input('permission_mode', 'select', 'Permission mode', default='', advanced=True,
                    options=['', 'default', 'acceptEdits', 'plan', 'bypassPermissions', 'dontAsk', 'auto']),
              Input('allowed_tools', label='Allowed tools', advanced=True, placeholder='Comma separated'),
              Input('disallowed_tools', label='Disallowed tools', advanced=True, placeholder='Comma separated'),
              Input('add_dirs', label='Additional directories', advanced=True, placeholder='Commas or newlines'),
              Input('max_turns', 'number', 'Max turns', advanced=True),
              Input('max_budget_usd', 'number', 'Budget limit (USD)', advanced=True),
              Input('env', 'json', 'Environment variables', multiline=True, advanced=True), SESSION]


class AgentTask(AgentCard):
    id = 'builtin.agent_task'
    name = 'Agent task'
    inputs = [Input('agent', 'agent', 'Agent', required=True), PROMPT, SESSION, *CLAUDE_INPUTS]


class MoreAgentTask(AgentCard):
    id = 'builtin.more_agent_task'
    name = 'More Agents agent task'
    module = 'more_agents'
    inputs = [Input('agent', 'more_agent', 'Agent', required=True), PROMPT, Input('cwd', label='Working directory'), Input('model', label='Model', advanced=True), Input('effort', 'select', 'Reasoning effort', advanced=True, default='', options=['', 'low', 'medium', 'high', 'xhigh', 'max']), SESSION]
    outputs = [Output('result', default=True), Output('session_id')]
