"""Normalized transcript items and event helpers."""
from uuid import uuid4
from .config import now


class Items:
    def __init__(self, items, emit):
        self.items, self.emit = items, emit
        self.stream = None
        self.plan = None
        self.tools = {}
        self.tool_data = {}
        self.turn_text = []
        self.last_text = ''

    def add(self, kind, **fields):
        if kind == 'text': fields.setdefault('phase', None)
        item = dict(id=uuid4().hex, kind=kind, ts=now(), **fields)
        self.items.append(item)
        self.emit({'type': 'item', 'item': item})
        return item

    def patch(self, item, **fields):
        item.update(fields)
        self.emit({'type': 'patch', 'id': item['id'], 'patch': fields})

    def finish_stream(self):
        if self.stream:
            self.patch(self.stream, streaming=False)
            self.stream = None

    def begin(self):
        self.finish_stream()
        self.plan = None
        self.tools = {}
        self.tool_data = {}
        self.turn_text = []
        self.last_text = ''

    def notice(self, level, text):
        self.finish_stream()
        return self.add('notice', level=level, text=text)

    def delta(self, item, field, text):
        item[field] = item.get(field, '') + text
        self.emit({'type': 'delta', 'id': item['id'], 'field': field, 'text': text})

    def finish(self):
        self.finish_stream()
        for item in self.items:
            if item.get('streaming'): self.patch(item, streaming=False)
