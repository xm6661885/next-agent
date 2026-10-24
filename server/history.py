"""Read and convert SDK transcript messages."""
import json
import re
from pathlib import Path
from .transcript import transcript_path, session_messages, subagent_messages
from .items import system_prompt_notice, task_notification, task_notice, item, user_text, normalize_result, is_synthetic_user


def transcript_parent(sdk_id, cwd, uuid):
    path=transcript_path(sdk_id,cwd)
    if not path or not path.exists(): raise ValueError('Transcript not found')
    with path.open() as stream:
        for line in stream:
            try: entry=json.loads(line)
            except ValueError: continue
            if entry.get('uuid')==uuid: return entry.get('parentUuid')
    raise ValueError('Message not found in transcript')

AGENT_ID = re.compile(r'^agentId: ([A-Za-z0-9_-]+)',re.M)

def agent_id(result_text):
    """The subagent id in an Agent tool result ("agentId: a1b2..."), or None."""
    match = AGENT_ID.search(result_text or '')
    return match.group(1) if match else None

def convert(messages, uploads=None):
    """Transcript messages to items (used for subagent transcripts)."""
    out = []
    tools = {}
    for message in messages:
        raw = message.message if isinstance(message.message,dict) else {}
        content = raw.get('content','')
        if message.type=='user':
            if isinstance(content,list) and any(isinstance(b,dict) and b.get('type')=='tool_result' for b in content):
                for block in content:
                    if isinstance(block,dict) and block.get('type')=='tool_result' and (t := tools.get(block.get('tool_use_id'))):
                        t['result']=normalize_result(block)
            elif (note := task_notification(content)) is not None: out.append(task_notice(None,note))
            elif not is_synthetic_user(content):
                text, attachments = user_text(content,uploads)
                out.append(item('user',text=text,attachments=attachments,uuid=message.uuid,pending=False,client_id=None))
        elif message.type=='assistant' and isinstance(content,list):
            for block in content:
                if not isinstance(block,dict): continue
                typ = block.get('type')
                if typ=='text': out.append(item('text',text=block.get('text',''),streaming=False))
                elif typ=='thinking': out.append(item('thinking',text=block.get('thinking',''),streaming=False))
                elif typ=='tool_use':
                    value = item('tool',tool_use_id=block.get('id'),name=block.get('name',''),input=block.get('input',{}),
                                 input_partial='',streaming=False,result=None)
                    value['id']=block.get('id')
                    out.append(value)
                    tools[value['id']]=value
    return out

def subagent_items(sdk_id, cwd, aid, uploads=None):
    return convert(subagent_messages(sdk_id,cwd,aid),uploads)

def load_items(session, agent, uploads=None):
    sdk_id = session.get('sdk_session_id')
    if not sdk_id:
        return []
    converted = []
    tools = {}
    agents = set()
    for message in session_messages(sdk_id,agent.cwd):
        if message.compact_summary:
            converted.append(item('notice',level='info',text='Context compacted'))
            continue
        raw = message.message if isinstance(message.message,dict) else {}
        content = raw.get('content','')
        parent = message.parent_tool_use_id
        if message.type=='user':
            if isinstance(content,list) and any(isinstance(b,dict) and b.get('type')=='tool_result' for b in content):
                for block in content:
                    if isinstance(block,dict) and block.get('type')=='tool_result':
                        target = tools.get(block.get('tool_use_id'))
                        if target: target['result']=normalize_result(block)
                        if target and (aid := agent_id(target['result']['content'])): agents.add(aid)
            elif (note := task_notification(content)) is not None:
                # A tool_use_id that is not a main-thread tool belongs to a subagent's shell; it is not main-chat news.
                if parent or not note['tool_use_id'] or note['tool_use_id'] in tools or note['task_id'] in agents:
                    converted.append(task_notice(parent,note))
            elif (notice := system_prompt_notice(content)):
                converted.append(item('notice',parent,level='info',text=notice))
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
    # History is only read when no CLI is mid-turn on it, so a tool without a result was cut off (interrupt, crash, restart).
    for value in tools.values():
        if value['result'] is None: value['result']={'content':'Interrupted','is_error':True,'images':[]}
    return converted

def slim(value, sid):
    """Inline tool-result images can be hundreds of KB each; send URLs instead (see /api/sessions/{sid}/images)."""
    images = (value.get('result') or {}).get('images') if value.get('kind')=='tool' else None
    if not sid or not images or not any(x.startswith('data:') for x in images): return value
    urls = [f'/api/sessions/{sid}/images/{value["id"]}/{n}' if x.startswith('data:') else x for n,x in enumerate(images)]
    return {**value,'result':{**value['result'],'images':urls}}

def page(items,before=None,limit=200,sid=None):
    limit = max(1,min(limit,200))
    end = next((i for i,x in enumerate(items) if x['id']==before),len(items)) if before else len(items)
    return {'items':[slim(x,sid) for x in items[max(0,end-limit):end]], 'has_more':end>limit}

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
        path=transcript_path(s['sdk_session_id'],cwd(s) if callable(cwd) else cwd) if s.get('sdk_session_id') else None
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
