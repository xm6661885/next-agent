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

TASK_NOTE = re.compile(r'<(task-id|tool-use-id|status|summary)>(.*?)</\1>', re.S)

def _plain(content):
    if isinstance(content,str): return content
    if isinstance(content,list):
        return '\n'.join(getattr(b,'text',None) or (b.get('text','') if isinstance(b,dict) else '') for b in content)
    return ''

def task_notification(content):
    """Fields of a CLI <task-notification> user turn (background task finished), or None."""
    text = _plain(content).lstrip()
    if not text.startswith('<task-notification>'): return None
    fields = {k.replace('-','_'):v.strip() for k,v in TASK_NOTE.findall(text)}
    return {'task_id':fields.get('task_id',''),'tool_use_id':fields.get('tool_use_id',''),
            'status':fields.get('status',''),'summary':fields.get('summary','')}

def task_notice(parent, note):
    status = note['status'] or 'finished'
    word = 'finished' if status=='completed' else status
    summary = ' '.join(note['summary'].split())
    if len(summary) > 100: summary = summary[:99] + '…'
    text = f'Background task {word}: {summary}' if summary else f'Background task {word}'
    level = 'warn' if status in ('failed','killed','stopped') else 'info'
    return item('notice',parent,level=level,text=text,task=note)

COMPACT_SUMMARY = 'This session is being continued from a previous conversation'

def is_compact_summary(content):
    """The summary the CLI injects as a user turn after compaction (isCompactSummary is not exposed live)."""
    if isinstance(content,list):
        content = next((getattr(b,'text',None) if not isinstance(b,dict) else b.get('text') for b in content),None)
    return isinstance(content,str) and content.startswith(COMPACT_SUMMARY)

CUT_OFF = 'Your response above was cut off mid-stream'

def system_prompt_notice(content):
    """CLI-injected continuation prompts render as a centered notice, not a user bubble."""
    if isinstance(content,list):
        content = next((getattr(b,'text',None) if not isinstance(b,dict) else b.get('text') for b in content),None)
    if isinstance(content,str) and content.startswith(CUT_OFF): return 'Response was cut off; resuming'
    return None

def is_synthetic_message(msg):
    return is_synthetic_user(msg.content)

def is_synthetic_user(content):
    """CLI-generated user turns (interrupt markers) that should not render as user bubbles."""
    if isinstance(content,list):
        texts=[getattr(b,'text',None) if not isinstance(b,dict) else b.get('text') for b in content]
        # Image reads replay a meta turn: "[Image: source: <path>, original WxH]" plus the image block.
        if texts and isinstance(texts[0],str) and texts[0].startswith('[Image:'): return True
        if len(texts)!=1 or not isinstance(texts[0],str): return False
        content=texts[0]
    if not isinstance(content,str): return False
    # Slash-command echoes the CLI replays as user turns, e.g. set_model -> <local-command-stdout>.
    # Skill bodies are replayed as user turns when a skill loads (the SDK parser drops isSynthetic).
    return content.startswith((COMPACT_SUMMARY,'[Request interrupted by user','<local-command-','<command-name>','<command-message>',
                               'Base directory for this skill:','[Image:',CUT_OFF))

