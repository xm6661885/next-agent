"""Workflow routes use core login or the shared server API key."""
import hmac
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from ..config import WorkflowConfig
from . import plugins, runs, workflows

ACTIVE = {'queued', 'starting', 'connecting', 'running', 'interrupting'}


def router(core, manager):
    def require(request: Request):
        scheme, _, key = request.headers.get('authorization', '').partition(' ')
        request.state.workflow_trigger = 'ui'
        if scheme.lower()=='bearer':
            expected = core.claude().api_key
            if not expected or not hmac.compare_digest(key.encode(), expected.encode()):
                raise HTTPException(401, 'Invalid API key')
            request.state.workflow_trigger = 'api'
        else:
            core.require(request)

    api = APIRouter(prefix='/api/workflow', dependencies=[Depends(require)])

    @api.get('/console')
    async def console():
        rows = await manager.db.fetchall("SELECT * FROM runs WHERE status IN ('queued','running','waiting_input') ORDER BY created_at DESC")
        sessions = []
        agents, more_agents = core.modules.get('agents'), core.modules.get('more_agents')
        for module, entries in (('agents', agents.sessions() if agents else []),
                                ('more_agents', list(more_agents.store.sessions.values()) if more_agents else [])):
            for session in entries:
                if session.get('origin')!='workflow': continue
                view = core.bridge.view(module, session['id'])
                if view['state'] in ACTIVE:
                    sessions.append(dict(module=module, session_id=session['id'],
                                         **{k: view[k] for k in ('agent_id', 'title', 'state', 'parent')}))
        return {'runs': [runs._run(r, False) for r in rows], 'sessions': sessions}

    def settings():
        return {**manager.config.data.server.model_dump(), 'env': manager.config.data.env}

    @api.get('/settings')
    async def get_settings(): return settings()

    @api.patch('/settings')
    async def patch_settings(body: dict):
        config = manager.config
        server = {k: v for k, v in body.items() if k!='env'}
        if server.keys() - type(config.data.server).model_fields.keys(): raise HTTPException(422, 'Unknown setting')
        try:
            updated = WorkflowConfig(server={**config.data.server.model_dump(), **server}, env=body.get('env', config.data.env))
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        if 'server' not in config.doc: config.doc['server'] = {}
        for key in server: config.doc['server'][key] = getattr(updated.server, key)
        if 'env' in body:
            if 'env' not in config.doc: config.doc['env'] = {}
            for key in list(config.doc['env']):
                if key not in updated.env: del config.doc['env'][key]
            for key, value in updated.env.items(): config.doc['env'][key] = value
        config.save()
        await config.changed()
        return settings()

    root = APIRouter()
    root.include_router(api)
    for module in (workflows, runs, plugins): root.include_router(module.router(core, manager, require))
    return root
