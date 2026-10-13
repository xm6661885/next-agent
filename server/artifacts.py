"""File references from conversation items."""
import mimetypes
import os
import re
from urllib.parse import quote, unquote

FILE_URL = re.compile(r'file://(/[^\s)"\'<>\]]+)')
EDIT_TOOLS = {'Edit','MultiEdit','NotebookEdit'}

def references(items):
    for entry in items:
        kind = entry.get('kind')
        if kind == 'text':
            for match in FILE_URL.findall(entry.get('text','')):
                yield os.path.normpath(unquote(match)), 'link', entry.get('ts',''), None
        elif kind == 'tool' and entry.get('result') is not None and not entry['result'].get('is_error'):
            name = entry.get('name')
            if name == 'Write' or name in EDIT_TOOLS:
                args = entry.get('input') or {}
                path = args.get('file_path') or args.get('notebook_path')
                if isinstance(path,str) and path:
                    yield os.path.normpath(path), 'write' if name == 'Write' else 'edit', entry.get('ts',''), None
        elif kind == 'user':
            for attachment in entry.get('attachments') or []:
                path = attachment.get('path')
                if isinstance(path,str) and path:
                    yield os.path.normpath(path), 'upload', entry.get('ts',''), attachment.get('url') or ''

def shared_refs(items):
    return {path for path, source, _, _ in references(items) if source in ('link','write','edit') and os.path.isabs(path)}

def listing(items,sid):
    found = {}
    for path, source, ts, upload_url in references(items):
        if not os.path.isabs(path): continue
        file_url=f'/api/sessions/{sid}/files?path={quote(path,safe="")}'
        if path not in found:
            mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            exists = os.path.isfile(path)
            found[path] = {'path':path,'name':os.path.basename(path),'mime':mime,
                           'is_image':mime.startswith('image/') and mime!='image/svg+xml',
                           'exists':exists,'size':os.path.getsize(path) if exists else None,
                           'sources':[],'first_ts':ts,'last_ts':ts,
                           'url':upload_url if source == 'upload' else file_url}
        artifact = found[path]
        if source not in artifact['sources']: artifact['sources'].append(source)
        artifact['first_ts'] = min(artifact['first_ts'],ts)
        artifact['last_ts'] = max(artifact['last_ts'],ts)
        if source == 'upload' and upload_url: artifact['url'] = upload_url
        elif source != 'upload' and not artifact['url']: artifact['url'] = file_url
    return sorted(found.values(),key=lambda a:a['last_ts'],reverse=True)
