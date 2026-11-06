"""What every module gets in mount(app, core). The only object shared across modules."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

@dataclass
class Core:
    paths: Any                 # DataDir; paths.root/'agents', 'builtin', 'chat', 'workflow', 'more_agents', 'automations', 'asr', 'imagegen', 'core'; config: paths.config_dir
    auth: Any                  # Auth; use `require` for routes and `await auth.require_ws(ws)` for sockets
    require: Callable          # FastAPI dependency: Depends(core.require)
    emit: Callable             # emit(event: dict) to every /ws/events client; set event['module']
    claude: Callable           # claude() -> ServerConfig with cli_path, max_concurrent, anthropic_base_url, anthropic_api_key
    version: str = ''
    bridge: Any = None         # AgentBridge (server/bridge.py), set after the Agents module is up
    modules: dict = field(default_factory=dict)   # name -> object a module chooses to expose (e.g. 'more_agents': MoreAgentsManager)
    hello: list = field(default_factory=list)     # callables returning extra keys for the /ws/events hello message
    _startup: list = field(default_factory=list)
    _shutdown: list = field(default_factory=list)
    _tasks: list = field(default_factory=list)

    def on_startup(self, fn):
        """async fn() run in the app lifespan before serving."""
        self._startup.append(fn)

    def on_shutdown(self, fn):
        """async fn() run in the app lifespan on shutdown, in reverse order."""
        self._shutdown.append(fn)

    def background(self, factory):
        """factory() -> coroutine; started after startup hooks, cancelled on shutdown."""
        self._startup.append(lambda: self._spawn(factory))

    async def _spawn(self, factory):
        self._tasks.append(asyncio.create_task(factory()))

    async def start(self):
        for fn in self._startup: await fn()

    async def stop(self):
        for task in self._tasks: task.cancel()
        for fn in reversed(self._shutdown):
            try: await fn()
            except Exception: log.exception('Shutdown hook failed')
