"""Codex app-server adapter and normalized item reducer."""
import asyncio, copy, os, time
from uuid import uuid4
from ...items import Items
from ...config import now
from .process import CodexProcess, CodexRpcError

MODES = {
    'full-access': {'name':'Full access', 'description':'No sandbox restrictions', 'sandboxPolicy': {'type':'dangerFullAccess'}, 'approvalPolicy':'never'},
    'auto': {'name':'Auto', 'description':'Write within the session directory and ask before escalation', 'sandboxPolicy': {'type':'workspaceWrite', 'writableRoots': []}, 'approvalPolicy':'on-request'},
    'read-only': {'name':'Read only', 'description':'Read files without writing', 'sandboxPolicy': {'type':'readOnly'}, 'approvalPolicy':'on-request'},
}

class CodexRuntime:
    def __init__(self, manager, sid):
        self.manager, self.sid = manager, sid; self.session = manager.store.sessions[sid]
        self.state='offline'; self.seq=0; self.ring=[]; self.subscribers=set(); self.viewers=0
        self.permissions={}; self.questions={}; self.process=None; self.thread_id=self.session.get('remote_id'); self.turn_id=None
        self.active=None; self.queue=[]; self.worker=None; self.last_activity=time.monotonic(); self.running_since=None
        self.flush_handle=None; self.item_by_id={}; self.text_by_id={}; self.tool_by_id={}; self.turn_text=[]
        self.items=Items(manager.store.load_items(sid), self.item_event)
        self.usage=self.session.get('usage'); self.context=self.session.get('context')
        for item in self.items.items:
            self.item_by_id[item['id']]=item

    def emit(self,event):
        self.seq += 1; event=copy.deepcopy({'seq':self.seq, **event}); self.ring.append(event); self.ring=self.ring[-500:]
        for queue in list(self.subscribers):
            try: queue.put_nowait(event)
            except asyncio.QueueFull: self.subscribers.discard(queue)
        return event
    def item_event(self,event):
        self.emit(event)
        if not self.flush_handle: self.flush_handle=asyncio.get_running_loop().call_later(1,self.flush)
    def flush(self):
        self.flush_handle=None; self.manager.store.save_items(self.sid,self.items.items)
    def elapsed_ms(self): return int((time.monotonic()-self.running_since)*1000) if self.running_since else None
    def state_change(self,state):
        self.state=state; self.running_since=time.monotonic() if state=='running' else (self.running_since if state=='interrupting' else None); self.last_activity=time.monotonic()
        self.emit({'type':'state','state':state,'elapsed_ms':self.elapsed_ms()}); self.manager.session_state(self.sid)
    def session_changed(self,**values):
        self.manager.store.update(self.sid,**values); self.emit({'type':'session','session':self.manager.view(self.sid)}); self.manager.session_state(self.sid)
    def snapshot(self):
        return dict(type='snapshot',seq=self.seq,session=self.manager.view(self.sid),state=self.state,items=self.items.items,has_more=False,
                    permissions=[r for r,_ in self.permissions.values()],questions=[r for r,_ in self.questions.values()],elapsed_ms=self.elapsed_ms())
    def submit(self,typ,payload=None):
        future=asyncio.get_running_loop().create_future()
        if typ=='send': self._queue_item(payload, future)
        else: asyncio.create_task(self._command(typ,payload,future))
        return future
    def enqueue(self, text, attachments=None, client_id=None):
        future=asyncio.get_running_loop().create_future()
        self._queue_item({'text':text,'attachments':attachments or [],'client_id':client_id}, future)
        return future

    def _queue_item(self,payload,future):
        text=payload.get('text',''); attachments=payload.get('attachments') or []
        if not isinstance(text,str) or (not text and not attachments): raise ValueError('Message is empty')
        item=self.items.add('user',text=text,attachments=attachments,pending=True,queued=bool(self.active or self.queue),client_id=payload.get('client_id'))
        if not self.session['title'] and text: self.session_changed(title=text[:60])
        entry=(item,text,attachments,future)
        if self.active and self.turn_id:
            item.update(pending=False,queued=False,steered=True); self.emit({'type':'patch','id':item['id'],'patch':{'pending':False,'queued':False,'steered':True}})
            asyncio.create_task(self._steer(item,text,attachments,future))
        else:
            self.queue.append(entry); self._ensure_worker()
    def _ensure_worker(self):
        if not self.worker or self.worker.done(): self.worker=asyncio.create_task(self._worker())
    async def _command(self,typ,payload,future):
        try:
            if typ in ('connect','reconnect'):
                if typ=='reconnect' and self.process: await self._disconnect()
                await self._connect()
            elif typ=='sleep':
                if self.active or self.queue: raise RuntimeError('Session is running')
                await self._disconnect()
            elif typ=='interrupt':
                if self.active and self.turn_id:
                    self.state_change('interrupting'); await self.process.request('turn/interrupt',{'threadId':self.thread_id,'turnId':self.turn_id})
            elif typ=='set_config': self.session_changed(**self._set_option(payload['config_id'],payload['value']))
            elif typ=='set_mode': self.session_changed(mode=payload['mode_id'], modes={**(self.session.get('modes') or {}),'currentModeId':payload['mode_id']})
            if not future.done(): future.set_result(None)
        except Exception as exc:
            if not future.done(): future.set_exception(exc)
    async def _connect(self):
        if self.process and self.process.alive and self.thread_id: return
        agent=self.manager.agent(self.sid and self.session['agent_id'])
        process=await self.manager.process_for(agent)
        self.process=process; self.state_change('connecting')
        if self.thread_id:
            try:
                result=await process.request('thread/resume',{'threadId':self.thread_id,'cwd':self.session['cwd'],'excludeTurns':True,**self._thread_settings(agent)})
            except CodexRpcError:
                self.items.notice('warn','Remote thread was gone; started a new one (earlier context is not available to the agent)')
                self.thread_id=None
        if not self.thread_id:
            result=await process.request('thread/start',{'cwd':self.session['cwd'],**self._thread_settings(agent),'serviceName':'next-agent'})
            thread=result.get('thread') or {}; self.thread_id=thread.get('id') or result.get('threadId')
            self.session_changed(remote_id=self.thread_id)
        self._apply_thread_result(result)
        self.state_change('idle')
    def _thread_settings(self,agent):
        mode=MODES[agent.mode]; config={'model_reasoning_summary':'auto'}
        if agent.effort: config['model_reasoning_effort']=agent.effort
        out={'approvalPolicy':mode['approvalPolicy'],'sandbox':mode['sandboxPolicy'],'config':config}
        if agent.model: out['model']=agent.model
        if agent.instructions: out['developerInstructions']=agent.instructions
        return out
    def _apply_thread_result(self,result):
        if result.get('model') is not None: self.session_changed(model=result.get('model'))
        if result.get('reasoningEffort') is not None: self.session_changed(effort=result.get('reasoningEffort'))
        self.session_changed(config_options=self._options(),modes=self._modes())
    def _options(self):
        agent=self.manager.agent(self.session['agent_id']); current=self.session.get('model') or agent.model
        models=self.manager.models(agent.id)
        values=[{'value':m.get('model') or m.get('id',''),'name':m.get('displayName') or m.get('name') or m.get('id',''),'description':m.get('description','')} for m in models]
        return [{'id':'model','name':'Model','category':'model','type':'select','currentValue':current,'options':values},
                {'id':'effort','name':'Reasoning','category':'thought_level','type':'select','currentValue':self.session.get('effort') or agent.effort,
                 'options':[{'value':e,'name':e.title(),'description':''} for e in (self.manager.model_efforts(current) or ['low','medium','high','xhigh','max'])]}]
    def _modes(self):
        return {'currentModeId':self.session.get('mode') or self.manager.agent(self.session['agent_id']).mode,
                'availableModes':[{'id':k,'name':v['name'],'description':v['description']} for k,v in MODES.items()]}
    def _set_option(self,key,value):
        if key=='model': return {'model':value,'effort':self.session.get('effort','') if value else '' ,'config_options':self._options()}
        if key=='effort': return {'effort':value,'config_options':self._options()}
        raise ValueError('Unknown config option')
    async def _worker(self):
        try:
            while self.queue:
                item,text,attachments,future=self.queue.pop(0)
                if future.cancelled(): continue
                await self._run_turn(item,text,attachments,future)
        finally:
            if self.queue: self._ensure_worker()
    async def _run_turn(self,item,text,attachments,future):
        self.active=(item,future); self.items.begin(); self.state_change('connecting')
        try:
            await self._connect(); self.state_change('running'); item.update(pending=False,queued=False); self.emit({'type':'patch','id':item['id'],'patch':{'pending':False,'queued':False}})
            input=[{'type':'text','text':text,'text_elements':[]}]
            for attachment in attachments:
                if attachment.get('is_image'): input.append({'type':'localImage','path':attachment['path']})
                else: input[0]['text'] += '\nAttached file: '+attachment['path']
            result=await self.process.request('turn/start',{'threadId':self.thread_id,'input':input,'cwd':self.session['cwd'],**self._turn_settings()})
            turn=result.get('turn') or {}; self.turn_id=turn.get('id') or result.get('turnId')
            await self._wait_turn()
        except Exception as exc:
            self._finish('disconnected',str(exc)); return
        self._finish(self.session.pop('_last_stop_reason','completed'),None)
    def _turn_settings(self):
        agent=self.manager.agent(self.session['agent_id']); mode=MODES[agent.mode]; out={'summary':'auto','approvalPolicy':mode['approvalPolicy'],'sandboxPolicy':mode['sandboxPolicy']}
        if self.session.get('model'): out['model']=self.session['model']
        if self.session.get('effort'): out['effort']=self.session['effort']
        return out
    async def _wait_turn(self):
        self._turn_done=asyncio.Event(); await self._turn_done.wait()
    async def _steer(self,item,text,attachments,future):
        try:
            input=[{'type':'text','text':text,'text_elements':[]}]
            await self.process.request('turn/steer',{'threadId':self.thread_id,'expectedTurnId':self.turn_id,'clientUserMessageId':item['id'],'input':input})
            if not future.done(): future.set_result(dict(session_id=self.sid,text='',stop_reason='steered',is_error=False,error=None))
        except CodexRpcError:
            self.queue.insert(0,(item,text,attachments,future)); self._ensure_worker()
    def _finish(self,reason,error):
        if not self.active: return
        item,future=self.active; self.items.finish_stream(); self.permissions.clear(); self.questions.clear()
        if error: self.items.notice('error',error)
        self.items.add('result',stop_reason=reason,duration_ms=self.elapsed_ms() or 0,usage=self.session.get('usage'))
        self.session_changed(turns=self.session.get('turns',0)+1,preview=''.join(self.turn_text)[-140:],unread=not bool(self.viewers),usage=self.session.get('usage'),context=self.session.get('context'))
        self.flush(); self.turn_id=None; self.active=None; self.session['_last_stop_reason']=reason; self.state_change('idle' if self.process and self.process.alive else 'offline')
        if not future.done(): future.set_result(dict(session_id=self.sid,text=''.join(self.turn_text),stop_reason=reason,is_error=bool(error),error=error))
        if hasattr(self,'_turn_done'): self._turn_done.set()
    async def _disconnect(self):
        self.process=None; self.state_change('offline'); self.flush()
    async def on_notification(self,method,p):
        if p.get('threadId') not in (None,self.thread_id): return
        if method=='__exit__':
            self.process=None
            for request, future in list(self.permissions.values()):
                if not future.done(): future.set_result(None)
            for request, future in list(self.questions.values()):
                if not future.done(): future.set_result(None)
            self.permissions.clear(); self.questions.clear()
            if self.active: self._finish('disconnected','Codex app-server disconnected')
            self.state_change('offline'); return
        if method=='item/agentMessage/delta':
            item=self._text_item(p['itemId'],'text',p.get('phase')); self._delta(item,'text',p.get('delta','')); self.turn_text.append(p.get('delta',''))
        elif method in ('item/reasoning/summaryTextDelta','item/reasoning/textDelta'):
            item=self._text_item(p['itemId'],'thinking'); self._delta(item,'text',p.get('delta',''))
        elif method=='item/commandExecution/outputDelta':
            item=self._tool_item(p['itemId'],'execute',p); self._delta(item,'output',p.get('delta',''))
        elif method=='item/started': self._item_started(p.get('item') or {})
        elif method=='item/completed': self._item_completed(p.get('item') or {})
        elif method=='item/fileChange/patchUpdated':
            item=self._tool_item(p['itemId'],'edit',p); self.items.patch(item,changes=p.get('changes') or [],streaming=True)
        elif method=='thread/tokenUsage/updated':
            usage=p.get('tokenUsage') or {}; total=usage.get('total') or {}; last=usage.get('last') or {}
            self.session_changed(usage={'input':total.get('inputTokens',0),'cached_input':total.get('cachedInputTokens',0),'output':total.get('outputTokens',0),'reasoning':total.get('reasoningOutputTokens',0)},context={'used':last.get('totalTokens',0),'max':usage.get('modelContextWindow')})
        elif method=='turn/completed':
            turn=p.get('turn') or {}; self.session['_last_stop_reason']={'completed':'completed','interrupted':'interrupted','failed':'error'}.get(turn.get('status'),'completed');
            if turn.get('error'): self.items.notice('error',turn['error'].get('message',str(turn['error'])))
            if hasattr(self,'_turn_done'): self._turn_done.set()
        elif method=='error' and p.get('willRetry') is False: self.items.notice('error',str(p.get('error')))
        elif method in ('item/plan/updated','item/plan/delta'):
            plan=p.get('plan') or p.get('entries') or []; self._plan(plan)
    def _text_item(self,iid,kind,phase=None):
        item=self.item_by_id.get(iid)
        if not item:
            item=self.items.add(kind,text='',streaming=True,**({'phase':{'final_answer':'final','commentary':'commentary'}.get(phase) if kind=='text' else None} if kind=='text' else {})); self.item_by_id[iid]=item
        return item
    def _delta(self,item,field,text):
        item[field]=item.get(field,'')+text; self.emit({'type':'delta','id':item['id'],'field':field,'text':text})
    def _tool_item(self,iid,kind,p):
        item=self.item_by_id.get(iid)
        if not item: item=self.items.add('tool',tool_use_id=iid,name=p.get('item',{}).get('type',kind),tool_kind=kind,input={},status='in_progress',locations=[],result=None,streaming=True); self.item_by_id[iid]=item
        return item
    def _item_started(self,item):
        iid=item.get('id'); typ=item.get('type'); self.item_by_id[iid]=self.item_by_id.get(iid) or self._item_from_wire(item,True)
    def _item_completed(self,item):
        iid=item.get('id'); existing=self.item_by_id.get(iid) or self._item_from_wire(item,False)
        self._apply_wire(existing,item); self.items.patch(existing,streaming=False)
    def _item_from_wire(self,item,streaming):
        typ=item.get('type','other')
        if typ=='agentMessage': out=self._text_item(item['id'],'text',item.get('phase')); self.items.patch(out,text=item.get('text',''),streaming=streaming); return out
        if typ=='reasoning': out=self._text_item(item['id'],'thinking'); self.items.patch(out,text='\n'.join(item.get('summary') or item.get('content') or []),streaming=streaming); return out
        kinds={'commandExecution':'execute','fileChange':'edit','mcpToolCall':'mcp','webSearch':'search'}
        if typ in kinds: out=self._tool_item(item['id'],kinds[typ],item); self._apply_wire(out,item); return out
        out=self.items.add('tool',tool_use_id=item['id'],name=typ,tool_kind='other',input=item,status='completed',locations=[],result=None,streaming=streaming); self.item_by_id[item['id']]=out; return out
    def _apply_wire(self,out,item):
        typ=item.get('type')
        if typ=='commandExecution': self.items.patch(out,command=item.get('command',''),cwd=item.get('cwd',''),output=item.get('aggregatedOutput',''),exit_code=item.get('exitCode'),duration_ms=item.get('durationMs'),status='failed' if item.get('status')=='failed' else 'completed',result={'content':item.get('aggregatedOutput',''),'is_error':item.get('status')=='failed','images':[],'diffs':[]})
        elif typ=='fileChange':
            changes=[]
            for change in item.get('changes') or []: changes.append({'path':change.get('path',''),'kind':(change.get('kind') or {}).get('type',change.get('kind','update')),'move_path':(change.get('kind') or {}).get('move_path'),'diff':change.get('diff','')})
            self.items.patch(out,changes=changes,status='completed',result={'content':'','is_error':False,'images':[],'diffs':[{'path':c['path'],'old_text':None,'new_text':c['diff']} for c in changes]})
        elif typ=='mcpToolCall': self.items.patch(out,server=item.get('server',''),tool=item.get('tool',''),input=item.get('arguments') or {},status='completed',result={'content':'','is_error':item.get('status')=='failed','images':[],'diffs':[],'raw':item})
        elif typ=='webSearch': self.items.patch(out,query=item.get('query',''),url=item.get('url',''),status='completed')
    def _plan(self,entries):
        item=next((i for i in self.items.items if i['kind']=='plan' and i.get('_turn')==self.turn_id),None)
        values=[{'content':e.get('text') or e.get('content',''),'status':{'inProgress':'in_progress','completed':'completed'}.get(e.get('status'),e.get('status','pending')),'priority':e.get('priority')} for e in entries]
        if item: self.items.patch(item,entries=values)
        else: item=self.items.add('plan',entries=values); item['_turn']=self.turn_id
    async def on_request(self,method,p):
        if method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval','item/permissions/requestApproval'):
            rid=uuid4().hex; options=[]
            for d in p.get('availableDecisions') or ['accept','acceptForSession','decline']:
                mapped={'accept':('allow_once','Allow'),'acceptForSession':('allow_always','Allow for this session'),'decline':('reject_once','Decline'),'cancel':('cancel','Cancel')}.get(d)
                if mapped: options.append({'option_id':mapped[0],'name':mapped[1],'kind':mapped[0]})
            request={'id':rid,'session_id':self.sid,'tool_call':{'title':p.get('command') or method,'tool_kind':'execute' if 'command' in method else 'edit', 'command':p.get('command'),'cwd':p.get('cwd'),'reason':p.get('reason')},'options':options,'created_at':now()}
            future=asyncio.get_running_loop().create_future(); self.permissions[rid]=(request,future); self.emit({'type':'permission','request':request}); self.manager.session_state(self.sid)
            option=await future; return {'decision': {'allow_once':'accept','allow_always':'acceptForSession','reject_once':'decline','cancel':'cancel'}.get(option,'cancel')}
        if method=='item/tool/requestUserInput':
            rid=uuid4().hex; request={'id':rid,'session_id':self.sid,'questions':p.get('questions') or [],'created_at':now()}; future=asyncio.get_running_loop().create_future(); self.questions[rid]=(request,future); self.emit({'type':'question','request':request}); self.manager.session_state(self.sid); return await future
        self.items.notice('warn','Unsupported Codex request: '+method); raise CodexRpcError({'code':-32601,'message':'Method not found'})
    def reply_permission(self,rid,option):
        request,future=self.permissions.pop(rid); self.emit({'type':'permission_resolved','id':rid,'option_id':option}); future.set_result(option); self.manager.session_state(self.sid)
    def reply_question(self,rid,answers):
        request,future=self.questions.pop(rid); self.emit({'type':'question_resolved','id':rid}); future.set_result({'answers':answers} if answers is not None else None); self.manager.session_state(self.sid)
    async def close(self):
        if self.worker and not self.worker.done(): self.worker.cancel(); await asyncio.gather(self.worker,return_exceptions=True)
        await self._disconnect()
