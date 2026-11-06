"""One supervised JSON-RPC stdio process per Codex agent."""
import asyncio
import json
import logging
import os

log = logging.getLogger(__name__)
LINE_LIMIT = 64 * 1024 * 1024

class CodexRpcError(RuntimeError):
    def __init__(self, error):
        self.error = error
        super().__init__(error['message'])

class CodexProcess:
    def __init__(self, agent, on_notification, on_request, version=''):
        self.agent, self.on_notification, self.on_request = agent, on_notification, on_request
        self.version = version
        self.proc = self.reader_task = self.stderr_task = None
        self.pending, self.handlers = {}, {}
        self.request_id = 0
        self.write_lock = asyncio.Lock()
        self.closed = asyncio.Event()

    @property
    def alive(self): return self.proc is not None and self.proc.returncode is None and not self.closed.is_set()

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            self.agent.command, 'app-server', '--listen', 'stdio://', '-c', 'analytics.enabled=false', *self.agent.args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **self.agent.env}, limit=LINE_LIMIT)
        self.reader_task = asyncio.create_task(self._read_loop())
        self.stderr_task = asyncio.create_task(self._drain_stderr())
        await self.request('initialize', {'clientInfo': {'name': 'next-agent', 'title': 'Next Agent', 'version': self.version},
                                          'capabilities': {'experimentalApi': True, 'requestAttestation': False}})
        await self.notify('initialized')
        return self

    async def _write(self, message):
        if not self.alive: raise ConnectionError('Codex app-server is not running')
        async with self.write_lock:
            self.proc.stdin.write((json.dumps(message, ensure_ascii=False)+'\n').encode())
            await self.proc.stdin.drain()

    async def request(self, method, params=None):
        self.request_id += 1
        rid = self.request_id
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            await self._write({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}})
            return await future
        finally: self.pending.pop(rid, None)

    async def notify(self, method): await self._write({'jsonrpc': '2.0', 'method': method})

    async def _drain_stderr(self):
        async for line in self.proc.stderr: log.debug('codex app-server: %s', line.decode(errors='replace').rstrip())

    async def _read_loop(self):
        error = ConnectionError('Codex app-server disconnected')
        try:
            async for raw in self.proc.stdout:
                message = json.loads(raw)
                if not isinstance(message, dict): raise ValueError('Invalid Codex message')
                if 'method' in message and 'id' in message:
                    rid = message['id']
                    task = asyncio.create_task(self._server_request(message))
                    self.handlers[rid] = task
                    task.add_done_callback(lambda _, rid=rid: self.handlers.pop(rid, None))
                elif 'method' in message:
                    params = message.get('params') or {}
                    if message['method'] == 'serverRequest/resolved':
                        task = self.handlers.get(params['requestId'])
                        if task: task.cancel()
                    self.on_notification(message['method'], params)
                elif 'id' in message:
                    future = self.pending.get(message['id'])
                    if future and not future.done():
                        if 'error' in message: future.set_exception(CodexRpcError(message['error']))
                        else: future.set_result(message['result'])
                else: raise ValueError('Invalid Codex message')
        except asyncio.CancelledError: raise
        except Exception as exc: error = ConnectionError(str(exc))
        finally:
            self.closed.set()
            for future in self.pending.values():
                if not future.done(): future.set_exception(error)
            for task in self.handlers.values(): task.cancel()
            self.on_notification('__exit__', {'error': str(error)})

    async def _server_request(self, message):
        try:
            result = await self.on_request(message['method'], message.get('params') or {}, message['id'])
            reply = {'result': result}
        except CodexRpcError as exc: reply = {'error': exc.error}
        except (KeyError, TypeError, ValueError) as exc: reply = {'error': {'code': -32602, 'message': str(exc)}}
        if self.alive: await self._write({'jsonrpc': '2.0', 'id': message['id'], **reply})

    async def close(self):
        if self.proc:
            if self.proc.returncode is None:
                self.proc.stdin.close()
                try: await asyncio.wait_for(self.proc.wait(), 3)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
            else: await self.proc.wait()
        tasks = [t for t in (self.reader_task, self.stderr_task, *self.handlers.values()) if t]
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.closed.set()
