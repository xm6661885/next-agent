"""Codex notifications -> shared transcript items; completed items are authoritative."""

def result(content='', error=False, **fields):
    return dict(content=content, is_error=error, images=[], diffs=[], **fields)

class CodexItems:
    def __init__(self, items):
        self.items = items
        self.begin()

    def begin(self):
        self.by_id, self.reasoning = {}, {}
        self.plan = None

    def text_result(self):
        texts = [i for i in self.by_id.values() if i['kind'] == 'text']
        self.items.turn_text = [i['text'] for i in texts]
        self.items.last_text = texts[-1]['text'] if texts else ''

    def upsert(self, native, done):
        typ, iid = native['type'], native['id']
        if typ == 'userMessage': return
        values = dict(streaming=not done)
        status = {'inProgress': 'in_progress', 'completed': 'completed', 'failed': 'failed', 'declined': 'failed'}.get(native.get('status'), 'completed' if done else 'in_progress')
        if typ == 'agentMessage':
            kind = 'text'
            values.update(text=native['text'], phase={'commentary':'commentary','final_answer':'final'}.get(native.get('phase')))
        elif typ == 'reasoning':
            kind = 'thinking'
            values['text'] = '\n'.join(native.get('summary') or native.get('content') or [])
        else:
            kind = 'tool'
            values.update(tool_use_id=iid, name=typ, tool_kind={'commandExecution':'execute','fileChange':'edit','mcpToolCall':'mcp','webSearch':'search'}.get(typ, 'other'),
                          input=native, status=status, locations=[], result=None)
            if typ == 'commandExecution':
                output = native.get('aggregatedOutput') or ''
                values.update(command=native['command'], cwd=native['cwd'], output=output, exit_code=native.get('exitCode'), duration_ms=native.get('durationMs'),
                              input={'command': native['command'], 'cwd': native['cwd']}, result=result(output, status=='failed') if done else None)
            elif typ == 'fileChange':
                changes = [dict(path=c['path'], kind=c['kind']['type'], move_path=c['kind'].get('move_path'), diff=c['diff']) for c in native['changes']]
                values.update(changes=changes, locations=[{'path': c['path']} for c in changes], result=result('\n'.join(c['diff'] for c in changes), status=='failed') if done else None)
            elif typ == 'mcpToolCall':
                raw = native.get('result')
                values.update(server=native['server'], tool=native['tool'], input=native['arguments'], raw=raw,
                              result=result('\n'.join(c['text'] for c in (raw or {}).get('content', []) if c.get('type')=='text'),
                                            status=='failed' or bool((raw or {}).get('isError'))) if done else None)
            elif typ == 'webSearch':
                action = native.get('action') or {}
                values.update(tool_kind='fetch' if action.get('type')=='openPage' else 'search', query=native.get('query',''), url=action.get('url'))
        existing = self.by_id.get(iid)
        if existing: self.items.patch(existing, **values)
        else: self.by_id[iid] = self.items.add(kind, **values)
        if typ == 'agentMessage': self.text_result()

    def consume(self, method, p):
        if method in ('item/started', 'item/completed'): self.upsert(p['item'], method=='item/completed')
        elif method == 'item/agentMessage/delta':
            item = self.by_id.get(p['itemId'])
            if item is None:
                self.upsert(dict(type='agentMessage', id=p['itemId'], text=''), False)
                item = self.by_id[p['itemId']]
            self.items.delta(item, 'text', p['delta']); self.text_result()
        elif method in ('item/reasoning/summaryTextDelta', 'item/reasoning/textDelta'):
            iid = p['itemId']
            if iid not in self.by_id: self.upsert(dict(type='reasoning', id=iid), False)
            parts = self.reasoning.setdefault(iid, {})
            field = 'summary' if 'summaryText' in method else 'content'
            index = p['summaryIndex'] if field=='summary' else p['contentIndex']
            parts[(field, index)] = parts.get((field, index), '')+p['delta']
            selected = 'summary' if any(k[0]=='summary' for k in parts) else 'content'
            self.items.patch(self.by_id[iid], text='\n'.join(parts[k] for k in sorted(parts) if k[0]==selected))
        elif method == 'item/commandExecution/outputDelta': self.items.delta(self.by_id[p['itemId']], 'output', p['delta'])
        elif method == 'item/fileChange/patchUpdated':
            item = self.by_id[p['itemId']]
            self.items.patch(item, changes=[dict(path=c['path'], kind=c['kind']['type'], move_path=c['kind'].get('move_path'), diff=c['diff']) for c in p['changes']])
        elif method == 'turn/plan/updated':
            fields = dict(entries=[dict(content=e['step'], status={'inProgress':'in_progress'}.get(e['status'], e['status'])) for e in p['plan']], explanation=p.get('explanation'))
            if self.plan: self.items.patch(self.plan, **fields)
            else: self.plan = self.items.add('plan', **fields)
