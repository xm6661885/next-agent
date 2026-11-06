"""ACP updates become the shared transcript item/event shapes."""
import json
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

    def consume(self, update):
        kind = update.get('sessionUpdate')
        if kind in ('agent_message_chunk', 'agent_thought_chunk'):
            content = update['content']
            if content.get('type')=='text': text = content['text']
            elif content.get('type')=='image': text = f"![](data:{content['mimeType']};base64,{content['data']})"
            else:
                self.finish_stream()
                return
            item_kind = 'text' if kind=='agent_message_chunk' else 'thinking'
            if kind=='agent_message_chunk' and content.get('type')=='text': self.turn_text.append(text)
            if not self.stream or self.stream['kind']!=item_kind:
                self.finish_stream()
                self.stream = self.add(item_kind, text=text, streaming=True)
            else:
                self.stream['text'] += text
                self.emit({'type': 'delta', 'id': self.stream['id'], 'field': 'text', 'text': text})
            if item_kind=='text': self.last_text = self.stream['text']
        elif kind in ('tool_call', 'tool_call_update'):
            self.finish_stream()
            tid = update['toolCallId']
            data = self.tool_data.setdefault(tid, {})
            data.update(update)
            fields = {}
            for source, target in (('title', 'name'), ('kind', 'tool_kind'), ('rawInput', 'input'),
                                   ('status', 'status'), ('locations', 'locations')):
                if source in update:
                    value = update[source] if source != 'rawInput' else update[source] or {}
                    if target == 'tool_kind' and value not in {'read','edit','delete','move','search','execute','think','fetch','mcp','other'}: value = 'other'
                    fields[target] = value
            if data.get('status') in ('completed', 'failed'):
                contents = data.get('content') or []
                texts = [c['content']['text'] for c in contents if c.get('type')=='content' and c.get('content', {}).get('type')=='text']
                diffs = [dict(path=c['path'], old_text=c.get('oldText'), new_text=c['newText']) for c in contents if c.get('type')=='diff']
                fields['result'] = dict(content='\n'.join(texts) if texts else json.dumps(data.get('rawOutput'), ensure_ascii=False),
                                        is_error=data['status']=='failed', images=[], diffs=diffs)
                fields['streaming'] = False
            if tid in self.tools: self.patch(self.tools[tid], **fields)
            else:
                defaults = dict(tool_use_id=tid, name='', tool_kind='', input={}, status='pending', locations=[],
                                result=None, streaming=False)
                self.tools[tid] = self.add('tool', **(defaults | fields))
        elif kind=='plan':
            self.finish_stream()
            if self.plan: self.patch(self.plan, entries=update['entries'])
            else: self.plan = self.add('plan', entries=update['entries'])
        elif kind in ('user_message_chunk', 'available_commands_update', 'current_mode_update',
                      'config_option_update', 'session_info_update', 'usage_update'):
            self.finish_stream()
