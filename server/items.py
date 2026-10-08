"""Convert SDK messages into flat chat items and incremental events."""
import json
import logging
import re
import time
from collections import deque
from dataclasses import asdict
from uuid import uuid4
from claude_agent_sdk import (AssistantMessage, UserMessage, SystemMessage, ResultMessage,
                              StreamEvent, TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock, RateLimitEvent)
from .config import now

PATH_LINE = re.compile(r'^The user sent a file: (.+)$')
log = logging.getLogger(__name__)

def _keep_synthetic_flag():
    """parse_message drops isSynthetic, which the CLI sets on replayed meta turns (skill bodies etc.).
    ClaudeSDKClient.receive_messages imports parse_message at call time, so patching the module works."""
    from claude_agent_sdk._internal import message_parser
    original = message_parser.parse_message
    if getattr(original,'_keeps_synthetic',False): return
    def parse_message(data):
        msg = original(data)
        if isinstance(msg,UserMessage) and isinstance(data,dict) and data.get('isSynthetic'):
            msg.synthetic = True
        return msg
    parse_message._keeps_synthetic = True
    message_parser.parse_message = parse_message

_keep_synthetic_flag()

def ident():
    return uuid4().hex[:12]

def item(kind, parent=None, **fields):
    value = {'id':ident(), 'kind':kind, 'ts':now(), **fields}
    if parent:
        value['parent_tool_use_id'] = parent
    return value

def user_text(content, uploads=None):
    if isinstance(content, str):
        chunks = [content]
    else:
        chunks = [b.text if isinstance(b, TextBlock) else b.get('text','') for b in content
                  if isinstance(b, TextBlock) or isinstance(b,dict) and b.get('type')=='text']
    paths = []
    lines = []
    for line in '\n'.join(chunks).splitlines():
        match = PATH_LINE.fullmatch(line)
        if match:
            paths.append(match.group(1))
        else:
            lines.append(line)
    attachments = []
    for path in paths:
        record = next((a for a in (uploads or {}).values() if a.get('path') == path), None)
        if record:
            attachments.append({k:record[k] for k in ('id','name','mime','size','path','url','is_image')})
        else:
            attachments.append({'id':'','name':path.rsplit('/',1)[-1],'mime':'application/octet-stream','size':0,
                                'path':path,'url':'','is_image':False})
    return '\n'.join(lines).strip(), attachments

def normalize_result(block):
    content = block.content if hasattr(block,'content') else block.get('content','')
    images = []
    if isinstance(content, str):
        value = content
    else:
        texts = []
        for part in content or []:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict):
                if part.get('type') == 'text': texts.append(part.get('text',''))
                if part.get('type') == 'image':
                    src = part.get('source',{})
                    images.append(f"data:{src.get('media_type','image/png')};base64,{src.get('data','')}")
            elif hasattr(part,'text'):
                texts.append(part.text)
        value = '\n'.join(texts)
    raw = value.encode()
    if len(raw) > 200000:
        value = raw[:200000].decode(errors='ignore') + f'\n... [truncated {len(raw)-200000} bytes]'
    error = block.is_error if hasattr(block,'is_error') else block.get('is_error',False)
    return {'content':value,'is_error':bool(error),'images':images}

def is_synthetic_message(msg):
    return getattr(msg,'synthetic',False) or is_synthetic_user(msg.content)

def is_synthetic_user(content):
    """CLI-generated user turns (interrupt markers) that should not render as user bubbles."""
    if isinstance(content,list):
        texts=[getattr(b,'text',None) if not isinstance(b,dict) else b.get('text') for b in content]
        if len(texts)!=1 or not isinstance(texts[0],str): return False
        content=texts[0]
    if not isinstance(content,str): return False
    # Slash-command echoes the CLI replays as user turns, e.g. set_model -> <local-command-stdout>.
    return content.startswith(('[Request interrupted by user','<local-command-','<command-name>','<command-message>'))

