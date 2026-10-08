"""Persistent session workers and event feeds."""
import asyncio
import os
import logging
import time
from uuid import uuid4
from collections import deque
from claude_agent_sdk import ClaudeSDKClient, ResultMessage, UserMessage
from .history import load_items, page, transcript_parent
from .items import ItemBuilder, is_synthetic_message

TERMINAL={'completed','failed','stopped','killed'}
from .options import build_options
from .permissions import PermissionRegistry
from .config import now
from .pricing import process_cost

log = logging.getLogger(__name__)

class ResizableSemaphore:
    """A FIFO concurrency gate whose capacity can change while clients are live."""
    def __init__(self, capacity):
        self.capacity = capacity
        self.active = 0
        self.waiters = deque()

    async def acquire(self):
        if self.active < self.capacity and not self.waiters:
            self.active += 1
            return True
        future = asyncio.get_running_loop().create_future()
        self.waiters.append(future)
        try:
            await future
            return True
        except asyncio.CancelledError:
            if future.done():
                self.active -= 1
                self._wake()
            else:
                self.waiters.remove(future)
            raise

    def release(self):
        self.active -= 1
        self._wake()

    def resize(self, capacity):
        self.capacity = capacity
        self._wake()

    def _wake(self):
        while self.active < self.capacity and self.waiters:
            future = self.waiters.popleft()
            if not future.done():
                self.active += 1
                future.set_result(True)

