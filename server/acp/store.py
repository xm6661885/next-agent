"""ACP session, transcript and attachment storage."""
import base64
import json
import mimetypes
import re
import shutil
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from ..paths import atomic_write
from .config import now

IMAGE_MIMES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}


def page(items, before=None, limit=200):
    end = next((i for i, item in enumerate(items) if item['id']==before), len(items)) if before else len(items)
    start = max(0, end-limit)
    return {'items': items[start:end], 'has_more': start>0}


class AcpStore:
    def __init__(self, root):
        self.root = root / 'acp'
        self.path = self.root / 'sessions.json'
        self.avatars = self.root / 'avatars'
        self.sessions = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not self.path.exists(): self.save()

    def save(self):
        atomic_write(self.path, json.dumps(self.sessions, ensure_ascii=False, indent=2))

    def create(self, agent_id, title='', origin='ui', parent=None):
        sid = str(uuid4())
        self.sessions[sid] = dict(id=sid, agent_id=agent_id, remote_id=None, title=title, preview='',
                                 created_at=now(), updated_at=now(), turns=0, unread=False, origin=origin,
                                 parent=parent, config_options=[], modes=None, commands=[])
        self.save()
        return self.sessions[sid]

    def update(self, sid, **values):
        self.sessions[sid].update(values, updated_at=now())
        self.save()

    def load_items(self, sid):
        path = self.root / 'items' / f'{sid}.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []

    def save_items(self, sid, items):
        atomic_write(self.root / 'items' / f'{sid}.jsonl', ''.join(json.dumps(i, ensure_ascii=False)+'\n' for i in items))

    def delete(self, sid):
        del self.sessions[sid]
        self.save()
        (self.root / 'items' / f'{sid}.jsonl').unlink(missing_ok=True)
        shutil.rmtree(self.root / 'uploads' / sid, ignore_errors=True)

    def upload_index(self, sid):
        path = self.root / 'uploads' / sid / 'index.json'
        return json.loads(path.read_text()) if path.exists() else {}

    async def upload(self, sid, file):
        content = await file.read(50*1024*1024+1)
        if len(content)>50*1024*1024: raise HTTPException(413, 'File is too large')
        fid = uuid4().hex
        name = re.sub(r'[^A-Za-z0-9._-]', '_', Path(file.filename or 'file').name)[:80] or 'file'
        path = self.root / 'uploads' / sid / fid
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        atomic_write(path, content)
        record = dict(id=fid, name=name, mime=mime, size=len(content), path=str(path.resolve()),
                      url=f'/api/acp/uploads/{sid}/{fid}', is_image=mime in IMAGE_MIMES)
        index = self.upload_index(sid)
        index[fid] = record
        atomic_write(path.parent / 'index.json', json.dumps(index))
        return record

    def attachment(self, sid, fid):
        record = self.upload_index(sid).get(fid)
        if not record: raise HTTPException(404, 'Upload not found')
        return record

    def prompt(self, text, attachments, capabilities):
        blocks = [{'type': 'text', 'text': text}] if text else []
        for attachment in attachments:
            path, mime = Path(attachment['path']), attachment['mime']
            if mime in IMAGE_MIMES and attachment['size']<=3750000 and capabilities.get('image'):
                blocks.append({'type': 'image', 'mimeType': mime, 'data': base64.b64encode(path.read_bytes()).decode()})
                continue
            if mime not in IMAGE_MIMES and attachment['size']<=200000 and capabilities.get('embeddedContext'):
                try: content = path.read_text(encoding='utf-8')
                except UnicodeDecodeError: pass
                else:
                    if '\x00' not in content:
                        blocks.append({'type': 'resource', 'resource': {'uri': path.as_uri(), 'mimeType': mime, 'text': content}})
                        continue
            blocks.append({'type': 'text', 'text': 'The user sent a file: '+attachment['name']})
        return blocks
