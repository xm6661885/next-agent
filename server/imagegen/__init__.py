"""Image generation module."""
from .config import config_file
from .jobs import ImageJobs
from .routes import router


def mount(app, core):
    config = config_file(core)
    jobs = ImageJobs(core, config)
    core.modules['imagegen'] = jobs
    app.include_router(router(core, jobs))
    core.on_startup(jobs.startup)
    core.on_shutdown(jobs.shutdown)
    core.background(config.watch)
