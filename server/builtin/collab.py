"""Collaboration tasks, linked durably through session parents."""
import asyncio
from typing import Literal
from uuid import uuid4
from pydantic import Field
from . import Input, Prompt, epoch, mcp_tool


class CreateTask(Prompt):
    module: Literal['agents', 'more_agents']
    agent_id: str = Field(min_length=1)
    title: str = ''
    wait: bool = False
    model: str = ''
    effort: str = ''
    cwd: str = ''


class TaskId(Input):
    task_id: str = Field(min_length=1)


class SendTask(Prompt, TaskId):
    pass


def last_text(items):
    return next((i['text'][:4000] for i in reversed(items) if i['kind']=='text' and not i.get('parent_tool_use_id')), '')


def recovered_result(items):
    end = next((i for i in reversed(items) if i['kind']=='result'), None)
    if end is None: return None
    start = max((i+1 for i, value in enumerate(items) if value['kind']=='user' and not value.get('parent_tool_use_id')), default=0)
    text = '\n\n'.join(i['text'] for i in items[start:] if i['kind']=='text' and not i.get('parent_tool_use_id'))
    error = bool(end.get('is_error') or end.get('stop_reason') in ('error', 'disconnected'))
    return dict(text=text, stop_reason=end.get('stop_reason','completed'), is_error=error, error='Turn failed' if error else None)


class Collab:
    def __init__(self, builtin):
        self.builtin = builtin
        self.tasks = {}

    def agents_list(self, caller):
        more_agents = self.builtin.core.modules.get('more_agents')
        groups = [('agents', self.builtin.agents.agents()), ('more_agents', more_agents.config.data.agents if more_agents else [])]
        rows=[]
        for module, agents in groups:
            for a in agents:
                if not a.as_subagent or (module, a.id)==(caller['module'], caller['agent_id']): continue
                row=dict(module=module, agent_id=a.id, name=a.name, description=a.description, kind=('claude' if module=='agents' else a.kind), needs_cwd=(module=='more_agents'))
                if module=='more_agents' and a.kind=='codex':
                    models=self.builtin.core.modules['more_agents'].models(a.id)
                    if models: row['models']=[dict(id=m.get('id') or m.get('model'), name=m.get('displayName') or m.get('name') or m.get('id'), efforts=m.get('supportedReasoningEfforts') or [], default_effort=m.get('defaultReasoningEffort') or '') for m in models]
                rows.append(row)
        return rows

    def get(self, task_id, caller):
        row = self.tasks.get(task_id)
        if row is None:
            for module in ('agents', 'more_agents'):
                for session in self.builtin.sessions(module):
                    parent = session.get('parent') or {}
                    if parent.get('task_id')!=task_id or parent.get('module')!='agents' or parent.get('session_id')!=caller['session_id']: continue
                    items = self.builtin.core.bridge.items(module, session['id'])
                    state = self.builtin.core.bridge.view(module, session['id'])['state']
                    row = dict(owner=caller['session_id'], version=0, task=dict(task_id=task_id, module=module,
                        agent_id=session['agent_id'], session_id=session['id'], title=session['title'],
                        created_at=epoch(session['created_at']),
                        result=recovered_result(items) if state in ('idle', 'offline') else None))
                    self.tasks[task_id] = row
                    break
        if row is None or row['owner']!=caller['session_id']: raise ValueError('Task not found for this session')
        return row

    def view(self, row):
        task = row['task']
        session = self.builtin.core.bridge.view(task['module'], task['session_id'])
        return {**task, 'state': session['state'], 'title': session['title']}

    async def finish(self, row, future, version):
        try: result = await future
        except Exception as exc: result = dict(text='', is_error=True, error=str(exc))
        if row['version']==version:
            row['task']['result'] = dict(text=result.get('text', ''), stop_reason=result.get('stop_reason','completed'), is_error=result.get('is_error', False), error=result.get('error'))

    def watch(self, row, future):
        row['version'] += 1
        row['task']['result'] = None
        return self.builtin.background(self.finish(row, future, row['version']))

    async def create(self, caller, args):
        if not any((a['module'], a['agent_id'])==(args.module, args.agent_id) for a in self.agents_list(caller)):
            raise ValueError('Agent is not available as a subagent')
        tid = 't_'+uuid4().hex[:12]
        parent = dict(module='agents', session_id=caller['session_id'], task_id=tid)
        if args.module == 'agents' and args.cwd: raise ValueError('cwd is only valid for More Agents')
        if args.module == 'more_agents' and not args.cwd: raise ValueError('cwd is required for More Agents tasks')
        sid, future = await self.builtin.start(args.module, args.agent_id, args.prompt, title=args.title,
            origin='subagent', parent=parent, model=args.model, effort=args.effort, cwd=args.cwd or None)
        session = self.builtin.core.bridge.view(args.module, sid)
        row = dict(owner=caller['session_id'], version=0, task=dict(task_id=tid, module=args.module,
            agent_id=args.agent_id, session_id=sid, title=session['title'],
            result=None, created_at=epoch(session['created_at'])))
        self.tasks[tid] = row
        finished = self.watch(row, future)
        if args.wait: await asyncio.shield(finished)
        return self.view(row)

    def listing(self, caller):
        ids = [tid for tid, row in self.tasks.items() if row['owner']==caller['session_id']]
        for module in ('agents', 'more_agents'):
            for session in self.builtin.sessions(module):
                parent = session.get('parent') or {}
                if parent.get('module')=='agents' and parent.get('session_id')==caller['session_id'] and parent.get('task_id'):
                    ids.append(parent['task_id'])
        return [self.view(self.get(tid, caller)) for tid in dict.fromkeys(ids)]

    def tools(self, caller):
        async def agents(args): return self.agents_list(caller)
        async def create(args): return await self.create(caller, args)
        async def status(args):
            row = self.get(args.task_id, caller)
            task = self.view(row)
            return {**task, 'last_text': last_text(self.builtin.core.bridge.items(task['module'], task['session_id']))}
        async def send(args):
            row = self.get(args.task_id, caller)
            task = row['task']
            future = await self.builtin.send(task['module'], task['session_id'], args.prompt)
            self.watch(row, future)
            return self.view(row)
        async def stop(args):
            row = self.get(args.task_id, caller)
            task = row['task']
            await self.builtin.core.bridge.stop(task['module'], task['session_id'])
            return self.view(row)
        async def listing(args): return self.listing(caller)
        return [mcp_tool('agents_list', 'List other agents available for collaboration.', Input, agents),
                mcp_tool('task_create', 'Start a subagent task, optionally waiting for its result.', CreateTask, create),
                mcp_tool('task_status', 'Get a task started by this session and its last assistant text.', TaskId, status),
                mcp_tool('task_send', 'Send a follow-up prompt to a task started by this session.', SendTask, send),
                mcp_tool('task_stop', 'Interrupt a task started by this session.', TaskId, stop),
                mcp_tool('task_list', 'List tasks started by this session.', Input, listing)]
