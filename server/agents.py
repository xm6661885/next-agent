"""Agent configuration and computed status."""
import re
import secrets
import shutil
from pathlib import Path
from fastapi import HTTPException
from .config import Agent, GROUPS, TempAgent, TEMP_AGENT, effective

class AgentService:
    def __init__(self, config, index, manager, paths):
        self.config, self.index, self.manager, self.paths = config, index, manager, paths

    def get(self, aid):
        if aid == TEMP_AGENT: return self.manager.agent(aid)
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
        return {**agent.model_dump(), 'effective':effective(agent,self.config.config.defaults), 'status': status}

    def list(self):
        return [self.view(a) for a in sorted(self.config.config.agents, key=lambda a:(a.order,a.created_at))]

    async def changed(self, aid):
        self.manager.global_emit({'type':'agents_changed'})
        self.manager.reconfigure(aid or None)
        await self.manager.extensions.emit('agent_changed', agent_id=aid)

    async def create(self, data):
        data = dict(data)
        data.pop('status', None)
        data.pop('effective', None)
        if not data.get('name') or not data.get('cwd'):
            raise HTTPException(422, 'name and cwd are required')
        if not data.get('id'):
            # Non-ASCII names derive nothing; fall back to a random id instead of a fixed one that collides.
            data['id'] = re.sub(r'[^a-z0-9]+', '-', data['name'].lower()).strip('-')[:40] or 'agent-' + secrets.token_hex(3)
        elif not re.fullmatch(r'[a-z0-9-]{1,40}', data['id']):
            raise HTTPException(422, 'id must be 1-40 characters of a-z, 0-9 and -')
        if any(a.id == data['id'] for a in self.config.config.agents):
            raise HTTPException(409, 'Agent id already exists')
        self.check_group(data)
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
        data.pop('effective', None)
        if aid == TEMP_AGENT:
            for key in ('id','cwd','order','created_at'): data.pop(key,None)
            from pydantic import ValidationError
            import tomlkit
            try:
                current=self.config.config.temp_agent or TempAgent()
                updated=TempAgent.model_validate({**current.model_dump(), **data})
            except ValidationError as exc:
                raise HTTPException(422,str(exc)) from exc
            if 'temp_agent' not in self.config.doc: self.config.doc['temp_agent']=tomlkit.table()
            dumped=updated.model_dump(mode='json')
            for key in data:
                if key in TempAgent.model_fields: self.config.doc['temp_agent'][key]=dumped[key]
            for group in set(current.override_groups) - set(updated.override_groups):
                for key in GROUPS.get(group, ()): self.config.doc['temp_agent'].pop(key, None)
            self.config.save()
            await self.changed(aid)
            return self.view(self.get(aid))
        if 'id' in data and data['id'] != aid:
            raise HTTPException(400, 'Agent id is immutable')
        data.pop('id', None)
        self.check_group(data)
        from pydantic import ValidationError
        try:
            updated = Agent.model_validate({**agent.model_dump(), **data})
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        entry = next(e for e in self.config.doc['agents'] if e['id'] == aid)
        for key, value in updated.model_dump(mode='json').items():
            if key in data:
                entry[key] = value
        # A group that stops overriding drops its values so the entry follows the global defaults again.
        for group in set(agent.override_groups) - set(updated.override_groups):
            for key in GROUPS.get(group, ()):
                if key in entry: del entry[key]
        self.config.save()
        await self.changed(aid)
        return self.view(self.get(aid))

    async def delete(self, aid):
        if aid == TEMP_AGENT: raise HTTPException(400,'Temporary agent cannot be deleted')
        self.get(aid)
        for sid, session in list(self.index.sessions.items()):
            if session['agent_id'] == aid:
                await self.manager.stop(sid)
                del self.index.sessions[sid]
                self.manager.runtimes.pop(sid, None)
                for fid, upload in list(self.index.uploads.items()):
                    if upload['session_id'] == sid:
                        Path(upload['path']).unlink(missing_ok=True)
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

    def check_group(self, data):
        if data.get('group') and data['group'] not in self.config.config.groups:
            raise HTTPException(422, 'Unknown group')

    def groups(self):
        return self.config.config.groups

    async def set_groups(self, groups, renames=None):
        """Replace the group list. renames maps old name -> new name; agents in a dropped group become ungrouped."""
        import tomlkit
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise HTTPException(422, 'groups must be a list of strings')
        groups = [g.strip() for g in groups]
        if any(not g or len(g) > 40 for g in groups) or len(groups) != len(set(groups)):
            raise HTTPException(422, 'group names must be unique, non-empty and at most 40 characters')
        renames = renames or {}
        if not isinstance(renames, dict): raise HTTPException(422, 'renames must be an object')
        for entry in self.config.doc.get('agents', []):
            group = entry.get('group', '')
            if not group: continue
            group = renames.get(group, group)
            entry['group'] = group if group in groups else ''
        self.config.doc['groups'] = tomlkit.array(groups) if groups else tomlkit.array()
        self.config.save()
        await self.changed('')
        return self.groups()

    def md_path(self, agent):
        if agent.id == TEMP_AGENT: raise HTTPException(400,'Temporary agent has no managed CLAUDE.md')
        return (self.paths.agents / agent.id / 'CLAUDE.md') if agent.claude_md == 'custom' else __import__('pathlib').Path(agent.cwd) / 'CLAUDE.md'
