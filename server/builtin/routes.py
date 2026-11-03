"""Authenticated schedule and task endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from .schedules import ScheduleInput


def router(core, builtin):
    api = APIRouter(prefix='/api/builtin', dependencies=[Depends(core.require)])
    schedules = builtin.schedules

    @api.get('/schedules')
    async def listing(): return list(schedules.entries.values())

    @api.post('/schedules')
    async def create(data: ScheduleInput):
        try: return schedules.create(data.model_dump())
        except (KeyError, ValueError) as exc: raise HTTPException(422, str(exc)) from exc

    def get(sid):
        try: return schedules.get(sid)
        except KeyError as exc: raise HTTPException(404, 'Schedule not found') from exc

    @api.patch('/schedules/{sid}')
    async def patch(sid: str, data: dict):
        get(sid)
        try: return schedules.update(sid, data)
        except (KeyError, ValueError) as exc: raise HTTPException(422, str(exc)) from exc

    @api.delete('/schedules/{sid}')
    async def delete(sid: str):
        get(sid)
        return schedules.delete(sid)

    @api.post('/schedules/{sid}/run')
    async def run(sid: str):
        get(sid)
        try: return await schedules.fire(sid)
        except (KeyError, ValueError) as exc: raise HTTPException(422, str(exc)) from exc
        except Exception as exc: raise HTTPException(502, str(exc)) from exc

    @api.get('/tasks')
    async def tasks(session_id: str):
        return builtin.collab.listing({'module': 'agents', 'session_id': session_id})

    return api
