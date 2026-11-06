"""ACP TCP lifecycle and protocol mapping, independent of the session queue."""
import asyncio
from .client import AcpConnection, AcpError
from .encode import prompt
from .items import AcpItems
from ..base import TurnError

class AcpAdapter:
    def __init__(self, runtime):
        self.runtime = runtime
        self.client = None
        self.closed = None
        self.replaying = False
        self.mapper = AcpItems(runtime.items)

    @property
    def connected(self): return bool(self.client and not self.client.closed.done())

    def options(self, result):
        values = {target: result[source] for source, target in (('modes', 'modes'), ('configOptions', 'config_options')) if source in result}
        if values: self.runtime.session_changed(**values)

    async def connect(self):
        r = self.runtime
        agent = r.manager.agent(r.session['agent_id'])
        self.client = AcpConnection(self.permission, self.notification)
        self.closed = self.client.closed
        await self.client.open(agent.host, agent.port, agent.token)
        await self.client.initialize(r.manager.core.version)
        r.manager.info[agent.id] = self.client.info
        r.manager.changed_event()
        loaded = False
        if r.session['remote_id'] and self.client.capabilities.get('loadSession'):
            self.replaying = True
            try:
                result = await self.client.request('session/load', {'sessionId': r.session['remote_id'], 'cwd': r.session['cwd'], 'mcpServers': []})
                loaded = True
            except AcpError:
                r.items.notice('warn', 'Remote session was gone; started a new one (earlier context is not available to the agent)')
            finally: self.replaying = False
        if not loaded:
            result = await self.client.request('session/new', {'cwd': r.session['cwd'], 'mcpServers': []})
            if not isinstance(result['sessionId'], str): raise ValueError('Invalid remote session id')
            r.session_changed(remote_id=result['sessionId'], modes=None, config_options=[], commands=[])
        self.options(result)
        if not loaded:
            for key, value in agent.config_defaults.items(): await self.set_option(key, value)

    async def run_turn(self, text, attachments):
        r = self.runtime
        native = await self.client.begin_request('session/prompt', {'sessionId': r.session['remote_id'],
            'prompt': prompt(text, attachments, self.client.capabilities.get('promptCapabilities', {}))})
        async def result():
            try: response = await native
            except AcpError as exc: raise TurnError(str(exc)) from exc
            reason = response['stopReason']
            if reason not in ('end_turn', 'max_tokens', 'max_turn_requests', 'refusal', 'cancelled'): raise ValueError('Invalid prompt stop reason')
            return {'reason': reason}
        return asyncio.create_task(result())

    async def interrupt(self):
        await self.client.notify('session/cancel', {'sessionId': self.runtime.session['remote_id']})

    async def set_option(self, id, value):
        self.options(await self.client.request('session/set_config_option', {'sessionId': self.runtime.session['remote_id'], 'configId': id, 'value': value}))

    async def set_mode(self, id):
        r = self.runtime
        await self.client.request('session/set_mode', {'sessionId': r.session['remote_id'], 'modeId': id})
        r.session_changed(modes={**(r.session['modes'] or {'availableModes': []}), 'currentModeId': id})

    async def permission(self, method, params):
        r = self.runtime
        if method != 'session/request_permission': raise AcpError(-32601, 'Method not found')
        if params.get('sessionId') != r.session['remote_id']: raise AcpError(-32602, 'Unknown session')
        if self.replaying or r.state == 'interrupting': return {'outcome': {'outcome': 'cancelled'}}
        if not isinstance(params.get('toolCall'), dict) or not isinstance(params.get('options'), list): raise AcpError(-32602, 'Invalid permission request')
        tool = dict(params['toolCall'])
        tool['tool_kind'] = tool.pop('kind', 'other')
        if tool['tool_kind'] not in {'read','edit','delete','move','search','execute','think','fetch','mcp','other'}: tool['tool_kind'] = 'other'
        tool.setdefault('title', '')
        options = [dict(option_id=o['optionId'], name=o['name'], kind=o['kind']) for o in params['options']]
        if any(not all(isinstance(v, str) for v in o.values()) for o in options): raise AcpError(-32602, 'Invalid permission options')
        option = await r.ask_permission(tool, options)
        return {'outcome': {'outcome': 'selected', 'optionId': option} if option is not None else {'outcome': 'cancelled'}}

    def notification(self, method, params):
        r = self.runtime
        if method != 'session/update' or self.replaying or params.get('sessionId') != r.session['remote_id']: return
        update = params['update']
        self.mapper.consume(update)
        kind = update.get('sessionUpdate')
        if kind == 'available_commands_update': r.session_changed(commands=update['availableCommands'])
        elif kind == 'current_mode_update': r.session_changed(modes={**(r.session['modes'] or {'availableModes': []}), 'currentModeId': update['currentModeId']})
        elif kind == 'config_option_update': r.session_changed(config_options=update['configOptions'])
        elif kind == 'session_info_update' and 'title' in update: r.session_changed(title=update['title'])

    async def disconnect(self):
        if self.client: await self.client.close()
        self.client = None
        self.closed = None

class AcpKind:
    capabilities = dict(images=True, steer=False, modes=True, local_cwd=False)
    def __init__(self, manager): self.manager = manager
    def adapter(self, runtime): return AcpAdapter(runtime)
    async def models(self, agent): return []
    async def shutdown(self): pass
    async def test(self, agent):
        connection = AcpConnection()
        try:
            async with asyncio.timeout(10):
                await connection.open(agent.host, agent.port, agent.token)
                await connection.initialize(self.manager.core.version)
                self.manager.info[agent.id] = connection.info
                self.manager.changed_event()
                result = await connection.request('session/new', {'cwd': agent.cwd, 'mcpServers': []})
                return dict(ok=True, info=connection.info, config_options=result.get('configOptions', []))
        except Exception as exc: return dict(ok=False, info=connection.info, config_options=[], error=str(exc) or 'Connection test timed out')
        finally: await connection.close()
