"""Authenticated Chat REST and WebSocket endpoints."""
import asyncio
from typing import Literal
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from ..paths import atomic_write
from . import providers
from .config import Effort, McpServer, Provider
from .store import IMAGE_MIMES, page
from .resources import FileName, MemoryText


class ConfigPatch(BaseModel):
    defaults: dict = Field(default_factory=dict)
    profile: dict = Field(default_factory=dict)
    titles: dict = Field(default_factory=dict)
    files: dict = Field(default_factory=dict)
    memory: dict = Field(default_factory=dict)
    providers: list[Provider] = Field(default_factory=list)
    mcp_servers: dict[str, McpServer] = Field(default_factory=dict)


class Overrides(BaseModel):
    model: str | None = None
    effort: Literal['', 'off', 'low', 'medium', 'high', 'max'] | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=-1, le=2, allow_inf_nan=False)
    max_tokens: int | None = Field(default=None, ge=0)


class SessionPatch(BaseModel):
    title: str = ''
    overrides: Overrides = Field(default_factory=Overrides)
    mcp: list[str] = Field(default_factory=list)


class Title(BaseModel):
    title: str = ''


class Reorder(BaseModel):
    ids: list[str]


class Command(BaseModel):
    type: Literal['resume', 'ping', 'send', 'stop', 'edit', 'regenerate', 'edit_reply', 'switch', 'set_model', 'set_effort', 'set_mcp']
    seq: int | None = Field(default=None, ge=0)
    req_id: str | int | None = None
    client_id: str | None = None
    text: str = ''
    attachments: list[str] = Field(default_factory=list)
    uuid: str | None = None
    id: str | None = None
    key: str | None = None
    index: int | None = None
    model: str | None = None
    effort: Effort | Literal[''] | None = None
    mcp: list[str] | None = None


def patch_session(manager, sid, body):
    session = manager.session(sid)
    changes = body.model_dump(exclude_unset=True)
    if 'overrides' in changes: changes['overrides'] = {**session['overrides'], **changes['overrides']}
    if 'mcp' in changes: changes['mcp'] = list(dict.fromkeys(changes['mcp']))
    return manager.update_session(sid, **changes)


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

    async def resume(seq):
        ring, baseline = list(runtime.ring), runtime.seq
        if seq and ring and ring[0]['seq']-1<=seq<=baseline:
            for event in ring:
                if event['seq']>seq: await ws.send_json(event)
        else: await ws.send_json(runtime.snapshot())
        await ws.send_json({'type': 'resumed', 'seq': baseline})
        return baseline

    async def send_events(baseline):
        while True:
            event = await queue.get()
            if event['type']=='__overflow__':
                await ws.close(code=1013)
                return
            if event['seq']>baseline: await ws.send_json(event)

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
                elif typ in ('send', 'edit'):
                    if typ=='edit' and not message.uuid: raise ValueError('uuid is required')
                    runtime.idle()
                    attachments = [manager.store.attachment(sid, fid) for fid in message.attachments]
                    runtime.send(message.text, attachments, message.client_id, message.uuid if typ=='edit' else None)
                elif typ=='regenerate': runtime.regenerate(message.uuid)
                elif typ=='edit_reply':
                    if message.id is None: raise ValueError('id is required')
                    runtime.edit_reply(message.id, message.text)
                elif typ=='switch':
                    if message.key is None or message.index is None: raise ValueError('key and index are required')
                    runtime.switch(message.key, message.index)
                elif typ=='stop': await asyncio.shield(runtime.stop())
                else:
                    field = typ[4:]
                    value = getattr(message, field)
                    if value is None: raise ValueError(field+' is required')
                    body = {'mcp': value} if field=='mcp' else {'overrides': {field: value or None}}
                    patch_session(manager, sid, SessionPatch.model_validate(body))
            except (ValueError, HTTPException) as exc:
                await ws.send_json({'type': 'error', 'seq': runtime.seq, 'req_id': req_id,
                                    'message': exc.detail if isinstance(exc, HTTPException) else str(exc)})
    except (WebSocketDisconnect, RuntimeError): pass
    except ValueError: await ws.close(code=1008)
    finally:
        runtime.viewers -= 1
        runtime.subscribers.discard(queue)
        if sender:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)


