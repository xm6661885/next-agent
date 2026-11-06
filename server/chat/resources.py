"""Assistant text files and durable memories."""
import json
import shutil
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, Field
from ..paths import atomic_write
from .config import now


class FileName(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemoryText(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


def file_name(name):
    return Path(name).name.replace('\x00', '')[:200] or 'file'


def text_content(content):
    try: text = content.decode('utf-8')
    except UnicodeDecodeError as exc: raise HTTPException(415, 'File must be UTF-8 text') from exc
    if '\x00' in text: raise HTTPException(415, 'File must not contain NUL')
    return text


class Resources:
    def __init__(self, root):
        self.root = root

    def file_dir(self, aid):
        return self.root / 'assistants' / aid / 'files'

    def files(self, aid):
        path = self.file_dir(aid) / 'index.json'
        return json.loads(path.read_text()) if path.exists() else []

    def save_files(self, aid, records):
        atomic_write(self.file_dir(aid) / 'index.json', json.dumps(records, ensure_ascii=False))

    def file(self, aid, fid):
        record = next((r for r in self.files(aid) if r['id']==fid), None)
        if record is None: raise HTTPException(404, 'File not found')
        return record

    async def upload(self, aid, uploads):
        added, contents = [], []
        for upload in uploads:
            content = await upload.read(2*1024*1024+1)
            if len(content)>2*1024*1024: raise HTTPException(413, 'File is too large')
            text = text_content(content)
            added.append(dict(id=uuid4().hex, name=file_name(upload.filename or 'file'), size=len(content),
                              chars=len(text), lines=len(text.splitlines()), created_at=now()))
            contents.append(content)
        records = self.files(aid)
        if len(records)+len(uploads)>100: raise HTTPException(409, 'At most 100 files per assistant')
        for record, content in zip(added, contents): atomic_write(self.file_dir(aid) / record['id'], content)
        self.save_files(aid, records+added)
        return added

    def rename(self, aid, fid, name):
        record = self.file(aid, fid)
        record['name'] = file_name(name)
        self.save_files(aid, [record if r['id']==fid else r for r in self.files(aid)])
        return record

    def delete_file(self, aid, fid):
        self.file(aid, fid)
        self.save_files(aid, [r for r in self.files(aid) if r['id']!=fid])
        (self.file_dir(aid) / fid).unlink()

    def memory_path(self, aid):
        return self.root / 'memory' / (aid+'.json')

    def memories(self, aid):
        path = self.memory_path(aid)
        return json.loads(path.read_text()) if path.exists() else []

    def save_memories(self, aid, records):
        atomic_write(self.memory_path(aid), json.dumps(records, ensure_ascii=False))

    def add_memory(self, aid, text, source):
        records = self.memories(aid)
        if len(records)>=200: raise HTTPException(409, 'At most 200 memories per assistant')
        record = dict(id=uuid4().hex, text=text, created_at=now(), updated_at=now(), source=source)
        self.save_memories(aid, records+[record])
        return record

    def update_memory(self, aid, mid, text):
        records = self.memories(aid)
        record = next((r for r in records if r['id']==mid), None)
        if record is None: raise HTTPException(404, 'Memory not found')
        record.update(text=text, updated_at=now())
        self.save_memories(aid, records)
        return record

    def delete_memory(self, aid, mid):
        records = self.memories(aid)
        if not any(r['id']==mid for r in records): raise HTTPException(404, 'Memory not found')
        self.save_memories(aid, [r for r in records if r['id']!=mid])

    def delete_assistant(self, aid):
        shutil.rmtree(self.root / 'assistants' / aid, ignore_errors=True)
        self.memory_path(aid).unlink(missing_ok=True)
