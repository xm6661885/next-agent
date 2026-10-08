"""Read and convert SDK transcript messages."""
import json
from pathlib import Path
from claude_agent_sdk import get_session_messages
from claude_agent_sdk._internal.sessions import _find_project_dir
from .items import item, user_text, normalize_result, is_synthetic_user

_cache = {}

def transcript_path(sdk_id, cwd):
    project = _find_project_dir(cwd)
    return project / f'{sdk_id}.jsonl' if project else None

def transcript_parent(sdk_id, cwd, uuid):
    path=transcript_path(sdk_id,cwd)
    if not path or not path.exists(): raise ValueError('Transcript not found')
    with path.open() as stream:
        for line in stream:
            try: entry=json.loads(line)
            except ValueError: continue
            if entry.get('uuid')==uuid: return entry.get('parentUuid')
    raise ValueError('Message not found in transcript')

def load_items(session, agent, uploads=None):
    sdk_id = session.get('sdk_session_id')
    if not sdk_id:
        return []
    path = transcript_path(sdk_id,agent.cwd)
    mtime = path.stat().st_mtime_ns if path and path.exists() else 0
    key = (session['id'],sdk_id,mtime)
    if key in _cache: return [dict(x) for x in _cache[key]]
    converted = []
    tools = {}
    for message in get_session_messages(sdk_id,directory=agent.cwd):
        raw = message.message if isinstance(message.message,dict) else {}
        content = raw.get('content','')
        parent = message.parent_tool_use_id
        if message.type=='user':
            if isinstance(content,list) and any(isinstance(b,dict) and b.get('type')=='tool_result' for b in content):
                for block in content:
                    if isinstance(block,dict) and block.get('type')=='tool_result':
                        target = tools.get(block.get('tool_use_id'))
                        if target: target['result']=normalize_result(block)
            elif not is_synthetic_user(content):
                text, attachments = user_text(content,uploads)
                converted.append(item('user',parent,text=text,attachments=attachments,uuid=message.uuid,pending=False,client_id=None))
        elif message.type=='assistant' and isinstance(content,list):
            for block in content:
                if not isinstance(block,dict): continue
                typ = block.get('type')
                if typ=='text': converted.append(item('text',parent,text=block.get('text',''),streaming=False))
                elif typ=='thinking': converted.append(item('thinking',parent,text=block.get('thinking',''),streaming=False))
                elif typ=='tool_use':
                    iid = block.get('id')
                    value = item('tool',parent,tool_use_id=iid,name=block.get('name',''),input=block.get('input',{}),
                                 input_partial='',streaming=False,result=None)
                    value['id']=iid
                    converted.append(value)
                    tools[iid]=value
    for old_key in list(_cache):
        if old_key[0] == session['id'] and old_key != key:
            del _cache[old_key]
    _cache[key]=converted
    return [dict(x) for x in converted]

def page(items,before=None,limit=200):
    limit = max(1,min(limit,200))
    end = next((i for i,x in enumerate(items) if x['id']==before),len(items)) if before else len(items)
    return {'items':items[max(0,end-limit):end], 'has_more':end>limit}

def _texts(entry):
    """User and assistant prose from one transcript line (tool calls and results are skipped)."""
    if entry.get('type') not in ('user','assistant'): return []
    content=(entry.get('message') or {}).get('content')
    if isinstance(content,str): return [] if is_synthetic_user(content) else [content]
    if not isinstance(content,list): return []
    return [b.get('text','') for b in content if isinstance(b,dict) and b.get('type')=='text']

def _snippet(text,pos,size,width=120):
    start=max(0,pos-width//3)
    end=min(len(text),start+width)
    out=' '.join(text[start:end].split())
    return ('…' if start else '')+out+('…' if end<len(text) else '')

def search_sessions(sessions,cwd,q,limit=50):
    """Case-insensitive substring search over titles, previews and transcript text.
    Returns [(session_id, snippet)] in the given order; snippet is '' for title-only matches."""
    ql=q.lower()
    hits=[]
    for s in sessions:
        if len(hits)>=limit: break
        found=None
        path=transcript_path(s['sdk_session_id'],cwd) if s.get('sdk_session_id') else None
        if path and path.exists():
            with path.open(encoding='utf-8',errors='replace') as stream:
                for line in stream:
                    if ql not in line.lower(): continue
                    try: entry=json.loads(line)
                    except ValueError: continue
                    for text in _texts(entry):
                        pos=text.lower().find(ql)
                        if pos>=0: found=_snippet(text,pos,len(ql)); break
                    if found: break
        if found is None and ql in (s.get('title','')+' '+s.get('preview','')).lower(): found=''
        if found is not None: hits.append((s['id'],found))
    return hits
