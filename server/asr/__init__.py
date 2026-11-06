import asyncio, json, os, re, shutil, time
from pathlib import Path
from urllib.parse import quote
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from .config import config_file
from . import transcribe as tr

MAX_CHUNK=20*1024*1024; MAX_UPLOAD=500*1024*1024; PIECE_SEC=60.0

def mount(app, core):
    config=config_file(core); root=core.paths.root/'asr'; recordings=root/'recordings'; recordings.mkdir(parents=True,exist_ok=True)
    tasks={}; locks={}
    def lock(rid): return locks.setdefault(rid,asyncio.Lock())
    def rec_dir(rid):
        if not rid or '/' in rid or '..' in rid or rid.startswith('.'): raise KeyError(rid)
        return recordings/rid
    def load(rid):
        try: return json.loads((rec_dir(rid)/'meta.json').read_text())
        except (FileNotFoundError,ValueError): raise KeyError(rid)
    def save(meta):
        path=rec_dir(meta['id'])/'meta.json'; path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(meta,ensure_ascii=False,separators=(',',':'))); os.replace(tmp,path)
    def joined(m): return '\n'.join(s['text'] for s in sorted(m['segments'],key=lambda s:s['seq']) if s.get('text'))
    def full_text(m): return m['text'] if m.get('text') is not None else joined(m)
    def public(m):
        out={k:v for k,v in m.items() if k!='pending'}; out['edited']=m.get('text') is not None; out['text']=full_text(m); return out
    def summary(m):
        return {k:m.get(k) for k in ('id','title','source','created_at','duration','status','size','starred','error','progress')}|{'preview':full_text(m)[:120]}
    def upsert(m,seg): m['segments']=[s for s in m['segments'] if s['seq']!=seg['seq']]+[seg]; m['segments'].sort(key=lambda s:s['seq'])
    async def update(rid,fn):
        async with lock(rid):
            try: m=load(rid)
            except KeyError: return None
            fn(m); save(m); return m
    def changed(rid,m): core.emit({'type':'asr_changed','module':'asr','id':rid})
    async def stream(req,dst,limit):
        n=0; tmp=dst.with_name(dst.name+'.part')
        try:
            with tmp.open('wb') as f:
                async for chunk in req.stream():
                    n+=len(chunk)
                    if n>limit: raise HTTPException(413,'file too large')
                    f.write(chunk)
        except BaseException: tmp.unlink(missing_ok=True); raise
        if not n: tmp.unlink(missing_ok=True); raise HTTPException(400,'empty body')
        tmp.replace(dst); return n
    def spawn(rid,coro):
        old=tasks.get(rid)
        if old and not old.done(): old.cancel()
        task=asyncio.create_task(coro); tasks[rid]=task
        task.add_done_callback(lambda t: tasks.get(rid) is t and tasks.pop(rid,None))
    def get(rid):
        try:return load(rid)
        except KeyError:raise HTTPException(404,'not found')
    def tail(m,before=None):
        vals=[s for s in m['segments'] if s.get('text') and (before is None or s['seq']<before)]
        return vals[-1]['text'][-200:] if vals else ''
    async def process_full(rid):
        d=rec_dir(rid); work=d/'work.wav'
        try:
            orig=next(iter(sorted(d.glob('original.*'))),None); src=orig or d/'audio.m4a'
            if not src.exists(): raise tr.TranscribeError('no audio file')
            if not (d/'audio.m4a').exists(): await tr.to_m4a(src,d/'audio.m4a')
            await tr.run('ffmpeg','-nostdin','-y','-v','error','-i',str(src),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(work))
            total=await tr.duration(work) or await tr.duration(src); pieces=await tr.plan_pieces(work,total,PIECE_SEC); size=(d/'audio.m4a').stat().st_size
            def start(m): m.update(duration=total,size=size,segments=[],text=None,error=None,progress={'done':0,'total':len(pieces)}); m['pending']='full'; changed(rid,m)
            if await update(rid,start) is None:return
            prev=''; ok=0
            for i,(a,b) in enumerate(pieces):
                piece=d/f'piece-{i}.wav'; seg={'seq':i,'start':round(a,3),'end':round(b,3),'text':'','status':'ok'}
                try:
                    await tr.slice_wav(work,piece,a,b)
                    if not tr.is_silent(piece): seg['text']=await tr.transcribe(piece,config.data,prev[-200:])
                    ok+=1
                except tr.TranscribeError as exc: seg.update(status='error',error=str(exc))
                finally: piece.unlink(missing_ok=True)
                if seg['text']: prev=seg['text']
                def add(m,seg=seg,i=i): upsert(m,seg); m['progress']={'done':i+1,'total':len(pieces)}; changed(rid,m)
                if await update(rid,add) is None:return
            def finish(m):
                m.pop('pending',None);m['progress']=None;m.update(status='done' if ok else 'error',error=None if ok else next((s.get('error') for s in m['segments'] if s.get('error')),'failed'));changed(rid,m)
            await update(rid,finish)
        except asyncio.CancelledError: raise
        except Exception as exc: await update(rid,lambda m:(m.pop('pending',None),m.update(status='error',error=str(exc),progress=None),changed(rid,m)))
        finally: work.unlink(missing_ok=True)
    async def finish_live(rid):
        d=rec_dir(rid); wavs=sorted((d/'chunks').glob('*.wav'),key=lambda p:int(p.stem)) if (d/'chunks').exists() else []
        try:
            if not wavs: raise tr.TranscribeError('no audio was recorded')
            await tr.concat_wavs(wavs,d/'audio.m4a'); dur=await tr.duration(d/'audio.m4a'); size=(d/'audio.m4a').stat().st_size
            def done(m):
                m.update(size=size,error=None); m['duration']=dur or m['duration'];
                if config.data.retranscribe_on_finish or not m.get('live',True):m['pending']='full'
                else:m['status']='done'
                changed(rid,m)
            m=await update(rid,done)
            if m and m.get('pending')=='full': await process_full(rid)
        except asyncio.CancelledError: raise
        except Exception as exc: await update(rid,lambda m:(m.update(status='error',error=str(exc)),changed(rid,m)))
    async def startup():
        now=time.time()
        for name in sorted((p.name for p in recordings.iterdir() if p.is_dir()),reverse=True):
            try:m=load(name)
            except KeyError:continue
            if m['status']=='processing': spawn(name,process_full(name) if m.get('source')=='upload' or m.get('pending')=='full' else finish_live(name))
            elif m['status']=='recording' and now-m['created_at']>6*3600: spawn(name,finish_live(name))
    core.on_startup(startup)
    async def shutdown():
        for task in tasks.values(): task.cancel()
    core.on_shutdown(shutdown)

    auth={'dependencies':[Depends(core.require)]}
    class SettingsIn(BaseModel):
        api_base:str|None=None; api_key:str|None=None; clear_key:bool=False; model:str|None=None; language:str|None=None; prompt:str|None=None; chunk_sec:int|None=None; retranscribe_on_finish:bool|None=None
    @app.get('/api/asr/settings',**auth)
    async def settings_get(): return config.data.model_dump()
    @app.patch('/api/asr/settings',**auth)
    async def settings_patch(body:SettingsIn):
        values=body.model_dump(exclude_unset=True); values.pop('clear_key',None)
        if body.clear_key: values['api_key']=''
        if 'api_key' in values and values['api_key'] is not None: values['api_key']=values['api_key'].strip()
        merged=config.data.model_dump()|values
        try: new=config.model.model_validate(merged)
        except ValueError as exc: raise HTTPException(422,str(exc))
        for key,val in values.items(): config.doc[key]=val
        config.save(); return new.model_dump()
    @app.post('/api/asr/settings/test',**auth)
    async def settings_test(): return await tr.list_models(config.data)
    @app.get('/api/asr/recordings',**auth)
    async def recordings_list(q:str=''):
        q=q.strip().lower(); out=[]
        for p in sorted((p for p in recordings.iterdir() if p.is_dir()),key=lambda p:p.name,reverse=True):
            try:m=load(p.name)
            except KeyError:continue
            if q and q not in m['title'].lower() and q not in full_text(m).lower():continue
            out.append(summary(m))
        return out
    class CreateIn(BaseModel): title:str|None=None; live:bool=True
    @app.post('/api/asr/recordings',**auth)
    async def recording_create(body:CreateIn):
        rid=time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(2).hex(); d=rec_dir(rid); d.mkdir(parents=True)
        m={'id':rid,'title':(body.title or '').strip()[:200] or 'Recording '+time.strftime('%m-%d %H:%M'),'source':'record','created_at':time.time(),'duration':0.0,'status':'recording','error':None,'size':0,'segments':[],'text':None,'starred':False,'progress':None}
        if not body.live:m['live']=False
        save(m); core.emit({'type':'asr_changed','module':'asr','id':rid}); return public(m)
    @app.post('/api/asr/recordings/upload',**auth)
    async def recording_upload(req:Request,filename:str='audio',title:str=''):
        rid=time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(2).hex(); d=rec_dir(rid); d.mkdir(parents=True)
        ext=re.sub(r'[^a-z0-9]','',Path(filename).suffix.lower())[:8] or 'bin'; m={'id':rid,'title':(title.strip() or Path(filename).stem or 'Upload')[:200],'source':'upload','created_at':time.time(),'duration':0.0,'status':'processing','error':None,'size':0,'segments':[],'text':None,'starred':False,'progress':None}; save(m)
        try:m['size']=await stream(req,d/f'original.{ext}',MAX_UPLOAD); save(m)
        except BaseException: shutil.rmtree(d); raise
        spawn(rid,process_full(rid)); return public(m)
    @app.get('/api/asr/recordings/{rid}',**auth)
    async def recording_get(rid): return public(get(rid))
    @app.post('/api/asr/recordings/{rid}/chunks',**auth)
    async def recording_chunk(rid,seq:int,start:float,end:float,req:Request):
        m=get(rid)
        if m['source']!='record':raise HTTPException(400,'not a live recording')
        if seq<0 or seq>100000:raise HTTPException(400,'bad seq')
        d=rec_dir(rid)/'chunks';d.mkdir(exist_ok=True);path=d/f'{seq}.wav';await stream(req,path,MAX_CHUNK);seg={'seq':seq,'start':round(start,3),'end':round(end,3),'text':'','status':'ok'}
        if m.get('live',True) and not tr.is_silent(path):
            try:seg['text']=await tr.transcribe(path,config.data,tail(m,seq))
            except tr.TranscribeError as exc:seg.update(status='error',error=str(exc))
        def put(mm):upsert(mm,seg);mm['duration']=max(mm['duration'],seg['end']);changed(rid,mm)
        if await update(rid,put) is None:raise HTTPException(404,'not found')
        return seg
    class FinishIn(BaseModel): duration:float|None=None
    @app.post('/api/asr/recordings/{rid}/finish',**auth)
    async def recording_finish(rid,body:FinishIn):
        get(rid)
        def f(m):
            if m['source']!='record':raise HTTPException(400,'not a live recording')
            m['status']='processing';m['duration']=body.duration or m['duration'];changed(rid,m)
        m=await update(rid,f);spawn(rid,finish_live(rid));return public(m)
    @app.post('/api/asr/recordings/{rid}/retranscribe',**auth)
    async def recording_retranscribe(rid):
        m=get(rid);d=rec_dir(rid)
        if not (d/'audio.m4a').exists() and not list(d.glob('original.*')):raise HTTPException(409,'audio is not ready')
        if m['status'] in ('recording','processing'):raise HTTPException(409,'recording is busy')
        m=await update(rid,lambda mm:(mm.update(status='processing',error=None,pending='full',text=None),changed(rid,mm)));spawn(rid,process_full(rid));return public(m)
    @app.post('/api/asr/recordings/{rid}/segments/{seq}/retry',**auth)
    async def recording_retry(rid,seq:int):
        m=get(rid);seg=next((s for s in m['segments'] if s['seq']==seq),None)
        if not seg:raise HTTPException(404,'segment not found')
        d=rec_dir(rid);chunk=d/'chunks'/f'{seq}.wav';tmp=None
        if not chunk.exists():
            if not (d/'audio.m4a').exists():raise HTTPException(409,'audio is not ready')
            tmp=d/f'retry-{seq}.wav';await tr.slice_wav(d/'audio.m4a',tmp,seg['start'],seg['end']);chunk=tmp
        new={'seq':seq,'start':seg['start'],'end':seg['end'],'text':'','status':'ok'}
        try:
            if not tr.is_silent(chunk):new['text']=await tr.transcribe(chunk,config.data,tail(m,seq))
        except tr.TranscribeError as exc:new.update(status='error',error=str(exc))
        finally:
            if tmp:tmp.unlink(missing_ok=True)
        await update(rid,lambda mm:(upsert(mm,new),changed(rid,mm)));return new
    class PatchIn(BaseModel): title:str|None=None;text:str|None=None;reset_text:bool=False;starred:bool|None=None
    @app.patch('/api/asr/recordings/{rid}',**auth)
    async def recording_patch(rid,body:PatchIn):
        get(rid);fields=body.model_fields_set
        def f(m):
            if body.title is not None and body.title.strip():m['title']=body.title.strip()[:200]
            if body.reset_text or ('text' in fields and body.text is None):m['text']=None
            elif body.text is not None:m['text']=None if body.text==joined(m) else body.text
            if body.starred is not None:m['starred']=body.starred
            changed(rid,m)
        return public(await update(rid,f))
    @app.delete('/api/asr/recordings/{rid}',**auth)
    async def recording_delete(rid):
        get(rid);task=tasks.pop(rid,None)
        if task:task.cancel()
        shutil.rmtree(rec_dir(rid),ignore_errors=True);core.emit({'type':'asr_changed','module':'asr','id':rid});return {'ok':True}
    @app.get('/api/asr/recordings/{rid}/audio',**auth)
    async def recording_audio(rid):
        get(rid);path=rec_dir(rid)/'audio.m4a'
        if not path.exists():raise HTTPException(404,'audio not ready')
        return FileResponse(path,media_type='audio/mp4',headers={'Cache-Control':'private, max-age=3600'})
    def srt_time(t):
        ms=int(round(t*1000));return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    @app.get('/api/asr/recordings/{rid}/export',**auth)
    async def recording_export(rid,fmt:str='txt'):
        m=get(rid)
        if fmt not in ('txt','srt'):raise HTTPException(400,'fmt must be txt or srt')
        def gen():
            if fmt=='srt':
                i=0
                for s in m['segments']:
                    if s.get('text'):i+=1;yield f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}\n\n".encode()
            elif m.get('text') is not None:yield (m['text']+'\n').encode()
            else:
                for s in m['segments']:
                    if s.get('text'):yield (s['text']+'\n').encode()
        fname=re.sub(r'[\\/:*?"<>|\r\n]','_',m['title'])+'.'+fmt
        return StreamingResponse(gen(),media_type='text/plain; charset=utf-8',headers={'Content-Disposition':f"attachment; filename=\"export.{fmt}\"; filename*=UTF-8''{quote(fname)}"})
