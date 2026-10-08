"""Agent configuration and computed status."""
import re
import shutil
from fastapi import HTTPException
from .config import Agent

class AgentService:
    def __init__(self, config, index, manager, paths):
        self.config, self.index, self.manager, self.paths = config, index, manager, paths

    def get(self, aid):
        agent = next((a for a in self.config.config.agents if a.id == aid), None)
        if not agent:
            raise HTTPException(404, 'Agent not found')
        return agent

    def view(self, agent):
        sessions = [s for s in self.index.sessions.values() if s['agent_id'] == agent.id]
        sessions.sort(key=lambda s: s['updated_at'], reverse=True)
        runtimes = [self.manager.runtimes.get(s['id']) for s in sessions]
        status = dict(running=sum(bool(r and r.state in ('running','interrupting')) for r in runtimes),
                      live=sum(bool(r and r.state in ('starting','idle','running','interrupting')) for r in runtimes),
                      pending=sum(len(r.permissions.pending) for r in runtimes if r),
                      last_session=({k: sessions[0][k] for k in ('id','title','updated_at','preview')} if sessions else None))
        return {**agent.model_dump(), 'status': status}

    def list(self):
        return [self.view(a) for a in sorted(self.config.config.agents, key=lambda a:(a.order,a.created_at))]

    async def changed(self, aid):
        self.manager.global_emit({'type':'agents_changed'})
        await self.manager.extensions.emit('agent_changed', agent_id=aid)

    async def create(self, data):
        data = dict(data)
        data.pop('status', None)
        if not data.get('name') or not data.get('cwd'):
            raise HTTPException(422, 'name and cwd are required')
        data.setdefault('id', re.sub(r'[^a-z0-9]+', '-', data['name'].lower()).strip('-')[:40] or 'agent')
        if any(a.id == data['id'] for a in self.config.config.agents):
            raise HTTPException(409, 'Agent id already exists')
        from pydantic import ValidationError
        try:
            agent = Agent.model_validate(data)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        self.config.doc.add('agents', []) if 'agents' not in self.config.doc else None
        import tomlkit
        self.config.doc['agents'].append(tomlkit.item(agent.model_dump(mode='json')))
        self.config.save()
        await self.changed(agent.id)
        return self.view(self.get(agent.id))

    async def patch(self, aid, data):
        agent = self.get(aid)
        data = dict(data)
        data.pop('status', None)
        if 'id' in data and data['id'] != aid:
            raise HTTPException(400, 'Agent id is immutable')
        data.pop('id', None)
        from pydantic import ValidationError
        try:
            updated = Agent.model_validate({**agent.model_dump(), **data})
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        entry = next(e for e in self.config.doc['agents'] if e['id'] == aid)
        for key, value in updated.model_dump(mode='json').items():
            if key in data:
                entry[key] = value
        self.config.save()
        await self.changed(aid)
        return self.view(self.get(aid))

    async def delete(self, aid):
        self.get(aid)
        for sid, session in list(self.index.sessions.items()):
            if session['agent_id'] == aid:
                await self.manager.stop(sid)
                del self.index.sessions[sid]
                self.manager.runtimes.pop(sid, None)
                for fid, upload in list(self.index.uploads.items()):
                    if upload['session_id'] == sid:
                        del self.index.uploads[fid]
                shutil.rmtree(self.paths.uploads / sid, ignore_errors=True)
        self.index.save()
        arr = self.config.doc['agents']
        for i, entry in enumerate(arr):
            if entry['id'] == aid:
                del arr[i]
                break
        self.config.save()
        await self.changed(aid)

    async def reorder(self, ids):
        actual = {a.id for a in self.config.config.agents}
        if len(ids) != len(actual) or set(ids) != actual:
            raise HTTPException(400, 'ids must contain every agent exactly once')
        for entry in self.config.doc['agents']:
            entry['order'] = ids.index(entry['id'])
        self.config.save()
        await self.changed('')

    def md_path(self, agent):
        return (self.paths.agents / agent.id / 'CLAUDE.md') if agent.claude_md == 'custom' else __import__('pathlib').Path(agent.cwd) / 'CLAUDE.md'
