"""Reply-local tool registry, alongside the MCP layer."""
import json
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .resources import MemoryText


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Read(Arguments):
    name: str
    offset: int = Field(default=1, ge=1)
    limit: int = Field(default=400, ge=1, le=2000)


class Search(Arguments):
    query: str = Field(min_length=1)
    name: str | None = None


class Add(Arguments, MemoryText):
    pass


class Update(Add):
    id: str


class Delete(Arguments):
    id: str


class LocalTools:
    def __init__(self, manager, sid):
        self.manager, self.sid = manager, sid
        self.aid = manager.session(sid)['assistant_id']
        self.calls = {}
        self.tools = []
        if manager.enabled(self.aid, 'files') and self.files():
            self.register('file_read', 'Read numbered lines of a text file (up to 2000 lines).', Read, self.read)
            self.register('file_search', 'Search text files for a case-insensitive substring (up to 50 hits).', Search, self.search)
        if manager.enabled(self.aid, 'memory'):
            self.register('memory_add', 'Save a durable fact about the user or preferences. Never save secrets.', Add, self.add)
            self.register('memory_update', 'Update a saved memory by id.', Update, self.update)
            self.register('memory_delete', 'Delete a saved memory by id.', Delete, self.delete)

    def register(self, name, description, model, call):
        self.calls[name] = (model, call)
        self.tools.append(dict(name=name, description=description, parameters=model.model_json_schema()))

    def files(self):
        resources, store = self.manager.resources, self.manager.store
        files = {r['name']: resources.file_dir(self.aid) / r['id'] for r in resources.files(self.aid)}
        for record in store.upload_index(self.sid).values():
            if record.get('is_text'): files[record['name']] = Path(record['path'])
        return files

    def selected(self, name=None):
        files = self.files()
        if name is None: return files
        if name not in files: raise ValueError('File not found: '+name)
        return {name: files[name]}

    def read(self, args):
        lines = self.selected(args.name)[args.name].read_text().splitlines()
        content = '\n'.join(f'{i+1}: {line}' for i, line in enumerate(lines)
                            if args.offset<=i+1<args.offset+args.limit)
        return f'Total lines: {len(lines)}\n'+content

    def search(self, args):
        hits = []
        for name, path in self.selected(args.name).items():
            for i, line in enumerate(path.read_text().splitlines(), 1):
                if args.query.lower() in line.lower():
                    hits.append(f'{name}:{i}: {line}')
                    if len(hits)==50: return '\n'.join(hits)
        return '\n'.join(hits)

    def add(self, args):
        record = self.manager.resources.add_memory(self.aid, args.text, 'assistant')
        self.manager.memory_changed(self.aid)
        return json.dumps({'id': record['id']})

    def update(self, args):
        record = self.manager.resources.update_memory(self.aid, args.id, args.text)
        self.manager.memory_changed(self.aid)
        return json.dumps({'id': record['id']})

    def delete(self, args):
        self.manager.resources.delete_memory(self.aid, args.id)
        self.manager.memory_changed(self.aid)
        return '{"ok": true}'

    async def call(self, name, arguments):
        model, call = self.calls[name]
        try: return dict(content=call(model.model_validate(arguments)), is_error=False, images=[])
        except (ValueError, HTTPException) as exc:
            return dict(content=str(exc), is_error=True, images=[])