def router(core, manager):
    api = APIRouter(dependencies=[Depends(core.require)])

    @api.get('/api/chat/meta')
    async def meta():
        config = manager.config.data
        return dict(models=[dict(id=p.id+'/'+m, provider=p.id, model=m, format=p.format) for p in config.providers for m in p.models],
                    efforts=['off', 'low', 'medium', 'high', 'max'], defaults=config.defaults.model_dump(),
                    mcp_servers=list(config.mcp_servers), profile=config.profile.model_dump())

    @api.get('/api/chat/config')
    async def config(): return manager.config_view()

    @api.patch('/api/chat/config')
    async def update_config(body: ConfigPatch): return manager.patch_config(body)

    @api.post('/api/chat/providers/models')
    async def provider_models(body: Provider):
        if not body.api_key:
            body.api_key = next((p.api_key for p in manager.config.data.providers if p.id==body.id), '')
        try: return {'models': await providers.list_models(body)}
        except (providers.ProviderError, httpx.HTTPError) as exc: raise HTTPException(502, str(exc)) from exc

    @api.post('/api/chat/providers/{pid}/test')
    async def test_provider(pid: str):
        provider = next((p for p in manager.config.data.providers if p.id==pid), None)
        if provider is None: raise HTTPException(404, 'Provider not found')
        return await providers.test(provider)

    @api.get('/api/chat/profile/avatar')
    async def profile_avatar():
        path = manager.store.avatars / '_user'
        if not path.exists(): raise HTTPException(404, 'Avatar not found')
        return FileResponse(path, media_type=(manager.store.avatars / '_user.mime').read_text())

    @api.post('/api/chat/profile/avatar')
    async def upload_profile_avatar(file: UploadFile = File(...)):
        if file.content_type not in IMAGE_MIMES: raise HTTPException(415, 'Unsupported avatar type')
        content = await file.read(2*1024*1024+1)
        if len(content)>2*1024*1024: raise HTTPException(413, 'Avatar is too large')
        atomic_write(manager.store.avatars / '_user', content)
        atomic_write(manager.store.avatars / '_user.mime', file.content_type)
        return {'profile': manager.patch_config(ConfigPatch(profile={'avatar': 'file'}))['profile']}

    @api.get('/api/chat/assistants')
    async def assistants(): return manager.assistants()

    @api.post('/api/chat/assistants')
    async def create_assistant(body: dict): return manager.create_assistant(body)

    @api.post('/api/chat/assistants/reorder')
    async def reorder(body: Reorder):
        manager.reorder(body.ids)
        return {'ok': True}

    @api.get('/api/chat/assistants/{aid}')
    async def assistant(aid: str): return manager.assistant_view(aid)

    @api.patch('/api/chat/assistants/{aid}')
    async def update_assistant(aid: str, body: dict): return manager.patch_assistant(aid, body)

    @api.delete('/api/chat/assistants/{aid}')
    async def delete_assistant(aid: str):
        await manager.delete_assistant(aid)
        return {'ok': True}

    @api.get('/api/chat/assistants/{aid}/avatar')
    async def avatar(aid: str):
        manager.assistant(aid)
        path = manager.store.avatars / aid
        if not path.exists(): raise HTTPException(404, 'Avatar not found')
        return FileResponse(path, media_type=(manager.store.avatars / (aid+'.mime')).read_text())

    @api.post('/api/chat/assistants/{aid}/avatar')
    async def upload_avatar(aid: str, file: UploadFile = File(...)):
        manager.assistant(aid)
        if file.content_type not in IMAGE_MIMES: raise HTTPException(415, 'Unsupported avatar type')
        content = await file.read(2*1024*1024+1)
        if len(content)>2*1024*1024: raise HTTPException(413, 'Avatar is too large')
        atomic_write(manager.store.avatars / aid, content)
        atomic_write(manager.store.avatars / (aid+'.mime'), file.content_type)
        return manager.patch_assistant(aid, {'avatar': 'file'})

    @api.get('/api/chat/assistants/{aid}/files')
    async def files(aid: str):
        manager.assistant(aid)
        return manager.resources.files(aid)

    @api.post('/api/chat/assistants/{aid}/files')
    async def add_files(aid: str, files: list[UploadFile] = File(...)):
        manager.assistant(aid)
        return await manager.resources.upload(aid, files)

    @api.get('/api/chat/assistants/{aid}/files/{fid}')
    async def file(aid: str, fid: str):
        manager.assistant(aid)
        record = manager.resources.file(aid, fid)
        return FileResponse(manager.resources.file_dir(aid) / fid, media_type='text/plain', filename=record['name'])

    @api.patch('/api/chat/assistants/{aid}/files/{fid}')
    async def rename_file(aid: str, fid: str, body: FileName):
        manager.assistant(aid)
        return manager.resources.rename(aid, fid, body.name)

    @api.delete('/api/chat/assistants/{aid}/files/{fid}')
    async def delete_file(aid: str, fid: str):
        manager.assistant(aid)
        manager.resources.delete_file(aid, fid)
        return {'ok': True}

    @api.get('/api/chat/assistants/{aid}/memory')
    async def memories(aid: str):
        manager.assistant(aid)
        return manager.resources.memories(aid)

    @api.post('/api/chat/assistants/{aid}/memory')
    async def add_memory(aid: str, body: MemoryText):
        manager.assistant(aid)
        record = manager.resources.add_memory(aid, body.text, 'user')
        manager.memory_changed(aid)
        return record

    @api.patch('/api/chat/assistants/{aid}/memory/{mid}')
    async def update_memory(aid: str, mid: str, body: MemoryText):
        manager.assistant(aid)
        record = manager.resources.update_memory(aid, mid, body.text)
        manager.memory_changed(aid)
        return record

    @api.delete('/api/chat/assistants/{aid}/memory/{mid}')
    async def delete_memory(aid: str, mid: str):
        manager.assistant(aid)
        manager.resources.delete_memory(aid, mid)
        manager.memory_changed(aid)
        return {'ok': True}

    @api.delete('/api/chat/assistants/{aid}/memory')
    async def clear_memory(aid: str):
        manager.assistant(aid)
        manager.resources.save_memories(aid, [])
        manager.memory_changed(aid)
        return {'ok': True}

    @api.get('/api/chat/assistants/{aid}/sessions')
    async def sessions(aid: str): return manager.sessions(aid)

    @api.post('/api/chat/assistants/{aid}/sessions')
    async def create_session(aid: str, body: Title = Title()): return manager.create_session(aid, body.title)

    @api.get('/api/chat/assistants/{aid}/search')
    async def search(aid: str, q: str = ''): return manager.search(aid, q)

    @api.get('/api/chat/sessions/{sid}')
    async def session(sid: str): return manager.view(sid)

    @api.patch('/api/chat/sessions/{sid}')
    async def update_session(sid: str, body: SessionPatch): return patch_session(manager, sid, body)

    @api.delete('/api/chat/sessions/{sid}')
    async def delete_session(sid: str):
        await manager.delete_session(sid)
        return {'ok': True}

    @api.post('/api/chat/sessions/{sid}/read')
    async def read(sid: str): return manager.mark_read(sid)

    @api.get('/api/chat/sessions/{sid}/items')
    async def items(sid: str, before: str | None = None, limit: int = Query(default=200, ge=1, le=200)):
        return page(manager.items(sid), before, limit)

    @api.post('/api/chat/sessions/{sid}/uploads')
    async def uploads(sid: str, files: list[UploadFile] = File(...)):
        session = manager.session(sid)
        enabled = manager.enabled(session['assistant_id'], 'files')
        return [await manager.store.upload(sid, file, enabled) for file in files]

    @api.get('/api/chat/uploads/{sid}/{fid}')
    async def upload(sid: str, fid: str):
        manager.session(sid)
        attachment = manager.store.attachment(sid, fid)
        return FileResponse(attachment['path'], media_type=attachment['mime'], filename=attachment['name'])

    sockets = APIRouter()

    @sockets.websocket('/ws/chat/{sid}')
    async def socket(ws: WebSocket, sid: str): await session_socket(ws, sid, core, manager)

    sockets.include_router(api)
    return sockets
