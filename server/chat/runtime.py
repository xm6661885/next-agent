"""Persistent chat replies and the module API."""
import asyncio
import copy
import json
import re
import secrets
import time
from collections import deque
from uuid import uuid4
import tomlkit
from fastapi import HTTPException
from pydantic import ValidationError
from . import mcp_tools, providers
from .config import Assistant, ChatConfig, DefaultAssistant, Settings, now
from .store import page


class ChatRuntime:
    def __init__(self, manager, sid):
        self.manager, self.sid = manager, sid
        self.session = manager.store.sessions[sid]
        self.items = manager.store.load_items(sid)
        self.state, self.seq = 'idle', 0
        self.ring = deque(maxlen=500)
        self.subscribers = set()
        self.viewers = 0
        self.task = self.active = None
        self.started = False

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

    def flush(self):
        self.manager.store.save_items(self.sid, [i for i in self.items if not i.get('streaming')])

    def add(self, kind, **fields):
        item = dict(id=uuid4().hex, kind=kind, ts=now(), **fields)
        if kind=='user': item['uuid'] = item['id']
        self.items.append(item)
        self.emit({'type': 'item', 'item': item})
        if not item.get('streaming'): self.flush()
        return item

    def patch(self, item, **fields):
        item.update(fields)
        self.emit({'type': 'patch', 'id': item['id'], 'patch': fields})
        if not item.get('streaming'): self.flush()

    def finish_text(self):
        if self.active:
            self.patch(self.active, streaming=False)
            self.active = None

    def delta(self, kind, text):
        if not isinstance(text, str): raise providers.ProviderError('Invalid text delta')
        if not self.active or self.active['kind']!=kind:
            self.finish_text()
            self.active = self.add(kind, text='', streaming=True)
        self.active['text'] += text
        self.emit({'type': 'delta', 'id': self.active['id'], 'field': 'text', 'text': text})

    def notice(self, text, level='warn'):
        self.finish_text()
        return self.add('notice', text=text, level=level)

    def snapshot(self):
        return copy.deepcopy(dict(type='snapshot', seq=self.seq, session=self.manager.view(self.sid), state=self.state, **page(self.items)))

    def idle(self):
        if self.state=='running': raise ValueError('Still replying')

    def send(self, text, attachments=None, client_id=None, uuid=None):
        self.idle()
        attachments = attachments or []
        if not text.strip() and not attachments: raise ValueError('Message is empty')
        if uuid is not None:
            at = next((i for i, item in enumerate(self.items) if item['kind']=='user' and item['uuid']==uuid), None)
            if at is None: raise ValueError('User message not found')
            del self.items[at:]
            self.flush()
            self.emit({'type': 'truncate', 'uuid': uuid})
        self.add('user', text=text, attachments=attachments, client_id=client_id, pending=False)
        self.manager.update_session(self.sid, preview=text[:120])
        self.start()

    def regenerate(self):
        self.idle()
        at = next((i for i in range(len(self.items)-1, -1, -1) if self.items[i]['kind']=='user'), None)
        if at is None: raise ValueError('No user message to regenerate')
        del self.items[at+1:]
        self.flush()
        self.emit({'type': 'truncate_after', 'uuid': self.items[at]['uuid']})
        self.start()

    def start(self):
        self.state, self.started = 'running', False
        self.emit({'type': 'state', 'state': 'running'})
        self.manager.session_state(self.sid)
        self.task = asyncio.create_task(self.reply())

    async def stop(self):
        task = self.task
        if task and not task.done():
            if not self.started: await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def title(self, model):
        first = next(i for i in self.items if i['kind']=='user')
        fallback = (first['text'] or first['attachments'][0]['name'])[:60]
        try:
            provider, name = self.manager.provider_model(self.manager.config.data.defaults.title_model or model)
            title = await providers.complete(provider, name, [{'role': 'user', 'content': first['text'] or fallback}],
                                             system='Write only a short conversation title, at most 30 characters.')
            title = ' '.join(title.split()).strip('"\'')[:30] or fallback
        except Exception: title = fallback
        if not self.session['title']: self.manager.update_session(self.sid, title=title)

    async def reply(self):
        self.started = True
        started, begin = time.monotonic(), len(self.items)
        usage, reason, model = {'input': 0, 'output': 0}, 'error', ''
        first = not any(i['kind']=='result' for i in self.items)
        try:
            settings = self.manager.resolve(self.sid)
            model = settings['model']
            provider, name = self.manager.provider_model(model)
            async with mcp_tools.tools_for_reply(self.manager.config.data.mcp_servers, list(self.session['mcp']), self.notice) as layer:
                tools = await mcp_tools.list_tools(layer)
                for _ in range(20):
                    calls, round_usage = {}, {'input': 0, 'output': 0}
                    messages = providers.history(self.items, provider.format)
                    async for event in providers.stream(provider, name, messages, settings['system_prompt'], tools,
                                                        settings['effort'], settings['temperature'], settings['max_tokens']):
                        kind = event['type']
                        if kind in ('text', 'thinking'): self.delta(kind, event['text'])
                        elif kind=='block_end': self.finish_text()
                        elif kind=='tool_start':
                            self.finish_text()
                            if event['id'] in calls: raise providers.ProviderError('Duplicate tool call id')
                            calls[event['id']] = self.add('tool', tool_use_id=event['id'], name=event['name'],
                                                         input=event['input'], input_partial='', streaming=True, result=None)
                        elif kind=='tool_args':
                            item = calls[event['id']]
                            item['input_partial'] += event['text']
                            self.emit({'type': 'delta', 'id': item['id'], 'field': 'input_partial', 'text': event['text']})
                        elif kind=='tool_end':
                            item = calls[event['id']]
                            args = json.loads(item['input_partial']) if item['input_partial'] else item['input']
                            if not isinstance(args, dict): raise providers.ProviderError('Tool arguments must be an object')
                            self.patch(item, input=args, streaming=False)
                        elif kind=='usage':
                            for key in usage:
                                if key in event:
                                    count = event[key]
                                    if not isinstance(count, int) or count<0: raise providers.ProviderError('Invalid usage')
                                    usage[key] += count-round_usage[key]
                                    round_usage[key] = count
                        elif kind=='stop': reason = event['reason']
                    self.finish_text()
                    if not calls: break
                    for item in calls.values():
                        if item['streaming']: raise providers.ProviderError('Incomplete tool call')
                        result = await mcp_tools.call_tool(layer, item['name'], item['input'])
                        self.patch(item, result=result)
                else:
                    reason = 'max_rounds'
                    self.notice('Tool round limit reached')
            if first and not self.session['title']: await self.title(model)
        except asyncio.CancelledError:
            reason = 'cancelled'
            self.notice('Stopped', 'info')
        except Exception as exc:
            reason = 'error'
            self.notice(str(exc) or type(exc).__name__, 'error')
        finally:
            self.finish_text()
            for item in self.items[begin:]:
                if item['kind']=='tool' and item.get('result') is None:
                    self.patch(item, streaming=False, result={'content': 'Tool call interrupted', 'is_error': True, 'images': []})
            self.add('result', duration_ms=int((time.monotonic()-started)*1000), usage=usage, model=model, stop_reason=reason)
            self.state = 'idle'
            total = {k: self.session['usage'][k]+usage[k] for k in usage}
            preview = ''.join(i['text'] for i in self.items[begin:] if i['kind']=='text')[:120] or self.session['preview']
            self.manager.update_session(self.sid, usage=total, unread=self.viewers==0, preview=preview)
            self.emit({'type': 'state', 'state': 'idle'})


