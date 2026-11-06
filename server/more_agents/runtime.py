"""One connection-owning worker per ACP session, plus the public module API."""
import asyncio
import copy
import re
import secrets
import time
from collections import deque
from uuid import uuid4
import tomlkit
from fastapi import HTTPException
from pydantic import ValidationError
from .kinds.acp.client import AcpConnection, AcpError
from .config import AcpAgent, CodexAgent, MoreAgentsConfig, now
from .items import Items
from .store import page
from .kinds.codex.process import CodexProcess
from .kinds.codex.adapter import CodexRuntime


class AcpRuntime:
    def __init__(self, manager, sid):
        self.manager, self.sid = manager, sid
        self.session = manager.store.sessions[sid]
        self.state = 'offline'
        self.seq = 0
        self.ring = deque(maxlen=500)
        self.subscribers = set()
        self.viewers = 0
        self.commands = asyncio.Queue()
        self.queued = deque()
        self.worker = self.client = self.turn = self.active = None
        self.permissions = {}
        self.running_since = None
        self.last_activity = time.monotonic()
        self.replaying = False
        self.flush_handle = None
        self.items = Items(manager.store.load_items(sid), self.item_event)
        recovered = any(i.get('streaming') or i.get('pending') for i in self.items.items)
        for item in self.items.items:
            if item.get('streaming'): item['streaming'] = False
            if item.get('pending'): item.update(pending=False, queued=False, cancelled=True)
        if recovered: self.manager.store.save_items(sid, self.items.items)

    def emit(self, event):
        self.seq += 1
        event = copy.deepcopy({'seq': self.seq, **event})
        self.ring.append(event)
        for queue in list(self.subscribers):
            try: queue.put_nowait(event)
            except asyncio.QueueFull:
                self.subscribers.discard(queue)
                queue.get_nowait()
                queue.put_nowait({'type': '__overflow__'})
        return event

    def item_event(self, event):
        self.emit(event)
        if not self.flush_handle: self.flush_handle = asyncio.get_running_loop().call_later(1, self.flush)

    def flush(self):
        if self.flush_handle: self.flush_handle.cancel()
        self.flush_handle = None
        self.manager.store.save_items(self.sid, self.items.items)

    def elapsed_ms(self):
        return int((time.monotonic()-self.running_since)*1000) if self.running_since is not None else None

    def state_change(self, state):
        self.state = state
        if state=='running': self.running_since = time.monotonic()
        elif state!='interrupting': self.running_since = None
        self.last_activity = time.monotonic()
        self.emit({'type': 'state', 'state': state, 'elapsed_ms': self.elapsed_ms()})
        self.manager.session_state(self.sid)

    def session_changed(self, **values):
        self.manager.store.update(self.sid, **values)
        self.emit({'type': 'session', 'session': self.manager.view(self.sid)})
        self.manager.session_state(self.sid)

    def snapshot(self):
        return dict(type='snapshot', seq=self.seq, session=self.manager.view(self.sid), state=self.state,
                    **page(self.items.items), permissions=[r for r, f in self.permissions.values()], elapsed_ms=self.elapsed_ms())

    def submit(self, typ, payload=None):
        future = asyncio.get_running_loop().create_future()
        self.commands.put_nowait((typ, payload, future))
        if not self.worker or self.worker.done(): self.worker = asyncio.create_task(self._worker())
        return future

    def enqueue(self, text, attachments=None, client_id=None):
        attachments = attachments or []
        if not isinstance(text, str) or not text and not attachments: raise ValueError('Message is empty')
        queued = self.active is not None or bool(self.queued) or any(i.get('pending') for i in self.items.items)
        item = self.items.add('user', text=text, attachments=attachments, pending=True, queued=queued, client_id=client_id)
        if not self.session['title'] and text: self.session_changed(title=text[:60])
        return self.submit('send', {'item': item, 'text': text, 'attachments': attachments})

    async def _permission(self, method, params):
        if method!='session/request_permission': raise AcpError(-32601, 'Method not found')
        if params.get('sessionId')!=self.session['remote_id']: raise AcpError(-32602, 'Unknown session')
        if self.replaying or self.state=='interrupting': return {'outcome': {'outcome': 'cancelled'}}
        if not isinstance(params.get('toolCall'), dict) or not isinstance(params.get('options'), list):
            raise AcpError(-32602, 'Invalid permission request')
        options = [dict(option_id=o['optionId'], name=o['name'], kind=o['kind']) for o in params['options']]
        if any(not all(isinstance(v, str) for v in o.values()) for o in options): raise AcpError(-32602, 'Invalid permission options')
        pid = uuid4().hex
        request = dict(id=pid, session_id=self.sid, tool_call=params['toolCall'], options=options, created_at=now())
        future = asyncio.get_running_loop().create_future()
        self.permissions[pid] = (request, future)
        self.emit({'type': 'permission', 'request': request})
        self.manager.session_state(self.sid)
        try:
            option = await future
            return {'outcome': {'outcome': 'selected', 'optionId': option} if option is not None else {'outcome': 'cancelled'}}
        finally:
            if pid in self.permissions: self.reply_permission(pid, None)

    def reply_permission(self, pid, option):
        if pid not in self.permissions: raise ValueError('Permission request is not pending')
        request, future = self.permissions[pid]
        if option is not None and option not in [o['option_id'] for o in request['options']]: raise ValueError('Unknown permission option')
        del self.permissions[pid]
        if not future.done(): future.set_result(option)
        self.emit({'type': 'permission_resolved', 'id': pid, 'option_id': option})
        self.manager.session_state(self.sid)

    def cancel_permissions(self):
        for pid in list(self.permissions): self.reply_permission(pid, None)

    def _notification(self, method, params):
        if method!='session/update' or self.replaying: return
        if params.get('sessionId')!=self.session['remote_id']: return
        update = params['update']
        self.items.consume(update)
        kind = update.get('sessionUpdate')
        if kind=='available_commands_update': self.session_changed(commands=update['availableCommands'])
        elif kind=='current_mode_update':
            self.session_changed(modes={**(self.session['modes'] or {'availableModes': []}), 'currentModeId': update['currentModeId']})
        elif kind=='config_option_update': self.session_changed(config_options=update['configOptions'])
        elif kind=='session_info_update' and 'title' in update: self.session_changed(title=update['title'])

    def _options(self, result):
        values = {target: result[source] for source, target in (('modes', 'modes'), ('configOptions', 'config_options')) if source in result}
        if values: self.session_changed(**values)

    async def _connect(self):
        if self.client and not self.client.closed.done(): return
        if self.client: await self._disconnect()
        agent = self.manager.agent(self.session['agent_id'])
        self.state_change('connecting')
        self.client = AcpConnection(self._permission, self._notification)
        await self.client.open(agent.host, agent.port, agent.token)
        await self.client.initialize(self.manager.core.version)
        self.manager.info[agent.id] = self.client.info
        self.manager.changed_event()
        loaded = False
        if self.session['remote_id'] and self.client.capabilities.get('loadSession'):
            self.replaying = True
            try:
                result = await self.client.request('session/load', {'sessionId': self.session['remote_id'], 'cwd': self.session.get('cwd', agent.cwd), 'mcpServers': []})
                loaded = True
            except AcpError:
                self.items.notice('warn', 'Remote session was gone; started a new one (earlier context is not available to the agent)')
            finally: self.replaying = False
        if not loaded:
            result = await self.client.request('session/new', {'cwd': self.session.get('cwd', agent.cwd), 'mcpServers': []})
            remote_id = result['sessionId']
            if not isinstance(remote_id, str): raise ValueError('Invalid remote session id')
            self.session_changed(remote_id=remote_id, modes=None, config_options=[], commands=[])
        self._options(result)
        if not loaded:
            for key, value in agent.config_defaults.items():
                self._options(await self.client.request('session/set_config_option', {'sessionId': self.session['remote_id'], 'configId': key, 'value': value}))
        self.state_change('idle')

    async def _disconnect(self):
        self.cancel_permissions()
        if self.client: await self.client.close()
        self.client = None
        self.state_change('offline')
        self.flush()

    async def _start(self):
        payload, future = self.queued.popleft()
        self.active = (payload, future)
        self.items.begin()
        try:
            await self._connect()
            self.state_change('running')
            prompt = self.manager.store.prompt(payload['text'], payload['attachments'], self.client.capabilities.get('promptCapabilities', {}))
            self.turn = await self.client.begin_request('session/prompt', {'sessionId': self.session['remote_id'], 'prompt': prompt})
            self.items.patch(payload['item'], pending=False, queued=False)
        except Exception as exc:
            self.items.patch(payload['item'], pending=False, queued=False)
            self._finish('disconnected', str(exc))
            await self._disconnect()

    def _finish(self, reason, error=None):
        if not self.active: return
        payload, future = self.active
        self.cancel_permissions()
        self.items.finish_stream()
        if payload['item'].get('pending'): self.items.patch(payload['item'], pending=False, queued=False)
        if error: self.items.notice('error', error)
        self.items.add('result', stop_reason=reason, duration_ms=self.elapsed_ms() or 0)
        result = dict(session_id=self.sid, text=''.join(self.items.turn_text), stop_reason=reason)
        if error: result.update(is_error=True, error=error)
        self.session_changed(turns=self.session['turns']+1, preview=self.items.last_text[:140], unread=not bool(self.viewers))
        self.flush()
        self.turn = self.active = None
        self.state_change('idle' if self.client and not self.client.closed.done() else 'offline')
        if not future.done(): future.set_result(result)

    async def _command(self, command):
        typ, payload, future = command
        try:
            if typ=='send':
                self.queued.append((payload, future))
                return
            if typ=='interrupt':
                self.cancel_permissions()
                if self.turn:
                    self.state_change('interrupting')
                    await self.client.notify('session/cancel', {'sessionId': self.session['remote_id']})
            elif typ=='cancel_queued':
                found = next((entry for entry in self.queued if entry[0]['item']['id']==payload), None)
                if not found: raise ValueError('Message was already delivered')
                self.queued.remove(found)
                self.items.patch(found[0]['item'], pending=False, queued=False, cancelled=True)
                if not found[1].done(): found[1].set_result(dict(session_id=self.sid, text='', stop_reason='cancelled'))
            elif typ=='sleep':
                if self.active or self.queued: raise HTTPException(409, 'Session is running')
                await self._disconnect()
            elif typ=='connect':
                await self._connect()
                self.last_activity = time.monotonic()
            elif typ=='reconnect':
                if self.active or self.queued: raise HTTPException(409, 'Session is running')
                await self._disconnect()
                await self._connect()
            elif typ in ('set_config', 'set_mode'):
                await self._connect()
                if typ=='set_config':
                    self._options(await self.client.request('session/set_config_option', {'sessionId': self.session['remote_id'], 'configId': payload['config_id'], 'value': payload['value']}))
                else:
                    await self.client.request('session/set_mode', {'sessionId': self.session['remote_id'], 'modeId': payload['mode_id']})
                    self.session_changed(modes={**(self.session['modes'] or {'availableModes': []}), 'currentModeId': payload['mode_id']})
                self.last_activity = time.monotonic()
            else: raise ValueError('Unknown command')
            if not future.done(): future.set_result(None)
        except asyncio.CancelledError:
            if not future.done(): future.cancel()
            raise
        except Exception as exc:
            if self.state=='connecting': await self._disconnect()
            if not future.done(): future.set_exception(exc)

    async def _worker(self):
        incoming = None
        try:
            while True:
                if self.turn and self.turn.done():
                    try:
                        result = self.turn.result()
                        reason = result['stopReason']
                        if reason not in ('end_turn', 'max_tokens', 'max_turn_requests', 'refusal', 'cancelled'):
                            raise ValueError('Invalid prompt stop reason')
                    except AcpError as exc: self._finish('error', str(exc))
                    except Exception as exc:
                        self._finish('disconnected', str(exc))
                        await self._disconnect()
                    else: self._finish(reason)
                if self.client and self.client.closed.done(): await self._disconnect()
                if not self.active and self.queued and self.commands.empty() and not (incoming and incoming.done()):
                    await self._start()
                    continue
                if incoming is None: incoming = asyncio.create_task(self.commands.get())
                waiting = {incoming}
                if self.turn: waiting.add(self.turn)
                if self.client: waiting.add(self.client.closed)
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if incoming in done:
                    command = incoming.result()
                    incoming = None
                    try: await self._command(command)
                    finally: self.commands.task_done()
        finally:
            if incoming:
                if incoming.done() and not incoming.cancelled():
                    command = incoming.result()
                    self.commands.put_nowait(command)
                    self.commands.task_done()
                else:
                    incoming.cancel()
                    await asyncio.gather(incoming, return_exceptions=True)
            pending_turn = self.turn
            self._finish('disconnected', 'ACP connection closed')
            await self._disconnect()
            if pending_turn and pending_turn.done() and not pending_turn.cancelled(): pending_turn.exception()
            while not self.commands.empty():
                typ, payload, future = self.commands.get_nowait()
                self.commands.task_done()
                if typ=='send': self.queued.append((payload, future))
                elif not future.done(): future.cancel()
            for payload, future in self.queued:
                self.items.patch(payload['item'], pending=False, queued=False, cancelled=True)
                if not future.done(): future.set_result(dict(session_id=self.sid, text='', stop_reason='disconnected', is_error=True, error='ACP connection closed'))
            self.queued.clear()
            self.flush()

    async def close(self):
        if self.worker and not self.worker.done():
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        elif self.flush_handle: self.flush()


