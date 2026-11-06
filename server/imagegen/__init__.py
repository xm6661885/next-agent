import asyncio, base64, json, mimetypes, os, re, shutil, time
from pathlib import Path
import httpx
from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from .config import config_file

transport: httpx.AsyncBaseTransport|None=None
MAGICS=((b'\x89PNG\r\n\x1a\n','image/png','.png'),(b'\xff\xd8\xff','image/jpeg','.jpg'),(b'GIF87a','image/gif','.gif'),(b'GIF89a','image/gif','.gif'),(b'RIFF','image/webp','.webp'))
MAX_REF=20*1024*1024

class ApiFailure(Exception):
    def __init__(self, detail): self.detail=detail

def sniff(data):
    for magic,mime,ext in MAGICS:
        if data.startswith(magic) and (magic!=b'RIFF' or data[8:12]==b'WEBP'): return mime,ext
    raise HTTPException(415,'unsupported image type')
def dimensions(data,mime):
    try:
        if mime=='image/png': return int.from_bytes(data[16:20],'big'),int.from_bytes(data[20:24],'big')
        if mime=='image/gif': return int.from_bytes(data[6:8],'little'),int.from_bytes(data[8:10],'little')
        if mime=='image/webp': return None,None
    except (IndexError,ValueError): pass
    return None,None