class ChatManager:
    def __init__(self, core, config, store):
        self.core, self.config, self.store = core, config, store
        self.runtimes = {}

    def assistant(self, aid):
        if aid=='_default': return self.config.data.default_assistant
        assistant = next((a for a in self.config.data.assistants if a.id==aid), None)
        if assistant is None: raise HTTPException(404, 'Assistant not found')
        return assistant

    def session(self, sid):
        if sid not in self.store.sessions: raise HTTPException(404, 'Session not found')
        return self.store.sessions[sid]

    def runtime(self, sid):
        self.session(sid)
        if sid not in self.runtimes: self.runtimes[sid] = ChatRuntime(self, sid)
        return self.runtimes[sid]

    def view(self, sid):
        runtime = self.runtimes.get(sid)
        return {**self.session(sid), 'state': runtime.state if runtime else 'idle'}

    def items(self, sid):
        return self.runtime(sid).items

    def sessions(self, aid):
        self.assistant(aid)
        return sorted((self.view(s['id']) for s in self.store.sessions.values() if s['assistant_id']==aid),
                      key=lambda s: s['updated_at'], reverse=True)

    def assistant_view(self, aid):
        sessions = self.sessions(aid)
        return {**self.assistant(aid).model_dump(), 'id': aid,
                'status': {'running': sum(s['state']=='running' for s in sessions),
                           'last_session': {k: sessions[0][k] for k in ('id', 'title', 'updated_at', 'preview')} if sessions else None}}

    def assistants(self):
        return [self.assistant_view(a.id) for a in sorted(self.config.data.assistants, key=lambda a: (a.order, a.created_at))]

    def changed_event(self):
        self.core.emit({'type': 'chat_changed'})

    async def changed(self):
        ids = {'_default', *(a.id for a in self.config.data.assistants)}
        for sid, session in list(self.store.sessions.items()):
            if session['assistant_id'] not in ids: await self.delete_session(sid)
        self.changed_event()

    def session_state(self, sid):
        session = self.view(sid)
        self.core.emit({'type': 'session_state', 'module': 'chat', 'session_id': sid,
                        **{k: session[k] for k in ('assistant_id', 'state', 'unread', 'title', 'updated_at', 'preview')}})

    def update_session(self, sid, **values):
        self.store.update(sid, **values)
        if sid in self.runtimes: self.runtimes[sid].emit({'type': 'session', 'session': self.view(sid)})
        self.session_state(sid)
        return self.view(sid)

    def create_session(self, aid, title=''):
        assistant = self.assistant(aid)
        mcp = list(dict.fromkeys(self.config.data.defaults.mcp+assistant.mcp))
        session = self.store.create(aid, title, mcp)
        self.session_state(session['id'])
        return self.view(session['id'])

    def mark_read(self, sid):
        if self.session(sid)['unread']: return self.update_session(sid, unread=False)
        return self.view(sid)

    async def delete_session(self, sid):
        self.session(sid)
        if sid in self.runtimes: await self.runtimes[sid].stop()
        self.runtimes.pop(sid, None)
        self.store.delete(sid)
        self.changed_event()

    async def close(self):
        await asyncio.gather(*(r.stop() for r in self.runtimes.values()))

    def resolve(self, sid):
        session = self.session(sid)
        assistant = self.assistant(session['assistant_id']).model_dump()
        defaults = self.config.data.defaults.model_dump()
        values = {}
        for key in Settings.model_fields:
            sentinel = -1 if key=='temperature' else 0 if key=='max_tokens' else ''
            values[key] = next((v for v in (session['overrides'].get(key), assistant[key], defaults[key])
                                if v is not None and v!=sentinel), defaults[key])
        if not values['model']:
            entries = self.config.data.providers
            if entries and entries[0].models: values['model'] = entries[0].id+'/'+entries[0].models[0]
        return values

    def provider_model(self, model):
        pid, _, name = model.partition('/')
        provider = next((p for p in self.config.data.providers if p.id==pid), None)
        if provider is None: raise ValueError('Unknown provider: '+(pid or '(none configured)'))
        if not name: raise ValueError('Model is required')
        return provider, name

    def config_view(self):
        data = self.config.data
        return dict(defaults=data.defaults.model_dump(), mcp_servers={k: v.model_dump(exclude_unset=True) for k, v in data.mcp_servers.items()},
                    providers=[{**p.model_dump(), 'api_key': '', 'api_key_set': bool(p.api_key)} for p in data.providers])

    def save_config(self, changes):
        try: ChatConfig.model_validate({**self.config.data.model_dump(), **changes})
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        for key, value in changes.items():
            if isinstance(value, dict) and key in ('defaults', 'default_assistant'):
                if key not in self.config.doc: self.config.doc[key] = tomlkit.table()
                self.config.doc[key].update(value)
            else: self.config.doc[key] = tomlkit.item(value)
        self.config.save()
        self.changed_event()

    def patch_config(self, body):
        changes = body.model_dump(exclude_unset=True)
        if 'defaults' in changes: changes['defaults'] = {**self.config.data.defaults.model_dump(), **changes['defaults']}
        if 'providers' in changes:
            keys = {p.id: p.api_key for p in self.config.data.providers}
            for provider in changes['providers']:
                if 'api_key' not in provider: provider['api_key'] = keys.get(provider['id'], '')
        self.save_config(changes)
        return self.config_view()

    def create_assistant(self, body):
        data = dict(body)
        if not data.get('id'):
            if not isinstance(data.get('name'), str): raise HTTPException(422, 'name is required')
            data['id'] = re.sub(r'[^a-z0-9]+', '-', data['name'].lower()).strip('-')[:40] or 'assistant-'+secrets.token_hex(3)
        try: assistant = Assistant.model_validate(data)
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        if any(a.id==assistant.id for a in self.config.data.assistants): raise HTTPException(409, 'Assistant id already exists')
        self.save_config({'assistants': [a.model_dump() for a in self.config.data.assistants]+[assistant.model_dump()]})
        return self.assistant_view(assistant.id)

    def patch_assistant(self, aid, body):
        current = self.assistant(aid)
        if body.get('id', aid)!=aid: raise HTTPException(400, 'Assistant id is immutable')
        model = DefaultAssistant if aid=='_default' else Assistant
        values = {k: v for k, v in body.items() if k in model.model_fields and k not in ('id', 'created_at')}
        try: updated = model.model_validate({**current.model_dump(), **values})
        except ValidationError as exc: raise HTTPException(422, str(exc)) from exc
        if aid=='_default': self.save_config({'default_assistant': updated.model_dump()})
        else: self.save_config({'assistants': [updated.model_dump() if a.id==aid else a.model_dump() for a in self.config.data.assistants]})
        return self.assistant_view(aid)

    async def delete_assistant(self, aid):
        self.assistant(aid)
        if aid=='_default': raise HTTPException(400, 'Cannot delete the default assistant')
        for session in self.sessions(aid): await self.delete_session(session['id'])
        self.save_config({'assistants': [a.model_dump() for a in self.config.data.assistants if a.id!=aid]})
        (self.store.avatars / aid).unlink(missing_ok=True)
        (self.store.avatars / (aid+'.mime')).unlink(missing_ok=True)

    def reorder(self, ids):
        actual = {a.id for a in self.config.data.assistants}
        if len(ids)!=len(actual) or set(ids)!=actual: raise HTTPException(400, 'ids must contain every assistant exactly once')
        self.save_config({'assistants': [{**a.model_dump(), 'order': ids.index(a.id)} for a in self.config.data.assistants]})

    def search(self, aid, q):
        sessions = self.sessions(aid)
        if not q.strip(): return []
        results = []
        for session in sessions:
            for item in self.items(session['id']):
                if item['kind'] not in ('user', 'text'): continue
                text = item['text']
                at = text.lower().find(q.lower())
                if at>=0:
                    start = max(0, at-40)
                    results.append({'session': session, 'snippet': text[start:start+120]})
                    break
        return results
