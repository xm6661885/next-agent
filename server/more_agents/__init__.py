"""More Agents module: ACP endpoints and native Codex app-server agents."""
from .config import config_file
from .runtime import MoreAgentsManager
from .store import MoreAgentsStore
from .routes import router

def mount(app, core):
    config = config_file(core)
    manager = MoreAgentsManager(core, config, MoreAgentsStore(core.paths.root))
    core.modules['more_agents'] = manager
    core.modules['overview_more_agents'] = lambda: {'more_agents_agents': len(config.data.agents), 'sessions': len(manager.store.sessions)}
    core.hello.append(lambda: {'more_agents_sessions': [{k: manager.view(sid)[k] for k in ('id', 'agent_id', 'state', 'pending', 'unread')}
                                                         for sid in manager.store.sessions]})
    config.on_change(manager.changed)
    app.include_router(router(core, manager))
    core.on_startup(manager.startup)
    core.background(config.watch)
    core.background(manager.reaper)
    core.on_shutdown(manager.close)
