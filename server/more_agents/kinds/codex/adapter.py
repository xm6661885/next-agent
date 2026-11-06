"""Native Codex thread lifecycle, settings and interactive requests."""
import asyncio
import json
from ....paths import atomic_write
from ..base import TurnEnded, TurnError
from .process import CodexProcess, CodexRpcError
from .items import CodexItems

MODES = [dict(id='full-access', name='Full access', description='Unrestricted access without approvals'),
         dict(id='auto', name='Auto', description='Workspace writes; ask for additional access'),
         dict(id='read-only', name='Read only', description='Read files; ask for additional access')]
DECISIONS = {'accept': ('allow_once', 'Allow'), 'acceptForSession': ('allow_always', 'Allow for this session'),
             'decline': ('reject_once', 'Decline'), 'cancel': ('reject_once', 'Cancel')}

def usage(tokens):
    return {k: tokens.get(v, 0) for k, v in (('input','inputTokens'), ('cached_input','cachedInputTokens'),
                                            ('output','outputTokens'), ('reasoning','reasoningOutputTokens'))}

class CodexKind:
    capabilities = dict(images=True, steer=True, modes=True, local_cwd=True)
    def __init__(self, manager):
        self.manager = manager
        self.processes, self.locks, self.cache = {}, {}, {}

    def adapter(self, runtime): return CodexAdapter(self, runtime)

    def cached_models(self, aid):
        if aid not in self.cache:
            path = self.manager.store.root / 'models' / (aid+'.json')
            if path.exists(): self.cache[aid] = json.loads(path.read_text())
        return self.cache.get(aid, [])

    async def acquire(self, agent, user):
        async with self.locks.setdefault(agent.id, asyncio.Lock()):
            entry = self.processes.get(agent.id)
            if entry is None or not entry['process'].alive:
                if entry: await entry['process'].close()
                users = set()
                def notification(method, params):
                    for adapter in list(users):
                        if method == '__exit__' or adapter.runtime.session['remote_id'] == params.get('threadId'):
                            adapter.notification(method, params)
                async def request(method, params, rid):
                    adapter = next((a for a in users if a.runtime.session['remote_id'] == params.get('threadId')), None)
                    if adapter is None: raise CodexRpcError(dict(code=-32602, message='Unknown thread'))
                    return await adapter.request(method, params, rid)
                process = CodexProcess(agent, notification, request, self.manager.core.version)
                try:
                    await process.start()
                    models, cursor = [], None
                    while True:
                        response = await process.request('model/list', dict(includeHidden=False, **({'cursor': cursor} if cursor else {})))
                        models.extend(response['data'])
                        cursor = response.get('nextCursor')
                        if not cursor: break
                    self.cache[agent.id] = models
                    atomic_write(self.manager.store.root / 'models' / (agent.id+'.json'), json.dumps(models))
                except BaseException:
                    await process.close()
                    raise
                entry = dict(process=process, users=users)
                self.processes[agent.id] = entry
            if user is not None: entry['users'].add(user)
            return entry['process']

    async def release(self, aid, process, user=None):
        async with self.locks[aid]:
            entry = self.processes.get(aid)
            if entry is None or entry['process'] is not process: return
            entry['users'].discard(user)
            if not entry['users']:
                del self.processes[aid]
                await process.close()

    async def models(self, agent):
        cached = self.cached_models(agent.id)
        if agent.id in self.cache: return cached
        process = await self.acquire(agent, None)
        await self.release(agent.id, process)
        return self.cache[agent.id]

    async def test(self, agent):
        try:
            async with asyncio.timeout(10):
                process = await self.acquire(agent, None)
                await self.release(agent.id, process)
                return dict(ok=True, info=None, models=self.cache[agent.id], config_options=[])
        except Exception as exc: return dict(ok=False, info=None, config_options=[], error=str(exc) or 'Connection test timed out')

    async def shutdown(self):
        await asyncio.gather(*(e['process'].close() for e in self.processes.values()))
        self.processes.clear()

