import json


class AcpItems:
    def __init__(self, items): self.items = items

    def consume(self, update):
        b = self.items
        kind = update.get('sessionUpdate')
        if kind in ('agent_message_chunk', 'agent_thought_chunk'):
            content = update['content']
            if content.get('type')=='text': text = content['text']
            elif content.get('type')=='image': text = f"![](data:{content['mimeType']};base64,{content['data']})"
            else:
                b.finish_stream()
                return
            item_kind = 'text' if kind=='agent_message_chunk' else 'thinking'
            if kind=='agent_message_chunk' and content.get('type')=='text': b.turn_text.append(text)
            if not b.stream or b.stream['kind']!=item_kind:
                b.finish_stream()
                b.stream = b.add(item_kind, text=text, streaming=True)
            else:
                b.stream['text'] += text
                b.emit({'type': 'delta', 'id': b.stream['id'], 'field': 'text', 'text': text})
            if item_kind=='text': b.last_text = b.stream['text']
        elif kind in ('tool_call', 'tool_call_update'):
            b.finish_stream()
            tid = update['toolCallId']
            data = b.tool_data.setdefault(tid, {})
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
            if tid in b.tools: b.patch(b.tools[tid], **fields)
            else:
                defaults = dict(tool_use_id=tid, name='', tool_kind='other', input={}, status='pending', locations=[],
                                result=None, streaming=False)
                b.tools[tid] = b.add('tool', **(defaults | fields))
        elif kind=='plan':
            b.finish_stream()
            if b.plan: b.patch(b.plan, entries=update['entries'])
            else: b.plan = b.add('plan', entries=update['entries'])
        elif kind in ('user_message_chunk', 'available_commands_update', 'current_mode_update',
                      'config_option_update', 'session_info_update', 'usage_update'):
            b.finish_stream()
