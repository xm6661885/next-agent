"""OpenAI-compatible transcription calls and ffmpeg helpers."""
import asyncio, logging, re, wave
from array import array
from pathlib import Path
import httpx

log = logging.getLogger('asr')
_sem = asyncio.Semaphore(1)
transport: httpx.AsyncBaseTransport | None = None

class TranscribeError(Exception): pass

async def transcribe(path, config, prompt=''):
    if not config.api_key: raise TranscribeError('API key not set (Settings)')
    full_prompt = ' '.join(p for p in (config.prompt.strip(), prompt.strip()) if p)
    data = {'model': config.model, 'response_format': 'json'}
    if config.language: data['language'] = config.language
    if full_prompt: data['prompt'] = full_prompt[-800:]
    mime = 'audio/wav' if Path(path).suffix == '.wav' else 'audio/mp4'
    async with _sem:
        last = 'unknown error'
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=120, trust_env=False, transport=transport) as client:
                    with Path(path).open('rb') as file:
                        response = await client.post(config.api_base.rstrip('/') + '/audio/transcriptions', data=data,
                                                     files={'file': (Path(path).name, file, mime)},
                                                     headers={'Authorization': f'Bearer {config.api_key}'})
            except httpx.HTTPError as exc:
                last = f'network error: {type(exc).__name__}'
                continue
            if response.status_code >= 500:
                last = f'HTTP {response.status_code}: {response.text[:200]}'
                continue
            if response.status_code != 200: raise TranscribeError(f'HTTP {response.status_code}: {response.text[:200]}')
            try: body = response.json()
            except ValueError: return response.text.strip()
            return str(body.get('text', '')).strip()
        raise TranscribeError(last)

async def list_models(config):
    if not config.api_key: return {'ok': False, 'detail': 'API key not set', 'models': []}
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False, transport=transport) as client:
            response = await client.get(config.api_base.rstrip('/') + '/models', headers={'Authorization': f'Bearer {config.api_key}'})
    except httpx.HTTPError as exc:
        return {'ok': False, 'detail': f'network error: {type(exc).__name__}', 'models': []}
    if response.status_code != 200: return {'ok': False, 'detail': f'HTTP {response.status_code}: {response.text[:200]}', 'models': []}
    try: ids = [m['id'] for m in response.json().get('data', []) if isinstance(m, dict) and 'id' in m]
    except (ValueError, AttributeError): ids = []
    return {'ok': True, 'detail': f'Connected, {len(ids)} models', 'models': sorted(ids)[:100]}

def is_silent(path, threshold=200):
    try:
        with wave.open(str(path), 'rb') as wav:
            if wav.getsampwidth() != 2: return False
            while buf := wav.readframes(4096):
                values = array('h', buf[:len(buf)//2*2])
                if max(values, default=0) >= threshold or -min(values, default=0) >= threshold: return False
            return True
    except (wave.Error, EOFError): return False

async def run(*args, on_line=None):
    if args[0] == 'ffmpeg': args = (args[0], '-nostats', '-threads', '1', *args[1:])
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    tail=[]
    async def read_err():
        async for raw in process.stderr:
            line=raw.decode(errors='replace')
            if on_line: on_line(line)
            tail.append(line)
            if len(tail)>8: tail.pop(0)
    async def read_out():
        out=[]
        while chunk := await process.stdout.read(4096):
            if sum(map(len,out)) < 65536: out.append(chunk)
        return b''.join(out)
    out = await asyncio.gather(read_err(), read_out()); rc=await process.wait()
    if rc: raise TranscribeError(f'{Path(args[0]).name} failed: {''.join(tail)[-300:]}')
    return out[1].decode(errors='replace')

async def duration(path):
    out=await run('ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path))
    try: return float(out.strip().splitlines()[0])
    except (ValueError, IndexError): return 0.0

async def to_m4a(src,dst):
    tmp=dst.with_name(dst.stem+'.tmp.m4a'); await run('ffmpeg','-nostdin','-y','-v','error','-i',str(src),'-vn','-ac','1','-c:a','aac','-b:a','64k','-movflags','+faststart',str(tmp)); tmp.replace(dst)

async def concat_wavs(wavs,dst):
    lst=dst.with_name('concat.txt'); lst.write_text(''.join(f"file '{w.resolve()}'\n" for w in wavs)); tmp=dst.with_name(dst.stem+'.tmp.m4a')
    try:
        await run('ffmpeg','-nostdin','-y','-v','error','-f','concat','-safe','0','-i',str(lst),'-ac','1','-c:a','aac','-b:a','64k','-movflags','+faststart',str(tmp)); tmp.replace(dst)
    finally: lst.unlink(missing_ok=True)

async def slice_wav(src,dst,start,end): await run('ffmpeg','-nostdin','-y','-v','error','-ss',f'{start:.3f}','-to',f'{end:.3f}','-i',str(src),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(dst))

async def plan_pieces(src,total,target=60.0):
    if total <= target*1.25: return [(0.0,total)]
    mids=[]; started=[]
    def line(value):
        if m:=re.search(r'silence_start: ([\d.]+)',value): started[:]=[float(m.group(1))]
        elif (m:=re.search(r'silence_end: ([\d.]+)',value)) and started: mids.append((started[0]+float(m.group(1)))/2); started.clear()
    try: await run('ffmpeg','-nostdin','-v','info','-i',str(src),'-vn','-af','silencedetect=noise=-35dB:d=0.35','-f','null','-',on_line=line)
    except TranscribeError: mids=[]
    pieces=[]; cur=0.0
    while total-cur > target*1.25:
        lo,hi=cur+target*.6,cur+target*1.25; candidates=[m for m in mids if lo<=m<=hi]; cut=min(candidates,key=lambda m:abs(m-(cur+target))) if candidates else cur+target; pieces.append((cur,cut)); cur=cut
    pieces.append((cur,total)); return pieces