def mount(app,core):
    config=config_file(core); root=core.paths.root/'imagegen'; root.mkdir(parents=True,exist_ok=True); sem=asyncio.Semaphore(2); tasks=set()
    def path(jid):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',jid): raise HTTPException(404,'not found')
        return root/'jobs'/jid
    def load(jid):
        try:return json.loads((path(jid)/'job.json').read_text())
        except (FileNotFoundError,ValueError):raise HTTPException(404,'not found')
    def save(job):
        d=path(job['id']);d.mkdir(parents=True,exist_ok=True);p=d/'job.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(job,ensure_ascii=False,separators=(',',':')));os.replace(tmp,p)
    def emit(job):core.emit({'type':'imagegen_changed','module':'imagegen','id':job['id'],'status':job['status']})
    async def request_generation(job,refs,mask):
        c=config.data; headers={'Authorization':f'Bearer {c.api_key}'}; model=job['model'];params=job['params']; payload={'model':model,'prompt':job['prompt']}
        payload.update({k:v for k,v in params.items() if v is not None and k not in ('model','reference_mode')})
        images=[f'data:{mime};base64,{base64.b64encode(data).decode()}' for _,data,mime in refs]
        if images:payload['image']=images[0] if len(images)==1 else images
        if mask:payload['mask']=f'data:{mask[2]};base64,{base64.b64encode(mask[1]).decode()}'
        async with httpx.AsyncClient(timeout=c.timeout,trust_env=False,transport=transport) as client:
            response=await client.post(c.api_base+'/images/generations',json=payload,headers=headers)
        if response.status_code>=400:raise ApiFailure(f'HTTP {response.status_code}: {response.text[:500]}')
        try:body=response.json(); data=body.get('data')
        except ValueError:raise ApiFailure('invalid JSON response')
        if not data:raise ApiFailure('response contained no images')
        return body
    async def request_edits(job,refs,mask):
        c=config.data; params=job['params']; fields={'model':job['model'],'prompt':job['prompt']}; fields.update({k:str(v) for k,v in params.items() if v is not None and k in ('size','quality','background','output_format','n')})
        files=[]
        for name,data,mime in refs:files.append(('image' if len(refs)==1 else 'image[]',(name,data,mime)))
        if mask:files.append(('mask',(mask[0],mask[1],mask[2])))
        async with httpx.AsyncClient(timeout=c.timeout,trust_env=False,transport=transport) as client:
            response=await client.post(c.api_base+'/images/edits',data=fields,files=files,headers={'Authorization':f'Bearer {c.api_key}'})
        if response.status_code>=400:raise ApiFailure(f'HTTP {response.status_code}: {response.text[:500]}')
        try:body=response.json();
        except ValueError:raise ApiFailure('invalid JSON response')
        if not body.get('data'):raise ApiFailure('response contained no images')
        return body
    async def run_job(job,refs,mask):
        async with sem:
            try:
                mode=config.data.reference_mode
                if not refs:body=await request_generation(job,refs,mask)
                elif mode=='generations':body=await request_generation(job,refs,mask)
                elif mode=='edits':body=await request_edits(job,refs,mask)
                else:
                    try:body=await request_edits(job,refs,mask)
                    except ApiFailure:body=await request_generation(job,refs,mask)
                out=[]
                for i,item in enumerate(body['data']):
                    name=f'image-{i+1}.'+({'png':'png','jpeg':'jpg','webp':'webp'}.get(job['params'].get('output_format','png'),'png'))
                    if item.get('b64_json'):raw=base64.b64decode(item['b64_json'])
                    elif item.get('url'):
                        async with httpx.AsyncClient(timeout=config.data.timeout,trust_env=False,transport=transport) as client:
                            response=await client.get(item['url']);response.raise_for_status();raw=response.content
                    else:raise ApiFailure('image has no data')
                    (path(job['id'])/name).write_bytes(raw);mime=mimetypes.guess_type(name)[0] or 'application/octet-stream';w,h=dimensions(raw,mime)
                    out.append({'name':name,'url':f'/api/imagegen/files/{job["id"]}/{name}','width':w,'height':h,'bytes':len(raw)})
                    if item.get('revised_prompt'):job['revised_prompt']=item['revised_prompt']
                job.update(status='done',images=out)
            except asyncio.CancelledError:raise
            except Exception as exc:job.update(status='error',error=str(exc))
            job['finished_at']=time.time();job['duration_ms']=round((job['finished_at']-job['created_at'])*1000);save(job);emit(job)
    async def startup():
        jobs=root/'jobs'
        if not jobs.exists():return
        for p in jobs.iterdir():
            if p.is_dir():
                try:job=load(p.name)
                except HTTPException:continue
                if job.get('status')=='running':job.update(status='error',error='Server restarted',finished_at=time.time());save(job);emit(job)
    core.on_startup(startup)
    async def shutdown():
        for task in tasks: task.cancel()
    core.on_shutdown(shutdown)
    class SettingsIn(BaseModel):
        api_base:str|None=None;api_key:str|None=None;models:list[str]|None=None;default_model:str|None=None;reference_mode:str|None=None;timeout:int|None=None
    auth={'dependencies':[Depends(core.require)]}
    @app.get('/api/imagegen/settings',**auth)
    async def settings_get():return config.data.model_dump()
    @app.patch('/api/imagegen/settings',**auth)
    async def settings_patch(body:SettingsIn):
        values=body.model_dump(exclude_unset=True);merged=config.data.model_dump()|values
        try:new=config.model.model_validate(merged)
        except ValueError as exc:raise HTTPException(422,str(exc))
        for k,v in values.items():config.doc[k]=v
        config.save();return new.model_dump()
    @app.post('/api/imagegen/settings/models',**auth)
    async def settings_models():
        if not config.data.api_key:return {'models':[]}
        try:
            async with httpx.AsyncClient(timeout=15,trust_env=False,transport=transport) as client:r=await client.get(config.data.api_base+'/models',headers={'Authorization':f'Bearer {config.data.api_key}'})
        except httpx.HTTPError as exc:raise HTTPException(502,f'network error: {type(exc).__name__}')
        if r.status_code!=200:raise HTTPException(502,f'HTTP {r.status_code}: {r.text[:200]}')
        try:return {'models':[x['id'] for x in r.json().get('data',[]) if isinstance(x,dict) and 'id' in x]}
        except (ValueError,AttributeError):return {'models':[]}
    @app.post('/api/imagegen/settings/test',**auth)
    async def settings_test():
        try:
            async with httpx.AsyncClient(timeout=15,trust_env=False,transport=transport) as client:r=await client.get(config.data.api_base+'/models',headers={'Authorization':f'Bearer {config.data.api_key}'})
        except httpx.HTTPError as exc:return {'ok':False,'detail':f'network error: {type(exc).__name__}'}
        if r.status_code!=200:return {'ok':False,'detail':f'HTTP {r.status_code}','models':[]}
        try:models=[x['id'] for x in r.json().get('data',[]) if isinstance(x,dict) and 'id' in x]
        except (ValueError,AttributeError):models=[]
        return {'ok':True,'detail':f'Connected, {len(models)} models','models':sorted(models)[:100]}
    @app.post('/api/imagegen/jobs',**auth)
    async def job_create(prompt:str=Form(...),model:str|None=Form(None),size:str|None=Form(None),quality:str|None=Form(None),n:int=Form(1),background:str|None=Form(None),output_format:str|None=Form(None),output_compression:int|None=Form(None),moderation:str|None=Form(None),images:list[UploadFile]=File(default=[],alias='images[]'),mask:UploadFile|None=File(None)):
        if not prompt.strip():raise HTTPException(422,'prompt is required')
        if n<1 or n>4:raise HTTPException(422,'n must be between 1 and 4')
        if size and size!='auto':
            match=re.fullmatch(r'(\d+)x(\d+)',size)
            if not match or int(match[1])<1 or int(match[2])<1:raise HTTPException(422,'invalid size')
        if quality and quality not in ('auto','low','medium','high'):raise HTTPException(422,'invalid quality')
        if background and background not in ('auto','opaque','transparent'):raise HTTPException(422,'invalid background')
        if output_format and output_format not in ('png','jpeg','webp'):raise HTTPException(422,'invalid output_format')
        if output_compression is not None and (output_compression<0 or output_compression>100 or not output_format or output_format=='png'):raise HTTPException(422,'invalid output_compression')
        if moderation and moderation not in ('auto','low'):raise HTTPException(422,'invalid moderation')
        if len(images)>8:raise HTTPException(422,'at most 8 reference images')
        refs=[]
        for image in images:
            data=await image.read(MAX_REF+1)
            if len(data)>MAX_REF:raise HTTPException(413,'reference image is too large')
            mime,ext=sniff(data);name=Path(image.filename or ('reference'+ext)).name
            refs.append((name,data,mime))
        maskdata=None
        if mask:
            data=await mask.read(MAX_REF+1)
            if len(data)>MAX_REF:raise HTTPException(413,'mask is too large')
            mime,ext=sniff(data);maskdata=(Path(mask.filename or ('mask'+ext)).name,data,mime)
        jid=time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(3).hex();params={k:v for k,v in {'size':size,'quality':quality,'n':n,'background':background,'output_format':output_format,'output_compression':output_compression,'moderation':moderation}.items() if v is not None};job={'id':jid,'prompt':prompt,'params':params,'model':model or config.data.default_model,'references':[],'status':'running','error':None,'images':[],'created_at':time.time(),'finished_at':None,'duration_ms':None}
        for name,data,mime in refs:
            (root/'jobs'/jid).mkdir(parents=True,exist_ok=True);(path(jid)/name).write_bytes(data);job['references'].append({'name':name,'url':f'/api/imagegen/files/{jid}/{name}'})
        if maskdata:(path(jid)/maskdata[0]).write_bytes(maskdata[1])
        save(job);emit(job)
        task=asyncio.create_task(run_job(job,refs,maskdata));tasks.add(task);task.add_done_callback(tasks.discard)
        return job
    @app.get('/api/imagegen/jobs',**auth)
    async def jobs(before:str='',limit:int=50):
        limit=max(1,min(limit,200));items=[]
        for p in sorted((p for p in (root/'jobs').iterdir() if p.is_dir()),key=lambda p:p.name,reverse=True):
            if before and p.name>=before:continue
            try:items.append(load(p.name))
            except HTTPException:continue
            if len(items)>=limit:break
        return items
    @app.get('/api/imagegen/jobs/{jid}',**auth)
    async def job_get(jid):return load(jid)
    @app.delete('/api/imagegen/jobs/{jid}',**auth)
    async def job_delete(jid):
        job=load(jid);shutil.rmtree(path(jid),ignore_errors=True);core.emit({'type':'imagegen_changed','module':'imagegen','id':jid,'status':'deleted'});return {'ok':True}
    @app.post('/api/imagegen/jobs/{jid}/retry',**auth)
    async def job_retry(jid):
        old=load(jid);refs=[]
        for ref in old.get('references',[]):
            p=path(jid)/ref['name'];data=p.read_bytes();mime,_=sniff(data);refs.append((ref['name'],data,mime))
        form={'prompt':old['prompt'],'model':old['model'],'params':old['params']};jid2=time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(3).hex();job={'id':jid2,'prompt':form['prompt'],'params':form['params'],'model':form['model'],'references':[],'status':'running','error':None,'images':[],'created_at':time.time(),'finished_at':None,'duration_ms':None};
        for name,data,mime in refs:(path(jid2)).mkdir(parents=True,exist_ok=True);(path(jid2)/name).write_bytes(data);job['references'].append({'name':name,'url':f'/api/imagegen/files/{jid2}/{name}'})
        save(job);emit(job);task=asyncio.create_task(run_job(job,refs,None));tasks.add(task);task.add_done_callback(tasks.discard);return job
    @app.get('/api/imagegen/files/{jid}/{name}',**auth)
    async def file_get(jid,name):
        job=load(jid);safe=Path(name).name
        if safe!=name:raise HTTPException(404,'not found')
        p=path(jid)/safe
        if not p.is_file():raise HTTPException(404,'not found')
        mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream';return FileResponse(p,media_type=mime,content_disposition_type='inline',filename=p.name)
