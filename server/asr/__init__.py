"""Speech to text module."""
from .config import config_file
from .jobs import AsrJobs
from .routes import router
from .store import AsrStore


def mount(app, core):
    config = config_file(core)
    jobs = AsrJobs(core, config, AsrStore(core.paths.root))
    core.modules['asr'] = jobs
    app.include_router(router(core, jobs))
    core.on_startup(jobs.startup)
    core.on_shutdown(jobs.shutdown)
    core.background(config.watch)
