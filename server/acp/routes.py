"""Authenticated ACP HTTP and WebSocket endpoints."""
import asyncio
from contextlib import suppress
from typing import Literal
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from ..paths import atomic_write
from .client import AcpConnection
from .store import page
from .config import AcpServer


class Title(BaseModel):
    title: str = ''


class Reorder(BaseModel):
    ids: list[str]


class Groups(BaseModel):
    groups: list[str]
    renames: dict[str, str] = Field(default_factory=dict)


class Command(BaseModel):
    type: Literal['resume', 'ping', 'send', 'cancel_queued', 'interrupt', 'permission_reply', 'set_config', 'set_mode']
    seq: int | None = Field(default=None, ge=0)
    req_id: str | int | None = None
    client_id: str | None = None
    text: str = ''
    attachments: list[str] = Field(default_factory=list)
    id: str | None = None
    option_id: str | None = None
    config_id: str | None = None
    value: str | None = None
    mode_id: str | None = None


async def session_socket(ws, sid, core, manager):
    if not await core.auth.require_ws(ws): return
    await ws.accept()
    if sid not in manager.store.sessions:
        await ws.close(code=4404)
        return
    runtime = manager.runtime(sid)
    queue = asyncio.Queue(maxsize=1000)
    runtime.subscribers.add(queue)
    runtime.viewers += 1
    manager.mark_read(sid)
    sender = None
    controls = set()

    async def resume(seq):
        ring = list(runtime.ring)
        baseline = runtime.seq
        if seq and ring and ring[0]['seq']-1<=seq<=baseline:
            for event in ring:
                if event['seq']>seq: await ws.send_json(event)
        else: await ws.send_json(runtime.snapshot())
        await ws.send_json({'type': 'resumed', 'seq': baseline})
        return baseline

    async def send_events(baseline):
        while True:
            event = await queue.get()
            if event.get('type')=='__overflow__':
                await ws.close(code=1013)
                return
            if event['seq']>baseline: await ws.send_json(event)

    async def control(typ, payload, req_id):
        try: await asyncio.shield(runtime.submit(typ, payload))
        except Exception as exc:
            with suppress(WebSocketDisconnect, RuntimeError):
                await ws.send_json({'type': 'error', 'seq': runtime.seq, 'req_id': req_id, 'message': str(exc)})

    try:
        first = Command.model_validate(await ws.receive_json())
        if first.type!='resume':
            await ws.send_json({'type': 'error', 'seq': runtime.seq, 'message': 'First message must be resume'})
            return
        baseline = await resume(first.seq)
        sender = asyncio.create_task(send_events(baseline))
        while True:
            req_id = None
            try:
                raw = await ws.receive_json()
                if isinstance(raw, dict): req_id = raw.get('req_id')
                message = Command.model_validate(raw)
                typ = message.type
                if typ=='resume':
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
                    baseline = await resume(message.seq)
                    sender = asyncio.create_task(send_events(baseline))
                elif typ=='ping': await ws.send_json({'type': 'pong', 'seq': runtime.seq})
                elif typ=='send':
                    attachments = [manager.store.attachment(sid, fid) for fid in message.attachments]
                    runtime.enqueue(message.text, attachments, message.client_id)
                elif typ=='permission_reply':
                    if not message.id: raise ValueError('id is required')
                    runtime.reply_permission(message.id, message.option_id)
                else:
                    payload = None
                    if typ=='cancel_queued':
                        if not message.id: raise ValueError('id is required')
                        payload = message.id
                    elif typ=='set_config':
                        if message.config_id is None or message.value is None: raise ValueError('config_id and value are required')
                        payload = {'config_id': message.config_id, 'value': message.value}
                    elif typ=='set_mode':
                        if message.mode_id is None: raise ValueError('mode_id is required')
                        payload = {'mode_id': message.mode_id}
                    task = asyncio.create_task(control(typ, payload, message.req_id))
                    controls.add(task)
                    task.add_done_callback(controls.discard)
            except (ValueError, HTTPException) as exc:
                await ws.send_json({'type': 'error', 'seq': runtime.seq, 'req_id': req_id,
                                    'message': exc.detail if isinstance(exc, HTTPException) else str(exc)})
    except (WebSocketDisconnect, RuntimeError): pass
    except (ValueError, ValidationError):
        await ws.close(code=1008)
    finally:
        runtime.viewers -= 1
        runtime.subscribers.discard(queue)
        if sender:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)


