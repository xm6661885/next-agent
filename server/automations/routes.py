"""Authenticated management API and the public AutoTask webhook contract."""
import asyncio
import hmac
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .config import AutomationsConfig
from .tasks import CreateTask, EditTask, create_fields, edit_fields, list_scripts, view
from .scheduler import compute_next_run
from .timezone import system_timezone_name


class Name(BaseModel):
    name: str


class RunOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    force: bool = False
    extra_args: list[str] = Field(default_factory=list)


def checked(fn, *args):
    try: return fn(*args)
    except (ValueError, sqlite3.IntegrityError) as exc: raise HTTPException(422, str(exc)) from exc


def router(core, manager):
    db, scheduler = manager.db, manager.scheduler
    r = APIRouter(prefix='/api/automations')
    private = APIRouter(dependencies=[Depends(core.require)])

    def task(ref):
        result = db.get_task(int(ref)) if str(ref).isdigit() else db.get_task_by_name(ref)
        if not result: raise HTTPException(404, 'Task not found')
        return result

    def task_view(ref):
        tid = task(ref)['id']
        return view(next(t for t in db.list_tasks() if t['id'] == tid))

    def group(gid):
        result = db.get_group(gid)
        if not result: raise HTTPException(404, 'Group not found')
        return result

    def run(run_id):
        result = db.get_run(run_id)
        if not result: raise HTTPException(404, 'Run not found')
        return result

    @private.get('/tasks')
    def tasks(): return [view(t) for t in db.list_tasks()]

    @private.get('/tasks/status')
    def statuses():
        keys = ('running','enabled','last_run_at','next_run_at','last_exit_code','failure_acked',
                'task_kind','one_off_state','one_off_trigger','scheduled_at')
        return {str(t['id']): {key: view(t)[key] for key in keys} for t in db.list_tasks()}

    @private.get('/tasks/{ref}')
    def detail(ref:str): return task_view(ref)

    @private.get('/tasks/{ref}/status')
    def status(ref:str): return statuses()[str(task(ref)['id'])]

    @private.post('/tasks', status_code=201)
    async def create(body:CreateTask):
        if db.get_task_by_name(body.name.strip()): raise HTTPException(409, 'Task name already exists')
        fields = checked(create_fields, manager.cfg, body)
        tid = db.create_task(**fields)
        fresh = db.get_task(tid)
        db.update_task(tid, next_run_at=compute_next_run(fresh) if fresh['enabled'] else None)
        if fresh['task_kind'] == 'one_off' and fresh['one_off_trigger'] == 'immediate':
            await asyncio.to_thread(scheduler.run_one_off_now, fresh)
        manager.emit()
        return task_view(tid)

    @private.patch('/tasks/{ref}')
    async def edit(ref:str, body:EditTask):
        current = task(ref)
        fields = checked(edit_fields, manager.cfg, current, body)
        db.update_task(current['id'], **fields)
        fresh = db.get_task(current['id'])
        if fields.keys() & {'schedule_type','schedule_value','scheduled_at'}:
            db.update_task(current['id'], next_run_at=compute_next_run(fresh) if fresh['enabled'] else None)
            if fresh['task_kind'] == 'one_off' and fresh['one_off_trigger'] == 'immediate':
                await asyncio.to_thread(scheduler.run_one_off_now, fresh)
        manager.emit()
        return task_view(ref)

    @private.delete('/tasks/{ref}')
    async def delete(ref:str):
        current = task(ref)
        if current['running_pid']: raise HTTPException(409, 'Task is running')
        db.delete_task(current['id']); manager.emit()
        return {'ok':True}

    async def start(current, options):
        one_off = current['task_kind'] == 'one_off'
        if one_off and (options.force or options.extra_args): raise HTTPException(422, 'One-offs do not accept force or extra args')
        if current['running_pid'] and not options.force: raise HTTPException(409, 'Task is running')
        if one_off:
            if current['one_off_state'] in ('completed','failed','cancelled') and not db.requeue_one_off(current['id']):
                raise HTTPException(409, 'One-off state changed')
            rid = await asyncio.to_thread(scheduler.run_one_off_now, current)
            if rid is None: raise HTTPException(409, 'One-off already claimed or cancelled')
        else:
            rid = await asyncio.to_thread(scheduler.run_now, current, options.extra_args)
        manager.emit()
        return {'run_id':rid}

    @private.post('/tasks/{ref}/run')
    async def run_now(ref:str, body:Annotated[RunOptions, Body()] = RunOptions()):
        return await start(task(ref), body)

    @private.post('/tasks/{ref}/start')
    async def start_early(ref:str):
        current = task(ref)
        if current['task_kind'] != 'one_off' or current['one_off_state'] != 'pending':
            raise HTTPException(409, 'Task is not a pending one-off')
        return await start(current, RunOptions())

    @private.post('/tasks/{ref}/run-again')
    async def run_again(ref:str):
        current = task(ref)
        if current['task_kind'] != 'one_off' or current['one_off_state'] not in ('completed','failed','cancelled'):
            raise HTTPException(409, 'Task is not a terminal one-off')
        return await start(current, RunOptions())

    @private.post('/tasks/{ref}/stop')
    async def stop(ref:str):
        if not manager.runner.stop_task(task(ref)): raise HTTPException(409, 'Task is not running or signal failed')
        manager.emit(); return {'ok':True}

    async def set_enabled(ref, enabled):
        current = task(ref)
        if current['task_kind'] == 'one_off': raise HTTPException(409, 'Use cancel for one-off tasks')
        db.update_task(current['id'], enabled=int(enabled))
        fresh = db.get_task(current['id'])
        db.update_task(current['id'], next_run_at=compute_next_run(fresh) if enabled else None)
        manager.emit(); return task_view(ref)

    @private.post('/tasks/{ref}/enable')
    async def enable(ref:str): return await set_enabled(ref, True)

    @private.post('/tasks/{ref}/disable')
    async def disable(ref:str): return await set_enabled(ref, False)

    @private.post('/tasks/{ref}/toggle')
    async def toggle(ref:str): return await set_enabled(ref, not task(ref)['enabled'])

    @private.post('/tasks/{ref}/cancel')
    async def cancel(ref:str):
        if not db.cancel_one_off(task(ref)['id']): raise HTTPException(409, 'Task is not a pending one-off')
        manager.emit(); return {'ok':True}

    @private.get('/tasks/{ref}/runs')
    def task_runs(ref:str, limit:int=Query(50,ge=1,le=200), offset:int=Query(0,ge=0)):
        return db.list_runs(task(ref)['id'],limit,offset)

    @private.get('/runs')
    def recent_runs(limit:int=Query(50,ge=1,le=200), offset:int=Query(0,ge=0)):
        return db.list_runs(limit=limit,offset=offset)

    @private.get('/runs/{run_id}')
    def run_detail(run_id:int): return run(run_id)

    @private.get('/runs/{run_id}/log')
    def log_read(run_id:int, offset:int=Query(0,ge=0)):
        current = run(run_id)
        text, end = '', offset
        path = current['log_path']
        if path and Path(path).is_file():
            with open(path, 'r', errors='replace') as stream:
                stream.seek(offset); text = stream.read(); end = stream.tell()
        return {'text':text, 'offset':end, 'done':current['finished_at'] is not None,
                'exit_code':current['exit_code'], 'finished_at':current['finished_at']}

    @private.get('/failures')
    def failures():
        return [view(t) for t in db.list_tasks() if t['last_run_at'] and not t['running_pid']
                and t['last_exit_code'] != 0 and not t['failure_acked']]

    @private.post('/failures/acknowledge')
    async def acknowledge():
        db.clear_failures(); manager.emit(); return {'ok':True}

    @private.get('/groups')
    def groups(): return db.list_groups()

    @private.post('/groups', status_code=201)
    async def create_group(body:Name):
        gid = checked(db.create_group, body.name); manager.emit(); return db.get_group(gid)

    @private.patch('/groups/{gid}')
    async def rename_group(gid:int, body:Name):
        group(gid); checked(db.rename_group, gid, body.name); manager.emit(); return db.get_group(gid)

    @private.delete('/groups/{gid}')
    async def delete_group(gid:int):
        group(gid); moved = db.delete_group(gid); manager.emit(); return {'moved':moved}

    @private.post('/groups/{gid}/tasks/{ref}')
    async def move(gid:int, ref:str):
        group(gid); db.move_task(task(ref)['id'], gid); manager.emit(); return {'ok':True}

    @private.delete('/tasks/{ref}/group')
    async def ungroup(ref:str):
        db.move_task(task(ref)['id'], None); manager.emit(); return {'ok':True}

    @private.get('/scripts')
    def scripts(): return list_scripts(manager.cfg['scripts_dir'], {t['script'] for t in db.list_tasks()})

    @private.get('/settings')
    def settings():
        return {**manager.cfg, 'config_path':str(manager.config.path),
                'timezone':system_timezone_name(), 'webhook_url':'https://agents.xm728070.dpdns.org/api/automations/webhook/<task>'}

    @private.patch('/settings')
    async def update_settings(body:AutomationsConfig):
        for key in body.model_fields_set: manager.config.doc[key] = getattr(body,key)
        manager.config.save(); await manager.config.changed(); return settings()

    @private.post('/settings/regenerate')
    async def regenerate():
        manager.config.doc['webhook_secret'] = secrets.token_urlsafe(32)
        manager.config.save(); await manager.config.changed(); return settings()

    r.include_router(private)

    @r.post('/webhook/{task_name}')
    async def webhook(task_name:str, request:Request):
        def error(status, message): return JSONResponse({'success':False,'error':message}, status_code=status)
        current = db.get_task_by_name(task_name)
        if not current: return error(404, 'task not found')
        if current['schedule_type'] != 'webhook': return error(409, 'task is not webhook-triggered')
        if not current['enabled']: return error(403, 'task is disabled')
        authorization = request.headers.get('authorization', '')
        bearer = authorization[7:] if authorization.lower().startswith('bearer ') else ''
        provided = request.headers.get('x-autotask-webhook-secret') or bearer or request.query_params.get('secret','')
        expected = manager.cfg['webhook_secret']
        if not expected or not hmac.compare_digest(provided.encode(), expected.encode()): return error(401, 'invalid webhook secret')
        length = request.headers.get('content-length')
        if length and int(length) > 1048576: return error(413, 'request body too large')
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > 1048576: return error(413, 'request body too large')
        payload = bytes(payload)
        try: decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError): return error(400, 'request body must be valid JSON')
        if not isinstance(decoded, dict): return error(400, 'request body must be a JSON object')
        if current['running_pid']:
            return JSONResponse({'success':True,'skipped':'task is already running','task_name':task_name}, status_code=202)
        rid = await asyncio.to_thread(scheduler.run_webhook, current, payload)
        manager.emit()
        return JSONResponse({'success':True,'run_id':rid,'task_name':task_name}, status_code=202)
    return r