class SessionRuntime:
    def __init__(self, manager, sid):
        self.manager, self.sid = manager, sid
        self.session = manager.index.sessions[sid]
        self.state = 'offline'
        self.seq = 0
        self.ring = deque(maxlen=2000)
        self.subscribers = set()
        self.commands = asyncio.Queue()
        self.items = ItemBuilder(manager.index.uploads)
        self.permissions = PermissionRegistry(self)
        self.worker = None
        self.client = None
        self.history_base = None
        self.last_activity = time.monotonic()
        self.written = 0
        self.last_process_cost = 0.0
        self.stderr_tail = deque(maxlen=50)
        self.restart_needed = False
        self.queue_position = 0
        self.resume_at = None
        self.truncate_uuid = None
        self.fresh_session_id = None
        self.file_refs_cache = None

    def emit(self, event):
        self.seq += 1
        event = {'seq':self.seq,**event}
        self.ring.append(event)
        for queue in list(self.subscribers):
            try: queue.put_nowait(event)
            except asyncio.QueueFull:
                self.subscribers.discard(queue)
                queue.get_nowait()
                queue.put_nowait({'type':'__overflow__'})
        return event

    def state_change(self,state):
        self.state = state
        self.last_activity = time.monotonic()
        self.emit({'type':'state','state':state,'queue_position':self.queue_position})
        self.manager.session_state(self)

    def persist_override(self,key,value):
        self.session['overrides'][key]=value or None
        self.manager.index.update(self.sid,overrides=self.session['overrides'])
        self.emit({'type':'session','session':self.manager.view(self.sid)})

    def submit(self,command):
        self.commands.put_nowait(command)
        if not self.worker or self.worker.done():
            self.worker=asyncio.create_task(self._worker())

    def _reply_error(self, command, message):
        req_id = command[2] if len(command)>2 else None
        queue = command[3] if len(command)>3 else None
        event = {'type':'error','req_id':req_id,'message':message,'seq':self.seq}
        if queue:
            try: queue.put_nowait(event)
            except asyncio.QueueFull: self.subscribers.discard(queue)
        else:
            self.emit(event)

    async def all_items(self):
        if self.history_base is None:
            source = self.session
            if not source.get('sdk_session_id') and source.get('fork_of'):
                source = self.manager.index.sessions.get(source['fork_of']['session_id'], source)
            agent = self.manager.agent(source['agent_id'])
            history = await asyncio.to_thread(load_items,source,agent,self.manager.index.uploads)
            if source is not self.session and self.session['fork_of'].get('at_uuid'):
                at = self.session['fork_of']['at_uuid']
                end = next((i for i,x in enumerate(history) if x.get('uuid')==at),len(history)-1)
                history=history[:end+1]
        else: history = self.history_base
        if self.truncate_uuid:
            end=next((i for i,x in enumerate(history) if x['kind']=='user' and
                      not x.get('parent_tool_use_id') and x.get('uuid')==self.truncate_uuid),None)
            if end is not None: history=history[:end]
        return history + list(self.items.items)

    async def snapshot(self):
        data = page(await self.all_items())
        return {'type':'snapshot','seq':self.seq,'session':self.manager.view(self.sid),'state':self.state,
                **data,'permissions':[p.request for p in self.permissions.pending.values()],
                'init':self.items.init,'tasks':list(self.items.tasks.values()),'queue_position':self.queue_position,
                'activity':self.items.activity}

    async def _connect(self):
        self.queue_position = self.manager.queue_position()
        self.state_change('queued')
        await self.manager.semaphore.acquire()
        self.queue_position = 0
        self.state_change('starting')
        try:
            agent = self.manager.agent(self.session['agent_id'])
            fork = self.session.get('fork_of') if not self.session.get('sdk_session_id') else None
            source = self.manager.index.sessions.get(fork['session_id']) if fork else None
            history_source = source or self.session
            history_agent = self.manager.agent(history_source['agent_id'])
            self.history_base = await asyncio.to_thread(load_items,history_source,history_agent,self.manager.index.uploads)
            if self.fresh_session_id:
                self.history_base = []
            elif self.truncate_uuid:
                end=next((i for i,x in enumerate(self.history_base) if x['kind']=='user' and
                          not x.get('parent_tool_use_id') and x.get('uuid')==self.truncate_uuid),None)
                if end is not None: self.history_base=self.history_base[:end]
            if fork and fork.get('at_uuid'):
                at = fork['at_uuid']
                end = next((i for i,x in enumerate(self.history_base) if x.get('uuid')==at),len(self.history_base)-1)
                self.history_base = self.history_base[:end+1]
            pending = [dict(x) for x in self.items.items if x['kind']=='user' and x.get('pending')]
            self.items = ItemBuilder(self.manager.index.uploads)
            for value in pending:
                self.items.items.append(value)
                self.items.pending.append(value['id'])
            resume = source.get('sdk_session_id') if source else self.session.get('sdk_session_id')
            opts = build_options(agent,self.session,self.manager.config.config.defaults,self.manager.config.config.server,
                                 self.permissions.make_can_use_tool(),resume=resume,fork=bool(fork),
                                 resume_at=fork.get('at_uuid') if fork else None,
                                 resume_session_at=self.resume_at,
                                 new_session_id=self.fresh_session_id or self.sid if not resume else None,
                                 stderr=self.stderr_tail.append,
                                 custom_md_path=self.manager.paths.agents/agent.id/'CLAUDE.md')
            self.client = ClaudeSDKClient(opts)
            await self.client.connect()
            self.resume_at=None
            self.last_process_cost=0
            self.state_change('idle')
            return True
        except Exception as exc:
            self.connect_error=str(exc)
            log.exception('CLI connection failed')
            self.emit(self.items.notice('error',f'CLI connection failed: {exc}\n'+ '\n'.join(self.stderr_tail)))
            while self.items.pending:
                self.emit(self.items.patch(self.items.pending.popleft(),{'pending':False}))
            retained=[]
            while not self.commands.empty():
                queued=self.commands.get_nowait()
                self.commands.task_done()
                if queued[0]=='send': self._reply_error(queued,f'CLI connection failed: {exc}')
                else: retained.append(queued)
            for queued in retained: self.commands.put_nowait(queued)
            if self.client:
                try: await asyncio.wait_for(self.client.disconnect(),timeout=3)
                except Exception: log.exception('Failed to close client after connection error')
            self.manager.semaphore.release()
            self.client=None
            self.state_change('offline')
            return False

    async def _disconnect(self):
        self.permissions.cancel_all()
        if self.items.activity is not None: self.emit({'type':'activity','activity':None})
        if self.client:
            try: await asyncio.wait_for(self.client.disconnect(),timeout=3)
            except Exception: log.exception('CLI disconnect failed')
            self.client=None
            self.manager.semaphore.release()
        self.state_change('offline')
        self.history_base=None
        self.items=ItemBuilder(self.manager.index.uploads)

    async def _worker(self):
        incoming = None
        commands = None
        iterator = None
        try:
            while True:
                if not self.client:
                    if incoming and not incoming.done():
                        incoming.cancel()
                        incoming = None
                    command = await self.commands.get()
                    if command[0]=='shutdown': break
                    if command[0]=='send':
                        if not await self._connect():
                            self._reply_error(command,f'CLI connection failed: {self.connect_error}')
                            self.commands.task_done()
                            continue
                        iterator = self.client.receive_messages().__aiter__()
                        incoming = asyncio.create_task(iterator.__anext__())
                    else:
                        previous_client=self.client
                        await self._offline_command(command)
                        if self.client is not previous_client and self.client:
                            iterator=self.client.receive_messages().__aiter__()
                            incoming=asyncio.create_task(iterator.__anext__())
                        self.commands.task_done()
                        continue
                else:
                    command = None
                if command is None:
                    commands = asyncio.create_task(self.commands.get())
                    done,_ = await asyncio.wait({incoming,commands},return_when=asyncio.FIRST_COMPLETED)
                    if incoming in done:
                        try: msg = incoming.result()
                        except StopAsyncIteration:
                            self.emit(self.items.notice('error','CLI stream ended unexpectedly'))
                            await self._disconnect()
                            if commands not in done: commands.cancel()
                            continue
                        except Exception as exc:
                            self.emit(self.items.notice('error',f'CLI stream failed: {exc}'))
                            await self._disconnect()
                            if commands not in done: commands.cancel()
                            continue
                        previous_client=self.client
                        await self._message(msg)
                        if self.client is not previous_client:
                            if self.client:
                                iterator=self.client.receive_messages().__aiter__()
                                incoming=asyncio.create_task(iterator.__anext__())
                            else:
                                incoming=None
                        else:
                            incoming = asyncio.create_task(iterator.__anext__())
                    if commands in done: command = commands.result()
                    else: commands.cancel()
                if command:
                    if command[0]=='shutdown':
                        self.commands.task_done()
                        break
                    previous_client=self.client
                    await self._command(command)
                    if self.client is not previous_client:
                        if incoming and not incoming.done(): incoming.cancel()
                        if self.client:
                            iterator=self.client.receive_messages().__aiter__()
                            incoming=asyncio.create_task(iterator.__anext__())
                        else: incoming=None
                    self.commands.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception('Session worker failed')
            self.emit(self.items.notice('error',f'Session worker failed: {exc}'))
        finally:
            for task in (incoming,commands):
                if task and not task.done(): task.cancel()
            if self.client: await self._disconnect()
            self.permissions.cancel_all()

    async def _offline_command(self,command):
        typ=command[0]
        if typ=='edit':
            try: await self._edit(command[1],command)
            except Exception as exc:
                self.emit(self.items.notice('error',f'edit failed: {exc}'))
                self._reply_error(command,f'edit failed: {exc}')
        elif typ in ('set_model','set_mode','set_effort'):
            self.persist_override({'set_model':'model','set_mode':'permission_mode','set_effort':'effort'}[typ],command[1])
            if typ=='set_model' and self.session.get('sdk_session_id'):
                self.emit(self.items.notice('info',f"Model switched to {command[1] or 'default'}"))

    async def _query(self, content):
        sdk_id=self.session.get('sdk_session_id') or self.fresh_session_id or self.sid
        async def one():
            yield {'type':'user','message':{'role':'user','content':content},
                   'parent_tool_use_id':None,'session_id':sdk_id}
        await self.client.query(one(),session_id=sdk_id)
        self.written += 1
        if self.state=='idle': self.state_change('running')

    async def _edit(self,payload,command):
        uuid=payload['uuid']
        if self.state not in ('offline','idle') or not self.session.get('sdk_session_id'):
            self._reply_error(command,'Edit requires an idle or offline session with history')
            return
        items=await self.all_items()
        if not any(x['kind']=='user' and not x.get('parent_tool_use_id') and x.get('uuid')==uuid for x in items):
            self._reply_error(command,'Message is not a top-level user message')
            return
        agent=self.manager.agent(self.session['agent_id'])
        if payload.get('rewind_files') and agent.enable_file_checkpointing:
            if not self.client and not await self._connect():
                self._reply_error(command,f'CLI connection failed: {self.connect_error}')
                return
            try: await self.client.rewind_files(uuid)
            except Exception as exc:
                self.emit(self.items.notice('error',f'File rewind failed: {exc}'))
                self._reply_error(command,f'File rewind failed: {exc}')
                return
        try: parent=await asyncio.to_thread(transcript_parent,self.session['sdk_session_id'],agent.cwd,uuid)
        except Exception as exc:
            self._reply_error(command,f'Cannot find edit point: {exc}')
            return
        self.emit({'type':'truncate','uuid':uuid})
        if self.client: await self._disconnect()
        self.resume_at=parent
        self.truncate_uuid=uuid
        if parent is None:
            self.session['sdk_session_id']=None
            self.session['fork_of']=None
            self.manager.index.update(self.sid,sdk_session_id=None,fork_of=None)
            self.fresh_session_id=str(uuid4())
        self.emit(self.items.pending_user(payload['text'],payload['attachments'],payload['client_id']))
        if not await self._connect():
            self._reply_error(command,f'CLI connection failed: {self.connect_error}')
            return
        await self._query(payload['content'])

    async def _command(self,command):
        typ=command[0]
        try:
            if typ=='send':
                await self._query(command[1]['content'])
            elif typ=='edit': await self._edit(command[1],command)
            elif typ=='interrupt':
                self.permissions.cancel_all()
                self.state_change('interrupting')
                await self.client.interrupt()
                self.emit(self.items.notice('info','Interrupted'))
            elif typ=='set_mode':
                self.persist_override('permission_mode',command[1])
                await self.client.set_permission_mode(command[1])
            elif typ=='set_model':
                self.persist_override('model',command[1])
                await self.client.set_model(command[1] or None)
                self.emit(self.items.notice('info',f"Model switched to {command[1] or 'default'}"))
            elif typ=='set_effort':
                self.persist_override('effort',command[1])
                if self.state=='idle':
                    await self._disconnect()
                    if not await self._connect():
                        self._reply_error(command,f'CLI connection failed: {self.connect_error}')
                else: self.restart_needed=True
            elif typ=='stop_task':
                if not str(command[1]).startswith('cron:'): await self.client.stop_task(command[1])
            elif typ=='rewind':
                await self.client.rewind_files(command[1])
                self.emit(self.items.notice('info','Files rewound'))
        except Exception as exc:
            self.emit(self.items.notice('error',f'{typ} failed: {exc}'))
            self._reply_error(command,f'{typ} failed: {exc}')

    async def _message(self,msg):
        if isinstance(msg,UserMessage) and not is_synthetic_message(msg) and not (isinstance(msg.content,list) and any(getattr(x,'tool_use_id',None) for x in msg.content)):
            self.written=max(0,self.written-1)
        events=self.items.consume(msg)
        if self.truncate_uuid and isinstance(msg,UserMessage) and any(e.get('type')=='patch' and e.get('patch',{}).get('uuid')==msg.uuid for e in events):
            self.truncate_uuid=None
            self.fresh_session_id=None
            self.resume_at=None
        if isinstance(msg,ResultMessage):
            cost=process_cost(msg,self.manager.config.config.pricing)
            delta=max(0,cost-self.last_process_cost)
            self.last_process_cost=cost
            self.session['total_cost_usd'] += delta
            self.session['turns'] += msg.num_turns
            self.session['sdk_session_id']=self.items.sdk_session_id or msg.session_id
            text=next((x['text'] for x in reversed(self.items.items) if x['kind']=='text'),None)
            if text: self.session['preview']=text[:140]
            self.manager.index.update(self.sid,**self.session)
            result_event=next((e for e in events if e.get('item',{}).get('kind')=='result'),None)
            if result_event: result_event['item'].update(cost_usd=delta,total_cost_usd=self.session['total_cost_usd'])
            try:
                context=await asyncio.wait_for(self.client.get_context_usage(),timeout=2)
                self.session['context']={'used':context['totalTokens'],'max':context['maxTokens'],'percent':context['percentage']}
                self.manager.index.update(self.sid,context=self.session['context'])
            except Exception: pass
            self.state_change('running' if self.written else 'idle')
            if self.restart_needed and not self.written:
                self.restart_needed=False
                await self._disconnect()
                await self._connect()
            await self.manager.extensions.emit('turn_result',session_id=self.sid,agent_id=self.session['agent_id'],
                                              result_item=next((e['item'] for e in events if e.get('item',{}).get('kind')=='result'),None))
            events.append({'type':'session','session':self.manager.view(self.sid)})
        elif self.items.sdk_session_id and self.session.get('sdk_session_id')!=self.items.sdk_session_id:
            self.session['sdk_session_id']=self.items.sdk_session_id
            self.manager.index.update(self.sid,sdk_session_id=self.items.sdk_session_id)
        for event in events: self.emit(event)
        self.last_activity=time.monotonic()