def router(core, manager):
    api = APIRouter(dependencies=[Depends(core.require)])

    @api.get('/api/acp/agents')
    async def agents(): return manager.agents()

    @api.post('/api/acp/agents')
    async def create_agent(body: dict): return await manager.create_agent(body)

    @api.post('/api/acp/agents/reorder')
    async def reorder(body: Reorder):
        manager.reorder(body.ids)
        return {'ok': True}

    @api.get('/api/acp/groups')
    async def groups(): return {'groups': manager.config.data.groups}

    @api.put('/api/acp/groups')
    async def set_groups(body: Groups): return {'groups': manager.set_groups(body.groups, body.renames)}

    @api.get('/api/acp/settings')
    async def settings(): return manager.config.data.server.model_dump()

    @api.patch('/api/acp/settings')
    async def set_settings(body: AcpServer):
        if 'server' not in manager.config.doc: manager.config.doc['server'] = {}
        manager.config.doc['server']['idle_timeout_min'] = body.idle_timeout_min
        manager.config.save()
        return manager.config.data.server.model_dump()

    @api.get('/api/acp/agents/{aid}')
    async def agent(aid: str): return manager.agent_view(manager.agent(aid))

    @api.patch('/api/acp/agents/{aid}')
    async def patch_agent(aid: str, body: dict): return await manager.patch_agent(aid, body)

    @api.delete('/api/acp/agents/{aid}')
    async def delete_agent(aid: str):
        await manager.delete_agent(aid)
        return {'ok': True}

    @api.get('/api/acp/agents/{aid}/avatar')
    async def avatar(aid: str):
        manager.agent(aid)
        path = manager.store.avatars / aid
        if not path.exists(): raise HTTPException(404, 'Avatar not found')
        mime = (manager.store.avatars / (aid+'.mime')).read_text()
        return FileResponse(path, media_type=mime)

    @api.post('/api/acp/agents/{aid}/avatar')
    async def avatar_upload(aid: str, file: UploadFile = File(...)):
        manager.agent(aid)
        if file.content_type not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
            raise HTTPException(415, 'Unsupported avatar type')
        data = await file.read(2*1024*1024+1)
        if len(data)>2*1024*1024: raise HTTPException(413, 'Avatar is too large')
        atomic_write(manager.store.avatars / aid, data)
        atomic_write(manager.store.avatars / (aid+'.mime'), file.content_type)
        return await manager.patch_agent(aid, {'avatar': 'file'})

    @api.post('/api/acp/agents/{aid}/test')
    async def test_agent(aid: str):
        agent = manager.agent(aid)
        connection = AcpConnection()
        try:
            async with asyncio.timeout(10):
                await connection.open(agent.host, agent.port, agent.token)
                await connection.initialize(core.version)
                manager.info[aid] = connection.info
                manager.changed_event()
                result = await connection.request('session/new', {'cwd': agent.cwd, 'mcpServers': []})
                await connection.close()
                return {'ok': True, 'info': connection.info, 'config_options': result.get('configOptions', [])}
        except Exception as exc:
            return {'ok': False, 'info': connection.info, 'config_options': [], 'error': str(exc) or 'Connection test timed out'}
        finally: await connection.close()

    @api.get('/api/acp/agents/{aid}/sessions')
    async def sessions(aid: str):
        manager.agent(aid)
        return sorted((manager.view(s['id']) for s in manager.store.sessions.values() if s['agent_id']==aid), key=lambda s: s['updated_at'], reverse=True)

    @api.post('/api/acp/agents/{aid}/sessions')
    async def create_session(aid: str, body: Title = Title()): return manager.create_session(aid, body.title)

    @api.get('/api/acp/agents/{aid}/search')
    async def search(aid: str, q: str = ''):
        manager.agent(aid)
        if not q.strip(): return []
        results = []
        for session in sorted(manager.store.sessions.values(), key=lambda s: s['updated_at'], reverse=True):
            if session['agent_id']!=aid: continue
            for item in manager.store.load_items(session['id']):
                text = item.get('text', '') or (item.get('result') or {}).get('content', '')
                at = text.lower().find(q.lower())
                if at>=0:
                    results.append({'session': manager.view(session['id']), 'snippet': text[max(0, at-60):at+140]})
                    break
        return results

    @api.get('/api/acp/sessions/{sid}')
    async def session(sid: str): return manager.view(sid)

    @api.patch('/api/acp/sessions/{sid}')
    async def patch_session(sid: str, body: Title):
        manager.session(sid)
        if 'title' in body.model_fields_set:
            if sid in manager.runtimes: manager.runtimes[sid].session_changed(title=body.title)
            else:
                manager.store.update(sid, title=body.title)
                manager.session_state(sid)
        return manager.view(sid)

    @api.delete('/api/acp/sessions/{sid}')
    async def delete_session(sid: str):
        await manager.delete_session(sid)
        return {'ok': True}

    @api.post('/api/acp/sessions/{sid}/read')
    async def read(sid: str): return manager.mark_read(sid)

    @api.post('/api/acp/sessions/{sid}/sleep')
    async def sleep(sid: str): return await manager.sleep(sid)

    @api.get('/api/acp/sessions/{sid}/items')
    async def items(sid: str, before: str | None = None, limit: int = Query(default=200, ge=1, le=200)):
        return page(manager.items(sid), before, limit)

    @api.post('/api/acp/sessions/{sid}/uploads')
    async def uploads(sid: str, files: list[UploadFile] = File(...)):
        manager.session(sid)
        return [await manager.store.upload(sid, file) for file in files]

    @api.get('/api/acp/uploads/{sid}/{fid}')
    async def upload(sid: str, fid: str):
        manager.session(sid)
        attachment = manager.store.attachment(sid, fid)
        return FileResponse(attachment['path'], media_type=attachment['mime'], filename=attachment['name'])

    sockets = APIRouter()

    @sockets.websocket('/ws/acp/{sid}')
    async def socket(ws: WebSocket, sid: str): await session_socket(ws, sid, core, manager)

    sockets.include_router(api)
    return sockets
