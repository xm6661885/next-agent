"""Public More Agents API; kinds own transports, runtimes own session work."""
import asyncio
import re
import secrets
import time
from pathlib import Path
import tomlkit
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from .config import Agent, MoreAgentsConfig
from .runtime import SessionRuntime
from .kinds.acp.adapter import AcpKind
from .kinds.codex.adapter import CodexKind

class MoreAgentsManager:
    def __init__(self, core, config, store):
        self.core, self.config, self.store = core, config, store
        self.runtimes = {}
        self.info = {}
        self.registry = {'acp': AcpKind(self), 'codex': CodexKind(self)}

    async def startup(self):
        for sid in self.store.sessions: self.session_state(sid)

    def agent(self, aid):
        agent = next((a for a in self.config.data.agents if a.id==aid), None)
        if not agent: raise HTTPException(404, 'Agent not found')
        return agent

    def session(self, sid):
        if sid not in self.store.sessions: raise HTTPException(404, 'Session not found')
        return self.store.sessions[sid]

    def runtime(self, sid):
        self.session(sid)
        if sid not in self.runtimes: self.runtimes[sid] = SessionRuntime(self, sid)
        return self.runtimes[sid]

    def view(self, sid):
        runtime = self.runtimes.get(sid)
        return {**self.session(sid), 'state': runtime.state if runtime else 'offline', 'pending': len(runtime.permissions)+len(runtime.questions) if runtime else 0}

    def items(self, sid):
        self.session(sid)
        return self.runtime(sid).items.items

    def agent_view(self, agent):
        sessions = sorted((s for s in self.store.sessions.values() if s['agent_id']==agent.id), key=lambda s: s['updated_at'], reverse=True)
        runtimes = [self.runtimes[s['id']] for s in sessions if s['id'] in self.runtimes]
        status = dict(running=sum(r.state in ('running', 'interrupting') for r in runtimes),
                      live=sum(r.adapter.connected for r in runtimes),
                      pending=sum(len(r.permissions)+len(r.questions) for r in runtimes),
                      last_session={k: sessions[0][k] for k in ('id', 'title', 'updated_at', 'preview')} if sessions else None)
        return {**agent.model_dump(), 'status': status, 'info': self.info.get(agent.id),
                'capabilities': self.kind(agent.kind).capabilities, 'recent': [self.view(s['id']) for s in sessions[:5]]}

    def agents(self):
        return [self.agent_view(a) for a in sorted(self.config.data.agents, key=lambda a: (a.order, a.created_at))]

    def session_state(self, sid):
        session = self.view(sid)
        self.core.emit({'type': 'session_state', 'module': 'more_agents', 'session_id': sid,
                        **{k: session[k] for k in ('agent_id', 'state', 'pending', 'unread', 'title', 'updated_at', 'preview')}})

    def changed_event(self):
        self.core.emit({'type': 'more_agents_changed'})

    async def changed(self):
        for sid in list(self.store.sessions):
            if self.store.sessions[sid]['agent_id'] not in {a.id for a in self.config.data.agents}: await self.delete_session(sid)
        self.changed_event()

    def kind(self, name): return self.registry[name]

    def kinds(self):
        return [dict(kind='acp', name='ACP', description='Remote ACP endpoint over TCP'),
                dict(kind='codex', name='Codex', description='Native Codex app-server')]

    def sessions(self): return [self.view(sid) for sid in self.store.sessions]

    def running(self):
        rows = []
        for session in self.sessions():
            if session['state'] not in ('running', 'interrupting') and not session['pending']: continue
            agent = self.agent(session['agent_id'])
            rows.append(dict(module='more_agents', session_id=session['id'], agent_name=agent.name, avatar=agent.avatar,
                             **{k: session[k] for k in ('agent_id','title','state','pending','unread','updated_at','preview','cwd')}))
        return rows

    async def models(self, aid):
        agent = self.agent(aid)
        return await self.kind(agent.kind).models(agent)

    def cached_models(self, aid):
        agent = self.agent(aid)
        return self.kind('codex').cached_models(aid) if agent.kind == 'codex' else []

    async def test(self, aid):
        agent = self.agent(aid)
        return await self.kind(agent.kind).test(agent)

    def prepare(self, sid):
        runtime = self.runtime(sid)
        if runtime.warm_future is None or runtime.warm_future.done():
            runtime.warm_future = runtime.submit('prepare')
        return runtime.warm_future

    def create_session(self, aid, title='', origin='ui', parent=None, *, cwd=None):
        agent = self.agent(aid)
        cwd = agent.cwd if cwd is None else cwd
        if not isinstance(cwd, str) or not cwd.strip(): raise HTTPException(400, 'cwd must be a non-empty path')
        if agent.kind == 'codex':
            try: path = Path(cwd).expanduser().resolve()
            except (OSError, RuntimeError, ValueError) as exc: raise HTTPException(400, 'cwd must be an existing directory') from exc
            if not path.is_dir(): raise HTTPException(400, 'cwd must be an existing directory')
            cwd = str(path)
        session = self.store.create(aid, title, origin, parent, kind=agent.kind, cwd=cwd)
        self.session_state(session['id'])
        self.prepare(session['id'])
        return self.view(session['id'])

    def _turn(self, aid, prompt, *, cwd=None, session_id=None, title='', origin='workflow', parent=None,
              model='', effort='', on_session=None):
        self.agent(aid)
        if session_id:
            if self.session(session_id)['agent_id'] != aid: raise ValueError('Session belongs to another agent')
        else:
            if not cwd: raise ValueError('cwd is required for a new More Agents session')
            session_id = self.create_session(aid, title, origin, parent, cwd=cwd)['id']
        if on_session: on_session(session_id)
        future = self.runtime(session_id).enqueue(prompt, steer=False, model=model, effort=effort)
        return session_id, future

    async def run_turn(self, agent_id, prompt, **kwargs):
        sid, future = self._turn(agent_id, prompt, **kwargs)
        return await asyncio.shield(future)

    def start_turn(self, agent_id, prompt, *, origin='subagent', **kwargs):
        return self._turn(agent_id, prompt, origin=origin, **kwargs)[0]

    async def wait_turn(self, sid):
        future = self.runtime(sid).last_future
        if future is None: raise ValueError('No turn has been submitted')
        return await asyncio.shield(future)

    async def set_option(self, sid, id, value):
        await self.runtime(sid).submit('set_config', dict(config_id=id, value=value))

    async def set_mode(self, sid, id):
        await self.runtime(sid).submit('set_mode', dict(mode_id=id))

    async def send(self, session_id, prompt):
        self.runtime(session_id).enqueue(prompt)

    async def stop(self, session_id):
        await self.runtime(session_id).submit('interrupt')

    async def sleep(self, sid):
        runtime = self.runtime(sid)
        if runtime.active or runtime.queued or runtime.state not in ('offline', 'idle'): raise HTTPException(409, 'Session is running')
        await runtime.submit('sleep')
        return self.view(sid)

    async def connect(self, sid, fresh=False):
        runtime = self.runtime(sid)
        if fresh and (runtime.active or runtime.queued or runtime.state not in ('offline', 'idle')):
            raise HTTPException(409, 'Session is running')
        await runtime.submit('reconnect' if fresh else 'connect')
        return self.view(sid)

    def mark_read(self, sid):
        if self.session(sid)['unread']:
            self.store.update(sid, unread=False)
            if sid in self.runtimes: self.runtimes[sid].emit({'type': 'session', 'session': self.view(sid)})
            self.session_state(sid)
        return self.view(sid)

    async def delete_session(self, sid):
        self.session(sid)
        if sid in self.runtimes: await self.runtimes[sid].close()
        self.runtimes.pop(sid, None)
        self.store.delete(sid)
        self.changed_event()

    async def reaper(self):
        while True:
            await asyncio.sleep(30)
            timeout = self.config.data.server.idle_timeout_min*60
            if timeout:
                for runtime in list(self.runtimes.values()):
                    if runtime.state=='idle' and not runtime.queued and time.monotonic()-runtime.last_activity>timeout:
                        try: await runtime.submit('sleep')
                        except HTTPException: pass

    async def close(self):
        await asyncio.gather(*(runtime.close() for runtime in self.runtimes.values()))
        await asyncio.gather(*(kind.shutdown() for kind in self.registry.values()))

    async def create_agent(self, data):
        data = dict(data)
        if not data.get('id'):
            if not isinstance(data.get('name'), str): raise HTTPException(422, 'name is required')
            data['id'] = re.sub(r'[^a-z0-9]+', '-', data['name'].lower()).strip('-')[:40] or 'agent-'+secrets.token_hex(3)
        try: agent = TypeAdapter(Agent).validate_python(data)
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        if any(a.id==agent.id for a in self.config.data.agents): raise HTTPException(409, 'Agent id already exists')
        if agent.group and agent.group not in self.config.data.groups: raise HTTPException(422, 'Unknown group')
        if 'agents' not in self.config.doc: self.config.doc['agents'] = tomlkit.aot()
        self.config.doc['agents'].append(tomlkit.item(agent.model_dump()))
        self.config.save()
        self.changed_event()
        return self.agent_view(self.agent(agent.id))

    async def patch_agent(self, aid, data):
        agent = self.agent(aid)
        data = {k: v for k, v in data.items() if k in type(agent).model_fields}
        if data.get('id', aid)!=aid: raise HTTPException(400, 'Agent id is immutable')
        if data.get('kind', agent.kind)!=agent.kind: raise HTTPException(400, 'Agent kind is immutable')
        if data.get('token') is None: data.pop('token', None)
        data.pop('created_at', None)
        try: updated = TypeAdapter(Agent).validate_python({**agent.model_dump(), **data})
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        if updated.group and updated.group not in self.config.data.groups: raise HTTPException(422, 'Unknown group')
        entry = next(e for e in self.config.doc['agents'] if e['id']==aid)
        for key in data: entry[key] = getattr(updated, key)
        self.config.save()
        self.changed_event()
        return self.agent_view(self.agent(aid))

    async def delete_agent(self, aid):
        self.agent(aid)
        for sid, session in list(self.store.sessions.items()):
            if session['agent_id']==aid: await self.delete_session(sid)
        entries = self.config.doc['agents']
        for i, entry in enumerate(entries):
            if entry['id']==aid:
                del entries[i]
                break
        self.config.save()
        (self.store.avatars / aid).unlink(missing_ok=True)
        (self.store.avatars / (aid+'.mime')).unlink(missing_ok=True)
        self.info.pop(aid, None)
        self.changed_event()

    def reorder(self, ids):
        actual = {a.id for a in self.config.data.agents}
        if len(ids)!=len(actual) or set(ids)!=actual: raise HTTPException(400, 'ids must contain every agent exactly once')
        for entry in self.config.doc.get('agents', []): entry['order'] = ids.index(entry['id'])
        self.config.save()
        self.changed_event()

    def set_groups(self, groups, renames):
        try: groups = MoreAgentsConfig(groups=groups).groups
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        for entry in self.config.doc.get('agents', []):
            group = renames.get(entry.get('group', ''), entry.get('group', ''))
            entry['group'] = group if group in groups else ''
        self.config.doc['groups'] = groups
        self.config.save()
        self.changed_event()
        return groups
