"""Claude Code memory on this machine: the global CLAUDE.md and every project's auto-memory folder."""
import json
import os
import re
from pathlib import Path
from fastapi import HTTPException
from .paths import atomic_write

FILE_RE = re.compile(r'^(CLAUDE\.md|projects/[^/]+/memory/[^/]+\.md)$')

def root() -> Path:
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')

def front(text: str) -> dict:
    """Read name/description/type from simple YAML frontmatter."""
    m = re.match(r'^---\n(.*?)\n---', text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.strip().partition(':')
        if k in ('name', 'description', 'type') and v.strip(): out['title' if k == 'name' else k] = v.strip().strip('"\'')
    return out

def project_cwd(pdir: Path) -> str | None:
    """The project folder, from the cwd field of any transcript in it."""
    for f in sorted(pdir.glob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
        try:
            with f.open() as s:
                for _, line in zip(range(20), s):
                    cwd = json.loads(line).get('cwd')
                    if cwd: return cwd
        except (OSError, ValueError): continue
    return None

def stat(p: Path, rel: str) -> dict:
    st = p.stat()
    return {'path': rel, 'name': p.name, 'size': st.st_size, 'mtime': st.st_mtime}

def listing() -> dict:
    r = root()
    g = r / 'CLAUDE.md'
    projects = []
    for mdir in sorted((r / 'projects').glob('*/memory')):
        files = []
        for f in sorted(mdir.glob('*.md')):
            try: files.append({**stat(f, f'projects/{mdir.parent.name}/memory/{f.name}'), **front(f.read_text(errors='replace')[:2000])})
            except OSError: continue
        if not files: continue
        files.sort(key=lambda x: (x['name'] != 'MEMORY.md', x['name']))
        projects.append({'id': mdir.parent.name, 'cwd': project_cwd(mdir.parent), 'files': files,
                         'mtime': max(x['mtime'] for x in files)})
    projects.sort(key=lambda x: x['mtime'], reverse=True)
    return {'root': str(r), 'global': stat(g, 'CLAUDE.md') if g.exists() else None, 'projects': projects}

def resolve(rel: str) -> Path:
    if not FILE_RE.match(rel or '') or '..' in rel.split('/'): raise HTTPException(400, 'Not a memory file')
    return root() / rel

def read(rel: str) -> dict:
    p = resolve(rel)
    if not p.is_file(): raise HTTPException(404, 'File not found')
    return {**stat(p, rel), 'content': p.read_text(errors='replace')}

def write(rel: str, content: str, create: bool = False) -> dict:
    p = resolve(rel)
    if create and p.exists(): raise HTTPException(409, 'File already exists')
    if not create and not p.parent.is_dir(): raise HTTPException(404, 'Project not found')
    atomic_write(p, content)
    return {**stat(p, rel), 'content': content}

def delete(rel: str):
    p = resolve(rel)
    if not p.is_file(): raise HTTPException(404, 'File not found')
    p.unlink()
