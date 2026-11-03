"""ACP agents module. Entry point: mount(app, core)."""
from .config import config_file
from .runtime import AcpManager
from .store import AcpStore
from .routes import router


def mount(app, core):
    config = config_file(core)
    manager = AcpManager(core, config, AcpStore(core.paths.root))
    core.modules['acp'] = manager
    core.modules['overview_acp'] = lambda: {'acp_agents': len(config.data.agents), 'sessions': len(manager.store.sessions)}
    core.hello.append(lambda: {'acp_sessions': [{k: manager.view(sid)[k] for k in ('id', 'agent_id', 'state', 'pending', 'unread')}
                                              for sid in manager.store.sessions]})
    config.on_change(manager.changed)
    app.include_router(router(core, manager))
    core.on_startup(manager.startup)
    core.background(config.watch)
    core.background(manager.reaper)
    core.on_shutdown(manager.close)