class CodexAdapter:
    def __init__(self, kind, runtime):
        self.kind, self.runtime = kind, runtime
        self.process = self.closed = self.done = self.turn_id = None
        self.mapper = CodexItems(runtime.items)
        agent = runtime.manager.agent(runtime.session['agent_id'])
        options = {o['id']: o['currentValue'] for o in runtime.session['config_options']}
        self.model, self.effort = options.get('model', agent.model), options.get('effort', agent.effort)
        self.mode = (runtime.session['modes'] or {}).get('currentModeId', agent.mode)
        self.baseline = {}

    @property
    def connected(self): return self.process is not None and self.process.alive and self.closed is not None and not self.closed.done()

    def mode_fields(self, turn=False):
        sandbox = {'full-access':'danger-full-access', 'auto':'workspace-write', 'read-only':'read-only'}[self.mode]
        fields = dict(approvalPolicy='never' if self.mode=='full-access' else 'on-request', approvalsReviewer='user')
        if turn:
            fields['sandboxPolicy'] = {'type': {'full-access':'dangerFullAccess','auto':'workspaceWrite','read-only':'readOnly'}[self.mode]}
            if self.mode == 'auto': fields['sandboxPolicy']['writableRoots'] = [self.runtime.session['cwd']]
        else: fields['sandbox'] = sandbox
        return fields

    def options(self):
        models = self.kind.cached_models(self.runtime.session['agent_id'])
        model = next((m for m in models if m['model']==self.model), None)
        efforts = model['supportedReasoningEfforts'] if model else []
        self.runtime.session_changed(config_options=[
            dict(id='model', name='Model', category='model', type='select', currentValue=self.model,
                 options=[dict(value=m['model'], name=m['displayName'], description=m['description']) for m in models]),
            dict(id='effort', name='Reasoning', category='thought_level', type='select', currentValue=self.effort,
                 options=[dict(value=e['reasoningEffort'], name=e['reasoningEffort'], description=e['description']) for e in efforts])],
            modes=dict(currentModeId=self.mode, availableModes=MODES))

    async def connect(self):
        r = self.runtime
        agent = r.manager.agent(r.session['agent_id'])
        self.closed = asyncio.get_running_loop().create_future()
        self.process = await self.kind.acquire(agent, self)
        params = dict(cwd=r.session['cwd'], config={'model_reasoning_summary':'auto'}, **self.mode_fields())
        if self.model: params['model'] = self.model
        if self.effort: params['config']['model_reasoning_effort'] = self.effort
        if agent.instructions: params['developerInstructions'] = agent.instructions
        response = None
        if r.session['remote_id']:
            try: response = await self.process.request('thread/resume', dict(threadId=r.session['remote_id'], excludeTurns=True, **params))
            except CodexRpcError as exc:
                if not any(s in str(exc).lower() for s in ('not found', 'no rollout found', 'does not exist')): raise
                r.items.notice('warn', 'Remote session was gone; started a new one (earlier context is not available to the agent)')
        if response is None:
            response = await self.process.request('thread/start', dict(serviceName='next-agent', **params))
            r.session_changed(usage=usage({}), context=None)
        r.session_changed(remote_id=response['thread']['id'])
        self.model, self.effort = response['model'], response.get('reasoningEffort') or ''
        self.options()

    def input(self, text, attachments):
        files = [f"Attached file: {a['path']}" for a in attachments if not a['is_image']]
        text = '\n'.join([text, *files]) if files else text
        return ([dict(type='text', text=text, text_elements=[])] if text else []) + [dict(type='localImage', path=a['path']) for a in attachments if a['is_image']]

    async def run_turn(self, text, attachments):
        self.mapper.begin()
        self.baseline = dict(self.runtime.session.get('usage') or usage({}))
        self.turn_id = None
        self.done = asyncio.get_running_loop().create_future()
        params = dict(threadId=self.runtime.session['remote_id'], cwd=self.runtime.session['cwd'], input=self.input(text, attachments), summary='auto', **self.mode_fields(True))
        if self.model: params['model'] = self.model
        if self.effort: params['effort'] = self.effort
        try: response = await self.process.request('turn/start', params)
        except CodexRpcError as exc: raise TurnError(str(exc)) from exc
        self.turn_id = response['turn']['id']
        return self.done

    async def steer(self, text, attachments):
        try:
            await self.process.request('turn/steer', dict(threadId=self.runtime.session['remote_id'], expectedTurnId=self.turn_id, input=self.input(text, attachments)))
        except CodexRpcError as exc:
            if self.done.done() or any(s in str(exc).lower() for s in ('no active turn', 'turn already completed', 'turn has completed')): raise TurnEnded() from exc
            raise

    async def interrupt(self):
        if self.done and not self.done.done():
            await self.process.request('turn/interrupt', dict(threadId=self.runtime.session['remote_id'], turnId=self.turn_id))

    async def set_option(self, id, value):
        models = self.kind.cached_models(self.runtime.session['agent_id'])
        if id == 'model':
            model = next((m for m in models if m['model']==value), None)
            if value and model is None: raise ValueError('Unknown model')
            self.model = value
            if model and self.effort not in [e['reasoningEffort'] for e in model['supportedReasoningEfforts']]: self.effort = model['defaultReasoningEffort']
            elif not model: self.effort = ''
        elif id == 'effort':
            model = next((m for m in models if m['model']==self.model), None)
            if value and (not model or value not in [e['reasoningEffort'] for e in model['supportedReasoningEfforts']]): raise ValueError('Unsupported reasoning effort')
            self.effort = value
        else: raise ValueError('Unknown config option')
        self.options()

    async def set_mode(self, id):
        if id not in [m['id'] for m in MODES]: raise ValueError('Unknown mode')
        self.mode = id
        self.options()

    def notification(self, method, p):
        r = self.runtime
        if method == '__exit__':
            if self.closed and not self.closed.done(): self.closed.set_result(p['error'])
        elif method == 'turn/started': self.turn_id = p['turn']['id']
        elif method == 'thread/tokenUsage/updated':
            tokens = p['tokenUsage']
            fields = dict(usage=usage(tokens['total']))
            if tokens.get('modelContextWindow') is not None:
                fields['context'] = dict(used=tokens['last']['totalTokens'], max=tokens['modelContextWindow'])
            r.session_changed(**fields)
        elif method == 'turn/completed':
            turn = p['turn']
            if self.done and not self.done.done():
                reason = {'completed':'completed','interrupted':'interrupted','failed':'error'}[turn['status']]
                error = (turn.get('error') or {}).get('message')
                self.done.set_result(dict(reason=reason, error=error, duration_ms=turn.get('durationMs'),
                                          usage={k:v-self.baseline.get(k,0) for k,v in r.session.get('usage', usage({})).items()}))
        elif method == 'serverRequest/resolved': r.cancel_prompts(p['requestId'])
        elif method == 'error': r.items.notice('warn' if p.get('willRetry') else 'error', p['error']['message'])
        else: self.mapper.consume(method, p)

    async def request(self, method, p, rid):
        r = self.runtime
        if method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval','item/permissions/requestApproval'):
            profile = method == 'item/permissions/requestApproval'
            decisions = p.get('availableDecisions') or ['accept','acceptForSession','decline','cancel']
            options = [dict(option_id=d, name=DECISIONS[d][1], kind=DECISIONS[d][0]) for d in decisions if isinstance(d,str) and d in DECISIONS]
            tool = dict(title=p.get('command') or p.get('reason') or 'Request access', tool_kind='execute' if 'commandExecution' in method else 'other' if profile else 'edit')
            tool.update({k:p[k] for k in ('command','cwd','reason','changes') if k in p})
            if profile: tool['input'] = p['permissions']
            decision = await r.ask_permission(tool, options, rid)
            if profile: return dict(permissions=p['permissions'] if decision in ('accept','acceptForSession') else {}, scope='session' if decision=='acceptForSession' else 'turn')
            return dict(decision=decision or 'cancel')
        if method == 'item/tool/requestUserInput':
            questions = [dict(id=q['id'], header=q['header'], question=q['question'], options=q.get('options') or [],
                              is_other=q.get('isOther',False), is_secret=q.get('isSecret',False)) for q in p['questions']]
            answers = await r.ask_question(questions, rid)
            return dict(answers={q['id']:dict(answers=(answers or {}).get(q['id'],[])) for q in questions})
        r.items.notice('warn', 'Unsupported Codex request: '+method)
        raise CodexRpcError(dict(code=-32601, message='Method not found'))

    async def disconnect(self):
        process = self.process
        if process:
            try:
                if self.connected and self.runtime.session['remote_id']:
                    await process.request('thread/unsubscribe', dict(threadId=self.runtime.session['remote_id']))
            except ConnectionError: pass  # The process exited while unsubscribing.
            finally:
                self.process = None
                await self.kind.release(self.runtime.session['agent_id'], process, self)
        self.closed = None
