"""Workflow module. Entry point: mount(app, core)."""
import asyncio
from pathlib import Path
from .config import config_file
from .db import Database
from .engine.events import EventBus
from .engine.runner import RunManager
from .plugins.manager import PluginManager
from .routes import router


def mount(app, core):
    config = config_file(core)
    root = core.paths.root / 'workflow'
    for name in ('plugins', 'workspace'): (root / name).mkdir(parents=True, exist_ok=True)
    db = Database(root / 'app.db')
    bus = EventBus(db)
    plugins = PluginManager([(Path(__file__).parent / 'plugins_core', 'core'), (root / 'plugins', 'user')])
    manager = RunManager(db, bus, plugins, root / 'workspace', config, core)
    core.modules['workflow'] = manager
    core.modules['overview_workflow'] = lambda: dict(manager.counts)

    async def changed():
        manager.limiter.set_limit(config.data.server.agent_concurrency)
        if config.data.server.plugin_watch and not plugins.watching: plugins.start_watch(root / 'plugins')
        elif not config.data.server.plugin_watch: plugins.stop_watch()

    async def startup():
        await db.open()
        await bus.start()
        plugins.load_all()
        await manager.recover_stale()
        await manager.refresh_counts()
        await changed()

    async def shutdown():
        watcher = plugins._watch_task
        plugins.stop_watch()
        if watcher: await asyncio.gather(watcher, return_exceptions=True)
        await manager.shutdown()
        await bus.stop()
        await db.close()

    config.on_change(changed)
    app.include_router(router(core, manager))
    core.on_startup(startup)
    core.background(config.watch)
    core.on_shutdown(shutdown)
