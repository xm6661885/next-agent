"""FastAPI application factory."""
import asyncio
import os
import mimetypes
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from urllib.parse import unquote
import bcrypt
import hmac
from fastapi import FastAPI, Request, Response, HTTPException, Depends, UploadFile, File, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from claude_agent_sdk import list_sessions
from .paths import DataDir, atomic_write
from .config import ConfigStore, Agent, now
from .store import SessionIndex
from .auth import Auth, COOKIE, AGE
from .agents import AgentService
from .uploads import UploadService
from .extensions import ExtensionBus
from .runtime import RuntimeManager
from .history import load_items, page, transcript_path, search_sessions
from .ws import session_socket, events_socket

MODELS=['','opus','sonnet','haiku','opus[1m]','claude-opus-5-5','claude-sonnet-5-5','claude-fable-5-1']
EFFORTS=['','low','medium','high','xhigh','max']
MODES=['default','acceptEdits','plan','bypassPermissions','dontAsk','auto']

class CachedAssets(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response

def create_app(data_dir=None):
    paths=DataDir(data_dir)
    config=ConfigStore(paths)
    index=SessionIndex(paths)
    auth=Auth(paths,config)
    extensions=ExtensionBus(config)
    manager=RuntimeManager(paths,config,index,extensions)
    agents=AgentService(config,index,manager,paths)
    uploads=UploadService(paths,index)
    async def config_changed():
        if hasattr(manager.semaphore,'resize'):
            manager.semaphore.resize(config.config.server.max_concurrent)
        else:
            manager.semaphore=asyncio.Semaphore(config.config.server.max_concurrent)
        manager.global_emit({'type':'agents_changed'})
    @asynccontextmanager
    async def lifespan(app):
        manager.reaper_task=asyncio.create_task(manager.reaper())
        watcher=asyncio.create_task(config.watch(config_changed))
        yield
        watcher.cancel()
        await manager.shutdown()
    app=FastAPI(lifespan=lifespan)
    app.state.paths=paths
    app.state.config=config
    app.state.index=index
    app.state.manager=manager
    app.state.auth=auth
    app.state.agents=agents
    app.state.uploads=uploads
    require=auth.require_auth

    @app.post('/api/login')
    async def login(request:Request):
        body=await request.json()
        auth.check_login(request,body.get('password',''))
        response=JSONResponse({'ok':True})
        response.set_cookie(COOKIE,auth.token(),max_age=AGE,httponly=True,samesite='lax',
                            secure=request.headers.get('x-forwarded-proto')=='https')
        return response
    @app.post('/api/logout')
    async def logout(_:None=Depends(require)):
        response=JSONResponse({'ok':True})
        response.delete_cookie(COOKIE)
        return response
    @app.api_route('/api/external/send',methods=['GET','POST'])
    async def external_send(request:Request):
        params=dict(request.query_params)
        if request.method=='POST':
            if 'json' in request.headers.get('content-type',''):
                body=await request.json()
                if isinstance(body,dict): params.update({k:str(v) for k,v in body.items() if v is not None})
            else: params.update({k:v for k,v in (await request.form()).items() if isinstance(v,str)})
        expected=config.config.server.api_key
        key=params.get('key') or request.headers.get('x-api-key','')
        if not expected: raise HTTPException(403,'External API is disabled')
        if not hmac.compare_digest(key.encode(),expected.encode()): raise HTTPException(401,'Invalid key')
        prompt=params.get('prompt','').strip()
        if not prompt: raise HTTPException(400,'prompt is required')
        try: sid=manager.external_send(params.get('agent_id',''),prompt,params.get('session_id') or None)
        except (KeyError,StopIteration): raise HTTPException(404,'Unknown agent or session')
        return PlainTextResponse('Message Sent',headers={'X-Session-Id':sid})
    @app.get('/api/me')
    async def me(_:None=Depends(require)): return {'authenticated':True}
    @app.get('/api/agents')
    async def agents_list(_:None=Depends(require)): return agents.list()
    @app.post('/api/agents')
    async def agents_create(request:Request,_:None=Depends(require)):
        return await agents.create(await request.json())
    @app.post('/api/agents/reorder')
    async def agents_reorder(request:Request,_:None=Depends(require)):
        await agents.reorder((await request.json())['ids'])
        return {'ok':True}
    @app.get('/api/agents/{aid}')
    async def agent_get(aid:str,_:None=Depends(require)): return agents.view(agents.get(aid))
    @app.patch('/api/agents/{aid}')
    async def agent_patch(aid:str,request:Request,_:None=Depends(require)):
        return await agents.patch(aid,await request.json())
    @app.delete('/api/agents/{aid}')
    async def agent_delete(aid:str,_:None=Depends(require)):
        await agents.delete(aid)
        return {'ok':True}
    @app.get('/api/agents/{aid}/claude-md')
    async def md_get(aid:str,_:None=Depends(require)):
        path=agents.md_path(agents.get(aid))
        return {'content':path.read_text() if path.exists() else '', 'path':str(path),'exists':path.exists()}
    @app.put('/api/agents/{aid}/claude-md')
    async def md_put(aid:str,request:Request,_:None=Depends(require)):
        path=agents.md_path(agents.get(aid))
        content=(await request.json()).get('content','')
        atomic_write(path,content)
        return {'content':content,'path':str(path),'exists':True}
    @app.get('/api/agents/{aid}/avatar')
    async def avatar_get(aid:str,_:None=Depends(require)):
        agents.get(aid)
        files=list((paths.agents/aid).glob('avatar.*'))
        if not files: raise HTTPException(404,'Avatar not found')
        return FileResponse(files[0])
    @app.post('/api/agents/{aid}/avatar')
    async def avatar_post(aid:str,file:UploadFile=File(...),_:None=Depends(require)):
        agents.get(aid)
        ext={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','image/gif':'.gif'}.get(file.content_type)
        if not ext: raise HTTPException(415,'Unsupported avatar type')
        data=await file.read(2*1024*1024+1)
        if len(data)>2*1024*1024: raise HTTPException(413,'Avatar is too large')
        directory=paths.agents/aid
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        for old in directory.glob('avatar.*'): old.unlink()
        atomic_write(directory/('avatar'+ext),data)
        return await agents.patch(aid,{'avatar':'file'})
    @app.get('/api/agents/{aid}/sessions')
    async def agent_sessions(aid:str,_:None=Depends(require)):
        agents.get(aid)
        return [manager.view(s['id']) for s in sorted(index.sessions.values(),key=lambda x:x['updated_at'],reverse=True) if s['agent_id']==aid]
    @app.get('/api/agents/{aid}/search')
    async def agent_search(aid:str,q:str='',limit:int=50,_:None=Depends(require)):
        agent=agents.get(aid)
        q=q.strip()
        if not q: return []
        own=sorted((s for s in index.sessions.values() if s['agent_id']==aid),key=lambda x:x['updated_at'],reverse=True)
        hits=await asyncio.to_thread(search_sessions,own,agent.cwd,q,max(1,min(limit,200)))
        return [{'session':manager.view(sid),'snippet':snippet} for sid,snippet in hits]
    @app.post('/api/agents/{aid}/sessions')
    async def session_create(aid:str,request:Request,_:None=Depends(require)):
        agents.get(aid)
        data=await request.json()
        created=index.create(aid,data.get('title',''))
        manager.session_state(manager.get_or_create(created['id']))
        return manager.view(created['id'])
    @app.get('/api/agents/{aid}/importable')
    async def importable(aid:str,_:None=Depends(require)):
        agent=agents.get(aid)
        existing={s['sdk_session_id'] for s in index.sessions.values()}
        return [{'sdk_session_id':s.session_id,'summary':s.summary,'first_prompt':s.first_prompt,
                 'last_modified':s.last_modified,'git_branch':s.git_branch} for s in await asyncio.to_thread(list_sessions,directory=agent.cwd)
                 if s.session_id not in existing]
    @app.post('/api/agents/{aid}/import')
    async def import_sessions(aid:str,request:Request,_:None=Depends(require)):
        agent=agents.get(aid)
        ids=(await request.json()).get('sdk_session_ids',[])
        available={s.session_id:s for s in await asyncio.to_thread(list_sessions,directory=agent.cwd)}
        output=[]
        for sdk_id in ids:
            if sdk_id not in available: raise HTTPException(404,f'Session {sdk_id} not found')
            if sdk_id in index.sessions: continue
            source=available[sdk_id]
            title=(source.custom_title or source.summary or source.first_prompt or '')[:60]
            session=index.create(aid,title,sdk_session_id=sdk_id,imported=True)
            index.sessions.pop(session['id'])
            session['id']=sdk_id
            index.sessions[sdk_id]=session
            index.save()
            output.append(manager.view(sdk_id))
        return output
    def session(sid):
        if sid not in index.sessions: raise HTTPException(404,'Session not found')
        return index.sessions[sid]
    @app.get('/api/sessions/{sid}')
    async def session_get(sid:str,_:None=Depends(require)):
        session(sid)
        return manager.view(sid)
    @app.patch('/api/sessions/{sid}')
    async def session_patch(sid:str,request:Request,_:None=Depends(require)):
        original=session(sid)
        data=await request.json()
        values={}
        if 'title' in data: values['title']=str(data['title'])
        if 'overrides' in data:
            values['overrides']={**original['overrides'],**{k:v for k,v in data['overrides'].items() if k in original['overrides']}}
        index.update(sid,**values)
        runtime=manager.runtimes.get(sid)
        if runtime:
            runtime.emit({'type':'session','session':manager.view(sid)})
            manager.session_state(runtime)
        else:
            manager.session_state(manager.get_or_create(sid))
        return manager.view(sid)
    async def delete_session(sid,purge):
        original=session(sid)
        await manager.stop(sid)
        if purge and original.get('sdk_session_id'):
            path=transcript_path(original['sdk_session_id'],agents.get(original['agent_id']).cwd)
            if path: path.unlink(missing_ok=True)
        shutil.rmtree(paths.uploads/sid,ignore_errors=True)
        for fid,record in list(index.uploads.items()):
            if record['session_id']==sid: del index.uploads[fid]
        del index.sessions[sid]
        manager.runtimes.pop(sid,None)
    @app.delete('/api/sessions/{sid}')
    async def session_delete(sid:str,purge:int=0,_:None=Depends(require)):
        await delete_session(sid,purge)
        index.save()
        return {'ok':True}
    @app.post('/api/sessions/delete')
    async def sessions_delete(request:Request,_:None=Depends(require)):
        body=await request.json()
        ids=[sid for sid in dict.fromkeys(body.get('ids',[])) if sid in index.sessions]
        for sid in ids: await delete_session(sid,bool(body.get('purge')))
        index.save()
        return {'ok':True,'deleted':ids}
    @app.post('/api/sessions/{sid}/sleep')
    async def session_sleep(sid:str,_:None=Depends(require)):
        session(sid)
        await manager.stop(sid)
        return manager.view(sid)
    @app.post('/api/sessions/{sid}/fork')
    async def session_fork(sid:str,request:Request,_:None=Depends(require)):
        source=session(sid)
        body=await request.json()
        fork=index.create(source['agent_id'],source['title']+' (fork)',fork_of={'session_id':sid,'at_uuid':body.get('at_uuid')})
        return manager.view(fork['id'])
    @app.get('/api/sessions/{sid}/items')
    async def session_items(sid:str,before:str|None=None,limit:int=200,_:None=Depends(require)):
        session(sid)
        runtime=manager.get_or_create(sid)
        snap=await runtime.snapshot()
        if before or limit!=200:
            return page(await runtime.all_items(),before,limit)
        return {'items':snap['items'],'has_more':snap['has_more']}
    async def shared_file(sid,path):
        session(sid)
        normalized=os.path.normpath(path)
        if not os.path.isabs(normalized): raise HTTPException(404,'File not found')
        runtime=manager.get_or_create(sid)
        items=await runtime.all_items()
        key=(len(items),items[-1]['id'] if items else None)
        if not runtime.file_refs_cache or runtime.file_refs_cache[0]!=key:
            refs={os.path.normpath(unquote(match)) for entry in items if entry['kind']=='text'
                  for match in re.findall(r'file://(/[^\s)"\'<>\]]+)',entry.get('text',''))}
            runtime.file_refs_cache=(key,refs)
        if normalized not in runtime.file_refs_cache[1] or not os.path.isfile(normalized):
            raise HTTPException(404,'File not found')
        mime=mimetypes.guess_type(normalized)[0] or 'application/octet-stream'
        return normalized,mime
    @app.get('/api/sessions/{sid}/files/stat')
    async def file_stat(sid:str,path:str,_:None=Depends(require)):
        file,mime=await shared_file(sid,path)
        return {'name':os.path.basename(file),'size':os.path.getsize(file),'mime':mime,
                'is_image':mime.startswith('image/') and mime!='image/svg+xml'}
    @app.get('/api/sessions/{sid}/files')
    async def file_get(sid:str,path:str,download:int=0,_:None=Depends(require)):
        file,mime=await shared_file(sid,path)
        unsafe=mime in ('text/html','image/svg+xml','application/xhtml+xml') and not download
        response=FileResponse(file,media_type='text/plain' if unsafe else mime,filename=os.path.basename(file),
                              content_disposition_type='attachment' if download else 'inline')
        if unsafe: response.headers['X-Content-Type-Options']='nosniff'
        return response
    @app.post('/api/sessions/{sid}/uploads')
    async def upload_files(sid:str,files:list[UploadFile]=File(...),_:None=Depends(require)):
        session(sid)
        return [await uploads.save(sid,file) for file in files]
    @app.get('/api/uploads/{sid}/{fid}')
    async def upload_get(sid:str,fid:str,_:None=Depends(require)):
        record=uploads.get(sid,fid)
        return FileResponse(record['path'],media_type=record['mime'],filename=record['name'],content_disposition_type='inline')
    @app.get('/api/status')
    async def status(_:None=Depends(require)):
        return {'live':sum(r.state in ('starting','idle','running','interrupting') for r in manager.runtimes.values()),
                'max_concurrent':config.config.server.max_concurrent,
                'queued':sum(r.state=='queued' for r in manager.runtimes.values()),
                'sessions':[{'id':s['id'],'agent_id':s['agent_id'],'state':manager.view(s['id'])['state'],
                             'pending':manager.view(s['id'])['pending']} for s in index.sessions.values()],
                'memory_mb':manager.memory_mb()}
    @app.get('/api/meta')
    async def meta(_:None=Depends(require)):
        return {'models':list(dict.fromkeys(MODELS+config.config.defaults.custom_models)),
                'efforts':EFFORTS,'permission_modes':MODES,'version':'0.1.0',
                'defaults':config.config.defaults.model_dump()}
    @app.get('/api/config')
    async def form_get(_:None=Depends(require)): return config.form()
    @app.patch('/api/config')
    async def form_patch(request:Request,_:None=Depends(require)):
        try: config.update_form(await request.json())
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        await config_changed()
        return config.form()
    @app.get('/api/config/raw')
    async def raw_get(_:None=Depends(require)): return {'content':config.masked()}
    @app.put('/api/config/raw')
    async def raw_put(request:Request,_:None=Depends(require)):
        content=(await request.json()).get('content','')
        try:
            doc,model=config.parse(content)
            if model.server.password_hash=='***':
                doc['server']['password_hash']=config.config.server.password_hash
                content=__import__('tomlkit').dumps(doc)
            config.replace_raw(content)
        except Exception as exc: raise HTTPException(400,str(exc)) from exc
        await config_changed()
        return {'content':config.masked()}
    @app.websocket('/ws/sessions/{sid}')
    async def ws_session(ws:WebSocket,sid:str): await session_socket(ws,sid,auth,manager,index,uploads)
    @app.websocket('/ws/events')
    async def ws_events(ws:WebSocket): await events_socket(ws,auth,manager,agents)
    dist=Path(__file__).resolve().parents[1]/'web'/'dist'
    if dist.exists():
        assets=dist/'assets'
        if assets.exists(): app.mount('/assets',CachedAssets(directory=assets),name='assets')
        @app.get('/{path:path}')
        async def spa(path:str):
            if path.startswith(('api/','ws/')): raise HTTPException(404)
            file=dist/path
            if not file.is_file(): file=dist/'index.html'
            response=FileResponse(file)
            if path=='sw.js': response.headers['Cache-Control']='no-cache'
            elif path.startswith('assets/'): response.headers['Cache-Control']='public, max-age=31536000, immutable'
            return response
    return app
