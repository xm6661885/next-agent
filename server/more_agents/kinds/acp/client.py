"""JSON-RPC over authenticated newline-delimited TCP."""
import asyncio
import inspect
import json

LINE_LIMIT = 16 * 1024 * 1024


class AcpError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


class AcpConnection:
    def __init__(self, on_request=None, on_notification=None):
        self.on_request, self.on_notification = on_request, on_notification
        self.reader = self.writer = self.reader_task = None
        self.closed = asyncio.get_running_loop().create_future()
        self.pending = {}
        self.handlers = set()
        self.counter = 0
        self.capabilities = {}
        self.info = None

    async def open(self, host, port, token=''):
        if '\n' in token or '\r' in token: raise ValueError('token must be a single line')
        self.reader, self.writer = await asyncio.open_connection(host, port, limit=LINE_LIMIT)
        if token:
            self.writer.write(('AUTH ' + token + '\n').encode())
            await self.writer.drain()
        self.reader_task = asyncio.create_task(self._read())
        return self

    async def initialize(self, version=''):
        result = await self.request('initialize', {
            'protocolVersion': 1, 'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False},
            'clientInfo': {'name': 'next-agent', 'version': version}})
        self.capabilities = result.get('agentCapabilities', {})
        self.info = result.get('agentInfo')
        if not isinstance(self.capabilities, dict) or not isinstance(self.capabilities.get('promptCapabilities', {}), dict):
            raise ValueError('Invalid agent capabilities')
        return result

    async def _write(self, message):
        if self.closed.done() or not self.writer: raise ConnectionError('ACP connection is closed')
        line = (json.dumps(message, ensure_ascii=False) + '\n').encode()
        if len(line)>LINE_LIMIT: raise ValueError('ACP message exceeds 16 MB')
        self.writer.write(line)
        await self.writer.drain()

    async def begin_request(self, method, params):
        self.counter += 1
        rid = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try: await self._write({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params})
        except BaseException:
            self.pending.pop(rid, None)
            if future.done() and not future.cancelled(): future.exception()
            else: future.cancel()
            raise
        return future

    async def request(self, method, params):
        future = await self.begin_request(method, params)
        try: return await future
        finally:
            for rid, pending in list(self.pending.items()):
                if pending is future: self.pending.pop(rid, None)

    async def notify(self, method, params):
        await self._write({'jsonrpc': '2.0', 'method': method, 'params': params})

    async def _server_request(self, message):
        response = {'jsonrpc': '2.0', 'id': message['id']}
        try:
            if not self.on_request: raise AcpError(-32601, 'Method not found')
            result = self.on_request(message['method'], message.get('params', {}))
            response['result'] = await result if inspect.isawaitable(result) else result
        except AcpError as exc: response['error'] = {'code': exc.code, 'message': exc.message}
        except (TypeError, KeyError, ValueError): response['error'] = {'code': -32602, 'message': 'Invalid params'}
        except Exception: response['error'] = {'code': -32603, 'message': 'Internal error'}
        try: await self._write(response)
        except (ConnectionError, OSError): pass

    async def _read(self):
        error = ConnectionError('ACP connection closed')
        try:
            while True:
                line = await self.reader.readline()
                if not line: break
                if len(line)>LINE_LIMIT: raise ValueError('ACP line exceeds 16 MB')
                message = json.loads(line)
                if not isinstance(message, dict) or message.get('jsonrpc')!='2.0': raise ValueError('Invalid JSON-RPC message')
                if 'method' in message:
                    if not isinstance(message['method'], str) or not isinstance(message.get('params', {}), dict):
                        raise ValueError('Invalid JSON-RPC request')
                    if 'id' in message:
                        if not isinstance(message['id'], (int, str)): raise ValueError('Invalid request id')
                        task = asyncio.create_task(self._server_request(message))
                        self.handlers.add(task)
                        task.add_done_callback(self.handlers.discard)
                    elif self.on_notification:
                        result = self.on_notification(message['method'], message.get('params', {}))
                        if inspect.isawaitable(result): await result
                else:
                    rid = message.get('id')
                    if not isinstance(rid, (int, str)): raise ValueError('Invalid response id')
                    if ('error' in message)==('result' in message): raise ValueError('Invalid JSON-RPC response')
                    if 'error' in message:
                        err = message['error']
                        if not isinstance(err, dict) or not isinstance(err.get('code'), int) or not isinstance(err.get('message'), str):
                            raise ValueError('Invalid JSON-RPC error')
                    elif not isinstance(message['result'], dict): raise ValueError('Invalid ACP result')
                    future = self.pending.pop(rid, None)
                    if future and not future.done():
                        if 'error' in message: future.set_exception(AcpError(err['code'], err['message']))
                        else: future.set_result(message['result'])
        except asyncio.CancelledError: pass
        except Exception as exc: error = ConnectionError(f'ACP connection failed: {exc}')
        finally:
            for future in self.pending.values():
                if not future.done(): future.set_exception(error)
            self.pending.clear()
            if self.writer: self.writer.close()
            if not self.closed.done(): self.closed.set_result(error)

    async def close(self):
        if self.reader_task and not self.reader_task.done(): self.reader_task.cancel()
        if self.reader_task: await asyncio.gather(self.reader_task, return_exceptions=True)
        for task in self.handlers: task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)
        if self.writer:
            self.writer.close()
            try: await self.writer.wait_closed()
            except (ConnectionError, OSError): pass
        if not self.closed.done(): self.closed.set_result(ConnectionError('ACP connection closed'))