class ItemBuilder:
    def __init__(self, uploads=None):
        self.items = deque(maxlen=2000)
        self.streamed = {}
        self.pending = deque()
        self.init = None
        self.tasks = {}
        self.sdk_session_id = None
        self.activity = None
        self.last_thinking_tokens = float('-inf')
        self.uploads = uploads or {}

    def add(self, value):
        self.items.append(value)
        return {'type':'item','item':value}

    def notice(self, level, text):
        return self.add(item('notice',level=level,text=text))

    def pending_user(self, text, attachments, client_id):
        value = item('user',text=text,attachments=attachments,uuid=None,pending=True,client_id=client_id)
        self.pending.append(value['id'])
        return self.add(value)

    def find(self, iid):
        return next((x for x in reversed(self.items) if x['id']==iid), None)

    def patch(self, iid, values):
        found = self.find(iid)
        if found: found.update(values)
        return {'type':'patch','id':iid,'patch':values}

    def set_activity(self, value):
        if value == self.activity: return None
        self.activity = value
        return {'type':'activity','activity':value}

    def tasks_event(self):
        return {'type':'tasks','tasks':list(self.tasks.values())}

    def task_event(self, subtype, data):
        """Track background work (subagents, shells, ...) from task_started/progress/notification/updated."""
        tid = data.get('task_id')
        if not tid: return None
        task = self.tasks.setdefault(tid,{'task_id':tid,'kind':'task','status':'running','started_at':now()})
        for key in ('tool_use_id','description','task_type','subagent_type','last_tool_name','summary','output_file'):
            if data.get(key) is not None: task[key] = data[key]
        if isinstance(data.get('usage'),dict): task['usage'] = data['usage']
        if subtype=='task_notification' and data.get('status'): task['status'] = data['status']
        elif subtype=='task_updated':
            patch = data.get('patch') if isinstance(data.get('patch'),dict) else {}
            if patch.get('status'): task['status'] = 'stopped' if patch['status']=='killed' else patch['status']
            if patch.get('description'): task['description'] = patch['description']
        task['updated_at'] = now()
        return self.tasks_event()

    def cron_event(self, tool, result):
        """CronCreate/CronDelete live only inside the CLI process; mirror them from tool calls."""
        if not tool or tool.get('kind')!='tool' or result['is_error']: return None
        args = tool.get('input') or {}
        if tool.get('name')=='CronCreate':
            match = re.search(r'Scheduled (?:recurring job|one-shot task) (\S+) \(([^)]*)\)',result['content'])
            jid = match.group(1) if match else tool['tool_use_id']
            self.tasks['cron:'+jid] = {'task_id':'cron:'+jid,'kind':'cron','job_id':jid,'tool_use_id':tool['tool_use_id'],
                                       'description':args.get('prompt',''),'cron':args.get('cron',''),
                                       'recurring':args.get('recurring',True) is not False,'schedule':match.group(2) if match else '','status':'scheduled',
                                       'started_at':now(),'updated_at':now()}
            return self.tasks_event()
        if tool.get('name')=='CronDelete' and self.tasks.pop('cron:'+str(args.get('id','')),None):
            return self.tasks_event()
        return None

    def consume(self, msg):
        out = []
        parent = getattr(msg,'parent_tool_use_id',None)
        if isinstance(msg, StreamEvent):
            event = msg.event
            kind = event.get('type')
            if kind == 'message_start':
                changed=self.set_activity(None)
                if changed: out.append(changed)
                self.stream_message_id = event.get('message',{}).get('id',msg.uuid)
            elif kind == 'content_block_start':
                index = event.get('index',0)
                block = event.get('content_block',{})
                btype = block.get('type')
                iid = block.get('id') if btype=='tool_use' else ident()
                if btype in ('text','thinking','tool_use'):
                    value = item({'tool_use':'tool'}.get(btype,btype),parent,
                                 **({'text':'','streaming':True} if btype!='tool_use' else
                                    {'tool_use_id':iid,'name':block.get('name',''),'input':{},'input_partial':'','streaming':True,'result':None}))
                    value['id'] = iid
                    self.streamed[(getattr(self,'stream_message_id',msg.uuid),index)] = iid
                    out.append(self.add(value))
            elif kind == 'content_block_delta':
                key = (getattr(self,'stream_message_id',msg.uuid),event.get('index',0))
                iid = self.streamed.get(key)
                delta = event.get('delta',{})
                field = {'text_delta':'text','thinking_delta':'text','input_json_delta':'input_partial'}.get(delta.get('type'))
                if iid and field:
                    value = delta.get('text',delta.get('thinking',delta.get('partial_json','')))
                    found = self.find(iid)
                    if found: found[field] = found.get(field,'')+value
                    out.append({'type':'delta','id':iid,'field':field,'text':value})
            elif kind == 'content_block_stop':
                iid = self.streamed.get((getattr(self,'stream_message_id',msg.uuid),event.get('index',0)))
                if iid:
                    found = self.find(iid)
                    patch = {'streaming':False}
                    if found and found['kind']=='tool' and not found.get('input'):
                        try: patch['input'] = json.loads(found.get('input_partial','') or '{}')
                        except ValueError: pass
                    out.append(self.patch(iid,patch))
        elif isinstance(msg, AssistantMessage):
            mid = msg.message_id or msg.uuid
            for block in msg.content:
                # The CLI may split one API message into several AssistantMessages (one block each), so
                # block positions don't match stream indices. Claim the oldest streamed block of the same kind.
                want = 'text' if isinstance(block,TextBlock) else 'thinking' if isinstance(block,ThinkingBlock) else None
                iid = None
                if want:
                    for key in sorted(k for k in self.streamed if k[0]==mid):
                        found = self.find(self.streamed[key])
                        if found and found['kind']==want:
                            iid = self.streamed.pop(key); break
                elif isinstance(block,ToolUseBlock):
                    for key in [k for k,v in self.streamed.items() if k[0]==mid and v==block.id]: self.streamed.pop(key)
                if isinstance(block, TextBlock):
                    kind, fields = 'text', {'text':block.text,'streaming':False}
                elif isinstance(block, ThinkingBlock):
                    kind, fields = 'thinking', {'text':block.thinking,'streaming':False}
                elif isinstance(block, ToolUseBlock):
                    kind, fields = 'tool', {'tool_use_id':block.id,'name':block.name,'input':block.input,
                                            'input_partial':'','streaming':False,'result':None}
                    iid = iid or block.id
                else: continue
                if iid and self.find(iid): out.append(self.patch(iid,fields))
                else:
                    value = item(kind,parent,**fields)
                    if iid: value['id']=iid
                    out.append(self.add(value))
            if msg.error: out.append(self.notice('error',str(msg.error)))
        elif isinstance(msg, UserMessage):
            blocks = msg.content if isinstance(msg.content,list) else []
            results = [b for b in blocks if isinstance(b,ToolResultBlock)]
            if results:
                for block in results:
                    result = normalize_result(block)
                    out.append(self.patch(block.tool_use_id,{'result':result}))
                    changed = self.cron_event(self.find(block.tool_use_id),result)
                    if changed: out.append(changed)
            elif is_synthetic_message(msg):
                pass
            else:
                if self.pending:
                    out.append(self.patch(self.pending.popleft(),{'pending':False,'uuid':msg.uuid}))
                else:
                    text, attachments = user_text(msg.content,self.uploads)
                    out.append(self.add(item('user',parent,text=text,attachments=attachments,uuid=msg.uuid,pending=False,client_id=None)))
        elif isinstance(msg, SystemMessage):
            if msg.subtype=='status':
                status=msg.data.get('status')
                if status in ('requesting','compacting'):
                    changed=self.set_activity({'kind':status,'at':now()})
                elif self.activity and self.activity['kind']=='compacting':
                    changed=self.set_activity(None)
                else: changed=None
                if changed: out.append(changed)
            elif msg.subtype=='api_retry':
                data=msg.data
                value={'kind':'retry','at':now(),**{k:data.get(k) for k in
                       ('attempt','max_retries','retry_delay_ms','error_status','error')}}
                if 'no_response' in data: value['no_response']=data['no_response']
                changed=self.set_activity(value)
                if changed: out.append(changed)
            elif msg.subtype=='thinking_tokens':
                stamp=time.monotonic()
                if stamp-self.last_thinking_tokens>=1:
                    self.last_thinking_tokens=stamp
                    changed=self.set_activity({'kind':'thinking_tokens','at':now(),
                                               'estimated_tokens':msg.data.get('estimated_tokens')})
                    if changed: out.append(changed)
            elif msg.subtype=='init':
                self.sdk_session_id = msg.data.get('session_id',self.sdk_session_id)
                keys = {'model':'model','permissionMode':'permission_mode','tools':'tools','slash_commands':'slash_commands',
                        'mcp_servers':'mcp_servers','agents':'agents','skills':'skills','claude_code_version':'claude_code_version','cwd':'cwd'}
                value = {v:msg.data.get(k) for k,v in keys.items()}
                if value != self.init:
                    self.init = value
                    out.append({'type':'init',**value})
            elif msg.subtype.startswith('task_'):
                changed = self.task_event(msg.subtype,msg.data)
                if changed: out.append(changed)
            elif 'compact' in msg.subtype.lower(): out.append(self.notice('info','Conversation compacted'))
            else: log.debug('Ignoring system message subtype: %s', msg.subtype)
        elif isinstance(msg, ResultMessage):
            changed=self.set_activity(None)
            if changed: out.append(changed)
            result = item('result',subtype=msg.subtype,is_error=msg.is_error,duration_ms=msg.duration_ms,
                          num_turns=msg.num_turns,cost_usd=0,total_cost_usd=0,
                          usage=msg.usage or {},terminal_reason=msg.terminal_reason)
            out.append(self.add(result))
            for error in msg.errors or []:
                if not str(error).startswith('[ede_diagnostic]'): out.append(self.notice('error',error))
            self.sdk_session_id = msg.session_id or self.sdk_session_id
        elif isinstance(msg, RateLimitEvent):
            out.append(self.notice('warn',f'Rate limit: {msg.rate_limit_info.status}'))
        return out
