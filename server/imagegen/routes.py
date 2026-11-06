"""Authenticated image settings, job and file routes."""
import mimetypes
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from . import client

MAX_REF = 20 * 1024 * 1024


class SettingsIn(BaseModel):
    api_base: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    default_model: str | None = None
    reference_mode: str | None = None
    timeout: int | None = None


async def read_image(image, label):
    data = await image.read(MAX_REF + 1)
    if len(data) > MAX_REF:
        raise HTTPException(413, f'{label} is too large')
    mime, ext = client.sniff(data)
    return Path(image.filename or label + ext).name, data, mime


def router(core, jobs):
    routes = APIRouter(prefix='/api/imagegen', dependencies=[Depends(core.require)])
    config = jobs.config

    @routes.get('/settings')
    async def settings_get():
        return config.data.model_dump()

    @routes.patch('/settings')
    async def settings_patch(body: SettingsIn):
        values = body.model_dump(exclude_unset=True, exclude_none=True)
        try:
            new = config.model.model_validate(config.data.model_dump() | values)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        for key in values:
            config.doc[key] = getattr(new, key)
        config.save()
        return new.model_dump()

    @routes.post('/settings/models')
    async def settings_models():
        try:
            return {'models': await client.models(config.data)}
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, str(exc)) from exc

    @routes.post('/settings/test')
    async def settings_test():
        try:
            models = await client.models(config.data)
        except (httpx.HTTPError, ValueError) as exc:
            return {'ok': False, 'detail': str(exc), 'models': []}
        return {'ok': True, 'detail': f'Connected, {len(models)} models', 'models': models}

    @routes.post('/jobs')
    async def job_create(prompt: str = Form(...), model: str | None = Form(None), size: str | None = Form(None),
                         quality: str | None = Form(None), n: int = Form(1), background: str | None = Form(None),
                         output_format: str | None = Form(None), output_compression: int | None = Form(None),
                         moderation: str | None = Form(None), images: list[UploadFile] = File(default=[], alias='images[]'),
                         mask: UploadFile | None = File(None)):
        if not prompt.strip():
            raise HTTPException(422, 'prompt is required')
        if not 1 <= n <= 4:
            raise HTTPException(422, 'n must be between 1 and 4')
        if size and size != 'auto':
            match = re.fullmatch(r'(\d+)x(\d+)', size)
            if not match or int(match[1]) < 1 or int(match[2]) < 1:
                raise HTTPException(422, 'invalid size')
        choices = {'quality': (quality, ('auto', 'low', 'medium', 'high')),
                   'background': (background, ('auto', 'opaque', 'transparent')),
                   'output_format': (output_format, ('png', 'jpeg', 'webp')),
                   'moderation': (moderation, ('auto', 'low'))}
        for key, (value, allowed) in choices.items():
            if value is not None and value not in allowed:
                raise HTTPException(422, f'invalid {key}')
        if output_compression is not None and (not 0 <= output_compression <= 100 or output_format not in ('jpeg', 'webp')):
            raise HTTPException(422, 'invalid output_compression')
        if len(images) > 8:
            raise HTTPException(422, 'at most 8 reference images')
        if mask and not images:
            raise HTTPException(422, 'mask requires a reference image')
        refs = [await read_image(image, 'reference image') for image in images]
        maskdata = await read_image(mask, 'mask') if mask else None
        params = {k: v for k, v in {'size': size, 'quality': quality, 'n': n, 'background': background,
                  'output_format': output_format, 'output_compression': output_compression, 'moderation': moderation}.items()
                  if v is not None}
        return jobs.create(prompt, model or config.data.default_model, params, refs, maskdata)

    @routes.get('/jobs')
    async def jobs_list(before: str = '', limit: int = 50):
        items = []
        for path in sorted(jobs.root.iterdir(), key=lambda p: p.name, reverse=True):
            if not path.is_dir() or (before and path.name >= before):
                continue
            try:
                items.append(jobs.load(path.name))
            except HTTPException:
                continue
            if len(items) >= max(1, min(limit, 200)):
                break
        return items

    @routes.get('/jobs/{jid}')
    async def job_get(jid: str):
        return jobs.load(jid)

    @routes.delete('/jobs/{jid}')
    async def job_delete(jid: str):
        await jobs.delete(jid)
        return {'ok': True}

    @routes.post('/jobs/{jid}/retry')
    async def job_retry(jid: str):
        return jobs.retry(jid)

    @routes.get('/files/{jid}/{name}')
    async def file_get(jid: str, name: str):
        job = jobs.load(jid)
        allowed = [f['name'] for f in job['references'] + job['images']]
        if job.get('mask'):
            allowed.append(job['mask']['name'])
        if name not in allowed:
            raise HTTPException(404, 'not found')
        path = jobs.path(jid) / name
        if not path.is_file():
            raise HTTPException(404, 'not found')
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        return FileResponse(path, media_type=mime, content_disposition_type='inline', filename=name)

    return routes
