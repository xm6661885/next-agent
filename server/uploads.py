"""Attachment storage and SDK content construction."""
import base64
import mimetypes
import re
import shutil
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from .paths import atomic_write

IMAGE_MIMES = {'image/png','image/jpeg','image/gif','image/webp'}

def safe_name(name):
    return re.sub(r'[^A-Za-z0-9._-]', '_', Path(name).name)[:80] or 'file'

class UploadService:
    def __init__(self, paths, index, manager=None):
        self.paths, self.index, self.manager = paths, index, manager

    def folder(self, sid):
        """Uploads live in the session agent's working directory, so Claude can work with them in place."""
        session = self.index.sessions.get(sid)
        if self.manager and session:
            try:
                cwd = Path(self.manager.session_agent(session).cwd).expanduser()
                if cwd.is_dir(): return cwd / 'uploads'
            except Exception:
                pass
        return self.paths.uploads / sid

    def remove_session(self, sid):
        """Delete a session's uploaded files and index records."""
        for fid, record in list(self.index.uploads.items()):
            if record['session_id'] == sid:
                Path(record['path']).unlink(missing_ok=True)
                del self.index.uploads[fid]
        shutil.rmtree(self.paths.uploads / sid, ignore_errors=True)

    async def save(self, sid, file):
        content = await file.read(50 * 1024 * 1024 + 1)
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(413, 'File is too large')
        fid = uuid4().hex
        name = safe_name(file.filename or 'file')
        path = self.folder(sid) / f'{fid[:8]}-{name}'
        atomic_write(path, content)
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        record = dict(id=fid, name=name, mime=mime, size=len(content), path=str(path.resolve()),
                      url=f'/api/uploads/{sid}/{fid}', is_image=mime in IMAGE_MIMES)
        self.index.uploads[fid] = {'session_id': sid, **record}
        self.index.save()
        return record

    def get(self, sid, fid):
        record = self.index.uploads.get(fid)
        if not record or record['session_id'] != sid:
            raise HTTPException(404, 'Upload not found')
        return record

    def build_content(self, text, attachments):
        blocks = []
        if text:
            blocks.append({'type':'text','text':text})
        for a in attachments:
            if a['mime'] in IMAGE_MIMES and a['size'] <= 3750000:
                blocks.append({'type':'image','source':{'type':'base64','media_type':a['mime'],
                         'data':base64.b64encode(Path(a['path']).read_bytes()).decode()}})
        if attachments:
            blocks.append({'type':'text','text':'\n'.join('The user sent a file: '+a['path'] for a in attachments)})
        return blocks
