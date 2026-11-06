"""Supervised JSON-RPC stdio process for a Codex app-server."""
import asyncio, json, logging, os

log = logging.getLogger(__name__)
LINE_LIMIT = 64 * 1024 * 1024

class CodexRpcError(RuntimeError):
    def __init__(self, error):
        self.error = error
        super().__init__(error.get('message', str(error)))

class CodexProcess:
    def __init__(self, agent, on_notification, on_request, version=''):
        self.agent = agent
        self.on_notification = on_notification
        self.on_request = on_request
        self.version = version
        self.proc = None
        self.reader_task = None
        self.stderr_task = None
        self.pending = {}
        self.request_id = 0
        self.write_lock = asyncio.Lock()
        self.handlers = set()
        self.closed = asyncio.Event()

    @property
    def alive(self): return self.proc is not None and self.proc.returncode is None

    async def start(self):
        env = os.environ.copy(); env.update(self.agent.env)
        self.proc = await asyncio.create_subprocess_exec(
            self.agent.command, 'app-server', '--listen', 'stdio://', '-c', 'analytics.enabled=false', *self.agent.args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, limit=LINE_LIMIT)
        self.reader_task = asyncio.create_task(self._read_loop())
        self.stderr_task = asyncio.create_task(self._drain_stderr())
        await self.request('initialize', {'clientInfo': {'name': 'next-agent', 'title': 'Next Agent', 'version': self.version},
                                          'capabilities': {'experimentalApi': True, 'requestAttestation': False}})
        await self.notify('initialized')
        return self

    async def _write(self, message):
        if not self.alive: raise ConnectionError('Codex app-server is not running')
        data = (json.dumps(message, ensure_ascii=False) + '\n').encode()
        async with self.write_lock:
            self.proc.stdin.write(data); await self.proc.stdin.drain()

    async def request(self, method, params=None):
        self.request_id += 1; rid = self.request_id
        future = asyncio.get_running_loop().create_future(); self.pending[rid] = future
        try: await self._write({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}})
        except BaseException:
            self.pending.pop(rid, None); future.cancel(); raise
        try: return await future
        finally: self.pending.pop(rid, None)

    async def notify(self, method, params=None):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None: message['params'] = params
        await self._write(message)

    async def _drain_stderr(self):
        async for line in self.proc.stderr:
            log.debug('codex app-server: %s', line.decode(errors='replace').rstrip())

    async def _read_loop(self):
        error = ConnectionError('Codex app-server disconnected')
        try:
            async for raw in self.proc.stdout:
                message = json.loads(raw)
                if 'method' in message and 'id' in message:
                    task = asyncio.create_task(self._server_request(message)); self.handlers.add(task); task.add_done_callback(self.handlers.discard)
                elif 'method' in message:
                    result = self.on_notification(message['method'], message.get('params') or {})
                    if asyncio.iscoroutine(result): await result
                elif 'id' in message:
                    future = self.pending.get(message['id'])
                    if future and not future.done():
                        if 'error' in message: future.set_exception(CodexRpcError(message['error']))
                        else: future.set_result(message.get('result'))
        except asyncio.CancelledError: return
        except Exception as exc: error = ConnectionError(str(exc))
        finally:
            for future in self.pending.values():
                if not future.done(): future.set_exception(error)
            self.pending.clear(); self.closed.set()
            callback = self.on_notification('__exit__', {})
            if asyncio.iscoroutine(callback): await callback

    async def _server_request(self, message):
        try:
            result = self.on_request(message['method'], message.get('params') or {})
            if asyncio.iscoroutine(result): result = await result
            await self._write({'jsonrpc':'2.0','id':message['id'],'result':result})
        except Exception as exc:
            await self._write({'jsonrpc':'2.0','id':message['id'],'error':{'code':-32603,'message':str(exc)}})

    async def close(self):
        if self.proc and self.proc.returncode is None:
            self.proc.stdin.close()
            try: await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill(); await self.proc.wait()
        for task in (self.reader_task, self.stderr_task, *self.handlers):
            if task and not task.done(): task.cancel()
        await asyncio.gather(*(t for t in (self.reader_task, self.stderr_task, *self.handlers) if t), return_exceptions=True)
        self.closed.set()
