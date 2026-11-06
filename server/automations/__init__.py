"""Automations module; CLI workers import only the modules they need."""
def mount(app, core):
    from .service import mount
    mount(app, core)
