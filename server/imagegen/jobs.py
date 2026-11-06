"""Persisted image jobs, background concurrency and restart recovery."""
import asyncio
import json
import os
import re
import shutil
import time

import httpx
from fastapi import HTTPException
from . import client


class ImageJobs:
    def __init__(self, core, config):
        self.core = core
        self.config = config
        self.root = core.paths.root / 'imagegen' / 'jobs'
        self.root.mkdir(parents=True, exist_ok=True)
        self.sem = asyncio.Semaphore(2)
        self.tasks = {}

    def path(self, jid):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', jid):
            raise HTTPException(404, 'not found')
        return self.root / jid

    def load(self, jid):
        try:
            return json.loads((self.path(jid) / 'job.json').read_text())
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, 'not found')

    def save(self, job):
        path = self.path(job['id']) / 'job.json'
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(job, ensure_ascii=False, separators=(',', ':')))
        tmp.replace(path)

    def emit(self, job):
        self.core.emit({'type': 'imagegen_changed', 'module': 'imagegen', 'id': job['id'], 'status': job['status']})

    def create(self, prompt, model, params, refs, mask):
        jid = time.strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(3).hex()
        directory = self.path(jid)
        directory.mkdir()
        job = {'id': jid, 'prompt': prompt, 'params': params, 'model': model, 'references': [],
               'status': 'running', 'error': None, 'images': [], 'created_at': time.time(),
               'finished_at': None, 'duration_ms': None}
        stored_refs = []
        for i, (_, raw, mime) in enumerate(refs):
            _, ext = client.sniff(raw)
            name = f'reference-{i + 1}{ext}'
            (directory / name).write_bytes(raw)
            job['references'].append(self.file(jid, name))
            stored_refs.append((name, raw, mime))
        stored_mask = None
        if mask:
            _, raw, mime = mask
            _, ext = client.sniff(raw)
            name = 'mask' + ext
            (directory / name).write_bytes(raw)
            job['mask'] = self.file(jid, name)
            stored_mask = (name, raw, mime)
        self.save(job)
        self.emit(job)
        task = asyncio.create_task(self.run(job, stored_refs, stored_mask))
        self.tasks[jid] = task
        task.add_done_callback(lambda t: self.tasks.pop(jid, None))
        return job

    def file(self, jid, name):
        return {'name': name, 'url': f'/api/imagegen/files/{jid}/{name}'}

    async def run(self, job, refs, mask):
        async with self.sem:
            try:
                config = self.config.data
                async with httpx.AsyncClient(timeout=config.timeout, transport=client.transport) as http:
                    body = await client.request_images(http, config, job, refs, mask)
                    images = []
                    for i, item in enumerate(body['data']):
                        raw = await client.decode(http, item)
                        kind = client.image_type(raw)
                        if kind:
                            mime, ext = kind
                        else:
                            fmt = job['params'].get('output_format', 'png')
                            mime, ext = 'image/' + fmt, '.' + ('jpg' if fmt == 'jpeg' else fmt)
                        name = f'image-{i + 1}{ext}'
                        (self.path(job['id']) / name).write_bytes(raw)
                        width, height = client.dimensions(raw, mime)
                        images.append(self.file(job['id'], name) | {'width': width, 'height': height, 'bytes': len(raw)})
                        if item.get('revised_prompt'):
                            job['revised_prompt'] = item['revised_prompt']
                job.update(status='done', images=images)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                job.update(status='error', error=str(exc))
            self.complete(job)

    def complete(self, job):
        job['finished_at'] = time.time()
        job['duration_ms'] = round((job['finished_at'] - job['created_at']) * 1000)
        self.save(job)
        self.emit(job)

    def retry(self, jid):
        old = self.load(jid)
        def read(ref):
            raw = (self.path(jid) / ref['name']).read_bytes()
            mime, _ = client.sniff(raw)
            return ref['name'], raw, mime
        refs = [read(ref) for ref in old['references']]
        mask = read(old['mask']) if old.get('mask') else None
        return self.create(old['prompt'], old['model'], old['params'], refs, mask)

    async def delete(self, jid):
        self.load(jid)
        task = self.tasks.pop(jid, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        shutil.rmtree(self.path(jid))
        self.emit({'id': jid, 'status': 'deleted'})

    async def startup(self):
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            try:
                job = self.load(path.name)
            except HTTPException:
                continue
            if job['status'] == 'running':
                job.update(status='error', error='Server restarted')
                self.complete(job)

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
