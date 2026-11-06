"""Service lifecycle. Task workers live in separate systemd scopes."""
import asyncio
import sqlite3
from .config import config_file, resolved, ensure_dirs
from .db import DB
from .scheduler import Scheduler


class Automations:
    def __init__(self, core, config):
        self.core, self.config = core, config
        self.cfg = resolved(config.data, core.paths.root)
        ensure_dirs(self.cfg)
        self.db = DB(self.cfg['data_dir'])
        self.scheduler = Scheduler(self.cfg, self.db)
        self.runner = self.scheduler.runner
        self.connection = None

    def emit(self):
        self.core.emit({'type': 'automations_changed', 'module': 'automations'})

    async def startup(self):
        self.db.recover_interrupted_runs()
        self.connection = sqlite3.connect(self.db.path)
        self.version = self.connection.execute('PRAGMA data_version').fetchone()[0]
        self.scheduler.start()

    async def shutdown(self):
        await asyncio.to_thread(self.scheduler.stop)
        if self.connection: self.connection.close()

    async def poll(self):
        while True:
            await asyncio.sleep(1)
            version = self.connection.execute('PRAGMA data_version').fetchone()[0]
            if version != self.version:
                self.version = version
                self.emit()

    async def changed(self):
        self.cfg.update(resolved(self.config.data, self.core.paths.root))
        ensure_dirs(self.cfg)
        self.emit()


def mount(app, core):
    from .routes import router
    config = config_file(core)
    manager = Automations(core, config)
    core.modules['automations'] = manager
    app.include_router(router(core, manager))
    config.on_change(manager.changed)
    core.on_startup(manager.startup)
    core.background(config.watch)
    core.background(manager.poll)
    core.on_shutdown(manager.shutdown)
