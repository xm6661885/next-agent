"""Recording metadata, transcript views and per-recording locks."""
import asyncio
import json
import os
import time
from fastapi import HTTPException

class AsrStore:

    def __init__(self, root):
        self.recordings = root / 'asr' / 'recordings'
        self.recordings.mkdir(parents=True, exist_ok=True)
        self.locks = {}

    def lock(self, rid):
        return self.locks.setdefault(rid, asyncio.Lock())

    def rec_dir(self, rid):
        if not rid or '/' in rid or '..' in rid or rid.startswith('.'):
            raise KeyError(rid)
        return self.recordings / rid

    def load(self, rid):
        try:
            return json.loads((self.rec_dir(rid) / 'meta.json').read_text())
        except (FileNotFoundError, ValueError):
            raise KeyError(rid)

    def create(self, title, source):
        rid = time.strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(2).hex()
        while self.rec_dir(rid).exists():
            rid = time.strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(2).hex()
        meta = {'id': rid, 'title': title, 'source': source, 'created_at': time.time(), 'duration': 0.0,
                'status': 'recording' if source == 'record' else 'processing', 'error': None, 'size': 0,
                'segments': [], 'text': None, 'starred': False, 'progress': None}
        self.save(meta)
        return meta

    def save(self, meta):
        path = self.rec_dir(meta['id']) / 'meta.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(meta, ensure_ascii=False, separators=(',', ':')))
        os.replace(tmp, path)

    def joined(self, m):
        return '\n'.join((s['text'] for s in sorted(m['segments'], key=lambda s: s['seq']) if s.get('text')))

    def full_text(self, m):
        return m['text'] if m.get('text') is not None else self.joined(m)

    def public(self, m):
        out = {k: v for k, v in m.items() if k != 'pending'}
        out['edited'] = m.get('text') is not None
        out['text'] = self.full_text(m)
        return out

    def summary(self, m):
        fields = ('id', 'title', 'source', 'created_at', 'duration', 'status', 'size', 'starred', 'error', 'progress')
        return {k: m.get(k) for k in fields} | {'preview': self.full_text(m)[:120]}

    def upsert(self, m, seg):
        m['segments'] = [s for s in m['segments'] if s['seq'] != seg['seq']] + [seg]
        m['segments'].sort(key=lambda s: s['seq'])

    def get(self, rid):
        try:
            return self.load(rid)
        except KeyError:
            raise HTTPException(404, 'not found')

    def tail(self, m, before=None):
        vals = [s for s in m['segments'] if s.get('text') and (before is None or s['seq'] < before)]
        return vals[-1]['text'][-200:] if vals else ''
