"""One TOML file per module under data/config/: parse, validate, comment-preserving save, hot reload."""
import asyncio
import logging
import tomlkit
from .paths import atomic_write

log = logging.getLogger(__name__)

class TomlFile:
    """`model` is a pydantic model class for the whole file; `template` is written when the file is missing."""
    def __init__(self, path, model, template=''):
        self.path, self.model = path, model
        if not path.exists(): atomic_write(path, template)
        self.doc = None
        self.data = None
        self.mtime = None
        self.listeners = []
        self.load()

    def parse(self, content):
        doc = tomlkit.parse(content)
        return doc, self.model.model_validate(doc.unwrap())

    def load(self):
        self.doc, self.data = self.parse(self.path.read_text())
        self.mtime = self.stamp()

    def save(self):
        content = tomlkit.dumps(self.doc)
        self.doc, self.data = self.parse(content)
        atomic_write(self.path, content)
        self.mtime = self.stamp()

    def replace_raw(self, content):
        self.doc, self.data = self.parse(content)
        self.save()

    def stamp(self):
        st = self.path.stat()
        return (st.st_mtime_ns, st.st_size)

    def on_change(self, handler):
        """async handler() called after a reload from disk or a raw replace."""
        self.listeners.append(handler)

    async def changed(self):
        for handler in self.listeners:
            try: await handler()
            except Exception: log.exception('Config listener failed: %s', self.path.name)

    async def watch(self, interval=2):
        while True:
            await asyncio.sleep(interval)
            try:
                if self.stamp() != self.mtime:
                    self.load()
                    await self.changed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning('Invalid config reload (%s): %s', self.path.name, exc)
                self.mtime = self.stamp()
