"""Session-scoped, in-process MCP tools."""
import asyncio
import json
from datetime import datetime

from claude_agent_sdk import create_sdk_mcp_server, tool
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Prompt(Input):
    prompt: str = Field(min_length=1)

    @field_validator('prompt')
    @classmethod
    def nonempty(cls, value):
        if not value.strip(): raise ValueError('prompt is required')
        return value


def epoch(value):
    return datetime.fromisoformat(value).timestamp()


def mcp_tool(name, description, schema, handler):
    async def call(arguments):
        try:
            result = await handler(schema.model_validate(arguments))
            return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}
        except Exception as exc:
            message = exc.detail if isinstance(exc, HTTPException) else str(exc)
            return {'content': [{'type': 'text', 'text': json.dumps({'error': message})}], 'is_error': True}
    return tool(name, description, schema.model_json_schema())(call)


class Builtin:
    def __init__(self, core):
        from .schedules import Schedules
        from .collab import Collab
        self.core = core
        self.pending = set()
        self.schedules = Schedules(self)
        self.collab = Collab(self)

    @property
    def agents(self):
        return self.core.modules['agents']

    def categories_for(self, agent, session):
        switches = {**self.agents.settings(), **agent.builtin_mcp}
        if not switches.get('enabled', False): return ()
        return tuple(name for name in ('schedules', 'history', 'collab') if switches.get(name, True)
                     and (name!='collab' or session.get('origin')!='subagent'))

    @staticmethod
    def allowed_tools(categories):
        names = {'schedules': ('schedule_create', 'schedule_list', 'schedule_delete'),
                 'history': ('history_list', 'history_search', 'history_read'),
                 'collab': ('agents_list', 'task_create', 'task_status', 'task_send', 'task_stop', 'task_list')}
        return ['mcp__next__'+name for category in categories for name in names[category]]

    def servers_for(self, agent, session):
        from .history_tools import history_tools
        categories = self.categories_for(agent, session)
        if not categories: return {}
        caller = dict(module='agents', agent_id=agent.id, session_id=session['id'])
        factories = {'schedules': self.schedules.tools, 'history': lambda c: history_tools(self, c),
                     'collab': self.collab.tools}
        tools = [tool for category in categories for tool in factories[category](caller)]
        return {'next': create_sdk_mcp_server('next', tools=tools)}

    def agent(self, module, aid):
        agents = self.agents.agents() if module=='agents' else self.core.modules['more_agents'].config.data.agents
        agent = next((a for a in agents if a.id==aid), None)
        if agent is None: raise ValueError('Target agent not found')
        return agent

    def sessions(self, module):
        if module=='agents': return self.agents.sessions()
        more_agents = self.core.modules.get('more_agents')
        return list(more_agents.store.sessions.values()) if more_agents else []

    def target(self, module, aid, sid=None):
        self.agent(module, aid)
        if sid and sid!='new':
            session = self.core.bridge.view(module, sid)
            if session['agent_id']!=aid: raise ValueError('Session belongs to another agent')

    def background(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)
        return task

    async def start(self, module, aid, prompt, *, session_id=None, title='', origin, parent=None, model='', effort='', cwd=None):
        self.target(module, aid, session_id)
        if module == 'agents':
            if cwd is not None: raise ValueError('cwd is only valid for More Agents')
            sid = self.core.bridge.start_claude(aid, prompt, overrides={'model': model, 'effort': effort},
                                                session_id=session_id, title=title, origin=origin, parent=parent)
            return sid, self.background(self.core.bridge.wait_claude(sid))
        if session_id is None and not cwd: raise ValueError('cwd is required for a new More Agents session')
        more = self.core.modules['more_agents']
        if session_id is None:
            created = more.create_session(aid, title, origin, parent, cwd=cwd)
            session_id = created['id']
        await more.prepare(session_id)
        sid = self.core.bridge.start_more(aid, prompt, cwd=cwd or self.core.bridge.view(module, session_id)['cwd'],
                                          session_id=session_id, title=title, origin=origin, parent=parent,
                                          model=model, effort=effort)
        return sid, self.background(self.core.bridge.wait_more(sid))

    async def send(self, module, sid, prompt):
        if module == 'agents':
            await self.core.bridge.send(module, sid, prompt)
            return self.background(self.core.bridge.wait_claude(sid))
        await self.core.bridge.send('more_agents', sid, prompt)
        return self.background(self.core.bridge.wait_more(sid))

    async def close(self):
        tasks = list(self.pending)
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def mount(app, core):
    from .routes import router
    module = Builtin(core)
    core.modules['builtin'] = module
    app.include_router(router(core, module))
    core.background(module.schedules.run)
    core.on_shutdown(module.close)
