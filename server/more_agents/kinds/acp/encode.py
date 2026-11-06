import base64
from pathlib import Path
from ...store import IMAGE_MIMES


def prompt(text, attachments, capabilities):
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
