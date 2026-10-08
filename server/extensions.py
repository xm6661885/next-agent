"""Optional event hooks for future integrations."""
import logging

log = logging.getLogger(__name__)

class ExtensionBus:
    """Register a webhook notifier with on('turn_result', async_handler).

    Handlers receive event payload and the free-form extensions config as `config`.
    Their failures are logged without affecting a conversation.
    """
    def __init__(self, config):
        self.config = config
        self.handlers = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    async def emit(self, event, **payload):
        for handler in self.handlers.get(event, []):
            try:
                await handler(**payload, config=self.config.config.extensions)
            except Exception:
                log.exception('Extension handler failed: %s', event)
