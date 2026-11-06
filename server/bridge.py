"""The session bridge used by Workflow, schedules and collaboration tools."""
import asyncio
from pathlib import Path
from .config import TEMP_AGENT

class AgentBridge:
    def __init__(self, core, manager):
        self.core, self.manager = core, manager; self.tasks=set(); self.more_tasks={}; core.on_shutdown(self.close)
    def _session(self, agent_id, session_id, title, origin, parent, cwd, overrides, extra):
        aid=agent_id or TEMP_AGENT; self.manager.agent(aid); index=self.manager.index
        if session_id:
            session=index.sessions[session_id]
            if session['agent_id']!=aid: raise ValueError('Session belongs to another agent')
            values={}
            if overrides is not None: values['overrides']={**session['overrides'],**overrides}
            if extra is not None: values['extra']=extra
            if values: index.update(session_id,**values)
        else:
            values={}
            if aid==TEMP_AGENT:
                path=Path(cwd or '~').expanduser().resolve()
                if not path.is_dir(): raise ValueError('cwd must be an existing directory')
                values['cwd']=str(path)
            if overrides is not None: values['overrides']={'model':None,'effort':None,'permission_mode':None,**overrides}
            session=index.create(aid,title,origin=origin,parent=parent,extra=extra,**values)
        runtime=self.manager.get_or_create(session['id']); self.manager.session_state(runtime); return session['id']
    async def run_claude(self, agent_id, prompt, *, session_id=None, title='', origin='workflow', parent=None,cwd=None,overrides=None,extra=None,on_session=None):
        sid=self._session(agent_id,session_id,title,origin,parent,cwd,overrides,extra)
        if on_session: on_session(sid)
        return await self.manager.run_turn(sid,prompt)
    def start_claude(self, agent_id, prompt, *, session_id=None, title='', origin='workflow', parent=None,cwd=None,overrides=None,extra=None):
        sid=self._session(agent_id,session_id,title,origin,parent,cwd,overrides,extra); task=asyncio.create_task(self.manager.run_turn(sid,prompt)); self.tasks.add(task); task.add_done_callback(self.tasks.discard); return sid
    async def wait_claude(self, session_id): return await self.manager.wait_turn(session_id)
    def more(self):
        module=self.core.modules.get('more_agents')
        if module is None: raise RuntimeError('More Agents module unavailable')
        return module
    async def run_more(self, agent_id, prompt, *, cwd, session_id=None, title='', origin='workflow', parent=None, model='', effort='', on_session=None):
        module=self.more(); result=await module.run_turn(agent_id,prompt,session_id=session_id,title=title,origin=origin,parent=parent,cwd=cwd,model=model,effort=effort,on_session=on_session)
        return {**dict(is_error=False,error=None),**result}
    def start_more(self, agent_id, prompt, *, cwd, session_id=None, title='', origin='workflow', parent=None, model='', effort='', on_session=None):
        module=self.more(); sid = module.start_turn(agent_id, prompt, session_id=session_id, title=title, origin=origin,
                                                    parent=parent, cwd=cwd, model=model, effort=effort)
        if on_session: on_session(sid)
        task=asyncio.create_task(module.wait_turn(sid)); self.more_tasks[task]=True; task.add_done_callback(self.more_tasks.pop); return sid
    async def wait_more(self, session_id): return await self.more().wait_turn(session_id)
    # Legacy method names remain for in-process callers while they migrate.
    def acp(self): return self.more()
    async def run_acp(self, agent_id, prompt, **kwargs): return await self.run_more(agent_id,prompt,cwd=kwargs.pop('cwd','/'),**kwargs)
    def start_acp(self, agent_id, prompt, **kwargs): return self.start_more(agent_id,prompt,cwd=kwargs.pop('cwd','/'),**kwargs)
    async def send(self,module,session_id,prompt):
        if module=='agents': return self.manager.send(session_id,prompt)
        if module=='more_agents': return self.more().send(session_id,prompt)
        raise ValueError('Unknown module')
    async def stop(self,module,session_id):
        if module=='agents':
            runtime=self.manager.get_or_create(session_id)
            if runtime.state in ('running','interrupting'): runtime.submit(('interrupt',))
            elif runtime.state in ('queued','starting'): await self.manager.stop(session_id)
            return
        if module=='more_agents': return await self.more().stop(session_id)
        raise ValueError('Unknown module')
    def view(self,module,session_id):
        if module=='agents': return self.manager.view(session_id)
        if module=='more_agents': return self.more().view(session_id)
        raise ValueError('Unknown module')
    def items(self,module,session_id):
        if module=='agents':
            runtime=self.manager.get_or_create(session_id); return runtime.history_items()+list(runtime.items.items)
        if module=='more_agents': return self.more().items(session_id)
        raise ValueError('Unknown module')
    async def close(self):
        tasks=list(self.tasks)+list(self.more_tasks)
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
