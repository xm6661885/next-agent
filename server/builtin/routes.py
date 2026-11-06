"""Authenticated task endpoints."""
from fastapi import APIRouter, Depends


def router(core, builtin):
    api = APIRouter(prefix='/api/builtin', dependencies=[Depends(core.require)])
    @api.get('/tasks')
    async def tasks(session_id: str):
        return builtin.collab.listing({'module': 'agents', 'session_id': session_id})

    return api
