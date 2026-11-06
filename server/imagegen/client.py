"""OpenAI-compatible generations/edits requests and image decoding."""
import base64
import struct

import httpx
from fastapi import HTTPException

transport: httpx.AsyncBaseTransport | None = None
MAGICS = ((b'\x89PNG\r\n\x1a\n', 'image/png', '.png'),
          (b'\xff\xd8\xff', 'image/jpeg', '.jpg'),
          (b'GIF87a', 'image/gif', '.gif'), (b'GIF89a', 'image/gif', '.gif'),
          (b'RIFF', 'image/webp', '.webp'))
EDIT_FIELDS = ('size', 'quality', 'background', 'output_format', 'n')


class ApiFailure(Exception):
    """HTTP failure or empty image result: auto mode may try generations."""


def image_type(data):
    for magic, mime, ext in MAGICS:
        if data.startswith(magic) and (magic != b'RIFF' or data[8:12] == b'WEBP'):
            return mime, ext
    return None


def sniff(data):
    kind = image_type(data)
    if kind is None:
        raise HTTPException(415, 'unsupported image type')
    return kind


def dimensions(data, mime):
    if mime == 'image/png' and len(data) >= 24:
        return struct.unpack('>II', data[16:24])
    if mime == 'image/gif' and len(data) >= 10:
        return struct.unpack('<HH', data[6:10])
    if mime == 'image/webp':
        if data[12:16] == b'VP8X' and len(data) >= 30:
            return int.from_bytes(data[24:27], 'little') + 1, int.from_bytes(data[27:30], 'little') + 1
        if data[12:16] == b'VP8L' and len(data) >= 25:
            bits = int.from_bytes(data[21:25], 'little')
            return (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
        if data[12:16] == b'VP8 ' and len(data) >= 30:
            w, h = struct.unpack('<HH', data[26:30])
            return w & 0x3fff, h & 0x3fff
    if mime == 'image/jpeg':
        pos = 2
        while pos + 4 <= len(data) and data[pos] == 0xff:
            marker = data[pos + 1]
            if marker in (0xd8, 0xd9):
                pos += 2
                continue
            length = int.from_bytes(data[pos + 2:pos + 4], 'big')
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf) and pos + 9 <= len(data):
                h, w = struct.unpack('>HH', data[pos + 5:pos + 9])
                return w, h
            if length < 2:
                break
            pos += length + 2
    return None, None


def data_url(image):
    _, raw, mime = image
    return f'data:{mime};base64,{base64.b64encode(raw).decode()}'


def result(response):
    if response.status_code >= 400:
        raise ApiFailure(f'HTTP {response.status_code}: {response.text[:500]}')
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get('data'), list) or not body['data']:
        raise ApiFailure('response contained no images')
    return body


async def generate(client, config, job, refs, mask):
    payload = {'model': job['model'], 'prompt': job['prompt'], **job['params']}
    if refs:
        images = [data_url(ref) for ref in refs]
        payload['image'] = images[0] if len(images) == 1 else images
    if mask:
        payload['mask'] = data_url(mask)
    response = await client.post(config.api_base + '/images/generations', json=payload,
                                 headers={'Authorization': f'Bearer {config.api_key}'})
    return result(response)


async def edit(client, config, job, refs, mask):
    fields = {'model': job['model'], 'prompt': job['prompt']}
    fields.update({k: str(v) for k, v in job['params'].items() if k in EDIT_FIELDS})
    files = [('image' if len(refs) == 1 else 'image[]', ref) for ref in refs]
    if mask:
        files.append(('mask', mask))
    response = await client.post(config.api_base + '/images/edits', data=fields, files=files,
                                 headers={'Authorization': f'Bearer {config.api_key}'})
    return result(response)


async def request_images(client, config, job, refs, mask):
    if not refs or config.reference_mode == 'generations':
        return await generate(client, config, job, refs, mask)
    if config.reference_mode == 'edits':
        return await edit(client, config, job, refs, mask)
    try:
        return await edit(client, config, job, refs, mask)
    except ApiFailure:
        return await generate(client, config, job, refs, mask)


async def decode(client, item):
    if item.get('b64_json'):
        return base64.b64decode(item['b64_json'])
    url = item.get('url')
    if not url:
        raise ValueError('image has no data')
    if url.startswith('data:'):
        return base64.b64decode(url.partition(',')[2])
    response = await client.get(url)
    response.raise_for_status()
    return response.content


async def models(config):
    async with httpx.AsyncClient(timeout=15, transport=transport) as client:
        response = await client.get(config.api_base + '/models', headers={'Authorization': f'Bearer {config.api_key}'})
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get('data'), list):
        raise ValueError('Invalid models response')
    if any(not isinstance(m, dict) or not isinstance(m.get('id'), str) for m in body['data']):
        raise ValueError('Invalid models response')
    return sorted(set(m['id'] for m in body['data']))