class MoreAgentsManager:
    def __init__(self, core, config, store):
        self.core, self.config, self.store = core, config, store
        self.runtimes = {}
        self.info = {}
        self.processes = {}
        self.model_cache = {}
        self._results = {}
        self.process_lock = asyncio.Lock()

    async def startup(self):
        for sid, session in self.store.sessions.items():
            session.setdefault('kind', getattr(self.agent(session['agent_id']), 'kind', 'acp'))
            session.setdefault('cwd', getattr(self.agent(session['agent_id']), 'cwd', '/'))
            self.session_state(sid)

    async def process_for(self, agent):
        async with self.process_lock:
            if agent.id in self.processes and self.processes[agent.id].alive: return self.processes[agent.id]
            async def notification(method, params):
                if method == '__exit__':
                    for runtime in list(self.runtimes.values()):
                        if runtime.session['agent_id'] == agent.id: await runtime.on_notification(method, params)
                    self.processes.pop(agent.id, None); return
                thread = params.get('threadId')
                for runtime in list(self.runtimes.values()):
                    if runtime.session['agent_id'] == agent.id and runtime.thread_id == thread:
                        await runtime.on_notification(method, params)
            async def request(method, params):
                thread = params.get('threadId')
                runtime = next((r for r in self.runtimes.values() if r.session['agent_id'] == agent.id and r.thread_id == thread), None)
                if runtime: return await runtime.on_request(method, params)
                raise RuntimeError('Unknown Codex thread')
            process = CodexProcess(agent, notification, request, self.core.version)
            await process.start(); self.processes[agent.id] = process
            try:
                result = await process.request('model/list', {'includeHidden': False})
                models = result.get('data') if isinstance(result, dict) else result
                self.model_cache[agent.id] = models or []
                from ..paths import atomic_write
                atomic_write(self.store.root / 'models' / f'{agent.id}.json', __import__('json').dumps(self.model_cache[agent.id], ensure_ascii=False, indent=2))
            except Exception: self.model_cache.setdefault(agent.id, [])
            return process

    def models(self, aid):
        if aid in self.model_cache: return self.model_cache[aid]
        path=self.store.root/'models'/f'{aid}.json'
        if path.exists():
            self.model_cache[aid]=__import__('json').loads(path.read_text()); return self.model_cache[aid]
        return []

    def model_efforts(self, model):
        for item in self.model_cache.values():
            for m in item:
                if m.get('id') == model or m.get('model') == model:
                    return m.get('supportedReasoningEfforts') or m.get('reasoningEfforts') or []
        return []

    async def prepare(self, sid):
        runtime=self.runtime(sid)
        if runtime.state=='offline':
            try: await runtime.submit('connect')
            except Exception as exc: runtime.items.notice('error', str(exc)); runtime.state_change('offline')

    def running(self):
        rows=[]
        for sid, runtime in self.runtimes.items():
            view=self.view(sid)
            if view['state'] in ('running','interrupting') or view['pending']:
                agent=self.agent(view['agent_id']); rows.append(dict(module='more_agents',session_id=sid,agent_id=agent.id,agent_name=agent.name,avatar=agent.avatar,title=view['title'],state=view['state'],pending=view['pending'],unread=view['unread'],updated_at=view['updated_at'],preview=view['preview'],cwd=view['cwd']))
        return rows

    def kinds(self):
        return [{'kind':'acp','name':'ACP','description':'Connect to an ACP endpoint'}, {'kind':'codex','name':'Codex','description':'Run native Codex app-server'}]


    def agent(self, aid):
        agent = next((a for a in self.config.data.agents if a.id==aid), None)
        if not agent: raise HTTPException(404, 'Agent not found')
        return agent

    def session(self, sid):
        if sid not in self.store.sessions: raise HTTPException(404, 'Session not found')
        return self.store.sessions[sid]

    def runtime(self, sid):
        self.session(sid)
        if sid not in self.runtimes:
            kind = self.session(sid).get('kind', getattr(self.agent(self.session(sid)['agent_id']), 'kind', 'acp'))
            self.runtimes[sid] = CodexRuntime(self, sid) if kind == 'codex' else AcpRuntime(self, sid)
        return self.runtimes[sid]

    def view(self, sid):
        runtime = self.runtimes.get(sid)
        session=self.session(sid)
        return {**session, 'kind': session.get('kind', getattr(self.agent(session['agent_id']), 'kind', 'acp')), 'state': runtime.state if runtime else 'offline', 'pending': (len(runtime.permissions) + len(getattr(runtime, 'questions', {}))) if runtime else 0, 'config_options': session.get('config_options', []), 'modes': session.get('modes'), 'commands': session.get('commands', []), 'usage': session.get('usage'), 'context': session.get('context')}

    def items(self, sid):
        self.session(sid)
        return self.runtime(sid).items.items

    def agent_view(self, agent):
        sessions = sorted((s for s in self.store.sessions.values() if s['agent_id']==agent.id), key=lambda s: s['updated_at'], reverse=True)
        runtimes = [self.runtimes[s['id']] for s in sessions if s['id'] in self.runtimes]
        status = dict(running=sum(r.state in ('running', 'interrupting') for r in runtimes),
                      live=sum(bool(getattr(r, 'client', None) and r.client.writer and not r.client.closed.done()) or bool(getattr(r, 'process', None) and r.process.alive) for r in runtimes),
                      pending=sum(len(r.permissions) + len(getattr(r, 'questions', {})) for r in runtimes),
                      last_session={k: sessions[0][k] for k in ('id', 'title', 'updated_at', 'preview')} if sessions else None)
        return {**agent.model_dump(), 'status': status, 'info': self.info.get(agent.id), 'capabilities': {'images': True, 'steer': agent.kind == 'codex', 'modes': True, 'local_cwd': agent.kind == 'codex'}, 'recent': [self.view(s['id']) for s in sessions[:5]]}

    def agents(self):
        return [self.agent_view(a) for a in sorted(self.config.data.agents, key=lambda a: (a.order, a.created_at))]

    def session_state(self, sid):
        session = self.view(sid)
        self.core.emit({'type': 'session_state', 'module': 'more_agents', 'session_id': sid,
                        **{k: session[k] for k in ('agent_id', 'state', 'pending', 'unread', 'title', 'updated_at', 'preview')}})

    def changed_event(self):
        self.core.emit({'type': 'more_agents_agents_changed'})

    async def changed(self):
        for sid in list(self.store.sessions):
            if self.store.sessions[sid]['agent_id'] not in {a.id for a in self.config.data.agents}: await self.delete_session(sid)
        self.changed_event()

    def create_session(self, aid, title='', origin='ui', parent=None, cwd=None):
        agent = self.agent(aid)
        if agent.kind == 'codex':
            import os
            path = os.path.realpath(os.path.expanduser(str(cwd or agent.cwd)))
            if not os.path.isdir(path): raise HTTPException(400, 'cwd must be an existing directory')
            cwd = path
        else:
            cwd = str(cwd or agent.cwd)
        session = self.store.create(aid, title, origin, parent, kind=agent.kind, cwd=cwd)
        if agent.kind == 'codex':
            session.update(model=getattr(agent, 'model', ''), effort=getattr(agent, 'effort', ''), mode=getattr(agent, 'mode', 'full-access'))
            self.store.save()
        asyncio.create_task(self.prepare(session['id']))
        self.session_state(session['id'])
        return self.view(session['id'])

    def _turn(self, aid, prompt, session_id=None, title='', origin='workflow', parent=None, on_session=None, cwd=None, model='', effort=''):
        self.agent(aid)
        if session_id:
            if self.session(session_id)['agent_id']!=aid: raise ValueError('Session belongs to another agent')
        else: session_id = self.create_session(aid, title, origin, parent, cwd=cwd)['id']
        if model or effort:
            if model: self.store.update(session_id, model=model)
            if effort: self.store.update(session_id, effort=effort)
        if on_session: on_session(session_id)
        return session_id, self.runtime(session_id).enqueue(prompt)

    async def run_turn(self, agent_id, prompt, *, session_id=None, title='', origin='workflow', parent=None, on_session=None, cwd=None, model='', effort=''):
        sid, future = self._turn(agent_id, prompt, session_id, title, origin, parent, on_session, cwd, model, effort)
        return await asyncio.shield(future)

    def start_turn(self, agent_id, prompt, *, session_id=None, title='', origin='subagent', parent=None, cwd=None, model='', effort=''):
        return self._turn(agent_id, prompt, session_id, title, origin, parent, cwd=cwd, model=model, effort=effort)[0]

    async def send(self, session_id, prompt):
        return self.runtime(session_id).enqueue(prompt)

    async def wait_turn(self, sid):
        runtime=self.runtime(sid)
        if runtime.active: return await asyncio.shield(runtime.active[1])
        return self._results.get(sid, dict(session_id=sid,text='',stop_reason='completed',is_error=False,error=None))

    async def stop(self, session_id):
        await self.runtime(session_id).submit('interrupt')

    async def sleep(self, sid):
        runtime = self.runtime(sid)
        if runtime.active or runtime.queued or runtime.state not in ('offline', 'idle'): raise HTTPException(409, 'Session is running')
        await runtime.submit('sleep')
        return self.view(sid)

    async def connect(self, sid, fresh=False):
        runtime = self.runtime(sid)
        if fresh and (runtime.active or runtime.queued or runtime.state not in ('offline', 'idle')):
            raise HTTPException(409, 'Session is running')
        await runtime.submit('reconnect' if fresh else 'connect')
        return self.view(sid)

    def mark_read(self, sid):
        if self.session(sid)['unread']:
            self.store.update(sid, unread=False)
            if sid in self.runtimes: self.runtimes[sid].emit({'type': 'session', 'session': self.view(sid)})
            self.session_state(sid)
        return self.view(sid)

    async def delete_session(self, sid):
        self.session(sid)
        if sid in self.runtimes: await self.runtimes[sid].close()
        self.runtimes.pop(sid, None)
        self.store.delete(sid)
        self.changed_event()

    async def reaper(self):
        while True:
            await asyncio.sleep(30)
            timeout = self.config.data.server.idle_timeout_min*60
            if timeout:
                for runtime in list(self.runtimes.values()):
                    if runtime.state=='idle' and not runtime.queued and time.monotonic()-runtime.last_activity>timeout:
                        try:
                            await runtime.submit('sleep')
                            if runtime.state != 'offline': await runtime._disconnect()
                            if isinstance(runtime, CodexRuntime) and not any(r.process and r.process.alive for r in self.runtimes.values() if r is not runtime and r.session['agent_id'] == runtime.session['agent_id']):
                                process=self.processes.pop(runtime.session['agent_id'], None)
                                if process: await process.close()
                        except HTTPException: pass

    async def close(self):
        await asyncio.gather(*(runtime.close() for runtime in self.runtimes.values()))
        await asyncio.gather(*(p.close() for p in self.processes.values()), return_exceptions=True)
        self.processes.clear()

    async def create_agent(self, data):
        data = dict(data)
        if not data.get('id'):
            if not isinstance(data.get('name'), str): raise HTTPException(422, 'name is required')
            data['id'] = re.sub(r'[^a-z0-9]+', '-', data['name'].lower()).strip('-')[:40] or 'agent-'+secrets.token_hex(3)
        data.setdefault('kind', 'acp')
        try: agent = (CodexAgent if data.get('kind') == 'codex' else AcpAgent).model_validate(data)
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        if any(a.id==agent.id for a in self.config.data.agents): raise HTTPException(409, 'Agent id already exists')
        if agent.group and agent.group not in self.config.data.groups: raise HTTPException(422, 'Unknown group')
        if 'agents' not in self.config.doc: self.config.doc['agents'] = tomlkit.aot()
        self.config.doc['agents'].append(tomlkit.item(agent.model_dump()))
        self.config.save()
        self.changed_event()
        return self.agent_view(self.agent(agent.id))

    async def patch_agent(self, aid, data):
        agent = self.agent(aid)
        fields = type(agent).model_fields
        data = {k: v for k, v in data.items() if k in fields}
        if data.get('id', aid)!=aid: raise HTTPException(400, 'Agent id is immutable')
        if data.get('token') is None: data.pop('token', None)
        data.pop('created_at', None)
        try: updated = type(agent).model_validate({**agent.model_dump(), **data})
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        if updated.group and updated.group not in self.config.data.groups: raise HTTPException(422, 'Unknown group')
        entry = next(e for e in self.config.doc['agents'] if e['id']==aid)
        for key in data: entry[key] = getattr(updated, key)
        self.config.save()
        self.changed_event()
        return self.agent_view(self.agent(aid))

    async def delete_agent(self, aid):
        self.agent(aid)
        for sid, session in list(self.store.sessions.items()):
            if session['agent_id']==aid: await self.delete_session(sid)
        entries = self.config.doc['agents']
        for i, entry in enumerate(entries):
            if entry['id']==aid:
                del entries[i]
                break
        self.config.save()
        (self.store.avatars / aid).unlink(missing_ok=True)
        (self.store.avatars / (aid+'.mime')).unlink(missing_ok=True)
        self.info.pop(aid, None)
        self.changed_event()

    def reorder(self, ids):
        actual = {a.id for a in self.config.data.agents}
        if len(ids)!=len(actual) or set(ids)!=actual: raise HTTPException(400, 'ids must contain every agent exactly once')
        for entry in self.config.doc.get('agents', []): entry['order'] = ids.index(entry['id'])
        self.config.save()
        self.changed_event()

    def set_groups(self, groups, renames):
        try: groups = MoreAgentsConfig(groups=groups).groups
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        for entry in self.config.doc.get('agents', []):
            group = renames.get(entry.get('group', ''), entry.get('group', ''))
            entry['group'] = group if group in groups else ''
        self.config.doc['groups'] = groups
        self.config.save()
        self.changed_event()
        return groups