class RuntimeManager:
    def __init__(self,paths,config,index,extensions):
        self.paths,self.config,self.index,self.extensions=paths,config,index,extensions
        self.runtimes={}
        self.semaphore=ResizableSemaphore(config.config.server.max_concurrent)
        self.global_subscribers=set()
        self.reaper_task=None
        self.external_queues={}
        self.external_workers={}

    def agent(self,aid):
        return next(a for a in self.config.config.agents if a.id==aid)

    def get_or_create(self,sid):
        if sid not in self.index.sessions: raise KeyError(sid)
        return self.runtimes.setdefault(sid,SessionRuntime(self,sid))

    def view(self,sid):
        runtime=self.runtimes.get(sid)
        return {**self.index.sessions[sid],'state':runtime.state if runtime else 'offline',
                'pending':len(runtime.permissions.pending) if runtime else 0}

    def external_send(self,aid,prompt,sid=None):
        """Queue an external message. Messages for one agent run strictly one after another."""
        self.agent(aid)
        if sid and self.index.sessions.get(sid,{}).get('agent_id')!=aid: raise KeyError(sid)
        if not sid:
            sid=self.index.create(aid,prompt[:60])['id']
            self.session_state(self.get_or_create(sid))
        queue=self.external_queues.setdefault(aid,asyncio.Queue())
        queue.put_nowait((sid,prompt))
        worker=self.external_workers.get(aid)
        if not worker or worker.done():
            self.external_workers[aid]=asyncio.create_task(self._external_worker(aid,queue))
        return sid

    async def _external_worker(self,aid,queue):
        while not queue.empty():
            sid,prompt=queue.get_nowait()
            try: await self._external_turn(sid,prompt)
            except Exception: log.exception('External send failed')

    async def _external_turn(self,sid,prompt):
        if sid not in self.index.sessions: return
        runtime=self.get_or_create(sid)
        events=asyncio.Queue(maxsize=10000)
        runtime.subscribers.add(events)
        try:
            # Wait for any turn already running in this session (e.g. started from the web UI).
            while runtime.state not in ('idle','offline'): await self._next_state(runtime,events)
            if not runtime.session['title']:
                runtime.session['title']=prompt[:60]
                self.index.update(sid,title=prompt[:60])
                self.session_state(runtime)
            runtime.emit(runtime.items.pending_user(prompt,[],None))
            req_id='external-'+sid
            runtime.submit(('send',{'content':prompt},req_id,events))
            started=False
            while True:
                event=await events.get()
                if event.get('type')=='error' and event.get('req_id')==req_id: return
                if event.get('type')!='state': continue
                if event['state']=='running': started=True
                elif event['state']=='offline' or (started and event['state']=='idle'): return
        finally: runtime.subscribers.discard(events)

    async def _next_state(self,runtime,events):
        while True:
            event=await events.get()
            if event.get('type') in ('state','__overflow__'): return

    def queue_position(self):
        return sum(r.state=='queued' for r in self.runtimes.values())

    def global_emit(self,event):
        for queue in list(self.global_subscribers):
            try: queue.put_nowait(event)
            except asyncio.QueueFull:
                self.global_subscribers.discard(queue)
                queue.get_nowait()
                queue.put_nowait({'type':'__overflow__'})

    def session_state(self,runtime):
        s=runtime.session
        self.global_emit({'type':'session_state','session_id':runtime.sid,'agent_id':s['agent_id'],
                          'state':runtime.state,'pending':len(runtime.permissions.pending),
                          'title':s['title'],'updated_at':s['updated_at'],'preview':s['preview']})
        asyncio.create_task(self.extensions.emit('session_state',session_id=runtime.sid,agent_id=s['agent_id'],state=runtime.state))

    async def reaper(self,interval=30):
        while True:
            await asyncio.sleep(interval)
            timeout=self.config.config.server.idle_timeout_min*60
            if timeout<=0: continue  # 0 disables idle sleep
            for runtime in list(self.runtimes.values()):
                # Sleeping the CLI would kill its background shells, subagents and in-process cron jobs.
                busy=any(t.get('kind')=='cron' or t.get('status') not in TERMINAL for t in runtime.items.tasks.values())
                if runtime.state=='idle' and not busy and not runtime.permissions.pending and time.monotonic()-runtime.last_activity>timeout:
                    runtime.submit(('shutdown',))

    async def stop(self,sid):
        runtime=self.runtimes.get(sid)
        if runtime and runtime.worker and not runtime.worker.done():
            runtime.submit(('shutdown',))
            try: await asyncio.wait_for(runtime.worker,timeout=5)
            except asyncio.TimeoutError: runtime.worker.cancel()

    async def shutdown(self):
        if self.reaper_task: self.reaper_task.cancel()
        await asyncio.wait_for(asyncio.gather(*(self.stop(sid) for sid in list(self.runtimes)),return_exceptions=True),timeout=10)

    def memory_mb(self):
        def rss(pid):
            try:
                for line in open(f'/proc/{pid}/status'):
                    if line.startswith('VmRSS:'): return int(line.split()[1])/1024
            except OSError: pass
            return 0
        total=rss(os.getpid())
        for entry in os.scandir('/proc'):
            if entry.name.isdigit():
                try:
                    status=open(f'/proc/{entry.name}/status').read()
                    if f'PPid:\t{os.getpid()}\n' in status: total+=rss(entry.name)
                except OSError: pass
        return round(total,1)