class ItemBuilder:
    def __init__(self, uploads=None):
        self.items = deque(maxlen=2000)
        self.streamed = {}
        self.pending = deque()
        self.delivered_commands = 0
        self.init = None
        self.tasks = {}
        self.sdk_session_id = None
        self.activity = None
        self.last_thinking_tokens = float('-inf')
        self.uploads = uploads or {}
        self.notified = set()
        self.started = {}  # item id -> monotonic start, for thinking/tool duration_ms
        self.turn_content = False  # anything but notices since the last result

    def add(self, value):
        if value['kind'] not in ('notice','result'): self.turn_content = True
        self.items.append(value)
        return {'type':'item','item':value}

    def notice(self, level, text):
        return self.add(item('notice',level=level,text=text))

    def pending_user(self, text, attachments, client_id, queued=False):
        value = item('user',text=text,attachments=attachments,uuid=None,pending=True,client_id=client_id)
        # queued: written into a running turn; the client shows it in the queue tray, not the transcript.
        if queued: value['queued'] = True
        value['cli_uuid'] = str(uuid4())
        self.pending.append(value['id'])
        return self.add(value)

    def owner(self, tool_use_id):
        """The Agent tool call a tool call ran under, or None for main-thread tools."""
        found = self.find(tool_use_id) if tool_use_id else None
        return found.get('parent_tool_use_id') if found else None

    def note_parent(self, note, parent=None):
        task = self.tasks.get(note['task_id']) or {}
        return parent or task.get('parent_tool_use_id') or self.owner(note['tool_use_id'])

    def drop_pending(self, iid):
        """Forget a queued user message the CLI cancelled."""
        if iid in self.pending: self.pending.remove(iid)
        found = self.find(iid)
        if found: self.items.remove(found)
        return {'type':'patch','id':iid,'patch':{'cancelled':True,'pending':False}}

    def drop_stale_streams(self):
        """Blocks from an aborted stream (API error, retry) never get content_block_stop: drop tools, settle text."""
        out = []
        for key, iid in list(self.streamed.items()):
            found = self.find(iid)
            if not found or not found.get('streaming'): continue
            self.streamed.pop(key)
            self.started.pop(iid,None)
            if found['kind']=='tool':
                self.items.remove(found)
                out.append({'type':'patch','id':iid,'patch':{'cancelled':True}})
            else: out.append(self.patch(iid,{'streaming':False}))
        return out

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
        if 'parent_tool_use_id' not in task:
            # Shells a subagent starts belong to that subagent's Agent tool call, not to the main thread.
            owner = self.owner(task.get('tool_use_id')) if data.get('owned_by_subagent') else None
            task['parent_tool_use_id'] = owner
        if isinstance(data.get('usage'),dict): task['usage'] = data['usage']
        if subtype=='task_notification' and data.get('status'): task['status'] = data['status']
        elif subtype=='task_started': task['status'] = 'running'  # a stopped subagent can be resumed

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
                out.extend(self.drop_stale_streams())
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
                    if btype=='thinking':
                        self.started[iid] = time.monotonic()
                        value['started_at'] = int(time.time()*1000)  # lets a reopened chat keep the "thinking for" clock
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
                    if found and found['kind']=='thinking' and iid in self.started:
                        patch['duration_ms'] = int((time.monotonic()-self.started.pop(iid))*1000)
                    if found and found['kind']=='tool': self.started.setdefault(iid,time.monotonic())
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
                    self.started.setdefault(iid,time.monotonic())
                else: continue
                if iid and (found := self.find(iid)):
                    # A result may already be in (eager tool runs, re-delivered blocks); never reset it.
                    if found.get('result') is not None: fields.pop('result',None)
                    out.append(self.patch(iid,fields))
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
                    patch = {'result':result}
                    if block.tool_use_id in self.started:
                        patch['duration_ms'] = int((time.monotonic()-self.started.pop(block.tool_use_id))*1000)
                    out.append(self.patch(block.tool_use_id,patch))
                    changed = self.cron_event(self.find(block.tool_use_id),result)
                    if changed: out.append(changed)
            elif (note := task_notification(msg.content)) is not None:
                if note['task_id'] not in self.notified:
                    self.notified.add(note['task_id'])
                    out.append(self.add(task_notice(self.note_parent(note,parent),note)))
            elif (text := system_prompt_notice(msg.content)):
                out.extend(self.drop_stale_streams())
                out.append(self.notice('info',text))
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
                    # Slash commands are never echoed back as user turns; compaction starting is the delivery signal.
                    head=self.find(self.pending[0]) if status=='compacting' and self.pending else None
                    manual=bool(head and (head.get('text') or '').strip().startswith('/compact'))
                    changed=self.set_activity({'kind':status,'at':now(),**({'manual':manual} if status=='compacting' else {})})
                    if manual:
                        out.append(self.patch(self.pending.popleft(),{'pending':False,'queued':False}))
                        self.delivered_commands+=1
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
                tid = msg.data.get('task_id')
                if msg.subtype=='task_notification' and tid and tid not in self.notified:
                    self.notified.add(tid)
                    note={'task_id':tid,'tool_use_id':msg.data.get('tool_use_id') or '',
                          'status':msg.data.get('status') or '','summary':msg.data.get('summary') or ''}
                    out.append(self.add(task_notice(self.note_parent(note),note)))
            elif 'compact' in msg.subtype.lower():
                changed=self.set_activity(None) if self.activity and self.activity['kind']=='compacting' else None
                if changed: out.append(changed)
                meta=msg.data.get('compact_metadata') or msg.data.get('compactMetadata') or {}
                out.append(self.notice('info','Conversation compacted' if meta.get('trigger')!='auto' else 'Conversation auto-compacted'))
            else: log.debug('Ignoring system message subtype: %s', msg.subtype)
        elif isinstance(msg, ResultMessage):
            changed=self.set_activity(None)
            if changed: out.append(changed)
            out.extend(self.drop_stale_streams())
            result = item('result',subtype=msg.subtype,is_error=msg.is_error,duration_ms=msg.duration_ms,
                          num_turns=msg.num_turns,cost_usd=0,total_cost_usd=0,
                          usage=msg.usage or {},terminal_reason=msg.terminal_reason)
            # Background-task notifications wake the CLI for empty turns; don't render a bare "Done" for each.
            if self.turn_content or msg.is_error: out.append(self.add(result))
            self.turn_content = False
            for error in msg.errors or []:
                if not str(error).startswith('[ede_diagnostic]'): out.append(self.notice('error',error))
            self.sdk_session_id = msg.session_id or self.sdk_session_id
        elif isinstance(msg, RateLimitEvent):
            out.append(self.notice('warn',f'Rate limit: {msg.rate_limit_info.status}'))
        return out
