"""Chat sessions, transcripts and images."""
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from ..paths import atomic_write
from .config import now
from .resources import text_content, file_name

IMAGE_MIMES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}


def page(items, before=None, limit=200):
    end = next((i for i, item in enumerate(items) if item['id']==before), len(items)) if before else len(items)
    start = max(0, end-limit)
    return {'items': items[start:end], 'has_more': start>0}


class ChatStore:
    def __init__(self, root):
        self.root = root / 'chat'
        self.path = self.root / 'sessions.json'
        self.avatars = self.root / 'avatars'
        self.sessions = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not self.path.exists(): self.save()

    def save(self):
        atomic_write(self.path, json.dumps(self.sessions, ensure_ascii=False, indent=2))

    def create(self, aid, title, mcp):
        sid = str(uuid4())
        self.sessions[sid] = dict(id=sid, assistant_id=aid, title=title, preview='', created_at=now(), updated_at=now(),
                                 overrides={'model': None, 'effort': None}, mcp=mcp, usage={'input': 0, 'output': 0}, unread=False)
        self.save()
        return self.sessions[sid]

    def update(self, sid, **values):
        self.sessions[sid].update(values, updated_at=now())
        self.save()

    def load_items(self, sid):
        path = self.root / 'messages' / f'{sid}.jsonl'
        items = [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []
        for item in items:
            if item['kind']=='user': item.setdefault('group', item['id'])
        return items

    def save_items(self, sid, items):
        atomic_write(self.root / 'messages' / f'{sid}.jsonl', ''.join(json.dumps(i, ensure_ascii=False)+'\n' for i in items))

    def load_forks(self, sid):
        path = self.root / 'messages' / f'{sid}.forks.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def save_forks(self, sid, forks):
        atomic_write(self.root / 'messages' / f'{sid}.forks.json', json.dumps(forks, ensure_ascii=False))

    def delete(self, sid):
        del self.sessions[sid]
        self.save()
        (self.root / 'messages' / f'{sid}.jsonl').unlink(missing_ok=True)
        (self.root / 'messages' / f'{sid}.forks.json').unlink(missing_ok=True)
        shutil.rmtree(self.root / 'uploads' / sid, ignore_errors=True)

    def upload_index(self, sid):
        path = self.root / 'uploads' / sid / 'index.json'
        return json.loads(path.read_text()) if path.exists() else {}

    async def upload(self, sid, file, files_enabled=True):
        image = file.content_type in IMAGE_MIMES
        if not image and not files_enabled: raise HTTPException(415, 'Text files are disabled')
        cap = (10 if image else 2)*1024*1024
        content = await file.read(cap+1)
        if len(content)>cap: raise HTTPException(413, 'File is too large')
        text = None if image else text_content(content)
        fid = uuid4().hex
        if image: name = re.sub(r'[^A-Za-z0-9._-]', '_', Path(file.filename or 'image').name)[:80] or 'image'
        else: name = file_name(file.filename or 'file')
        path = self.root / 'uploads' / sid / fid
        atomic_write(path, content)
        record = dict(id=fid, name=name, mime=file.content_type, size=len(content), path=str(path.resolve()),
                      url=f'/api/chat/uploads/{sid}/{fid}', is_image=image)
        if not image: record.update(is_text=True, mime='text/plain', chars=len(text), lines=len(text.splitlines()))
        index = self.upload_index(sid)
        index[fid] = record
        atomic_write(path.parent / 'index.json', json.dumps(index))
        return record

    def attachment(self, sid, fid):
        record = self.upload_index(sid).get(fid)
        if not record: raise HTTPException(404, 'Upload not found')
        return record
