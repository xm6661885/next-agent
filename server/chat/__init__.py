"""Plain LLM chat. Entry point: mount(app, core)."""
from .config import config_file
from .routes import router
from .runtime import ChatManager
from .store import ChatStore


def mount(app, core):
    config = config_file(core)
    manager = ChatManager(core, config, ChatStore(core.paths.root))
    core.modules['chat'] = manager
    core.modules['overview_chat'] = lambda: {'assistants': len(config.data.assistants), 'providers': len(config.data.providers),
                                           'sessions': len(manager.store.sessions)}
    core.hello.append(lambda: {'chat_sessions': [{k: session[k] for k in ('id', 'assistant_id', 'state', 'unread')}
                                               for sid in manager.store.sessions if (session := manager.view(sid))['state']=='running' or session['unread']]})
    config.on_change(manager.changed)
    app.include_router(router(core, manager))
    core.background(config.watch)
    core.on_shutdown(manager.close)
