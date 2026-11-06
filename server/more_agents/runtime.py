"""Session coordinator: event replay, FIFO turns, prompts and persistence."""
import asyncio
import copy
import time
from collections import deque
from uuid import uuid4
from fastapi import HTTPException
from .config import now
from .items import Items
from .store import page
from .kinds.base import TurnEnded, TurnError

class SessionRuntime:
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
        self.worker = self.turn = self.active = None
        self.permissions, self.questions = {}, {}
        self.running_since = None
        self.last_activity = time.monotonic()
        self.flush_handle = self.warm_future = self.last_future = None
        self.steered = []
        self.items = Items(manager.store.load_items(sid), self.item_event)
        recovered = False
        for item in self.items.items:
            if item.get('streaming'): item['streaming'] = False; recovered = True
            if item.get('pending'): item.update(pending=False, queued=False, cancelled=True); recovered = True
        if recovered: manager.store.save_items(sid, self.items.items)
        self.adapter = manager.kind(self.session['kind']).adapter(self)

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
                    **page(self.items.items), permissions=[r for r, f in self.permissions.values()], questions=[r for r, f in self.questions.values()], elapsed_ms=self.elapsed_ms())

    def submit(self, typ, payload=None):
        future = asyncio.get_running_loop().create_future()
        self.commands.put_nowait((typ, payload, future))
        if not self.worker or self.worker.done(): self.worker = asyncio.create_task(self._worker())
        return future

    def enqueue(self, text, attachments=None, client_id=None, *, steer=True, model='', effort=''):
        attachments = attachments or []
        if not isinstance(text, str) or not text and not attachments: raise ValueError('Message is empty')
        queued = self.active is not None or bool(self.queued) or any(i.get('pending') for i in self.items.items)
        item = self.items.add('user', text=text, attachments=attachments, pending=True, queued=queued, client_id=client_id)
        if not self.session['title'] and text: self.session_changed(title=text[:60])
        payload = dict(item=item, text=text, attachments=attachments, steer=steer, model=model, effort=effort)
        future = self.submit('send', payload)
        self.last_future = future
        return future

    async def ask_permission(self, tool, options, native_id=None):
        return await self.ask('permission', dict(tool_call=tool, options=options), native_id)

    async def ask_question(self, questions, native_id=None):
        return await self.ask('question', dict(questions=questions), native_id)

    async def ask(self, typ, fields, native_id):
        if self.state == 'interrupting': return None
        pid = uuid4().hex
        request = dict(id=pid, session_id=self.sid, **fields, created_at=now())
        future = asyncio.get_running_loop().create_future()
        future.native_id = native_id
        pending = self.permissions if typ == 'permission' else self.questions
        pending[pid] = (request, future)
        self.emit({'type': typ, 'request': request})
        self.manager.session_state(self.sid)
        try: return await future
        finally:
            if pid in pending: self.resolve(typ, pid, None)

    def resolve(self, typ, pid, value):
        pending = self.permissions if typ == 'permission' else self.questions
        if pid not in pending: raise ValueError('Request is not pending')
        request, future = pending[pid]
        if typ == 'permission' and value is not None and value not in [o['option_id'] for o in request['options']]: raise ValueError('Unknown permission option')
        if typ == 'question' and value is not None and set(value) - {q['id'] for q in request['questions']}: raise ValueError('Unknown question')
        del pending[pid]
        if not future.done(): future.set_result(value)
        self.emit({'type': typ + '_resolved', 'id': pid, **({'option_id': value} if typ == 'permission' else {})})
        self.manager.session_state(self.sid)

    def reply_permission(self, pid, value): self.resolve('permission', pid, value)
    def reply_question(self, pid, value): self.resolve('question', pid, value)

    def cancel_prompts(self, native_id=None):
        for typ, pending in (('permission', self.permissions), ('question', self.questions)):
            for pid, (_, future) in list(pending.items()):
                if native_id is None or future.native_id == native_id: self.resolve(typ, pid, None)

    async def connect(self):
        if self.adapter.connected: return
        await self.adapter.disconnect()
        self.state_change('connecting')
        await self.adapter.connect()
        self.state_change('idle')

    async def disconnect(self):
        self.cancel_prompts()
        await self.adapter.disconnect()
        self.state_change('offline')
        self.flush()

    async def apply_choices(self, model, effort):
        for category, value in (('model', model), ('thought_level', effort)):
            if not value: continue
            option = next((o for o in self.session['config_options'] if o.get('category') == category), None)
            if option: await self.adapter.set_option(option['id'], value)

    async def _start(self):
        payload, future = self.queued.popleft()
        self.active = (payload, future)
        self.items.begin()
        try:
            await self.connect()
            await self.apply_choices(payload['model'], payload['effort'])
            self.state_change('running')
            self.items.patch(payload['item'], pending=False, queued=False)
            self.turn = await self.adapter.run_turn(payload['text'], payload['attachments'])
        except TurnError as exc:
            self.finish('error', str(exc))
        except Exception as exc:
            self.finish('disconnected', str(exc))
            await self.disconnect()

    def finish(self, reason, error=None, usage=None, duration_ms=None):
        if not self.active: return
        payload, future = self.active
        self.cancel_prompts()
        self.items.finish()
        if payload['item'].get('pending'): self.items.patch(payload['item'], pending=False, queued=False)
        if error: self.items.notice('error', error)
        self.items.add('result', stop_reason=reason, duration_ms=duration_ms if duration_ms is not None else self.elapsed_ms() or 0,
                       **({'usage': usage} if usage is not None else {}))
        result = dict(session_id=self.sid, text=''.join(self.items.turn_text), stop_reason=reason,
                      is_error=bool(error) or reason in ('error', 'disconnected'), error=error)
        self.session_changed(turns=self.session['turns']+1, preview=self.items.last_text[:140], unread=not bool(self.viewers))
        self.flush()
        self.turn = self.active = None
        self.state_change('idle' if self.adapter.connected else 'offline')
        for waiting in [future, *self.steered]:
            if not waiting.done(): waiting.set_result(result)
        self.steered.clear()

    async def _command(self, command):
        typ, payload, future = command
        try:
            if typ == 'send':
                if payload['steer'] and self.active and self.turn and not self.turn.done() and self.state == 'running' and self.manager.kind(self.session['kind']).capabilities['steer']:
                    try: await self.adapter.steer(payload['text'], payload['attachments'])
                    except TurnEnded: pass
                    else:
                        self.items.patch(payload['item'], pending=False, queued=False, steered=True)
                        self.steered.append(future)
                        return
                self.queued.append((payload, future))
                return
            if typ == 'interrupt':
                self.cancel_prompts()
                if self.turn:
                    self.state_change('interrupting')
                    await self.adapter.interrupt()
            elif typ == 'cancel_queued':
                found = next((entry for entry in self.queued if entry[0]['item']['id'] == payload), None)
                if not found: raise ValueError('Message was already delivered')
                self.queued.remove(found)
                self.items.patch(found[0]['item'], pending=False, queued=False, cancelled=True)
                if not found[1].done(): found[1].set_result(dict(session_id=self.sid, text='', stop_reason='cancelled', is_error=False, error=None))
            elif typ == 'sleep':
                if self.active or self.queued: raise HTTPException(409, 'Session is running')
                await self.disconnect()
            elif typ in ('prepare', 'connect', 'reconnect'):
                if typ == 'reconnect':
                    if self.active or self.queued: raise HTTPException(409, 'Session is running')
                    await self.disconnect()
                await self.connect()
            elif typ in ('set_config', 'set_mode'):
                await self.connect()
                if typ == 'set_config': await self.adapter.set_option(payload['config_id'], payload['value'])
                else: await self.adapter.set_mode(payload['mode_id'])
                self.last_activity = time.monotonic()
            else: raise ValueError('Unknown command')
            if not future.done(): future.set_result(None)
        except asyncio.CancelledError:
            if not future.done(): future.cancel()
            raise
        except Exception as exc:
            if self.state == 'connecting': await self.disconnect()
            if typ == 'send':
                self.items.patch(payload['item'], pending=False, queued=False, cancelled=True)
                self.items.notice('error', str(exc))
                if not future.done(): future.set_result(dict(session_id=self.sid, text='', stop_reason='error', is_error=True, error=str(exc)))
            elif typ == 'prepare':
                self.items.notice('error', str(exc)); self.flush()
                if not future.done(): future.set_result(None)
            elif not future.done(): future.set_exception(exc)

    async def _worker(self):
        incoming = None
        try:
            while True:
                if self.turn and self.turn.done():
                    try: result = self.turn.result()
                    except TurnError as exc: self.finish('error', str(exc))
                    except Exception as exc:
                        self.finish('disconnected', str(exc))
                        await self.disconnect()
                    else: self.finish(**result)
                if self.adapter.closed and self.adapter.closed.done():
                    if self.active: self.finish('disconnected', str(self.adapter.closed.result()))
                    else: self.items.notice('warn', str(self.adapter.closed.result()))
                    await self.disconnect()
                if not self.active and self.queued and self.commands.empty() and not (incoming and incoming.done()):
                    await self._start()
                    continue
                if incoming is None: incoming = asyncio.create_task(self.commands.get())
                waiting = {incoming}
                if self.turn: waiting.add(self.turn)
                if self.adapter.closed: waiting.add(self.adapter.closed)
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if incoming in done:
                    command = incoming.result()
                    incoming = None
                    try: await self._command(command)
                    finally: self.commands.task_done()
        finally:
            if incoming:
                if incoming.done() and not incoming.cancelled():
                    self.commands.put_nowait(incoming.result()); self.commands.task_done()
                else:
                    incoming.cancel(); await asyncio.gather(incoming, return_exceptions=True)
            turn = self.turn
            self.finish('disconnected', 'Agent disconnected')
            await self.disconnect()
            if turn:
                if not turn.done(): turn.cancel()
                await asyncio.gather(turn, return_exceptions=True)
            while not self.commands.empty():
                typ, payload, future = self.commands.get_nowait(); self.commands.task_done()
                if typ == 'send': self.queued.append((payload, future))
                elif not future.done(): future.cancel()
            for payload, future in self.queued:
                self.items.patch(payload['item'], pending=False, queued=False, cancelled=True)
                if not future.done(): future.set_result(dict(session_id=self.sid, text='', stop_reason='disconnected', is_error=True, error='Agent disconnected'))
            self.queued.clear()
            self.flush()

    async def close(self):
        if self.worker and not self.worker.done():
            self.worker.cancel(); await asyncio.gather(self.worker, return_exceptions=True)
        elif self.flush_handle: self.flush()
